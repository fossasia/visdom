#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Metric alert rules: what one is, and what it will accept.

An :class:`Alert` is a rule attached to one experiment: a metric name, a
condition, and the bookkeeping that decides when the condition has held for
long enough to be worth telling someone about. A rule is shaped to live on
the experiment record alongside the params and metrics it watches, so that
it will be persisted, searched and forked with the environment and survive a
server restart once the record carries it.

A condition is a **fixed enum with a numeric operand**, never an expression:
``>``, ``<`` and ``==`` compare against a constant, ``nan`` catches an
observation that is not a finite number -- including the ``null`` a NaN
becomes on the wire -- and ``stalled`` catches a metric that has stopped
improving. :func:`parse_condition` is the only thing that reads the operand,
and it reads it with ``int()`` or ``float()`` -- an integer operand stays an
integer, because ``float()`` would round the very value the rule names;
nothing here evaluates user text.

Every rule also carries its own running state -- the streak of matching
observations, the best value seen so far, how many observations have passed
since -- which is part of the stored record rather than held in memory, so a
restarted server picks a streak up where it left off. Folding an observation
into that state is the next piece and lives beside this one.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Union

CONDITION_GT = ">"
CONDITION_LT = "<"
CONDITION_EQ = "=="
CONDITION_NAN = "nan"
CONDITION_STALLED = "stalled"

# The conditions that compare an observation against a constant, and so need
# one. The two without an operand watch the shape of the series instead.
THRESHOLD_CONDITIONS = (CONDITION_GT, CONDITION_LT, CONDITION_EQ)
VALID_CONDITIONS = THRESHOLD_CONDITIONS + (CONDITION_NAN, CONDITION_STALLED)

ACTION_TOAST = "toast"
VALID_ACTIONS = (ACTION_TOAST,)

GOAL_MIN = "min"
GOAL_MAX = "max"
VALID_GOALS = (GOAL_MIN, GOAL_MAX)

DEFAULT_PATIENCE = 10
DEFAULT_FOR_STEPS = 1
DEFAULT_GOAL = GOAL_MIN

# A rule is user input stored on the record and evaluated on every logged
# observation, so the number of them an environment may hold is bounded. The
# same ceiling the tag mapping uses.
MAX_ALERTS_PER_ENV = 20
MAX_MESSAGE_LENGTH = 200

# ``==`` on two floats is exact, which is the right answer for the integral
# and interned values a threshold is actually written against (``== 0``) and
# the wrong one for everything else. Documented rather than fudged with a
# tolerance nobody asked for: ``>``/``<`` is what a real-valued metric wants.
#
# Which is also why an integer stays an integer everywhere below -- in the
# operand the grammar reads, in the field the rule stores and in the
# observation it is compared against. ``float()`` is lossy past 2**53, so
# ``== 9007199254740993`` would otherwise be stored, reloaded and compared as
# 9007199254740992: a rule watching the integer next to the one written.


def _is_finite_number(value: Any) -> bool:
    """Whether ``value`` is a real number that can be compared with another.

    A ``bool`` is excluded so that ``True`` does not compare as ``1``, and an
    integer too wide to become a float is excluded rather than raising --
    JSON puts no bound on integer length, so an observation can hold one, and
    ``math.isfinite`` would otherwise raise ``OverflowError`` out of a
    request rather than answering. The same exclusion
    :func:`~visdom.experiments.store._is_number` makes, for the same reason.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _as_number(value: Any) -> Optional[Union[int, float]]:
    """``value`` as the number it is, or ``None`` if it is not a finite one.

    A metric logged as a string, a ``None`` or a ``NaN`` cannot be over or
    under a threshold, and saying so here keeps every condition free of the
    question.

    An integer comes back as itself rather than as ``float(value)``: a
    threshold that was kept exact is of no use if the observation it is
    compared against is rounded on the way in, and the comparison operators
    are exact across the two types anyway.
    """
    if not _is_finite_number(value):
        return None
    return value


def _positive_int(value: Any, field_name: str) -> int:
    """``value`` as an ``int >= 1``, or raise ``ValueError``.

    ``bool`` is refused before ``int`` because it is an ``int`` subclass, and
    ``for_steps=True`` means nothing.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            "{0} must be a positive integer, got {1!r}".format(field_name, value)
        )
    if value < 1:
        raise ValueError("{0} must be at least 1, got {1!r}".format(field_name, value))
    return value


