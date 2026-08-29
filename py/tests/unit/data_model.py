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

import pytest

from visdom.data_model import JSONStore, DataStore
from visdom.data_model import json_store as json_store_module
from visdom.utils.server_utils import LazyEnvData, extract_eid

pytestmark = pytest.mark.unit


def _env(win_id="win_0"):
    """Build a minimal environment payload (one window) for use in tests."""
    return {"jsons": {win_id: {"id": win_id}}, "reload": {}}


# -- JSONStore with persistence enabled --------------------------------------


def test_is_a_data_store(store):
    """JSONStore satisfies the DataStore interface."""
    assert isinstance(store, DataStore)


def test_save_then_load_round_trip(store):
    """A saved environment is read back unchanged."""
    env = _env()
    assert store.save_env("main", env)
    assert store.load_env("main") == env


def test_save_writes_expected_file(store, env_path):
    """save_env writes the env to <env_path>/<eid>.json on disk."""
    store.save_env("main", _env())
    expected = os.path.join(env_path, "main.json")
    assert os.path.exists(expected)
    with open(expected) as fn:
        assert json.load(fn) == _env()


def test_load_missing_env_returns_empty(store):
    """Loading an environment that was never saved returns {}."""
    assert store.load_env("nope") == {}


def test_env_exists(store):
    """env_exists reflects whether the environment is on disk."""
    assert not store.env_exists("main")
    store.save_env("main", _env())
    assert store.env_exists("main")


def test_list_envs(store):
    """list_envs returns the ids of all saved environments."""
    assert store.list_envs() == []
    store.save_env("main", _env())
    store.save_env("other", _env())
    assert sorted(store.list_envs()) == ["main", "other"]


def test_list_ignores_subdirs(store, env_path):
    """A view/layouts.json side-file is not mistaken for an environment."""
    os.mkdir(os.path.join(env_path, "view"))
    with open(os.path.join(env_path, "view", "layouts.json"), "w") as fn:
        fn.write("{}")
    store.save_env("main", _env())
    assert store.list_envs() == ["main"]


def test_delete_env(store):
    """delete_env removes the env and reports False when nothing to remove."""
    store.save_env("main", _env())
    assert store.delete_env("main")
    assert not store.env_exists("main")
    assert not store.delete_env("main")


def test_save_envs_saves_named_subset(store):
    """save_envs persists only the named subset of state."""
    state = {"main": _env(), "other": _env()}
    assert store.save_envs(state, ["main"]) == ["main"]
    assert store.env_exists("main")
    assert not store.env_exists("other")


def test_save_envs_drops_unknown_ids(store):
    """save_envs ignores ids that aren't present in state."""
    assert store.save_envs({"main": _env()}, ["main", "ghost"]) == ["main"]


def test_save_all_saves_everything(store):
    """save_all persists every environment in state."""
    state = {"main": _env(), "other": _env()}
    assert sorted(store.save_all(state)) == ["main", "other"]
    assert store.load_env("main") == _env()


def test_save_skips_unmaterialised_lazy_env(store):
    """A LazyEnvData never loaded into memory is not rewritten by save.

    Its on-disk copy is already current, so save must not force it into
    memory just to write it back — it is skipped and left out of the
    returned ids.
    """
    lazy = LazyEnvData(store, "lazy")
    assert lazy._raw_dict is None
    assert store.save_envs({"lazy": lazy}, ["lazy"]) == []
    assert not store.env_exists("lazy")


def test_whitespace_differing_eids_no_longer_collide(store):
    """'main' and 'main ' must not silently overwrite each other on disk.

    Regression test: the in-memory state dict is keyed by ``extract_eid(args)``,
    while JSONStore derives filenames via its own whitespace-stripping
    ``_safe_eid``. Before ``escape_eid`` also stripped whitespace, two distinct
    in-memory envs differing only by surrounding whitespace would collide on
    disk (whichever saved last would clobber the other). Now both normalise to
    the same id, so this is expected, intentional behaviour rather than an
    accidental clobber.
    """
    eid_a = extract_eid({"eid": "main"})
    eid_b = extract_eid({"eid": "main "})
    assert eid_a == eid_b  # they are now (correctly) one env

    store.save_env(eid_a, _env("winA"))
    store.save_env(eid_b, _env("winB"))

    # Only one file exists on disk, holding the last write - not two
    # environments silently fighting over the same filename.
    assert store.list_envs() == ["main"]
    assert store.load_env("main")["jsons"] == _env("winB")["jsons"]


