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
    DeleteEnvHandler,
    ForkEnvHandler,
    SaveHandler,
)
from visdom.utils.server_utils import (
    LazyEnvData,
    clear_deleted,
    compare_envs,
    count_deleted,
    gather_envs,
    ensure_env_loaded,
    load_env,
    pop_deleted,
    push_deleted,
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
    assert gather_envs(handler.state, spy_store) == []


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
    assert gather_envs(handler.state, spy_store) == []


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


def test_socket_save_writes_the_new_env_off_the_loop(spy_store, env_path):
    """Saving under a new id persists the copy without blocking the loop."""
    handler = socket_handler(spy_store, env_path, {"expt": env_payload()})

    loop_thread = dispatch(handler, cmd="save", eid="copy", prev_eid="expt", data={})

    assert spy_store.calls["save_env"] == ["copy"]
    assert_off_loop(spy_store, loop_thread, {"save_env"})


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
