#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for visdom.pytorch.VisdomLogger.

Covers both the existing params=/ExperimentStore integration (previously
untested) and the run=/RunTracker integration, plus their interaction.
Hermetic like tests/unit/tracking*.py: temp dirs for the run's own files,
and the same _unconnected_visdom() + patched _send() pattern
tests/unit/plots.py and tests/unit/tracking_graphs.py use to exercise
Visdom's plotting methods without a real server or network.
"""

import json
import os
import tempfile
import unittest
import warnings
from unittest.mock import Mock, patch

import visdom
from visdom.pytorch import VisdomLogger
from visdom.tracking import RunTracker
from visdom.tracking.core import RunTracker as _RunTrackerClass


def _unconnected_visdom():
    with (
        patch.object(visdom.Visdom, "_handle_post", return_value=True),
        patch.object(visdom.Visdom, "_start_session_reaper"),
    ):
        client = visdom.Visdom(use_incoming_socket=False)
    client._handle_post = Mock(
        side_effect=AssertionError("unexpected transport call in unit test")
    )
    return client


def _unique_win_send(msg, **kw):
    """A _send stand-in that gives every distinct requested win a stable
    id and every win=None call a fresh, unique one -- unlike a single
    constant fake win, this lets tests actually distinguish which
    window an update landed on."""
    if msg.get("win"):
        return msg["win"]
    _unique_win_send.counter += 1
    return "win_{}".format(_unique_win_send.counter)


_unique_win_send.counter = 0


def _read_events_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


class TestVisdomLoggerExperimentTracking(unittest.TestCase):
    """The pre-existing params=/ExperimentStore integration -- previously
    had no test coverage at all."""

    def setUp(self):
        self.vis = _unconnected_visdom()
        _unique_win_send.counter = 0

    def test_no_params_never_touches_experiment_apis(self):
        with patch.object(self.vis, "experiment") as mock_experiment:
            with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                with VisdomLogger(self.vis, env="e1") as tracker:
                    tracker.log("loss", 0.5)
        mock_experiment.assert_not_called()

    def test_params_calls_experiment_on_enter_and_finish_on_exit(self):
        calls = []
        with patch.object(
            self.vis,
            "experiment",
            side_effect=lambda params=None, env=None: calls.append(
                ("experiment", params, env)
            )
            or {"env_id": env},
        ):
            with patch.object(
                self.vis,
                "finish_experiment",
                side_effect=lambda status=None, env=None: calls.append(
                    ("finish_experiment", status, env)
                )
                or {"env_id": env},
            ):
                with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                    with VisdomLogger(self.vis, env="e2", params={"lr": 0.01}):
                        pass
        self.assertEqual(calls[0], ("experiment", {"lr": 0.01}, "e2"))
        self.assertEqual(calls[-1], ("finish_experiment", "finished", "e2"))

    def test_exception_in_block_marks_experiment_failed_and_still_propagates(self):
        calls = []
        with patch.object(self.vis, "experiment", return_value={"env_id": "e3"}):
            with patch.object(
                self.vis,
                "finish_experiment",
                side_effect=lambda status=None, env=None: calls.append(status)
                or {"env_id": env},
            ):
                with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                    with self.assertRaises(RuntimeError):
                        with VisdomLogger(self.vis, env="e3", params={"lr": 0.01}):
                            raise RuntimeError("training crashed")
        self.assertEqual(calls, ["failed"])

    def test_log_calls_log_metrics_alongside_line(self):
        metric_calls = []
        with patch.object(self.vis, "experiment", return_value={"env_id": "e4"}):
            with patch.object(self.vis, "finish_experiment", return_value=True):
                with patch.object(
                    self.vis,
                    "log_metrics",
                    side_effect=lambda metrics, step=None, env=None: metric_calls.append(
                        (metrics, step, env)
                    )
                    or {"env_id": env},
                ):
                    with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                        with VisdomLogger(
                            self.vis, env="e4", params={"lr": 0.01}
                        ) as tracker:
                            tracker.log("loss", 0.5)
                            tracker.log("loss", 0.3)
        self.assertEqual(
            metric_calls,
            [({"loss": 0.5}, 1, "e4"), ({"loss": 0.3}, 2, "e4")],
        )

    def test_rejected_experiment_reply_disables_tracking_but_does_not_raise(self):
        """A server-side rejection (e.g. readonly server) comes back as a
        plain reply with no exception -- __enter__ must notice it isn't
        the expected shape, warn, and fall back to plain plotting rather
        than continuing to call log_metrics()/finish_experiment() for an
        experiment that was never actually created."""
        with patch.object(self.vis, "experiment", return_value={"error": "readonly"}):
            with patch.object(self.vis, "finish_experiment") as mock_finish:
                with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                    with self.assertWarns(UserWarning):
                        with VisdomLogger(
                            self.vis, env="e5", params={"lr": 0.01}
                        ) as tracker:
                            tracker.log("loss", 0.5)  # must not raise
        mock_finish.assert_not_called()

    def test_experiment_connection_failure_disables_tracking_but_does_not_raise(self):
        with patch.object(self.vis, "experiment", side_effect=ConnectionError("down")):
            with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                with self.assertWarns(UserWarning):
                    with VisdomLogger(
                        self.vis, env="e6", params={"lr": 0.01}
                    ) as tracker:
                        tracker.log("loss", 0.5)  # must not raise

    def test_experiment_warnings_survive_warnings_as_errors(self):
        """Regression test: __enter__/__exit__/_check_experiment_reply's
        warnings now go through _safe_warn, not a bare warnings.warn --
        a malformed reply under warnings-as-errors must not raise."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with patch.object(
                self.vis, "experiment", return_value={"unexpected": "shape"}
            ):
                with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                    with VisdomLogger(
                        self.vis, env="e7", params={"lr": 0.01}
                    ) as tracker:
                        tracker.log("loss", 0.5)  # must not raise


