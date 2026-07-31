#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Window CRUD over real HTTP: create, exists, read, write, close.

Covers the routes a client touches for the whole life of a pane --
``/events``, ``/win_exists``, ``/win_data``, ``/update`` and ``/close`` --
against a listening ``Application``. Pane construction itself is unit-tested
in ``unit/test_window_builder.py``; here we assert what survives the round
trip through the server's state.
"""

import json

import pytest

pytestmark = pytest.mark.integration


# -- Create -------------------------------------------------------------------


def test_create_returns_nonempty_id(visdom_server):
    assert len(visdom_server.create_text_window()) > 0


def test_auto_generated_id_is_prefixed(visdom_server):
    assert visdom_server.create_text_window().startswith("window_")


def test_supplied_id_is_used_verbatim(visdom_server):
    assert visdom_server.create_text_window(win="my_id") == "my_id"


# -- Exists -------------------------------------------------------------------


def test_window_exists_after_creation(visdom_server):
    assert visdom_server.win_exists(visdom_server.create_text_window())


def test_window_does_not_exist_when_never_created(visdom_server):
    assert not visdom_server.win_exists("no_such_win")


def test_window_does_not_exist_in_another_env(visdom_server):
    win = visdom_server.create_text_window(eid="env_a")
    assert not visdom_server.win_exists(win, eid="main")


# -- Read ---------------------------------------------------------------------


def test_read_single_window(visdom_server):
    win = visdom_server.create_text_window(content="get me")
    assert visdom_server.get_win_data(win)["content"] == "get me"


def test_read_every_window_at_once(visdom_server):
    first = visdom_server.create_text_window(content="first")
    second = visdom_server.create_text_window(content="second")
    every = visdom_server.get_win_data()
    assert set(every) == {first, second}


# -- Write --------------------------------------------------------------------


def test_window_data_can_be_replaced(visdom_server):
    win = visdom_server.create_text_window(content="original")
    replacement = {
        "type": "text",
        "content": "replaced",
        "id": win,
        "command": "window",
    }
    resp = visdom_server.post_json(
        "/win_data", {"eid": "main", "win": win, "data": json.dumps(replacement)}
    )
    assert resp.status_code == 200
    assert visdom_server.get_win_data(win)["content"] == "replaced"


# -- Close --------------------------------------------------------------------


def test_close_removes_only_the_named_window(visdom_server):
    keep = visdom_server.create_text_window(content="keep")
    drop = visdom_server.create_text_window(content="drop")
    assert visdom_server.close_window(drop).status_code == 200
    assert visdom_server.win_exists(keep)
    assert not visdom_server.win_exists(drop)


def test_close_with_no_window_clears_the_env(visdom_server):
    visdom_server.create_text_window(content="a")
    visdom_server.create_text_window(content="b")
    visdom_server.close_window(None)
    assert visdom_server.get_win_data() == {}


# -- Update against a missing window ------------------------------------------


def test_update_missing_window_is_reported_not_created(visdom_server):
    resp = visdom_server.update("no_such_win", [{"type": "text", "content": "nope"}])
    assert resp.status_code == 200
    assert resp.text == "win does not exist"
    assert not visdom_server.win_exists("no_such_win")


def test_update_missing_window_with_append_creates_it(visdom_server):
    resp = visdom_server.update(
        "auto_created", [{"type": "text", "content": "made by append"}], append=True
    )
    assert resp.status_code == 200
    assert visdom_server.win_exists("auto_created")


# -- Ordering index -----------------------------------------------------------


def test_windows_are_indexed_in_creation_order(visdom_server):
    wins = [visdom_server.create_text_window(content=str(n)) for n in range(3)]
    panes = visdom_server.panes()
    assert [panes[win]["i"] for win in wins] == [0, 1, 2]


def test_recreating_a_window_keeps_its_index(visdom_server):
    first = visdom_server.create_text_window(win="stable", content="v1")
    second = visdom_server.create_text_window(win="stable", content="v2")
    assert first == second
    pane = visdom_server.get_win_data("stable")
    assert pane["i"] == 0
    assert pane["content"] == "v2"
