#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Metric alert rules, and the folding of observations into them.

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
and it reads it with ``int()`` or ``float()`` -- an integer operand stays an
integer, because ``float()`` would round the very value the rule names;
nothing here evaluates user text.

Evaluation is a fold, not a query. Every rule carries its own running state
-- the streak of matching observations, the best value seen so far, how many
observations have passed since -- so deciding whether an observation fires
costs the same whether the run has logged ten of them or ten thousand, and
reads nothing but the rule itself. That is what lets it run on the event loop
beside the append rather than behind a re-read of the environment.

A rule fires on the observation that *completes* its streak and not again
until the streak breaks, so a metric that stays over its threshold for an
hour is one notification rather than one per observation. An observation
that is not a finite number does not break a streak -- an integer too wide
to become a float among them, which is the same thing spelled as an ``int``:
a diverging run is precisely the one that logs them, and re-arming there
would spend a second notification on the run that already sent one.
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

# The fields that are the fold's running state rather than the rule its
# author wrote. They are stored with the rule so that a restart finds the
# streak it left off at, and they are what :meth:`Alert.rearmed` -- and so
# every replacement of a rule -- starts over from.
STATE_FIELDS = (
    "streak",
    "fire_count",
    "last_fired_at",
    "last_fired_step",
    "best",
    "since_best",
)

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


