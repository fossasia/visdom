#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import collections
import copy
import errno
import hashlib
import json
import logging
import os
import re
import threading

from visdom.data_model.base import DataStore, read_json_file, UNREADABLE_JSON
from visdom.server.defaults import LAYOUT_FILE, UNDO_DIRNAME
from visdom.utils.server_utils import escape_eid, LazyEnvData
from visdom.utils.shared_utils import ensure_dir_exists, NanSafeEncoder

HASHED_ENV_RE = re.compile(r"^hash_[a-f0-9]{64}\.json$", re.IGNORECASE)

#: The small facts an env file holds outside its windows: the experiment
#: metadata blob and, for a ``hash_<sha256>.json`` fallback, the real env id.
#: ``readable`` is ``False`` for a file that could not be opened or parsed --
#: never cached, for the reasons in :meth:`JSONStore._read_meta`, and distinct
#: from a file that parsed but holds neither fact.
MetaRecord = collections.namedtuple("MetaRecord", "readable experiment name")

UNREADABLE_META = MetaRecord(readable=False, experiment=None, name=None)

#: Per-object overheads the weight estimate charges, in bytes, measured on
#: CPython 3.12 with :func:`sys.getsizeof`: an empty dict is 64 B and a list
#: 56 B, a slot in either costs up to ~64 B once the table has grown, a string
#: carries 41 B of header over its characters, and every scalar (int, float,
#: bool, ``None``) fits in 32 B. Each is rounded *up*, because a budget that
#: runs under its own guess is the one that fails.
META_MAPPING_BYTES = 64
META_SEQUENCE_BYTES = 56
META_SLOT_BYTES = 64
META_TEXT_BYTES = 41
META_SCALAR_BYTES = 32

#: What one cache entry costs before any of its content: the ``MetaRecord``,
#: the stat key, the absolute path it is filed under, and the dict slot holding
#: all three.
META_ENTRY_BYTES = 512

#: What one stored observation is charged. The metric series is the only part
#: of a record that grows without bound, so it is the only part counted rather
#: than walked -- ``len`` is O(1) where a walk would be O(observations), and an
#: observation is a uniform four-key dict (``key``, ``value``, ``step``,
#: ``timestamp``) whose cost does not vary. Measured at ~310 B in place, where
#: the four key strings are shared across every observation in the series.
META_OBSERVATION_BYTES = 320

#: How much memory the metadata cache may hold before it starts evicting, i.e.
#: ~26k stored observations, or thousands of ordinary environments. A cache
#: that forgets is still correct here -- the file is re-read -- so this is a
#: memory ceiling, not a correctness one, and it is what keeps the dimensions
#: that really grow (a long metric history, or a run logging large parameter
#: values, *not* plot data) from being unbounded.
DEFAULT_META_CACHE_BYTES = 8 * 1024 * 1024


def _value_weight(value):
    """Estimate what holding ``value`` costs, in bytes.

    Walks containers and charges strings by their length, so metadata a run
    chooses the size of -- parameter values, tag names, a long description --
    is paid for rather than assumed small. Only the metric series escapes the
    walk, in :func:`meta_weight`.
    """
    if isinstance(value, dict):
        total = META_MAPPING_BYTES
        for key, item in value.items():
            total += META_SLOT_BYTES + _value_weight(key) + _value_weight(item)
        return total
    if isinstance(value, (list, tuple)):
        total = META_SEQUENCE_BYTES
        for item in value:
            total += META_SLOT_BYTES + _value_weight(item)
        return total
    if isinstance(value, str):
        return META_TEXT_BYTES + len(value)
    return META_SCALAR_BYTES