def test_save_writes_materialised_lazy_env(store):
    """A LazyEnvData that has been loaded is persisted by save."""
    store.save_env("lazy", _env())
    lazy = LazyEnvData(store, "lazy")
    lazy.lazy_load_data()  # materialise from disk
    store.delete_env("lazy")  # prove the next save recreates it
    assert not store.env_exists("lazy")
    assert store.save_envs({"lazy": lazy}, ["lazy"]) == ["lazy"]
    assert store.load_env("lazy") == _env()


def test_env_named_like_hash_is_not_misread(store):
    """An env named 'hash_results' is not treated as a hash_<64hex> file."""
    store.save_env("hash_results", _env())
    assert store.list_envs() == ["hash_results"]


def test_long_name_hash_fallback_round_trips(store):
    """An over-long env name uses the hash_<sha256>.json fallback and round-trips."""
    long_eid = "e" * 5000
    store.save_env(long_eid, _env())
    assert store.list_envs() == [long_eid]
    assert store.env_exists(long_eid)
    assert store.load_env(long_eid)["jsons"] == _env()["jsons"]


def test_layouts_round_trip(store):
    """Saved layouts read back byte-for-byte as the same string."""
    blob = '[["view A", {"win_0": [0, 0, 3, 3]}]]'
    store.save_layouts(blob)
    assert store.load_layouts() == blob


def test_save_layouts_writes_expected_file(store, env_path):
    """save_layouts writes <env_path>/view/layouts.json."""
    store.save_layouts("[]")
    expected = os.path.join(env_path, "view", "layouts.json")
    assert os.path.exists(expected)
    with open(expected) as fn:
        assert fn.read() == "[]"


def test_load_layouts_missing_returns_empty(store):
    """load_layouts returns '' when no layout file has been written."""
    assert store.load_layouts() == ""


def test_undo_round_trip(store):
    """A saved undo stack reads back unchanged."""
    stack = [["win_0", {"id": "win_0"}], ["win_1", {"id": "win_1"}]]
    store.save_undo("expt", stack)
    assert store.load_undo("expt") == stack


def test_load_undo_missing_returns_empty(store):
    """load_undo returns [] when no undo file exists."""
    assert store.load_undo("expt") == []


def test_save_undo_writes_under_dot_undo(store, env_path):
    """save_undo writes <env_path>/.undo/<eid>.json."""
    store.save_undo("expt", [["win_0", {"id": "win_0"}]])
    assert os.path.exists(os.path.join(env_path, ".undo", "expt.json"))


def test_clear_undo_removes_history(store):
    """clear_undo drops a previously saved undo stack."""
    store.save_undo("expt", [["win_0", {"id": "win_0"}]])
    store.clear_undo("expt")
    assert store.load_undo("expt") == []


def test_undo_long_name_hash_fallback_round_trips(store):
    """An over-long env name uses the hash_<sha256>.json undo fallback."""
    long_eid = "e" * 5000
    stack = [["win_0", {"id": "win_0"}]]
    store.save_undo(long_eid, stack)
    assert store.load_undo(long_eid) == stack


@pytest.mark.parametrize("eid", ["../evil", "subdir/../evil", "/etc/evil"])
def test_save_ignores_path_traversal_ids(store, env_path, eid):
    """A crafted id like '../evil' cannot write outside env_path."""
    parent = os.path.dirname(env_path)
    before = set(os.listdir(parent))

    store.save_env(eid, _env())

    assert set(os.listdir(parent)) - before == set()
    base = os.path.abspath(env_path)
    for name in os.listdir(env_path):
        resolved = os.path.abspath(os.path.join(env_path, name))
        assert resolved.startswith(base + os.sep)


def test_traversal_id_round_trips_within_env_path(store):
    """A crafted id is sanitised consistently across save/exists/list/load."""
    store.save_env("../evil", _env())
    assert store.env_exists("../evil")
    assert store.list_envs() == [".._evil"]
    assert store.load_env("../evil") == _env()


def test_env_literally_named_like_hash_pattern_is_still_listed(store):
    """A primary env whose (escaped) id exactly matches hash_<64hex>.

    This is the actual collision that used to make list_envs() drop the
    environment entirely: the filename looks exactly like a hash-fallback file
    (there is nothing else to distinguish it by), but it is really an ordinary
    primary file with no "name" bookkeeping field inside. It must still be
    listed, using its own filename stem, which -- for this specific collision
    -- *is* the real, already-escaped id.
    """
    eid = "hash_" + "c" * 64
    store.save_env(eid, _env())

    assert store.list_envs() == [eid]
    assert store.env_exists(eid)


