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
The entry points that touch disk -- the wrap functions and ``on_message``
alike -- are coroutines, so those calls go through ``asyncio.run``: the loop is
what hands their work to the storage executor.
"""

import asyncio
import contextlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import pytest
import tornado.web

from visdom.data_model.base import DataStore
from visdom.data_model.json_store import JSONStore
from visdom.server.defaults import DEFAULT_MAX_UNDO_HISTORY
from visdom.server.handlers.socket_handlers import AnySocketHandlerOrWrapper
from visdom.server.handlers.web_handlers import (
    CloseHandler,
    DeleteEnvHandler,
    ForkEnvHandler,
    SaveHandler,
)
from visdom.utils.server_utils import (
    LazyEnvData,
    clear_deleted,
    compare_envs,
    count_deleted,
    drop_deleted_many,
    ensure_env_loaded,
    load_env,
    pop_deleted,
    purge_env,
    push_deleted,
    push_deleted_many,
    push_deleted_off_loop,
    register_window,
    run_on_storage_executor,
    save_env_off_loop,
    warm_env,
)

from testutils import open_sub
from testutils.fakes import FakeHandler, FakeSocket, SpyStore
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

    asyncio.run(SaveHandler.wrap_func(handler, {"data": ["main"]}))

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


def test_web_delete_routes_through_storage(spy_store, env_path, inline_executor):
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


def test_socket_delete_routes_through_storage(spy_store, env_path, inline_executor):
    """The socket delete_env command reaches the same backend call."""
    spy_store.save_env("expt", env_payload())
    handler = FakeHandler(
        state={"expt": env_payload()},
        storage=spy_store,
        env_path=env_path,
        readonly=False,
    )

    asyncio.run(
        AnySocketHandlerOrWrapper.on_message(
            handler, json.dumps({"cmd": "delete_env", "eid": "expt"})
        )
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


# -- Workspace isolation ------------------------------------------------------


def test_workspaces_start_with_no_layouts(app_factory):
    """A workspace nobody has saved a view in has none, not the server's."""
    app = app_factory()
    app.layouts = '[["server", {}]]'

    assert app.workspace_env_manager.space("ws-a").get_layouts() == ""


def test_saving_layouts_in_one_workspace_does_not_leak(app_factory):
    """Layouts are per workspace, not one shared blob."""
    manager = app_factory().workspace_env_manager

    space_a = manager.space("ws-a")
    space_a.set_layouts('[["a", {}]]')
    space_a.save_layouts()

    assert manager.space("ws-a").get_layouts() == '[["a", {}]]'
    assert manager.space("ws-b").get_layouts() == ""


def test_saving_in_a_workspace_leaves_the_server_state_alone(app_factory):
    app = app_factory()
    app.layouts = '[["server", {}]]'

    space = app.workspace_env_manager.space("ws-a")
    space.set_layouts('[["a", {}]]')
    space.save_layouts()

    assert app.layouts == '[["server", {}]]'


def test_layouts_persist_under_the_workspace_directory(app_factory, env_path):
    space = app_factory().workspace_env_manager.space("ws-a")
    space.set_layouts('[["a", {}]]')
    space.save_layouts()

    written = os.path.join(env_path, "workspaces", "ws-a", "view", "layouts.json")
    assert os.path.isfile(written)


def test_workspace_environments_are_separate(app_factory):
    """Two workspaces writing the same env id do not share it."""
    manager = app_factory().workspace_env_manager

    manager.space("ws-a").state["shared"] = env_payload("a")
    manager.space("ws-b").state["shared"] = env_payload("b")

    assert manager.space("ws-a").state["shared"] == env_payload("a")
    assert manager.space("ws-b").state["shared"] == env_payload("b")


def test_workspace_inherits_the_server_configuration(app_factory):
    """A workspace cannot end up with different limits from its server."""
    app = app_factory()
    space = app.workspace_env_manager.space("ws-a")

    assert space.save_interval == app.server_state.save_interval
    assert space.max_plot_history == app.server_state.max_plot_history
    assert space.readonly == app.server_state.readonly


def test_eager_workspace_load_keeps_extra_env_keys(app_factory, env_path):
    """A workspace loaded eagerly keeps the keys the server's own load keeps."""
    experiment = {"env_id": "expt", "name": "run-1", "status": "running"}
    workspace_store = JSONStore(os.path.join(env_path, "workspaces", "ws-a"))
    workspace_store.save_env("expt", dict(env_payload("w1"), experiment=experiment))

    app = app_factory(eager_data_loading=True)
    space = app.workspace_env_manager.space("ws-a")

    assert space.state["expt"]["experiment"] == experiment
    assert space.state["expt"]["jsons"] == env_payload("w1")["jsons"]


@pytest.mark.parametrize(
    "workspace_id", ["", ".", "..", "../outside", "a/b", "/tmp/outside"]
)
def test_a_workspace_id_cannot_leave_the_workspaces_folder(
    app_factory, env_path, workspace_id
):
    manager = app_factory().workspace_env_manager

    with pytest.raises(ValueError):
        manager.space(workspace_id)

    assert not os.path.exists(os.path.join(env_path, "outside"))
    assert not os.path.exists(os.path.join(env_path, "workspaces", "a"))


def test_default_workspace_is_the_server_state(app_factory):
    """Workspace None is not a copy of the server's state, it is that state."""
    app = app_factory()

    assert app.workspace_env_manager.space(None) is app.server_state


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


def closed_panes(*win_ids):
    """The ``(win_id, p_data)`` pairs a close hands to the undo stack."""
    return [(win_id, {"id": win_id}) for win_id in win_ids]


def env_with(*win_ids):
    """An environment holding one bare pane per id."""
    return env_payload(jsons={win_id: {"id": win_id} for win_id in win_ids})


def test_pushing_many_stacks_them_in_the_order_they_were_closed(store):
    """Closing a whole env leaves the stack pushing one at a time would have."""
    push_deleted_many(store, "expt", closed_panes("win_0", "win_1"))

    assert count_deleted(store, "expt") == 2
    assert pop_deleted(store, "expt") == ("win_1", {"id": "win_1"})
    assert pop_deleted(store, "expt") == ("win_0", {"id": "win_0"})
    assert pop_deleted(store, "expt") is None


def test_pushing_many_is_one_read_and_one_write(spy_store):
    """The point of the batch: a file per pane becomes a file per close."""
    depth = push_deleted_many(
        spy_store, "expt", closed_panes("win_0", "win_1", "win_2")
    )

    assert depth == 3
    assert spy_store.calls["load_undo"] == ["expt"]
    assert spy_store.calls["save_undo"] == ["expt"]


