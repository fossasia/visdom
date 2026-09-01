#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Window CRUD over real HTTP: create, exists, read, write, close.

Covers the routes a client touches for the whole life of a pane --
``/events``, ``/win_exists``, ``/win_data``, ``/update`` and ``/close`` --
against a real ``Application``. Pane construction itself is unit-tested in
``unit/window_builder.py``; here we assert what survives the round trip
through the server's state.

The same five routes are also the ones a plotting client hits in a loop, so
the second half of this file exercises them against an environment that is
still on disk. Each used to reach into ``handler.state[eid]`` and run a whole
``load_env`` inline, with every other connection waiting on that read; they are
coroutines now and prime the environment through the storage executor first.
The proof is which thread the read lands on, so ``ThreadRecordingStore``
remembers it -- a correct answer proves nothing on its own, because the
blocking version returned the same body, just later and at everyone else's
expense.
"""

import inspect
import json
import threading
import unittest
from unittest import mock

import pytest

from visdom.data_model.json_store import JSONStore
from visdom.server.handlers.web_handlers import (
    CloseHandler,
    DataHandler,
    ExistsHandler,
    PostHandler,
    UpdateHandler,
)
from visdom.utils.server_utils import LazyEnvData

from testutils.http import VisdomHTTPTestCase
from testutils.payloads import env_payload

pytestmark = pytest.mark.integration


class TestWindowCreate(VisdomHTTPTestCase):
    def test_create_returns_nonempty_id(self):
        self.assertTrue(len(self.create_text_window()) > 0)

    def test_auto_generated_id_is_prefixed(self):
        self.assertTrue(self.create_text_window().startswith("window_"))

    def test_supplied_id_is_used_verbatim(self):
        self.assertEqual(self.create_text_window(win="my_id"), "my_id")


class TestWindowExists(VisdomHTTPTestCase):
    def test_window_exists_after_creation(self):
        self.assertTrue(self.win_exists(self.create_text_window()))

    def test_window_does_not_exist_when_never_created(self):
        self.assertFalse(self.win_exists("no_such_win"))

    def test_window_does_not_exist_in_another_env(self):
        win = self.create_text_window(eid="env_a")
        self.assertFalse(self.win_exists(win, eid="main"))


class TestWindowRead(VisdomHTTPTestCase):
    def test_read_single_window(self):
        win = self.create_text_window(content="get me")
        self.assertEqual(self.get_win_data(win)["content"], "get me")

    def test_read_every_window_at_once(self):
        first = self.create_text_window(content="first")
        second = self.create_text_window(content="second")
        self.assertEqual(set(self.get_win_data()), {first, second})


class TestWindowWrite(VisdomHTTPTestCase):
    def test_window_data_can_be_replaced(self):
        win = self.create_text_window(content="original")
        replacement = {
            "type": "text",
            "content": "replaced",
            "id": win,
            "command": "window",
        }
        resp = self.post_json(
            "/win_data", {"eid": "main", "win": win, "data": json.dumps(replacement)}
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(self.get_win_data(win)["content"], "replaced")


class TestWindowClose(VisdomHTTPTestCase):
    def test_close_removes_only_the_named_window(self):
        keep = self.create_text_window(content="keep")
        drop = self.create_text_window(content="drop")
        self.assertEqual(self.close_window(drop).code, 200)
        self.assertTrue(self.win_exists(keep))
        self.assertFalse(self.win_exists(drop))

    def test_close_with_no_window_clears_the_env(self):
        self.create_text_window(content="a")
        self.create_text_window(content="b")
        self.close_window(None)
        self.assertEqual(self.get_win_data(), {})


class TestUpdateMissingWindow(VisdomHTTPTestCase):
    def test_update_missing_window_is_reported_not_created(self):
        resp = self.update("no_such_win", [{"type": "text", "content": "nope"}])
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body.decode(), "win does not exist")
        self.assertFalse(self.win_exists("no_such_win"))

    def test_update_missing_window_with_append_creates_it(self):
        resp = self.update(
            "auto_created", [{"type": "text", "content": "made by append"}], append=True
        )
        self.assertEqual(resp.code, 200)
        self.assertTrue(self.win_exists("auto_created"))


class TestWindowOrdering(VisdomHTTPTestCase):
    def test_windows_are_indexed_in_creation_order(self):
        wins = [self.create_text_window(content=str(n)) for n in range(3)]
        panes = self.panes()
        self.assertEqual([panes[win]["i"] for win in wins], [0, 1, 2])

    def test_recreating_a_window_keeps_its_index(self):
        """Posting the same win id twice replaces the pane instead of adding one."""
        created_id = self.create_text_window(win="stable", content="v1")
        recreated_id = self.create_text_window(win="stable", content="v2")

        # both calls hand back the id they asked for, so only one pane exists
        self.assertEqual(created_id, recreated_id)
        self.assertEqual(len(self.panes()), 1)

        pane = self.get_win_data("stable")
        self.assertEqual(pane["i"], 0)
        self.assertEqual(pane["content"], "v2")

    def test_an_index_is_never_reused_after_a_close(self):
        wins = [self.create_text_window(content=str(n)) for n in range(3)]
        self.close_window(wins[1])

        added = self.create_text_window(content="after the close")

        panes = self.panes()
        self.assertEqual(sorted(pane["i"] for pane in panes.values()), [0, 2, 3])
        self.assertEqual(panes[added]["i"], 3)

    def test_indices_stay_unique_while_windows_churn(self):
        live = [self.create_text_window(content=str(n)) for n in range(4)]

        for round_ in range(4):
            self.close_window(live.pop(0))
            live.append(self.create_text_window(content="round {}".format(round_)))

            indices = [pane["i"] for pane in self.panes().values()]
            self.assertEqual(len(set(indices)), len(indices), indices)


COLD = "cold"
COLD_WIN = "win_cold"


def cold_env():
    """One text pane, as an environment that was written by an earlier run."""
    return env_payload(
        jsons={COLD_WIN: {"id": COLD_WIN, "type": "text", "content": "seeded", "i": 0}}
    )


class ThreadRecordingStore(JSONStore):
    """JSONStore that remembers which thread each read ran on."""

    def __init__(self, env_path):
        super().__init__(env_path)
        self.load_threads = []

    def load_env(self, eid):
        self.load_threads.append(threading.current_thread().name)
        return super().load_env(eid)


class ColdEnvTestCase(VisdomHTTPTestCase):
    """App booted with ``cold`` already on disk, so state holds it lazily."""

    def get_app(self):
        JSONStore(self.env_path).save_env(COLD, cold_env())
        with mock.patch("visdom.server.app.JSONStore", ThreadRecordingStore):
            app = super().get_app()
        self.recorder = app.storage
        return app

    def assertLoadedOffLoop(self):
        """The cold read happened, and not on the thread serving requests."""
        self.assertEqual(len(self.recorder.load_threads), 1)
        self.assertNotEqual(
            self.recorder.load_threads[0], threading.current_thread().name
        )
        self.assertTrue(self.recorder.load_threads[0].startswith("visdom-storage"))


class TestColdEnvStartsLazy(ColdEnvTestCase):
    def test_the_seeded_env_is_not_read_at_boot(self):
        self.assertIsInstance(self._app.state[COLD], LazyEnvData)
        self.assertFalse(self._app.state[COLD].is_loaded)

    def test_a_request_for_another_env_leaves_it_cold(self):
        self.create_text_window(eid="main")

        self.assertFalse(self._app.state[COLD].is_loaded)
        self.assertEqual(self.recorder.load_threads, [])


class TestEventsPrimesOffLoop(ColdEnvTestCase):
    def test_the_read_runs_on_the_storage_worker(self):
        self.create_text_window(eid=COLD, win="fresh")

        self.assertLoadedOffLoop()

    def test_the_new_pane_joins_the_ones_from_disk(self):
        self.create_text_window(eid=COLD, win="fresh")

        self.assertEqual(set(self.panes(COLD)), {COLD_WIN, "fresh"})

    def test_the_new_pane_is_numbered_after_the_seeded_one(self):
        self.create_text_window(eid=COLD, win="fresh")

        self.assertEqual(self.panes(COLD)["fresh"]["i"], 1)


class TestWinExistsPrimesOffLoop(ColdEnvTestCase):
    def test_the_read_runs_on_the_storage_worker(self):
        self.win_exists(COLD_WIN, eid=COLD)

        self.assertLoadedOffLoop()

    def test_a_pane_only_on_disk_is_reported_present(self):
        self.assertTrue(self.win_exists(COLD_WIN, eid=COLD))

    def test_a_pane_in_no_env_is_still_reported_absent(self):
        self.assertFalse(self.win_exists("ghost", eid=COLD))


class TestUpdatePrimesOffLoop(ColdEnvTestCase):
    def test_the_read_runs_on_the_storage_worker(self):
        self.update(COLD_WIN, [{"content": " more"}], eid=COLD)

        self.assertLoadedOffLoop()

    def test_the_pane_from_disk_is_the_one_appended_to(self):
        resp = self.update(COLD_WIN, [{"content": " more"}], eid=COLD, append=True)

        self.assertEqual(resp.body.decode(), COLD_WIN)
        self.assertIn("seeded", self.panes(COLD)[COLD_WIN]["content"])

    def test_an_append_to_a_missing_pane_still_creates_it(self):
        self.update("fresh", [{"type": "text", "content": "hi"}], eid=COLD, append=True)

        self.assertIn("fresh", self.panes(COLD))


class TestClosePrimesOffLoop(ColdEnvTestCase):
    def test_the_read_runs_on_the_storage_worker(self):
        self.close_window(COLD_WIN, eid=COLD)

        self.assertLoadedOffLoop()

    def test_a_pane_only_on_disk_can_be_closed(self):
        self.close_window(COLD_WIN, eid=COLD)

        self.assertEqual(self.panes(COLD), {})

    def test_closing_marks_the_env_for_saving(self):
        self.close_window(COLD_WIN, eid=COLD)

        self.assertEqual(self._app.dirty_envs[COLD], 1)


class TestWinDataPrimesOffLoop(ColdEnvTestCase):
    def test_the_read_runs_on_the_storage_worker(self):
        self.get_win_data(COLD_WIN, eid=COLD)

        self.assertLoadedOffLoop()

    def test_the_pane_from_disk_is_returned(self):
        self.assertEqual(self.get_win_data(COLD_WIN, eid=COLD)["content"], "seeded")

    def test_a_write_through_win_data_lands_on_the_primed_env(self):
        self.post_json(
            "/win_data", {"eid": COLD, "win": "fresh", "data": '{"id": "fresh"}'}
        )

        self.assertEqual(set(self.panes(COLD)), {COLD_WIN, "fresh"})


class TestWarmEnvIsNotReRead(ColdEnvTestCase):
    def test_a_second_request_reuses_the_primed_env(self):
        self.win_exists(COLD_WIN, eid=COLD)
        self.win_exists(COLD_WIN, eid=COLD)

        self.assertEqual(len(self.recorder.load_threads), 1)

    def test_two_different_routes_share_one_read(self):
        self.win_exists(COLD_WIN, eid=COLD)
        self.get_win_data(COLD_WIN, eid=COLD)
        self.create_text_window(eid=COLD, win="fresh")

        self.assertEqual(len(self.recorder.load_threads), 1)


class TestHotPostsAreCoroutines(VisdomHTTPTestCase):
    """The decorators hand their return value back, so the shells stay awaitable.

    ``check_auth`` discarding the wrapped result is what made this conversion
    impossible before -- an ``async def post`` became a coroutine nobody
    awaited, and the client got a silent empty 200. Guard the shape.
    """

    def test_every_hot_post_is_a_coroutine_function(self):
        for handler in (
            PostHandler,
            ExistsHandler,
            UpdateHandler,
            CloseHandler,
            DataHandler,
        ):
            with self.subTest(handler=handler.__name__):
                self.assertTrue(
                    inspect.iscoroutinefunction(inspect.unwrap(handler.post))
                )


class TestErrorsSurviveTheAsyncShells(VisdomHTTPTestCase):
    """An exception raised inside a coroutine still reaches the client."""

    def test_update_without_a_win_is_a_400(self):
        self.assertEqual(self.post_json("/update", {"eid": "main"}).code, 400)

    def test_win_exists_without_a_win_is_a_400(self):
        self.assertEqual(self.post_json("/win_exists", {"eid": "main"}).code, 400)

    def test_the_lua_torch_payload_still_fails_loudly(self):
        self.assertEqual(self.post_json("/events", {"func": "anything"}).code, 500)


if __name__ == "__main__":
    unittest.main()
