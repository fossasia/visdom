#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests that environments changed in memory reach disk without anyone asking.

Before autosaving, the only automatic write was an ``atexit`` handler, which
does not run on SIGTERM -- so a container stop discarded every unsaved plot.
These cover the two triggers that replace it (the timer and the update
threshold) and the bookkeeping that keeps them from writing more than needed.
"""

import tempfile
import unittest
from unittest import mock

from visdom.server.app import Application
from visdom.server.handlers.web_handlers import CloseHandler, UpdateHandler
from visdom.utils.server_utils import register_window, window

from testutils.fakes import FakeHandler
from testutils.payloads import window_args


class AutosaveTestCase(unittest.TestCase):
    """Shared temporary-directory Application."""

    save_interval = 30
    save_threshold = 50

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app = Application(
            port=8097,
            env_path=self._tmp.name,
            save_interval=self.save_interval,
            save_threshold=self.save_threshold,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def dirty_count(self, eid):
        return self.app.dirty_envs.get(eid, 0)


class TestDirtyTracking(AutosaveTestCase):
    """``mark_dirty`` records pending work and ``flush`` clears it."""

    def test_marking_accumulates_per_environment(self):
        self.app.mark_dirty("first")
        self.app.mark_dirty("first")
        self.app.mark_dirty("second")

        self.assertEqual(self.dirty_count("first"), 2)
        self.assertEqual(self.dirty_count("second"), 1)

    def test_flush_writes_and_clears_only_dirty_environments(self):
        self.app.state["written"] = {"jsons": {}, "reload": {}}
        self.app.state["untouched"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("written")

        self.assertEqual(self.app.flush_dirty(), ["written"])
        self.assertEqual(self.dirty_count("written"), 0)
        self.assertIn("written", self.app.storage.list_envs())

    def test_flush_is_a_no_op_when_nothing_changed(self):
        self.app.state["quiet"] = {"jsons": {}, "reload": {}}

        self.assertEqual(self.app.flush_dirty(), [])
        self.assertEqual(self.app.flush_envs(["quiet"]), [])

    def test_a_failed_write_is_retried_rather_than_dropped(self):
        self.app.state["fragile"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("fragile")

        with mock.patch.object(
            self.app.storage, "save_envs", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                self.app.flush_dirty()

        self.assertEqual(self.dirty_count("fragile"), 1)
        self.assertEqual(self.app.flush_dirty(), ["fragile"])

    def test_environment_is_rewritten_after_changing_again(self):
        self.app.state["repeat"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("repeat")
        self.app.flush_dirty()

        self.app.mark_dirty("repeat")
        self.assertEqual(self.app.flush_dirty(), ["repeat"])


class TestThresholdTrigger(AutosaveTestCase):
    """A busy environment is saved before its interval elapses."""

    save_threshold = 3

    def test_saves_once_the_threshold_is_reached(self):
        self.app.state["busy"] = {"jsons": {}, "reload": {}}

        self.app.mark_dirty("busy")
        self.app.mark_dirty("busy")
        self.assertNotIn("busy", self.app.storage.list_envs())

        self.app.mark_dirty("busy")
        self.assertIn("busy", self.app.storage.list_envs())
        self.assertEqual(self.dirty_count("busy"), 0)

    def test_only_the_busy_environment_is_written(self):
        self.app.state["busy"] = {"jsons": {}, "reload": {}}
        self.app.state["idle"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("idle")

        for _ in range(self.save_threshold):
            self.app.mark_dirty("busy")

        self.assertEqual(self.dirty_count("idle"), 1)
        self.assertNotIn("idle", self.app.storage.list_envs())


class TestDisabled(AutosaveTestCase):
    """Zero restores the previous behaviour of never saving on its own."""

    save_interval = 0
    save_threshold = 0

    def test_no_timer_is_started(self):
        self.assertIsNone(self.app.start_autosave())
        self.assertIsNone(self.app.autosave)

    def test_updates_never_trigger_a_write(self):
        self.app.state["busy"] = {"jsons": {}, "reload": {}}
        for _ in range(100):
            self.app.mark_dirty("busy")

        self.assertNotIn("busy", self.app.storage.list_envs())


class TestTimer(AutosaveTestCase):
    """``start_autosave`` owns a single periodic callback."""

    def test_starts_once_and_is_idempotent(self):
        started = self.app.start_autosave()

        self.assertIsNotNone(started)
        self.assertTrue(started.is_running())
        self.assertIs(self.app.start_autosave(), started)

        started.stop()

    def test_interval_is_the_configured_number_of_seconds(self):
        started = self.app.start_autosave()

        self.assertEqual(started.callback_time, self.save_interval * 1000)

        started.stop()


class TestHandlersMarkTheirWrites(unittest.TestCase):
    """The paths that mutate state tell the app the environment changed."""

    def setUp(self):
        self.handler = FakeHandler()

    def test_registering_a_window(self):
        register_window(self.handler, window(window_args(win="win_0")), "main")

        self.assertEqual(self.handler.dirtied, ["main"])

    def test_updating_a_window(self):
        args = window_args(win="win_0")
        register_window(self.handler, window(args), "main")
        self.handler.dirtied.clear()

        UpdateHandler.wrap_func(self.handler, dict(args, append=True))

        self.assertEqual(self.handler.dirtied, ["main"])

    def test_closing_a_window(self):
        register_window(self.handler, window(window_args(win="win_0")), "main")
        self.handler.dirtied.clear()

        CloseHandler.wrap_func(self.handler, {"eid": "main", "win": "win_0"})

        self.assertEqual(self.handler.dirtied, ["main"])


if __name__ == "__main__":
    unittest.main()
