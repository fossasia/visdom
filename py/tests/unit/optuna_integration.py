#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the optional Optuna experiment integration."""

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from visdom.integrations import OptunaCallback


def make_trial(
    number=0,
    state="COMPLETE",
    values=(0.25,),
    params=None,
    intermediate_values=None,
):
    return SimpleNamespace(
        number=number,
        state=SimpleNamespace(name=state),
        values=values,
        params=params or {"x": 2.0},
        intermediate_values=intermediate_values or {},
    )


def make_study(trials):
    return SimpleNamespace(
        study_name="quadratic",
        directions=[SimpleNamespace(name="MINIMIZE")],
        metric_names=None,
        best_value=0.25,
        best_params={"x": 2.0},
        best_trials=[],
        get_trials=Mock(return_value=trials),
    )


def fake_visualization_module(intermediate_error=None):
    visualization = types.ModuleType("optuna.visualization")
    figures = {
        "history": Mock(name="history"),
        "importance": Mock(name="importance"),
        "intermediate": Mock(name="intermediate"),
        "pareto": Mock(name="pareto"),
        "timeline": Mock(name="timeline", data=()),
    }
    visualization.plot_optimization_history = Mock(return_value=figures["history"])
    visualization.plot_param_importances = Mock(return_value=figures["importance"])
    visualization.plot_intermediate_values = Mock(
        return_value=figures["intermediate"], side_effect=intermediate_error
    )
    visualization.plot_pareto_front = Mock(return_value=figures["pareto"])
    visualization.plot_timeline = Mock(return_value=figures["timeline"])

    optuna = types.ModuleType("optuna")
    optuna.__path__ = []
    optuna.visualization = visualization
    return optuna, visualization, figures


class TestOptunaIntermediateValues(unittest.TestCase):
    def test_logs_intermediate_values_in_step_order_before_final_metric(self):
        viz = Mock()
        trial = make_trial(
            values=(0.2,),
            intermediate_values={2: 0.3, 0: 0.9, 1: 0.5},
        )
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")

        callback(make_study([trial]), trial)

        self.assertEqual(
            viz.log_metrics.call_args_list,
            [
                call(
                    {"intermediate_value": 0.9},
                    step=0,
                    env="optuna_quadratic_trial_000000",
                ),
                call(
                    {"intermediate_value": 0.5},
                    step=1,
                    env="optuna_quadratic_trial_000000",
                ),
                call(
                    {"intermediate_value": 0.3},
                    step=2,
                    env="optuna_quadratic_trial_000000",
                ),
                call(
                    {"objective": 0.2},
                    env="optuna_quadratic_trial_000000",
                ),
            ],
        )
        self.assertEqual(
            [method[0] for method in viz.method_calls],
            [
                "experiment",
                "log_metrics",
                "log_metrics",
                "log_metrics",
                "log_metrics",
                "finish_experiment",
            ],
        )

    def test_trial_without_intermediate_values_only_logs_final_metric(self):
        viz = Mock()
        trial = make_trial(values=(0.2,))
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")

        callback(make_study([trial]), trial)

        viz.log_metrics.assert_called_once_with(
            {"objective": 0.2}, env="optuna_quadratic_trial_000000"
        )

    def test_pruned_trial_preserves_intermediate_values_and_failed_status(self):
        viz = Mock()
        trial = make_trial(
            state="PRUNED",
            values=None,
            intermediate_values={4: 0.6},
        )
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")

        callback(make_study([trial]), trial)

        viz.log_metrics.assert_called_once_with(
            {"intermediate_value": 0.6},
            step=4,
            env="optuna_quadratic_trial_000000",
        )
        self.assertEqual(
            viz.experiment.call_args.kwargs["tags"]["optuna_state"], "PRUNED"
        )
        viz.finish_experiment.assert_called_once_with(
            status="failed", env="optuna_quadratic_trial_000000"
        )

    def test_intermediate_logging_failure_uses_existing_error_policy(self):
        trial = make_trial(intermediate_values={0: 0.9})
        study = make_study([trial])

        warning_viz = Mock()
        warning_viz.log_metrics.side_effect = RuntimeError("offline")
        warning_callback = OptunaCallback(warning_viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "failed to log trial 0: offline"):
            warning_callback(study, trial)
        warning_viz.finish_experiment.assert_not_called()
        self.assertEqual(warning_callback._trial_envs, [])

        raising_viz = Mock()
        raising_viz.log_metrics.side_effect = RuntimeError("offline")
        raising_callback = OptunaCallback(
            raising_viz,
            dashboard_env="optuna_quadratic",
            raise_on_error=True,
        )
        with self.assertRaisesRegex(RuntimeError, "offline"):
            raising_callback(study, trial)


