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
from visdom.experiments.models import (
    Experiment,
    ExperimentFinishedError,
    STATUS_FINISHED,
)

METADATA_KEY = "experiment"


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
        """
        env = self.datastore.load_env(env_id)
        if not isinstance(env, dict):
            env = {}
        env.setdefault("jsons", {})
        env.setdefault("reload", {})
        blob = env.get(METADATA_KEY)
        experiment = Experiment.from_dict(blob) if isinstance(blob, dict) else None
        return env, experiment

    def _write(self, env_id, env, experiment):
        """Attach ``experiment`` to ``env`` and persist it; return the experiment."""
        env[METADATA_KEY] = experiment.to_dict()
        self.datastore.save_env(env_id, env)
        return experiment

    @staticmethod
    def _reject_if_terminal(env_id, experiment):
        """Raise if ``experiment`` is finished/failed and so must not be logged to."""
        if experiment.is_terminal():
            raise ExperimentFinishedError(
                "experiment {0!r} is {1}; cannot log to a terminal experiment".format(
                    env_id, experiment.status
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

    def finish_experiment(self, env_id, status=STATUS_FINISHED):
        """Mark ``env_id``'s experiment terminal; raise if none was logged."""
        env, experiment = self._read(env_id)
        if experiment is None:
            raise KeyError("no experiment logged for env {0!r}".format(env_id))
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