def test_pushing_many_trims_to_max_history(store):
    """The cap holds over a batch, and the last panes closed are the survivors."""
    many = closed_panes(*[f"win_{i}" for i in range(DEFAULT_MAX_UNDO_HISTORY + 3)])

    assert push_deleted_many(store, "expt", many) == DEFAULT_MAX_UNDO_HISTORY

    win_id, _ = pop_deleted(store, "expt")
    assert win_id == f"win_{DEFAULT_MAX_UNDO_HISTORY + 2}"


def test_pushing_many_keeps_what_an_earlier_close_left(store):
    """A second close stacks on top of the first rather than replacing it."""
    push_deleted(store, "expt", "win_0", {"id": "win_0"})

    assert push_deleted_many(store, "expt", closed_panes("win_1")) == 2
    assert pop_deleted(store, "expt") == ("win_1", {"id": "win_1"})
    assert pop_deleted(store, "expt") == ("win_0", {"id": "win_0"})


def test_dropping_many_takes_back_what_one_close_pushed(store):
    """A rolled-back close's entries go; the close before it stays undoable."""
    push_deleted(store, "expt", "win_0", {"id": "win_0"})
    rolled_back = closed_panes("win_1", "win_2")
    push_deleted_many(store, "expt", rolled_back)

    assert drop_deleted_many(store, "expt", rolled_back) == 1
    assert pop_deleted(store, "expt") == ("win_0", {"id": "win_0"})
    assert pop_deleted(store, "expt") is None


def test_dropping_many_removes_the_file_when_nothing_is_left(spy_store):
    """An empty stack is no file, the way popping the last entry leaves it."""
    panes = closed_panes("win_0")
    push_deleted_many(spy_store, "expt", panes)

    assert drop_deleted_many(spy_store, "expt", panes) == 0
    assert spy_store.calls["clear_undo"] == ["expt"]
    assert count_deleted(spy_store, "expt") == 0


def test_dropping_many_writes_nothing_when_the_push_never_landed(spy_store):
    """The failed-write case: there is no entry to take back, so no write."""
    assert drop_deleted_many(spy_store, "expt", closed_panes("win_0")) == 0

    assert spy_store.calls["save_undo"] == []
    assert spy_store.calls["clear_undo"] == []


def test_dropping_many_leaves_a_later_close_of_the_same_pane_alone(store):
    """Two entries under one id: the one this close pushed is the one that goes.

    The id was re-created and closed again while the rolled-back write was out,
    so the stack holds the pane this close took and the newer pane behind it.
    Matching on the id alone would take the newer pane, which the undo stack is
    the only remaining copy of.
    """
    rolled_back = closed_panes("win_0")
    push_deleted_many(store, "expt", rolled_back)
    push_deleted(store, "expt", "win_0", {"id": "win_0", "type": "text"})

    assert drop_deleted_many(store, "expt", rolled_back) == 1
    assert pop_deleted(store, "expt") == ("win_0", {"id": "win_0", "type": "text"})
    assert pop_deleted(store, "expt") is None


def test_dropping_many_matches_by_id_when_the_stack_changed_the_pane(store):
    """What comes back off disk is not always what went down.

    ``NanSafeEncoder`` writes a NaN as ``null``, so the entry read back is not
    equal to the pane the close is holding. The id it was closed under still
    names it, and an entry left behind here is exactly the one this is for.
    """
    pane = {"id": "win_0", "content": [float("nan")]}
    push_deleted_many(store, "expt", [("win_0", pane)])

    assert drop_deleted_many(store, "expt", [("win_0", pane)]) == 0
    assert count_deleted(store, "expt") == 0


def test_dropping_many_keeps_an_entry_it_was_not_asked_about(store):
    """Only the panes named are taken back, not the whole stack."""
    push_deleted_many(store, "expt", closed_panes("win_0", "win_1"))

    assert drop_deleted_many(store, "expt", closed_panes("win_1")) == 1
    assert pop_deleted(store, "expt") == ("win_0", {"id": "win_0"})


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


def test_compare_envs_reads_cold_env_through_store(spy_store, fake_socket):
    """Comparing against a cold env loads it through the store first."""
    spy_store.save_env("cold", env_payload())
    state = {"warm": env_payload("w1")}

    compare_envs(state, ["warm", "cold"], fake_socket, spy_store)

    assert spy_store.calls["load_env"] == ["cold"]
    assert "cold" in state


# -- Storage executor ---------------------------------------------------------


def test_application_owns_a_single_worker_storage_executor(app):
    """One worker is what serializes writes, so two saves cannot interleave."""
    assert isinstance(app.storage_executor, ThreadPoolExecutor)
    assert app.storage_executor._max_workers == 1


def test_handlers_receive_the_storage_executor(app):
    handler = SaveHandler(app, mock.Mock())
    handler.initialize(app)

    assert handler.storage_executor is app.storage_executor


def test_shutdown_drains_the_queue_before_the_final_save(app):
    """A queued write landing after the final save would restore a stale env."""
    order = []

    def slow_write():
        time.sleep(0.05)
        order.append("queued-write")

    app.storage.save_all = lambda state: order.append("final-save")
    app.storage_executor.submit(slow_write)

    app.shutdown_storage()

    assert order == ["queued-write", "final-save"]


def test_a_second_shutdown_does_not_write_again(app):
    """The graceful stop drains, then the atexit hook calls it once more."""
    saves = []
    app.storage.save_all = lambda state: saves.append(state)

    app.shutdown_storage()
    app.shutdown_storage()

    assert len(saves) == 1


def test_a_failed_final_save_is_retried_by_the_next_shutdown(app):
    """A save that raised must not mark storage shut down, or atexit skips it."""
    saves = []

    def flaky_save_all(state):
        saves.append(state)
        if len(saves) == 1:
            raise OSError("disk full")

    app.storage.save_all = flaky_save_all

    with pytest.raises(OSError):
        app.shutdown_storage()
    app.shutdown_storage()
    app.shutdown_storage()

    assert len(saves) == 2


