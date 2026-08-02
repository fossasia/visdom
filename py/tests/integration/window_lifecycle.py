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
"""

import json
import unittest

import pytest

from testutils.http import VisdomHTTPTestCase

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


if __name__ == "__main__":
    unittest.main()
