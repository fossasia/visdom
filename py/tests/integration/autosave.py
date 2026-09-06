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
threshold), the bookkeeping that keeps them from writing more than needed, and
that a save already queued cannot put a deleted environment back.

The write itself happens on the application's storage worker, so ``flush_envs``
answers with a future rather than the list of ids it wrote. These run it inline
instead (see ``_run_storage_inline``) and read the result off that future, which
keeps the assertions from racing a thread pool.
"""

import asyncio
import json
import tempfile
import types
import unittest
from concurrent.futures import Future
from unittest import mock

import pytest
import tornado.ioloop

from visdom.server.app import Application
from visdom.server.handlers.socket_handlers import AnySocketHandlerOrWrapper
from visdom.server.handlers.web_handlers import (
    CloseHandler,
    DeleteEnvHandler,
    UpdateHandler,
)
from visdom.utils.server_utils import (
    LazyEnvData,
    purge_env,
    register_window,
    window,
)

from testutils.fakes import FakeHandler
from testutils.payloads import embeddings_pane, table_pane, window_args

pytestmark = pytest.mark.integration


class AutosaveTestCase(unittest.TestCase):
    """Shared temporary-directory Application with an inline storage worker."""

    save_interval = 30
    save_threshold = 50

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.scheduled = self._run_storage_inline()
        self.app = Application(
            port=8097,
            env_path=self._tmp.name,
            save_interval=self.save_interval,
            save_threshold=self.save_threshold,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _run_storage_inline(self):
        """Run what the app submits to its storage worker inline instead.

        There is no IO loop running under a plain ``TestCase``, and the real
        worker would be writing on another thread while these assertions read
        the directory. A settled future is what the submission returns either
        way, so the done-callback that clears the dirty marks still runs.

        Returns the list of ``(func, args)`` that were submitted, so a test can
        assert what was handed over as well as what it did.
        """
        submitted = []

        def run_inline(_handler, func, *args):
            submitted.append((func, args))
            future = Future()
            try:
                future.set_result(func(*args))
            except Exception as exc:
                future.set_exception(exc)
            return future

        patcher = mock.patch(
            "visdom.server.server_state.run_on_storage_executor", side_effect=run_inline
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return submitted

    def flush_dirty(self):
        """``app.flush_dirty()``, resolved to the ids that reached disk."""
        return self._written(self.app.flush_dirty())

    def flush_envs(self, eids):
        """``app.flush_envs()``, resolved to the ids that reached disk."""
        return self._written(self.app.flush_envs(eids))

    @staticmethod
    def _written(future):
        """Nothing scheduled means nothing written."""
        return [] if future is None else future.result()

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

        self.assertEqual(self.flush_dirty(), ["written"])
        self.assertEqual(self.dirty_count("written"), 0)
        self.assertIn("written", self.app.storage.list_envs())

    def test_flush_is_a_no_op_when_nothing_changed(self):
        self.app.state["quiet"] = {"jsons": {}, "reload": {}}

        self.assertEqual(self.flush_dirty(), [])
        self.assertEqual(self.flush_envs(["quiet"]), [])

    def test_a_failed_write_is_retried_rather_than_dropped(self):
        self.app.state["fragile"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("fragile")

        with mock.patch.object(
            self.app.storage, "save_envs", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                self.flush_dirty()

        self.assertEqual(self.dirty_count("fragile"), 1)
        self.assertEqual(self.flush_dirty(), ["fragile"])

    def test_an_environment_the_backend_declined_stays_marked(self):
        self.app.state["skipped"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("skipped")

        with mock.patch.object(self.app.storage, "save_envs", return_value=[]):
            self.assertEqual(self.flush_dirty(), [])

        self.assertEqual(self.dirty_count("skipped"), 1)

    def test_an_environment_deleted_since_it_was_marked_is_cleared(self):
        self.app.state["gone"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("gone")
        del self.app.state["gone"]

        self.assertEqual(self.flush_dirty(), [])
        self.assertEqual(self.dirty_count("gone"), 0)

    def test_environment_is_rewritten_after_changing_again(self):
        self.app.state["repeat"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("repeat")
        self.flush_dirty()

        self.app.mark_dirty("repeat")
        self.assertEqual(self.flush_dirty(), ["repeat"])


class TestWritesGoToTheStorageWorker(AutosaveTestCase):
    """Autosaving serializes off the loop, and only ever from a copy."""

    def test_the_write_is_submitted_rather_than_run_here(self):
        self.app.state["busy"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("busy")

        self.flush_dirty()

        func, args = self.scheduled[0]
        self.assertEqual(func, self.app.storage.save_envs)
        self.assertEqual(args[1], ["busy"])

    def test_the_worker_is_handed_a_snapshot_not_the_live_state(self):
        """Otherwise the worker walks dictionaries the handlers still mutate."""
        self.app.state["busy"] = {"jsons": {"win_0": {"i": 0}}, "reload": {}}
        self.app.mark_dirty("busy")

        self.flush_dirty()

        handed = self.scheduled[0][1][0]
        self.assertIsNot(handed, self.app.state)
        self.assertIsNot(handed["busy"]["jsons"], self.app.state["busy"]["jsons"])
        self.assertEqual(handed["busy"]["jsons"], {"win_0": {"i": 0}})

    def test_an_environment_already_being_written_waits_for_the_next_pass(self):
        self.app.state["busy"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("busy")
        self.app.saving_envs.add("busy")

        self.assertIsNone(self.app.flush_envs(["busy"]))
        self.assertEqual(self.scheduled, [])
        self.assertEqual(self.dirty_count("busy"), 1)

    def test_a_change_made_during_the_write_stays_marked(self):
        """The snapshot predates the change, so the write did not cover it."""
        self.app.state["busy"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("busy")
        save_envs = self.app.storage.save_envs

        def save_then_change(state, eids):
            written = save_envs(state, eids)
            self.app.mark_dirty("busy")
            return written

        with mock.patch.object(self.app.storage, "save_envs", save_then_change):
            self.assertEqual(self.flush_dirty(), ["busy"])

        self.assertEqual(self.dirty_count("busy"), 1)

    def test_a_lazy_environment_never_read_is_not_written_back(self):
        """Its file is already current, so there is nothing to save."""
        self.app.state["cold"] = LazyEnvData(self.app.storage, "cold")
        self.app.mark_dirty("cold")

        self.assertEqual(self.flush_dirty(), [])
        self.assertEqual(self.scheduled, [])
        self.assertEqual(self.dirty_count("cold"), 0)


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

    def test_stopping_is_safe_before_it_ever_started(self):
        self.app.stop_autosave()

        self.assertIsNone(self.app.autosave)


class TestShutdown(AutosaveTestCase):
    """Shutting storage down ends the timer and writes what is still pending."""

    def test_the_timer_stops_before_the_final_save(self):
        """A tick during the drain would queue a write nothing waits for."""
        started = self.app.start_autosave()

        self.app.shutdown_storage()

        self.assertFalse(started.is_running())
        self.assertIsNone(self.app.autosave)

    def test_whatever_is_still_marked_reaches_disk(self):
        self.app.state["unsaved"] = {"jsons": {}, "reload": {}}
        self.app.mark_dirty("unsaved")

        self.app.shutdown_storage()

        self.assertIn("unsaved", self.app.storage.list_envs())
        self.assertEqual(self.dirty_count("unsaved"), 0)


class TestDeleteOutlastsAQueuedSave(unittest.TestCase):
    """Deleting an environment beats a save that is already on its way to disk.

    Autosaving serializes from a snapshot taken before the write, so a delete
    that removed the file itself was undone by the write landing afterwards:
    the environment was gone from the UI and back on the next restart. Both
    delete paths now hand the removal to the same single-threaded worker, which
    is what puts it after the save rather than in front of it.

    The worker here is a queue that runs nothing until ``run_queued`` says so,
    which is the interleaving those two paths have to survive.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.queued = self._queue_storage_work()
        self.app = Application(port=8097, env_path=self._tmp.name)
        self.handler = FakeHandler(
            state=self.app.state,
            storage=self.app.storage,
            env_path=self.app.env_path,
        )
        self.app.state["expt"] = {"jsons": {"win_0": {"i": 0}}, "reload": {}}
        self.app.storage.save_env("expt", self.app.state["expt"])

    def _queue_storage_work(self):
        """Hold everything submitted to the storage worker until asked to run.

        One queue stands in for the whole worker, so a save submitted by the
        application and a delete submitted by a handler land in it in the order
        the server chose -- which is the thing under test.
        """
        queued = []

        def run_in_executor(_executor, func, *args):
            future = self._pending_future()
            queued.append((func, args, future))
            return future

        loop = types.SimpleNamespace(run_in_executor=run_in_executor)
        patcher = mock.patch.object(
            tornado.ioloop.IOLoop, "current", staticmethod(lambda: loop)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return queued

    @staticmethod
    def _pending_future():
        """An unresolved future the caller can wait on however it waits.

        The delete path is awaited by the socket command, so inside a running
        loop the future has to be that loop's own; the handlers called directly
        from a test method read their result off a plain ``Future`` instead.
        """
        try:
            return asyncio.get_running_loop().create_future()
        except RuntimeError:
            return Future()

    def run_queued(self):
        """Run the queued work in submission order, as one worker would."""
        while self.queued:
            func, args, future = self.queued.pop(0)
            try:
                future.set_result(func(*args))
            except Exception as exc:  # pragma: no cover - fails the test below
                future.set_exception(exc)

    def queue_autosave(self):
        """Mark the env changed and hand its write to the worker, unrun."""
        self.app.mark_dirty("expt")
        self.app.flush_dirty()

    def test_a_web_delete_survives_the_save_queued_before_it(self):
        self.queue_autosave()

        DeleteEnvHandler.wrap_func(self.handler, {"eid": "expt"})
        self.run_queued()

        self.assertFalse(self.app.storage.env_exists("expt"))
        self.assertNotIn("expt", self.app.state)

    def test_a_socket_delete_survives_the_save_queued_before_it(self):
        """The command waits for the removal, so the worker runs mid-dispatch.

        Unlike the web handler, the socket command awaits what it queued; the
        queue has to be drained while it is waiting rather than after it
        returns, or nothing would ever resolve the future it is parked on.
        """
        self.queue_autosave()

        async def dispatch():
            command = asyncio.ensure_future(
                AnySocketHandlerOrWrapper.on_message(
                    self.handler, json.dumps({"cmd": "delete_env", "eid": "expt"})
                )
            )
            await asyncio.sleep(0)
            self.run_queued()
            await command

        asyncio.run(dispatch())

        self.assertFalse(self.app.storage.env_exists("expt"))
        self.assertNotIn("expt", self.app.state)

    def test_the_removal_is_queued_behind_the_save_rather_than_run_at_once(self):
        """Running it on the loop is what let the save overtake it."""
        self.queue_autosave()

        DeleteEnvHandler.wrap_func(self.handler, {"eid": "expt"})

        submitted = [func for func, _args, _future in self.queued]
        self.assertEqual(submitted, [self.app.storage.save_envs, purge_env])
        self.assertTrue(self.app.storage.env_exists("expt"))

    def test_the_environment_is_still_removed_with_nothing_queued(self):
        DeleteEnvHandler.wrap_func(self.handler, {"eid": "expt"})
        self.run_queued()

        self.assertFalse(self.app.storage.env_exists("expt"))

    def test_a_save_marked_after_the_delete_never_reaches_disk(self):
        """The env left ``state`` on the loop, so a later flush has nothing."""
        DeleteEnvHandler.wrap_func(self.handler, {"eid": "expt"})
        self.queue_autosave()

        self.run_queued()

        self.assertFalse(self.app.storage.env_exists("expt"))
        self.assertEqual(self.app.dirty_envs.get("expt", 0), 0)


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
        # ``on_message`` is a coroutine now that the commands hand their disk
        # work to the storage worker, so a loop has to drive it to completion.
        asyncio.run(AnySocketHandlerOrWrapper.on_message(self.handler, json.dumps(msg)))

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
