#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Inputs the server has to survive rather than serve.

Environment ids become file names, so ``escape_eid`` rewrites the characters
that would escape the storage directory, and names too long for a file system
fall back to a hash. Everything else here is the awkward end of the range:
missing envs and windows, twenty creations in a row, empty and enormous and
markup-bearing content, and the pages that render straight from state.
"""

import os

import pytest

pytestmark = pytest.mark.integration


# -- Environment id escaping --------------------------------------------------


@pytest.mark.parametrize(
    "eid,stored",
    [
        ("a/b", "a_b"),
        ("a\\b", "a_b"),
        ("a\nb", "a-b"),
        ("env_éàü", "env_éàü"),
    ],
    ids=["forward-slash", "backslash", "newline", "unicode-kept"],
)
def test_env_ids_are_escaped_into_safe_names(visdom_server, eid, stored):
    visdom_server.create_text_window(eid=eid, content="escaped")
    envs = visdom_server.get_envs()
    assert stored in envs
    if stored != eid:
        assert eid not in envs


def test_an_over_long_env_name_falls_back_to_a_hash_file(visdom_server):
    long_name = "x" * 300
    visdom_server.create_text_window(eid=long_name, content="long name")
    visdom_server.save([long_name])
    files = os.listdir(visdom_server.env_path)
    assert [f for f in files if f.startswith("hash_") and f.endswith(".json")], files


# -- Error routes -------------------------------------------------------------


@pytest.mark.parametrize(
    "path,status",
    [("/error/test_error_msg", 400), ("/error/500", 500), ("/error/404", 404)],
    ids=["not-a-status", "server-error", "not-found"],
)
def test_error_route_echoes_the_requested_status(visdom_server, path, status):
    assert visdom_server.get(path).status_code == status


def test_the_server_survives_a_requested_error(visdom_server):
    visdom_server.get("/error/500")
    assert visdom_server.get("/health").status_code == 200


def test_reading_an_unknown_window_is_a_bad_request(visdom_server):
    resp = visdom_server.post_json("/win_data", {"eid": "main", "win": "nonexistent"})
    assert resp.status_code == 400
    assert "window doesn't exist" in resp.reason


def test_naming_a_trace_while_sending_several_is_a_bad_request(visdom_server):
    trace = {"type": "scatter", "x": [1, 2], "y": [3, 4], "name": "t1"}
    win = visdom_server.create_window([trace])

    resp = visdom_server.update(win, [trace, dict(trace, name="t2")], name="t1")

    assert resp.status_code == 400
    assert "exactly one data entry" in resp.reason


def test_a_named_trace_update_with_one_entry_is_accepted(visdom_server):
    trace = {"type": "scatter", "x": [1, 2], "y": [3, 4], "name": "t1"}
    win = visdom_server.create_window([trace])

    replacement = dict(trace, y=[9, 9])
    assert visdom_server.update(win, [replacement], name="t1").status_code == 200
    assert visdom_server.get_win_data(win)["content"]["data"][0]["y"] == [9, 9]


def test_updating_a_window_in_an_unknown_env_does_not_crash(visdom_server):
    resp = visdom_server.update(
        "w1", [{"type": "text", "content": "fail"}], eid="nonexistent_env"
    )
    assert resp.status_code == 200
    assert resp.text == "win does not exist"


# -- Volume and isolation -----------------------------------------------------


def test_twenty_windows_in_a_row_all_land(visdom_server):
    wins = [visdom_server.create_text_window(content=f"win_{n}") for n in range(20)]
    assert len(set(wins)) == 20

    panes = visdom_server.panes()
    assert len(panes) == 20
    assert sorted(pane["i"] for pane in panes.values()) == list(range(20))


def test_windows_do_not_leak_between_envs(visdom_server):
    visdom_server.create_text_window(eid="env_a", content="a_only", win="wa")
    visdom_server.create_text_window(eid="env_b", content="b_only", win="wb")

    assert visdom_server.win_exists("wa", eid="env_a")
    assert not visdom_server.win_exists("wb", eid="env_a")
    assert visdom_server.win_exists("wb", eid="env_b")
    assert not visdom_server.win_exists("wa", eid="env_b")


# -- Awkward content ----------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    ["", "x" * 100000, 'He said "hello" & <script>alert(1)</script>'],
    ids=["empty", "100k-chars", "quotes-and-markup"],
)
def test_text_content_round_trips_unaltered(visdom_server, content):
    win = visdom_server.create_text_window(content=content)
    assert visdom_server.get_win_data(win)["content"] == content


# -- Deleting what is not there -----------------------------------------------


@pytest.mark.parametrize("eid", ["never_existed", None], ids=["unknown", "none"])
def test_deleting_a_missing_env_is_a_no_op(visdom_server, eid):
    assert visdom_server.post_json("/delete_env", {"eid": eid}).status_code == 200


# -- Pages rendered straight from state ---------------------------------------


@pytest.mark.parametrize("path", ["/env/main", "/compare/main+main"])
def test_page_renders(visdom_server, path):
    assert visdom_server.get(path).status_code == 200
