#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Environment lifecycle over real HTTP: create, fork, save, delete, reload.

An environment is never created explicitly -- it appears the moment a pane is
addressed to it. From there ``/fork_env`` deep-copies it, ``/save`` writes it
through the storage backend, ``/delete_env`` removes both the state and the
file, and a fresh ``Application`` over the same directory picks it back up.
That the writes go through the backend rather than around it is asserted
separately in ``test_storage_wiring``.
"""

import json
import os

import pytest

pytestmark = pytest.mark.integration


# -- Startup state ------------------------------------------------------------


def test_main_env_exists_and_is_empty_on_startup(visdom_server):
    assert "main" in visdom_server.get_envs()
    assert visdom_server.get_win_data() == {}


def test_env_state_returns_a_list(visdom_server):
    assert isinstance(visdom_server.get_envs(), list)


# -- Implicit creation --------------------------------------------------------


def test_addressing_an_unknown_env_creates_it(visdom_server):
    visdom_server.create_text_window(eid="new_env", content="hello")
    assert "new_env" in visdom_server.get_envs()


def test_env_state_lists_every_env_created(visdom_server):
    visdom_server.create_text_window(eid="x_env")
    visdom_server.create_text_window(eid="y_env")
    assert {"main", "x_env", "y_env"} <= set(visdom_server.get_envs())


# -- Fork ---------------------------------------------------------------------


def test_fork_copies_the_panes_across(visdom_server):
    visdom_server.create_text_window(eid="main", content="original", win="w1")
    resp = visdom_server.post_json("/fork_env", {"prev_eid": "main", "eid": "fork1"})
    assert resp.status_code == 200
    assert resp.text == "fork1"
    assert visdom_server.get_win_data("w1", eid="fork1")["content"] == "original"


def test_fork_is_independent_of_its_source(visdom_server):
    visdom_server.create_text_window(eid="main", content="original", win="w1")
    visdom_server.post_json("/fork_env", {"prev_eid": "main", "eid": "fork2"})

    visdom_server.update("w1", [{"content": "modified"}], eid="fork2")

    assert visdom_server.get_win_data("w1", eid="main")["content"] == "original"


def test_forking_an_unknown_env_is_rejected(visdom_server):
    resp = visdom_server.post_json("/fork_env", {"prev_eid": "no_exist", "eid": "new"})
    assert resp.status_code == 500


# -- Save ---------------------------------------------------------------------


def test_save_writes_a_file_named_for_the_env(visdom_server):
    visdom_server.create_text_window(eid="main", content="save me")
    visdom_server.save(["main"])
    assert os.path.exists(os.path.join(visdom_server.env_path, "main.json"))


def test_saved_file_carries_jsons_and_reload(visdom_server):
    visdom_server.create_text_window(eid="main", content="save me")
    visdom_server.save(["main"])
    with open(os.path.join(visdom_server.env_path, "main.json")) as handle:
        saved = json.load(handle)
    assert "jsons" in saved
    assert "reload" in saved


def test_save_handles_several_envs_at_once(visdom_server):
    visdom_server.create_text_window(eid="env_a", content="a")
    visdom_server.create_text_window(eid="env_b", content="b")
    visdom_server.save(["env_a", "env_b"])
    for eid in ("env_a", "env_b"):
        assert os.path.exists(os.path.join(visdom_server.env_path, eid + ".json"))


def test_save_reports_only_the_envs_that_existed(visdom_server):
    visdom_server.create_text_window(eid="main", content="x")
    saved = visdom_server.save(["main", "nonexistent"]).json()
    assert "main" in saved
    assert "nonexistent" not in saved


# -- Delete -------------------------------------------------------------------


def test_delete_removes_the_env_from_state(visdom_server):
    visdom_server.create_text_window(eid="del_me", content="bye")
    visdom_server.post_json("/delete_env", {"eid": "del_me"})
    assert "del_me" not in visdom_server.get_envs()


def test_delete_removes_the_saved_file_too(visdom_server):
    visdom_server.create_text_window(eid="del_file", content="bye")
    visdom_server.save(["del_file"])
    path = os.path.join(visdom_server.env_path, "del_file.json")
    assert os.path.exists(path)

    visdom_server.post_json("/delete_env", {"eid": "del_file"})

    assert not os.path.exists(path)


def test_main_env_cannot_be_deleted(visdom_server):
    visdom_server.post_json("/delete_env", {"eid": "main"})
    assert "main" in visdom_server.get_envs()


# -- Reload -------------------------------------------------------------------


def test_a_saved_env_is_reloaded_by_a_fresh_application(visdom_server, app_factory):
    visdom_server.create_text_window(eid="persist", content="I survive", win="w1")
    visdom_server.save(["persist"])

    restarted = app_factory()

    assert "persist" in restarted.state
    assert restarted.state["persist"]["jsons"]["w1"]["content"] == "I survive"
