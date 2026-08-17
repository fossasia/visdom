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
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from visdom.data_model.base import DataStore
from visdom.data_model.json_store import JSONStore
from visdom.server.app import Application
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

from testutils.fakes import FakeHandler, FakeSocket, SpyStore
from testutils.payloads import env_payload


class TestStorageWiring(unittest.TestCase):
    """The server's save handlers route through ``Application.storage``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = self._tmp.name
        self.app = Application(port=8097, env_path=self.env_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_application_has_json_store(self):
        self.assertIsInstance(self.app.storage, DataStore)
        self.assertIsInstance(self.app.storage, JSONStore)
        self.assertEqual(self.app.storage.env_path, self.env_path)

    def test_save_routes_through_storage(self):
        calls = []
        real_save_envs = self.app.storage.save_envs

        def spy(state, eids):
            calls.append(list(eids))
            return real_save_envs(state, eids)

        self.app.storage.save_envs = spy

        handler = FakeHandler(state=self.app.state, storage=self.app.storage)
        SaveHandler.wrap_func(handler, {"data": ["main"]})

        self.assertEqual(len(calls), 1)
        self.assertIn("main", calls[0])
        self.assertIn("main", handler.json_body())


class TestLoadStateWiring(unittest.TestCase):
    """``Application.load_state`` routes env discovery/reads through storage."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self, eid, env=None):
        JSONStore(self.env_path).save_env(
            eid, env if env is not None else env_payload()
        )

    def test_saved_envs_load_into_state(self):
        self._seed("main")
        self._seed("expt", env_payload("w1"))
        app = Application(port=8097, env_path=self.env_path)
        self.assertIn("expt", app.state)
        self.assertEqual(dict(app.state["expt"]), env_payload("w1"))

    def test_lazy_by_default(self):
        self._seed("expt")
        app = Application(port=8097, env_path=self.env_path)
        self.assertIsInstance(app.state["expt"], LazyEnvData)
        self.assertEqual(app.state["expt"]["jsons"], env_payload()["jsons"])

    def test_eager_loads_plain_dicts(self):
        self._seed("expt")
        app = Application(port=8097, env_path=self.env_path, eager_data_loading=True)
        self.assertIsInstance(app.state["expt"], dict)
        self.assertEqual(app.state["expt"], env_payload())

    def test_eager_preserves_extra_env_keys(self):
        """Eager loading keeps env keys the server itself does not read.

        Experiment metadata lives under the env's ``experiment`` key, so
        dropping unknown keys here would lose it on the next full-env save.
        """
        experiment = {"env_id": "expt", "name": "run-1", "status": "running"}
        self._seed("expt", dict(env_payload("w1"), experiment=experiment))
        app = Application(port=8097, env_path=self.env_path, eager_data_loading=True)
        self.assertEqual(app.state["expt"]["experiment"], experiment)

    def test_load_state_routes_through_storage(self):
        self._seed("expt")
        with mock.patch("visdom.server.app.JSONStore", SpyStore):
            app = Application(port=8097, env_path=self.env_path)
        self.assertEqual(app.storage.calls["list_envs"], 1)
        self.assertEqual(app.storage.calls["load_env"], [])
        _ = app.state["expt"]["jsons"]
        self.assertIn("expt", app.storage.calls["load_env"])

    def test_none_path_is_in_memory(self):
        app = Application(port=8097, env_path=None)
        self.assertEqual(app.state, {"main": {"jsons": {}, "reload": {}}})

    def test_missing_main_is_created_and_persisted(self):
        app = Application(port=8097, env_path=self.env_path)
        self.assertIn("main", app.state)
        self.assertTrue(JSONStore(self.env_path).env_exists("main"))


