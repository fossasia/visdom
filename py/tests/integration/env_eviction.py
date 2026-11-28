#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Idle environments are dropped from memory once they are safely on disk.

Every environment a client opened or wrote to used to stay in ``state`` until it
was deleted or the server restarted, so a long-lived server only ever grew.
``-env_idle_seconds`` lets a saved, untouched environment fall back to the cold
``LazyEnvData`` it was at startup. What matters is what must *not* be dropped:
anything unsaved, being written or deleted, or with nothing on disk to read back.
"""

import asyncio
import inspect
import json
import os
import threading

import pytest

from testutils import open_sub
from visdom.server.handlers import experiments_handler, socket_handlers
from visdom.server import run_server
from visdom.server.app import Application
from visdom.utils import server_utils
from visdom.utils.server_utils import LazyEnvData, hold_envs, save_env_off_loop

pytestmark = pytest.mark.integration

IDLE = 60


def _write_env(env_path, eid, value):
    with open(os.path.join(env_path, "%s.json" % eid), "w") as fn:
        json.dump({"jsons": {"w": {"v": value}}, "reload": {}}, fn)


def _make_app(env_path, idle=IDLE, **kwargs):
    return Application(port=8097, env_path=env_path, env_idle_seconds=idle, **kwargs)


def _sweep(owner):
    return asyncio.run(owner.evict_idle_envs())


def _age(app, eid, seconds=IDLE + 1):
    """Make ``eid`` look untouched for ``seconds``."""
    state = app.server_state
    env = dict.get(app.state, eid)
    if isinstance(env, LazyEnvData):
        env.last_access -= seconds
    for stamps in (state.last_dirty, app.state.accessed):
        if eid in stamps:
            stamps[eid] -= seconds


def test_loaded_lazy_env_is_unloaded_when_idle(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    assert app.state["a"]["jsons"]["w"]["v"] == 1
    assert app.state["a"].is_loaded

    _age(app, "a")
    assert _sweep(app.server_state) == ["a"]
    assert not app.state["a"].is_loaded

    # Reading it again brings it back from disk, unchanged.
    assert app.state["a"]["jsons"]["w"]["v"] == 1
    assert app.state["a"].is_loaded


def test_recently_used_env_stays_loaded(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    app.state["a"]["jsons"]
    assert _sweep(app.server_state) == []
    assert app.state["a"].is_loaded


def test_reading_resets_the_idle_clock(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    app.state["a"]["jsons"]
    _age(app, "a")
    app.state["a"]["jsons"]  # a viewer reads it just before the sweep
    assert _sweep(app.server_state) == []


def test_reading_a_plain_dict_env_resets_its_idle_clock(env_path):
    app = _make_app(env_path)
    app.state["made"] = {"jsons": {}, "reload": {}}
    app.storage.save_env("made", app.state["made"])
    _age(app, "made")
    app.state.get("made")  # read, never written again
    assert _sweep(app.server_state) == []
    assert isinstance(app.state["made"], dict)


def test_prime_counts_as_a_use(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    _age(app, "a")  # cold, and its last use is long ago
    app.state["a"].prime({"jsons": {}, "reload": {}})
    assert _sweep(app.server_state) == []


def test_disabled_by_default_evicts_nothing(env_path):
    _write_env(env_path, "a", 1)
    app = Application(port=8097, env_path=env_path)
    assert app.server_state.env_idle_seconds == 0
    app.state["a"]["jsons"]
    _age(app, "a", 10**6)
    assert _sweep(app.server_state) == []
    assert app.state["a"].is_loaded


def test_dirty_env_is_never_evicted(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    app.state["a"]["jsons"]["w"]["v"] = 2
    app.server_state.dirty_envs["a"] += 1  # changed, not yet written
    _age(app, "a")
    assert _sweep(app.server_state) == []
    assert app.state["a"]["jsons"]["w"]["v"] == 2


def test_env_being_saved_or_deleted_is_not_evicted(env_path):
    for eid in ("saving", "deleting"):
        _write_env(env_path, eid, 1)
    app = _make_app(env_path)
    for eid in ("saving", "deleting"):
        app.state[eid]["jsons"]
        _age(app, eid)
    app.server_state.saving_envs.add("saving")
    app.server_state.deleting_envs["deleting"] = 1
    assert _sweep(app.server_state) == []


def test_env_without_a_file_is_not_evicted(env_path):
    app = _make_app(env_path)
    app.state["fresh"] = {"jsons": {"w": 1}, "reload": {}}
    _age(app, "fresh")
    assert _sweep(app.server_state) == []
    assert isinstance(app.state["fresh"], dict)


def test_plain_dict_env_written_this_session_is_evicted_once_saved(env_path):
    app = _make_app(env_path)
    app.state["made"] = {"jsons": {"w": {"v": 5}}, "reload": {}}
    app.server_state.mark_dirty("made")
    app.storage.save_env("made", app.state["made"])
    app.server_state.dirty_envs.clear()  # what a completed autosave does
    _age(app, "made")

    assert "made" in _sweep(app.server_state)
    assert isinstance(app.state["made"], LazyEnvData)
    assert not app.state["made"].is_loaded
    assert app.state["made"]["jsons"]["w"]["v"] == 5


def test_env_saved_without_mark_dirty_is_still_evicted(env_path):
    """Uploads and forks save directly and never mark the env dirty."""
    app = _make_app(env_path)
    app.state["forked"] = {"jsons": {"w": {"v": 3}}, "reload": {}}
    app.storage.save_env("forked", app.state["forked"])
    _age(app, "forked")
    assert _sweep(app.server_state) == ["forked"]


def test_eager_loaded_env_nobody_asked_for_stays_resident(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path, eager_data_loading=True)
    assert _sweep(app.server_state) == []
    assert isinstance(app.state["a"], dict)


def test_write_after_eviction_reloads_and_persists(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    app.state["a"]["jsons"]
    _age(app, "a")
    _sweep(app.server_state)

    app.state["a"]["jsons"]["w"]["v"] = 9
    app.storage.save_env("a", app.state["a"])
    with open(os.path.join(env_path, "a.json")) as fn:
        assert json.load(fn)["jsons"]["w"]["v"] == 9


def test_env_used_while_the_file_check_runs_is_kept(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    state = app.server_state
    app.state["a"]["jsons"]
    _age(app, "a")
    real = state._existing_envs

    def touched_meanwhile(eids):
        present = real(eids)
        state.dirty_envs["a"] += 1  # a write lands while the worker checks
        return present

    state._existing_envs = touched_meanwhile
    assert _sweep(state) == []
    assert app.state["a"].is_loaded


def test_failed_file_check_evicts_nothing(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    app.state["a"]["jsons"]
    _age(app, "a")

    def broken(eids):
        raise OSError("storage unavailable")

    app.server_state._existing_envs = broken
    assert _sweep(app.server_state) == []
    assert app.state["a"].is_loaded


def test_application_sweep_covers_the_default_state(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    app.state["a"]["jsons"]
    _age(app, "a")
    assert _sweep(app) == ["a"]


def test_start_env_eviction_only_runs_when_enabled(env_path):
    off = _make_app(env_path, idle=0)
    assert off.start_env_eviction() is None
    on = _make_app(env_path)
    try:
        timer = on.start_env_eviction()
        assert timer is not None and timer.is_running()
    finally:
        on.server_state.stop_env_eviction()


def test_env_idle_seconds_cannot_shift_existing_positional_arguments():
    for func in (run_server.start_server, run_server._serve):
        params = list(inspect.signature(func).parameters)
        assert params[-1] == "env_idle_seconds"


class _Handler:
    """The slice of a handler the direct-save helpers use."""

    def __init__(self, app):
        self.state = app.state
        self.storage = app.storage
        self.dirty_envs = app.server_state.dirty_envs
        self.held_envs = app.server_state.held_envs
        self.storage_executor = None


def _direct_save(handler, eid):
    async def run():
        return await save_env_off_loop(handler, eid)

    return asyncio.run(run())


def test_direct_save_holds_the_env_dirty_until_it_lands(env_path):
    app = _make_app(env_path)
    handler = _Handler(app)
    app.state["forked"] = {"jsons": {"w": {"v": 3}}, "reload": {}}
    _direct_save(handler, "forked")
    assert "forked" not in app.server_state.dirty_envs
    assert "forked" not in app.server_state.held_envs


def test_failed_direct_save_keeps_the_env_dirty_and_resident(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    handler = _Handler(app)
    app.state["a"] = {"jsons": {"w": {"v": 2}}, "reload": {}}  # newer than disk

    def broken(eid, env):
        raise OSError("disk full")

    handler.storage = type("S", (), {"save_env": staticmethod(broken)})()
    with pytest.raises(OSError):
        _direct_save(handler, "a")

    assert app.server_state.dirty_envs["a"] == 1  # a real mark, for autosave
    assert "a" not in app.server_state.held_envs
    _age(app, "a")
    assert _sweep(app.server_state) == []
    assert app.state["a"]["jsons"]["w"]["v"] == 2


def test_held_env_is_not_evicted_until_released(env_path):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    handler = _Handler(app)
    app.state["a"]["jsons"]
    _age(app, "a")
    with hold_envs(handler, ["a"]):
        assert _sweep(app.server_state) == []
    assert _sweep(app.server_state) == ["a"]


def test_direct_save_never_touches_the_autosave_counter(env_path):
    """The autosave settles its own marks; a second owner would be released twice."""
    app = _make_app(env_path)
    handler = _Handler(app)
    state = app.server_state
    seen = {}

    class Storage:
        def save_env(self, eid, env):
            seen["dirty"] = dict(state.dirty_envs)
            seen["held"] = dict(state.held_envs)
            return True

    handler.storage = Storage()
    app.state["a"] = {"jsons": {"w": 1}, "reload": {}}
    _direct_save(handler, "a")

    assert seen == {"dirty": {}, "held": {"a": 1}}  # mid-write: held, not dirty
    assert not state.dirty_envs and not state.held_envs  # settled cleanly


def test_declined_direct_save_is_not_marked_dirty(env_path):
    """No ``env_path`` means no write can ever land, so no retry is queued."""
    app = _make_app(env_path)
    handler = _Handler(app)

    class Declining:
        def save_env(self, eid, env):
            return False

    handler.storage = Declining()
    app.state["a"] = {"jsons": {}, "reload": {}}
    assert _direct_save(handler, "a") is False
    assert not app.server_state.dirty_envs
    assert not app.server_state.held_envs


def test_removed_env_takes_its_access_stamp_with_it(env_path):
    app = _make_app(env_path, idle=0)
    for eid in ("a", "b", "c"):
        app.state[eid] = {"jsons": {}, "reload": {}}
    app.state.pop("a")
    del app.state["b"]
    assert set(app.state.accessed) == {"c"}
    app.state.clear()
    assert app.state.accessed == {}


def test_write_times_are_not_kept_while_eviction_is_off(env_path):
    app = _make_app(env_path, idle=0)
    app.server_state.mark_dirty("main")
    assert app.server_state.last_dirty == {}


@pytest.mark.parametrize("idle", [-1, 1, 9])
def test_too_short_or_negative_idle_period_is_refused(env_path, idle):
    with pytest.raises(ValueError):
        _make_app(env_path, idle=idle)


@pytest.mark.parametrize("idle, expected", [(10, 2500), (120, 30000), (3600, 60000)])
def test_sweep_interval_tracks_the_idle_period(env_path, idle, expected):
    assert (
        _make_app(env_path, idle=idle).server_state.eviction_interval_ms() == expected
    )


@pytest.mark.parametrize("cmd", ["close", "undo"])
def test_sweep_while_socket_command_waits_for_undo_storage(env_path, monkeypatch, cmd):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    sock = open_sub(app)  # viewing main, so only the operation pins a
    worker = "push_deleted_off_loop" if cmd == "close" else "pop_deleted_off_loop"
    original = getattr(socket_handlers, worker)
    if cmd == "undo":
        app.storage.save_undo("a", [["restored", {"id": "restored"}]])

    async def sweep_during_io(*args):
        _age(app, "a")
        assert await app.server_state.evict_idle_envs() == []
        return await original(*args)

    monkeypatch.setattr(socket_handlers, worker, sweep_during_io)
    loop_thread = threading.get_ident()
    load = app.storage.load_env

    def check_worker(eid):
        assert threading.get_ident() != loop_thread
        return load(eid)

    monkeypatch.setattr(app.storage, "load_env", check_worker)
    asyncio.run(sock.on_message(json.dumps({"cmd": cmd, "eid": "a", "data": "w"})))
    panes = app.state["a"]["jsons"]
    if cmd == "close":
        assert "w" not in panes
    else:
        assert "restored" in panes
    assert not app.server_state.held_envs


@pytest.mark.parametrize("selection", ["a", ["main", "a"]])
def test_view_stays_resident_until_subscriber_leaves(env_path, selection):
    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    subscriber = open_sub(app)
    subscriber.eid = selection
    app.state["a"]["jsons"]
    _age(app, "a")
    assert _sweep(app.server_state) == []
    subscriber.eid = "main"
    assert _sweep(app.server_state) == ["a"]


def test_sweep_considers_only_touched_environments(env_path, monkeypatch):
    for eid in ("hot", "cold"):
        _write_env(env_path, eid, 1)
    app = _make_app(env_path)
    app.state["hot"]["jsons"]
    _age(app, "hot")

    def forbid_full_scan(*args):
        pytest.fail("sweep enumerated the entire environment state")

    for method in ("__iter__", "items", "keys", "values"):
        monkeypatch.setattr(type(app.state), method, forbid_full_scan)
    assert _sweep(app.server_state) == ["hot"]
    assert "hot" not in app.state.accessed


def test_hparams_refresh_keeps_destination_resident_during_selection(
    env_path, monkeypatch
):
    app = _make_app(env_path)
    handler = experiments_handler.LivePaneWriter(app.server_state)
    destination = {
        "jsons": {"hp": {"type": "hparams", "i": 0, "hparams": {}}},
        "reload": {},
    }
    app.state["dashboard"] = destination
    app.storage.save_env("dashboard", destination)

    async def select(handler, spec):
        _age(app, "dashboard")
        assert await app.server_state.evict_idle_envs() == []
        return {"records": []}

    monkeypatch.setattr(
        experiments_handler.ExperimentHparamsHandler,
        "_build_content_off_loop",
        staticmethod(select),
    )
    asyncio.run(
        experiments_handler.ExperimentHparamsUpdateHandler.wrap_func(
            handler, {"eid": "dashboard", "win": "hp"}
        )
    )
    assert app.storage.load_env("dashboard")["jsons"]["hp"]["content"] == {
        "records": []
    }
    assert not app.server_state.held_envs


@pytest.mark.parametrize("transport", ["socket", "http"])
def test_save_as_pins_a_cold_source_until_the_copy_is_ready(
    env_path, monkeypatch, transport
):
    from visdom.server.handlers.web_handlers import ForkEnvHandler

    _write_env(env_path, "a", 1)
    app = _make_app(env_path)
    read = server_utils.load_env_off_loop

    async def read_and_sweep(handler, eid):
        raw = await read(handler, eid)
        # A second reader can warm the same env while save-as is waiting.
        app.state[eid].prime(raw)
        _age(app, eid)
        assert await app.server_state.evict_idle_envs() == []
        return raw

    monkeypatch.setattr(server_utils, "load_env_off_loop", read_and_sweep)
    args = {"eid": "copy", "prev_eid": "a", "data": {}}
    if transport == "socket":
        asyncio.run(open_sub(app).on_message(json.dumps({"cmd": "save", **args})))
    else:
        writer = experiments_handler.LivePaneWriter(app.server_state)
        asyncio.run(ForkEnvHandler.wrap_func(writer, args))
    assert app.storage.load_env("copy")["jsons"] == {"w": {"v": 1}}
    assert not app.server_state.held_envs


def test_unrelated_metric_scan_does_not_keep_loaded_lazy_env_resident(env_path):
    from visdom.experiments.live import resolve_targets

    _write_env(env_path, "idle", 1)
    app = _make_app(env_path)
    app.state["idle"]["jsons"]
    _age(app, "idle")
    assert resolve_targets(app.state, {"other-run"}) == []
    assert _sweep(app.server_state) == ["idle"]


@pytest.mark.parametrize("edit_during_write", [False, True])
def test_explicit_save_clears_only_snapshotted_edits(env_path, edit_during_write):
    from visdom.server.handlers.web_handlers import SaveHandler

    app = _make_app(env_path, save_interval=0, save_threshold=0)
    handler = experiments_handler.LivePaneWriter(app.server_state)
    replies = []
    handler.write = replies.append
    app.state["a"] = {"jsons": {"w": 1}, "reload": {}}
    app.mark_dirty("a")

    async def run():
        request = asyncio.create_task(
            SaveHandler.wrap_func(handler, {"data": ["a", "a"]})
        )
        await asyncio.sleep(0)  # the request has submitted its snapshot
        if edit_during_write:
            app.state["a"]["jsons"]["w"] = 2
            app.mark_dirty("a")
        await request

    asyncio.run(run())
    assert "a" in json.loads(replies[0])
    assert app.storage.load_env("a")["jsons"]["w"] == 1
    assert app.server_state.dirty_envs["a"] == int(edit_during_write)
    _age(app, "a")
    assert _sweep(app.server_state) == ([] if edit_during_write else ["a"])


@pytest.mark.parametrize("automatic_first", [True, False])
def test_overlapping_saves_do_not_clear_the_same_edit_twice(env_path, automatic_first):
    app = _make_app(env_path, save_interval=0, save_threshold=0)
    writer = experiments_handler.LivePaneWriter(app.server_state)
    app.state["a"] = {"jsons": {"w": 1}, "reload": {}}
    app.mark_dirty("a")

    def manual():
        return server_utils.save_envs_off_loop(writer, ["a"])

    async def run():
        first, second = (
            (app.flush_dirty, manual) if automatic_first else (manual, app.flush_dirty)
        )
        earlier = first()
        app.state["a"]["jsons"]["w"] = 2
        app.mark_dirty("a")
        later = second()
        app.state["a"]["jsons"]["w"] = 3
        app.mark_dirty("a")
        await asyncio.gather(earlier, later)

    asyncio.run(run())
    assert app.storage.load_env("a")["jsons"]["w"] == 2
    assert app.server_state.dirty_envs["a"] == 1


def test_explicit_save_only_acknowledges_ids_returned_by_storage(env_path, monkeypatch):
    app = _make_app(env_path, save_interval=0, save_threshold=0)
    writer = experiments_handler.LivePaneWriter(app.server_state)
    for eid in ("written", "declined"):
        app.state[eid] = {"jsons": {}, "reload": {}}
        app.mark_dirty(eid)

    save = app.storage.save_envs
    monkeypatch.setattr(
        app.storage, "save_envs", lambda state, eids: save(state, ["written"])
    )

    async def run():
        return await server_utils.save_envs_off_loop(writer, ["declined", "written"])

    assert asyncio.run(run()) == ["written"]
    assert app.server_state.dirty_envs == {"declined": 1}