def _overflows_float(value: Any) -> bool:
    """Whether ``value`` is an integer too wide to become a float.

    JSON puts no bound on integer length, so an observation can hold one, and
    ``float()`` raises ``OverflowError`` on it rather than answering. An
    integer that wide is also what a diverging accumulator looks like when it
    is logged as an ``int`` rather than as a ``float``, which is why
    :func:`_is_diverged` counts it as one.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    try:
        float(value)
    except OverflowError:
        return True
    return False


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


def _is_diverged(value: Any) -> bool:
    """Whether ``value`` is an observation that is not a finite number.

    That is a NaN or an infinity -- and ``None``, which is the same thing
    after a round trip. Standard JSON cannot spell a non-finite number, so
    ``NanSafeEncoder`` writes one as ``null``: by the time a diverged metric
    reaches the server it *is* ``None``, and a condition that only matched the
    float would never fire for any client that went over the wire. The store's
    own ``_is_absent`` treats the two spellings as one for the same reason.

    An integer too wide to become a float counts as one too. It is a number
    no threshold can be compared against, and the reason it belongs here
    rather than among the values of the wrong kind is the streak: a rule that
    fired on a run which is now overflowing must not be re-armed by the
    overflow, whichever of the two ways the client spelled it.

    A metric logged as a string is not covered: that is a value of the wrong
    kind rather than arithmetic that went wrong, and it is not absent either.
    """
    if value is None:
        return True
    if _overflows_float(value):
        return True
    if isinstance(value, bool) or not isinstance(value, float):
        return False
    return not math.isfinite(value)


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

    def rearmed(self) -> "Alert":
        """A copy of this rule with the fold's running state back at its start.

        What a replacement is built from. Re-stating a rule is how its author
        changes it, and the rule they get back has to be judged by the
        observations it sees rather than by the ones the rule it replaced saw:
        a streak only fires as it is completed, so a replacement that
        inherited a streak which had already fired would stay silent for the
        whole run that follows. The rule handed in may even be one the caller
        read off the record, state and all.

        Loading a rule from storage and forking an environment keep the state
        they find, and go through :meth:`from_dict` rather than through here.
        """
        return Alert.from_dict(
            {
                name: value
                for name, value in self.to_dict().items()
                if name not in STATE_FIELDS
            }
        )

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


@dataclass(frozen=True)
class AlertEvent:
    """A rule that has just fired, and the observation that fired it.

    ``best`` is the stall watch's best value as it stood at that moment, read
    off the rule here rather than when the text is built: the rule goes on
    folding, and a later observation -- in the batch this event came out of,
    even -- can improve it, leaving the notification quoting a best that was
    never the one the rule stalled against.
    """

    alert: Alert
    value: Any
    step: Optional[int] = None
    best: Optional[float] = None

    def __post_init__(self):
        if self.best is None:
            object.__setattr__(self, "best", self.alert.best)


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


def _matches(alert: Alert, value: Any) -> bool:
    """Whether this observation satisfies ``alert``, folding in its state.

    The stall watch is the one condition that cannot be a pure predicate: it
    is the series that stalls, not the value, so the best seen so far and the
    count since it was seen are updated here.
    """
    if alert.condition == CONDITION_NAN:
        return _is_diverged(value)

    number = _as_number(value)
    if number is None:
        return False

    if alert.condition == CONDITION_STALLED:
        improved = alert.best is None or (
            number < alert.best if alert.goal == GOAL_MIN else number > alert.best
        )
        if improved:
            alert.best = number
            alert.since_best = 0
            return False
        alert.since_best += 1
        return alert.since_best >= alert.patience

    if alert.condition == CONDITION_GT:
        return number > alert.threshold
    if alert.condition == CONDITION_LT:
        return number < alert.threshold
    return number == alert.threshold


def observe(alert: Alert, value: Any, step: Optional[int] = None) -> bool:
    """Fold one observation of ``alert.key`` in; return whether it fires.

    The streak is compared to ``for_steps`` for equality rather than for
    having reached it, which is what makes a rule fire once per unbroken run
    of matching observations: the streak keeps climbing past the threshold
    without firing again, and an observation that does not match resets it and
    re-arms the rule.

    An observation that is not a finite number is the exception, and leaves
    the streak where it is. It is not evidence that the condition stopped
    holding -- a run that is already over its threshold is the one that
    starts logging nulls -- and resetting on it would re-arm the rule and
    spend a second notification on the same run. A value of the wrong kind
    still breaks the streak: that is a metric logged as something other than
    a number, not arithmetic that went wrong.
    """
    if alert.condition != CONDITION_NAN and _is_diverged(value):
        return False

    if _matches(alert, value):
        alert.streak += 1
    else:
        alert.streak = 0
        return False

    if alert.streak != alert.for_steps:
        return False

    alert.fire_count += 1
    alert.last_fired_at = time.time()
    alert.last_fired_step = step
    return True


def evaluate(experiment, observations, step: Optional[int] = None) -> list:
    """Fold ``observations`` into ``experiment``'s rules; return what fired.

    ``observations`` is the ``(key, value)`` sequence just appended to the
    record -- the values themselves, not the series they were appended to.
    Nothing here reads the metric history, so a run with a long one costs no
    more than a run on its first step.

    The rules are mutated in place, so the caller's next write of the
    experiment carries the new state. That is the only reason this is called
    before the record is serialised rather than after.
    """
    alerts = getattr(experiment, "alerts", None)
    if not alerts:
        return []

    watched: dict = {}
    for alert in alerts:
        watched.setdefault(alert.key, []).append(alert)

    fired = []
    for key, value in observations:
        for alert in watched.get(key, ()):
            if observe(alert, value, step):
                fired.append(AlertEvent(alert=alert, value=value, step=step))
    return fired


def _written(number: Any) -> str:
    """``number`` as it goes into a notification, without rounding it.

    An integer is written out in full: it is already exact, and a threshold
    the grammar and the record went to the trouble of keeping exact would
    otherwise be rounded by the one thing that ever shows it to its author --
    ``"{0:.12g}"`` writes ``9007199254740993`` as ``'9.00719925474e+15'``,
    and writes the threshold beside it the same way, so the message would
    name one number twice and read as though the rule had fired on its own
    threshold.

    A float is written with ``repr``, the shortest text that reads back as
    the same float, rather than to a fixed number of significant digits.
    Twelve is enough for a rule on ``> 1.0000001`` and not for one on
    ``> 1.000000000000001``, which is the argument against picking a number
    at all: whatever it is, some pair of values either side of a threshold
    rounds to one number and the notification says the metric equals the
    threshold it just crossed.
    """
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        return str(number)
    return repr(number)


def describe(event: AlertEvent, env_id: Optional[str] = None) -> str:
    """The notification text for a fired rule.

    A caller's own ``message`` is used verbatim when it set one -- it is the
    sentence they wanted, and interpolating into it would make the rule's text
    a format string. Otherwise the message is built from the rule, the
    observation that fired it and the environment it fired in, because a toast
    arrives with none of that context around it.

    Numbers are written by :func:`_written`, which rounds nothing: a rule on
    ``> 1.0000001`` that fired on ``1.00000011`` has to say so rather than
    report that "loss is 1, > 1", and a threshold written as an integer has
    to come back as the integer it was written as.
    """
    alert = event.alert
    where = "" if not env_id else "{0}: ".format(env_id)
    if alert.message:
        return "{0}{1}".format(where, alert.message)

    at = "" if event.step is None else " at step {0}".format(event.step)

    if alert.condition == CONDITION_NAN:
        # ``None`` is what a NaN or an infinity looks like after the JSON on
        # the wire has been through it, and "is None" is not what happened.
        # An integer too wide to become a float is worded the same way: its
        # four hundred digits are not what its reader needs, and the rule
        # caught it for being a number nothing can compare against.
        arrived = (
            "not a finite number"
            if event.value is None or _overflows_float(event.value)
            else _written(event.value)
        )
        return "{0}{1} is {2}{3}".format(where, alert.key, arrived, at)

    if alert.condition == CONDITION_STALLED:
        best = "" if event.best is None else " (best {0})".format(_written(event.best))
        return "{0}{1} has not improved in {2} observations{3}{4}".format(
            where, alert.key, alert.patience, best, at
        )

    held = (
        "" if alert.for_steps == 1 else " for {0} observations".format(alert.for_steps)
    )
    return "{0}{1} is {2}, {3} {4}{5}{6}".format(
        where,
        alert.key,
        _written(event.value),
        alert.condition,
        _written(alert.threshold),
        held,
        at,
    )