def _counter(value: Any, field_name: str) -> int:
    """``value`` as an ``int >= 0``, or raise ``ValueError``.

    A counter starts at zero and only climbs, so zero is legal here where it
    is not for ``for_steps``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            "{0} must be a whole number of observations, got {1!r}".format(
                field_name, value
            )
        )
    if value < 0:
        raise ValueError("{0} cannot be negative, got {1!r}".format(field_name, value))
    return value


def _optional_number(value: Any, field_name: str) -> Optional[Union[int, float]]:
    """``value`` as a finite number, or ``None``; anything else raises.

    A remembered value and a timestamp are either absent or a number that can
    be compared with another one. An integer is left as one, for the reason
    the threshold is: ``best`` is an observation that was written to the
    record, and rounding it on the way back in would have the stall watch
    comparing against a value the series never held.
    """
    if value is None:
        return None
    if not _is_finite_number(value):
        raise ValueError(
            "{0} must be a finite number or absent, got {1!r}".format(field_name, value)
        )
    return value if isinstance(value, int) else float(value)


def _optional_int(value: Any, field_name: str) -> Optional[int]:
    """``value`` as an ``int``, or ``None``; anything else raises.

    A step is the caller's own counter, so a negative one is theirs to pick.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            "{0} must be a whole number or absent, got {1!r}".format(field_name, value)
        )
    return value


def _written_number(operand: str) -> Union[int, float]:
    """The number written in ``operand``, as the kind of number it is written as.

    An integer literal comes back as an ``int``. ``float()`` is lossy past
    sixteen digits -- ``float("9007199254740993")`` is ``9007199254740992.0``
    -- and a threshold is the one number in a rule that is written rather
    than measured, so rounding it hands its author a rule watching the
    integer beside the one they typed. Anything else is a ``float``, which is
    what a metric usually is.

    ``ValueError`` out of either conversion is the caller's to report, which
    is where the operand it was read out of is still in hand.
    """
    try:
        return int(operand)
    except ValueError:
        digits = operand.strip()
        digits = digits[1:] if digits[:1] in "+-" else digits
        if digits.isdigit():
            # ``int()`` refuses a run of digits for exactly one reason: it is
            # longer than CPython's integer string conversion limit. Falling
            # through to ``float()`` would parse it anyway -- that limit is
            # ``int()``'s alone -- and round it, which is the one thing this
            # function exists to prevent. A padded threshold is refused where
            # it is written instead of silently becoming its neighbour.
            raise ValueError(
                "{0!r} is written as an integer but is too long for one to "
                "be read exactly".format(operand)
            )
        return float(operand)


def parse_condition(text: Any) -> tuple:
    """Split a written condition into ``(condition, threshold)``.

    The spelling a caller writes is the one in the docs --
    ``"> 2.0"``, ``"< 0.5"``, ``"== 0"``, ``"nan"``, ``"stalled"`` -- and this
    is the only place it is read. The operand goes through ``int()`` or
    ``float()`` and nothing else, so the worst a hostile condition can be is
    a ``ValueError``; an integer one keeps every digit it was written with.

    ``>=`` and ``<=`` are deliberately absent rather than silently accepted as
    ``>``: a rule that fires on exactly the threshold is a different rule, and
    one the caller can write as a threshold a step away.
    """
    if not isinstance(text, str):
        raise ValueError("condition must be a string, got {0!r}".format(text))
    condition = " ".join(text.split())
    if not condition:
        raise ValueError("condition must not be empty")

    for rejected in (">=", "<=", "!="):
        # Checked before the operators below, which would otherwise match the
        # '>' of '>= 2.0' and report its operand '= 2.0' as not being a
        # number -- sending its author looking for the wrong mistake. A lone
        # '=' falls through to the message at the end, which names '=='
        # among the conditions that do exist.
        if condition.startswith(rejected):
            raise ValueError(
                "{0!r} is not one of the conditions; a rule that fires on "
                "exactly the threshold is a different rule, so write the "
                "threshold a step over instead".format(rejected)
            )

    for operator in THRESHOLD_CONDITIONS:
        if not condition.startswith(operator):
            continue
        operand = condition[len(operator) :].strip()
        if not operand:
            raise ValueError(
                "condition {0!r} needs a number to compare against, "
                "for example {0!r} 2.0".format(operator)
            )
        try:
            threshold = _written_number(operand)
        except ValueError:
            raise ValueError("{0!r} is not a number to compare against".format(operand))
        # Not ``math.isfinite``, which raises ``OverflowError`` rather than
        # answering for an integer too wide to become a float -- a 400-digit
        # operand is a number no observation can reach, and it is refused
        # here for the same reason an infinite one is.
        if not _is_finite_number(threshold):
            raise ValueError(
                "a threshold must be a finite number an observation can "
                "reach, got {0!r}; use the 'nan' condition to catch a "
                "metric that is not a finite number".format(operand)
            )
        return operator, threshold

    if condition in (CONDITION_NAN, CONDITION_STALLED):
        return condition, None

    raise ValueError(
        "unknown condition {0!r}; expected one of {1}, 'nan', 'stalled'".format(
            text,
            ", ".join("'{0} <number>'".format(op) for op in THRESHOLD_CONDITIONS),
        )
    )


