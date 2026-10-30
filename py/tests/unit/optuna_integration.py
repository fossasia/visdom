#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the optional Optuna experiment integration."""

import os
import sys
import tempfile
import threading
import types
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

from visdom.integrations import OptunaCallback

pytestmark = pytest.mark.unit


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


def recording_viz():
    """A client whose experiment writes come back recorded, as from a server.

    ``_last_response_status`` is set to ``None`` rather than left for ``Mock``
    to auto-create, since a real client always has it (``None`` until a
    request is made, then the status of the last one) and the integration
    reads it to tell a 409 conflict apart from another rejection.
    """
    viz = Mock()
    viz._last_response_status = None
    stored = {"env_id": "stored"}
    viz.experiment.return_value = stored
    viz.log_metrics.return_value = stored
    viz.finish_experiment.return_value = stored
    return viz


def reject_with_status(viz, method, status, body="<html>error</html>"):
    """Make ``viz.<method>`` answer like a real client call that got ``status``.

    Sets the return value to the rejected body and ``_last_response_status``
    to ``status``, mirroring what ``Visdom._experiment_request`` leaves behind
    after a real request: the two always change together.
    """
    getattr(viz, method).return_value = body

    def record_status(*args, **kwargs):
        viz._last_response_status = status
        return body

    getattr(viz, method).side_effect = record_status


def fake_visualization_module(
    intermediate_error=None, contour_error=None, history_error=None
):
    visualization = types.ModuleType("optuna.visualization")
    figures = {
        "history": Mock(name="history"),
        "importance": Mock(name="importance"),
        "intermediate": Mock(name="intermediate"),
        "contour": Mock(name="contour"),
        "pareto": Mock(name="pareto"),
        "timeline": Mock(name="timeline", data=()),
    }
    visualization.plot_optimization_history = Mock(
        return_value=figures["history"], side_effect=history_error
    )
    visualization.plot_param_importances = Mock(return_value=figures["importance"])
    visualization.plot_intermediate_values = Mock(
        return_value=figures["intermediate"], side_effect=intermediate_error
    )
    visualization.plot_contour = Mock(
        return_value=figures["contour"], side_effect=contour_error
    )
    visualization.plot_pareto_front = Mock(return_value=figures["pareto"])
    visualization.plot_timeline = Mock(return_value=figures["timeline"])

    optuna = types.ModuleType("optuna")
    optuna.__path__ = []
    optuna.visualization = visualization
    return optuna, visualization, figures


class TestOptunaEnvironmentIds(unittest.TestCase):
    def test_study_name_slashes_are_sanitized_before_trial_ids_are_used(self):
        trial = make_trial(number=3)
        study = make_study([trial])
        study.study_name = "team/study"
        viz = recording_viz()
        callback = OptunaCallback(viz)

        callback(study, trial)

        self.assertEqual(callback.study_env(study), "optuna_team_study")
        self.assertEqual(
            callback.trial_env(trial, study),
            "optuna_team_study_trial_000003",
        )
        self.assertEqual(callback._trial_envs, ["optuna_team_study_trial_000003"])
        self.assertEqual(
            viz.experiment.call_args.kwargs["env"],
            "optuna_team_study_trial_000003",
        )


class TestOptunaDashboardErrorHandling(unittest.TestCase):
    def test_figure_generation_failure_uses_dashboard_error_policy(self):
        trial = make_trial()
        study = make_study([trial])
        study.best_trial = trial
        optuna, visualization, _ = fake_visualization_module(
            history_error=RuntimeError("figure exploded")
        )
        modules = {
            "optuna": optuna,
            "optuna.visualization": visualization,
        }

        warning_viz = recording_viz()
        warning_callback = OptunaCallback(warning_viz)
        warning_callback._trial_envs = [warning_callback.trial_env(trial, study)]
        with patch.dict(sys.modules, modules):
            with self.assertWarnsRegex(
                RuntimeWarning,
                "failed to update the dashboard: figure exploded",
            ):
                self.assertFalse(warning_callback.update_dashboard(study))
        warning_viz.text.assert_not_called()

        raising_callback = OptunaCallback(Mock(), raise_on_error=True)
        raising_callback._trial_envs = [raising_callback.trial_env(trial, study)]
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "figure exploded"):
                raising_callback.update_dashboard(study)


