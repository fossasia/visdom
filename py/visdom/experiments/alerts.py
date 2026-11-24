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
and it reads it with ``float()``; nothing here evaluates user text.

Evaluation is a fold, not a query. Every rule carries its own running state
-- the streak of matching observations, the best value seen so far, how many
observations have passed since -- so deciding whether an observation fires
costs the same whether the run has logged ten of them or ten thousand, and
reads nothing but the rule itself. That is what lets it run on the event loop
beside the append rather than behind a re-read of the environment.

A rule fires on the observation that *completes* its streak and not again
until the streak breaks, so a metric that stays over its threshold for an
hour is one notification rather than one per observation. An observation
that is not a finite number does not break a streak: a diverging run is
precisely the one that logs them, and re-arming there would spend a second
notification on the run that already sent one.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

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
ACTION_WEBHOOK = "webhook"
VALID_ACTIONS = (ACTION_TOAST, ACTION_WEBHOOK)

# The schemes a webhook may be posted to. Everything else -- ``file:``,
# ``gopher:``, a scheme the url author invented -- is refused where the rule
# is written rather than skipped where it would have been sent, so a rule that
# can never be delivered cannot be stored in the first place.
WEBHOOK_SCHEMES = ("http", "https")

# A url is user input kept on the record, so it is bounded the way the message
# is. Browsers stop caring somewhere above 2000 characters and so does this.
MAX_URL_LENGTH = 2000

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


def _is_diverged(value: Any) -> bool:
    """Whether ``value`` is an observation that is not a finite number.

    That is a NaN or an infinity -- and ``None``, which is the same thing
    after a round trip. Standard JSON cannot spell a non-finite number, so
    ``NanSafeEncoder`` writes one as ``null``: by the time a diverged metric
    reaches the server it *is* ``None``, and a condition that only matched the
    float would never fire for any client that went over the wire. The store's
    own ``_is_absent`` treats the two spellings as one for the same reason.

    A metric logged as a string is not covered: that is a value of the wrong
    kind rather than arithmetic that went wrong, and it is not absent either.
    """
    if value is None:
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


def parse_webhook_url(text: Any) -> str:
    """The url a webhook rule posts to, refusing everything it is not.

    Shape only: a scheme this server speaks, a host to send it to, no
    credentials, and a length. *Whether* that host may be reached is a
    different question with a different answer, asked by
    :mod:`visdom.server.webhooks` -- it depends on the flags the server was
    started with rather than on the rule, so the same rule is legal on one
    server and refused on another, and a rule reloaded from a record written
    before those flags changed still has to parse.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError(
            "the {0!r} action needs a url to post to".format(ACTION_WEBHOOK)
        )
    url = text.strip()
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(
            "a webhook url is limited to {0} characters".format(MAX_URL_LENGTH)
        )

    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        # Read for the check, not for the value. A bracketed address that is
        # not one and a port that is not a number both raise out of the
        # accessor rather than out of the split, which is why all three are in
        # one try: a url the stdlib cannot take apart is not a url this server
        # should be storing.
        parsed.port
    except ValueError as error:
        raise ValueError("{0!r} is not a url: {1}".format(url, error))

    if parsed.scheme not in WEBHOOK_SCHEMES:
        raise ValueError(
            "a webhook url must be {0}, got {1!r}".format(
                " or ".join(WEBHOOK_SCHEMES), parsed.scheme or url
            )
        )
    if "@" in parsed.netloc:
        # Credentials in a url are a secret written onto the experiment record
        # and the oldest way to make a hostile url read as a friendly one:
        # https://hooks.example.com@attacker.example/ is a request to
        # attacker.example. Refused rather than stripped, so nobody is told
        # their secret was kept and then quietly dropped.
        raise ValueError("a webhook url must not carry credentials")
    if not host:
        raise ValueError("{0!r} names no host to post to".format(url))
    return url


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
    ``url`` is the same shape of rule for ``action``: required by ``webhook``
    and refused by ``toast``, which posts nowhere.

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
    url: str = ""
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

        if self.url is None:
            self.url = ""
        if self.action == ACTION_WEBHOOK:
            self.url = parse_webhook_url(self.url)
        elif self.url:
            raise ValueError(
                "a url applies to the {0!r} action only; {1!r} posts nowhere".format(
                    ACTION_WEBHOOK, self.action
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
            "url": self.url,
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
            url=data.get("url", ""),
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
    url: Any = None,
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
        url=url,
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


def describe(event: AlertEvent, env_id: Optional[str] = None) -> str:
    """The notification text for a fired rule.

    A caller's own ``message`` is used verbatim when it set one -- it is the
    sentence they wanted, and interpolating into it would make the rule's text
    a format string. Otherwise the message is built from the rule, the
    observation that fired it and the environment it fired in, because a toast
    arrives with none of that context around it.

    Numbers are written to twelve significant digits rather than the six
    ``:g`` defaults to, which is what keeps the crossing visible: a rule on
    ``> 1.0000001`` that fired on ``1.00000011`` would otherwise report that
    "loss is 1, > 1".
    """
    alert = event.alert
    where = "" if not env_id else "{0}: ".format(env_id)
    if alert.message:
        return "{0}{1}".format(where, alert.message)

    at = "" if event.step is None else " at step {0}".format(event.step)

    if alert.condition == CONDITION_NAN:
        # ``None`` is what a NaN or an infinity looks like after the JSON on
        # the wire has been through it, and "is None" is not what happened.
        arrived = "not a finite number" if event.value is None else str(event.value)
        return "{0}{1} is {2}{3}".format(where, alert.key, arrived, at)

    if alert.condition == CONDITION_STALLED:
        best = "" if event.best is None else " (best {0:.12g})".format(event.best)
        return "{0}{1} has not improved in {2} observations{3}{4}".format(
            where, alert.key, alert.patience, best, at
        )

    held = (
        "" if alert.for_steps == 1 else " for {0} observations".format(alert.for_steps)
    )
    return "{0}{1} is {2:.12g}, {3} {4:.12g}{5}{6}".format(
        where,
        alert.key,
        event.value,
        alert.condition,
        alert.threshold,
        held,
        at,
    )
