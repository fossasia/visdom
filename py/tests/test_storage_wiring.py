"""
Tests that the server routes persistence through ``Application.storage``
(the DataStore backend) rather than calling ``serialize_env`` directly.

These guard the PR-#2 wiring: end-to-end save/fork/reload behavior is already
covered in ``test_environment_lifecycle``; here we assert the abstraction itself
is in place so a future refactor cannot silently bypass the backend.
"""

import json
import tempfile
import types
import unittest
from unittest import mock

from visdom.data_model.base import DataStore
from visdom.data_model.json_store import JSONStore
from visdom.server.app import Application
from visdom.server.handlers.web_handlers import SaveHandler
from visdom.utils.server_utils import LazyEnvData


def _env(win_id="win_0"):
    """Minimal environment payload (one window)."""
    return {"jsons": {win_id: {"id": win_id}}, "reload": {}}


class TestStorageWiring(unittest.TestCase):
    """PR #2: the server's save handlers route through ``Application.storage``."""

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

        written = []
        handler = types.SimpleNamespace(
            storage=self.app.storage, state=self.app.state, write=written.append
        )
        SaveHandler.wrap_func(handler, {"data": ["main"]})

        self.assertEqual(len(calls), 1)
        self.assertIn("main", calls[0])
        self.assertIn("main", json.loads(written[0]))


class _SpyStore(JSONStore):
    """JSONStore that records load-path calls while delegating to the real impl."""

    def __init__(self, env_path):
        super().__init__(env_path)
        self.calls = {"list_envs": 0, "load_env": []}

    def list_envs(self):
        self.calls["list_envs"] += 1
        return super().list_envs()

    def load_env(self, eid):
        self.calls["load_env"].append(eid)
        return super().load_env(eid)


class TestLoadStateWiring(unittest.TestCase):
    """PR #3: ``Application.load_state`` routes env discovery/reads through storage."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self, eid, env=None):
        JSONStore(self.env_path).save_env(eid, env if env is not None else _env())

    def test_saved_envs_load_into_state(self):
        self._seed("main")
        self._seed("expt", _env("w1"))
        app = Application(port=8097, env_path=self.env_path)
        self.assertIn("expt", app.state)
        self.assertEqual(dict(app.state["expt"]), _env("w1"))

    def test_lazy_by_default(self):
        self._seed("expt")
        app = Application(port=8097, env_path=self.env_path)
        self.assertIsInstance(app.state["expt"], LazyEnvData)
        self.assertEqual(app.state["expt"]["jsons"], _env()["jsons"])

    def test_eager_loads_plain_dicts(self):
        self._seed("expt")
        app = Application(port=8097, env_path=self.env_path, eager_data_loading=True)
        self.assertIsInstance(app.state["expt"], dict)
        self.assertEqual(app.state["expt"], _env())

    def test_load_state_routes_through_storage(self):
        self._seed("expt")
        with mock.patch("visdom.server.app.JSONStore", _SpyStore):
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


class TestLazyEnvDataBackend(unittest.TestCase):
    """``LazyEnvData`` reads through the DataStore and defers until first access."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._store = JSONStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defers_until_access_then_caches(self):
        self._store.save_env("main", _env())
        reads = []
        real_load = self._store.load_env

        def spy(eid):
            reads.append(eid)
            return real_load(eid)

        self._store.load_env = spy
        lazy = LazyEnvData(self._store, "main")
        self.assertEqual(reads, [])
        self.assertEqual(lazy["jsons"], _env()["jsons"])
        self.assertEqual(reads, ["main"])
        _ = lazy["reload"]
        self.assertEqual(reads, ["main"])

    def test_missing_env_raises_value_error(self):
        lazy = LazyEnvData(self._store, "does_not_exist")
        with self.assertRaises(ValueError):
            _ = lazy["jsons"]


if __name__ == "__main__":
    unittest.main()
