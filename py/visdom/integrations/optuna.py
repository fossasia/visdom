#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Record completed Optuna trials as Visdom experiments.

The integration deliberately implements Optuna's callback protocol by shape
rather than importing Optuna. Users already have Optuna installed when they
run a study, while users who do not tune with Optuna should not acquire a new
Visdom dependency just for this optional adapter.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from typing import Any

from visdom.experiments.tags import normalize_tags


class OptunaCallback:
    """Log each completed Optuna trial to a dedicated Visdom environment.

    Instances are passed to ``Study.optimize(callbacks=[...])``. Optuna calls
    the instance with a ``Study`` and ``FrozenTrial`` after a trial finishes;
    the callback stores the trial's parameters, objective values and state via
    Visdom's experiment API.

    ``dashboard_env`` is the namespace for the study and its trial
    environments. When omitted it is derived from the Optuna study name. The
    callback itself does not create a dashboard pane; it only establishes the
    stable environment layout that a dashboard can aggregate later.

    Optuna is intentionally not imported here. This keeps the integration
    optional and also means importing :mod:`visdom.integrations` never requires
    Optuna to be installed.

    Args:
        viz: A :class:`visdom.Visdom` client.
        dashboard_env: Study environment namespace. Defaults to
            ``"optuna_<study name>"``.
        objective_names: Optional names for the objective metrics. When absent,
            Optuna study metric names are used if available, followed by
            ``"objective"`` or ``"objective_<index>"``.
        tags: Additional string tags to attach to every trial. Reserved Optuna
            tags override entries with the same names.
        raise_on_error: Re-raise Visdom logging failures when true. By default a
            warning is emitted so an unavailable dashboard does not stop the
            optimization.

    Example::

        callback = OptunaCallback(
            viz,
            dashboard_env="optuna_resnet",
            objective_names=["validation_accuracy"],
        )
        study.optimize(objective, callbacks=[callback])
    """

    def __init__(
        self,
        viz: Any,
        dashboard_env: str | None = None,
        objective_names: Sequence[str] | None = None,
        tags: Mapping[str, str] | None = None,
        raise_on_error: bool = False,
    ) -> None:
        if dashboard_env is not None and not isinstance(dashboard_env, str):
            raise TypeError("dashboard_env must be a string or None")
        if dashboard_env == "":
            raise ValueError("dashboard_env must not be empty")

        self.viz = viz
        self.dashboard_env = dashboard_env
        self.objective_names = self._validate_objective_names(objective_names)
        self.tags = self._validate_tags(tags)
        self.raise_on_error = raise_on_error

    @staticmethod
    def _validate_objective_names(
        objective_names: Sequence[str] | None,
    ) -> tuple[str, ...] | None:
        if objective_names is None:
            return None
        if isinstance(objective_names, str) or not isinstance(
            objective_names, Sequence
        ):
            raise TypeError("objective_names must be a sequence of strings or None")
        names = tuple(objective_names)
        if not names:
            raise ValueError("objective_names must not be empty")
        if not all(isinstance(name, str) and name for name in names):
            raise ValueError("objective_names must contain non-empty strings")
        if len(set(names)) != len(names):
            raise ValueError("objective_names must be unique")
        return names

    @staticmethod
    def _validate_tags(tags: Mapping[str, str] | None) -> dict[str, str]:
        if tags is None:
            return {}
        if not isinstance(tags, Mapping):
            raise TypeError("tags must be a mapping of string names to string values")
        return normalize_tags(dict(tags))

    def study_env(self, study: Any) -> str:
        """Return the environment namespace for an Optuna study."""
        if self.dashboard_env is not None:
            return self.dashboard_env
        return "optuna_{}".format(study.study_name)

    def trial_env(self, trial: Any, study: Any = None) -> str:
        """Return the deterministic Visdom environment for an Optuna trial.

        ``study`` may be omitted when ``dashboard_env`` was supplied to
        the constructor. This lets objective functions find their environment
        before the completion callback runs::

            env = callback.trial_env(trial)
            viz.line(..., env=env)
        """
        if self.dashboard_env is None and study is None:
            raise ValueError("study is required when dashboard_env was not supplied")
        return "{}_trial_{:06d}".format(self.study_env(study), trial.number)

    def _metric_names(self, study: Any, value_count: int) -> tuple[str, ...]:
        if self.objective_names is not None:
            names = self.objective_names
        else:
            study_names = study.metric_names
            if study_names is not None:
                names = tuple(study_names)
            elif value_count == 1:
                names = ("objective",)
            else:
                names = tuple(
                    "objective_{}".format(index) for index in range(value_count)
                )
        if len(names) != value_count:
            raise ValueError(
                "expected {} objective name(s), got {}".format(value_count, len(names))
            )
        return names

    def _trial_tags(self, study: Any, trial: Any) -> dict[str, str]:
        tags = dict(self.tags)
        tags.update(
            {
                "integration": "optuna",
                "optuna_study": str(study.study_name),
                "optuna_trial": str(trial.number),
                "optuna_state": trial.state.name,
                "optuna_direction": ",".join(
                    direction.name.lower() for direction in study.directions
                ),
            }
        )
        return normalize_tags(tags)

    def _build_payload(self, study: Any, trial: Any) -> dict[str, Any]:
        env = self.trial_env(trial, study)
        state = trial.state.name
        if state not in ("COMPLETE", "PRUNED", "FAIL"):
            raise ValueError(
                "cannot log non-terminal Optuna trial state {!r}".format(state)
            )
        values = tuple(trial.values or ())
        metrics = (
            dict(zip(self._metric_names(study, len(values)), values)) if values else {}
        )
        return {
            "env": env,
            "name": "{} / trial {}".format(study.study_name, trial.number),
            "params": dict(trial.params),
            "tags": self._trial_tags(study, trial),
            "description": "Optuna trial {} from study {!r}.".format(
                trial.number, study.study_name
            ),
            "metrics": metrics,
            "status": "finished" if state == "COMPLETE" else "failed",
        }

    def __call__(self, study: Any, trial: Any) -> None:
        """Record the completed ``trial`` without affecting optimization by default."""
        payload = self._build_payload(study, trial)
        try:
            self.viz.experiment(
                name=payload["name"],
                params=payload["params"],
                tags=payload["tags"],
                description=payload["description"],
                env=payload["env"],
            )
            if payload["metrics"]:
                self.viz.log_metrics(payload["metrics"], env=payload["env"])
            self.viz.finish_experiment(
                status=payload["status"],
                env=payload["env"],
            )
        except Exception as error:
            if self.raise_on_error:
                raise
            warnings.warn(
                "OptunaCallback failed to log trial {}: {}".format(trial.number, error),
                RuntimeWarning,
                stacklevel=2,
            )
