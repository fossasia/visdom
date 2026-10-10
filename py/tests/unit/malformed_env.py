#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Environments that hold something a reader cannot use.

Every reader of an environment used to take its shape on trust: ``load_env``
called ``.values()`` on ``jsons`` and ``.get()`` on each pane, ``compare_envs``
called ``.keys()``. An env carrying ``{"jsons": [], "reload": {}}`` was stored,
persisted and then answered HTTP 500 on every attempt to open or compare it.

The rule now: anything the store cannot read is left out of the env it serves
and out of what it writes back, the client being served is told what is
missing, and the file is copied to ``<name>.json.unreadable`` before it is
first written over, so nothing that was on disk is lost.
"""

import json
import os

import pytest

from visdom.data_model.json_store import UNREADABLE_SUFFIX
from visdom.utils.server_utils import (
    LazyEnvData,
    compare_envs,
    env_is_readable,
    load_env,
    readable_panes,
    reload_is_readable,
)

from testutils.payloads import env_payload

pytestmark = pytest.mark.unit


UNREADABLE = [
    ("jsons_is_a_list", {"jsons": [], "reload": {}}),
    ("jsons_is_null", {"jsons": None, "reload": {}}),
    ("jsons_is_a_string", {"jsons": "panes", "reload": {}}),
    ("jsons_is_missing", {"reload": {}}),
    ("reload_is_missing", {"jsons": {}}),
    ("not_an_object", []),
]

BAD_PANE = [
    ("a_pane_is_a_string", {"jsons": {"w1": "not a pane"}, "reload": {}}),
    ("a_pane_is_a_list", {"jsons": {"w1": []}, "reload": {}}),
]

BAD_RELOAD = [
    ("reload_is_a_list", {"jsons": {}, "reload": []}),
    ("reload_is_null", {"jsons": {}, "reload": None}),
    ("reload_is_a_string", {"jsons": {}, "reload": "wide"}),
]

PARTLY = BAD_PANE + BAD_RELOAD

UNREADABLE_IDS = [case[0] for case in UNREADABLE]
BAD_RELOAD_IDS = [case[0] for case in BAD_RELOAD]
PARTLY_IDS = [case[0] for case in PARTLY]

GOOD_PANE = {
    "command": "window",
    "id": "good",
    "type": "text",
    "i": 0,
    "content": "hello",
}


def _with_one_bad_pane():
    return {"jsons": {"good": dict(GOOD_PANE), "bad": "not a pane"}, "reload": {}}


def _with_bad_reload():
    return {"jsons": {"good": dict(GOOD_PANE)}, "reload": "wide"}


def _write(env_path, name, payload):
    with open(os.path.join(env_path, name + ".json"), "w") as fn:
        fn.write(json.dumps(payload))


def _read(env_path, name):
    with open(os.path.join(env_path, name + ".json")) as fn:
        return json.load(fn)


def _windows(socket):
    return [m for m in socket.sent if m.get("command") == "window"]


def _notifications(socket):
    return [m for m in socket.sent if m.get("command") == "notification"]


@pytest.mark.parametrize("name, payload", UNREADABLE, ids=UNREADABLE_IDS)
def test_an_env_without_panes_to_read_is_not_readable(name, payload):
    assert env_is_readable(payload) is False


@pytest.mark.parametrize("name, payload", PARTLY, ids=PARTLY_IDS)
def test_an_env_is_readable_even_when_part_of_it_is_not(name, payload):
    assert env_is_readable(payload) is True


def test_an_empty_env_is_readable():
    assert env_is_readable({"jsons": {}, "reload": {}}) is True


def test_a_lazy_env_is_readable_once_it_is_primed(store):
    lazy = LazyEnvData(store, "main")
    lazy.prime(env_payload())
    assert env_is_readable(lazy) is True


@pytest.mark.parametrize("name, payload", BAD_RELOAD, ids=BAD_RELOAD_IDS)
def test_an_unusable_reload_is_not_readable(name, payload):
    assert reload_is_readable(payload) is False


def test_a_mapping_reload_is_readable():
    assert reload_is_readable({"jsons": {}, "reload": {"w1": {}}}) is True


def test_the_panes_that_can_be_read_are_separated_from_the_rest():
    panes, unreadable = readable_panes(_with_one_bad_pane())
    assert panes == {"good": GOOD_PANE}
    assert unreadable == ["bad"]


def test_reading_the_panes_leaves_the_env_alone():
    env = _with_one_bad_pane()
    readable_panes(env)
    assert env["jsons"]["bad"] == "not a pane"


@pytest.mark.parametrize("name, payload", UNREADABLE, ids=UNREADABLE_IDS)
def test_priming_a_lazy_env_that_cannot_be_read_is_a_value_error(name, payload, store):
    lazy = LazyEnvData(store, "broken")
    with pytest.raises(ValueError):
        lazy.prime(payload)
    assert lazy.is_loaded is False


def test_priming_a_lazy_env_with_nothing_is_still_a_value_error(store):
    lazy = LazyEnvData(store, "broken")
    with pytest.raises(ValueError):
        lazy.prime({})
    assert lazy.is_loaded is False


@pytest.mark.parametrize("name, payload", UNREADABLE, ids=UNREADABLE_IDS)
def test_a_file_that_cannot_be_read_is_not_loaded(name, payload, store, env_path):
    _write(env_path, "broken", payload)
    assert store.load_env("broken") == {}


def test_a_bad_pane_is_kept_out_of_the_env_the_server_works_on(store, env_path):
    _write(env_path, "mixed", _with_one_bad_pane())
    env = store.load_env("mixed")
    assert env["jsons"] == {"good": GOOD_PANE}
    assert store.unreadable_report("mixed")["panes"] == ["bad"]


def test_a_bad_reload_is_kept_out_of_the_env_the_server_works_on(store, env_path):
    _write(env_path, "r", _with_bad_reload())
    env = store.load_env("r")
    assert env["reload"] == {}
    assert store.unreadable_report("r")["reload"] is True


def test_a_readable_file_is_reported_as_whole(store, env_path):
    _write(env_path, "good", env_payload())
    env = store.load_env("good")
    assert env["jsons"] == {"win_0": {"id": "win_0"}}
    assert store.unreadable_report("good") == {}


@pytest.mark.parametrize("name, payload", UNREADABLE, ids=UNREADABLE_IDS)
def test_a_file_that_cannot_be_read_at_all_is_reported(name, payload, store, env_path):
    _write(env_path, "broken", payload)
    store.load_env("broken")
    assert store.unreadable_report("broken")["whole"] is True


def test_nothing_is_reported_before_the_file_is_read(store, env_path):
    _write(env_path, "mixed", _with_one_bad_pane())
    assert store.unreadable_report("mixed") == {}


def test_the_file_is_copied_aside_before_it_is_written_over(store, env_path):
    _write(env_path, "mixed", _with_one_bad_pane())
    env = store.load_env("mixed")
    store.save_env("mixed", env)
    kept = json.load(open(os.path.join(env_path, "mixed.json" + UNREADABLE_SUFFIX)))
    assert kept["jsons"]["bad"] == "not a pane"
    assert json.load(open(os.path.join(env_path, "mixed.json")))["jsons"] == {
        "good": GOOD_PANE
    }


def test_a_file_whose_jsons_cannot_be_read_is_copied_aside_too(store, env_path):
    _write(env_path, "broken", {"jsons": ["not a map"], "reload": {}})
    store.load_env("broken")
    store.save_env("broken", {"jsons": {}, "reload": {}})
    kept = json.load(open(os.path.join(env_path, "broken.json" + UNREADABLE_SUFFIX)))
    assert kept["jsons"] == ["not a map"]


def test_the_copy_is_only_taken_once(store, env_path):
    _write(env_path, "mixed", _with_one_bad_pane())
    env = store.load_env("mixed")
    store.save_env("mixed", env)
    backup = os.path.join(env_path, "mixed.json" + UNREADABLE_SUFFIX)
    first = open(backup).read()
    env["jsons"]["added"] = {"id": "added", "type": "text"}
    store.save_env("mixed", env)
    assert open(backup).read() == first


def test_a_readable_file_is_never_copied_aside(store, env_path):
    _write(env_path, "good", env_payload())
    store.save_env("good", store.load_env("good"))
    assert not os.path.exists(os.path.join(env_path, "good.json" + UNREADABLE_SUFFIX))


def test_the_copy_is_not_listed_as_an_environment(store, env_path):
    _write(env_path, "mixed", _with_one_bad_pane())
    store.save_env("mixed", store.load_env("mixed"))
    assert store.list_envs() == ["mixed"]


def test_what_is_written_back_holds_only_what_could_be_read(store, env_path):
    _write(env_path, "mixed", _with_one_bad_pane())
    store.save_env("mixed", store.load_env("mixed"))
    saved = _read(env_path, "mixed")
    assert sorted(saved["jsons"]) == ["good"]
    assert "unreadable_parts" not in saved


@pytest.mark.parametrize("name, payload", UNREADABLE, ids=UNREADABLE_IDS)
def test_loading_an_env_that_cannot_be_read_is_a_value_error(
    name, payload, store, fake_socket
):
    with pytest.raises(ValueError):
        load_env({"broken": payload}, "broken", fake_socket, store)


def test_loading_an_env_that_does_not_exist_is_not_an_error(store, fake_socket):
    load_env({}, "ghost", fake_socket, store)
    assert fake_socket.commands() == ["layout", "undo_state"]


def test_only_the_readable_panes_reach_the_client(store, env_path, fake_socket):
    _write(env_path, "mixed", _with_one_bad_pane())
    load_env({"mixed": store.load_env("mixed")}, "mixed", fake_socket, store)
    assert [w["id"] for w in _windows(fake_socket)] == ["good"]


def test_the_client_is_told_which_pane_it_is_not_getting(store, env_path, fake_socket):
    _write(env_path, "mixed", _with_one_bad_pane())
    load_env({"mixed": store.load_env("mixed")}, "mixed", fake_socket, store)
    notes = _notifications(fake_socket)
    assert len(notes) == 1
    assert "bad" in notes[0]["data"]["message"]
    assert notes[0]["data"]["type"] == "warning"


def test_the_client_is_told_about_a_layout_it_is_not_getting(
    store, env_path, fake_socket
):
    _write(env_path, "r", _with_bad_reload())
    load_env({"r": store.load_env("r")}, "r", fake_socket, store)
    notes = _notifications(fake_socket)
    assert len(notes) == 1
    assert "saved layout" in notes[0]["data"]["message"]


def test_a_readable_env_is_served_without_a_warning(store, fake_socket):
    load_env({"main": env_payload()}, "main", fake_socket, store)
    assert _notifications(fake_socket) == []


@pytest.mark.parametrize("name, payload", UNREADABLE, ids=UNREADABLE_IDS)
def test_comparing_an_env_that_cannot_be_read_is_a_value_error(
    name, payload, store, fake_socket
):
    state = {"good": env_payload(), "broken": payload}
    with pytest.raises(ValueError):
        compare_envs(state, ["good", "broken"], fake_socket, store)


def test_comparing_warns_about_a_pane_it_is_not_getting(store, env_path, fake_socket):
    _write(env_path, "mixed", _with_one_bad_pane())
    state = {"mixed": store.load_env("mixed"), "b": env_payload()}
    compare_envs(state, ["mixed", "b"], fake_socket, store)
    assert len(_notifications(fake_socket)) == 1
    assert "layout" in fake_socket.commands()


def test_comparing_readable_envs_still_works(store, fake_socket):
    state = {"a": env_payload(), "b": env_payload()}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert "layout" in fake_socket.commands()
    assert _notifications(fake_socket) == []


def test_a_pane_that_is_not_a_mapping_never_reaches_a_client(store, fake_socket):
    state = {"mixed": _with_one_bad_pane()}
    load_env(state, "mixed", fake_socket, store)
    assert [w["id"] for w in _windows(fake_socket)] == ["good"]


def test_comparing_does_not_read_a_pane_that_is_not_a_mapping(store, fake_socket):
    state = {"a": _with_one_bad_pane(), "b": _with_one_bad_pane()}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert "layout" in fake_socket.commands()
    assert state["a"]["jsons"]["bad"] == "not a pane"