def test_two_shutdowns_at_once_still_save_only_once(app):
    """Nothing orders the graceful stop against the ``atexit`` hook -- a server
    embedded in a thread runs the first off the main thread, where the second
    always runs -- and the flag that guards the second pass is not set until
    the save has returned. So both used to get in and write the same
    environment files from two threads at once.

    The first save is held open rather than merely made slow, so the overlap
    is certain on every schedule instead of on most of them.
    """
    saves = []
    running = threading.Event()
    finish = threading.Event()
    overlapped = threading.Event()

    def held_save_all(state):
        saves.append(state)
        if len(saves) > 1:
            overlapped.set()
            return
        running.set()
        assert finish.wait(10), "the first shutdown was never released"

    app.storage.save_all = held_save_all

    first = threading.Thread(target=app.shutdown_storage)
    second = threading.Thread(target=app.shutdown_storage)
    first.start()
    try:
        assert running.wait(10), "the first shutdown never reached save_all"
        second.start()

        assert not overlapped.wait(0.5), "both shutdowns were inside save_all"
    finally:
        finish.set()
        first.join(10)
        second.join(10)

    # The second waited out the first, then found the flag set, so the state
    # reached disk exactly once.
    assert len(saves) == 1
    assert not first.is_alive() and not second.is_alive()


def test_shutdown_flushes_state_through_storage(app):
    app.state["expt"] = env_payload()

    app.shutdown_storage()

    assert app.storage.env_exists("expt")


def test_ensure_env_loaded_primes_a_cold_env(spy_store):
    """The read happens off the loop, then the result is handed back."""
    spy_store.save_env("cold", env_payload())
    handler = FakeHandler(
        state={"cold": LazyEnvData(spy_store, "cold")}, storage=spy_store
    )
    assert handler.state["cold"].is_loaded is False

    asyncio.run(ensure_env_loaded(handler, "cold"))

    assert handler.state["cold"].is_loaded is True
    assert "win_0" in handler.state["cold"]["jsons"]


def test_ensure_env_loaded_skips_an_env_already_in_memory(app, spy_store):
    handler = FakeHandler(state={"warm": env_payload()}, storage=spy_store)

    asyncio.run(ensure_env_loaded(handler, "warm"))

    assert spy_store.calls["load_env"] == []


# -- Socket commands and the loop thread --------------------------------------


def dispatch(handler, **msg):
    """Run one socket command to completion, reporting the loop's thread.

    ``on_message`` is a coroutine, so a loop has to drive it; the name of the
    thread that loop ran on is what the assertions below compare the store's
    calls against.
    """
    loop_thread = {}

    async def main():
        loop_thread["name"] = threading.current_thread().name
        await AnySocketHandlerOrWrapper.on_message(handler, json.dumps(msg))

    asyncio.run(main())
    return loop_thread["name"]


def assert_off_loop(store, loop_thread, methods):
    """Every call to ``methods`` happened somewhere other than the loop."""
    ran = [(m, t) for m, t in store.threads if m in methods]
    assert ran, f"expected {methods} to be called, saw {store.threads}"
    assert [t for _m, t in ran if t == loop_thread] == []


def socket_handler(spy_store, env_path, state):
    return FakeHandler(
        state=state, storage=spy_store, env_path=env_path, readonly=False
    )


def test_socket_close_writes_the_undo_stack_off_the_loop(spy_store, env_path):
    """Closing a pane records it for undo, and that write is not on the loop."""
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})

    loop_thread = dispatch(handler, cmd="close", eid="expt", data="win_0")

    assert spy_store.calls["save_undo"] == ["expt"]
    assert_off_loop(spy_store, loop_thread, {"load_undo", "save_undo"})


def close_handler(spy_store, env_path, state):
    """The handler ``/close`` runs against, with no Tornado request behind it."""
    return FakeHandler(state=state, storage=spy_store, env_path=env_path)


def close_over_http(handler, **args):
    """Run the ``/close`` wrap function to completion, reporting the loop's thread.

    Like ``dispatch`` for socket commands: ``wrap_func`` is a coroutine now, so
    a loop has to drive it, and the name of the thread that loop ran on is what
    the store's calls are compared against.
    """
    loop_thread = {}

    async def main():
        loop_thread["name"] = threading.current_thread().name
        await CloseHandler.wrap_func(handler, args)

    asyncio.run(main())
    return loop_thread["name"]


def test_http_close_writes_the_undo_stack_off_the_loop(spy_store, env_path):
    """``/close`` records the pane for undo, and not on the loop.

    The socket close was taken off the loop with the rest of the commands; this
    one kept writing the undo file inline, under a ``post`` that was already a
    coroutine.
    """
    handler = close_handler(spy_store, env_path, {"expt": env_payload()})

    loop_thread = close_over_http(handler, eid="expt", win="win_0")

    assert spy_store.calls["save_undo"] == ["expt"]
    assert_off_loop(spy_store, loop_thread, {"load_undo", "save_undo"})


def test_http_close_of_a_whole_env_writes_the_stack_once(spy_store, env_path):
    """Every pane of the env goes to the worker as one write, off the loop."""
    env = env_with("win_0", "win_1", "win_2")
    handler = close_handler(spy_store, env_path, {"expt": env})

    loop_thread = close_over_http(handler, eid="expt", win=None)

    assert handler.state["expt"]["jsons"] == {}
    assert spy_store.calls["load_undo"] == ["expt"]
    assert spy_store.calls["save_undo"] == ["expt"]
    assert_off_loop(spy_store, loop_thread, {"load_undo", "save_undo"})


def test_http_close_of_a_whole_env_can_be_undone_pane_by_pane(spy_store, env_path):
    """The batch leaves the stack a client can walk back, newest pane first."""
    env = env_with("win_0", "win_1")
    handler = close_handler(spy_store, env_path, {"expt": env})

    close_over_http(handler, eid="expt", win=None)

    assert count_deleted(spy_store, "expt") == 2
    assert pop_deleted(spy_store, "expt")[0] == "win_1"
    assert pop_deleted(spy_store, "expt")[0] == "win_0"


def test_http_close_of_a_pane_that_is_already_gone_writes_nothing(spy_store, env_path):
    """Nothing was closed, so there is nothing to record -- but it is announced."""
    handler = close_handler(spy_store, env_path, {"expt": env_payload()})
    sub = handler.add_sub(eid="expt")

    close_over_http(handler, eid="expt", win="never_existed")

    assert spy_store.calls["save_undo"] == []
    assert handler.dirtied == []
    assert sub.last()["data"] == "never_existed"


@contextlib.contextmanager
def undo_write_failing(store):
    """Make ``save_undo`` raise, the way a full or read-only disk does.

    The close has already popped its panes by the time the write goes out, so
    this is the only moment where the panes exist nowhere but in the handler's
    own frame -- which is what makes the failure worth a test of its own.
    """
    real_save = store.save_undo

    def refuse(eid, stack):
        raise OSError("no space left on device")

    store.save_undo = refuse
    try:
        yield
    finally:
        store.save_undo = real_save


