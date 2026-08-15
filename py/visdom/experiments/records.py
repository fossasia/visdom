#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Flatten experiments into the compact records payload the hparams pane reads.

An :class:`~visdom.experiments.models.Experiment` stores its params, metrics
and tags as lists of ``{"key": ..., "value": ...}`` dicts. The hyper-parameter
pane instead wants one row per run with those collapsed into ``{name: value}``
maps, plus the union of names to use as columns. This module is the single
definition of that transform, used by the ``experiments/hparams`` endpoint over
:meth:`~visdom.experiments.models.Experiment.to_dict`.
"""


def flatten_experiments(experiments):
    """Flatten experiment dicts into a compact records payload.

    ``experiments`` is a list of experiment dicts in the shape of
    :meth:`~visdom.experiments.models.Experiment.to_dict`. Each run's
    ``params``/``metrics``/``tags`` lists are collapsed into per-run
    ``{name: value}`` maps so a table/parallel-coordinates view renders without
    re-deriving the column set. Metrics form a time series, so only each
    metric's *latest* logged value is kept (the last observation for that key).

    Entries that are not dicts are skipped rather than raising, so a partial or
    malformed reply still yields a usable payload. Returns a dict of ``records``
    (one flattened row per run) plus the sorted ``param_keys``, ``metric_keys``
    and ``tag_keys`` unions across all runs.
    """
    records = []
    param_keys = set()
    metric_keys = set()
    tag_keys = set()
    for exp in experiments:
        if not isinstance(exp, dict):
            continue
        params = {}
        for param in exp.get("params", []) or []:
            key = param.get("key")
            if key is None:
                continue
            params[key] = param.get("value")
            param_keys.add(key)
        metrics = {}
        for metric in exp.get("metrics", []) or []:
            key = metric.get("key")
            if key is None:
                continue
            metrics[key] = metric.get("value")
            metric_keys.add(key)
        tags = {}
        for tag in exp.get("tags", []) or []:
            key = tag.get("key")
            if key is None:
                continue
            tags[key] = tag.get("value")
            tag_keys.add(key)
        records.append(
            {
                "env_id": exp.get("env_id"),
                "name": exp.get("name", exp.get("env_id")),
                "status": exp.get("status"),
                "created_at": exp.get("created_at"),
                "params": params,
                "metrics": metrics,
                "tags": tags,
            }
        )
    return {
        "records": records,
        "param_keys": sorted(param_keys),
        "metric_keys": sorted(metric_keys),
        "tag_keys": sorted(tag_keys),
    }
