#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Schemas for the experiment metadata attached to Visdom environments.

An :class:`Experiment` is a small, JSON-serialisable record describing a
training run: the hyper-parameters it was launched with, the metrics logged
against it over time, and free-form tags. It is stored inside its
environment's persisted data under the ``"experiment"`` key, so it travels
with the env through the existing ``DataStore`` and needs no new storage
backend.

The classes are deliberately thin: they validate and (de)serialise, and are
the single definition of the on-disk metadata shape that the query and search
layers build on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
VALID_STATUSES = (STATUS_RUNNING, STATUS_FINISHED, STATUS_FAILED)


class ExperimentFinishedError(Exception):
    """Raised when logging to an experiment already in a terminal state."""


def infer_dtype(value: Any) -> str:
    """Return a stable dtype tag (``bool``/``int``/``float``/``str``) for ``value``.

    Used so the query layer can cast a stored string back to the type it was
    logged as. ``bool`` is checked before ``int`` because ``bool`` is an ``int``
    subclass in Python and would otherwise be mislabelled.
    """
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


@dataclass
class Param:
    """A single hyper-parameter: its name, value, and inferred dtype."""

    key: str
    value: Any
    dtype: str = ""

    def __post_init__(self):
        if not self.dtype:
            self.dtype = infer_dtype(self.value)

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "dtype": self.dtype}

    @classmethod
    def from_dict(cls, data: dict) -> "Param":
        return cls(
            key=data["key"],
            value=data.get("value"),
            dtype=data.get("dtype", ""),
        )


@dataclass
class Metric:
    """One logged metric observation, optionally at a training ``step``."""

    key: str
    value: float
    step: Optional[int] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "step": self.step,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Metric":
        return cls(
            key=data["key"],
            value=data.get("value"),
            step=data.get("step"),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class Tag:
    """A free-form ``key=value`` label used to group/filter experiments."""

    key: str
    value: str

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict) -> "Tag":
        return cls(key=data["key"], value=data.get("value", ""))


@dataclass
class Experiment:
    """Metadata for one experiment, keyed to the environment it ran in.

    ``env_id`` is the only required field; ``name`` defaults to it. ``params``,
    ``metrics`` and ``tags`` are held as typed lists but are keyed by name in
    practice, so :meth:`set_param`/:meth:`set_tag` replace-or-append while
    :meth:`add_metric` always appends (metrics form a time series).
    """

    env_id: str
    name: str = ""
    description: str = ""
    status: str = STATUS_RUNNING
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    params: list[Param] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)

    def __post_init__(self):
        if not self.name:
            self.name = self.env_id
        if self.status not in VALID_STATUSES:
            raise ValueError(
                "invalid status {0!r}; expected one of {1}".format(
                    self.status, ", ".join(VALID_STATUSES)
                )
            )

    def set_param(self, key: str, value: Any) -> Param:
        """Set ``key`` to ``value``, replacing any existing param of that name."""
        param = Param(key=key, value=value)
        for i, existing in enumerate(self.params):
            if existing.key == key:
                self.params[i] = param
                return param
        self.params.append(param)
        return param

    def get_param(self, key: str) -> Optional[Param]:
        """Return the param named ``key``, or ``None`` if it was never set."""
        for param in self.params:
            if param.key == key:
                return param
        return None

    def add_metric(self, key: str, value: float, step: Optional[int] = None) -> Metric:
        """Append a metric observation to this experiment's time series."""
        metric = Metric(key=key, value=value, step=step)
        self.metrics.append(metric)
        return metric

    def latest_metric(self, key: str) -> Optional[Metric]:
        """Return the most recently logged metric named ``key``, or ``None``."""
        for metric in reversed(self.metrics):
            if metric.key == key:
                return metric
        return None

    def set_tag(self, key: str, value: str) -> Tag:
        """Set tag ``key`` to ``value``, replacing any existing tag of that name."""
        tag = Tag(key=key, value=value)
        for i, existing in enumerate(self.tags):
            if existing.key == key:
                self.tags[i] = tag
                return tag
        self.tags.append(tag)
        return tag

    def is_terminal(self) -> bool:
        """True if the experiment is in a terminal state (finished/failed)."""
        return self.status in (STATUS_FINISHED, STATUS_FAILED)

    def finish(self, status: str = STATUS_FINISHED) -> None:
        """Mark the experiment terminal and stamp ``finished_at``.

        ``status`` must be a terminal state (``finished`` or ``failed``);
        passing ``running`` is rejected since finishing implies it stopped.
        """
        if status not in (STATUS_FINISHED, STATUS_FAILED):
            raise ValueError(
                "finish status must be {0!r} or {1!r}, got {2!r}".format(
                    STATUS_FINISHED, STATUS_FAILED, status
                )
            )
        self.status = status
        self.finished_at = time.time()

    def to_dict(self) -> dict:
        """Return the JSON-serialisable dict stored under ``env["experiment"]``."""
        return {
            "env_id": self.env_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "params": [p.to_dict() for p in self.params],
            "metrics": [m.to_dict() for m in self.metrics],
            "tags": [t.to_dict() for t in self.tags],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Experiment":
        """Rebuild an :class:`Experiment` from its :meth:`to_dict` form."""
        return cls(
            env_id=data["env_id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=data.get("status", STATUS_RUNNING),
            created_at=data.get("created_at", time.time()),
            finished_at=data.get("finished_at"),
            params=[Param.from_dict(p) for p in data.get("params", [])],
            metrics=[Metric.from_dict(m) for m in data.get("metrics", [])],
            tags=[Tag.from_dict(t) for t in data.get("tags", [])],
        )