def test_http_close_puts_the_panes_back_when_the_undo_write_fails(spy_store, env_path):
    """A close that cannot be recorded is undone rather than left unundoable.

    Without the rollback the panes were gone from ``state`` and the env was
    marked dirty before the write that failed: the next autosave wrote the env
    without them, and the undo file that was meant to hold them never landed,
    so nothing anywhere could bring them back.
    """
    env = env_with("win_0", "win_1")
    handler = close_handler(spy_store, env_path, {"expt": env})

    with undo_write_failing(spy_store):
        with pytest.raises(OSError):
            close_over_http(handler, eid="expt", win=None)

    assert handler.state["expt"]["jsons"] == {
        "win_0": {"id": "win_0"},
        "win_1": {"id": "win_1"},
    }


def test_a_failed_undo_write_announces_no_close(spy_store, env_path):
    """The panes are still there, so no client is told they went away."""
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0")})
    sub = handler.add_sub(eid="expt")

    with undo_write_failing(spy_store):
        with pytest.raises(OSError):
            close_over_http(handler, eid="expt", win="win_0")

    assert sub.commands() == []


def test_a_failed_undo_write_marks_the_env_it_put_back(spy_store, env_path):
    """The restored panes have to reach disk the way the close's pops did.

    The pop marked the env already; putting the pane back changes it again,
    and an env left unmarked after that is one an autosave can skip -- the
    restore would live only in memory until something else dirtied it.
    """
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0")})

    with undo_write_failing(spy_store):
        with pytest.raises(OSError):
            close_over_http(handler, eid="expt", win="win_0")

    assert handler.dirtied == ["expt", "expt"]


def test_a_failed_undo_write_does_not_overwrite_a_pane_written_behind_it(
    spy_store, env_path, storage_worker
):
    """Rolling back restores what is missing, not what is there.

    The loop kept serving while the doomed write was out, so an ``/events``
    post could have put a new window under one of the closed ids. Restoring
    that id would throw the new pane away -- the rollback owes the close's
    panes a place to come back to, not the id itself.
    """
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0", "win_1")})
    handler.storage_executor = storage_worker

    with undo_write_failing(spy_store):
        with pytest.raises(OSError):
            race_close_with_rewrite(handler, spy_store, "expt", "win_0", win=None)

    panes = handler.state["expt"]["jsons"]
    assert panes["win_0"]["type"] == "text"
    assert panes["win_1"] == {"id": "win_1"}


def test_a_failed_undo_write_restores_nothing_into_a_deleted_env(
    spy_store, env_path, storage_worker
):
    """An env that was deleted meanwhile stays deleted, failure or not.

    There is nothing to roll back into: the env the panes belonged to is gone
    from ``state`` and its files are gone from disk. Marking it dirty anyway
    would point the next autosave at an id the server no longer holds.
    """
    spy_store.save_env("expt", env_payload())
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0")})
    handler.storage_executor = storage_worker
    marked_by_the_pop = ["expt"]

    with undo_write_failing(spy_store):
        with pytest.raises(OSError):
            race_close_with_delete(handler, spy_store, "expt", win="win_0")

    assert "expt" not in handler.state
    assert handler.dirtied == marked_by_the_pop


async def worker_drained(handler):
    """Wait for everything already queued on the storage worker to finish.

    The single worker runs its tasks in the order they were submitted, so a
    task submitted now settles behind them -- which is what the rollback of a
    cancelled close relies on, and the only way a test can tell that the write
    it was taking back has run.
    """
    await run_on_storage_executor(handler, lambda: None)


def cancel_close_mid_write(handler, store, eid, **args):
    """Cancel an HTTP close while its undo write is on the worker.

    The undo read is held open, so the close is parked on the disk when the
    cancellation arrives -- a client that went away, or a request Tornado gave
    up on. Releasing it afterwards lets the write it no longer owns run to the
    end, which is the point: cancelling the future does not stop the worker.
    Everything the handler queued in response is settled before this returns.
    """

    async def main():
        with call_held_open(store, "load_undo", eid) as (running, finish):
            close = asyncio.ensure_future(
                CloseHandler.wrap_func(handler, dict(args, eid=eid))
            )
            assert await asyncio.to_thread(
                running.wait, 10
            ), "the close never reached the disk"
            close.cancel()
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await close
        await worker_drained(handler)

    asyncio.run(main())


def test_a_cancelled_close_puts_its_panes_back_too(spy_store, env_path, storage_worker):
    """A client that goes away mid-close must not take its panes with it.

    The await is where the close can be interrupted, and a cancellation
    arriving there leaves exactly what a failed write leaves: panes out of
    ``state`` with no undo entry anywhere. This is why the rollback catches
    more than ``Exception``.
    """
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0")})
    handler.storage_executor = storage_worker

    cancel_close_mid_write(handler, spy_store, "expt", win="win_0")

    assert handler.state["expt"]["jsons"] == {"win_0": {"id": "win_0"}}
    # The pane is back, so nothing may still say it was closed: the write the
    # cancellation did not stop ran to the end -- ``save_undo`` is the proof --
    # and the rollback took its entry out again behind it.
    assert spy_store.calls["save_undo"] == ["expt"]
    assert count_deleted(spy_store, "expt") == 0


def test_a_cancelled_close_of_a_whole_env_leaves_no_entry_behind(
    spy_store, env_path, storage_worker
):
    """Every pane of the env comes back, and the stack is as it was before.

    The batch is one entry per pane, so a cancellation that puts them all back
    owes the stack all of them -- including when the env had a close of its own
    to undo already, which is not this close's to take.
    """
    push_deleted(spy_store, "expt", "win_old", {"id": "win_old"})
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0", "win_1")})
    handler.storage_executor = storage_worker

    cancel_close_mid_write(handler, spy_store, "expt", win=None)

    assert handler.state["expt"]["jsons"] == {
        "win_0": {"id": "win_0"},
        "win_1": {"id": "win_1"},
    }
    assert count_deleted(spy_store, "expt") == 1
    assert pop_deleted(spy_store, "expt") == ("win_old", {"id": "win_old"})


