#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests that the server routes persistence through ``Application.storage``
(the DataStore backend) rather than writing environment files directly.

As end-to-end save/fork/reload behavior is already
covered in ``environment_lifecycle``; here we assert the abstraction itself
is in place so a future refactor cannot silently bypass the backend.

Nothing here speaks HTTP -- the handlers are driven through ``wrap_func`` and
``on_message`` with a ``FakeHandler`` -- so these are plain functions on the
shared fixtures, and ``SpyStore`` stands in wherever a call has to be observed.
"""

import json
import os
from unittest import mock

import pytest

from visdom.data_model.base import DataStore
from visdom.data_model.json_store import JSONStore
from visdom.server.defaults import DEFAULT_MAX_UNDO_HISTORY
from visdom.server.handlers.socket_handlers import AnySocketHandlerOrWrapper
from visdom.server.handlers.web_handlers import DeleteEnvHandler, SaveHandler
from visdom.utils.server_utils import (
    LazyEnvData,
    clear_deleted,
    compare_envs,
    count_deleted,
    gather_envs,
    load_env,
    pop_deleted,
    push_deleted,
)

from testutils.fakes import FakeHandler, SpyStore
from testutils.payloads import env_payload

pytestmark = pytest.mark.integration


# -- Save ---------------------------------------------------------------------


def test_application_has_json_store(app, env_path):
    """The app exposes a DataStore, and it points at the configured path."""
    assert isinstance(app.storage, DataStore)
    assert isinstance(app.storage, JSONStore)
    assert app.storage.env_path == env_path


def test_save_routes_through_storage(app, spy_store):
    """SaveHandler persists via storage.save_envs rather than writing files."""
    handler = FakeHandler(state=app.state, storage=spy_store)

    SaveHandler.wrap_func(handler, {"data": ["main"]})

    assert spy_store.calls["save_envs"] == [["main"]]
    assert "main" in handler.json_body()


# -- load_state ---------------------------------------------------------------


def test_saved_envs_load_into_state(store, app_factory):
    """Environments already on disk are present in a new app's state."""
    store.save_env("main", env_payload())
    store.save_env("expt", env_payload("w1"))

    app = app_factory()

    assert "expt" in app.state
    assert dict(app.state["expt"]) == env_payload("w1")


def test_lazy_by_default(store, app_factory):
    """State entries are LazyEnvData until something reads them."""
    store.save_env("expt", env_payload())

    app = app_factory()

    assert isinstance(app.state["expt"], LazyEnvData)
    assert app.state["expt"]["jsons"] == env_payload()["jsons"]


def test_eager_loads_plain_dicts(store, app_factory):
    """eager_data_loading materialises every env up front."""
    store.save_env("expt", env_payload())

    app = app_factory(eager_data_loading=True)

    assert isinstance(app.state["expt"], dict)
    assert app.state["expt"] == env_payload()


def test_eager_preserves_extra_env_keys(store, app_factory):
    """Eager loading keeps env keys the server itself does not read.

    Experiment metadata lives under the env's ``experiment`` key, so
    dropping unknown keys here would lose it on the next full-env save.
    """
    experiment = {"env_id": "expt", "name": "run-1", "status": "running"}
    store.save_env("expt", dict(env_payload("w1"), experiment=experiment))

    app = app_factory(eager_data_loading=True)

    assert app.state["expt"]["experiment"] == experiment


def test_load_state_routes_through_storage(store, app_factory):
    """Discovery lists through the store, and the read is deferred to access."""
    store.save_env("expt", env_payload())

    with mock.patch("visdom.server.app.JSONStore", SpyStore):
        app = app_factory()

    assert app.storage.calls["list_envs"] == 1
    assert app.storage.calls["load_env"] == []

    _ = app.state["expt"]["jsons"]

    assert "expt" in app.storage.calls["load_env"]


def test_none_path_is_in_memory(app_factory):
    """With no env_path the app starts on an empty in-memory main."""
    app = app_factory(env_path=None)
    assert app.state == {"main": {"jsons": {}, "reload": {}}}


def test_missing_main_is_created_and_persisted(app, store):
    """A fresh env_path gains a main environment, written through the store."""
    assert "main" in app.state
    assert store.env_exists("main")


# -- Delete -------------------------------------------------------------------


def test_web_delete_routes_through_storage(spy_store, env_path):
    """DeleteEnvHandler drops the env via storage.delete_env, not os.remove."""
    spy_store.save_env("expt", env_payload())
    assert spy_store.env_exists("expt")
    handler = FakeHandler(
        state={"expt": env_payload()}, storage=spy_store, env_path=env_path
    )

    DeleteEnvHandler.wrap_func(handler, {"eid": "expt"})

    assert spy_store.calls["delete_env"] == ["expt"]
    assert "expt" not in handler.state
    assert not spy_store.env_exists("expt")
    assert not os.path.exists(os.path.join(env_path, "expt.json"))


def test_web_delete_protects_main(spy_store, env_path):
    """The main environment is never deleted, so the store is never asked."""
    spy_store.save_env("main", env_payload())
    handler = FakeHandler(
        state={"main": env_payload()}, storage=spy_store, env_path=env_path
    )

    DeleteEnvHandler.wrap_func(handler, {"eid": "main"})

    assert spy_store.calls["delete_env"] == []
    assert spy_store.env_exists("main")