def meta_weight(record):
    """Estimate what caching ``record`` costs, in bytes.

    An estimate rather than a measurement: sizing the held objects exactly
    (walking them with :func:`sys.getsizeof`, following shared references)
    costs more than the parse the cache exists to avoid. It is still a walk of
    everything the record actually holds -- the experiment blob is kept whole,
    so params, tags, the name and the description are charged by their real
    size, not assumed to be small. ``POST /experiments/log`` takes all four
    from the client, so none of them has a bound this code may assume.

    The single exception is the metric series, which is counted rather than
    walked: it is the one part that grows without limit, so weighing it must
    stay O(1), and its entries are uniform (see :data:`META_OBSERVATION_BYTES`).

    Deliberately rounds up at every step, since a budget that runs under its
    own guess is the one that fails.
    """
    total = META_ENTRY_BYTES
    if isinstance(record.name, str):
        total += META_TEXT_BYTES + len(record.name)
    blob = record.experiment
    if not isinstance(blob, dict):
        return total + _value_weight(blob)
    total += META_MAPPING_BYTES
    for key, value in blob.items():
        total += META_SLOT_BYTES + _value_weight(key)
        if key == "metrics" and isinstance(value, list):
            total += META_SEQUENCE_BYTES + len(value) * META_OBSERVATION_BYTES
        else:
            total += _value_weight(value)
    return total


