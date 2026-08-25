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

import heapq

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

_MIN_TRIM_AT = 64


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


def _rank_key(entry, descending):
    """Sort key for a ``(seq, value, experiment)`` entry: value, then arrival.

    The arrival counter is negated for a descending sort so that reversing the
    comparison reverses the values *without* reversing ties. Two experiments
    scoring the same keep the order they were scanned in, whichever direction
    the sort runs — the property a stable ``list.sort`` used to provide, which
    selecting through a heap does not.
    """
    seq, value, _ = entry
    return (_order_key(value), -seq if descending else seq)


def _rank(entries, descending, keep=None):
    """Order scanned ``(seq, value, experiment)`` entries, best first.

    ``keep`` bounds the result to that many entries, selected with a heap so
    that ranking a large scan costs memory proportional to what is kept rather
    than to what was seen. Without it every entry is ordered.
    """

    def key(entry):
        return _rank_key(entry, descending)

    if keep is not None and keep < len(entries):
        select = heapq.nlargest if descending else heapq.nsmallest
        return select(keep, entries, key=key)
    return sorted(entries, key=key, reverse=descending)


class ExperimentStore:
    """Read/write experiment metadata attached to environments via a DataStore."""

    def __init__(self, datastore, env_provider=None):
        """Create a store backed by ``datastore`` (a :class:`DataStore`).

        ``env_provider`` is an optional callable ``env_id -> env | None`` that
        returns the *live* environment (the server passes ``state.get``). When
        it yields one, reads and writes go through that object rather than a
        fresh copy off disk, so persisting an experiment cannot overwrite the
        env file with a snapshot that is missing windows created — or reviving
        windows closed — since the file was last written.
        """
        if not isinstance(datastore, DataStore):
            raise TypeError(
                f"datastore must be a DataStore, got {type(datastore).__name__}"
            )
        self.datastore = datastore
        self.env_provider = env_provider

    def _read(self, env_id):
        """Return ``(env, Experiment|None)`` for ``env_id``.

        The live env is preferred when an ``env_provider`` serves it; only then
        is the file read. The env always has ``jsons``/``reload`` keys so that
        persisting it back never strips an environment of the fields the rest
        of the server relies on, even for an env that did not exist before.
        The env may be a ``LazyEnvData`` rather than a plain dict, so it is
        mutated through the mapping interface and never copied — a write must
        land in the same object the server is serving.

        The env an experiment is stored under is the authoritative one, so the
        loaded experiment is re-pointed at ``env_id`` rather than trusting the
        ``env_id`` recorded in the blob. Forking an environment deep-copies the
        whole env dict, metadata included, which leaves the copy's blob naming
        the env it was forked from; a comparison keyed by experiment env_id
        would then fold the fork and its parent into one column.
        """
        env = self.env_provider(env_id) if self.env_provider is not None else None
        if env is None:
            env = self.datastore.load_env(env_id)
            if not isinstance(env, dict):
                env = {}
        if "jsons" not in env:
            env["jsons"] = {}
        if "reload" not in env:
            env["reload"] = {}
        blob = env.get(METADATA_KEY)
        experiment = Experiment.from_dict(blob) if isinstance(blob, dict) else None
        if experiment is not None:
            experiment.env_id = env_id
        return env, experiment

    def _read_metadata(self, env_id):
        """Return ``env_id``'s :class:`Experiment` without materialising its env.

        The read path for callers that want metadata and nothing else. Unlike
        :meth:`_read` it never assembles — or forces into memory — the env dict,
        because reading one experiment must not be a reason to hold an env's
        windows.

        A live env is still preferred, but only when it is *already* resident:
        an env the server is holding may carry changes the file has not seen, so
        it wins; an env that has never been materialised cannot, so the store is
        asked instead. ``LazyEnvData`` reports this through ``is_loaded``;
        anything else (a plain dict) is resident by definition.

        As in :meth:`_read`, the experiment answers to the env it was read from
        rather than to the ``env_id`` its blob records, so a forked env does not
        report its parent's id.
        """
        env = self.env_provider(env_id) if self.env_provider is not None else None
        if env is not None and not getattr(env, "is_loaded", True):
            env = None
        if env is not None:
            blob = env.get(METADATA_KEY)
        else:
            blob = self.datastore.load_experiment(env_id)
        if not isinstance(blob, dict):
            return None
        experiment = Experiment.from_dict(blob)
        experiment.env_id = env_id
        return experiment

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

    def update_tags(self, env_id, tags, append=False, env_data=None):
        """Replace or append organizational tags for ``env_id``.

        ``tags`` is the model's ``{key: value}`` representation.  Unlike run
        logging, tag management is allowed after an experiment reaches a
        terminal state: tags organize completed runs and do not alter their
        parameters, metrics, result status, or completion timestamp.

        ``env_data`` may provide the server's current in-memory environment.
        Using it avoids flushing that environment before validation merely so
        this store can read it back. Invalid requests therefore perform no
        writes, while valid requests persist the complete current environment
        exactly once.
        """
        if not isinstance(append, bool):
            raise TypeError("append must be a boolean")
        tags = normalize_tags(tags)

        if env_data is None:
            env, experiment = self._read(env_id)
        else:
            env = env_data
            blob = env.get(METADATA_KEY)
            experiment = Experiment.from_dict(blob) if isinstance(blob, dict) else None
            if experiment is not None:
                experiment.env_id = env_id
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
        """Return ``env_id``'s :class:`Experiment`, or ``None`` if it has none.

        A pure read, so it goes through :meth:`_read_metadata` and leaves an
        env that was not already in memory out of it.
        """
        return self._read_metadata(env_id)

    def iter_experiments(self):
        """Yield every stored :class:`Experiment`, one environment at a time.

        A generator rather than a list because the caller is usually filtering:
        an experiment that does not survive the filter should be collectable
        immediately, not held until the whole store has been walked.
        """
        for env_id in self.datastore.list_envs():
            experiment = self._read_metadata(env_id)
            if experiment is not None:
                yield experiment

    def list_experiments(self):
        """Return every stored :class:`Experiment`, across all environments."""
        return list(self.iter_experiments())

    def _scan(self, query, sort_by, descending=True, keep=None):
        """Scan every experiment once; return matches and how many there were.

        Returns the pieces both search entry points need: ``(present, missing,
        total)``, where ``present`` are ``(seq, value, experiment)`` entries
        carrying the value ``sort_by`` will order them by, and ``missing`` are
        the matches that have no such value and so sort last.

        The flattened record is built per experiment and dropped as soon as it
        has answered — it is several times the size of the experiment it
        describes, and only the sort value outlives it. Non-matches are held no
        longer than the loop body.

        ``keep`` bounds what survives the scan to the first ``keep`` results a
        page could reach: ``present`` is trimmed back to its best ``keep``
        whenever it has grown to twice that (dropping an entry already outside
        the top ``keep`` can never change the top ``keep``), and ``missing``
        stops growing there too. ``total`` still counts every match, since a
        counter costs nothing. Without ``keep`` every match is retained.
        """
        if query is not None and not isinstance(query, str):
            raise TypeError(
                "query must be a string or None, got {0}".format(type(query).__name__)
            )
        compiled = Query(query) if query is not None and query.strip() else None
        trim_at = None if keep is None else max(2 * keep, _MIN_TRIM_AT)
        present = []
        missing = []
        total = 0
        for experiment in self.iter_experiments():
            record = build_record(experiment)
            if compiled is not None and not compiled.matches(record):
                continue
            total += 1
            if not sort_by:
                if keep is None or len(present) < keep:
                    present.append((total, None, experiment))
                continue
            value = record.get(sort_by, _MISSING)
            if value is _MISSING or value is None:
                if keep is None or len(missing) < keep:
                    missing.append(experiment)
            else:
                present.append((total, value, experiment))
                if trim_at is not None and len(present) >= trim_at:
                    present = _rank(present, descending, keep)
        return present, missing, total

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
        are ordinary :class:`Experiment` objects.

        Every match is returned, so the result grows with the store; a caller
        serving a request should use :meth:`search_page`, which bounds it.

        Raises :class:`~visdom.experiments.query.QueryParseError` if ``query``
        is not valid query syntax.
        """
        present, missing, _ = self._scan(query, sort_by, descending)
        if not sort_by:
            return [experiment for _, _, experiment in present]
        ordered = _rank(present, descending)
        return [experiment for _, _, experiment in ordered] + missing

    def search_page(
        self,
        query=None,
        sort_by=DEFAULT_SORT_FIELD,
        descending=True,
        offset=0,
        limit=None,
    ):
        """Return one page of matches and the unpaged total, as ``(page, total)``.

        The paged form of :meth:`search`, for callers answering a request. The
        scan is the same — every environment must be read to know whether it
        matches, and ``total`` counts all of them — but only the first
        ``offset + limit`` matches are ever ranked and held, so the memory a
        request costs is set by the page asked for rather than by how much the
        server happens to store. ``limit=None`` keeps every match, which is
        :meth:`search` with a count.

        Experiments with no value for ``sort_by`` sort last, so they are only
        materialised while the page can still reach them.
        """
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("offset and limit must not be negative")
        keep = None if limit is None else offset + limit
        present, missing, total = self._scan(query, sort_by, descending, keep)
        if not sort_by:
            page = [experiment for _, _, experiment in present]
        else:
            ordered = _rank(present, descending, keep)
            page = [experiment for _, _, experiment in ordered] + missing
        end = keep
        return page[offset:end], total

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
        del env[METADATA_KEY]
        self.datastore.save_env(env_id, env)
        return True