def test_socket_delete_routes_through_storage(spy_store, env_path):
    """The socket delete_env command reaches the same backend call."""
    spy_store.save_env("expt", env_payload())
    handler = FakeHandler(
        state={"expt": env_payload()},
        storage=spy_store,
        env_path=env_path,
        readonly=False,
    )

    AnySocketHandlerOrWrapper.on_message(
        handler, json.dumps({"cmd": "delete_env", "eid": "expt"})
    )

    assert spy_store.calls["delete_env"] == ["expt"]
    assert "expt" not in handler.state


# -- Layouts ------------------------------------------------------------------


def test_layout_save_and_load_route_through_storage(app_factory):
    """save_layouts writes through the store, and a new app reads it back.

    The spy has to be the store the app builds for itself: ``ServerState``
    takes its own reference at construction, so a store swapped in afterwards
    would be observed by nobody.
    """
    with mock.patch("visdom.server.app.JSONStore", SpyStore):
        app = app_factory()

    app.layouts = '[["v", {}]]'

    app.save_layouts()

    assert app.storage.calls["save_layouts"] == ['[["v", {}]]']
    assert app_factory().layouts == '[["v", {}]]'


def test_none_path_does_not_touch_storage(app_factory):
    """In-memory mode reports no layouts rather than reaching for a file."""
    assert app_factory(env_path=None).load_layouts() == ""


# -- Undo ---------------------------------------------------------------------


def test_push_then_pop_is_lifo(store):
    """The undo stack returns the most recently closed pane first."""
    push_deleted(store, "expt", "win_0", {"id": "win_0"})
    push_deleted(store, "expt", "win_1", {"id": "win_1"})

    assert count_deleted(store, "expt") == 2
    assert pop_deleted(store, "expt") == ("win_1", {"id": "win_1"})
    assert pop_deleted(store, "expt") == ("win_0", {"id": "win_0"})
    assert pop_deleted(store, "expt") is None


def test_push_trims_to_max_history(store):
    """The stack is capped, and the newest entry survives the trim."""
    for i in range(DEFAULT_MAX_UNDO_HISTORY + 3):
        push_deleted(store, "expt", f"win_{i}", {"id": f"win_{i}"})

    assert count_deleted(store, "expt") == DEFAULT_MAX_UNDO_HISTORY
    win_id, _ = pop_deleted(store, "expt")
    assert win_id == f"win_{DEFAULT_MAX_UNDO_HISTORY + 2}"


def test_clear_removes_history(store):
    """clear_deleted empties the stack."""
    push_deleted(store, "expt", "win_0", {"id": "win_0"})
    clear_deleted(store, "expt")
    assert count_deleted(store, "expt") == 0


def test_push_routes_through_store(spy_store):
    """Pushing persists through storage.save_undo, not raw env_path I/O."""
    push_deleted(spy_store, "expt", "win_0", {"id": "win_0"})
    assert spy_store.calls["save_undo"] == ["expt"]


# -- LazyEnvData --------------------------------------------------------------


def test_lazy_env_defers_until_access_then_caches(spy_store):
    """The backend read happens on first access and only once."""
    spy_store.save_env("main", env_payload())

    lazy = LazyEnvData(spy_store, "main")
    assert spy_store.calls["load_env"] == []

    assert lazy["jsons"] == env_payload()["jsons"]
    assert spy_store.calls["load_env"] == ["main"]

    _ = lazy["reload"]
    assert spy_store.calls["load_env"] == ["main"]


def test_lazy_env_missing_env_raises_value_error(store):
    """An env that was never saved surfaces as a ValueError on access."""
    lazy = LazyEnvData(store, "does_not_exist")
    with pytest.raises(ValueError):
        _ = lazy["jsons"]


# -- Read helpers -------------------------------------------------------------


def test_load_env_reads_cold_env_through_store(spy_store, fake_socket):
    """A cold env is pulled into state via the store."""
    spy_store.save_env("expt", env_payload())
    state = {}

    load_env(state, "expt", fake_socket, spy_store)

    assert spy_store.calls["load_env"] == ["expt"]
    assert dict(state["expt"]) == env_payload()


def test_load_env_skips_store_when_already_in_state(spy_store, fake_socket):
    """An env already in memory is not re-read from the backend."""
    state = {"expt": env_payload()}

    load_env(state, "expt", fake_socket, spy_store)

    assert spy_store.calls["load_env"] == []


def test_gather_envs_lists_through_store(spy_store):
    """gather_envs merges in-memory ids with whatever the store lists."""
    spy_store.save_env("on_disk", env_payload())

    items = gather_envs({"in_memory": env_payload()}, spy_store)

    assert spy_store.calls["list_envs"] == 1
    assert items == ["in_memory", "on_disk"]


def test_gather_envs_in_memory_only():
    """With persistence disabled only the in-memory ids come back."""
    assert gather_envs({"main": env_payload()}, SpyStore(None)) == ["main"]


def test_compare_envs_reads_cold_env_through_store(spy_store, fake_socket):
    """Comparing against a cold env loads it through the store first."""
    spy_store.save_env("cold", env_payload())
    state = {"warm": env_payload("w1")}

    compare_envs(state, ["warm", "cold"], fake_socket, spy_store)

    assert spy_store.calls["load_env"] == ["cold"]
    assert "cold" in state