class TestOptunaIntermediateValues(unittest.TestCase):
    def test_logs_intermediate_values_in_step_order_before_final_metric(self):
        viz = recording_viz()
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
        viz = recording_viz()
        trial = make_trial(values=(0.2,))
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")

        callback(make_study([trial]), trial)

        viz.log_metrics.assert_called_once_with(
            {"objective": 0.2}, env="optuna_quadratic_trial_000000"
        )

    def test_pruned_trial_preserves_intermediate_values_and_failed_status(self):
        viz = recording_viz()
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

        warning_viz = recording_viz()
        warning_viz.log_metrics.side_effect = RuntimeError("offline")
        warning_callback = OptunaCallback(warning_viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "failed to log trial 0: offline"):
            warning_callback(study, trial)
        warning_viz.finish_experiment.assert_not_called()
        self.assertEqual(warning_callback._trial_envs, [])

        raising_viz = recording_viz()
        raising_viz.log_metrics.side_effect = RuntimeError("offline")
        raising_callback = OptunaCallback(
            raising_viz,
            dashboard_env="optuna_quadratic",
            raise_on_error=True,
        )
        with self.assertRaisesRegex(RuntimeError, "offline"):
            raising_callback(study, trial)


class TestOptunaRejectedWrites(unittest.TestCase):
    """A write the server refuses must not pass for a recorded trial."""

    # What visdom hands back for a generic rejection with no status recorded.
    REJECTED = "<html><title>Visdom - Error</title></html>"

    def test_rerun_into_a_finished_trial_env_warns(self):
        viz = recording_viz()
        reject_with_status(viz, "experiment", 409)
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")

        with self.assertWarnsRegex(
            RuntimeWarning,
            "failed to log trial 0: visdom did not record it in env "
            "'optuna_quadratic_trial_000000'.*already finished there"
            ".*same dashboard_env, use a new one or delete",
        ):
            callback(make_study([trial]), trial)
        viz.log_metrics.assert_not_called()
        viz.finish_experiment.assert_not_called()
        self.assertEqual(callback._trial_envs, [])

    def test_advice_names_study_name_when_envs_come_from_it(self):
        viz = recording_viz()
        reject_with_status(viz, "experiment", 409)
        trial = make_trial()
        callback = OptunaCallback(viz)
        with self.assertWarnsRegex(
            RuntimeWarning,
            "'optuna_quadratic_trial_000000'.*already finished there"
            ".*same study_name, use a new one or delete",
        ):
            callback(make_study([trial]), trial)

    def test_rejection_raises_with_raise_on_error(self):
        viz = recording_viz()
        reject_with_status(viz, "experiment", 409)
        trial = make_trial()
        callback = OptunaCallback(
            viz, dashboard_env="optuna_quadratic", raise_on_error=True
        )
        with self.assertRaisesRegex(RuntimeError, "did not record it"):
            callback(make_study([trial]), trial)

    def test_every_write_is_checked(self):
        trial = make_trial(intermediate_values={0: 0.9})
        for method in ("log_metrics", "finish_experiment"):
            viz = recording_viz()
            reject_with_status(viz, method, 409)
            callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
            with self.assertWarnsRegex(RuntimeWarning, "did not record it"):
                callback(make_study([trial]), trial)
            self.assertEqual(callback._trial_envs, [])

    def test_unreachable_server_warns(self):
        viz = recording_viz()
        viz.experiment.return_value = False
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "did not record it"):
            callback(make_study([trial]), trial)

    def test_a_rejected_metric_closes_the_created_trial_as_failed(self):
        viz = recording_viz()
        reject_with_status(viz, "log_metrics", 409)
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "did not record it"):
            callback(make_study([trial]), trial)
        viz.finish_experiment.assert_called_once_with(
            status="failed", env="optuna_quadratic_trial_000000"
        )

    @staticmethod
    def _unreachable_metric_write(viz):
        viz.log_metrics.return_value = False

    @staticmethod
    def _metric_write_raises(viz):
        viz.log_metrics.side_effect = ConnectionError("network down")

    @staticmethod
    def _metric_write_server_error(viz):
        reject_with_status(viz, "log_metrics", 503)

    def test_a_transient_metric_failure_leaves_the_trial_open(self):
        """A network or server error isn't final, so the trial stays open."""
        for break_it in (
            self._unreachable_metric_write,
            self._metric_write_raises,
            self._metric_write_server_error,
        ):
            viz = recording_viz()
            break_it(viz)
            trial = make_trial()
            callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
            with self.assertWarnsRegex(RuntimeWarning, "once the server can be"):
                callback(make_study([trial]), trial)
            viz.finish_experiment.assert_not_called()
            self.assertEqual(callback._trial_envs, [])
            self.assertIn("optuna_quadratic_trial_000000", callback._pending)

    def test_a_rejected_finish_is_not_sent_again(self):
        viz = recording_viz()
        reject_with_status(viz, "finish_experiment", 409)
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "did not record it"):
            callback(make_study([trial]), trial)
        viz.finish_experiment.assert_called_once_with(
            status="finished", env="optuna_quadratic_trial_000000"
        )

    def test_a_reply_without_env_id_is_not_taken_as_recorded(self):
        viz = recording_viz()
        viz.experiment.return_value = {"error": "something else"}
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "did not record it"):
            callback(make_study([trial]), trial)

    def test_a_401_or_403_names_the_key_or_readonly_mode_not_an_old_run(self):
        """An expired key or a readonly server is not a conflict with a past run."""
        for status in (401, 403):
            viz = recording_viz()
            reject_with_status(viz, "log_metrics", status)
            trial = make_trial()
            callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
            with self.assertWarnsRegex(
                RuntimeWarning,
                r"status {}.*API key.*readonly".format(status),
            ) as caught:
                callback(make_study([trial]), trial)
            self.assertNotIn("study_name", str(caught.warning))
            self.assertNotIn("dashboard_env", str(caught.warning))
            # Still a final rejection: the half-written trial is closed.
            viz.finish_experiment.assert_called_once_with(
                status="failed", env="optuna_quadratic_trial_000000"
            )

    def test_a_400_names_the_status_not_an_old_run(self):
        """A malformed request is a bug in this integration, not a stale run."""
        viz = recording_viz()
        reject_with_status(viz, "experiment", 400)
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "status 400") as caught:
            callback(make_study([trial]), trial)
        self.assertNotIn("study_name", str(caught.warning))
        self.assertNotIn("already finished there", str(caught.warning))

    def test_a_404_mid_trial_still_closes_it_as_failed(self):
        """A rejection the server never gave a status 409 still ends the trial.

        This is the gap that used to leave a trial open forever: a rejection
        that was not the one case the old code recognised as final was never
        closed, so it never finished and stayed out of the dashboard.
        """
        viz = recording_viz()
        reject_with_status(viz, "log_metrics", 404)
        trial = make_trial(intermediate_values={0: 0.9})
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "status 404"):
            callback(make_study([trial]), trial)
        viz.finish_experiment.assert_called_once_with(
            status="failed", env="optuna_quadratic_trial_000000"
        )

    def test_a_refused_cleanup_is_reported_with_the_original_error(self):
        viz = recording_viz()
        reject_with_status(viz, "log_metrics", 409)
        reject_with_status(viz, "finish_experiment", 403)
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            callback(make_study([trial]), trial)
        messages = [str(w.message) for w in caught]
        self.assertTrue(
            any(
                "could not mark trial 0 as failed" in m and "403" in m for m in messages
            )
        )
        self.assertTrue(
            any(
                "failed to log trial 0" in m and "already finished" in m
                for m in messages
            )
        )

    def test_a_refused_cleanup_does_not_hide_the_original_error(self):
        viz = recording_viz()
        reject_with_status(viz, "log_metrics", 409)
        reject_with_status(viz, "finish_experiment", 403)
        trial = make_trial()
        callback = OptunaCallback(
            viz, dashboard_env="optuna_quadratic", raise_on_error=True
        )
        with self.assertWarnsRegex(RuntimeWarning, "could not mark trial 0"):
            with self.assertRaisesRegex(RuntimeError, "already finished"):
                callback(make_study([trial]), trial)

    def test_a_rejection_with_no_status_still_closes_the_trial(self):
        """Covers a client that leaves no status (an older or custom one),
        so the old behaviour -- warn and still close a half-written trial --
        is kept rather than silently leaving it open."""
        viz = recording_viz()
        viz.experiment.return_value = self.REJECTED
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with self.assertWarnsRegex(RuntimeWarning, "did not record it"):
            callback(make_study([trial]), trial)
        viz.log_metrics.assert_not_called()
        viz.finish_experiment.assert_not_called()

    def test_offline_client_is_not_a_rejection(self):
        """True is the client's offline sentinel; nothing could be confirmed."""
        viz = Mock()
        viz.experiment.return_value = True
        viz.log_metrics.return_value = True
        viz.finish_experiment.return_value = True
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            callback(make_study([trial]), trial)

    def test_recorded_writes_do_not_warn(self):
        stored = {"env_id": "optuna_quadratic_trial_000000"}
        viz = recording_viz()
        viz.experiment.return_value = stored
        viz.log_metrics.return_value = stored
        viz.finish_experiment.return_value = stored
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            callback(make_study([trial]), trial)
        self.assertEqual(callback._trial_envs, ["optuna_quadratic_trial_000000"])