def test_list_recovers_hash_file_missing_name_field(store, env_path):
    """A well-formed hash_<64>.json missing its "name" field is recovered.

    This can happen if a genuine hash-fallback file's "name" field is lost
    (e.g. hand-edited, or written by an older/different DataStore
    implementation). Rather than silently vanishing, the environment is
    surfaced under its filename stem -- worse than having the real name, but
    strictly better than losing access to the data entirely.
    """
    stem = "hash_" + "b" * 64
    with open(os.path.join(env_path, stem + ".json"), "w") as fn:
        fn.write(json.dumps({"jsons": {}, "reload": {}}))
    store.save_env("main", _env())

    assert store.list_envs() == sorted(["main", stem])


def test_list_recovers_hash_file_unusable_name_field(store, env_path):
    """A hash_<64>.json with a non-string "name" field falls back to stem.

    Even if a "name" key exists in the JSON, it must be a string; otherwise we
    treat it like a missing name and use the filename stem so the environment
    still appears in list_envs().
    """
    stem = "hash_" + "c" * 64
    with open(os.path.join(env_path, stem + ".json"), "w") as fn:
        fn.write(json.dumps({"name": 123, "jsons": {}, "reload": {}}))
    store.save_env("main", _env())

    assert store.list_envs() == sorted(["main", stem])


def test_list_skips_unreadable_hash_files(store, env_path):
    """Malformed hash_<64>.json files are ignored, not raised, by list_envs."""
    with open(os.path.join(env_path, "hash_{0}.json".format("a" * 64)), "w") as fn:
        fn.write("{not valid json")
    store.save_env("main", _env())

    assert store.list_envs() == ["main"]


# -- JSONStore(None): persistence disabled (in-memory-only mode) --------------


@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda s: s.save_env("main", _env()), False),
        (lambda s: s.save_envs({"main": _env()}, ["main"]), []),
        (lambda s: s.save_all({"main": _env()}), []),
        (lambda s: s.load_env("main"), {}),
        (lambda s: s.list_envs(), []),
        (lambda s: s.env_exists("main"), False),
        (lambda s: s.delete_env("main"), False),
        (lambda s: s.save_layouts("[]"), None),
        (lambda s: s.load_layouts(), ""),
        (lambda s: s.load_undo("expt"), []),
        (lambda s: s.save_undo("expt", [["w", {}]]), None),
        (lambda s: s.clear_undo("expt"), None),
    ],
    ids=[
        "save_env",
        "save_envs",
        "save_all",
        "load_env",
        "list_envs",
        "env_exists",
        "delete_env",
        "save_layouts",
        "load_layouts",
        "load_undo",
        "save_undo",
        "clear_undo",
    ],
)
def test_no_env_path_makes_every_operation_inert(call, expected):
    """With no env_path nothing is persisted and every call answers emptily."""
    assert call(JSONStore(None)) == expected


# -- Durability of the env write --------------------------------------------


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


def test_env_named_like_a_hash_file_is_still_listed(store):
    """An env whose own name matches hash_<64 hex> no longer disappears.

    HASHED_ENV_RE matches on the filename alone, so this file is read as a
    hash fallback first. It has none of the fallback bookkeeping though --
    there's no ``name`` field, because it was written as an ordinary primary
    file. list_envs() used to drop such environments from the listing
    entirely on a bare KeyError; it now falls back to the filename stem,
    which for this exact collision *is* the real, already-escaped id.
    """
    colliding_eid = "hash_" + "a" * 64
    store.save_env(colliding_eid, _env())
    store.save_env("main", _env())

    assert store.env_exists(colliding_eid)
    assert store.load_env(colliding_eid) == _env()
    assert store.list_envs() == sorted(["main", colliding_eid])


def test_hash_fallback_file_reports_the_real_id(store, env_path):
    """A genuine long-name fallback file does carry its id and is listed."""
    long_eid = "e" * 5000
    store.save_env(long_eid, _env())

    assert _hashed_name(long_eid) in os.listdir(env_path)
    assert store.list_envs() == [long_eid]


def test_hash_shaped_file_missing_name_field_falls_back_to_its_stem(store, env_path):
    """A well-formed hash_<64>.json without a ``name`` field isn't dropped.

    This can happen if a genuine hash-fallback file's ``name`` field is lost
    (hand-edited, or written by a different DataStore implementation).
    Surfacing it under its filename stem is worse than having the real name,
    but strictly better than losing access to the environment entirely.
    """
    stem = "hash_" + "b" * 64
    with open(os.path.join(env_path, stem + ".json"), "w") as fn:
        fn.write(json.dumps({"jsons": {}, "reload": {}}))
    store.save_env("main", _env())

    assert store.list_envs() == sorted(["main", stem])


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