class TestDeleteWiring(unittest.TestCase):
    """Env deletion routes through ``storage.delete_env`` (no direct FS)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = self._tmp.name
        self.store = JSONStore(self.env_path)

    def tearDown(self):
        self._tmp.cleanup()

    def _spy_delete(self):
        calls = []
        real = self.store.delete_env

        def spy(eid):
            calls.append(eid)
            return real(eid)

        self.store.delete_env = spy
        return calls

    def _handler(self, state, **extra):
        """A stand-in handler exposing only what the delete paths read."""
        return FakeHandler(
            state=state, storage=self.store, env_path=self.env_path, **extra
        )

    def test_web_delete_routes_through_storage(self):
        self.store.save_env("expt", env_payload())
        self.assertTrue(self.store.env_exists("expt"))
        calls = self._spy_delete()
        handler = self._handler({"expt": env_payload()})
        DeleteEnvHandler.wrap_func(handler, {"eid": "expt"})
        self.assertEqual(calls, ["expt"])
        self.assertNotIn("expt", handler.state)
        self.assertFalse(self.store.env_exists("expt"))
        self.assertFalse(os.path.exists(os.path.join(self.env_path, "expt.json")))

    def test_web_delete_protects_main(self):
        self.store.save_env("main", env_payload())
        calls = self._spy_delete()
        handler = self._handler({"main": env_payload()})
        DeleteEnvHandler.wrap_func(handler, {"eid": "main"})
        self.assertEqual(calls, [])
        self.assertTrue(self.store.env_exists("main"))

    def test_socket_delete_routes_through_storage(self):
        self.store.save_env("expt", env_payload())
        calls = self._spy_delete()
        fake = self._handler({"expt": env_payload()}, readonly=False)
        AnySocketHandlerOrWrapper.on_message(
            fake, json.dumps({"cmd": "delete_env", "eid": "expt"})
        )
        self.assertEqual(calls, ["expt"])
        self.assertNotIn("expt", fake.state)
        self.assertFalse(self.store.env_exists("expt"))


class TestLayoutWiring(unittest.TestCase):
    """``Application`` layout save/load route through ``storage``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = self._tmp.name
        self.app = Application(port=8097, env_path=self.env_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_and_load_route_through_storage(self):
        saved = []
        real_save = self.app.storage.save_layouts

        def spy(layouts):
            saved.append(layouts)
            return real_save(layouts)

        self.app.storage.save_layouts = spy
        self.app.layouts = '[["v", {}]]'
        self.app.save_layouts()
        self.assertEqual(saved, ['[["v", {}]]'])

        app2 = Application(port=8097, env_path=self.env_path)
        self.assertEqual(app2.layouts, '[["v", {}]]')

    def test_none_path_does_not_touch_storage(self):
        app = Application(port=8097, env_path=None)
        self.assertEqual(app.load_layouts(), "")


class TestUndoWiring(unittest.TestCase):
    """Undo helpers persist through the DataStore, not raw env_path I/O."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = JSONStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_push_then_pop_is_lifo(self):
        push_deleted(self.store, "expt", "win_0", {"id": "win_0"})
        push_deleted(self.store, "expt", "win_1", {"id": "win_1"})
        self.assertEqual(count_deleted(self.store, "expt"), 2)
        self.assertEqual(pop_deleted(self.store, "expt"), ("win_1", {"id": "win_1"}))
        self.assertEqual(pop_deleted(self.store, "expt"), ("win_0", {"id": "win_0"}))
        self.assertIsNone(pop_deleted(self.store, "expt"))

    def test_push_trims_to_max_history(self):
        for i in range(DEFAULT_MAX_UNDO_HISTORY + 3):
            push_deleted(self.store, "expt", f"win_{i}", {"id": f"win_{i}"})
        self.assertEqual(count_deleted(self.store, "expt"), DEFAULT_MAX_UNDO_HISTORY)
        win_id, _ = pop_deleted(self.store, "expt")
        self.assertEqual(win_id, f"win_{DEFAULT_MAX_UNDO_HISTORY + 2}")

    def test_clear_removes_history(self):
        push_deleted(self.store, "expt", "win_0", {"id": "win_0"})
        clear_deleted(self.store, "expt")
        self.assertEqual(count_deleted(self.store, "expt"), 0)

    def test_push_routes_through_store(self):
        saved = []
        real_save = self.store.save_undo

        def spy(eid, stack):
            saved.append((eid, list(stack)))
            return real_save(eid, stack)

        self.store.save_undo = spy
        push_deleted(self.store, "expt", "win_0", {"id": "win_0"})
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0][0], "expt")


class TestLazyEnvDataBackend(unittest.TestCase):
    """``LazyEnvData`` reads through the DataStore and defers until first access."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._store = JSONStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defers_until_access_then_caches(self):
        self._store.save_env("main", env_payload())
        reads = []
        real_load = self._store.load_env

        def spy(eid):
            reads.append(eid)
            return real_load(eid)

        self._store.load_env = spy
        lazy = LazyEnvData(self._store, "main")
        self.assertEqual(reads, [])
        self.assertEqual(lazy["jsons"], env_payload()["jsons"])
        self.assertEqual(reads, ["main"])
        _ = lazy["reload"]
        self.assertEqual(reads, ["main"])

    def test_missing_env_raises_value_error(self):
        lazy = LazyEnvData(self._store, "does_not_exist")
        with self.assertRaises(ValueError):
            _ = lazy["jsons"]


class TestReadHelperWiring(unittest.TestCase):
    """``load_env`` reads a cold env through the store, not raw env_path."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = SpyStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_env_reads_cold_env_through_store(self):
        JSONStore(self.store.env_path).save_env("expt", env_payload())
        state = {}
        socket = FakeSocket()
        load_env(state, "expt", socket, self.store)
        self.assertEqual(self.store.calls["load_env"], ["expt"])
        self.assertEqual(dict(state["expt"]), env_payload())

    def test_load_env_skips_store_when_already_in_state(self):
        state = {"expt": env_payload()}
        socket = FakeSocket()
        load_env(state, "expt", socket, self.store)
        self.assertEqual(self.store.calls["load_env"], [])

    def test_gather_envs_lists_through_store(self):
        JSONStore(self.store.env_path).save_env("on_disk", env_payload())
        items = gather_envs({"in_memory": env_payload()}, self.store)
        self.assertEqual(self.store.calls["list_envs"], 1)
        self.assertEqual(items, ["in_memory", "on_disk"])

    def test_gather_envs_in_memory_only(self):
        store = SpyStore(None)
        self.assertEqual(gather_envs({"main": env_payload()}, store), ["main"])

    def test_compare_envs_reads_cold_env_through_store(self):
        JSONStore(self.store.env_path).save_env("cold", env_payload())
        state = {"warm": env_payload("w1")}
        socket = FakeSocket()
        compare_envs(state, ["warm", "cold"], socket, self.store)
        self.assertEqual(self.store.calls["load_env"], ["cold"])
        self.assertIn("cold", state)


if __name__ == "__main__":
    unittest.main()
