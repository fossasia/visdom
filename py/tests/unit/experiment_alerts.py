#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for metric alert rules: the grammar, the fold, and the record.

A rule is three separable things, and they are tested separately here. The
*grammar* is what turns ``"> 2.0"`` into an operator and a number, and is the
only place user text is read. The *fold* is what decides whether an
observation fires a rule, and is a pure function of the rule's own state --
never of the metric history, which is the property that lets it run on the
event loop beside the append. The *record* is where rules live, which is the
experiment, so that a restart finds the streak it left off at.

The store tests assert the fourth thing, which is the one a reader is most
likely to doubt: that evaluating a rule reads no environment. A rule is
evaluated inside the one read-append-write ``log_metrics`` already makes, so
the datastore handed to it here raises on every call it could make.
"""

import math

import pytest

from visdom.data_model.base import DataStore
from visdom.experiments import ExperimentStore
from visdom.experiments.alerts import (
    ACTION_TOAST,
    Alert,
    AlertEvent,
    build_alert,
    condition_name,
    DEFAULT_PATIENCE,
    describe,
    evaluate,
    GOAL_MAX,
    MAX_ALERTS_PER_ENV,
    observe,
    parse_condition,
)
from visdom.experiments.models import Experiment, STATUS_FINISHED

pytestmark = pytest.mark.unit


class Record:
    """The least an ``evaluate`` caller can be: something holding rules."""

    def __init__(self, *alerts):
        self.alerts = list(alerts)


def _refuse(name):
    """A ``DataStore`` method that fails rather than answering."""

    def method(self, *args, **kwargs):
        raise AssertionError("the alert path reached storage: {0}".format(name))

    method.__name__ = name
    return method


class ExplodingStore(DataStore):
    """A ``DataStore`` whose every operation fails.

    The alert fold runs where the server already has the environment in hand.
    Anything that went looking for it again would be reading a file on the
    event loop, which is the one thing this feature must not do -- and a
    store that raises turns that from a performance regression nobody
    measures into a failed test.
    """


# Filled in rather than spelled out: thirteen abstract methods are thirteen
# places to forget the refusal, and the point is that *nothing* answers.
for _abstract in sorted(DataStore.__abstractmethods__):
    setattr(ExplodingStore, _abstract, _refuse(_abstract))
ExplodingStore.__abstractmethods__ = frozenset()


def live_store(env):
    """A store over one in-memory env, with no storage behind it at all.

    The same shape the server builds for every metadata write: the env is
    served from memory and the write is somebody else's job.
    """
    written = []
    store = ExperimentStore(
        ExplodingStore(),
        env_provider=lambda _eid, _env=env: _env,
        persist=lambda eid, env_data: written.append(eid),
    )
    return store, written


# ------------------------------------------------------------------ grammar --


class TestParseCondition:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("> 2.0", (">", 2.0)),
            (">2.0", (">", 2.0)),
            ("  >   2  ", (">", 2.0)),
            ("< 0.5", ("<", 0.5)),
            ("== 0", ("==", 0.0)),
            ("> -1e-3", (">", -0.001)),
            ("nan", ("nan", None)),
            ("stalled", ("stalled", None)),
        ],
    )
    def test_accepted_spellings(self, text, expected):
        assert parse_condition(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            ">",
            "> ",
            "> abc",
            ">= 2.0",
            "<= 2.0",
            "!= 2.0",
            "= 2.0",
            "val_loss > 2.0",
            "2.0 >",
            "nan 2.0",
            "stalled 10",
            "__import__('os')",
        ],
    )
    def test_refused_spellings(self, text):
        with pytest.raises(ValueError):
            parse_condition(text)

    @pytest.mark.parametrize("text", [">= 2.0", "<= 2.0", "!= 2.0"])
    def test_a_rejected_operator_is_named_in_the_message(self, text):
        # '>= 2.0' matches the '>' of a real condition first, which without
        # this would report '= 2.0' as not being a number and point its
        # author at the operand rather than at the operator.
        with pytest.raises(ValueError, match=text[:2]):
            parse_condition(text)

    def test_a_lone_equals_is_pointed_at_the_condition_that_exists(self):
        with pytest.raises(ValueError, match="== <number>"):
            parse_condition("= 2.0")

    @pytest.mark.parametrize("text", ["> inf", "> nan", "< -inf"])
    def test_a_threshold_has_to_be_finite(self, text):
        # float('nan') parses, and a rule comparing against it could never
        # match: every comparison with NaN is false. The 'nan' condition is
        # what that caller wanted.
        with pytest.raises(ValueError):
            parse_condition(text)

    @pytest.mark.parametrize("text", [None, 2.0, [">", 2.0], True])
    def test_a_condition_has_to_be_text(self, text):
        with pytest.raises(ValueError):
            parse_condition(text)

    @pytest.mark.parametrize(
        "text,expected",
        [(">", ">"), ("> 2.0", ">"), ("nan", "nan"), ("  stalled ", "stalled")],
    )
    def test_condition_name_takes_either_spelling(self, text, expected):
        assert condition_name(text) == expected

    def test_condition_name_still_refuses_nonsense(self):
        with pytest.raises(ValueError):
            condition_name("> abc")


# --------------------------------------------------------------------- rule --


class TestAlertValidation:
    def test_a_threshold_condition_needs_its_operand(self):
        with pytest.raises(ValueError):
            Alert(key="loss", condition=">")

    def test_a_shapeless_condition_refuses_an_operand(self):
        # Not ignored: a threshold beside 'nan' means its author expected it
        # to do something, and silently dropping it leaves them with a rule
        # that fires on a different thing than they wrote.
        with pytest.raises(ValueError):
            Alert(key="loss", condition="nan", threshold=2.0)

    @pytest.mark.parametrize("key", ["", "   ", None, 7])
    def test_a_rule_needs_a_metric(self, key):
        with pytest.raises(ValueError):
            Alert(key=key, condition="nan")

    def test_the_metric_name_is_stripped(self):
        assert Alert(key="  val_loss  ", condition="nan").key == "val_loss"

    @pytest.mark.parametrize("for_steps", [0, -1, 1.5, True, "3"])
    def test_for_steps_must_be_a_positive_integer(self, for_steps):
        with pytest.raises(ValueError):
            build_alert("loss", "> 2.0", for_steps=for_steps)

    def test_for_steps_defaults_when_left_out(self):
        assert build_alert("loss", "> 2.0").for_steps == 1

    def test_for_steps_normalises_an_explicit_none(self):
        assert build_alert("loss", "> 2.0", for_steps=None).for_steps == 1

    def test_patience_defaults_only_for_the_stall_watch(self):
        assert build_alert("loss", "stalled").patience == DEFAULT_PATIENCE
        assert build_alert("loss", "> 2.0").patience is None

    @pytest.mark.parametrize("condition", ["> 2.0", "nan"])
    def test_patience_and_goal_are_refused_elsewhere(self, condition):
        with pytest.raises(ValueError):
            build_alert("loss", condition, patience=5)
        with pytest.raises(ValueError):
            build_alert("loss", condition, goal="max")

    def test_the_goal_defaults_to_minimising(self):
        # A loss is the metric people set a stall watch on first, and down is
        # better for it. An accuracy has to say so.
        assert build_alert("loss", "stalled").goal == "min"

    @pytest.mark.parametrize("goal", ["lower", "MIN", "", 0])
    def test_an_unknown_goal_is_refused(self, goal):
        with pytest.raises(ValueError):
            build_alert("loss", "stalled", goal=goal)

    @pytest.mark.parametrize("action", ["email", "toasted", "", 7])
    def test_an_unknown_action_is_refused(self, action):
        # An action nobody delivers is a rule configured to do nothing, which
        # is worse than a refusal: it looks armed on the record.
        with pytest.raises(ValueError):
            build_alert("loss", "nan", action=action)

    def test_the_action_defaults_to_the_toast(self):
        assert build_alert("loss", "nan", action=None).action == ACTION_TOAST

    def test_a_message_is_trimmed_and_bounded(self):
        assert build_alert("loss", "nan", message="  diverged  ").message == "diverged"
        with pytest.raises(ValueError):
            build_alert("loss", "nan", message="x" * 500)

    @pytest.mark.parametrize("message", [7, ["a"], {"a": 1}])
    def test_a_message_has_to_be_text(self, message):
        with pytest.raises(ValueError):
            build_alert("loss", "nan", message=message)

    def test_the_rule_identity_is_the_metric_and_the_condition(self):
        assert build_alert("loss", "> 2.0").rule_id == ("loss", ">")
        assert build_alert("loss", "> 9.0").rule_id == ("loss", ">")
        assert build_alert("loss", "stalled").rule_id != ("loss", ">")

    def test_a_rule_round_trips_through_its_dict(self):
        # Including the running state, which is the reason the state is on the
        # record at all: a restarted server has to find the streak it left.
        alert = build_alert("loss", "> 2.0", for_steps=3, message="too high")
        alert.streak, alert.fire_count, alert.last_fired_step = 3, 1, 42
        restored = Alert.from_dict(alert.to_dict())
        assert restored.to_dict() == alert.to_dict()
        assert (restored.streak, restored.fire_count) == (3, 1)

    def test_an_old_record_without_the_new_fields_still_loads(self):
        restored = Alert.from_dict({"key": "loss", "condition": "nan"})
        assert restored.for_steps == 1
        assert restored.fire_count == 0


class TestWebhookRules:
    """The url half of a rule: required by one action and refused by the other.

    None of this asks whether the server may *reach* the host -- that answer
    comes from the flags the server was started with, so it lives next to the
    request in ``visdom.server.webhooks`` and is tested there. What a rule
    owes on its own is a url that is a url.
    """

    def test_a_webhook_rule_keeps_its_url(self):
        alert = build_alert(
            "loss", "nan", action="webhook", url="  https://hooks.example.com/t  "
        )
        assert alert.action == "webhook"
        assert alert.url == "https://hooks.example.com/t"

    @pytest.mark.parametrize("url", [None, "", "   "])
    def test_a_webhook_rule_needs_a_url(self, url):
        with pytest.raises(ValueError):
            build_alert("loss", "nan", action="webhook", url=url)

    def test_a_toast_rule_refuses_a_url(self):
        # The same shape as patience off the stall watch: a url that posts
        # nowhere is a rule its author would have to read the source to
        # understand.
        with pytest.raises(ValueError):
            build_alert("loss", "nan", url="https://hooks.example.com/t")

    def test_a_toast_rule_has_an_empty_url(self):
        assert build_alert("loss", "nan").url == ""
        assert build_alert("loss", "nan", url=None).url == ""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://hooks.example.com/t",
            "javascript:alert(1)",
            "hooks.example.com/t",
        ],
    )
    def test_only_http_and_https_are_posted_to(self, url):
        with pytest.raises(ValueError):
            build_alert("loss", "nan", action="webhook", url=url)

    def test_credentials_in_a_url_are_refused(self):
        # https://hooks.example.com@attacker.example/ is a request to
        # attacker.example, and a secret on the experiment record besides.
        with pytest.raises(ValueError):
            build_alert(
                "loss",
                "nan",
                action="webhook",
                url="https://hooks.example.com@attacker.example/t",
            )

    @pytest.mark.parametrize(
        "url", ["https://", "https:///t", "http://[notanaddress]/t", "http://h:70000/"]
    )
    def test_a_url_the_stdlib_cannot_take_apart_is_refused(self, url):
        # Including the two that raise out of an accessor rather than out of
        # the split: a bracketed address that is not one, and a port that is
        # not a port. Both would otherwise come back as an OverflowError or an
        # AttributeError from somewhere far from here.
        with pytest.raises(ValueError):
            build_alert("loss", "nan", action="webhook", url=url)

    def test_a_url_is_bounded(self):
        with pytest.raises(ValueError):
            build_alert(
                "loss",
                "nan",
                action="webhook",
                url="https://hooks.example.com/" + "t" * 2100,
            )

    def test_a_webhook_rule_round_trips_through_its_dict(self):
        alert = build_alert(
            "loss", "> 2.0", action="webhook", url="https://hooks.example.com/t"
        )
        restored = Alert.from_dict(alert.to_dict())
        assert restored.to_dict() == alert.to_dict()
        assert restored.url == "https://hooks.example.com/t"

    def test_a_record_written_before_webhooks_loads_with_no_url(self):
        assert Alert.from_dict({"key": "loss", "condition": "nan"}).url == ""

    def test_a_stored_webhook_rule_with_a_bad_url_is_refused_on_load(self):
        # Validation on the way in as well as on the way out: a record edited
        # by hand, or written by a version that allowed something this one
        # does not, must not become a request this server then makes.
        with pytest.raises(ValueError):
            Alert.from_dict(
                {
                    "key": "loss",
                    "condition": "nan",
                    "action": "webhook",
                    "url": "file:///etc/passwd",
                }
            )


# --------------------------------------------------------------------- fold --


def feed(alert, values, step=None):
    """Fold ``values`` in one at a time; return the steps at which it fired."""
    fired = []
    for index, value in enumerate(values):
        if observe(alert, value, step if step is not None else index):
            fired.append(index)
    return fired


class TestThresholdConditions:
    def test_over_fires_on_the_first_observation_over(self):
        assert feed(build_alert("loss", "> 2.0"), [1.0, 2.0, 2.5]) == [2]

    def test_under_and_equal(self):
        assert feed(build_alert("loss", "< 0.5"), [1.0, 0.4]) == [1]
        assert feed(build_alert("loss", "== 0"), [1.0, 0.0]) == [1]

    def test_the_threshold_itself_does_not_fire_a_strict_comparison(self):
        assert feed(build_alert("loss", "> 2.0"), [2.0, 2.0, 2.0]) == []

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), None, "2.5", True])
    def test_a_value_that_is_not_a_finite_number_never_crosses_a_threshold(self, value):
        # NaN in particular: every comparison against it is false, so a
        # diverged loss would slip past '> 2.0' unnoticed. That is what the
        # 'nan' condition is for, and the test below holds it to it.
        assert feed(build_alert("loss", "> 2.0"), [value]) == []

    def test_an_integer_too_wide_for_a_float_is_refused_rather_than_raising(self):
        # JSON puts no bound on integer length, so an observation can hold
        # one. float() and math.isfinite() both raise OverflowError on it,
        # which would come out of the request that logged the metric.
        assert feed(build_alert("loss", "> 2.0"), [10**400]) == []
        assert feed(build_alert("loss", "nan"), [10**400]) == []
        assert feed(build_alert("loss", "stalled", patience=1), [10**400, 1]) == []

    def test_a_non_numeric_observation_breaks_a_streak(self):
        alert = build_alert("loss", "> 2.0", for_steps=2)
        assert feed(alert, [2.5, "paused", 2.5]) == []
        assert alert.streak == 1


class TestNanCondition:
    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_every_non_finite_float_fires(self, value):
        assert feed(build_alert("loss", "nan"), [value]) == [0]

    def test_a_null_fires_too_because_that_is_what_crosses_the_wire(self):
        # The one that matters: standard JSON cannot spell a non-finite
        # number, so the client's encoder writes one as null. A condition
        # that only matched the float would be dead for every real client.
        assert feed(build_alert("loss", "nan"), [None]) == [0]

    @pytest.mark.parametrize("value", [0.0, -1, 1e308, True])
    def test_a_number_does_not(self, value):
        assert feed(build_alert("loss", "nan"), [value]) == []

    @pytest.mark.parametrize("value", ["nan", [float("nan")], {"a": 1}])
    def test_a_value_of_the_wrong_kind_does_not(self, value):
        # This condition is about arithmetic going wrong, not about a metric
        # being logged as something other than a number -- which the store
        # does not treat as absent either.
        assert feed(build_alert("loss", "nan"), [value]) == []


class TestStalledCondition:
    def test_it_fires_once_patience_observations_bring_no_improvement(self):
        alert = build_alert("loss", "stalled", patience=2)
        assert feed(alert, [1.0, 0.9, 0.9, 0.9]) == [3]
        assert alert.best == 0.9

    def test_an_improvement_resets_the_count(self):
        alert = build_alert("loss", "stalled", patience=2)
        assert feed(alert, [1.0, 1.0, 0.5, 1.0, 1.0, 1.0]) == [4]

    def test_the_goal_decides_which_way_is_better(self):
        rising = [0.1, 0.2, 0.3, 0.4]
        assert (
            feed(build_alert("acc", "stalled", patience=2, goal=GOAL_MAX), rising) == []
        )
        assert feed(build_alert("acc", "stalled", patience=2), rising) == [2]

    def test_the_first_observation_is_the_best_so_far_and_never_fires(self):
        alert = build_alert("loss", "stalled", patience=1)
        assert feed(alert, [5.0]) == []
        assert alert.best == 5.0

    def test_a_non_finite_observation_is_neither_a_stall_nor_an_improvement(self):
        alert = build_alert("loss", "stalled", patience=1)
        assert feed(alert, [1.0, float("nan"), float("nan")]) == []
        assert alert.best == 1.0
        assert alert.since_best == 0


class TestDebounce:
    def test_the_condition_has_to_hold_for_the_whole_streak(self):
        alert = build_alert("loss", "> 2.0", for_steps=3)
        assert feed(alert, [2.5, 2.5]) == []
        assert feed(alert, [2.5]) == [0]

    def test_one_observation_under_the_threshold_starts_the_streak_over(self):
        alert = build_alert("loss", "> 2.0", for_steps=3)
        assert feed(alert, [2.5, 2.5, 1.0, 2.5, 2.5]) == []
        assert alert.streak == 2

    def test_a_rule_fires_once_per_unbroken_run(self):
        # The whole point of the debounce: a metric that sits over its
        # threshold for an hour is one notification, not one per step.
        alert = build_alert("loss", "> 2.0", for_steps=2)
        assert feed(alert, [2.5] * 10) == [1]
        assert alert.fire_count == 1

    def test_it_re_arms_once_the_streak_breaks(self):
        alert = build_alert("loss", "> 2.0", for_steps=2)
        assert feed(alert, [2.5, 2.5, 1.0, 2.5, 2.5]) == [1, 4]
        assert alert.fire_count == 2

    def test_the_streak_survives_a_round_trip_through_the_record(self):
        # The reason the state is stored rather than held in memory: a server
        # restarted mid-run picks the streak up where it left off instead of
        # re-arming every rule it reloads.
        alert = build_alert("loss", "> 2.0", for_steps=3)
        feed(alert, [2.5, 2.5])
        restored = Alert.from_dict(alert.to_dict())
        assert feed(restored, [2.5]) == [0]

    def test_a_diverged_observation_does_not_re_arm_the_rule(self):
        # The run that fires a threshold rule is the one that goes on to log
        # nulls, and a null is not the metric coming back under the
        # threshold. Re-arming there is a second notification for one run.
        alert = build_alert("loss", "> 2.0", for_steps=3)
        assert feed(alert, [2.5, 2.5, 2.5, 2.5, None, 2.5, 2.5, 2.5]) == [2]
        assert alert.fire_count == 1

    def test_a_diverged_observation_does_not_re_arm_the_stall_watch(self):
        # Here the metric demonstrably never improved -- the NaN leaves the
        # count since the best alone -- so a second firing would contradict
        # the message it carries.
        alert = build_alert("loss", "stalled", patience=2)
        assert feed(alert, [1.0, 1.5, 1.5, 1.5, float("nan"), 1.5, 1.5]) == [2]
        assert alert.fire_count == 1

    def test_firing_records_where_it_happened(self):
        alert = build_alert("loss", "> 2.0")
        assert feed(alert, [2.5], step=120) == [0]
        assert alert.last_fired_step == 120
        assert alert.last_fired_at is not None


# ---------------------------------------------------------------- evaluate --


class TestEvaluate:
    def test_only_the_metrics_in_the_batch_are_judged(self):
        # The second rule would fire on the first one's observation, so a
        # fold that ignored the key shows up here as two events rather than
        # passing quietly.
        experiment = Record(build_alert("loss", "> 2.0"))
        experiment.alerts.append(build_alert("acc", "> 2.0"))
        fired = evaluate(experiment, [("loss", 2.5)], step=3)
        assert [event.alert.key for event in fired] == ["loss"]
        assert fired[0].value == 2.5 and fired[0].step == 3

    def test_every_rule_on_one_metric_sees_the_observation(self):
        # Both calls are asserted: the threshold rule fires on the first
        # observation and the stall watch on the second, so a fold that
        # judged only one rule per metric fails on one of them.
        experiment = Record(build_alert("loss", "> 2.0"))
        experiment.alerts.append(build_alert("loss", "stalled", patience=1))
        first = evaluate(experiment, [("loss", 2.5)])
        assert [event.alert.condition for event in first] == [">"]
        fired = evaluate(experiment, [("loss", 2.5)])
        assert [event.alert.condition for event in fired] == ["stalled"]

    def test_an_experiment_with_no_rules_is_not_walked(self):
        assert evaluate(Record(), [("loss", 2.5)]) == []

    def test_a_batch_is_judged_in_the_order_it_was_logged(self):
        # Two observations whose order decides the outcome: the 2.5 completes
        # the streak and the 1.0 then breaks it, where the other way round
        # nothing fires at all.
        experiment = Record(build_alert("loss", "> 2.0", for_steps=2))
        evaluate(experiment, [("loss", 2.5)])
        fired = evaluate(experiment, [("loss", 2.5), ("loss", 1.0)])
        assert [event.value for event in fired] == [2.5]
        assert experiment.alerts[0].streak == 0


class TestDescribe:
    def test_a_threshold_message_names_the_value_and_the_rule(self):
        alert = build_alert("val_loss", "> 2.0", for_steps=3)
        message = describe(AlertEvent(alert, 2.41, 120), env_id="run-7")
        assert message == (
            "run-7: val_loss is 2.41, > 2 for 3 observations at step 120"
        )

    def test_a_stall_message_names_the_best_seen(self):
        alert = build_alert("acc", "stalled", patience=10, goal=GOAL_MAX)
        feed(alert, [0.91])
        message = describe(AlertEvent(alert, 0.9, 30), env_id="run-7")
        assert message == (
            "run-7: acc has not improved in 10 observations (best 0.91) at step 30"
        )

    def test_a_stall_message_names_the_best_at_the_time_it_fired(self):
        # The rule keeps folding after the event comes out, and the later
        # 0.95 in this very batch must not rewrite what the notification for
        # the 0.80 says.
        experiment = Record(build_alert("acc", "stalled", patience=1, goal=GOAL_MAX))
        evaluate(experiment, [("acc", 0.90)], step=1)
        fired = evaluate(experiment, [("acc", 0.80), ("acc", 0.95)], step=2)
        assert describe(fired[0], env_id="run-7") == (
            "run-7: acc has not improved in 1 observations (best 0.9) at step 2"
        )

    def test_a_message_keeps_the_precision_that_made_the_rule_fire(self):
        # Six significant digits round both sides of this comparison to 1,
        # and "loss is 1, > 1" is worse than no notification at all.
        alert = build_alert("loss", "> 1.0000001")
        assert describe(AlertEvent(alert, 1.00000011)) == (
            "loss is 1.00000011, > 1.0000001"
        )

    def test_a_nan_message_says_what_arrived(self):
        alert = build_alert("loss", "nan")
        assert describe(AlertEvent(alert, float("nan"), 12), env_id="run-7") == (
            "run-7: loss is nan at step 12"
        )

    def test_a_null_is_described_as_what_it_means(self):
        # "loss is None" is not what happened: the observation was a NaN or
        # an infinity, and the wire turned it into null on the way here.
        alert = build_alert("loss", "nan")
        assert describe(AlertEvent(alert, None, 12), env_id="run-7") == (
            "run-7: loss is not a finite number at step 12"
        )

    def test_a_caller_s_own_message_is_used_verbatim(self):
        # Never interpolated into: a rule's text would otherwise be a format
        # string, and one with a stray brace in it would raise from the
        # notification path rather than from the call that set it.
        alert = build_alert("loss", "nan", message="the loss diverged {oops}")
        assert describe(AlertEvent(alert, float("nan")), env_id="run-7") == (
            "run-7: the loss diverged {oops}"
        )

    def test_the_step_is_left_out_when_there_was_none(self):
        alert = build_alert("loss", "> 2.0")
        assert describe(AlertEvent(alert, 2.5)) == "loss is 2.5, > 2"


# ------------------------------------------------------------------ records --


class TestExperimentRules:
    def test_a_metric_may_carry_several_rules_of_different_conditions(self):
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "> 2.0"))
        experiment.set_alert(build_alert("loss", "stalled"))
        assert [a.rule_id for a in experiment.alerts] == [
            ("loss", ">"),
            ("loss", "stalled"),
        ]

    def test_restating_a_rule_replaces_it_and_resets_its_state(self):
        experiment = Experiment(env_id="run-7")
        first = build_alert("loss", "> 2.0", for_steps=2)
        experiment.set_alert(first)
        feed(first, [2.5, 2.5])
        experiment.set_alert(build_alert("loss", "> 9.0", for_steps=2))
        assert len(experiment.alerts) == 1
        assert experiment.alerts[0].threshold == 9.0
        assert experiment.alerts[0].streak == 0

    def test_the_number_of_rules_is_bounded(self):
        experiment = Experiment(env_id="run-7")
        for index in range(MAX_ALERTS_PER_ENV):
            experiment.set_alert(build_alert("m{0}".format(index), "nan"))
        with pytest.raises(ValueError):
            experiment.set_alert(build_alert("one-too-many", "nan"))

    def test_the_bound_does_not_stop_a_replacement(self):
        experiment = Experiment(env_id="run-7")
        for index in range(MAX_ALERTS_PER_ENV):
            experiment.set_alert(build_alert("m{0}".format(index), "> 1.0"))
        experiment.set_alert(build_alert("m0", "> 5.0"))
        assert len(experiment.alerts) == MAX_ALERTS_PER_ENV

    def test_clearing_a_metric_drops_every_rule_on_it(self):
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "> 2.0"))
        experiment.set_alert(build_alert("loss", "stalled"))
        experiment.set_alert(build_alert("acc", "nan"))
        assert experiment.clear_alerts("loss") == 2
        assert [a.rule_id for a in experiment.alerts] == [("acc", "nan")]

    def test_clearing_one_condition_leaves_the_others(self):
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "> 2.0"))
        experiment.set_alert(build_alert("loss", "stalled"))
        assert experiment.clear_alerts("loss", ">") == 1
        assert [a.rule_id for a in experiment.alerts] == [("loss", "stalled")]

    def test_clearing_nothing_removes_nothing(self):
        experiment = Experiment(env_id="run-7")
        assert experiment.clear_alerts("loss") == 0

    def test_rules_survive_the_record_round_trip(self):
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "> 2.0", for_steps=2))
        restored = Experiment.from_dict(experiment.to_dict())
        assert [a.rule_id for a in restored.alerts] == [("loss", ">")]

    def test_an_experiment_recorded_before_alerts_existed_still_loads(self):
        blob = Experiment(env_id="run-7").to_dict()
        del blob["alerts"]
        assert Experiment.from_dict(blob).alerts == []

    def test_get_alerts_can_be_narrowed_to_one_metric(self):
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "nan"))
        experiment.set_alert(build_alert("acc", "nan"))
        assert [a.key for a in experiment.get_alerts("acc")] == ["acc"]
        assert len(experiment.get_alerts()) == 2

    def test_get_alerts_hands_back_a_list_the_caller_cannot_grow(self):
        experiment = Experiment(env_id="run-7")
        experiment.get_alerts().append(build_alert("loss", "nan"))
        assert experiment.alerts == []


# ------------------------------------------------------------------- store --


class TestStoreEvaluation:
    def test_logging_a_metric_folds_the_rules_and_reads_no_storage(self):
        env = {"jsons": {}, "reload": {}}
        store, written = live_store(env)
        store.set_alert("run-7", build_alert("loss", "> 2.0"))

        fired = []
        store.log_metrics("run-7", {"loss": 2.5}, step=4, fired=fired)

        assert [event.alert.key for event in fired] == ["loss"]
        assert written == ["run-7", "run-7"]

    def test_the_new_state_is_in_the_blob_the_write_carried(self):
        # The fold happens between the append and the serialisation on
        # purpose: state updated afterwards would be lost on the next read.
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.set_alert("run-7", build_alert("loss", "> 2.0", for_steps=5))

        store.log_metrics("run-7", {"loss": 2.5}, fired=[])

        stored = env["experiment"]["alerts"][0]
        assert stored["streak"] == 1
        assert stored["fire_count"] == 0

    def test_a_caller_that_asks_nothing_pays_for_no_fold(self):
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.set_alert("run-7", build_alert("loss", "> 2.0"))

        store.log_metrics("run-7", {"loss": 2.5})

        assert env["experiment"]["alerts"][0]["streak"] == 0

    def test_a_rule_can_be_set_before_the_run_logs_anything(self):
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        experiment = store.set_alert("run-7", build_alert("loss", "nan"))
        assert experiment.env_id == "run-7"
        assert len(env["experiment"]["alerts"]) == 1

    def test_a_finished_run_refuses_a_new_rule(self):
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.log_metrics("run-7", {"loss": 1.0})
        store.finish_experiment("run-7", STATUS_FINISHED)
        with pytest.raises(Exception) as caught:
            store.set_alert("run-7", build_alert("loss", "nan"))
        assert "terminal" in str(caught.value)

    def test_a_finished_run_still_lets_a_rule_be_cleared(self):
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.set_alert("run-7", build_alert("loss", "nan"))
        store.log_metrics("run-7", {"loss": 1.0})
        store.finish_experiment("run-7", STATUS_FINISHED)
        store.clear_alerts("run-7", "loss")
        assert env["experiment"]["alerts"] == []

    def test_clearing_a_rule_that_was_never_set_writes_nothing(self):
        env = {"jsons": {}, "reload": {}}
        store, written = live_store(env)
        store.set_alert("run-7", build_alert("loss", "nan"))
        written.clear()
        store.clear_alerts("run-7", "accuracy")
        assert written == []

    def test_clearing_on_an_env_with_no_experiment_is_a_key_error(self):
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        with pytest.raises(KeyError):
            store.clear_alerts("run-7", "loss")

    def test_get_alerts_answers_from_the_env_it_was_given(self):
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.set_alert("run-7", build_alert("loss", "> 2.0"))
        assert [a.rule_id for a in store.get_alerts("run-7")] == [("loss", ">")]

    def test_get_alerts_on_an_env_without_an_experiment_is_empty(self):
        store, _ = live_store({"jsons": {}, "reload": {}})
        assert store.get_alerts("run-7") == []

    def test_a_long_history_costs_the_fold_nothing(self):
        # The fold reads the rule, never the series. A record with ten
        # thousand observations behind it is the same work as one on its
        # first step -- which is what lets this run on the event loop.
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.set_alert("run-7", build_alert("loss", "> 2.0"))
        store.log_metrics("run-7", [("loss", 1.0)] * 10, fired=[])
        env["experiment"]["metrics"].extend(
            {"key": "loss", "value": 1.0, "step": index, "timestamp": 0.0}
            for index in range(10000)
        )

        fired = []
        store.log_metrics("run-7", {"loss": 2.5}, fired=fired)

        assert len(fired) == 1
        assert math.isclose(fired[0].value, 2.5)
