#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Metric alert rules: what one is, and what it will accept.

An :class:`Alert` is a rule attached to one experiment: a metric name, a
condition, and the bookkeeping that decides when the condition has held for
long enough to be worth telling someone about. Rules live on the experiment
record alongside the params and metrics they watch, so they are persisted,
searched and forked with the environment and survive a server restart.

A condition is a **fixed enum with a numeric operand**, never an expression:
``>``, ``<`` and ``==`` compare against a constant, ``nan`` catches an
observation that is not a finite number -- including the ``null`` a NaN
becomes on the wire -- and ``stalled`` catches a metric that has stopped
improving. :func:`parse_condition` is the only thing that reads the operand,
and it reads it with ``float()``; nothing here evaluates user text.

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
from typing import Any, Optional

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


def _is_finite_number(value: Any) -> bool:
    """Whether ``value`` is a real number that can be compared with another.

    A ``bool`` is excluded so that ``True`` does not compare as ``1``, and an
    integer too wide to become a float is excluded rather than raising --
    JSON puts no bound on integer length, so an observation can hold one, and
    both ``math.isfinite`` and the conversion below would otherwise raise
    ``OverflowError`` out of a request. The same exclusion
    :func:`~visdom.experiments.store._is_number` makes, for the same reason.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _as_number(value: Any) -> Optional[float]:
    """``value`` as a float, or ``None`` if it is not a finite number.

    A metric logged as a string, a ``None`` or a ``NaN`` cannot be over or
    under a threshold, and saying so here keeps every condition free of the
    question.
    """
    if not _is_finite_number(value):
        return None
    try:
        return float(value)
    except OverflowError:  # pragma: no cover - _is_finite_number refuses these
        return None


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


def parse_condition(text: Any) -> tuple:
    """Split a written condition into ``(condition, threshold)``.

    The spelling a caller writes is the one in the docs --
    ``"> 2.0"``, ``"< 0.5"``, ``"== 0"``, ``"nan"``, ``"stalled"`` -- and this
    is the only place it is read. The operand goes through ``float()``, so the
    worst a hostile condition can be is a ``ValueError``.

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
            threshold = float(operand)
        except ValueError:
            raise ValueError("{0!r} is not a number to compare against".format(operand))
        if not math.isfinite(threshold):
            raise ValueError(
                "a threshold must be finite, got {0!r}; use the 'nan' "
                "condition to catch a non-finite metric".format(operand)
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
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("an alert needs the name of the metric to watch")
        self.key = self.key.strip()

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
