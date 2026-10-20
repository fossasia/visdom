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

import pytest

import visdom
from visdom.pytorch import VisdomLogger
from visdom.tracking import RunTracker
from visdom.tracking.core import RunTracker as _RunTrackerClass

pytestmark = pytest.mark.unit


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

    def test_log_metrics_failure_does_not_suppress_run_tracking(self):
        """Regression test for a flagged issue: log_metrics() (the
        ExperimentStore call, only made when params= is set) used to run
        inside the same try/except as viz.line(). If viz.line() succeeded
        but log_metrics() then raised, the shared except caught it and
        returned early -- skipping run= tracking for a point that had
        genuinely already been plotted. run= tracking must not depend on
        the unrelated params=/ExperimentStore integration succeeding."""
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "log_metrics", side_effect=ConnectionError("down")):
            with patch.object(self.vis, "_send", side_effect=_unique_win_send):
                with self.assertWarns(UserWarning):
                    tracker = VisdomLogger(
                        self.vis, env="e1", params={"lr": 0.01}, run=run
                    )
                    tracker.log("loss", 0.5)  # viz.line() succeeds, log_metrics fails
        run.finish()
        updates = self._plot_update_events(run)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["data"]["value"], 0.5)

    def test_offline_mode_sentinel_does_not_collapse_per_metric_windows(self):
        """In offline mode viz.line() returns True for every metric, not a
        real window id -- RunTracker must still key each metric's
        per-window sequence independently (falling back to name) instead
        of merging them all onto one shared True."""
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", return_value=True):  # offline sentinel
            with VisdomLogger(self.vis, env="e1", run=run) as tracker:
                tracker.log("Train Loss", 1.0)
                tracker.log("Val Loss", 2.0)
                tracker.log("Train Loss", 0.9)
        run.finish()

        updates = self._plot_update_events(run)
        by_name = {}
        for e in updates:
            by_name.setdefault(e["data"]["name"], []).append(
                (e["data"]["win"], e["data"]["window_update_seq"])
            )
        # each metric's win is a real string (its own name), never the
        # raw True sentinel
        for name, entries in by_name.items():
            for win, _ in entries:
                self.assertIsInstance(win, str)
                self.assertEqual(win, name)
        # and sequences stay independent per metric rather than merging
        self.assertEqual([seq for _, seq in by_name["Train Loss"]], [1, 2])
        self.assertEqual([seq for _, seq in by_name["Val Loss"]], [1])

    def test_failed_send_is_retried_through_full_create_append_lifecycle(self):
        """End-to-end: real Visdom.line() -> scatter() -> _send() path
        (only _send is mocked), two metrics, one append genuinely fails
        and later succeeds on retry. Each metric should stay on one
        window throughout, and RunTracker's per-window sequence should
        end up gap-free and unaffected by the other metric's failure."""
        call_count = {"n": 0}
        win_ids = {"n": 0}

        def _send_with_one_failure(msg, **kw):
            call_count["n"] += 1
            if call_count["n"] == 3:  # Train Loss's first append
                return False
            if msg.get("win"):
                return msg["win"]
            win_ids["n"] += 1
            return "win_{}".format(win_ids["n"])

        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_send_with_one_failure):
            with VisdomLogger(self.vis, env="e1", run=run) as tracker:
                tracker.log("Train Loss", 1.0)  # creates win_1
                tracker.log("Val Loss", 2.0)  # creates win_2
                tracker.log("Train Loss", 0.9)  # append fails
                tracker.log("Val Loss", 1.8)  # append ok
                tracker.log("Train Loss", 0.8)  # retries 0.9, then sends 0.8
                tracker.log("Val Loss", 1.7)  # append ok
        run.finish()

        self.assertEqual(tracker._wins["Train Loss"], "win_1")
        self.assertEqual(tracker._wins["Val Loss"], "win_2")
        self.assertNotIn("Train Loss", tracker._pending)
        self.assertNotIn("Val Loss", tracker._pending)

        updates = self._plot_update_events(run)
        by_name = {}
        for e in updates:
            by_name.setdefault(e["data"]["name"], []).append(
                (e["data"]["win"], e["data"]["value"], e["data"]["window_update_seq"])
            )
        self.assertEqual(
            by_name["Train Loss"],
            [("win_1", 1.0, 1), ("win_1", 0.9, 2), ("win_1", 0.8, 3)],
        )
        self.assertEqual(
            by_name["Val Loss"],
            [("win_2", 2.0, 1), ("win_2", 1.8, 2), ("win_2", 1.7, 3)],
        )

    def test_failed_create_send_is_not_tracked(self):
        """Regression test for a flagged review issue ("failed sends can
        still be recorded as successful"): a client built with
        raise_exceptions=False can have viz.line() return False/None on a
        failed send instead of raising -- a real attempt the server never
        actually applied. That must not be recorded to run= at all, not
        recorded under a name-fallback window id as if it had succeeded."""
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", return_value=False):
            with VisdomLogger(self.vis, env="e1", run=run) as tracker:
                tracker.log("loss", 0.5)  # must not raise
        run.finish()
        self.assertEqual(self._plot_update_events(run), [])

    def test_failed_append_is_skipped_but_prior_success_stays_tracked(self):
        """Regression test for the exact review comment this fixes: when
        viz.line(..., update="append") returns False/None, the update
        must be skipped for run= tracking rather than recorded under the
        window id the earlier, genuinely successful send left behind. A
        successful first send followed by a non-raising failed append."""
        run = RunTracker("exp", out_dir=self.out_dir)
        results = iter(["win_1", False])
        with patch.object(self.vis, "line", side_effect=lambda *a, **kw: next(results)):
            with VisdomLogger(self.vis, env="e1", run=run) as tracker:
                tracker.log("loss", 0.5)  # creates win_1, tracked
                tracker.log("loss", 0.4)  # append fails, must be skipped
        run.finish()
        updates = self._plot_update_events(run)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["data"]["value"], 0.5)
        self.assertEqual(updates[0]["data"]["win"], "win_1")

    def test_unverifiable_truthy_win_is_cached_but_not_tracked(self):
        """Regression test for a flagged review issue: viz.line() returning
        an arbitrary truthy non-string value isn't proof of a genuine
        plot. It's still cached so it isn't retried forever, but
        params=/run= tracking must not record it."""
        run = RunTracker("exp", out_dir=self.out_dir)
        metric_calls = []
        with patch.object(self.vis, "experiment", return_value={"env_id": "e1"}):
            with patch.object(
                self.vis, "finish_experiment", return_value={"env_id": "e1"}
            ):
                with patch.object(
                    self.vis,
                    "log_metrics",
                    side_effect=lambda metrics, step=None, env=None: metric_calls.append(
                        metrics
                    )
                    or {"env_id": env},
                ):
                    with patch.object(
                        self.vis, "line", side_effect=lambda *a, **kw: 12345
                    ):
                        with VisdomLogger(
                            self.vis, env="e1", params={"lr": 0.01}, run=run
                        ) as tracker:
                            tracker.log("loss", 0.5)  # must not raise
                            self.assertEqual(tracker._wins["loss"], 12345)
        run.finish()
        self.assertEqual(metric_calls, [])
        self.assertEqual(self._plot_update_events(run), [])

    # Visdom's transport returns the raw HTTP response body without
    # checking the status code, so any of these can come back from a
    # rejected/broken request just as truthy as a real window id.
    NON_WIN_RESPONSES = {
        "json_object": '{"success": false, "error": "readonly mode"}',
        "json_array": '["error", "readonly mode"]',
        "html_error": "<html><title>502 Bad Gateway</title></html>",
        "plain_text_error": "Internal Server Error",
        # Single-token, whitespace-free, digit-free rejection bodies --
        # exactly the shape a reverse proxy or auth layer in front of
        # the Visdom server (not the server's own handlers, which
        # either write an empty 401 body or a JSON 403 body) commonly
        # returns, and the gap the old heuristic missed: no whitespace,
        # doesn't start with "{[<", so it used to pass as a plausible
        # window id. Every id Visdom itself generates contains a digit
        # (a hex timestamp or a uuid4 suffix), so requiring one closes
        # this without rejecting any real id.
        "single_token_forbidden": "Forbidden",
        "single_token_unauthorized": "Unauthorized",
        "single_token_denied": "Denied",
        "single_token_error_word": "ERROR",
        "single_token_ok": "OK",
    }

    def test_rejection_bodies_are_not_mistaken_for_a_window_id_on_creation(self):
        """Regression test: none of NON_WIN_RESPONSES -- whatever shape a
        rejected creation's body takes -- is mistaken for a real window id
        by params=/run= tracking."""
        for label, body in self.NON_WIN_RESPONSES.items():
            with self.subTest(label):
                run = RunTracker("exp", out_dir=self.out_dir)
                metric_calls = []
                with patch.object(
                    self.vis, "experiment", return_value={"env_id": "e1"}
                ), patch.object(
                    self.vis, "finish_experiment", return_value={"env_id": "e1"}
                ), patch.object(
                    self.vis,
                    "log_metrics",
                    side_effect=lambda metrics, step=None, env=None: metric_calls.append(
                        metrics
                    )
                    or {"env_id": env},
                ), patch.object(
                    self.vis, "line", side_effect=lambda *a, **kw: body
                ):
                    with VisdomLogger(
                        self.vis, env="e1", params={"lr": 0.01}, run=run
                    ) as tracker:
                        tracker.log("loss", 0.5)
                run.finish()
                self.assertEqual(metric_calls, [])
                self.assertEqual(self._plot_update_events(run), [])

    def test_rejection_bodies_are_not_mistaken_for_a_window_id_on_append(self):
        """Same regression, for an append after a genuinely successful
        creation: the exact-id-match check must reject every shape in
        NON_WIN_RESPONSES, not just JSON-looking ones."""
        for label, body in self.NON_WIN_RESPONSES.items():
            with self.subTest(label):
                run = RunTracker("exp", out_dir=self.out_dir)
                results = iter(["win_1", body])
                with patch.object(
                    self.vis, "line", side_effect=lambda *a, **kw: next(results)
                ):
                    with VisdomLogger(self.vis, env="e1", run=run) as tracker:
                        tracker.log("loss", 0.5)  # creates win_1, tracked
                        tracker.log("loss", 0.4)  # append rejected, skipped
                run.finish()
                updates = self._plot_update_events(run)
                self.assertEqual(len(updates), 1)
                self.assertEqual(updates[0]["data"]["value"], 0.5)

    def test_true_response_after_a_real_window_id_is_not_mistaken_for_success(self):
        """Regression test for the exact bug the _is_verified_win() fix
        addresses: once a real window id has been cached for a metric
        (from a genuinely successful creation), a later `True` response
        must NOT be accepted as proof that *this* window was updated --
        True only ever confirms the offline sentinel, and an
        already-established real id must be echoed back exactly
        instead. Before the fix, `win is True` was checked first and
        short-circuited straight to "verified" regardless of
        expected_win, so this append would have been wrongly tracked
        under the cached win_1 id."""
        run = RunTracker("exp", out_dir=self.out_dir)
        results = iter(["win_1", True])
        with patch.object(self.vis, "line", side_effect=lambda *a, **kw: next(results)):
            with VisdomLogger(self.vis, env="e1", run=run) as tracker:
                tracker.log("loss", 0.5)  # creates win_1, tracked
                tracker.log("loss", 0.4)  # append returns True, must be skipped
                # the real cached id must survive untouched -- not
                # clobbered by the untrustworthy True response
                self.assertEqual(tracker._wins["loss"], "win_1")
        run.finish()
        updates = self._plot_update_events(run)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["data"]["value"], 0.5)
        self.assertEqual(updates[0]["data"]["win"], "win_1")

    def test_true_response_after_a_real_window_id_also_skips_experiment_store(self):
        """Same regression as above, for params=/ExperimentStore tracking
        (viz.log_metrics()) rather than run=/RunTracker."""
        metric_calls = []
        results = iter(["win_1", True])
        with patch.object(self.vis, "experiment", return_value={"env_id": "e1"}):
            with patch.object(
                self.vis, "finish_experiment", return_value={"env_id": "e1"}
            ):
                with patch.object(
                    self.vis,
                    "log_metrics",
                    side_effect=lambda metrics, step=None, env=None: metric_calls.append(
                        metrics
                    )
                    or {"env_id": env},
                ):
                    with patch.object(
                        self.vis, "line", side_effect=lambda *a, **kw: next(results)
                    ):
                        with VisdomLogger(
                            self.vis, env="e1", params={"lr": 0.01}
                        ) as tracker:
                            tracker.log("loss", 0.5)  # creates win_1, tracked
                            tracker.log("loss", 0.4)  # append True, must be skipped
        self.assertEqual(metric_calls, [{"loss": 0.5}])

    def test_failed_send_also_skips_experiment_store_log_metrics(self):
        """The same genuine-failure check guards params=/ExperimentStore
        tracking too, for the same reason: viz.log_metrics() must not
        record a point that was never actually plotted."""
        metric_calls = []
        with patch.object(self.vis, "experiment", return_value={"env_id": "e1"}):
            with patch.object(
                self.vis,
                "log_metrics",
                side_effect=lambda metrics, step=None, env=None: metric_calls.append(
                    metrics
                )
                or {"env_id": env},
            ):
                with patch.object(self.vis, "_send", return_value=False):
                    with VisdomLogger(
                        self.vis, env="e1", params={"lr": 0.01}
                    ) as tracker:
                        tracker.log("loss", 0.5)  # must not raise
        self.assertEqual(metric_calls, [])

    def test_invalid_run_value_raises_clear_error_at_construction(self):
        """Regression test for a flagged review issue: an invalid run=
        (anything without log_plot_update) must raise TypeError at
        construction time, not crash later inside tracking's own
        best-effort warning formatting."""
        with self.assertRaises(TypeError):
            VisdomLogger(self.vis, env="e1", run=object())
        with self.assertRaises(TypeError):
            VisdomLogger(self.vis, env="e1", run="not-a-run-tracker")

    def test_run_with_non_callable_log_plot_update_raises_at_construction(self):
        """Regression test for a flagged review issue: hasattr() alone
        accepts a run= whose log_plot_update attribute exists but isn't
        callable (e.g. None, or any other non-method value), which would
        otherwise raise TypeError inside _log_to_run on every single
        logged metric instead of failing once, clearly, up front."""

        class _RunWithNoneAttribute:
            log_plot_update = None

        with self.assertRaises(TypeError):
            VisdomLogger(self.vis, env="e1", run=_RunWithNoneAttribute())

        class _RunWithNonCallableAttribute:
            log_plot_update = "not a method either"

        with self.assertRaises(TypeError):
            VisdomLogger(self.vis, env="e1", run=_RunWithNonCallableAttribute())

    def test_run_like_object_missing_run_id_does_not_crash_on_warning(self):
        """A duck-typed run= can satisfy the log_plot_update check at
        construction yet still lack run_id (e.g. a broken/partial test
        double). The best-effort warning this triggers must use it
        defensively and never crash itself."""

        class _BrokenRun:
            def log_plot_update(self, *a, **kw):
                raise TypeError("injected bug")

        with patch.object(self.vis, "_send", side_effect=_unique_win_send):
            tracker = VisdomLogger(self.vis, env="e1", run=_BrokenRun())
            with self.assertWarns(RuntimeWarning):
                tracker.log("loss", 0.5)  # must not raise
        self.assertIn("loss", tracker._wins)

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


