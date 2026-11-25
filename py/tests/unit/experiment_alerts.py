#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the alert rule: its grammar, and what it will accept.

A rule is three separable things, and this covers the first two. The
*grammar* is what turns ``"> 2.0"`` into an operator and a number, and is the
only place user text is read -- so the refusals are as much the subject here
as the acceptances. The *rule* is what that grammar builds: a dataclass that
validates every field at construction and round-trips through the dict it is
stored as.

The third thing, the fold that decides whether an observation fires a rule,
is tested beside the code that does it.
"""

import builtins
import json

import pytest

from visdom.experiments.alerts import (
    ACTION_TOAST,
    Alert,
    build_alert,
    condition_name,
    DEFAULT_PATIENCE,
    parse_condition,
)

pytestmark = pytest.mark.unit


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
