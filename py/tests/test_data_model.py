"""Unit tests for the data_model storage layer.

Exercises the JSONStore backend directly against a temporary directory: no
running visdom server is needed, so these run under ``pytest -m "not server"``.
"""

import json
import os
import tempfile
import unittest

from visdom.data_model import JSONStore, DataStore


def _env(win_id="win_0"):
    """Build a minimal environment payload (one window) for use in tests."""
    return {"jsons": {win_id: {"id": win_id}}, "reload": {}}


class TestJSONStore(unittest.TestCase):
    """JSONStore behaviour when persistence is enabled (a real env_path)."""

    def setUp(self):
        """Give each test a fresh, isolated temp directory as the env_path."""
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = self._tmp.name
        self.backend = JSONStore(self.env_path)

    def tearDown(self):
        """Remove the temp directory after each test."""
        self._tmp.cleanup()

    def test_is_a_data_store(self):
        """JSONStore satisfies the DataStore interface."""
        self.assertIsInstance(self.backend, DataStore)

    def test_save_then_load_round_trip(self):
        """A saved environment is read back unchanged."""
        env = _env()
        self.assertTrue(self.backend.save_env("main", env))
        self.assertEqual(self.backend.load_env("main"), env)

    def test_save_writes_expected_file(self):
        """save_env writes the env to <env_path>/<eid>.json on disk."""
        self.backend.save_env("main", _env())
        expected = os.path.join(self.env_path, "main.json")
        self.assertTrue(os.path.exists(expected))
        with open(expected) as fn:
            self.assertEqual(json.load(fn), _env())

    def test_load_missing_env_returns_empty(self):
        """Loading an environment that was never saved returns {}."""
        self.assertEqual(self.backend.load_env("nope"), {})

    def test_env_exists(self):
        """env_exists reflects whether the environment is on disk."""
        self.assertFalse(self.backend.env_exists("main"))
        self.backend.save_env("main", _env())
        self.assertTrue(self.backend.env_exists("main"))

    def test_list_envs(self):
        """list_envs returns the ids of all saved environments."""
        self.assertEqual(self.backend.list_envs(), [])
        self.backend.save_env("main", _env())
        self.backend.save_env("other", _env())
        self.assertEqual(sorted(self.backend.list_envs()), ["main", "other"])

    def test_list_ignores_subdirs(self):
        """A view/layouts.json side-file is not mistaken for an environment."""
        os.mkdir(os.path.join(self.env_path, "view"))
        with open(os.path.join(self.env_path, "view", "layouts.json"), "w") as fn:
            fn.write("{}")
        self.backend.save_env("main", _env())
        self.assertEqual(self.backend.list_envs(), ["main"])

    def test_delete_env(self):
        """delete_env removes the env and reports False when nothing to remove."""
        self.backend.save_env("main", _env())
        self.assertTrue(self.backend.delete_env("main"))
        self.assertFalse(self.backend.env_exists("main"))
        self.assertFalse(self.backend.delete_env("main"))

    def test_save_envs_saves_named_subset(self):
        """save_envs persists only the named subset of state."""
        state = {"main": _env(), "other": _env()}
        ret = self.backend.save_envs(state, ["main"])
        self.assertEqual(ret, ["main"])
        self.assertTrue(self.backend.env_exists("main"))
        self.assertFalse(self.backend.env_exists("other"))

    def test_save_envs_drops_unknown_ids(self):
        """save_envs ignores ids that aren't present in state."""
        state = {"main": _env()}
        ret = self.backend.save_envs(state, ["main", "ghost"])
        self.assertEqual(ret, ["main"])

    def test_save_all_saves_everything(self):
        """save_all persists every environment in state."""
        state = {"main": _env(), "other": _env()}
        ret = self.backend.save_all(state)
        self.assertEqual(sorted(ret), ["main", "other"])
        self.assertEqual(self.backend.load_env("main"), _env())

    def test_env_named_like_hash_is_not_misread(self):
        """An env named 'hash_results' is not treated as a hash_<64hex> file."""
        self.backend.save_env("hash_results", _env())
        self.assertEqual(self.backend.list_envs(), ["hash_results"])

    def test_long_name_hash_fallback_round_trips(self):
        """An over-long env name uses the hash_<sha256>.json fallback and still round-trips."""
        long_eid = "e" * 5000
        self.backend.save_env(long_eid, _env())
        self.assertEqual(self.backend.list_envs(), [long_eid])
        self.assertTrue(self.backend.env_exists(long_eid))
        loaded = self.backend.load_env(long_eid)
        self.assertEqual(loaded["jsons"], _env()["jsons"])

    def test_save_ignores_path_traversal_ids(self):
        """A crafted id like '../evil' cannot write outside env_path."""
        parent = os.path.dirname(self.env_path)
        before = set(os.listdir(parent))
        for eid in ("../evil", "subdir/../evil", "/etc/evil"):
            self.backend.save_env(eid, _env())
            self.assertEqual(set(os.listdir(parent)) - before, set())
            base = os.path.abspath(self.env_path)
            for name in os.listdir(self.env_path):
                resolved = os.path.abspath(os.path.join(self.env_path, name))
                self.assertTrue(resolved.startswith(base + os.sep))

    def test_traversal_id_round_trips_within_env_path(self):
        """A crafted id is sanitised consistently across save/exists/list/load."""
        self.backend.save_env("../evil", _env())
        self.assertTrue(self.backend.env_exists("../evil"))
        self.assertEqual(self.backend.list_envs(), [".._evil"])
        self.assertEqual(self.backend.load_env("../evil"), _env())

    def test_list_skips_unreadable_hash_files(self):
        """Malformed hash_<64>.json files are ignored, not raised, by list_envs."""
        hex64 = "a" * 64
        with open(
            os.path.join(self.env_path, "hash_{0}.json".format(hex64)), "w"
        ) as fn:
            fn.write("{not valid json")
        with open(
            os.path.join(self.env_path, "hash_{0}.json".format("b" * 64)), "w"
        ) as fn:
            fn.write(json.dumps({"jsons": {}, "reload": {}}))
        self.backend.save_env("main", _env())
        self.assertEqual(self.backend.list_envs(), ["main"])


class TestJSONStoreNoPath(unittest.TestCase):
    """JSONStore(None): persistence disabled (in-memory-only mode)."""

    def setUp(self):
        """Create a store with no env_path so all persistence is a no-op."""
        self.backend = JSONStore(None)

    def test_save_env_is_noop(self):
        """save_env persists nothing and reports False."""
        self.assertFalse(self.backend.save_env("main", _env()))

    def test_save_envs_is_noop(self):
        """save_envs persists nothing and returns an empty list."""
        self.assertEqual(self.backend.save_envs({"main": _env()}, ["main"]), [])

    def test_save_all_is_noop(self):
        """save_all persists nothing and returns an empty list."""
        self.assertEqual(self.backend.save_all({"main": _env()}), [])

    def test_load_returns_empty(self):
        """load_env returns {} when persistence is disabled."""
        self.assertEqual(self.backend.load_env("main"), {})

    def test_list_returns_empty(self):
        """list_envs returns [] when persistence is disabled."""
        self.assertEqual(self.backend.list_envs(), [])

    def test_exists_is_false(self):
        """env_exists is always False when persistence is disabled."""
        self.assertFalse(self.backend.env_exists("main"))

    def test_delete_is_noop(self):
        """delete_env removes nothing and reports False."""
        self.assertFalse(self.backend.delete_env("main"))


if __name__ == "__main__":
    unittest.main()
