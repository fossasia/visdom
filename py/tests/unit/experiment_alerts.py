#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the alert rule: its grammar, what it accepts, and the fold.

A rule is three separable things, and this covers the first two and a half.
The *grammar* is what turns ``"> 2.0"`` into an operator and a number, and is
the only place user text is read. The *rule* is what that grammar builds. The
*fold* is what decides whether an observation fires one, and is a pure
function of the rule's own state -- never of the metric history, which is the
property that lets it run on the event loop beside the append.

The fold is held to that here by feeding it a stand-in record rather than an
``Experiment``: it reads nothing but ``alerts``, and a test that proved it
against the real record could not tell the difference.
"""

import json

import pytest

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
    observe,
    parse_condition,
)

pytestmark = pytest.mark.unit


class Record:
    """The least an ``evaluate`` caller can be: something holding rules."""

    def __init__(self, *alerts):
        self.alerts = list(alerts)


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