class FlakyServer:
    """A stand-in client that stores trials the way the server does.

    While ``down`` is set nothing is stored and no reply comes back. With
    ``lose_reply`` set the write is stored but its reply is lost, as when a
    connection drops after the server has acted on a request.
    """

    def __init__(self):
        self._last_response_status = None
        self.down = False
        self.lose_reply = False
        self.calls = 0
        self.stored = {}
        self.lock = threading.Lock()

    def _write(self, env, apply):
        with self.lock:
            self.calls += 1
            self._last_response_status = None
            if self.down:
                return False
            run = self.stored.setdefault(env, {"metrics": [], "status": None})
            if run["status"] is not None:
                self._last_response_status = 409
                return "<html>409</html>"
            apply(run)
            return False if self.lose_reply else {"env_id": env}

    def experiment(self, env=None, **kwargs):
        return self._write(env, lambda run: run.update(name=kwargs["name"]))

    def log_metrics(self, metrics, step=None, env=None):
        return self._write(env, lambda run: run["metrics"].append((step, metrics)))

    def finish_experiment(self, status="finished", env=None):
        return self._write(env, lambda run: run.update(status=status))

    def search_experiments(self, query=None):
        with self.lock:
            self.calls += 1
            if self.down:
                return None
            env = query.split('"')[1]
            if env not in self.stored:
                return {"experiments": []}
            run = self.stored[env]
            metrics = [
                {"key": key, "value": value, "step": step}
                for step, values in run["metrics"]
                for key, value in values.items()
            ]
            return {
                "experiments": [
                    {"env_id": env, "status": run["status"], "metrics": metrics}
                ]
            }