def condition_name(text: Any) -> str:
    """The condition of a rule a caller is naming rather than defining.

    Clearing or picking out one rule needs the condition without its operand,
    so both spellings answer the same way: ``">"`` names the rule, and
    ``"> 2.0"`` -- the way it was written when it was set -- names it too. The
    operand is parsed and discarded rather than ignored, so a nonsense one is
    still an error here.
    """
    if not isinstance(text, str):
        raise ValueError("condition must be a string, got {0!r}".format(text))
    candidate = " ".join(text.split())
    if candidate in VALID_CONDITIONS:
        return candidate
    return parse_condition(candidate)[0]


@dataclass
class Alert:
    """One alert rule, with the state that decides when it fires.

    ``key`` names the metric watched. ``condition`` is one of
    :data:`VALID_CONDITIONS`, and carries ``threshold`` for the three that
    compare against a constant. ``for_steps`` is the debounce: the condition
    has to hold for that many consecutive observations of ``key`` before the
    rule fires, so a noisy metric crossing a threshold once stays quiet.

    ``patience`` and ``goal`` belong to ``stalled`` alone and are refused on
    any other condition -- a ``patience`` silently doing nothing beside a
    ``>`` is a rule its author would have to read the source to understand.

    The remaining fields are the fold's running state, and are part of the
    stored record on purpose: a restarted server picks up a streak where it
    left off instead of re-arming every rule it reloads.
    """

    key: str
    condition: str
    threshold: Optional[float] = None
    for_steps: int = DEFAULT_FOR_STEPS
    patience: Optional[int] = None
    goal: Optional[str] = None
    action: str = ACTION_TOAST
    message: str = ""
    created_at: float = field(default_factory=time.time)
    streak: int = 0
    fire_count: int = 0
    last_fired_at: Optional[float] = None
    last_fired_step: Optional[int] = None
    best: Optional[float] = None
    since_best: int = 0

    def __post_init__(self):
        # Kept exactly as supplied: a logged key is stored verbatim and every
        # reader compares keys exactly, so a trimmed one would never match.
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("an alert needs the name of the metric to watch")

        if self.condition not in VALID_CONDITIONS:
            raise ValueError(
                "invalid condition {0!r}; expected one of {1}".format(
                    self.condition, ", ".join(VALID_CONDITIONS)
                )
            )
        if self.action not in VALID_ACTIONS:
            raise ValueError(
                "invalid action {0!r}; expected one of {1}".format(
                    self.action, ", ".join(VALID_ACTIONS)
                )
            )

        if self.condition in THRESHOLD_CONDITIONS:
            if not _is_finite_number(self.threshold):
                raise ValueError(
                    "condition {0!r} needs a finite number to compare "
                    "against, got {1!r}".format(self.condition, self.threshold)
                )
            # An integer is left alone rather than floated: it is already
            # exact, and the rounding would land in the stored record and be
            # redone on every load, so the rule would watch the wrong integer
            # for good rather than only in the comparison.
            if not isinstance(self.threshold, int):
                self.threshold = float(self.threshold)
        elif self.threshold is not None:
            raise ValueError(
                "condition {0!r} compares against nothing, so it takes no "
                "threshold".format(self.condition)
            )

        if self.condition == CONDITION_STALLED:
            self.patience = (
                DEFAULT_PATIENCE
                if self.patience is None
                else _positive_int(self.patience, "patience")
            )
            self.goal = DEFAULT_GOAL if self.goal is None else self.goal
            if self.goal not in VALID_GOALS:
                raise ValueError(
                    "invalid goal {0!r}; expected one of {1}".format(
                        self.goal, ", ".join(VALID_GOALS)
                    )
                )
        else:
            if self.patience is not None:
                raise ValueError(
                    "patience applies to the {0!r} condition only".format(
                        CONDITION_STALLED
                    )
                )
            if self.goal is not None:
                raise ValueError(
                    "goal applies to the {0!r} condition only".format(CONDITION_STALLED)
                )

        self.for_steps = _positive_int(self.for_steps, "for_steps")

        if self.message is None:
            self.message = ""
        if not isinstance(self.message, str):
            raise ValueError(
                "an alert message must be a string, got {0!r}".format(self.message)
            )
        self.message = self.message.strip()
        if len(self.message) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                "an alert message is limited to {0} characters".format(
                    MAX_MESSAGE_LENGTH
                )
            )

        # The running state arrives from storage rather than from a caller,
        # and a junk counter would raise out of the request that logged an
        # observation rather than here.
        self.created_at = _optional_number(self.created_at, "created_at")
        if self.created_at is None:
            self.created_at = time.time()
        self.streak = _counter(self.streak, "streak")
        self.fire_count = _counter(self.fire_count, "fire_count")
        self.since_best = _counter(self.since_best, "since_best")
        self.last_fired_at = _optional_number(self.last_fired_at, "last_fired_at")
        self.last_fired_step = _optional_int(self.last_fired_step, "last_fired_step")
        self.best = _optional_number(self.best, "best")

    @property
    def rule_id(self) -> tuple:
        """What makes two rules the same rule.

        A metric is allowed more than one rule -- a threshold and a stall
        watch on the same loss are different questions -- so the condition is
        part of the identity and only a repeat of both replaces.
        """
        return (self.key, self.condition)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "condition": self.condition,
            "threshold": self.threshold,
            "for_steps": self.for_steps,
            "patience": self.patience,
            "goal": self.goal,
            "action": self.action,
            "message": self.message,
            "created_at": self.created_at,
            "streak": self.streak,
            "fire_count": self.fire_count,
            "last_fired_at": self.last_fired_at,
            "last_fired_step": self.last_fired_step,
            "best": self.best,
            "since_best": self.since_best,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Alert":
        return cls(
            key=data["key"],
            condition=data["condition"],
            threshold=data.get("threshold"),
            for_steps=data.get("for_steps", DEFAULT_FOR_STEPS),
            patience=data.get("patience"),
            goal=data.get("goal"),
            action=data.get("action", ACTION_TOAST),
            message=data.get("message", ""),
            created_at=data.get("created_at", time.time()),
            streak=data.get("streak", 0),
            fire_count=data.get("fire_count", 0),
            last_fired_at=data.get("last_fired_at"),
            last_fired_step=data.get("last_fired_step"),
            best=data.get("best"),
            since_best=data.get("since_best", 0),
        )


def build_alert(
    key: Any,
    condition: Any,
    for_steps: Any = DEFAULT_FOR_STEPS,
    patience: Any = None,
    goal: Any = None,
    action: Any = ACTION_TOAST,
    message: Any = None,
) -> Alert:
    """An :class:`Alert` from the written form a caller sends.

    The one entry point that turns a request into a rule: it reads the
    operand out of ``condition`` and lets :class:`Alert` refuse everything
    else, so a caller gets one kind of error however the rule is wrong.
    """
    parsed, threshold = parse_condition(condition)
    return Alert(
        key=key,
        condition=parsed,
        threshold=threshold,
        for_steps=DEFAULT_FOR_STEPS if for_steps is None else for_steps,
        patience=patience,
        goal=goal,
        action=ACTION_TOAST if action is None else action,
        message=message,
    )