class TestWindowIdVerificationHeuristics(unittest.TestCase):
    """Direct, table-driven coverage of _looks_like_a_window_id() and
    _is_verified_win() in isolation, independent of any VisdomLogger
    plumbing. These are the two building blocks every other test in
    this file exercises indirectly; testing them directly pins down
    every branch -- including ones no integration test happens to hit
    -- and is what actually caught the two bugs fixed here (the
    missing digit requirement, and the `win is True` ordering)."""

    # --- _looks_like_a_window_id -------------------------------------

    LOOKS_LIKE_WIN_ID_TRUE = {
        "server_generated_uuid_style": "window_3f9a4b7c-1e2d-4a5b-8c6d-9e0f1a2b3c4d",
        "client_offline_hex_timestamp_style": "window_18f3a2c9d0e",
        "short_sequential_test_id": "win_1",
        "another_sequential_test_id": "win_2",
        "digit_only": "12345",  # a digit string is still a str, so it qualifies
    }

    LOOKS_LIKE_WIN_ID_FALSE = {
        "none": None,
        "empty_string": "",
        "bool_true": True,
        "bool_false": False,
        "int": 12345,
        "float": 1.5,
        "dict": {"success": False},
        "list": ["error"],
        "json_object_string": '{"success": false}',
        "json_array_string": '["error"]',
        "html_string": "<html>502 Bad Gateway</html>",
        "whitespace_only": "   ",
        "multi_word_no_digit": "Internal Server Error",
        "single_token_no_digit_forbidden": "Forbidden",
        "single_token_no_digit_unauthorized": "Unauthorized",
        "single_token_no_digit_error": "ERROR",
        "single_token_no_digit_ok": "OK",
        "leading_whitespace_digit": " win_1",
        "trailing_whitespace_digit": "win_1 ",
        "internal_whitespace_digit": "win 1",
    }

    def test_looks_like_a_window_id_accepts_plausible_ids(self):
        for label, win in self.LOOKS_LIKE_WIN_ID_TRUE.items():
            with self.subTest(label):
                self.assertTrue(VisdomLogger._looks_like_a_window_id(win))

    def test_looks_like_a_window_id_rejects_everything_else(self):
        for label, win in self.LOOKS_LIKE_WIN_ID_FALSE.items():
            with self.subTest(label):
                self.assertFalse(VisdomLogger._looks_like_a_window_id(win))

    # --- _is_verified_win ---------------------------------------------

    def test_is_verified_win_fresh_creation_accepts_a_plausible_id(self):
        # expected_win is None on a window's first-ever creation.
        self.assertTrue(VisdomLogger._is_verified_win("win_1", None))

    def test_is_verified_win_fresh_creation_rejects_rejection_bodies(self):
        # Bug 1 regression: single-token, digit-free error bodies must
        # not be mistaken for a freshly created window's id.
        for label, body in (
            ("forbidden", "Forbidden"),
            ("unauthorized", "Unauthorized"),
            ("error", "ERROR"),
            ("json", '{"success": false}'),
            ("html", "<html>error</html>"),
            ("multi_word", "Internal Server Error"),
        ):
            with self.subTest(label):
                self.assertFalse(VisdomLogger._is_verified_win(body, None))

    def test_is_verified_win_fresh_creation_accepts_offline_sentinel(self):
        self.assertTrue(VisdomLogger._is_verified_win(True, None))

    def test_is_verified_win_append_requires_exact_match(self):
        self.assertTrue(VisdomLogger._is_verified_win("win_1", "win_1"))
        self.assertFalse(VisdomLogger._is_verified_win("win_2", "win_1"))
        self.assertFalse(VisdomLogger._is_verified_win("Forbidden", "win_1"))

    def test_is_verified_win_true_does_not_override_a_real_expected_win(self):
        # Bug 2 regression: once a real window id is established, a
        # later `True` must not be accepted in its place.
        self.assertFalse(VisdomLogger._is_verified_win(True, "win_1"))

    def test_is_verified_win_true_sentinel_requires_true_on_both_sides(self):
        self.assertTrue(VisdomLogger._is_verified_win(True, True))
        # a real-looking id does not satisfy an established True
        # sentinel either -- the sentinel's identity is True itself
        self.assertFalse(VisdomLogger._is_verified_win("win_1", True))

    def test_is_verified_win_rejects_falsy_and_unverifiable_responses(self):
        for label, win, expected_win in (
            ("false_on_creation", False, None),
            ("none_on_creation", None, None),
            ("empty_string_on_creation", "", None),
            ("int_on_creation", 12345, None),
            ("false_on_append", False, "win_1"),
            ("none_on_append", None, "win_1"),
        ):
            with self.subTest(label):
                self.assertFalse(VisdomLogger._is_verified_win(win, expected_win))


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

    def test_nesting_run_inside_visdomlogger_silently_drops_the_exit_flush(self):
        """Documents the exact foot-gun the docstring warns against:
        nesting the two context managers in the wrong order (run= inner,
        VisdomLogger outer) finishes run before VisdomLogger.__exit__'s
        own pending-value flush runs, so that flushed update is silently
        dropped from run's record -- RunAlreadyFinishedError is swallowed
        by design, the same as any other already-finished-run write, so
        this must not raise. The documented order (run outer, VisdomLogger
        inner) does not have this problem; see
        test_both_together_each_record_independently above."""
        run = RunTracker("exp", out_dir=self.out_dir)
        with patch.object(self.vis, "_send", side_effect=_unique_win_send):
            with VisdomLogger(self.vis, env="e1", run=run, log_every=5) as tracker:
                with run:  # wrong order: run finishes before __exit__ below
                    tracker.log("loss", 1.0)  # first call -> plotted & tracked
                    tracker.log("loss", 2.0)  # buffered by log_every=5
                # VisdomLogger.__exit__ flushes "loss"=2.0 here, but run is
                # already finished -- must not raise.
        events_path = os.path.join(
            self.out_dir, json.load(open(run.path))["events_file"]
        )
        updates = [
            e for e in _read_events_jsonl(events_path) if e["type"] == "plot_update"
        ]
        self.assertEqual([e["data"]["value"] for e in updates], [1.0])


if __name__ == "__main__":
    unittest.main()