class TestOptunaTransientFailures(unittest.TestCase):
    """A server blip or outage must not lose, repeat or block on a trial."""

    ENV = "optuna_quadratic_trial_{:06d}"

    def callback(self, viz, **kwargs):
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic", **kwargs)
        callback._retry_backoff = 0  # retry with the next trial
        return callback

    def assert_stored_once(self, server, trial):
        run = server.stored[self.ENV.format(trial.number)]
        expected = [
            (step, {"intermediate_value": value})
            for step, value in sorted(trial.intermediate_values.items())
        ] + [(None, {"objective": trial.values[0]})]
        self.assertEqual(run["metrics"], expected)
        self.assertEqual(run["status"], "finished")

    def test_a_failed_write_is_sent_once_without_waiting(self):
        viz = recording_viz()
        viz.log_metrics.return_value = False
        trial = make_trial()
        callback = OptunaCallback(viz, dashboard_env="optuna_quadratic")
        with patch("visdom.integrations.optuna.time.sleep") as sleep:
            with self.assertWarns(RuntimeWarning):
                callback(make_study([trial]), trial)
        sleep.assert_not_called()
        self.assertEqual(viz.log_metrics.call_count, 1)
        self.assertIn(self.ENV.format(0), callback._pending)

    def test_a_refusal_is_not_set_aside(self):
        viz = recording_viz()
        reject_with_status(viz, "log_metrics", 403)
        trial = make_trial()
        callback = self.callback(viz)
        with self.assertWarns(RuntimeWarning):
            callback(make_study([trial]), trial)
        self.assertEqual(viz.log_metrics.call_count, 1)
        self.assertEqual(callback._pending, {})

    def test_a_metric_whose_reply_was_lost_is_not_sent_twice(self):
        server = FlakyServer()
        callback = self.callback(server)
        first = make_trial(0, intermediate_values={0: 0.9, 1: 0.8})
        study = make_study([first])
        original = server.log_metrics

        def lose_first_reply(metrics, step=None, env=None):
            server.lose_reply = step == 0 and env == self.ENV.format(0)
            try:
                return original(metrics, step=step, env=env)
            finally:
                server.lose_reply = False

        server.log_metrics = lose_first_reply
        with self.assertWarns(RuntimeWarning):
            callback(study, first)
        server.log_metrics = original
        self.assertTrue(callback.flush())
        self.assert_stored_once(server, first)

    def test_a_finish_whose_reply_was_lost_is_not_reported_as_an_old_run(self):
        server = FlakyServer()
        callback = self.callback(server)
        trial = make_trial()
        original = server.finish_experiment

        def lose_reply(status="finished", env=None):
            server.lose_reply = True
            try:
                return original(status=status, env=env)
            finally:
                server.lose_reply = False

        server.finish_experiment = lose_reply
        with self.assertWarns(RuntimeWarning):
            callback(make_study([trial]), trial)
        server.finish_experiment = Mock(side_effect=original)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertTrue(callback.flush())
        server.finish_experiment.assert_not_called()
        self.assert_stored_once(server, trial)
        self.assertEqual(callback._trial_envs, [self.ENV.format(0)])

    def test_an_outage_mid_trial_resumes_where_it_stopped(self):
        server = FlakyServer()
        callback = self.callback(server)
        first = make_trial(0, intermediate_values={0: 0.9, 1: 0.8})
        second = make_trial(1, intermediate_values={0: 0.7})
        study = make_study([first, second])
        original = server._write
        sent = []

        def down_after_two(env, apply):
            sent.append(env)
            server.down = len(sent) > 2
            return original(env, apply)

        server._write = down_after_two
        with self.assertWarns(RuntimeWarning):
            callback(study, first)
        server._write = original
        server.down = False
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            callback(study, second)
        self.assert_stored_once(server, first)
        self.assert_stored_once(server, second)
        self.assertEqual(callback._pending, {})
        self.assertEqual(callback._trial_envs, [self.ENV.format(0), self.ENV.format(1)])

    def test_trials_do_not_wait_on_a_down_server(self):
        """After one failure, trials are set aside without any request."""
        server = FlakyServer()
        callback = OptunaCallback(server, dashboard_env="optuna_quadratic")
        trials = [make_trial(n) for n in range(4)]
        study = make_study(trials)
        server.down = True
        with self.assertWarns(RuntimeWarning):
            callback(study, trials[0])
        calls = server.calls
        for trial in trials[1:]:
            with self.assertWarns(RuntimeWarning):
                callback(study, trial)
        self.assertEqual(server.calls, calls)
        self.assertEqual(
            list(callback._pending), [self.ENV.format(n) for n in range(4)]
        )
        server.down = False
        self.assertTrue(callback.flush())
        for trial in trials:
            self.assert_stored_once(server, trial)
        self.assertEqual(callback._trial_envs, [self.ENV.format(n) for n in range(4)])

    def test_retries_back_off_up_to_a_limit(self):
        server = FlakyServer()
        callback = OptunaCallback(server, dashboard_env="optuna_quadratic")
        server.down = True
        waits = []
        with patch("visdom.integrations.optuna.time.monotonic", return_value=0.0):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                trial = make_trial(0)
                callback(make_study([trial]), trial)
                waits.append(callback._retry_wait)
                for _ in range(8):
                    callback.flush()
                    waits.append(callback._retry_wait)
        self.assertEqual(
            waits, [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0, 300.0]
        )

    def test_update_dashboard_logs_set_aside_trials_right_away(self):
        server = FlakyServer()
        callback = OptunaCallback(server, dashboard_env="optuna_quadratic")
        trial = make_trial(intermediate_values={0: 0.9})
        server.down = True
        with self.assertWarns(RuntimeWarning):
            callback(make_study([trial]), trial)
        server.down = False
        with patch.object(callback, "_write_dashboard", return_value=True):
            self.assertTrue(callback.update_dashboard(make_study([trial])))
        self.assert_stored_once(server, trial)
        self.assertEqual(callback._pending, {})

    def test_the_dashboard_waits_for_the_server_then_refreshes(self):
        server = FlakyServer()
        callback = self.callback(server, create_dashboard=True)
        trials = [make_trial(n) for n in range(2)]
        study = make_study(trials)
        with patch.object(callback, "_write_dashboard") as write_dashboard:
            server.down = True
            with self.assertWarns(RuntimeWarning):
                callback(study, trials[0])
            write_dashboard.assert_not_called()
            server.down = False
            callback(study, trials[1])
        write_dashboard.assert_called_once()

    def test_raise_on_error_still_sets_the_trial_aside(self):
        viz = recording_viz()
        viz.log_metrics.return_value = False
        trial = make_trial()
        callback = self.callback(viz, raise_on_error=True)
        with self.assertRaisesRegex(RuntimeError, "could not be reached"):
            callback(make_study([trial]), trial)
        self.assertIn(self.ENV.format(0), callback._pending)

    def test_concurrent_trials_through_a_flaky_server_are_stored_once(self):
        """Optuna's n_jobs>1 runs callbacks on several threads at once."""
        import random

        server = FlakyServer()
        rng = random.Random(0)
        original = server._write

        def flaky(env, apply):
            with server.lock:
                roll = rng.random()
                server.down = roll < 0.2
                server.lose_reply = 0.2 <= roll < 0.35
            try:
                return original(env, apply)
            finally:
                server.lose_reply = False

        server._write = flaky
        callback = self.callback(server)
        trials = [
            make_trial(n, values=(n / 10,), intermediate_values={0: 1.0, 1: 0.5})
            for n in range(40)
        ]
        study = make_study(trials)

        def run(chunk):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for trial in chunk:
                    callback(study, trial)

        workers = [threading.Thread(target=run, args=(trials[i::4],)) for i in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        server._write = original
        server.down = False
        self.assertTrue(callback.flush())
        for trial in trials:
            self.assert_stored_once(server, trial)
        self.assertEqual(
            sorted(callback._trial_envs), sorted(self.ENV.format(n) for n in range(40))
        )


class TestResponseStatusPerThread(unittest.TestCase):
    """Callbacks run on Optuna's worker threads and share one client."""

    def test_each_thread_reads_its_own_status(self):
        import visdom

        with tempfile.TemporaryDirectory() as tmp:
            viz = visdom.Visdom(
                offline=True, log_to_filename=os.path.join(tmp, "visdom.log")
            )
        viz._last_response_status = 409
        seen = []

        def other_worker():
            seen.append(viz._last_response_status)
            viz._last_response_status = 403

        worker = threading.Thread(target=other_worker)
        worker.start()
        worker.join()
        self.assertEqual(seen, [None])
        self.assertEqual(viz._last_response_status, 409)


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


class TestOptunaContourDashboard(unittest.TestCase):
    def test_skips_contour_when_optuna_rejects_params(self):
        trials = [make_trial(number=0), make_trial(number=1)]
        study = make_study(trials)
        optuna, visualization, figures = fake_visualization_module(
            contour_error=ValueError("parameter has not been sampled")
        )
        callback = OptunaCallback(
            Mock(),
            dashboard_env="optuna_quadratic",
            contour_params=["x", "missing"],
        )

        with patch.dict(
            sys.modules,
            {"optuna": optuna, "optuna.visualization": visualization},
        ):
            result = callback._dashboard_figures(study)

        self.assertEqual(
            [win for win, _ in result],
            ["optuna-history", "optuna-importance", "optuna-timeline"],
        )
        visualization.plot_contour.assert_called_once_with(
            study,
            params=["x", "missing"],
            target_name="objective",
        )
        figures["contour"].update_layout.assert_not_called()


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
        viz = recording_viz()
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
        viz = recording_viz()
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