def test_a_cancelled_close_keeps_the_entry_for_a_pane_it_could_not_put_back(
    spy_store, env_path, storage_worker
):
    """An id taken by a newer window keeps its undo entry.

    The rollback restores only the ids that are still missing, and an entry
    whose pane did not come back is the one place that pane still exists:
    dropping it with the others would lose it for good, where keeping it leaves
    exactly what a close followed by a re-create leaves.
    """
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0", "win_1")})
    handler.storage_executor = storage_worker

    async def main():
        with call_held_open(spy_store, "load_undo", "expt") as (running, finish):
            close = asyncio.ensure_future(
                CloseHandler.wrap_func(handler, {"eid": "expt", "win": None})
            )
            assert await asyncio.to_thread(running.wait, 10)
            register_window(handler, {"id": "win_0", "type": "text"}, "expt")
            close.cancel()
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await close
        await worker_drained(handler)

    asyncio.run(main())

    assert handler.state["expt"]["jsons"]["win_0"]["type"] == "text"
    assert count_deleted(spy_store, "expt") == 1
    assert pop_deleted(spy_store, "expt") == ("win_0", {"id": "win_0"})


def test_a_failed_undo_write_asks_for_no_removal_it_does_not_need(
    spy_store, env_path, storage_worker
):
    """A write that raised left no entry, so the rollback writes nothing.

    The removal goes out either way -- the handler cannot know how far the
    write got, and a cancellation is far more likely to have let it through
    than to have stopped it -- but it finds the close's entries missing here,
    and a stack it did not change is a stack it must not rewrite.
    """
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0")})
    handler.storage_executor = storage_worker

    async def main():
        with undo_write_failing(spy_store):
            with pytest.raises(OSError):
                await CloseHandler.wrap_func(handler, {"eid": "expt", "win": "win_0"})
            await worker_drained(handler)

    asyncio.run(main())

    assert spy_store.calls["load_undo"] == ["expt", "expt"]
    assert spy_store.calls["clear_undo"] == []
    assert count_deleted(spy_store, "expt") == 0


def test_a_close_rolled_back_into_a_deleted_env_asks_for_nothing(
    spy_store, env_path, storage_worker
):
    """Nothing came back, so there is nothing to take back.

    The delete took the undo file with the env, and a removal queued behind it
    would only read a stack that is already gone -- or, worse, write one back
    under a name the server no longer holds.
    """
    spy_store.save_env("expt", env_payload())
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0")})
    handler.storage_executor = storage_worker
    spy_store.calls["load_undo"] = []

    with undo_write_failing(spy_store):
        with pytest.raises(OSError):
            race_close_with_delete(handler, spy_store, "expt", win="win_0")

    assert spy_store.calls["load_undo"] == ["expt"]


def test_socket_close_reports_the_depth_it_was_just_told(spy_store, env_path):
    """The undo count rides back on the push, so the stack is read once."""
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})
    sub = handler.add_sub(eid="expt")

    dispatch(handler, cmd="close", eid="expt", data="win_0")

    assert spy_store.calls["load_undo"] == ["expt"]
    assert sub.last("undo_state")["count"] == 1


def test_socket_undo_reads_the_stack_off_the_loop(spy_store, env_path):
    """Undo pops from disk, and reports what is left, without the loop waiting."""
    push_deleted(spy_store, "expt", "win_1", {"id": "win_1"})
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})
    sub = handler.add_sub(eid="expt")
    spy_store.threads.clear()

    loop_thread = dispatch(handler, cmd="undo", eid="expt")

    assert "win_1" in handler.state["expt"]["jsons"]
    assert sub.last("undo_state")["count"] == 0
    assert_off_loop(spy_store, loop_thread, {"load_undo", "clear_undo"})


def test_socket_delete_env_removes_the_env_file_off_the_loop(spy_store, env_path):
    """Both files an env owns go to the worker, undo stack included.

    Clearing the stack on the loop would run it ahead of any close or undo
    already queued, which would then save the stack back behind the delete;
    handing the two removals over as one task keeps them behind that write.
    """
    spy_store.save_env("expt", env_payload())
    push_deleted(spy_store, "expt", "win_0", {"id": "win_0"})
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})
    spy_store.threads.clear()

    loop_thread = dispatch(handler, cmd="delete_env", eid="expt")

    assert spy_store.calls["delete_env"] == ["expt"]
    assert count_deleted(spy_store, "expt") == 0
    assert_off_loop(spy_store, loop_thread, {"delete_env", "clear_undo"})


# -- Socket commands racing a delete of the env they name ----------------------


@pytest.fixture
def storage_worker():
    """The single worker the application runs its disk work on.

    ``FakeHandler`` leaves the executor unset, which lands the work on the
    loop's default pool -- several threads, so nothing keeps two tasks in the
    order they were submitted. The races below are about that order, so they
    need the one worker ``ServerState`` builds.
    """
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-storage")
    yield worker
    worker.shutdown()


@contextlib.contextmanager
def call_held_open(store, method, eid):
    """Hold one ``store`` call for ``eid`` open on the worker, loop running on.

    The races below need their command parked on the disk when the delete
    lands, and starting it and yielding once with ``await asyncio.sleep(0)``
    does not put it there: the executor future the command awaits can already
    be resolved by the time it is awaited, and awaiting a resolved future
    returns without suspending. The command then runs to completion before the
    delete it was meant to race is issued at all -- a test that passes for the
    wrong reason on most runs and fails on the rest. Blocking inside the call
    makes the overlap certain on every schedule.

    Yields the two events: the first is set once the call is in flight, the
    second releases it. What a caller does between the two is what it is
    testing -- see the two shapes below.
    """
    running = threading.Event()
    finish = threading.Event()
    real_call = getattr(store, method)

    def held(name, *args, **kwargs):
        if name == eid:
            running.set()
            assert finish.wait(10), "the {} of {!r} was never released".format(
                method, name
            )
        return real_call(name, *args, **kwargs)

    setattr(store, method, held)
    try:
        yield running, finish
    finally:
        setattr(store, method, real_call)


def read_held_open(store, eid):
    """Hold ``load_env(eid)`` open, for the races staged on reading an env.

    A caller that settles its delete before releasing -- which the two copy
    races below do, on the multi-threaded default pool -- leaves the read to
    resume against an env gone from ``state`` and off disk both. One that
    releases first -- which ``race_read_with_delete`` does, to keep the purge
    behind the read on the single worker -- leaves it resuming against an env
    that is only gone from ``state``. Both are cases a handler has to answer
    for rather than raise out of.
    """
    return call_held_open(store, "load_env", eid)


