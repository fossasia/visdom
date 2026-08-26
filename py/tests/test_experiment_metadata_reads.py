"""Tests for reading experiment metadata without materialising environments.

Searching means visiting every environment, and an environment carries all of
its window data — plot traces, encoded images — while its experiment metadata
is a few hundred bytes. Reading the former to reach the latter is expensive
once (the parse) and expensive forever (a ``LazyEnvData`` caches what it was
made to load, in the state the server keeps).

So the read path is a projection: :meth:`DataStore.load_experiment` returns the
blob alone, and ``ExperimentStore`` prefers the live env only when it is already
resident. These tests pin both halves — that the projection is correct, and that
a bulk read leaves untouched environments untouched.
"""

import json
import os
import shutil
import tempfile
import unittest

from visdom.data_model import JSONStore
from visdom.data_model.base import DataStore
from visdom.experiments import ExperimentStore
from visdom.utils.server_utils import LazyEnvData


class TestJSONStoreProjection(unittest.TestCase):
    """JSONStore.load_experiment returns the blob, or None, and never raises."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_meta_read_")
        self.store = JSONStore(self._tmp_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _write_raw(self, eid, payload):
        with open(os.path.join(self._tmp_dir, eid + ".json"), "w") as fn:
            fn.write(json.dumps(payload))

    def test_returns_the_logged_blob(self):
        ExperimentStore(self.store).log_experiment("run-a", params={"lr": 0.1})
        blob = self.store.load_experiment("run-a")
        self.assertEqual(blob["env_id"], "run-a")
        self.assertEqual(blob["params"][0]["key"], "lr")

    def test_returns_none_for_env_without_experiment(self):
        self.store.save_env("plain", {"jsons": {}, "reload": {}})
        self.assertIsNone(self.store.load_experiment("plain"))

    def test_returns_none_for_unknown_env(self):
        self.assertIsNone(self.store.load_experiment("never-existed"))

    def test_traversal_id_cannot_read_outside_env_path(self):
        """A crafted id names no experiment instead of reaching a parent file.

        The projection opens a file, so it is a path sink like ``load_env``:
        the id is escaped and the resolved path is checked against
        ``env_path`` before anything is read, which leaves ``../<name>``
        pointing at a sibling that does not exist rather than at the real file
        one directory up.
        """
        outside = os.path.join(os.path.dirname(self._tmp_dir), "outside_meta.json")
        with open(outside, "w") as fn:
            fn.write(json.dumps({"jsons": {}, "reload": {}, "experiment": {"a": 1}}))
        self.addCleanup(os.remove, outside)

        for eid in ("../outside_meta", "../../outside_meta", "/etc/passwd"):
            self.assertIsNone(self.store.load_experiment(eid))

    def test_returns_none_for_unreadable_file(self):
        self._write_raw("broken", {"jsons": {}, "reload": {}})
        with open(os.path.join(self._tmp_dir, "broken.json"), "w") as fn:
            fn.write("{not json")
        self.assertIsNone(self.store.load_experiment("broken"))

    def test_returns_none_when_blob_is_not_an_object(self):
        self._write_raw("odd", {"jsons": {}, "reload": {}, "experiment": "nope"})
        self.assertIsNone(self.store.load_experiment("odd"))

    def test_agrees_with_load_env(self):
        ExperimentStore(self.store).log_experiment("run-b", params={"lr": 0.2})
        self.assertEqual(
            self.store.load_experiment("run-b"),
            self.store.load_env("run-b")["experiment"],
        )

    def test_projection_ignores_window_data(self):
        """An env full of windows still yields only its metadata."""
        store = ExperimentStore(self.store)
        store.log_experiment("run-c", params={"lr": 0.3})
        env = self.store.load_env("run-c")
        env["jsons"] = {"win": {"content": "x" * 10000}}
        self.store.save_env("run-c", env)
        blob = self.store.load_experiment("run-c")
        self.assertEqual(blob["env_id"], "run-c")
        self.assertNotIn("jsons", blob)


class TestInterfaceRequiresTheProjection(unittest.TestCase):
    """Every backend answers load_experiment itself; the interface has no default.

    A default reading through ``load_env`` would be inherited silently by a
    backend that reads whole environments — the one thing the projection exists
    to avoid — and would look correct until someone measured it.
    """

    def test_load_experiment_is_abstract(self):
        self.assertIn("load_experiment", DataStore.__abstractmethods__)


class TestLiveEnvsAreNotMaterialised(unittest.TestCase):
    """A bulk read leaves lazily-loaded envs lazy."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_meta_lazy_")
        self.backing = JSONStore(self._tmp_dir)
        seed = ExperimentStore(self.backing)
        for i in range(5):
            eid = "run-%d" % i
            seed.log_experiment(eid, params={"lr": 0.1 * i})
            env = self.backing.load_env(eid)
            env["jsons"] = {"win": {"content": "x" * 5000}}
            self.backing.save_env(eid, env)
        self.state = {
            eid: LazyEnvData(self.backing, eid) for eid in self.backing.list_envs()
        }
        self.store = ExperimentStore(self.backing, env_provider=self.state.get)

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _loaded(self):
        return [eid for eid, env in self.state.items() if env.is_loaded]

    def test_search_materialises_nothing(self):
        found = self.store.search(query="lr < 0.25")
        self.assertEqual(sorted(e.env_id for e in found), ["run-0", "run-1", "run-2"])
        self.assertEqual(self._loaded(), [])

    def test_get_experiment_materialises_nothing(self):
        self.assertIsNotNone(self.store.get_experiment("run-3"))
        self.assertEqual(self._loaded(), [])

    def test_iter_experiments_materialises_nothing(self):
        self.assertEqual(len(list(self.store.iter_experiments())), 5)
        self.assertEqual(self._loaded(), [])

    def test_results_match_a_store_reading_only_disk(self):
        """The env_provider must not change what a search finds, only its cost."""
        disk_only = ExperimentStore(self.backing)
        self.assertEqual(
            [e.env_id for e in self.store.search(query="lr > 0.15")],
            [e.env_id for e in disk_only.search(query="lr > 0.15")],
        )

    def test_a_resident_env_still_wins(self):
        """An env already in memory may hold changes the file has not seen."""
        live = self.state["run-4"]
        live["experiment"] = dict(live["experiment"], name="renamed-in-memory")
        self.assertTrue(live.is_loaded)
        self.assertEqual(self.store.get_experiment("run-4").name, "renamed-in-memory")

    def test_writes_still_go_through_the_live_env(self):
        """Logging keeps writing into the object the server is serving."""
        self.store.log_experiment("run-0", params={"momentum": 0.9})
        self.assertTrue(self.state["run-0"].is_loaded)
        self.assertEqual(
            self.state["run-0"]["experiment"]["params"][-1]["key"], "momentum"
        )


if __name__ == "__main__":
    unittest.main()