class JSONStore(DataStore):
    """DataStore backed by one ``<eid>.json`` file per environment.

    Environments too long to use as a filename are stored under a
    ``hash_<sha256>.json`` fallback with their real id kept inside the file.
    When ``env_path`` is ``None`` persistence is disabled and the store behaves
    as a no-op (matching Visdom's in-memory-only mode).
    """

    def __init__(self, env_path, meta_cache_bytes=DEFAULT_META_CACHE_BYTES):
        """Create a store rooted at ``env_path`` (``None`` disables persistence).

        ``meta_cache_bytes`` caps the metadata cache (see :meth:`_read_meta`);
        it is a constructor argument rather than only a module constant so a
        test can set a budget small enough to evict in a handful of reads.
        """
        self.env_path = env_path
        # Parsed metadata per env file, keyed by the file's stat identity, in
        # least-recently-used order: dicts keep insertion order, a hit moves its
        # entry to the end, and eviction takes from the front. See
        # :meth:`_read_meta`.
        #
        # The lock is here for ``_meta_bytes``, not for the dict. Every single
        # dict operation below is atomic under the GIL, and losing a race on one
        # would only cost a re-parse -- but ``_meta_bytes`` is adjusted with
        # ``+=``/``-=``, which is a read-modify-write, and a lost update there
        # makes the running total drift away from what is held. That is a
        # *silent* failure: the budget stops matching reality and the cache
        # either evicts constantly or stops evicting at all, which is the
        # unbounded growth the budget exists to prevent.
        #
        # Disk work does run on a single storage worker today
        # (``ServerState.storage_executor``, ``max_workers=1``), so in the
        # server's steady state there is no contention to lose. This does not
        # rely on that: ``Application.load_state`` and ``shutdown_storage`` call
        # the store directly off that worker, the tests call it from whatever
        # thread they are on, and a future reader pool is a plausible thing for
        # someone to add. Two uncontended acquires cost ~0.4us against the
        # ~1080us parse a hit avoids, so correctness here is close to free.
        self._meta_cache = {}
        self._meta_bytes = 0
        self._meta_cache_bytes = meta_cache_bytes
        self._meta_lock = threading.Lock()

    def __deepcopy__(self, memo):
        """Return a store on the same path with an empty metadata cache.

        ``LazyEnvData`` holds a store, so deep-copying an env -- forking one,
        for instance -- deep-copies this. The cache is scratch derived from
        files both stores can read, not state the copy inherits, and copying it
        would put every cached blob through :func:`copy.deepcopy` to arrive at
        something the fork can re-read for the cost of one parse. A fork
        therefore starts cold. (Defining this also keeps the copy off
        :mod:`copy`'s ``__reduce_ex__`` fallback, which cannot handle the lock.)
        """
        twin = type(self)(
            copy.deepcopy(self.env_path, memo),
            meta_cache_bytes=self._meta_cache_bytes,
        )
        memo[id(self)] = twin
        return twin

    def _safe_eid(self, eid):
        """Sanitise ``eid`` into the id used for on-disk filenames.

        Strips surrounding whitespace and neutralises path separators (via
        ``escape_eid``) so a crafted id such as ``../evil`` cannot escape
        ``env_path``. Saves, loads, deletes and existence checks all funnel
        through this so they agree on the file a given ``eid`` maps to.
        """
        return escape_eid(eid.strip())

    def _primary_path(self, eid):
        """Return the canonical ``<env_path>/<eid>.json`` path for ``eid``.

        Returns ``None`` if the resolved path would escape ``env_path`` (guards
        against path traversal via a crafted env id). Every read, write and
        delete resolves through here, so the containment check is the single
        point where an id stops being user input and becomes a path.

        The check is a prefix comparison against the normalised root -- the
        path is made absolute first, so ``..`` segments are already collapsed
        by the time it is tested, and ``os.path.join(base, "")`` supplies the
        trailing separator that keeps a sibling directory (``/envs-evil``) from
        matching the root (``/envs``). ``os.path.commonpath`` decides the same
        question, but only after the fact and only for a reader who knows it
        raises on mixed drives; the prefix form is the shape both static
        analysis and a reader recognise as "compared against env_path".
        """
        safe_eid = self._safe_eid(eid)
        base = os.path.abspath(self.env_path)
        path = os.path.abspath(os.path.join(base, "{0}.json".format(safe_eid)))
        if not path.startswith(os.path.join(base, "")):
            return None
        return path

    def _hash_path(self, eid):
        """Return the ``hash_<sha256>.json`` fallback path for ``eid``.

        No containment check is needed here: the filename is entirely a hex
        digest, so no part of ``eid`` survives into it.
        """
        safe_eid = self._safe_eid(eid)
        base = os.path.abspath(self.env_path)
        hashed_id = hashlib.sha256(safe_eid.encode("utf-8")).hexdigest()
        return os.path.abspath(os.path.join(base, "hash_{0}.json".format(hashed_id)))

    def _resolve_existing(self, eid):
        """Return the existing file path for ``eid`` (primary or hash), or ``None``.

        Every candidate is re-checked here rather than trusted from its
        builder: this is the method whose return value is opened, so the
        containment guarantee has to hold at the point the path leaves it.
        """
        base = os.path.abspath(self.env_path)
        for candidate in (self._primary_path(eid), self._hash_path(eid)):
            if candidate is None:
                continue
            path = os.path.abspath(candidate)
            if not path.startswith(os.path.join(base, "")):
                continue
            if os.path.exists(path):
                return path
        return None

    def save_env(self, eid, env_data):
        """Persist a single environment; return ``True`` if written, else ``False``."""
        return bool(self.save_envs({eid: env_data}, [eid]))

    def save_envs(self, state, eids):
        """Persist the named subset of ``state``; return the ids actually written.

        Each id is sanitised (see :meth:`_safe_eid`) before it becomes a
        filename, so a crafted id cannot write outside ``env_path``. The real
        (unsanitised) ids are returned, matching how callers refer to them.
        """
        if self.env_path is None:
            return []
        os.makedirs(os.path.abspath(self.env_path), exist_ok=True)
        written = []
        for eid in eids:
            if eid not in state:
                continue
            if self.serialize_env(eid, state[eid]):
                written.append(eid)
        return written

    def _atomic_write(self, path, payload):
        """Write ``payload`` to ``path`` via a temporary file and one rename.

        Writing straight to ``path`` truncates the previous contents before the
        new ones are complete, so an interrupted write leaves a half-file that
        :meth:`load_env` cannot parse and silently reports as an empty
        environment. Staging into ``<path>.tmp`` and calling :func:`os.replace`
        keeps the old file readable until the new one is whole. This mirrors
        :meth:`save_undo`.
        """
        tmp = path + ".tmp"
        with open(tmp, "w") as fn:
            fn.write(payload)
        os.replace(tmp, path)
        # Every write this process makes passes through here, so dropping the
        # record is what keeps the metadata cache honest about our own saves.
        # The stat key in :meth:`_read_meta` then only has to catch edits made
        # from outside -- a second server on the same directory, or a hand-
        # edited file. Undo and layout files are never cached; forgetting a
        # path that was never there costs a dict lookup.
        self._forget_meta(path)

    def serialize_env(self, eid, env_data):
        """Write one environment to disk; return ``True`` if written.

        A :class:`LazyEnvData` that was never materialised (``_raw_dict`` is
        ``None``) is skipped and ``False`` is returned: its on-disk copy is
        already current, so there is nothing to rewrite and no reason to force
        it into memory. The write funnels through :meth:`_primary_path` /
        :meth:`_hash_path` so it agrees with load/delete/exists on the file a
        given ``eid`` maps to; over-long ids fall back to ``hash_<sha256>.json``
        with the real id kept in a ``name`` field.

        The write itself is atomic (see :meth:`_atomic_write`), so a crash
        part-way through cannot destroy the environment already on disk. The
        staging file carries a ``.tmp`` suffix rather than ``.json``, so a
        stranded one is never mistaken for an environment by :meth:`list_envs`.
        """
        if isinstance(env_data, LazyEnvData):
            if not env_data.is_loaded:
                return False
            env_data.lazy_load_data()
            payload = env_data._raw_dict
        else:
            payload = env_data

        primary = self._primary_path(eid)
        try:
            if primary is None:
                raise OSError(errno.ENAMETOOLONG, "env id maps outside env_path")
            self._atomic_write(primary, json.dumps(payload, cls=NanSafeEncoder))
        except OSError as e:
            if e.errno != errno.ENAMETOOLONG and getattr(e, "winerror", None) != 206:
                raise
            data_to_save = copy.deepcopy(payload)
            data_to_save["name"] = self._safe_eid(eid)
            self._atomic_write(
                self._hash_path(eid), json.dumps(data_to_save, cls=NanSafeEncoder)
            )
        return True

    def save_all(self, state):
        """Persist every environment in ``state``; return the ids written."""
        return self.save_envs(state, list(state.keys()))

    def load_env(self, eid):
        """Read one environment by ``eid``; return ``{}`` if it is absent.

        Only the canonical env fields are returned: ``jsons`` and ``reload``,
        plus the ``experiment`` metadata blob when present. Internal bookkeeping
        such as the ``name`` field written for hashed long-id files is dropped.

        Deliberately not served from the metadata cache :meth:`_read_meta`
        keeps: what that cache is worth is that it holds a few hundred bytes per
        env instead of every window, and holding the windows of every env ever
        read is exactly the memory :meth:`load_experiment` exists to avoid.
        """
        if self.env_path is None:
            return {}
        path = self._resolve_existing(eid)
        if path is None:
            return {}
        data = read_json_file(path, default=None)
        if not (isinstance(data, dict) and "jsons" in data and "reload" in data):
            return {}
        env = {"jsons": data.get("jsons", {}), "reload": data.get("reload", {})}
        if "experiment" in data:
            env["experiment"] = data["experiment"]
        return env

    def _forget_meta(self, path):
        """Drop ``path``'s cached metadata, if any."""
        with self._meta_lock:
            self._drop_locked(os.path.abspath(path))

    def _drop_locked(self, path):
        """Remove one entry and credit its weight back. Caller holds the lock."""
        entry = self._meta_cache.pop(path, None)
        if entry is not None:
            self._meta_bytes -= entry[2]

    def _evict_locked(self):
        """Evict least-recently-used entries until the budget is met.

        The last entry standing is never evicted, even if it alone is over
        budget: it was just read, so the caller is holding that blob either way
        and dropping it would buy nothing now while guaranteeing a re-parse on
        the next read. So the ceiling is "the budget, or one record, whichever
        is larger" -- a bound set by the biggest single experiment on disk
        rather than by how many there are.

        Caller holds the lock.
        """
        while self._meta_bytes > self._meta_cache_bytes and len(self._meta_cache) > 1:
            self._drop_locked(next(iter(self._meta_cache)))

    def _parse_meta(self, path):
        """Parse ``path`` once and keep only the facts outside its windows.

        Mirrors what :meth:`load_experiment` and :meth:`list_envs` used to read
        inline, including which failures they tolerate: an unopenable or
        unparseable file is :data:`UNREADABLE_META`, and a document that is not
        a JSON object parsed fine but holds neither fact. The read itself is
        :func:`~visdom.data_model.base.read_json_file`, so this store never
        opens a file for itself and the two outcomes stay distinguishable:
        :data:`~visdom.data_model.base.UNREADABLE_JSON` is a sentinel object, so
        a file holding a literal ``null`` is not read as a failure.
        """
        data = read_json_file(path)
        if data is UNREADABLE_JSON:
            return UNREADABLE_META
        if not isinstance(data, dict):
            return MetaRecord(readable=True, experiment=None, name=None)
        blob = data.get("experiment")
        name = data.get("name")
        return MetaRecord(
            readable=True,
            experiment=blob if isinstance(blob, dict) else None,
            name=name if isinstance(name, str) else None,
        )

    def _read_meta(self, path):
        """Return ``path``'s :data:`MetaRecord`, parsing the file at most once.

        An env is one JSON document, so reading the experiment blob or a hashed
        file's real id meant parsing every window in it -- and
        :meth:`~visdom.experiments.store.ExperimentStore.iter_experiments` does
        that for every env on disk, on each ``/experiments/search``,
        ``/experiments/hparams`` and ``GET /experiments/tags``. The facts those
        callers want are a few hundred bytes next to megabytes of plot data, so
        they are cached and the file is re-read only once it changes.

        The cache key is the file's stat identity -- ``st_mtime_ns``,
        ``st_ctime_ns``, ``st_size``, ``st_ino``, ``st_dev`` and ``st_mode`` --
        not its path alone. ``st_mtime`` on its own would not do: it is whole
        seconds on some filesystems, so a rewrite in the same second as the
        read it followed would be missed. ``st_ino`` closes most of the gap,
        because :meth:`_atomic_write` finishes with :func:`os.replace` and a
        replaced file is a new inode whatever its timestamps say.

        Only a *successful* read is stored. A failure is returned to the
        caller and then forgotten, because nothing in the stat key has to move
        for a read to fail: a process out of file descriptors, an interrupted
        syscall or a disk error makes the next read fail while leaving the
        file itself untouched. A cached failure would therefore outlive its
        cause and keep the env out of :meth:`list_envs` and out of every
        ``/experiments`` answer until the file was rewritten, deleted or
        evicted. Re-reading an unreadable file costs one failed open per scan,
        on a file that is rare to begin with, so that is the cheaper mistake.
        The stat-failure branch below forgets the path for the same reason.

        ``st_ctime_ns`` and ``st_mode`` are still in the key, because
        permissions are the one way a file can change what it answers without
        its contents moving at all: ``chmod -r`` makes the next read fail
        without touching mtime, size or inode, so a record cached while the
        file was readable would otherwise go on being served after access was
        revoked. Both are cheap: they come from the same :func:`os.stat` the
        key already needs.

        What is left is a genuine, narrow window rather than an oversight: an
        **external, in-place** rewrite that leaves the file the same size and
        lands within the filesystem's timestamp resolution -- so the same
        whole second on a filesystem that keeps seconds -- is indistinguishable
        from no change at all. It cannot be closed by stat, only by hashing the
        contents, which means reading the file: precisely the work the cache
        exists to avoid, and a cost paid on every scan to cover a case that
        needs a second writer editing a file in place. Nothing Visdom itself
        writes can hit it, because every write in this class goes through
        :meth:`_atomic_write`, which drops the record outright and ends in
        :func:`os.replace`; and a rewrite of a *different* size is caught
        whatever the clock says.

        The parse happens outside the lock, so a scan of many envs does not
        serialise on it. Two threads may then parse the same file at once and
        store the same answer twice, which costs a repeated parse and nothing
        else. Taking the stat *before* the parse rather than after is deliberate
        too: if the file is rewritten in between, the newer content is filed
        under the older key, and the next read's key no longer matches, so it
        parses again. The cache can hand back something newer than its key says,
        never something older.

        What is held is bounded by ``meta_cache_bytes``: an estimate per record
        (see :func:`meta_weight`) is kept as a running total, and once it is
        over budget the least recently used records are dropped. Plot data is
        never in here, so the cache does not grow as a run plots more. What
        does grow without limit is everything the client chooses the size of --
        a metric history, but equally a parameter value, a tag or a
        description -- and the estimate charges all of it, so none of it can
        accumulate behind the budget's back. Evicting costs only a re-parse, so
        the ceiling trades memory for work and never for correctness.
        """
        path = os.path.abspath(path)
        try:
            stat = os.stat(path)
        except OSError:
            self._forget_meta(path)
            return UNREADABLE_META
        key = (
            stat.st_mtime_ns,
            stat.st_ctime_ns,
            stat.st_size,
            stat.st_ino,
            stat.st_dev,
            stat.st_mode,
        )
        with self._meta_lock:
            cached = self._meta_cache.get(path)
            if cached is not None and cached[0] == key:
                # Just used, so it moves to the end of the eviction order.
                # Re-assigning after a pop is what moves a key in a plain dict.
                self._meta_cache.pop(path)
                self._meta_cache[path] = cached
                return cached[1]
        record = self._parse_meta(path)
        if not record.readable:
            self._forget_meta(path)
            return record
        weight = meta_weight(record)
        with self._meta_lock:
            self._drop_locked(path)
            self._meta_cache[path] = (key, record, weight)
            self._meta_bytes += weight
            self._evict_locked()
        return record

    def _prune_meta(self, keep):
        """Forget cached records for files that are no longer on disk.

        ``keep`` is the set of env files :meth:`list_envs` just saw. Nothing
        else is ever cached, so anything outside it has been deleted -- without
        this, a directory that churns through env ids would grow the cache for
        the lifetime of the process.
        """
        with self._meta_lock:
            for path in [p for p in self._meta_cache if p not in keep]:
                self._drop_locked(path)

    def load_experiment(self, eid):
        """Read only ``eid``'s experiment blob; return ``None`` if it has none.

        One env is one JSON document, so the file still has to be parsed to
        reach the metadata inside it -- but the windows are dropped the moment
        the blob is taken, instead of being assembled into an env dict and
        handed to a caller that never wanted them. That is what makes a search
        across every environment cost one env's memory rather than all of them.

        Reading the metadata without the env is only safe because the file is
        authoritative for it: an experiment write persists immediately, and
        :meth:`serialize_env` skips envs that were never materialised precisely
        because their on-disk copy is current.

        The blob comes from :meth:`_read_meta`, so an unchanged file is not
        parsed again and two reads hand back the *same* object. That is already
        the contract a stored blob is held to -- ``ExperimentStore`` writes one
        by rebinding ``env["experiment"]`` to a freshly built ``to_dict``, never
        by editing the one it read, which is what lets
        ``_resident_experiments`` hand blobs to the storage worker uncopied. A
        caller that breaks it no longer corrupts only its own read.
        """
        if self.env_path is None:
            return None
        path = self._resolve_existing(eid)
        if path is None:
            return None
        return self._read_meta(path).experiment

    def list_envs(self):
        """Return the ids of all environments stored on disk.

        Hash-fallback files are recognised by their exact ``hash_<64 hex>.json``
        shape and resolved to the real id kept inside; every other ``.json`` file
        yields its filename stem. Sub-directories (e.g. ``view/``) are skipped.

        The ``hash_<64 hex>.json`` shape is only a naming convention, not a
        guarantee: a user-chosen eid that happens to equal that exact pattern
        (e.g. an environment literally named ``hash_<64 hex chars>``) is short
        enough to be written as an ordinary primary file, with none of the
        hash-fallback bookkeeping -- there is no ``name`` field inside it. Such
        a file is indistinguishable from a genuine hash-fallback file by name
        alone, so it is resolved the same way an unreadable ``name`` field
        would be: fall back to the filename stem. That stem is the correct id
        either way -- for a colliding primary file it *is* the real,
        already-escaped id, and for a hash-fallback file with unusable
        metadata it is still the best identifier available. Surfacing it beats
        silently hiding the environment.

        """
        if self.env_path is None or not os.path.isdir(self.env_path):
            return []
        envs = []
        seen = set()
        for name in os.listdir(self.env_path):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.env_path, name)
            if not os.path.isfile(path):
                continue
            seen.add(os.path.abspath(path))
            stem = name[: -len(".json")]
            if HASHED_ENV_RE.match(name):
                record = self._read_meta(path)
                if not record.readable:
                    continue
                envs.append(record.name if record.name is not None else stem)
            else:
                envs.append(stem)
        self._prune_meta(seen)
        return sorted(envs)

    def delete_env(self, eid):
        """Remove ``eid`` from disk; return ``True`` if a file was removed."""
        if self.env_path is None:
            return False
        path = self._resolve_existing(eid)
        if path is None:
            return False
        try:
            os.remove(path)
        except FileNotFoundError:
            return False
        except OSError as e:
            logging.error(f"Failed to delete {path}: {e}")
            return False
        # An id can be recreated, and a fresh file can land on the inode the
        # deleted one held, so the record goes now rather than waiting for a
        # stat to disagree with it.
        self._forget_meta(path)
        return True

    def env_exists(self, eid):
        """Return whether an environment ``eid`` is present on disk."""
        if self.env_path is None:
            return False
        return self._resolve_existing(eid) is not None

    def _layout_path(self):
        """Return the ``<env_path>/view/<LAYOUT_FILE>`` path for saved layouts."""
        return os.path.join(self.env_path, "view", LAYOUT_FILE)

    def save_layouts(self, layouts):
        """Write the saved-views layout string; no-op when persistence is off."""
        if self.env_path is None:
            return
        layout_path = self._layout_path()
        ensure_dir_exists(os.path.dirname(layout_path))
        with open(layout_path, "w") as fn:
            fn.write(layouts)

    def load_layouts(self):
        """Read the saved-views layout string; return ``""`` if none is stored."""
        if self.env_path is None:
            return ""
        layout_path = self._layout_path()
        if os.path.isfile(layout_path):
            with open(layout_path, "r") as fn:
                return fn.read()
        return ""

    def _undo_paths(self, eid):
        """Return ``(undo_dir, plain_path, hashed_path)`` for ``eid``'s undo file.

        ``hashed_path`` mirrors ``serialize_env``'s fallback for env ids whose
        plain filename would exceed the filesystem limit.
        """
        safe_eid = self._safe_eid(eid)
        undo_dir = os.path.join(self.env_path, UNDO_DIRNAME)
        plain = os.path.join(undo_dir, "{0}.json".format(safe_eid))
        hashed_id = hashlib.sha256(safe_eid.encode("utf-8")).hexdigest()
        hashed = os.path.join(undo_dir, "hash_{0}.json".format(hashed_id))
        return undo_dir, plain, hashed

    def load_undo(self, eid):
        """Return ``eid``'s undo stack (a list), or ``[]`` if missing/corrupt."""
        if self.env_path is None:
            return []
        _, plain, hashed = self._undo_paths(eid)
        path = plain if os.path.exists(plain) else hashed
        if not os.path.exists(path):
            return []
        data = read_json_file(path)
        if data is UNREADABLE_JSON:
            logging.warning(f"Could not read undo stack for env {eid}; ignoring it")
            return []
        return data if isinstance(data, list) else []

    def save_undo(self, eid, stack):
        """Atomically persist ``eid``'s undo stack; no-op when persistence is off."""
        if self.env_path is None:
            return
        undo_dir, plain, hashed = self._undo_paths(eid)
        os.makedirs(undo_dir, exist_ok=True)
        payload = json.dumps(stack, cls=NanSafeEncoder)
        try:
            target = plain
            self._atomic_write(plain, payload)
        except OSError as e:
            if e.errno != errno.ENAMETOOLONG and getattr(e, "winerror", None) != 206:
                raise
            target = hashed
            self._atomic_write(hashed, payload)
        return target

    def clear_undo(self, eid):
        """Remove ``eid``'s on-disk undo history; no-op when persistence is off."""
        if self.env_path is None:
            return
        _, plain, hashed = self._undo_paths(eid)
        for path in (plain, hashed):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    logging.error(f"Failed to delete undo file {path}: {e}")
