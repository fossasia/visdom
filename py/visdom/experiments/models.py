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
from collections.abc import Sequence
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


class LazyMetricList(Sequence):
    """A metric series held as the dicts it is stored as, built on demand.

    A run's metrics are parsed far more often than they are read: every write
    of the experiment blob re-parses the whole series, and so does every
    search scan, comparison and hyper-parameter pane. What those callers want
    is the *latest* value per key or the serialised form back again — not one
    :class:`Metric` object per observation ever logged. Keeping the stored
    dicts and building a ``Metric`` only when one is actually indexed makes
    parsing an experiment cost the same whatever its history, which is what
    stops logging observation *m* from costing Θ(m).

    This is a ``Sequence``, so ``len``, indexing, slicing, iteration,
    ``reversed`` and ``in`` read exactly as they did when the field held a
    list. Equality against a list is spelled out because the ``Sequence``
    mixins do not provide it.

    The stored list is treated as read-only. It is the list living inside the
    environment's experiment blob, and the server hands that blob to the
    storage worker without copying it
    (``server.handlers.experiments_handler._resident_experiments``), so
    appending to it in place would mutate what another thread is reading.
    :meth:`append_data` therefore copies it first and appends to the copy it
    then owns; :meth:`publish` marks the list as handed out again.
    """

    __slots__ = ("_data", "_objects", "_shared")

    def __init__(self, data: list, shared: bool = True):
        self._data = data
        self._objects: dict[int, Metric] = {}
        self._shared = shared

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self._data)))]
        if index < 0:
            index += len(self._data)
        if not 0 <= index < len(self._data):
            raise IndexError("metric index out of range")
        metric = self._objects.get(index)
        if metric is None:
            metric = Metric.from_dict(self._data[index])
            self._objects[index] = metric
        return metric

    def __eq__(self, other) -> bool:
        if isinstance(other, LazyMetricList):
            return self._data == other._data
        if isinstance(other, (list, tuple)):
            return len(self) == len(other) and all(
                mine == theirs for mine, theirs in zip(self, other)
            )
        return NotImplemented

    def __repr__(self) -> str:
        return "LazyMetricList({0!r})".format(self._data)

    def publish(self) -> list:
        """Return the stored list, marking it as handed out to a caller.

        Whoever receives it may keep it — :meth:`Experiment.to_dict` puts it
        straight into the env blob — so the next :meth:`append_data` must copy
        rather than touch it.
        """
        self._shared = True
        return self._data

    def append(self, metric: "Metric") -> None:
        """Append ``metric``, copying the stored list first if it was handed out.

        The copy is the correctness condition, not an optimisation: the list
        may be the one inside a blob the storage worker is iterating, and a
        list that grows underneath an iteration raises there. Appending to a
        private copy and letting :meth:`Experiment.to_dict` rebind the blob
        keeps the worker's view whole -- the most it can see is a slightly
        older experiment, which is what it was always promised.
        """
        if self._shared:
            self._data = list(self._data)
            self._shared = False
        self._objects[len(self._data)] = metric
        self._data.append(metric.to_dict())

    def latest_values(self) -> dict:
        """Return ``{key: latest value}`` without building a single ``Metric``.

        Walked newest-first with ``setdefault`` so the most recent observation
        of each key wins, which is the rule
        :func:`~visdom.experiments.query.build_record` has always applied. An
        entry with no usable ``key`` is skipped rather than raising, as the
        flatten path in :mod:`~visdom.experiments.records` already does.
        """
        latest: dict = {}
        for data in reversed(self._data):
            key = data.get("key")
            if key is None:
                continue
            latest.setdefault(key, data.get("value"))
        return latest

    def latest(self, key: str) -> Optional["Metric"]:
        """Return the most recently stored metric named ``key``, or ``None``."""
        for index in range(len(self._data) - 1, -1, -1):
            if self._data[index].get("key") == key:
                return self[index]
        return None


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
    metrics: Sequence[Metric] = field(default_factory=list)
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
        """Append a metric observation to this experiment's time series.

        An experiment read from a stored blob holds its series as a
        :class:`LazyMetricList`, which stores the observation in its stored
        form; one built by hand holds plain ``Metric`` objects and keeps
        doing so. Either way appending costs the same whether the run has
        logged ten observations or ten thousand.
        """
        metric = Metric(key=key, value=value, step=step)
        self.metrics.append(metric)
        return metric

    def latest_metric(self, key: str) -> Optional[Metric]:
        """Return the most recently logged metric named ``key``, or ``None``."""
        if isinstance(self.metrics, LazyMetricList):
            return self.metrics.latest(key)
        for metric in reversed(self.metrics):
            if metric.key == key:
                return metric
        return None

    def latest_metric_values(self) -> dict:
        """Return ``{key: latest value}`` across this experiment's series.

        The one shape every reader of a metric series actually wants: a
        comparison, a query record and a hyper-parameter pane all show one
        number per key, and it is the newest. Answering it here lets an
        experiment read from a blob answer from the stored dicts without
        building a ``Metric`` per observation first.
        """
        if isinstance(self.metrics, LazyMetricList):
            return self.metrics.latest_values()
        latest: dict = {}
        for metric in reversed(self.metrics):
            latest.setdefault(metric.key, metric.value)
        return latest

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
        """Return the JSON-serialisable dict stored under ``env["experiment"]``.

        A series still in its stored form is handed back as it stands rather
        than rebuilt a dict at a time, so serialising an experiment costs the
        same whatever its history. The list is marked as handed out, which is
        what makes the next :meth:`add_metric` copy it instead of appending to
        a list this dict — and, once it is stored, the env blob — now holds.
        """
        metrics = self.metrics
        metric_data = (
            metrics.publish()
            if isinstance(metrics, LazyMetricList)
            else [m.to_dict() for m in metrics]
        )
        return {
            "env_id": self.env_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "params": [p.to_dict() for p in self.params],
            "metrics": metric_data,
            "tags": [t.to_dict() for t in self.tags],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Experiment":
        """Rebuild an :class:`Experiment` from its :meth:`to_dict` form.

        Params and tags are rebuilt as objects — there are a handful of each,
        and every caller reads them. The metric series is wrapped in a
        :class:`LazyMetricList` instead, so reading an experiment costs
        nothing per observation logged; anything that is not a list is
        rebuilt the way it always was, since only a list can be wrapped.
        """
        raw_metrics = data.get("metrics", [])
        metrics = (
            LazyMetricList(raw_metrics)
            if isinstance(raw_metrics, list)
            else [Metric.from_dict(m) for m in raw_metrics]
        )
        return cls(
            env_id=data["env_id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=data.get("status", STATUS_RUNNING),
            created_at=data.get("created_at", time.time()),
            finished_at=data.get("finished_at"),
            params=[Param.from_dict(p) for p in data.get("params", [])],
            metrics=metrics,
            tags=[Tag.from_dict(t) for t in data.get("tags", [])],
        )
