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

import builtins
import json
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
from visdom.experiments.models import Experiment, Metric, STATUS_FINISHED

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

    def test_a_condition_is_never_evaluated(self, monkeypatch):
        # The refusal above is necessary but not sufficient: a grammar that
        # ran the text through eval() and then refused the result would pass
        # it too. This fails instead, because the probe records being called
        # and the condition is written as a call to it.
        called = []
        monkeypatch.setattr(
            builtins, "_visdom_alert_probe", called.append, raising=False
        )
        with pytest.raises(ValueError):
            parse_condition("> _visdom_alert_probe(1)")
        assert called == []

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

    def test_an_integer_operand_is_read_as_an_integer(self):
        # float('9007199254740993') is 9007199254740992.0 -- the integer
        # below the one written -- so reading every operand as a float would
        # hand back a rule watching a value its author never typed.
        condition, threshold = parse_condition("== 9007199254740993")
        assert (condition, threshold) == ("==", 9007199254740993)
        assert isinstance(threshold, int)

    @pytest.mark.parametrize("text", ["> 2.0", "< 0.5", "> -1e-3", "== 2."])
    def test_a_decimal_operand_is_still_read_as_a_float(self, text):
        assert isinstance(parse_condition(text)[1], float)

    def test_a_digit_padded_integer_is_refused_rather_than_rounded(self):
        # int() refuses a run of digits longer than CPython's conversion
        # limit, and float() does not -- so leading zeros alone used to walk
        # an exact integer operand back into the rounding the test above
        # exists to prevent. 4300 is the limit; this is one digit over it.
        padded = "0" * 4300 + "9007199254740993"
        assert float(padded) != 9007199254740993
        with pytest.raises(ValueError):
            parse_condition("== " + padded)

    def test_an_integer_no_observation_could_reach_is_refused(self):
        # An integer operand is not bounded by float's range the way a
        # decimal one is -- '1e400' parses as an infinity and is refused
        # below -- so the width has to be refused rather than overflowed.
        with pytest.raises(ValueError):
            parse_condition("== {0}".format(10**400))

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

    def test_the_metric_name_is_kept_exactly_as_supplied(self):
        # A trimmed key would watch a name the series does not have.
        assert Alert(key="  val_loss  ", condition="nan").key == "  val_loss  "

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

    @pytest.mark.parametrize("action", ["webhook", "email", "", None])
    def test_only_the_delivered_action_is_accepted(self, action):
        # The webhook action is a separate change: refusing it here is what
        # keeps a caller from configuring a delivery that silently never
        # happens.
        if action is None:
            assert build_alert("loss", "nan", action=action).action == ACTION_TOAST
            return
        with pytest.raises(ValueError):
            build_alert("loss", "nan", action=action)

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

    def test_an_integer_threshold_survives_the_written_rule(self):
        alert = build_alert("count", "== 9007199254740993")
        assert alert.threshold == 9007199254740993
        assert isinstance(alert.threshold, int)

    def test_an_integer_threshold_survives_the_saved_rule(self):
        # Through JSON, which is what an environment is stored as: the
        # rounding the grammar avoids would otherwise be reapplied on every
        # load, so the rule would drift to the neighbouring integer and stay
        # there.
        alert = build_alert("count", "== 9007199254740993")
        restored = Alert.from_dict(json.loads(json.dumps(alert.to_dict())))
        assert restored.threshold == 9007199254740993
        assert isinstance(restored.threshold, int)
        assert restored.to_dict() == alert.to_dict()

    def test_a_digit_padded_threshold_never_reaches_a_saved_rule(self):
        # The same operand through the written form a caller sends: refused
        # at build time, so no rounded threshold is ever stored to be read
        # back exactly on the next load.
        with pytest.raises(ValueError):
            build_alert("count", "== " + "0" * 4300 + "9007199254740993")

    def test_a_remembered_best_is_not_rounded_at_load(self):
        # 'best' is an observation the record kept, and the stall watch
        # compares the next one against it.
        restored = Alert.from_dict(
            {"key": "count", "condition": "stalled", "best": 9007199254740993}
        )
        assert restored.best == 9007199254740993

    def test_an_old_record_without_the_new_fields_still_loads(self):
        restored = Alert.from_dict({"key": "loss", "condition": "nan"})
        assert restored.for_steps == 1
        assert restored.fire_count == 0

    @pytest.mark.parametrize("counter", ["streak", "fire_count", "since_best"])
    @pytest.mark.parametrize("value", ["3", -1, 1.5, True, None, float("nan")])
    def test_a_counter_has_to_be_a_whole_number_of_observations(self, counter, value):
        with pytest.raises(ValueError):
            Alert(key="loss", condition="nan", **{counter: value})

    def test_a_zero_counter_is_legal_where_a_zero_for_steps_is_not(self):
        assert Alert(key="loss", condition="nan", streak=0).streak == 0

    @pytest.mark.parametrize("field_name", ["best", "last_fired_at", "created_at"])
    @pytest.mark.parametrize("value", ["2.5", float("inf"), float("nan"), 10**400])
    def test_a_remembered_number_has_to_be_finite(self, field_name, value):
        with pytest.raises(ValueError):
            Alert(key="loss", condition="stalled", **{field_name: value})

    @pytest.mark.parametrize("value", ["42", 1.5, True])
    def test_the_step_a_rule_fired_at_has_to_be_whole(self, value):
        with pytest.raises(ValueError):
            Alert(key="loss", condition="nan", last_fired_step=value)

    def test_a_negative_step_is_the_callers_own_business(self):
        assert Alert(key="loss", condition="nan", last_fired_step=-5)

    def test_a_corrupted_record_is_refused_at_load(self):
        # An environment is a JSON file somebody can edit, and the state is
        # the half of a rule that comes back from it.
        with pytest.raises(ValueError):
            Alert.from_dict({"key": "loss", "condition": "nan", "streak": "3"})
        with pytest.raises(ValueError):
            Alert.from_dict({"key": "loss", "condition": "nan", "best": "low"})


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
        # which would come out of the request that logged the metric. No
        # threshold can be compared against it, and the stall watch neither
        # improves on it nor counts it; what catches it is 'nan', because an
        # integer that wide is a diverging accumulator logged as an int.
        assert feed(build_alert("loss", "> 2.0"), [10**400]) == []
        assert feed(build_alert("loss", "nan"), [10**400]) == [0]
        assert feed(build_alert("loss", "stalled", patience=1), [10**400, 1]) == []

    def test_an_overflowing_integer_does_not_re_arm_a_rule_that_fired(self):
        # The same rule as the diverged-observation case below, and the same
        # reason: the run that has gone over its threshold is the one that
        # starts overflowing, and re-arming on the overflow would spend a
        # second notification on it.
        alert = build_alert("loss", "> 2.0")
        assert feed(alert, [2.5, 10**400, 2.5]) == [0]
        assert (alert.streak, alert.fire_count) == (2, 1)

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
            "run-7: val_loss is 2.41, > 2.0 for 3 observations at step 120"
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

    def test_no_number_of_digits_is_enough_so_none_is_fixed(self):
        # Twelve significant digits are enough for the rule above and not for
        # this one, which is the argument against picking a number at all: a
        # float is written as the shortest text that reads back as itself.
        alert = build_alert("loss", "> 1.000000000000001")
        assert describe(AlertEvent(alert, 1.000000000000002)) == (
            "loss is 1.000000000000002, > 1.000000000000001"
        )

    def test_an_integer_threshold_is_written_as_the_integer_it_is(self):
        # The grammar and the record keep this threshold exact; a message
        # that rendered it as 9.00719925474e+15 would be the only place the
        # rule's author ever saw it, rounded.
        alert = build_alert("count", "== 9007199254740993")
        assert describe(AlertEvent(alert, 9007199254740993)) == (
            "count is 9007199254740993, == 9007199254740993"
        )

    def test_an_overflowing_integer_is_named_rather_than_spelled_out(self):
        # Four hundred digits in a toast say less than the sentence does.
        alert = build_alert("loss", "nan")
        assert describe(AlertEvent(alert, 10**400)) == "loss is not a finite number"

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
        assert describe(AlertEvent(alert, 2.5)) == "loss is 2.5, > 2.0"


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

    def test_a_rule_read_back_and_set_again_is_rearmed_too(self):
        # Editing a rule means reading it, changing it and setting it again,
        # so the rule handed in is routinely one that has been folding all
        # run. Its state cannot be assumed to be clean just because the
        # docstring says a replacement starts clean.
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "> 2.0", for_steps=2))
        stored = experiment.get_alerts("loss")[0]
        feed(stored, [2.5, 2.5])
        assert (stored.streak, stored.fire_count) == (2, 1)

        stored.threshold = 1.0
        replacement = experiment.set_alert(stored)
        assert replacement.threshold == 1.0
        assert (replacement.streak, replacement.fire_count) == (0, 0)
        assert (replacement.best, replacement.since_best) == (None, 0)
        assert experiment.get_alerts("loss") == [replacement]

    def test_a_replacement_can_fire_where_the_rule_it_replaced_already_had(self):
        # The consequence of carrying a streak over, and the reason this is
        # not only tidiness: a rule fires as its streak is completed and not
        # again until it breaks, so a replacement that inherited a streak
        # which had already fired would stay silent through a run that went
        # on matching it -- the one run its author wanted to hear about.
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "> 2.0", for_steps=2))
        evaluate(experiment, [("loss", 2.5)], step=1)
        assert len(evaluate(experiment, [("loss", 2.5)], step=2)) == 1

        experiment.set_alert(experiment.get_alerts("loss")[0])
        assert evaluate(experiment, [("loss", 2.5)], step=3) == []
        assert [e.step for e in evaluate(experiment, [("loss", 2.5)], step=4)] == [4]

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

    def test_a_rule_can_be_cleared_by_the_condition_it_was_written_with(self):
        # '> 2.0' is the spelling its author has in hand; the stored rule's
        # condition is '>'. Comparing the two as text clears nothing and
        # reports that it cleared nothing, which is a rule you can set and
        # cannot remove.
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "> 2.0"))
        experiment.set_alert(build_alert("loss", "stalled"))
        assert experiment.clear_alerts("loss", "> 2.0") == 1
        assert [a.rule_id for a in experiment.alerts] == [("loss", "stalled")]

    def test_clearing_by_something_that_is_not_a_condition_is_refused(self):
        experiment = Experiment(env_id="run-7")
        experiment.set_alert(build_alert("loss", "> 2.0"))
        with pytest.raises(ValueError):
            experiment.clear_alerts("loss", ">= 2.0")
        assert len(experiment.alerts) == 1

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

    def test_the_rules_are_folded_even_when_nobody_collects_the_events(self):
        # The state belongs to the record, not to the caller. A path that
        # logs observations without asking what they set off would otherwise
        # leave the streak counting a series the run never had, and the next
        # caller that does ask would be answered from it.
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.set_alert("run-7", build_alert("loss", "> 2.0", for_steps=2))

        store.log_metrics("run-7", {"loss": 2.5})
        assert env["experiment"]["alerts"][0]["streak"] == 1

        fired = []
        store.log_metrics("run-7", {"loss": 2.5}, fired=fired)
        assert [event.alert.key for event in fired] == ["loss"]

    def test_one_observation_is_folded_the_same_way(self):
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.set_alert("run-7", build_alert("loss", "> 2.0"))

        fired = []
        store.log_metric("run-7", "loss", 2.5, fired=fired)

        assert [event.value for event in fired] == [2.5]
        assert env["experiment"]["alerts"][0]["fire_count"] == 1

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

    def test_a_long_history_costs_the_fold_nothing(self, monkeypatch):
        # The fold reads the rule, never the series. A record with ten
        # thousand observations behind it is the same work as one on its
        # first step -- which is what lets this run on the event loop.
        #
        # Asserting the event alone would not catch a fold that scanned the
        # history first: it would arrive at the same answer, only Theta(m)
        # later. So the one thing a scan cannot avoid is taken away instead.
        # Reading a stored observation back out of a LazyMetricList builds a
        # Metric from its dict, and iterating the series does it once per
        # observation, so a from_dict that raises turns a history scan from a
        # regression nobody measures into a failed test. Nothing else on this
        # path builds one: the append constructs a Metric directly, and the
        # write hands the stored dicts back untouched.
        env = {"jsons": {}, "reload": {}}
        store, _ = live_store(env)
        store.set_alert("run-7", build_alert("loss", "> 2.0"))
        store.log_metrics("run-7", [("loss", 1.0)] * 10, fired=[])
        env["experiment"]["metrics"].extend(
            {"key": "loss", "value": 1.0, "step": index, "timestamp": 0.0}
            for index in range(10000)
        )

        def unread(_data):
            raise AssertionError("the fold read an observation out of the series")

        monkeypatch.setattr(Metric, "from_dict", staticmethod(unread))

        fired = []
        store.log_metrics("run-7", {"loss": 2.5}, fired=fired)

        assert len(fired) == 1
        assert math.isclose(fired[0].value, 2.5)
        assert len(env["experiment"]["metrics"]) == 10011