class TestVisdomLoggerRunTracking(unittest.TestCase):
    """The run=/RunTracker integration."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name
        self.vis = _unconnected_visdom()
        _unique_win_send.counter = 0

    def tearDown(self):
        self._tmp.cleanup()

    def _plot_update_events(self, run):
        events_path = os.path.join(
            self.out_dir, json.load(open(run.path))["events_file"]
        )
        return [
            e for e in _read_events_jsonl(events_path) if e["type"] == "plot_update"
        ]

    def test_run_none_by_default_does_not_touch_tracking(self):
        with patch.object(self.vis, "_send", side_effect=_unique_win_send):
            with VisdomLogger(self.vis, env="e1") as tracker:
                tracker.log("loss", 0.5)
        self.assertIsNone(tracker.run)

    def test_logged_metrics_are_tracked_with_independent_per_window_sequences(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_unique_win_send):
            with VisdomLogger(self.vis, env="e1", run=run) as tracker:
                for epoch in range(5):
                    tracker.log("Train Loss", 1.0 / (epoch + 1))
                    tracker.log("Val Loss", 1.2 / (epoch + 1))
        run.finish()

        updates = self._plot_update_events(run)
        by_name = {}
        for e in updates:
            by_name.setdefault(e["data"]["name"], []).append(
                (e["data"]["win"], e["data"]["window_update_seq"])
            )
        self.assertEqual(len(by_name), 2)
        for name, entries in by_name.items():
            wins = {w for w, _ in entries}
            self.assertEqual(len(wins), 1, "{} should stay on one window".format(name))
            self.assertEqual([seq for _, seq in entries], [1, 2, 3, 4, 5])
        train_win = by_name["Train Loss"][0][0]
        val_win = by_name["Val Loss"][0][0]
        self.assertNotEqual(train_win, val_win)

    def test_only_actually_plotted_values_are_tracked_not_every_log_call(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_unique_win_send):
            with VisdomLogger(self.vis, env="e1", run=run, log_every=3) as tracker:
                for i in range(7):
                    tracker.log("metric", float(i), xlabel="step")
        run.finish()

        updates = self._plot_update_events(run)
        values = [e["data"]["value"] for e in updates]
        self.assertEqual(values, [0.0, 2.0, 5.0, 6.0])

    def test_pending_value_flushed_on_exit_is_tracked_too(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_unique_win_send):
            with VisdomLogger(self.vis, env="e1", run=run, log_every=5) as tracker:
                tracker.log("metric", 1.0)
                tracker.log("metric", 2.0)
        run.finish()
        updates = self._plot_update_events(run)
        self.assertEqual([e["data"]["value"] for e in updates], [1.0, 2.0])

    def test_tracking_never_breaks_logging_even_on_a_finished_run(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        run.finish()
        with patch.object(self.vis, "_send", side_effect=_unique_win_send):
            tracker = VisdomLogger(self.vis, env="e1", run=run)
            tracker.log("loss", 0.5)  # must not raise
        self.assertIn("loss", tracker._wins)

    def test_plot_failure_skips_run_tracking_without_crashing(self):
        """If viz.line() itself fails, _wins[name] is never set for that
        call -- run tracking must be skipped entirely for it, not
        attempted with a missing/stale window id."""
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "line", side_effect=ConnectionError("down")):
            tracker = VisdomLogger(self.vis, env="e1", run=run)
            with self.assertWarns(UserWarning):
                tracker.log("loss", 0.5)  # must not raise
        run.finish()
        self.assertEqual(self._plot_update_events(run), [])

    def test_unexpected_internal_bug_warns_but_does_not_break_logging(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(
            _RunTrackerClass, "log_plot_update", side_effect=TypeError("injected bug")
        ):
            with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                tracker = VisdomLogger(self.vis, env="e1", run=run)
                with self.assertWarns(RuntimeWarning):
                    tracker.log("loss", 0.5)
        self.assertIn("loss", tracker._wins)
        run.finish()

    def test_warning_stacklevel_points_at_the_users_call_site(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(
            _RunTrackerClass, "log_plot_update", side_effect=TypeError("injected bug")
        ):
            with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                tracker = VisdomLogger(self.vis, env="e1", run=run)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    tracker.log("loss", 0.5)  # this exact line should be reported
        run.finish()
        self.assertNotIn("pytorch.py", caught[0].filename)
        self.assertIn("pytorch_tracking.py", caught[0].filename)

    def test_numpy_and_torch_like_scalar_values_are_tracked_correctly(self):
        import numpy as np

        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_unique_win_send):
            with VisdomLogger(self.vis, env="e1", run=run) as tracker:
                tracker.log("loss", np.float32(0.25))
        run.finish()
        updates = self._plot_update_events(run)
        value = updates[0]["data"]["value"]
        self.assertIsInstance(value, float)
        self.assertAlmostEqual(value, 0.25, places=4)

    def test_warnings_as_errors_does_not_break_logging(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with patch.object(
                _RunTrackerClass,
                "log_plot_update",
                side_effect=TypeError("injected bug"),
            ):
                with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                    tracker = VisdomLogger(self.vis, env="e1", run=run)
                    tracker.log("loss", 0.5)  # must not raise
        self.assertIn("loss", tracker._wins)
        run.finish()

    def test_passing_a_tracked_viz_alongside_run_warns_about_double_logging(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            VisdomLogger(tvis, env="e1", run=run)

        self.assertEqual(len(caught), 1)
        self.assertTrue(issubclass(caught[0].category, RuntimeWarning))
        self.assertIn("recorded twice", str(caught[0].message))
        run.finish()

    def test_normal_usage_does_not_trigger_the_double_logging_warning(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            VisdomLogger(self.vis, env="e1", run=run)
        self.assertEqual(len(caught), 0)
        run.finish()


class TestVisdomLoggerBothIntegrationsTogether(unittest.TestCase):
    """params= (ExperimentStore) and run= (RunTracker) are independent
    and must not interfere with each other when both are used at once."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name
        self.vis = _unconnected_visdom()
        _unique_win_send.counter = 0

    def tearDown(self):
        self._tmp.cleanup()

    def test_both_together_each_record_independently(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        metric_calls = []
        with patch.object(self.vis, "experiment", return_value={"env_id": "e1"}):
            with patch.object(self.vis, "finish_experiment", return_value=True):
                with patch.object(
                    self.vis,
                    "log_metrics",
                    side_effect=lambda metrics, step=None, env=None: metric_calls.append(
                        metrics
                    )
                    or {"env_id": env},
                ):
                    with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                        with VisdomLogger(
                            self.vis, env="e1", params={"lr": 0.01}, run=run
                        ) as tracker:
                            tracker.log("loss", 0.5)
                            tracker.log("loss", 0.3)
        run.finish()

        # ExperimentStore side: both values reached log_metrics
        self.assertEqual(metric_calls, [{"loss": 0.5}, {"loss": 0.3}])

        # RunTracker side: both values reached the local JSON record too,
        # independently of the ExperimentStore calls above
        events_path = os.path.join(
            self.out_dir, json.load(open(run.path))["events_file"]
        )
        updates = [
            e for e in _read_events_jsonl(events_path) if e["type"] == "plot_update"
        ]
        self.assertEqual([e["data"]["value"] for e in updates], [0.5, 0.3])


if __name__ == "__main__":
    unittest.main()
