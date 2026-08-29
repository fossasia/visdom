#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for visdom.tracking.graphs.TrackedVisdom.

Hermetic like tests/unit/tracking.py: temp dirs for the run's own files, and
the same _unconnected_visdom() + patched _send() pattern tests/unit/plots.py
uses to exercise Visdom's plotting methods without a real server or network.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pytest
import visdom

from visdom.tracking import GRAPH_METHODS, NON_GRAPH_METHODS, RunTracker

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


def _read_events_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


class TestTrackedVisdomAutoLogging(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name
        self.vis = _unconnected_visdom()

    def tearDown(self):
        self._tmp.cleanup()

    def _plot_update_events(self, run):
        events_path = os.path.join(
            self.out_dir, json.load(open(run.path))["events_file"]
        )
        return [
            e for e in _read_events_jsonl(events_path) if e["type"] == "plot_update"
        ]

    def test_repeated_updates_to_same_window_get_increasing_seq_and_deltas(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = self.vis
        run_tvis = run.track(tvis)

        with patch.object(tvis, "_send", side_effect=lambda msg, **kw: msg.get("win")):
            run_tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
            run_tvis.line(
                X=np.array([1]), Y=np.array([0.5]), win="loss", update="append"
            )
            run_tvis.line(
                X=np.array([2]), Y=np.array([0.3]), win="loss", update="append"
            )
        run.finish()

        updates = self._plot_update_events(run)
        seqs = [e["data"]["window_update_seq"] for e in updates]
        self.assertEqual(seqs, [1, 2, 3])
        self.assertIsNone(updates[0]["data"]["seconds_since_prev_update_to_window"])
        for e in updates[1:]:
            self.assertIsNotNone(e["data"]["seconds_since_prev_update_to_window"])
            self.assertGreaterEqual(e["data"]["seconds_since_prev_update_to_window"], 0)

    def test_different_windows_get_independent_sequences(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)

        with patch.object(
            self.vis, "_send", side_effect=lambda msg, **kw: msg.get("win")
        ):
            tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
            tvis.line(X=np.array([0]), Y=np.array([1.0]), win="accuracy")
            tvis.line(X=np.array([1]), Y=np.array([0.9]), win="loss", update="append")
        run.finish()

        updates = self._plot_update_events(run)
        by_win = {}
        for e in updates:
            by_win.setdefault(e["data"]["win"], []).append(
                e["data"]["window_update_seq"]
            )
        self.assertEqual(by_win["loss"], [1, 2])
        self.assertEqual(by_win["accuracy"], [1])

    def test_auto_generated_window_name_is_captured_from_return_value(self):
        """win=None -> the server assigns a name; the return value (not the
        None the caller passed) must be what gets recorded."""
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)

        with patch.object(
            self.vis, "_send", side_effect=lambda msg, **kw: "window_auto123"
        ):
            tvis.bar(X=np.array([1, 2, 3]), win=None)
        run.finish()

        updates = self._plot_update_events(run)
        self.assertEqual(updates[0]["data"]["win"], "window_auto123")

    def test_non_graph_methods_pass_through_unwrapped_and_unlogged(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)

        with patch.object(self.vis, "close", return_value=True) as mock_close:
            result = tvis.close(win="loss")
        self.assertTrue(result)
        mock_close.assert_called_once_with(win="loss")
        run.finish()

        self.assertEqual(self._plot_update_events(run), [])

    def test_attribute_access_and_assignment_proxy_through(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)
        self.assertEqual(tvis.env, self.vis.env)
        tvis.env = "some_other_env"
        self.assertEqual(self.vis.env, "some_other_env")
        run.finish()

    def test_plot_exception_propagates_and_is_logged_as_plot_error(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)

        with patch.object(
            self.vis, "_send", side_effect=ConnectionError("server down")
        ):
            with self.assertRaises(ConnectionError):
                tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
        run.finish()

        events_path = os.path.join(
            self.out_dir, json.load(open(run.path))["events_file"]
        )
        errors = [
            e for e in _read_events_jsonl(events_path) if e["type"] == "plot_error"
        ]
        self.assertEqual(len(errors), 1)
        self.assertIn("ConnectionError", errors[0]["data"]["error"])
        self.assertIn("server down", errors[0]["data"]["error"])

    def test_tracking_never_breaks_plotting_even_on_a_finished_run(self):
        """The whole point of the proxy is to be transparent -- a plot call
        must succeed identically whether or not logging it succeeds."""
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)
        run.finish()  # tracker is now terminal; log_plot_update would raise

        with patch.object(self.vis, "_send", side_effect=lambda msg, **kw: "loss"):
            result = tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
        self.assertEqual(result, "loss")  # plot call itself still succeeded

    def test_unresolvable_win_skips_logging_without_erroring(self):
        """A falsy/unusable return value (e.g. a swallowed connection error
        in raise_exceptions=False mode) must not produce a bogus event."""
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)

        with patch.object(self.vis, "_send", side_effect=lambda msg, **kw: False):
            result = tvis.line(X=np.array([0]), Y=np.array([1.0]))  # no win kwarg
        self.assertFalse(result)
        run.finish()

        self.assertEqual(self._plot_update_events(run), [])

    def test_graph_methods_set_matches_actual_visdom_methods(self):
        """Every name in GRAPH_METHODS must exist as a callable Visdom
        method -- guards against the whitelist drifting from the real API
        (e.g. a method getting renamed) without a test noticing."""
        for method_name in GRAPH_METHODS:
            self.assertTrue(
                callable(getattr(self.vis, method_name, None)),
                "GRAPH_METHODS lists {0!r} but Visdom has no such "
                "callable method".format(method_name),
            )

    def test_every_public_visdom_method_is_classified(self):
        """The other direction of the check above: every public method
        Visdom actually has must be in GRAPH_METHODS *or*
        NON_GRAPH_METHODS. If a future Visdom PR adds a new chart type
        (or renames one), this fails instead of the new method silently
        going untracked forever with nobody noticing."""
        import inspect

        actual_methods = {
            name
            for name, member in inspect.getmembers(
                visdom.Visdom, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        }
        classified = GRAPH_METHODS | NON_GRAPH_METHODS
        unclassified = actual_methods - classified
        self.assertEqual(
            unclassified,
            set(),
            "Visdom has method(s) {0} that aren't in GRAPH_METHODS or "
            "NON_GRAPH_METHODS in visdom/tracking/graphs.py -- decide "
            "whether each belongs in one or the other.".format(sorted(unclassified)),
        )
        # and the reverse: nothing listed that Visdom no longer has
        # (a renamed/removed method should be caught here too).
        stale = classified - actual_methods
        self.assertEqual(
            stale,
            set(),
            "GRAPH_METHODS/NON_GRAPH_METHODS list method(s) {0} that no "
            "longer exist on Visdom -- likely renamed or removed "
            "upstream.".format(sorted(stale)),
        )

    def test_delegating_methods_are_not_double_logged(self):
        """histogram() calls self.bar() and stem() calls self.scatter()
        internally, but that `self` is the real Visdom instance, not this
        proxy -- calling tvis.histogram(...) must log exactly one event
        ('histogram'), never an extra 'bar' event alongside it."""
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)

        with patch.object(
            self.vis, "_send", side_effect=lambda msg, **kw: msg.get("win") or "auto"
        ):
            tvis.histogram(X=np.random.randn(50), win="hist1")
            tvis.stem(X=np.array([1, 2, 3]), Y=np.array([1, 2, 3]), win="stem1")
        run.finish()

        updates = self._plot_update_events(run)
        methods_logged = [e["data"]["method"] for e in updates]
        self.assertEqual(methods_logged, ["histogram", "stem"])

    def test_unexpected_internal_bug_warns_but_does_not_break_plotting(self):
        """RunAlreadyFinishedError is expected/benign and stays silent (see
        test_tracking_never_breaks_plotting_even_on_a_finished_run). Any
        *other* exception from our own tracking code is still swallowed
        (plotting must never break) but must not vanish without a trace,
        or a real bug here would be nearly undebuggable."""
        run = RunTracker("exp", out_dir=self.out_dir)
        tvis = run.track(self.vis)

        with patch.object(
            RunTracker, "log_plot_update", side_effect=TypeError("injected bug")
        ):
            with patch.object(
                self.vis, "_send", side_effect=lambda msg, **kw: msg.get("win")
            ):
                with self.assertWarns(RuntimeWarning):
                    result = tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
        self.assertEqual(result, "loss")  # plot call still succeeded
        run.finish()


if __name__ == "__main__":
    unittest.main()
