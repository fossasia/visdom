#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Diffing a set of experiments field by field.

Where :mod:`~visdom.experiments.query` flattens one experiment into a record to
match a predicate against, this module lines several experiments up beside each
other and reports, per section (params/metrics/tags), which fields they agree on
and which they do not. It is pure: it reads experiment objects and returns a
JSON-serialisable dict, touching no storage. :meth:`ExperimentStore.compare`
selects the experiments and delegates the arithmetic here.

The interesting output is ``differing``: given a dozen runs of the same model,
it is the short list of knobs that actually changed between them.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Protocol, Sequence

from visdom.experiments.query import ExperimentLike


class ComparableExperiment(ExperimentLike, Protocol):
    """An :class:`ExperimentLike` that can also serialise itself.

    :func:`build_comparison` echoes the compared experiments back in full, which
    the query layer's protocol alone does not cover.
    """

    def to_dict(self) -> dict:
        ...


def _param_values(experiment: ComparableExperiment) -> dict:
    """Return ``{name: value}`` for the experiment's params."""
    return {param.key: param.value for param in experiment.params}


def _metric_values(experiment: ComparableExperiment) -> dict:
    """Return ``{name: latest value}`` for the experiment's metrics.

    Metrics are a time series, but a comparison wants one number per run, so the
    most recent observation wins — the same value
    :func:`~visdom.experiments.query.build_record` compares on, so a run found by
    ``acc > 0.9`` shows that same ``acc`` here.
    """
    latest: dict[str, Any] = {}
    for metric in reversed(experiment.metrics):
        latest.setdefault(metric.key, metric.value)
    return latest


def _tag_values(experiment: ComparableExperiment) -> dict:
    """Return ``{name: value}`` for the experiment's tags."""
    return {tag.key: tag.value for tag in experiment.tags}


_SECTION_READERS = {
    "params": _param_values,
    "metrics": _metric_values,
    "tags": _tag_values,
}

SECTIONS = tuple(_SECTION_READERS)
"""The section names :func:`build_comparison` diffs, in the order it emits them."""


def _same_value(a: Any, b: Any) -> bool:
    """Return ``True`` if two logged values should count as the same.

    Stricter than ``==`` about bools, because ``True == 1`` in Python and a run
    launched with ``amp=True`` did not use the same setting as one launched with
    ``amp=1``; :mod:`~visdom.experiments.query` draws the same line by refusing to
    treat a bool as a number. Looser than ``==`` about NaN, which is never equal
    to itself: a metric that is NaN in every run agrees across them, and calling
    that a difference would bury the real ones.
    """
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
    return bool(a == b)


def _group_values(present: dict) -> list:
    """Cluster ``{env_id: value}`` into ``[{"value": v, "env_ids": [...]}, ...]``.

    Answers "which runs used the same value?" rather than only "did they all?" —
    with three runs on two learning rates, the two that match end up in one group
    and the odd one out in another.

    The obvious ``defaultdict`` keyed by value cannot be used here. Values need
    not be hashable (a param may hold a list), ``hash(True) == hash(1)`` with
    ``True == 1`` so a dict would silently merge them and undo the bool rule
    :func:`_same_value` exists to enforce, and NaN never equals itself so it would
    never group. Scanning the groups with :func:`_same_value` keeps one definition
    of sameness for the whole module; the run count per comparison is small.

    Groups appear in the order their value was first seen, and env_ids within a
    group keep the order the runs were compared in.
    """
    groups: list = []
    for env_id, value in present.items():
        for group in groups:
            if _same_value(group["value"], value):
                group["env_ids"].append(env_id)
                break
        else:
            groups.append({"value": value, "env_ids": [env_id]})
    return groups


def _compare_section(per_env: dict) -> dict:
    """Diff one section across the experiments in ``per_env``.

    ``per_env`` maps env_id to that experiment's ``{field: value}`` for the
    section. Each field gets its per-run ``values``, its ``groups`` of runs that
    agree, and a place in ``shared`` or ``differing``.

    A field counts as shared only when every experiment carries it *and* they all
    agree — one group holding every run. A value one run never logged is a
    difference between the runs, not a consensus among those that happen to have
    it, and that run appears in no group for the field.
    """
    fields = sorted({field for values in per_env.values() for field in values})
    values = {
        field: {
            env_id: env_values[field]
            for env_id, env_values in per_env.items()
            if field in env_values
        }
        for field in fields
    }
    groups = {field: _group_values(values[field]) for field in fields}
    shared = {
        field: groups[field][0]["value"]
        for field in fields
        if len(groups[field]) == 1 and len(values[field]) == len(per_env)
    }
    return {
        "fields": fields,
        "shared": shared,
        "differing": [field for field in fields if field not in shared],
        "values": values,
        "groups": groups,
    }


def build_comparison(experiments: Iterable[ComparableExperiment]) -> dict:
    """Compare ``experiments`` field by field and return the result as a dict.

    The reply echoes the compared runs (``env_ids`` in the order given, and the
    full ``experiments``) alongside one diff per section::

        {
          "env_ids": ["run-a", "run-b", "run-c"],
          "experiments": [{...}, {...}, {...}],
          "params": {
            "fields": ["epochs", "lr"],
            "shared": {"epochs": 10},
            "differing": ["lr"],
            "values": {"lr": {"run-a": 0.1, "run-b": 0.001, "run-c": 0.1},
                       "epochs": {"run-a": 10, "run-b": 10, "run-c": 10}},
            "groups": {
              "epochs": [{"value": 10, "env_ids": ["run-a", "run-b", "run-c"]}],
              "lr": [{"value": 0.1, "env_ids": ["run-a", "run-c"]},
                     {"value": 0.001, "env_ids": ["run-b"]}]
            }
          },
          "metrics": {...}, "tags": {...}
        }

    ``fields`` is every name any run has, sorted. ``shared`` holds the fields all
    runs carry with the same value, and ``differing`` is the rest — the ones that
    vary or that some run is missing; together they answer "what changed?" at a
    glance. ``values`` gives the raw per-run value, omitting the runs that never
    logged the field.

    ``groups`` answers the finer question "*which* runs agree?", clustering the
    runs by value per field: above, ``lr`` differs overall, but run-a and run-c
    still used the same one. A field is in ``shared`` exactly when its ``groups``
    is a single cluster holding every compared run, so the two never disagree.

    Comparing a single experiment is legal and puts everything it has in
    ``shared``; comparing none yields empty sections.
    """
    ordered: Sequence[ComparableExperiment] = list(experiments)
    comparison = {
        "env_ids": [experiment.env_id for experiment in ordered],
        "experiments": [experiment.to_dict() for experiment in ordered],
    }
    for section, read in _SECTION_READERS.items():
        comparison[section] = _compare_section(
            {experiment.env_id: read(experiment) for experiment in ordered}
        )
    return comparison