def race_with_delete(handler, store, **msg):
    """Run one socket command, deleting its env while it waits on the disk.

    The command's undo-stack read is held open on the worker, so the delete
    runs on the loop with the command parked -- exactly as it would if a second
    client had sent one. Releasing before the removal is awaited leaves the two
    disk visits in the order the application gives them to the single worker:
    the command's write first, the purge behind it. Both are settled before
    this returns.
    """

    async def main():
        with call_held_open(store, "load_undo", msg["eid"]) as (running, finish):
            command = asyncio.ensure_future(
                AnySocketHandlerOrWrapper.on_message(handler, json.dumps(msg))
            )
            assert await asyncio.to_thread(
                running.wait, 10
            ), "the command never reached the disk"
            removal = DeleteEnvHandler.wrap_func(handler, {"eid": msg["eid"]})
            finish.set()
            await command
            if removal is not None:
                await removal

    asyncio.run(main())


def race_close_with_delete(handler, store, eid, **args):
    """Delete ``eid`` on the loop while the HTTP close's undo write is out.

    ``race_with_delete`` for ``/close`` instead of a socket command: the undo
    read is held open on the worker, so the delete runs with the close parked on
    the disk -- exactly as it would if a second client had sent one.
    """

    async def main():
        with call_held_open(store, "load_undo", eid) as (running, finish):
            close = asyncio.ensure_future(
                CloseHandler.wrap_func(handler, dict(args, eid=eid))
            )
            assert await asyncio.to_thread(
                running.wait, 10
            ), "the close never reached the disk"
            removal = DeleteEnvHandler.wrap_func(handler, {"eid": eid})
            finish.set()
            try:
                await close
            finally:
                # The delete is on its way to the worker either way: a close
                # that raises here must not leave its future unawaited.
                if removal is not None:
                    await removal

    asyncio.run(main())


def race_close_with_rewrite(handler, store, eid, rewritten, **args):
    """Write ``rewritten`` back into ``eid`` while the close's undo write is out.

    ``race_close_with_delete``, but with the second client re-creating the pane
    id rather than deleting its environment: the undo read is held open on the
    worker, so the new window lands on the loop with the close parked on the
    disk -- what a ``/events`` post reusing the id does.
    """

    async def main():
        with call_held_open(store, "load_undo", eid) as (running, finish):
            close = asyncio.ensure_future(
                CloseHandler.wrap_func(handler, dict(args, eid=eid))
            )
            assert await asyncio.to_thread(
                running.wait, 10
            ), "the close never reached the disk"
            register_window(handler, {"id": rewritten, "type": "text"}, eid)
            finish.set()
            await close

    asyncio.run(main())


def test_http_close_does_not_announce_a_pane_written_again_behind_it(
    spy_store, env_path, storage_worker
):
    """A pane re-created while the close was on the disk survives the close.

    The close popped the id on the loop and then awaited its undo write, and
    the loop went on serving: an ``/events`` post reusing the id put a new
    window there. Announcing the close afterwards took that window off every
    client while the server went on holding it -- a pane only a reload brought
    back.
    """
    handler = close_handler(spy_store, env_path, {"expt": env_payload()})
    handler.storage_executor = storage_worker
    sub = handler.add_sub(eid="expt")

    race_close_with_rewrite(handler, spy_store, "expt", "win_0", win="win_0")

    assert "win_0" in handler.state["expt"]["jsons"]
    assert "close" not in sub.commands()


def test_http_close_still_announces_the_panes_that_stayed_closed(
    spy_store, env_path, storage_worker
):
    """Only the id that came back is held back; the rest close as they always did."""
    handler = close_handler(spy_store, env_path, {"expt": env_with("win_0", "win_1")})
    handler.storage_executor = storage_worker
    sub = handler.add_sub(eid="expt")

    race_close_with_rewrite(handler, spy_store, "expt", "win_0", win=None)

    closed = [m["data"] for m in sub.sent if m.get("command") == "close"]
    assert closed == ["win_1"]


def race_read_with_delete(handler, store, eid, make_reader):
    """Delete ``eid`` on the loop while a read of it is out on the worker.

    The read is released before the removal is awaited, so the purge stays
    behind it on the single worker; what the read must not do is file what it
    read back into ``state`` once the delete has dropped it.
    """

    async def main():
        with read_held_open(store, eid) as (reading, finish):
            reading_task = asyncio.ensure_future(make_reader())
            assert await asyncio.to_thread(
                reading.wait, 10
            ), "the read never reached the disk"
            removal = DeleteEnvHandler.wrap_func(handler, {"eid": eid})
            finish.set()
            await reading_task
            if removal is not None:
                await removal

    asyncio.run(main())


def test_http_close_racing_a_delete_announces_nothing(
    spy_store, env_path, storage_worker
):
    """The env is gone by the time the close resumes, so nobody hears about it.

    The pane left ``state`` before the delete landed, so the close has an undo
    entry on its way to a file the purge is about to remove. Announcing it
    would tell subscribers a pane of an environment they have already been told
    is gone just closed.
    """
    spy_store.save_env("expt", env_payload())
    handler = close_handler(spy_store, env_path, {"expt": env_payload()})
    handler.storage_executor = storage_worker
    sub = handler.add_sub(eid="expt")

    race_close_with_delete(handler, spy_store, "expt", win="win_0")

    # The delete announced itself; the close that resumed behind it did not.
    assert sub.commands() == ["env_update"]
    assert "expt" not in handler.state


def test_http_close_racing_a_delete_leaves_no_undo_history(
    spy_store, env_path, storage_worker
):
    """A close on its way to disk cannot restore the undo file behind a delete."""
    spy_store.save_env("expt", env_payload())
    handler = close_handler(spy_store, env_path, {"expt": env_payload()})
    handler.storage_executor = storage_worker

    race_close_with_delete(handler, spy_store, "expt", win="win_0")

    assert not spy_store.env_exists("expt")
    assert count_deleted(spy_store, "expt") == 0


def test_socket_close_racing_a_delete_leaves_no_undo_history(
    spy_store, env_path, storage_worker
):
    """A close on its way to disk cannot restore the undo file behind a delete.

    The push was queued before the delete, so it lands first; clearing the
    stack on the loop happened before that write and left the deleted env's
    undo history sitting on disk for whoever next took its name.
    """
    spy_store.save_env("expt", env_payload())
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})
    handler.storage_executor = storage_worker

    race_with_delete(handler, spy_store, cmd="close", eid="expt", data="win_0")

    assert "expt" not in handler.state
    assert not spy_store.env_exists("expt")
    assert count_deleted(spy_store, "expt") == 0


