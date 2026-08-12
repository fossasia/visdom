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

import json
import tempfile
import unittest
from unittest import mock

from visdom.server.app import Application
from visdom.server.handlers.socket_handlers import AnySocketHandlerOrWrapper
from visdom.server.handlers.web_handlers import CloseHandler, UpdateHandler
from visdom.utils.server_utils import register_window, window

from testutils.fakes import FakeHandler
from testutils.payloads import embeddings_pane, table_pane, window_args


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

    def test_an_environment_the_backend_declined_stays_marked(self):
        self.app.state["skipped"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("skipped")

        with mock.patch.object(self.app.storage, "save_envs", return_value=[]):
            self.assertEqual(self.app.flush_dirty(), [])

        self.assertEqual(self.dirty_count("skipped"), 1)

    def test_an_environment_deleted_since_it_was_marked_is_cleared(self):
        self.app.state["gone"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("gone")
        del self.app.state["gone"]

        self.assertEqual(self.app.flush_dirty(), [])
        self.assertEqual(self.dirty_count("gone"), 0)

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

    def test_updating_an_embeddings_window(self):
        self.handler.state["main"] = {
            "jsons": {"win_0": embeddings_pane()},
            "reload": {},
        }

        UpdateHandler.wrap_func(
            self.handler,
            {
                "win": "win_0",
                "eid": "main",
                "data": {"update_type": "EntitySelected", "selected": [2]},
            },
        )

        pane = self.handler.state["main"]["jsons"]["win_0"]
        self.assertEqual(pane["content"]["selected"], [2])
        self.assertEqual(self.handler.dirtied, ["main"])


class TestSocketCommandsMarkTheirWrites(unittest.TestCase):
    """The socket commands that mutate state mark it too.

    These reach state without going through the ``/events`` route, so a mark
    missing here is a change the timer and threshold never learn about and only
    the shutdown save can rescue.
    """

    def setUp(self):
        # A real env_path, because the undo stack close/undo trade through is
        # persisted by the store and drops on the floor without one.
        self._tmp = tempfile.TemporaryDirectory()
        self.handler = FakeHandler(env_path=self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def send(self, **msg):
        AnySocketHandlerOrWrapper.on_message(self.handler, json.dumps(msg))

    def register(self, win="win_0"):
        register_window(self.handler, window(window_args(win=win)), "main")
        self.handler.dirtied.clear()

    def test_closing_a_window(self):
        self.register()

        self.send(cmd="close", eid="main", data="win_0")

        self.assertEqual(self.handler.dirtied, ["main"])

    def test_undoing_a_close(self):
        self.register()
        self.send(cmd="close", eid="main", data="win_0")
        self.handler.dirtied.clear()

        self.send(cmd="undo", eid="main")

        self.assertIn("win_0", self.handler.state["main"]["jsons"])
        self.assertEqual(self.handler.dirtied, ["main"])

    def test_undo_with_nothing_to_restore_changes_nothing(self):
        self.register()

        self.send(cmd="undo", eid="main")

        self.assertEqual(self.handler.dirtied, [])

    def test_moving_a_window(self):
        self.register()

        self.send(
            cmd="layout_item_update", eid="main", win="win_0", data={"x": 1, "y": 2}
        )

        self.assertEqual(
            self.handler.state["main"]["reload"]["win_0"], {"x": 1, "y": 2}
        )
        self.assertEqual(self.handler.dirtied, ["main"])

    def test_editing_a_plot_layout(self):
        self.register()

        self.send(
            cmd="update_plot_layout", eid="main", win="win_0", data={"title": "renamed"}
        )

        pane = self.handler.state["main"]["jsons"]["win_0"]
        self.assertEqual(pane["content"]["layout"]["title"], "renamed")
        self.assertEqual(self.handler.dirtied, ["main"])

    def test_commenting_on_a_window(self):
        self.register()

        self.send(cmd="update_comment", eid="main", win="win_0", data="a note")

        pane = self.handler.state["main"]["jsons"]["win_0"]
        self.assertEqual(pane["comment"], "a note")
        self.assertEqual(self.handler.dirtied, ["main"])

    def test_editing_a_table_cell(self):
        self.handler.state["main"] = {"jsons": {"win_0": table_pane()}, "reload": {}}

        self.send(
            cmd="table_edit",
            eid="main",
            win="win_0",
            op="edit_cell",
            data={"row": 0, "col": 1, "value": "changed"},
        )

        pane = self.handler.state["main"]["jsons"]["win_0"]
        self.assertEqual(pane["content"]["rows"][0][1], "changed")
        self.assertEqual(self.handler.dirtied, ["main"])

    def test_popping_an_embeddings_pane(self):
        pane = embeddings_pane()
        pane["old_content"] = [[{"previous": True}]]
        self.handler.state["main"] = {"jsons": {"win_0": pane}, "reload": {}}

        self.send(cmd="pop_embeddings_pane", data={"eid": "main", "target": "win_0"})

        restored = self.handler.state["main"]["jsons"]["win_0"]
        self.assertEqual(restored["content"]["data"], [{"previous": True}])
        self.assertEqual(self.handler.dirtied, ["main"])

    def test_a_readonly_server_neither_changes_nor_marks(self):
        self.register()
        self.handler.readonly = True

        self.send(cmd="close", eid="main", data="win_0")

        self.assertIn("win_0", self.handler.state["main"]["jsons"])
        self.assertEqual(self.handler.dirtied, [])


if __name__ == "__main__":
    unittest.main()
