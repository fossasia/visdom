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

import html
import json
import threading
import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from visdom.experiments.tags import MAX_TAGS_PER_ENV, normalize_tags
from visdom.utils.server_utils import escape_eid


_INTERMEDIATE_METRIC_NAME = "intermediate_value"
_OPTUNA_TAG_NAMES = {
    "integration",
    "optuna_study",
    "optuna_trial",
    "optuna_state",
    "optuna_direction",
}


class OptunaCallback:
    """Log completed Optuna trials and optionally maintain a study dashboard.

    Instances are passed to ``Study.optimize(callbacks=[...])``. Optuna calls
    the instance with a ``Study`` and ``FrozenTrial`` after a trial finishes;
    the callback stores the trial's parameters, objective values, reported
    intermediate values and state via Visdom's experiment API.

    ``dashboard_env`` is the namespace for the study and its trial
    environments. When omitted it is derived from the Optuna study name.
    ``create_dashboard=True`` creates a summary, an HParams pane and Optuna's
    Plotly study visualizations in that environment. The first completed trial
    creates the dashboard; later trials refresh it every ``refresh_every``
    successful writes. Call :meth:`update_dashboard` after ``Study.optimize``
    to ensure the final trials are included when the total is not an exact
    multiple of that interval.

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
        create_dashboard: Create and periodically refresh the study dashboard.
        refresh_every: Positive integer number of newly logged trials between
            dashboard refreshes.

    Example::

        callback = OptunaCallback(
            viz,
            dashboard_env="optuna_resnet",
            objective_names=["validation_accuracy"],
            create_dashboard=True,
        )
        study.optimize(objective, callbacks=[callback])
        callback.update_dashboard(study)
    """

    def __init__(
        self,
        viz: Any,
        dashboard_env: str | None = None,
        objective_names: Sequence[str] | None = None,
        tags: Mapping[str, str] | None = None,
        raise_on_error: bool = False,
        create_dashboard: bool = False,
        refresh_every: int = 10,
    ) -> None:
        if dashboard_env is not None and not isinstance(dashboard_env, str):
            raise TypeError("dashboard_env must be a string or None")
        if dashboard_env is not None and not dashboard_env.strip():
            raise ValueError("dashboard_env must not be empty")
        if isinstance(refresh_every, bool) or not isinstance(refresh_every, int):
            raise TypeError("refresh_every must be an integer")
        if refresh_every < 1:
            raise ValueError("refresh_every must be at least 1")

        self.viz = viz
        self.dashboard_env = dashboard_env
        self.objective_names = self._validate_objective_names(objective_names)
        self.tags = self._validate_tags(tags)
        self.raise_on_error = raise_on_error
        self.create_dashboard = create_dashboard
        self.refresh_every = refresh_every
        self._dashboard_created = False
        self._trials_since_refresh = 0
        self._trial_envs: list[str] = []
        self._dashboard_lock = threading.RLock()

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
        if _INTERMEDIATE_METRIC_NAME in names:
            raise ValueError(
                "objective_names must not contain reserved name {!r}".format(
                    _INTERMEDIATE_METRIC_NAME
                )
            )
        return names

    @staticmethod
    def _validate_tags(tags: Mapping[str, str] | None) -> dict[str, str]:
        if tags is None:
            return {}
        if not isinstance(tags, Mapping):
            raise TypeError("tags must be a mapping of string names to string values")
        normalized = normalize_tags(dict(tags))
        if len(set(normalized) | _OPTUNA_TAG_NAMES) > MAX_TAGS_PER_ENV:
            raise ValueError(
                "OptunaCallback tags may contain at most {} non-reserved tags".format(
                    MAX_TAGS_PER_ENV - len(_OPTUNA_TAG_NAMES)
                )
            )
        return normalized

    def study_env(self, study: Any) -> str:
        """Return the environment namespace for an Optuna study."""
        if self.dashboard_env is not None:
            env = self.dashboard_env
        else:
            env = "optuna_{}".format(study.study_name)
        return escape_eid(env)

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

    def _trial_url(self, trial: Any, study: Any) -> str:
        root = "{}:{}{}".format(
            self.viz.server,
            self.viz.port,
            self.viz.base_url,
        ).rstrip("/")
        env = quote(escape_eid(self.trial_env(trial, study)), safe="")
        return "{}/env/{}".format(root, env)

    def _metric_names(self, study: Any, value_count: int) -> tuple[str, ...]:
        if self.objective_names is not None:
            names = self.objective_names
        else:
            study_names = getattr(study, "metric_names", None)
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
        if _INTERMEDIATE_METRIC_NAME in names:
            raise ValueError(
                "objective names must not contain reserved name {!r}".format(
                    _INTERMEDIATE_METRIC_NAME
                )
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

    @staticmethod
    def _intermediate_values(trial: Any) -> list[tuple[int, float]]:
        """Return reported intermediate values ordered by training step."""
        values = getattr(trial, "intermediate_values", None) or {}
        return sorted(values.items())

    @staticmethod
    def _add_timeline_markers(timeline: Any) -> None:
        """Keep very short trials visible without changing their duration bars.

        Optuna renders each trial as a horizontal bar whose width is its runtime.
        When callback or scheduler overhead dominates a study's wall-clock span,
        sub-millisecond trials can become substantially narrower than one browser
        pixel. A fixed-size marker at each trial's true start time preserves the
        timeline semantics while keeping those trials discoverable and hoverable.
        """
        for trace in tuple(timeline.data):
            if trace.type != "bar" or trace.orientation != "h":
                continue

            starts = list(trace.base) if trace.base is not None else []
            durations = list(trace.x) if trace.x is not None else []
            trial_numbers = list(trace.y) if trace.y is not None else []
            if not starts or not (len(starts) == len(durations) == len(trial_numbers)):
                continue

            text = list(trace.text) if trace.text is not None else None
            color = trace.marker.color if trace.marker is not None else None
            timeline.add_scatter(
                x=starts,
                y=trial_numbers,
                mode="markers",
                name=trace.name,
                legendgroup=trace.name,
                showlegend=False,
                marker={
                    "color": color,
                    "size": 9,
                    "symbol": "circle",
                    "line": {"color": "white", "width": 1},
                },
                customdata=durations,
                text=text,
                hovertemplate=(
                    "Start: %{x}<br>Duration: %{customdata:.3f} ms"
                    "<br>%{text}<extra>" + html.escape(str(trace.name)) + "</extra>"
                ),
            )

    def _summary_html(self, study: Any) -> str:
        trials = study.get_trials(deepcopy=False)
        states = Counter(trial.state.name for trial in trials)
        links = []
        rows = [
            ("Study", study.study_name),
            (
                "Direction",
                ", ".join(direction.name.lower() for direction in study.directions),
            ),
            ("Trials", len(trials)),
            ("Complete", states["COMPLETE"]),
            ("Pruned", states["PRUNED"]),
            ("Failed", states["FAIL"]),
        ]
        if len(study.directions) == 1 and states["COMPLETE"]:
            try:
                best_trial = study.best_trial
                best_value = study.best_value
                best_params = study.best_params
            except ValueError:
                pass
            else:
                links.append(("Open best trial", self._trial_url(best_trial, study)))
                rows.extend(
                    [
                        ("Best value", best_value),
                        (
                            "Best parameters",
                            json.dumps(
                                best_params,
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        ),
                    ]
                )
        elif states["COMPLETE"]:
            rows.append(("Pareto trials", len(study.best_trials)))

        terminal_trials = [
            trial
            for trial in trials
            if trial.state.name in ("COMPLETE", "PRUNED", "FAIL")
        ]
        if terminal_trials:
            latest_trial = max(terminal_trials, key=lambda trial: trial.number)
            links.append(("Open latest trial", self._trial_url(latest_trial, study)))

        body = "".join(
            "<tr><th>{}</th><td>{}</td></tr>".format(
                html.escape(str(label)), html.escape(str(value))
            )
            for label, value in rows
        )
        navigation = ""
        if links:
            anchors = " | ".join(
                '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>'.format(
                    html.escape(url, quote=True),
                    html.escape(label),
                )
                for label, url in links
            )
            navigation = "<p><strong>Open in Visdom:</strong> {}</p>".format(anchors)
        return "<h3>Optuna Study</h3><table>{}</table>{}".format(body, navigation)

    def _dashboard_figures(self, study: Any) -> list[tuple[str, Any]]:
        try:
            from optuna.visualization import (
                plot_intermediate_values,
                plot_optimization_history,
                plot_param_importances,
                plot_pareto_front,
                plot_timeline,
            )

            objective_names = self._metric_names(study, len(study.directions))
            figures = []
            multi_objective = len(objective_names) > 1
            trials = study.get_trials(deepcopy=False)
            complete_trials = sum(trial.state.name == "COMPLETE" for trial in trials)
            for index, objective_name in enumerate(objective_names):
                target = (
                    (lambda trial, i=index: trial.values[i])
                    if multi_objective
                    else None
                )
                kwargs: dict[str, Any] = {"target_name": objective_name}
                if target is not None:
                    kwargs["target"] = target
                history = plot_optimization_history(study, **kwargs)
                history.update_layout(
                    title="Optimization History — {}".format(objective_name)
                )
                suffix = "-{}".format(index) if multi_objective else ""
                figures.append(("optuna-history{}".format(suffix), history))

                if complete_trials >= 2:
                    try:
                        importance = plot_param_importances(study, **kwargs)
                    except (ImportError, ValueError) as error:
                        warnings.warn(
                            "Skipping Optuna parameter importance plot: {}".format(
                                error
                            ),
                            RuntimeWarning,
                            stacklevel=2,
                        )
                    else:
                        importance.update_layout(
                            title="Parameter Importance — {}".format(objective_name)
                        )
                        figures.append(
                            ("optuna-importance{}".format(suffix), importance)
                        )

            if complete_trials and len(objective_names) in (2, 3):
                try:
                    pareto = plot_pareto_front(
                        study,
                        target_names=list(objective_names),
                    )
                except ValueError as error:
                    warnings.warn(
                        "Skipping Optuna Pareto front plot: {}".format(error),
                        RuntimeWarning,
                        stacklevel=2,
                    )
                else:
                    pareto.update_layout(title="Optuna Pareto Front")
                    figures.append(("optuna-pareto-front", pareto))

            if any(self._intermediate_values(trial) for trial in trials):
                try:
                    intermediate = plot_intermediate_values(study)
                except ValueError as error:
                    warnings.warn(
                        "Skipping Optuna intermediate values plot: {}".format(error),
                        RuntimeWarning,
                        stacklevel=2,
                    )
                else:
                    intermediate.update_layout(title="Optuna Intermediate Values")
                    figures.append(("optuna-intermediate-values", intermediate))

            timeline = plot_timeline(study)
            try:
                self._add_timeline_markers(timeline)
            except (AttributeError, TypeError, ValueError) as error:
                warnings.warn(
                    "Skipping Optuna timeline markers: {}".format(error),
                    RuntimeWarning,
                    stacklevel=2,
                )
            timeline.update_layout(title="Optuna Trial Timeline")
            figures.append(("optuna-timeline", timeline))
            return figures
        except ImportError as error:
            warnings.warn(
                "Optuna dashboard plots are unavailable: {}".format(error),
                RuntimeWarning,
                stacklevel=2,
            )
            return []

    def _build_dashboard_payload(self, study: Any) -> dict[str, Any]:
        if not self._trial_envs:
            raise ValueError("cannot create an Optuna dashboard before logging a trial")
        return {
            "env": self.study_env(study),
            "env_ids": list(self._trial_envs),
            "summary": self._summary_html(study),
            "figures": self._dashboard_figures(study),
        }

    def update_dashboard(self, study: Any) -> bool:
        """Create or refresh all dashboard panes for ``study``.

        Returns whether the dashboard was written successfully. Only trials
        logged by this callback instance are included in the HParams pane;
        loading trials from a resumed study is handled by the later resume
        integration.
        """
        with self._dashboard_lock:
            try:
                payload = self._build_dashboard_payload(study)
                self.viz.text(
                    payload["summary"],
                    win="optuna-summary",
                    env=payload["env"],
                    opts={"title": "Optuna Study"},
                )
                self.viz.hparams(
                    env_ids=payload["env_ids"],
                    win="optuna-trials",
                    env=payload["env"],
                    opts={"title": "Optuna Trials"},
                )
                for win, figure in payload["figures"]:
                    self.viz.plotlyplot(figure, win=win, env=payload["env"])
            except Exception as error:
                if self.raise_on_error:
                    raise
                warnings.warn(
                    "OptunaCallback failed to update the dashboard: {}".format(error),
                    RuntimeWarning,
                    stacklevel=2,
                )
                return False
            self._dashboard_created = True
            self._trials_since_refresh = 0
            return True

    def _maybe_update_dashboard(self, study: Any) -> None:
        with self._dashboard_lock:
            self._trials_since_refresh += 1
            if (
                not self._dashboard_created
                or self._trials_since_refresh >= self.refresh_every
            ):
                self.update_dashboard(study)

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
        try:
            payload = self._build_payload(study, trial)
            self.viz.experiment(
                name=payload["name"],
                params=payload["params"],
                tags=payload["tags"],
                description=payload["description"],
                env=payload["env"],
            )
            for step, value in self._intermediate_values(trial):
                self.viz.log_metrics(
                    {_INTERMEDIATE_METRIC_NAME: value},
                    step=step,
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
            return

        with self._dashboard_lock:
            self._trial_envs.append(payload["env"])
            if self.create_dashboard:
                self._maybe_update_dashboard(study)