def test_socket_close_racing_a_delete_announces_nothing(
    spy_store, env_path, storage_worker
):
    """The env is gone by the time the close resumes, so nobody hears about it."""
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})
    handler.storage_executor = storage_worker
    sub = handler.add_sub(eid="expt")

    race_with_delete(handler, spy_store, cmd="close", eid="expt", data="win_0")

    assert sub.last("undo_state") is None
    assert handler.dirtied == []


def test_socket_undo_racing_a_delete_does_not_restore_the_env(
    spy_store, env_path, storage_worker
):
    """Undo resumes to find its env deleted, and leaves it deleted.

    Reaching for ``state[eid]`` here raised ``KeyError`` and took the socket
    down with it; restoring the pane would have brought the env back into a
    listing the delete had already announced it out of.
    """
    spy_store.save_env("expt", env_payload())
    push_deleted(spy_store, "expt", "win_1", {"id": "win_1"})
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})
    handler.storage_executor = storage_worker

    race_with_delete(handler, spy_store, cmd="undo", eid="expt")

    assert "expt" not in handler.state
    assert not spy_store.env_exists("expt")
    assert count_deleted(spy_store, "expt") == 0


def test_socket_save_racing_a_delete_of_its_source_writes_nothing(spy_store, env_path):
    """Saving under a new id stops when the env it is copying is deleted.

    The delete is settled while the read is held open, so the source is gone
    from disk as well as from ``state`` by the time the copy resumes.
    """
    spy_store.save_env("cold", env_payload("w1"))
    handler = socket_handler(
        spy_store, env_path, {"cold": LazyEnvData(spy_store, "cold")}
    )

    async def main():
        with read_held_open(spy_store, "cold") as (reading, finish):
            command = asyncio.ensure_future(
                AnySocketHandlerOrWrapper.on_message(
                    handler,
                    json.dumps(
                        {"cmd": "save", "eid": "copy", "prev_eid": "cold", "data": {}}
                    ),
                )
            )
            await asyncio.to_thread(reading.wait, 10)
            removal = DeleteEnvHandler.wrap_func(handler, {"eid": "cold"})
            if removal is not None:
                await removal
            finish.set()
            await command

    asyncio.run(main())

    assert "copy" not in handler.state
    assert "copy" not in spy_store.calls["save_env"]


def test_web_fork_racing_a_delete_of_its_source_is_a_bad_request(spy_store, env_path):
    """A fork whose source is deleted mid-read answers as if it never existed.

    The delete is settled while the read is held open, so the read comes back
    empty; answering 400 rather than raising out of the empty read is the whole
    point of the guard this covers.
    """
    spy_store.save_env("cold", env_payload("w1"))
    handler = FakeHandler(
        state={"cold": LazyEnvData(spy_store, "cold")},
        storage=spy_store,
        env_path=env_path,
    )

    async def main():
        with read_held_open(spy_store, "cold") as (reading, finish):
            fork = asyncio.ensure_future(
                ForkEnvHandler.wrap_func(handler, {"prev_eid": "cold", "eid": "copy"})
            )
            await asyncio.to_thread(reading.wait, 10)
            removal = DeleteEnvHandler.wrap_func(handler, {"eid": "cold"})
            if removal is not None:
                await removal
            finish.set()
            with pytest.raises(tornado.web.HTTPError):
                await fork

    asyncio.run(main())

    assert "copy" not in handler.state
    assert "copy" not in spy_store.calls["save_env"]


def test_a_read_that_outlives_a_delete_does_not_relist_the_env(
    spy_store, env_path, storage_worker
):
    """An env read for a browser is not filed back under a delete that beat it.

    Reading it inline left no window for this; reading it on the worker means
    the read can resolve after the delete has already dropped the env, and
    filing it away then put it back in the environment list for good.
    """
    spy_store.save_env("expt", env_payload())
    handler = FakeHandler(state={}, storage=spy_store, env_path=env_path)
    handler.storage_executor = storage_worker

    race_read_with_delete(handler, spy_store, "expt", lambda: warm_env(handler, "expt"))

    assert "expt" not in handler.state
    assert spy_store.list_envs() == []


async def serve_env(handler, eid, socket):
    """The two steps ``EnvHandler.post`` takes to hand an env to a browser."""
    undo_count = await warm_env(handler, eid)
    load_env(handler.state, eid, socket, handler.storage, undo_count, warmed=True)


def test_serving_an_env_deleted_mid_read_does_not_relist_it(
    spy_store, env_path, storage_worker
):
    """Neither half of serving an env may file a deleted one back into state.

    ``warm_env`` declines to store what it read once the delete is in flight,
    and the send that follows it must not undo that by reading the env again
    itself -- a read on the loop, and one that lands past the guard.
    """
    spy_store.save_env("expt", env_payload())
    handler = FakeHandler(state={}, storage=spy_store, env_path=env_path)
    handler.storage_executor = storage_worker
    sub = handler.add_sub(eid="expt")

    race_read_with_delete(
        handler, spy_store, "expt", lambda: serve_env(handler, "expt", sub)
    )

    assert "expt" not in handler.state
    assert spy_store.list_envs() == []


def test_a_warmed_send_does_not_read_the_env_again(spy_store, env_path):
    """The env was read on the worker, so the send makes no read of its own."""
    spy_store.save_env("expt", env_payload())
    state = {}
    spy_store.calls["load_env"] = []

    load_env(state, "expt", FakeSocket(), spy_store, undo_count=0, warmed=True)

    assert spy_store.calls["load_env"] == []
    assert "expt" not in state


def test_a_warmed_comparison_does_not_read_the_envs_again(spy_store, env_path):
    """Comparison warms every env it names, so it reads none of them twice."""
    spy_store.save_env("expt", env_payload())
    state = {}
    spy_store.calls["load_env"] = []

    compare_envs(state, ["expt"], FakeSocket(), spy_store, warmed=True)

    assert spy_store.calls["load_env"] == []
    assert "expt" not in state