class TestOptunaIntermediateDashboard(unittest.TestCase):
    def dashboard_figures(self, trial, intermediate_error=None):
        optuna, visualization, figures = fake_visualization_module(
            intermediate_error=intermediate_error
        )
        modules = {
            "optuna": optuna,
            "optuna.visualization": visualization,
        }
        callback = OptunaCallback(Mock(), dashboard_env="optuna_quadratic")
        with patch.dict(sys.modules, modules):
            result = callback._dashboard_figures(make_study([trial]))
        return result, visualization, figures

    def test_adds_intermediate_figure_when_values_exist(self):
        trial = make_trial(intermediate_values={0: 0.9})

        result, visualization, figures = self.dashboard_figures(trial)

        self.assertEqual(
            [win for win, _ in result],
            ["optuna-history", "optuna-intermediate-values", "optuna-timeline"],
        )
        visualization.plot_intermediate_values.assert_called_once()
        figures["intermediate"].update_layout.assert_called_once_with(
            title="Optuna Intermediate Values"
        )

    def test_skips_intermediate_figure_when_values_are_absent(self):
        result, visualization, _ = self.dashboard_figures(make_trial())

        self.assertEqual(
            [win for win, _ in result],
            ["optuna-history", "optuna-timeline"],
        )
        visualization.plot_intermediate_values.assert_not_called()

    def test_skips_intermediate_figure_when_optuna_cannot_build_it(self):
        trial = make_trial(intermediate_values={0: 0.9})

        result, visualization, _ = self.dashboard_figures(
            trial, intermediate_error=ValueError("not enough data")
        )

        self.assertEqual(
            [win for win, _ in result],
            ["optuna-history", "optuna-timeline"],
        )
        visualization.plot_intermediate_values.assert_called_once()


class TestOptunaMultiObjective(unittest.TestCase):
    def test_logs_two_objectives_and_adds_pareto_front(self):
        trial = make_trial(values=(0.92, 18.4))
        study = SimpleNamespace(
            study_name="accuracy-latency",
            directions=[
                SimpleNamespace(name="MAXIMIZE"),
                SimpleNamespace(name="MINIMIZE"),
            ],
            metric_names=None,
            best_trials=[trial],
            get_trials=Mock(return_value=[trial]),
        )
        viz = Mock()
        callback = OptunaCallback(
            viz,
            dashboard_env="optuna_accuracy_latency",
            objective_names=["accuracy", "latency_ms"],
        )

        callback(study, trial)

        viz.log_metrics.assert_called_once_with(
            {"accuracy": 0.92, "latency_ms": 18.4},
            env="optuna_accuracy_latency_trial_000000",
        )
        self.assertEqual(
            viz.experiment.call_args.kwargs["tags"]["optuna_direction"],
            "maximize,minimize",
        )

        optuna, visualization, figures = fake_visualization_module()
        with patch.dict(
            sys.modules,
            {"optuna": optuna, "optuna.visualization": visualization},
        ):
            result = callback._dashboard_figures(study)

        self.assertEqual(
            [win for win, _ in result],
            [
                "optuna-history-0",
                "optuna-history-1",
                "optuna-pareto-front",
                "optuna-timeline",
            ],
        )
        visualization.plot_pareto_front.assert_called_once_with(
            study,
            target_names=["accuracy", "latency_ms"],
        )
        figures["pareto"].update_layout.assert_called_once_with(
            title="Optuna Pareto Front"
        )

    def test_logs_three_objectives_and_adds_pareto_front(self):
        trial = make_trial(values=(0.92, 18.4, 512.0))
        study = SimpleNamespace(
            study_name="accuracy-latency-memory",
            directions=[
                SimpleNamespace(name="MAXIMIZE"),
                SimpleNamespace(name="MINIMIZE"),
                SimpleNamespace(name="MINIMIZE"),
            ],
            metric_names=None,
            best_trials=[trial],
            get_trials=Mock(return_value=[trial]),
        )
        viz = Mock()
        callback = OptunaCallback(
            viz,
            dashboard_env="optuna_accuracy_latency_memory",
            objective_names=["accuracy", "latency_ms", "memory_mb"],
        )

        callback(study, trial)

        viz.log_metrics.assert_called_once_with(
            {"accuracy": 0.92, "latency_ms": 18.4, "memory_mb": 512.0},
            env="optuna_accuracy_latency_memory_trial_000000",
        )

        optuna, visualization, figures = fake_visualization_module()
        with patch.dict(
            sys.modules,
            {"optuna": optuna, "optuna.visualization": visualization},
        ):
            result = callback._dashboard_figures(study)

        self.assertEqual(
            [win for win, _ in result],
            [
                "optuna-history-0",
                "optuna-history-1",
                "optuna-history-2",
                "optuna-pareto-front",
                "optuna-timeline",
            ],
        )
        visualization.plot_pareto_front.assert_called_once_with(
            study,
            target_names=["accuracy", "latency_ms", "memory_mb"],
        )
        figures["pareto"].update_layout.assert_called_once_with(
            title="Optuna Pareto Front"
        )


if __name__ == "__main__":
    unittest.main()
