#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Persistence for experiment metadata, layered on top of a ``DataStore``.

``ExperimentStore`` keeps no storage of its own: every experiment lives under
the ``"experiment"`` key of its environment's persisted data, which is read
and written through the injected :class:`~visdom.data_model.base.DataStore`
(``JSONStore`` today, a database later). Because the metadata rides inside the
env dict, an environment without an experiment blob behaves exactly as it does
today — the feature is fully opt-in.
"""

from visdom.data_model.base import DataStore
from visdom.experiments.compare import build_comparison
from visdom.experiments.models import (
    Experiment,
    ExperimentFinishedError,
    STATUS_FINISHED,
)
from visdom.experiments.query import Query, build_record
from visdom.experiments.tags import MAX_TAGS_PER_ENV, normalize_tags

METADATA_KEY = "experiment"

DEFAULT_SORT_FIELD = "created_at"

_MISSING = object()


def retarget_experiment(env, env_id):
    """Point ``env``'s experiment metadata, if it has any, at ``env_id``.

    Cloning an environment copies its persisted data wholesale, metadata blob
    included, which leaves the copy recording the env it was cloned from. The
    callers that clone an env re-point the copy through here so what lands on
    disk names the env it actually lives in.

    Returns ``env`` so a clone can be retargeted in the same expression that
    copies it. ``env`` may be any mutable mapping — the server holds
    environments as plain dicts or as ``LazyEnvData``.
    """
    blob = env.get(METADATA_KEY)
    if isinstance(blob, dict):
        blob["env_id"] = env_id
    return env


def _order_key(value):
    """Return a sort key that totally orders values of mixed types.

    Records come from user-supplied params/metrics/tags, so one field can hold a
    number in one experiment and a string in another; sorting them directly
    would raise ``TypeError``. Numbers sort before strings, and everything that
    is neither is compared by its text form. Booleans are ordered as text rather
    than as 0/1, matching :mod:`~visdom.experiments.query`, which likewise
    refuses to treat a bool as a number.
    """
    if isinstance(value, bool):
        return (1, 0.0, str(value))
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0.0, str(value))


def _sort_pairs(pairs, field, descending):
    """Sort ``(record, experiment)`` pairs by ``record[field]``.

    Experiments whose record lacks ``field`` (or holds ``None`` there) keep
    their relative order and always land last, in both directions: a run that
    never logged ``acc`` is not the best-scoring run just because the sort was
    reversed.
    """
    present = []
    missing = []
    for record, experiment in pairs:
        value = record.get(field, _MISSING)
        if value is _MISSING or value is None:
            missing.append((record, experiment))
        else:
            present.append((record, experiment))
    present.sort(key=lambda pair: _order_key(pair[0][field]), reverse=descending)
    return present + missing


class ExperimentStore:
    """Read/write experiment metadata attached to environments via a DataStore."""

    def __init__(self, datastore):
        """Create a store backed by ``datastore`` (a :class:`DataStore`)."""
        if not isinstance(datastore, DataStore):
            raise TypeError(
                f"datastore must be a DataStore, got {type(datastore).__name__}"
            )
        self.datastore = datastore

    def _read(self, env_id):
        """Return ``(env_dict, Experiment|None)`` for ``env_id``.

        The env dict always has ``jsons``/``reload`` keys so that persisting it
        back never strips an environment of the fields the rest of the server
        relies on, even for an env that did not exist before.

        The env an experiment is stored under is the authoritative one, so the
        loaded experiment is re-pointed at ``env_id`` rather than trusting the
        ``env_id`` recorded in the blob. Forking an environment deep-copies the
        whole env dict, metadata included, which leaves the copy's blob naming
        the env it was forked from; a comparison keyed by experiment env_id
        would then fold the fork and its parent into one column.
        """
        env = self.datastore.load_env(env_id)
        if not isinstance(env, dict):
            env = {}
        env.setdefault("jsons", {})
        env.setdefault("reload", {})
        blob = env.get(METADATA_KEY)
        experiment = Experiment.from_dict(blob) if isinstance(blob, dict) else None
        if experiment is not None:
            experiment.env_id = env_id
        return env, experiment

    def _write(self, env_id, env, experiment):
        """Attach ``experiment`` to ``env`` and persist it; return the experiment."""
        env[METADATA_KEY] = experiment.to_dict()
        self.datastore.save_env(env_id, env)
        return experiment

    @staticmethod
    def _reject_if_terminal(env_id, experiment, action="log to"):
        """Raise if ``experiment`` is finished/failed and so must not be written to.

        ``action`` names the attempted operation so the error reads sensibly for
        every caller (``"log to"`` for the logging paths, ``"finish"`` for a
        second attempt at finishing an already terminal experiment).
        """
        if experiment.is_terminal():
            raise ExperimentFinishedError(
                "experiment {0!r} is {1}; cannot {2} a terminal experiment".format(
                    env_id, experiment.status, action
                )
            )

    def log_experiment(
        self, env_id, name=None, params=None, tags=None, description=None
    ):
        """Create or update the experiment for ``env_id`` and persist it.

        Calling this repeatedly for the same ``env_id`` updates the existing
        record (merging in any ``params``/``tags`` and overwriting ``name``/
        ``description`` when provided) rather than replacing it, so previously
        logged metrics survive.
        """
        env, experiment = self._read(env_id)
        if experiment is None:
            experiment = Experiment(
                env_id=env_id,
                name=name or env_id,
                description=description or "",
            )
        else:
            self._reject_if_terminal(env_id, experiment)
            if name is not None:
                experiment.name = name
            if description is not None:
                experiment.description = description
        for key, value in (params or {}).items():
            experiment.set_param(key, value)
        for key, value in (tags or {}).items():
            experiment.set_tag(key, value)
        return self._write(env_id, env, experiment)

    def log_metric(self, env_id, key, value, step=None):
        """Append a metric to ``env_id``'s experiment, creating it if needed."""
        env, experiment = self._read(env_id)
        if experiment is None:
            experiment = Experiment(env_id=env_id, name=env_id)
        else:
            self._reject_if_terminal(env_id, experiment)
        experiment.add_metric(key, value, step)
        return self._write(env_id, env, experiment)

    def update_tags(self, env_id, tags, append=False):
        """Replace or append organizational tags for ``env_id``.

        ``tags`` is the model's ``{key: value}`` representation.  Unlike run
        logging, tag management is allowed after an experiment reaches a
        terminal state: tags organize completed runs and do not alter their
        parameters, metrics, result status, or completion timestamp.
        """
        if not isinstance(append, bool):
            raise TypeError("append must be a boolean")
        tags = normalize_tags(tags)

        env, experiment = self._read(env_id)
        if experiment is None:
            experiment = Experiment(env_id=env_id, name=env_id)
        if append:
            final_tag_names = {tag.key for tag in experiment.tags}
            final_tag_names.update(tags)
            if len(final_tag_names) > MAX_TAGS_PER_ENV:
                raise ValueError(
                    "environments may have at most {0} tags".format(MAX_TAGS_PER_ENV)
                )
        if not append:
            experiment.tags = []
        for key, value in tags.items():
            experiment.set_tag(key, value)
        return self._write(env_id, env, experiment)

    def finish_experiment(self, env_id, status=STATUS_FINISHED):
        """Mark ``env_id``'s experiment terminal; raise if none was logged.

        An experiment that is already terminal is rejected rather than
        re-finished, matching ``log_experiment``/``log_metric``: once a run has
        stopped, neither its status nor its ``finished_at`` stamp may change.
        """
        env, experiment = self._read(env_id)
        if experiment is None:
            raise KeyError("no experiment logged for env {0!r}".format(env_id))
        self._reject_if_terminal(env_id, experiment, "finish")
        experiment.finish(status)
        return self._write(env_id, env, experiment)

    def get_experiment(self, env_id):
        """Return ``env_id``'s :class:`Experiment`, or ``None`` if it has none."""
        _, experiment = self._read(env_id)
        return experiment

    def list_experiments(self):
        """Return every stored :class:`Experiment`, across all environments."""
        experiments = []
        for env_id in self.datastore.list_envs():
            experiment = self.get_experiment(env_id)
            if experiment is not None:
                experiments.append(experiment)
        return experiments

    def search(self, query=None, sort_by=DEFAULT_SORT_FIELD, descending=True):
        """Return the experiments matching ``query``, sorted by ``sort_by``.

        ``query`` is the human-readable syntax of
        :mod:`~visdom.experiments.query` (``"lr < 0.01 AND acc > 90"``); ``None``
        or a blank string matches every experiment. Matching runs against the
        flattened record of :func:`~visdom.experiments.query.build_record`, so a
        param, latest metric or tag is reachable both bare (``acc``) and
        namespaced (``metric.acc``) — and ``sort_by`` accepts either spelling of
        the same names.

        Sorting defaults to newest-first; pass ``descending=False`` for oldest
        first, or ``sort_by=None`` to keep the backend's own ordering. Results
        are ordinary :class:`Experiment` objects, and paging through them is left
        to the caller — the whole set is scanned regardless, since every
        environment must be read to know whether it matches.

        Raises :class:`~visdom.experiments.query.QueryParseError` if ``query``
        is not valid query syntax.
        """
        if query is not None and not isinstance(query, str):
            raise TypeError(
                "query must be a string or None, got {0}".format(type(query).__name__)
            )
        pairs = [
            (build_record(experiment), experiment)
            for experiment in self.list_experiments()
        ]
        if query is not None and query.strip():
            compiled = Query(query)
            pairs = [pair for pair in pairs if compiled.matches(pair[0])]
        if sort_by:
            pairs = _sort_pairs(pairs, sort_by, descending)
        return [experiment for _, experiment in pairs]

    def _load_named(self, env_ids):
        """Return the experiments for ``env_ids``, in the order asked for.

        Duplicate ids collapse to their first occurrence: a comparison is keyed
        by env_id, so a run named twice cannot mean anything beyond once.
        """
        if isinstance(env_ids, str) or not isinstance(env_ids, (list, tuple)):
            raise TypeError(
                "env_ids must be a list of environment ids, got {0}".format(
                    type(env_ids).__name__
                )
            )
        unique = list(dict.fromkeys(env_ids))
        for env_id in unique:
            if not isinstance(env_id, str):
                raise TypeError(
                    "env_ids must contain strings, got {0}".format(
                        type(env_id).__name__
                    )
                )
        if not unique:
            raise ValueError("env_ids must name at least one environment")
        experiments = []
        missing = []
        for env_id in unique:
            experiment = self.get_experiment(env_id)
            if experiment is None:
                missing.append(env_id)
            else:
                experiments.append(experiment)
        if missing:
            raise KeyError(
                "no experiment logged for env(s) {0}".format(
                    ", ".join(repr(env_id) for env_id in missing)
                )
            )
        return experiments

    def compare(self, env_ids):
        """Compare the named experiments field by field; see :func:`build_comparison`.

        ``env_ids`` is an explicit list, compared in the order given. Every id must
        have an experiment; a :class:`KeyError` names those that do not, since a
        comparison silently missing a run it was asked for would be read as a
        comparison of the rest.

        Finding the runs to compare is :meth:`search`'s job, not this one: search
        answers "which runs match?" and compare answers "how do these runs differ?".
        Callers that want to compare a query's matches search first and pass the
        ids on, which also keeps the diff honest — it always describes exactly the
        runs that were named.
        """
        return build_comparison(self._load_named(env_ids))

    def delete_experiment(self, env_id):
        """Drop the experiment blob from ``env_id`` (keeping the env itself).

        Returns ``True`` if an experiment was removed, ``False`` if ``env_id``
        had none.
        """
        env, experiment = self._read(env_id)
        if experiment is None:
            return False
        env.pop(METADATA_KEY, None)
        self.datastore.save_env(env_id, env)
        return True