def test_socket_delete_env_finishes_only_once_the_files_are_gone(
    spy_store, env_path, storage_worker
):
    """The command answers for the removal rather than merely starting it.

    The polling bridge replies by returning from ``on_message``, so a client
    told its env was deleted would otherwise be free to list it again. The
    worker has to be one of ours: ``asyncio.run`` drains the loop's own
    executor on the way out, which would settle the removal either way.
    """
    spy_store.save_env("expt", env_payload())
    push_deleted(spy_store, "expt", "win_0", {"id": "win_0"})
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})
    handler.storage_executor = storage_worker
    unhurried = SpyStore.delete_env

    def slow_delete_env(store, eid):
        """Long enough that a removal merely started is still unfinished."""
        time.sleep(0.05)
        return unhurried(store, eid)

    with mock.patch.object(SpyStore, "delete_env", slow_delete_env):
        dispatch(handler, cmd="delete_env", eid="expt")

    assert not spy_store.env_exists("expt")
    assert count_deleted(spy_store, "expt") == 0


def test_delete_env_outlasts_a_close_already_queued(spy_store, env_path):
    """A pane closed a moment earlier cannot leave undo history behind.

    Both jobs land on one storage worker in submission order, so the close's
    ``push_deleted`` runs *first* and writes the stack. Clearing it on the loop
    therefore cleared nothing: the push put the file back, ``delete_env``
    removes the env file and nothing else, and the stack outlived the
    environment for the next env to reuse the id and undo panes out of.
    """
    spy_store.save_env("expt", env_payload())
    handler = FakeHandler(
        state={"expt": env_payload()}, storage=spy_store, env_path=env_path
    )

    async def close_then_delete():
        with ThreadPoolExecutor(max_workers=1) as worker:
            handler.storage_executor = worker
            close = push_deleted_off_loop(handler, "expt", "win_0", {"id": "win_0"})
            removal = DeleteEnvHandler.wrap_func(handler, {"eid": "expt"})
            await close
            await removal

    asyncio.run(close_then_delete())

    assert spy_store.calls["save_undo"] == ["expt"]
    assert count_deleted(spy_store, "expt") == 0
    assert not spy_store.env_exists("expt")


def test_delete_env_clears_the_undo_history_before_the_file(spy_store, env_path):
    """Within the one task, the stack goes first, so a failed unlink of the env
    still leaves nothing to undo it with."""
    spy_store.save_env("expt", env_payload())
    push_deleted(spy_store, "expt", "win_0", {"id": "win_0"})

    purge_env(spy_store, "expt")

    order = [method for method, _thread in spy_store.threads]
    assert order.index("clear_undo") < order.index("delete_env")
    assert count_deleted(spy_store, "expt") == 0
    assert not spy_store.env_exists("expt")


def test_socket_save_writes_the_new_env_off_the_loop(spy_store, env_path):
    """Saving under a new id persists the copy without blocking the loop."""
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})

    loop_thread = dispatch(handler, cmd="save", eid="copy", prev_eid="expt", data={})

    assert spy_store.calls["save_env"] == ["copy"]
    assert_off_loop(spy_store, loop_thread, {"save_env"})


def test_save_env_off_loop_hands_the_worker_a_snapshot(inline_executor):
    """The worker is given a copy, never the env the loop keeps mutating."""
    storage = mock.Mock()
    handler = FakeHandler(state={"expt": env_payload()}, storage=storage)
    live = handler.state["expt"]

    save_env_off_loop(handler, "expt")

    func, (eid, handed) = inline_executor[0]
    assert func == storage.save_env
    assert eid == "expt"
    assert handed is not live
    assert handed["jsons"] is not live["jsons"]
    assert handed == dict(live)


def test_save_env_off_loop_snapshot_ignores_later_mutations(inline_executor):
    """What reaches disk is the env as it was when the save was asked for."""
    captured = {}
    handler = FakeHandler(state={"expt": env_payload()}, storage=mock.Mock())

    def capture(eid, env):
        captured["panes"] = sorted(env["jsons"])
        handler.state["expt"]["jsons"]["win_late"] = {"id": "win_late"}

    handler.storage.save_env = capture
    save_env_off_loop(handler, "expt")

    assert captured["panes"] == sorted(env_payload()["jsons"])
    assert "win_late" in handler.state["expt"]["jsons"]


def test_socket_save_reads_a_cold_source_env_off_the_loop(spy_store, env_path):
    """A cold source is materialised first, so the copy has data to write.

    Copying the ``LazyEnvData`` itself carried the source's id rather than its
    panes, leaving the new env answering to the file it was copied from.
    """
    spy_store.save_env("cold", env_payload("w1"))
    handler = socket_handler(
        spy_store, env_path, {"cold": LazyEnvData(spy_store, "cold")}
    )

    loop_thread = dispatch(handler, cmd="save", eid="copy", prev_eid="cold", data={})

    assert_off_loop(spy_store, loop_thread, {"load_env"})
    assert spy_store.load_env("copy")["jsons"] == env_payload("w1")["jsons"]


def test_socket_save_layouts_writes_the_snapshot_off_the_loop(app_factory):
    """Layouts are written on the worker, from the blob read on the loop.

    The spy has to be the store the app builds for itself: ``ServerState``
    takes its own reference at construction, so a store swapped in afterwards
    would be observed by nobody.
    """
    with mock.patch("visdom.server.app.JSONStore", SpyStore):
        app = app_factory()
    spy_store = app.storage
    sub = open_sub(app)
    loop_thread = {}

    async def main():
        loop_thread["name"] = threading.current_thread().name
        await sub.on_message(json.dumps({"cmd": "save_layouts", "data": '[["v", {}]]'}))

    asyncio.run(main())

    assert app.layouts == '[["v", {}]]'
    assert spy_store.calls["save_layouts"] == ['[["v", {}]]']
    assert_off_loop(spy_store, loop_thread["name"], {"save_layouts"})


def test_save_layouts_writes_what_it_was_handed(app_factory):
    """The worker writes the snapshot it was given, not a later edit."""
    with mock.patch("visdom.server.app.JSONStore", SpyStore):
        app = app_factory()
    app.layouts = '[["newer", {}]]'

    app.save_layouts('[["older", {}]]')

    assert app.storage.calls["save_layouts"] == ['[["older", {}]]']


def test_each_workspace_refreshes_its_own_hparams_panes(app):
    pane = {"type": "hparams", "hparams": {"mode": "env_ids", "env_ids": ["run-1"]}}
    space = app.workspace_env_manager.space("ws-a")
    space.state["board"] = {"jsons": {"theirs": pane}, "reload": {}}
    app.server_state.state["board"] = {"jsons": {"ours": pane}, "reload": {}}

    assert space.live_updates is not app.server_state.live_updates
    assert space.live_updates._resolve({"run-1"}) == [("board", "theirs")]
    assert app.server_state.live_updates._resolve({"run-1"}) == [("board", "ours")]
