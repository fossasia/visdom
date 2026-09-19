#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Environments whose ``jsons`` is not a map of panes.

Every reader of an environment takes its shape on trust: ``load_env`` calls
``.values()`` on ``jsons`` and ``.get()`` on each pane, ``compare_envs`` calls
``.keys()``. Nothing used to check that shape on the way in, so an upload or an
env file carrying ``{"jsons": [], "reload": {}}`` was stored, persisted and then
answered HTTP 500 on every attempt to open or compare it.
"""

import json
import os

import pytest

from visdom.utils.server_utils import (
    LazyEnvData,
    compare_envs,
    env_is_well_formed,
    load_env,
)

from testutils.payloads import env_payload

pytestmark = pytest.mark.unit


MALFORMED = [
    ("jsons_is_a_list", {"jsons": [], "reload": {}}),
    ("jsons_is_null", {"jsons": None, "reload": {}}),
    ("jsons_is_a_string", {"jsons": "panes", "reload": {}}),
    ("a_pane_is_a_string", {"jsons": {"w1": "not a pane"}, "reload": {}}),
    ("a_pane_is_a_list", {"jsons": {"w1": []}, "reload": {}}),
    ("reload_is_a_list", {"jsons": {}, "reload": []}),
    ("jsons_is_missing", {"reload": {}}),
    ("reload_is_missing", {"jsons": {}}),
    ("not_an_object", []),
]

MALFORMED_IDS = [case[0] for case in MALFORMED]


@pytest.mark.parametrize("name, payload", MALFORMED, ids=MALFORMED_IDS)
def test_a_malformed_env_is_not_well_formed(name, payload):
    assert env_is_well_formed(payload) is False


def test_an_empty_env_is_well_formed():
    assert env_is_well_formed({"jsons": {}, "reload": {}}) is True


def test_a_populated_env_is_well_formed():
    assert env_is_well_formed(env_payload()) is True


def test_a_lazy_env_is_well_formed_once_it_is_primed(store):
    lazy = LazyEnvData(store, "main")
    lazy.prime(env_payload())
    assert env_is_well_formed(lazy) is True


@pytest.mark.parametrize("name, payload", MALFORMED, ids=MALFORMED_IDS)
def test_a_malformed_file_is_not_loaded(name, payload, store, env_path):
    with open(os.path.join(env_path, "broken.json"), "w") as fn:
        fn.write(json.dumps(payload))
    assert store.load_env("broken") == {}


def test_a_well_formed_file_is_still_loaded(store, env_path):
    with open(os.path.join(env_path, "good.json"), "w") as fn:
        fn.write(json.dumps(env_payload()))
    assert store.load_env("good")["jsons"] == {"win_0": {"id": "win_0"}}


@pytest.mark.parametrize("name, payload", MALFORMED, ids=MALFORMED_IDS)
def test_loading_a_malformed_env_is_a_value_error(name, payload, store, fake_socket):
    with pytest.raises(ValueError):
        load_env({"broken": payload}, "broken", fake_socket, store)


def test_loading_an_env_that_does_not_exist_is_not_an_error(store, fake_socket):
    load_env({}, "ghost", fake_socket, store)
    assert fake_socket.commands() == ["layout", "undo_state"]


@pytest.mark.parametrize("name, payload", MALFORMED, ids=MALFORMED_IDS)
def test_comparing_a_malformed_env_is_a_value_error(name, payload, store, fake_socket):
    state = {"good": env_payload(), "broken": payload}
    with pytest.raises(ValueError):
        compare_envs(state, ["good", "broken"], fake_socket, store)


def test_comparing_well_formed_envs_still_works(store, fake_socket):
    state = {"a": env_payload(), "b": env_payload()}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert "layout" in fake_socket.commands()
