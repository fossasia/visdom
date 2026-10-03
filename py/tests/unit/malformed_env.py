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

The rule now: an env with no ``jsons`` mapping cannot be read at all and is
refused, and anything inside one that cannot be used is held back by the store,
kept out of the state the server works on, written back to the file exactly as
it was found, and reported to the client being served.
"""

import json
import os

import pytest

from visdom.utils.server_utils import (
    LazyEnvData,
    UNREADABLE_PARTS,
    compare_envs,
    env_is_readable,
    load_env,
    readable_panes,
    reload_is_readable,
    unreadable_parts,
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
    assert unreadable_parts(env)["jsons"] == {"bad": "not a pane"}


def test_a_bad_reload_is_kept_out_of_the_env_the_server_works_on(store, env_path):
    _write(env_path, "r", _with_bad_reload())
    env = store.load_env("r")
    assert env["reload"] == {}
    assert unreadable_parts(env)["reload"] == "wide"


def test_a_readable_file_holds_nothing_back(store, env_path):
    _write(env_path, "good", env_payload())
    env = store.load_env("good")
    assert env["jsons"] == {"win_0": {"id": "win_0"}}
    assert unreadable_parts(env) == {}
    assert UNREADABLE_PARTS not in env


def test_saving_an_env_writes_its_bad_pane_back_unchanged(store, env_path):
    _write(env_path, "mixed", _with_one_bad_pane())
    env = store.load_env("mixed")
    env["jsons"]["added"] = {"id": "added", "type": "text", "content": "new"}
    store.save_env("mixed", env)
    saved = _read(env_path, "mixed")
    assert saved["jsons"]["bad"] == "not a pane"
    assert sorted(saved["jsons"]) == ["added", "bad", "good"]


def test_saving_an_env_writes_its_bad_reload_back_unchanged(store, env_path):
    _write(env_path, "r", _with_bad_reload())
    env = store.load_env("r")
    store.save_env("r", env)
    assert _read(env_path, "r")["reload"] == "wide"


def test_what_is_held_back_never_reaches_the_file_as_its_own_key(store, env_path):
    _write(env_path, "mixed", _with_one_bad_pane())
    store.save_env("mixed", store.load_env("mixed"))
    assert UNREADABLE_PARTS not in _read(env_path, "mixed")


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
