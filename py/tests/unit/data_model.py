#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the data_model storage layer.

Exercises the JSONStore backend directly against a temporary directory: no
running visdom server is needed, so these run under ``pytest -m "not server"``.
"""

import copy
import errno
import hashlib
import json
import os
import tempfile
import unittest

import pytest

from visdom.data_model import JSONStore, DataStore
from visdom.data_model import json_store as json_store_module
from visdom.utils.server_utils import LazyEnvData, extract_eid

pytestmark = pytest.mark.unit


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

    def test_save_skips_unmaterialised_lazy_env(self):
        """A LazyEnvData never loaded into memory is not rewritten by save.

        Its on-disk copy is already current, so save must not force it into
        memory just to write it back — it is skipped and left out of the
        returned ids.
        """
        lazy = LazyEnvData(self.backend, "lazy")
        self.assertIsNone(lazy._raw_dict)
        ret = self.backend.save_envs({"lazy": lazy}, ["lazy"])
        self.assertEqual(ret, [])
        self.assertFalse(self.backend.env_exists("lazy"))

    def test_whitespace_differing_eids_no_longer_collide(self):
        """'main' and 'main ' must not silently overwrite each other on disk.

        Regression test: the in-memory state dict is keyed by
        ``extract_eid(args)``, while JSONStore derives filenames via its own
        whitespace-stripping ``_safe_eid``. Before ``escape_eid`` also
        stripped whitespace, two distinct in-memory envs differing only by
        surrounding whitespace would collide on disk (whichever saved last
        would clobber the other). Now both normalise to the same id, so this
        is expected, intentional behaviour rather than an accidental clobber.
        """
        eid_a = extract_eid({"eid": "main"})
        eid_b = extract_eid({"eid": "main "})
        self.assertEqual(eid_a, eid_b)  # they are now (correctly) one env

        self.backend.save_env(eid_a, _env("winA"))
        self.backend.save_env(eid_b, _env("winB"))
        # Only one file exists on disk, holding the last write - not two
        # environments silently fighting over the same filename.
        self.assertEqual(self.backend.list_envs(), ["main"])
        self.assertEqual(self.backend.load_env("main")["jsons"], _env("winB")["jsons"])

    def test_save_writes_materialised_lazy_env(self):
        """A LazyEnvData that has been loaded is persisted by save."""
        self.backend.save_env("lazy", _env())
        lazy = LazyEnvData(self.backend, "lazy")
        lazy.lazy_load_data()  # materialise from disk
        self.backend.delete_env("lazy")  # prove the next save recreates it
        self.assertFalse(self.backend.env_exists("lazy"))
        ret = self.backend.save_envs({"lazy": lazy}, ["lazy"])
        self.assertEqual(ret, ["lazy"])
        self.assertEqual(self.backend.load_env("lazy"), _env())

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

    def test_layouts_round_trip(self):
        """Saved layouts read back byte-for-byte as the same string."""
        blob = '[["view A", {"win_0": [0, 0, 3, 3]}]]'
        self.backend.save_layouts(blob)
        self.assertEqual(self.backend.load_layouts(), blob)

    def test_save_layouts_writes_expected_file(self):
        """save_layouts writes <env_path>/view/layouts.json."""
        self.backend.save_layouts("[]")
        expected = os.path.join(self.env_path, "view", "layouts.json")
        self.assertTrue(os.path.exists(expected))
        with open(expected) as fn:
            self.assertEqual(fn.read(), "[]")

    def test_load_layouts_missing_returns_empty(self):
        """load_layouts returns '' when no layout file has been written."""
        self.assertEqual(self.backend.load_layouts(), "")

    def test_undo_round_trip(self):
        """A saved undo stack reads back unchanged."""
        stack = [["win_0", {"id": "win_0"}], ["win_1", {"id": "win_1"}]]
        self.backend.save_undo("expt", stack)
        self.assertEqual(self.backend.load_undo("expt"), stack)

    def test_load_undo_missing_returns_empty(self):
        """load_undo returns [] when no undo file exists."""
        self.assertEqual(self.backend.load_undo("expt"), [])

    def test_save_undo_writes_under_dot_undo(self):
        """save_undo writes <env_path>/.undo/<eid>.json."""
        self.backend.save_undo("expt", [["win_0", {"id": "win_0"}]])
        expected = os.path.join(self.env_path, ".undo", "expt.json")
        self.assertTrue(os.path.exists(expected))

    def test_clear_undo_removes_history(self):
        """clear_undo drops a previously saved undo stack."""
        self.backend.save_undo("expt", [["win_0", {"id": "win_0"}]])
        self.backend.clear_undo("expt")
        self.assertEqual(self.backend.load_undo("expt"), [])

    def test_undo_long_name_hash_fallback_round_trips(self):
        """An over-long env name uses the hash_<sha256>.json undo fallback."""
        long_eid = "e" * 5000
        stack = [["win_0", {"id": "win_0"}]]
        self.backend.save_undo(long_eid, stack)
        self.assertEqual(self.backend.load_undo(long_eid), stack)

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

    def test_save_layouts_is_noop(self):
        """save_layouts persists nothing when persistence is disabled."""
        self.assertIsNone(self.backend.save_layouts("[]"))

    def test_load_layouts_returns_empty(self):
        """load_layouts returns '' when persistence is disabled."""
        self.assertEqual(self.backend.load_layouts(), "")

    def test_load_undo_returns_empty(self):
        """load_undo returns [] when persistence is disabled."""
        self.assertEqual(self.backend.load_undo("expt"), [])

    def test_save_undo_is_noop(self):
        """save_undo persists nothing when persistence is disabled."""
        self.assertIsNone(self.backend.save_undo("expt", [["w", {}]]))

    def test_clear_undo_is_noop(self):
        """clear_undo removes nothing when persistence is disabled."""
        self.assertIsNone(self.backend.clear_undo("expt"))


# -- Durability of the env write --------------------------------------------
#
# Written as plain functions on the shared fixtures rather than as methods on
# the classes above: the conversion of those two classes belongs to a later
# clean-up, and fixtures cannot reach unittest.TestCase methods.


def _fail_after(monkeypatch, prefix_bytes):
    """Make writes inside json_store emit ``prefix_bytes`` then die.

    Stands in for a process killed part-way through a save. ``open`` is looked
    up in the module's globals before the builtins, so setting it on the module
    intercepts only json_store's own writes.
    """
    real_open = open

    class _DyingFile:
        def __init__(self, handle):
            self._handle = handle

        def write(self, data):
            self._handle.write(data[:prefix_bytes])
            raise OSError(errno.EIO, "interrupted mid-write")

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._handle.close()
            return False

    def dying_open(path, mode="r", *args, **kwargs):
        if "w" not in mode:
            return real_open(path, mode, *args, **kwargs)
        return _DyingFile(real_open(path, mode, *args, **kwargs))

    monkeypatch.setattr(json_store_module, "open", dying_open, raising=False)


def test_interrupted_save_keeps_the_previous_env(store, monkeypatch):
    """A save killed mid-write leaves the environment that was already there.

    Without the staging file the real env is truncated on open and load_env's
    ValueError handler then reports the environment as empty — data loss with
    no signal at all.
    """
    store.save_env("main", _env("win_original"))

    _fail_after(monkeypatch, prefix_bytes=8)
    with pytest.raises(OSError):
        store.save_env("main", _env("win_replacement"))

    assert store.load_env("main") == _env("win_original")


def test_interrupted_save_leaves_a_usable_env(store, monkeypatch):
    """The environment is still discoverable *and* readable after a failure.

    A truncated file keeps its name, so listing and existence alone would pass
    even with the env destroyed; the reload is what makes this meaningful.
    """
    store.save_env("main", _env())

    _fail_after(monkeypatch, prefix_bytes=8)
    with pytest.raises(OSError):
        store.save_env("main", _env("win_replacement"))

    assert store.list_envs() == ["main"]
    assert store.env_exists("main")
    assert JSONStore(store.env_path).load_env("main") == _env()


def test_stranded_staging_file_is_not_an_env(store, env_path, monkeypatch):
    """A leftover .tmp is on disk but never mistaken for an environment.

    list_envs only considers names ending in .json, and the staging file is
    named <eid>.json.tmp precisely so that stays true.
    """
    store.save_env("main", _env())

    _fail_after(monkeypatch, prefix_bytes=8)
    with pytest.raises(OSError):
        store.save_env("main", _env("win_replacement"))

    assert "main.json.tmp" in os.listdir(env_path)
    assert store.list_envs() == ["main"]


def test_successful_save_leaves_no_staging_file(store, env_path):
    """The staging file is renamed away, not left behind."""
    store.save_env("main", _env())
    assert [n for n in os.listdir(env_path) if n.endswith(".tmp")] == []


def test_failed_rename_keeps_the_previous_env(store, env_path, monkeypatch):
    """If the rename itself fails, the old env is still the one on disk."""
    store.save_env("main", _env("win_original"))

    def boom(src, dst):
        raise OSError(errno.EIO, "rename failed")

    monkeypatch.setattr(json_store_module.os, "replace", boom)
    with pytest.raises(OSError):
        store.save_env("main", _env("win_replacement"))

    monkeypatch.undo()
    assert store.load_env("main") == _env("win_original")


def test_long_name_fallback_leaves_no_staging_file(store, env_path):
    """The hash fallback path stages and renames too."""
    long_eid = "e" * 5000
    assert store.save_env(long_eid, _env())
    assert [n for n in os.listdir(env_path) if n.endswith(".tmp")] == []
    assert store.load_env(long_eid)["jsons"] == _env()["jsons"]


def test_interrupted_undo_save_keeps_the_previous_stack(store, monkeypatch):
    """The undo stack was already written this way; it stays that way."""
    store.save_undo("main", [["win_0", {"id": "win_0"}]])

    _fail_after(monkeypatch, prefix_bytes=4)
    with pytest.raises(OSError):
        store.save_undo("main", [["win_1", {"id": "win_1"}]])

    assert store.load_undo("main") == [["win_0", {"id": "win_0"}]]


# -- Name collisions ---------------------------------------------------------


def _hashed_name(eid):
    """The hash-fallback filename JSONStore would pick for ``eid``."""
    digest = hashlib.sha256(eid.encode("utf-8")).hexdigest()
    return "hash_{0}.json".format(digest)


def test_env_named_like_a_hash_file_is_dropped_from_the_listing(store):
    """An env whose own name matches hash_<64 hex> disappears from list_envs.

    HASHED_ENV_RE matches on the filename alone, so the file is read as a hash
    fallback and skipped when the ``name`` field it expects is absent. The
    environment is still saved, and still loads by id — only the listing loses
    it. Documented here rather than fixed: changing the rule would break the
    long-name files already on users' disks.
    """
    colliding_eid = "hash_" + "a" * 64
    store.save_env(colliding_eid, _env())
    store.save_env("main", _env())

    assert store.env_exists(colliding_eid)
    assert store.load_env(colliding_eid) == _env()
    assert store.list_envs() == ["main"]


def test_hash_fallback_file_reports_the_real_id(store, env_path):
    """A genuine long-name fallback file does carry its id and is listed."""
    long_eid = "e" * 5000
    store.save_env(long_eid, _env())

    assert _hashed_name(long_eid) in os.listdir(env_path)
    assert store.list_envs() == [long_eid]


# -- LazyEnvData -------------------------------------------------------------


def test_lazy_env_defers_the_read(spy_store):
    """Constructing a LazyEnvData touches the backend not at all."""
    spy_store.save_env("main", _env())

    LazyEnvData(spy_store, "main")

    assert spy_store.calls["load_env"] == []


def test_lazy_env_reads_once_and_caches(spy_store):
    """Repeated access hits the backend exactly once."""
    spy_store.save_env("main", _env())
    lazy = LazyEnvData(spy_store, "main")

    lazy["jsons"]
    lazy["reload"]
    len(lazy)
    list(lazy)

    assert spy_store.calls["load_env"] == ["main"]


def test_lazy_env_satisfies_the_mapping_contract(store):
    """It behaves like the dict it stands in for."""
    store.save_env("main", _env())
    lazy = LazyEnvData(store, "main")

    assert sorted(lazy.keys()) == ["jsons", "reload"]
    assert lazy["jsons"] == _env()["jsons"]
    assert lazy.get("reload") == {}
    assert lazy.get("absent") is None
    assert lazy.get("absent", "fallback") == "fallback"
    assert "jsons" in lazy
    assert "absent" not in lazy
    assert len(lazy) == 2
    assert dict(lazy.items()) == _env()
    assert lazy == _env()


def test_lazy_env_setitem_materialises_first(store):
    """Writing a key loads the env, so the write lands on real data."""
    store.save_env("main", _env())
    lazy = LazyEnvData(store, "main")

    lazy["reload"] = {"win_0": [0, 0, 3, 3]}

    assert lazy["jsons"] == _env()["jsons"]
    assert lazy["reload"] == {"win_0": [0, 0, 3, 3]}


def test_lazy_env_raises_value_error_for_a_malformed_env(store, env_path):
    """A file that is not a valid env becomes a ValueError naming the id."""
    with open(os.path.join(env_path, "broken.json"), "w") as fn:
        fn.write("{not valid json")

    lazy = LazyEnvData(store, "broken")
    with pytest.raises(ValueError, match="broken"):
        lazy.lazy_load_data()


def test_lazy_env_raises_value_error_for_a_missing_env(store):
    """A never-saved env is malformed too: load_env returns {} with no jsons."""
    with pytest.raises(ValueError, match="Failed loading environment json"):
        LazyEnvData(store, "ghost").lazy_load_data()


def test_lazy_env_keeps_the_experiment_blob(store):
    """Metadata beyond jsons/reload survives the lazy load."""
    payload = dict(_env(), experiment={"name": "run-1"})
    store.save_env("main", payload)

    assert LazyEnvData(store, "main")["experiment"] == {"name": "run-1"}


# -- Deep copies of environment state ----------------------------------------
#
# ForkEnvHandler (web_handlers.py) and the socket "save" command both fork an
# environment with copy.deepcopy. When the source is a LazyEnvData that means
# the store reference is deep-copied alongside the data.


def test_deep_copy_of_a_lazy_env_is_independent(store):
    """Mutating the fork leaves the source environment alone."""
    store.save_env("main", _env())
    source = LazyEnvData(store, "main")
    source.lazy_load_data()

    fork = copy.deepcopy(source)
    fork["jsons"]["win_1"] = {"id": "win_1"}

    assert "win_1" not in source["jsons"]
    assert sorted(fork["jsons"]) == ["win_0", "win_1"]


def test_deep_copy_clones_the_store_reference(store):
    """The fork gets its own JSONStore, not the one the source holds.

    Harmless today because JSONStore's only state is the path, but it means the
    fork does not observe a later swap of the source's backend.
    """
    store.save_env("main", _env())
    source = LazyEnvData(store, "main")
    source.lazy_load_data()

    fork = copy.deepcopy(source)

    assert fork._store is not source._store
    assert fork._store.env_path == source._store.env_path
    assert fork._store.load_env("main") == _env()


def test_deep_copy_of_an_unmaterialised_lazy_env_still_loads(store):
    """A fork taken before the first read resolves against the copied store."""
    store.save_env("main", _env())
    source = LazyEnvData(store, "main")

    fork = copy.deepcopy(source)

    assert fork["jsons"] == _env()["jsons"]
    assert source._raw_dict is None


def test_forked_env_persists_under_its_own_id(store):
    """Saving a deep copy under a new id writes a second, separate file."""
    store.save_env("main", _env())
    source = LazyEnvData(store, "main")
    source.lazy_load_data()

    fork = copy.deepcopy(source)
    fork["jsons"]["win_1"] = {"id": "win_1"}
    store.save_env("forked", fork)

    assert store.load_env("main") == _env()
    assert sorted(store.load_env("forked")["jsons"]) == ["win_0", "win_1"]


if __name__ == "__main__":
    unittest.main()
