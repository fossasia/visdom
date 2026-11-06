#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Owns one isolated slice of server state per workspace, so a multi-tenant
deployment keeps each workspace's environments, disk storage, and realtime
subscribers separate.

Each workspace gets its own ``ServerState``, the same facade a single-tenant
server has, differing only in which containers and storage it points at. Once a
request's workspace is resolved, ``bind_workspace`` swaps the handler's
``server_state`` for that workspace's one, so every accessor the handler already
reads through resolves inside that workspace without the handler knowing.

Workspace ``None`` maps to the server's own state, so plain single-tenant or
local visdom behaves exactly as before.
"""

import asyncio
import json
import os
import shutil
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from visdom.data_model.json_store import HASHED_ENV_RE, JSONStore
from visdom.server.server_state import ServerState
from visdom.utils.server_utils import LazyEnvData
from visdom.utils.shared_utils import ensure_dir_exists

# How long a disk scan is reused before the directories are walked again.
DISK_SCAN_TTL = 30.0

# Configuration a workspace inherits from the server it runs inside. Only the
# containers and the storage differ per workspace; how the server behaves does
# not change with which tenant is asking.
_INHERITED_SETTINGS = (
    "port",
    "login_enabled",
    "readonly",
    "user_credential",
    "base_url",
    "wrap_socket",
    "user_settings",
    "max_text_lines",
    "max_old_content",
    "max_image_history",
    "max_plot_history",
    "save_interval",
    "save_threshold",
)


def build_state(storage, eager=False, ensure_main=True):
    """Build an in-memory env-state dict from a storage backend, mirroring
    Application.load_state but reusable for any workspace's storage."""
    state = {}
    if storage is None:
        return {"main": {"jsons": {}, "reload": {}}} if ensure_main else {}
    for eid in storage.list_envs():
        if eager:
            env_data = storage.load_env(eid)
            if not isinstance(env_data, dict):
                env_data = {}
            state[eid] = dict(env_data)
            state[eid].setdefault("jsons", {})
            state[eid].setdefault("reload", {})
        else:
            state[eid] = LazyEnvData(storage, eid)
    if ensure_main and "main" not in state:
        state["main"] = {"jsons": {}, "reload": {}}
        storage.save_env("main", state["main"])
    return state


class WorkspaceState(ServerState):
    """One workspace's state, and what an operator can ask about it.

    A ServerState in every respect the handlers care about. The additions
    are the slug, which the proxy hashes on and this process would otherwise
    never learn, and enough activity to answer whether anyone is using the
    workspace at all.
    """

    def __init__(self, *, slug=None, storage_executor=None, **kwargs):
        super().__init__(**kwargs)
        self.slug = slug
        self.last_write_at = None
        # Counted here because a process serving many workspaces cannot have its
        # own CPU divided between them afterwards. These are running totals for
        # the life of the process, which is what a scraper expects of a counter.
        self.writes = 0
        self.broadcasts = 0
        self.broadcast_bytes = 0
        self.active_hour = None
        self.active_minutes_mask = 0
        if storage_executor is not None:
            # One worker per workspace would mean a thread per tenant held for
            # the life of the process, and the ordering the single worker exists
            # to guarantee holds just as well across workspaces as within one.
            self.storage_executor.shutdown(wait=False)
            self.storage_executor = storage_executor

    def mark_dirty(self, eid):
        """Persist as usual, and remember that this workspace was written to."""
        now = time.time()
        self.last_write_at = now
        self.writes += 1
        self.mark_active_minute(now)
        return super().mark_dirty(eid)

    def mark_active_minute(self, now):
        """Record that this minute of the hour had work in it.

        Billing wants time spent working, which is not the same as time
        connected: a dashboard left open overnight is idle, and a run that
        writes at nine and again at five did not work for eight hours. A minute
        with at least one write in it is the honest unit, and the smallest one
        that does not simply restate the write count.

        The hour is held as sixty bits rather than a count so that instances can
        be combined. Three of them serving the same workspace in the same minute
        have done one minute of work between them, and a union says so where a
        sum would say three.
        """
        hour = int(now // 3600)
        if hour != self.active_hour:
            self.active_hour = hour
            self.active_minutes_mask = 0
        self.active_minutes_mask |= 1 << int((now % 3600) // 60)

    def record_broadcast(self, messages, size):
        """Note messages pushed to this workspace's viewers.

        Counted at the push rather than per subscriber pair, so a message going
        to ten viewers is ten messages and ten times the bytes: what is being
        measured is work the instance did, and it did it ten times.
        """
        self.broadcasts += messages
        self.broadcast_bytes += size

    def flush_envs(self, eids):
        """Persist as usual, but never hold marks a save can never clear.

        ``flush_envs`` keeps the mark on anything the backend did not report as
        written, so it is retried rather than silently dropped. With no path to
        write to nothing is ever reported, so the marks would accumulate for the
        life of the process against a workspace that is memory-only by
        construction. ``None`` is what a caller gets when there was no write to
        wait on, which is exactly the case here.
        """
        if self.env_path is None:
            for eid in list(eids):
                self.dirty_envs.pop(eid, None)
            return None
        return super().flush_envs(eids)

    def last_active_at(self):
        """When this workspace was last written to, as a unix timestamp.

        Prefers the in-memory mark, which is exact but resets when the instance
        restarts, and falls back to the mtime of the workspace's directory so a
        restart reports a stale time rather than none at all.
        """
        if self.last_write_at is not None:
            return self.last_write_at
        env_path = getattr(self.storage, "env_path", None)
        if not env_path:
            return None
        try:
            return os.path.getmtime(env_path)
        except OSError:
            return None

    def activity(self):
        """Live socket counts for this workspace, plus when it was last written.

        Readers and writers are counted separately because they mean different
        things to an operator: a workspace with viewers but no sources is being
        watched, one with sources and no viewers is being fed by a training run
        nobody is looking at.
        """
        return {
            "slug": self.slug,
            "viewers": len(self.subs),
            "writers": len(self.sources),
            "last_active_at": self.last_active_at(),
            "writes": self.writes,
            "broadcasts": self.broadcasts,
            "broadcast_bytes": self.broadcast_bytes,
            "active_hour": self.active_hour,
            "active_minutes_mask": self.active_minutes_mask,
        }


class WorkspaceEnvManager:
    def __init__(self, base_env_path, default_state, eager=False, live_queue=None):
        self.base_env_path = base_env_path
        self.default_state = default_state
        self.eager = eager
        self.live_queue = live_queue
        self._states = {None: default_state}
        self._lock = threading.Lock()
        self._disk_lock = threading.Lock()
        self._scan_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="workspace-scan"
        )
        self._disk_cache = {}
        self._disk_scanned_at = None

    def space(self, workspace_id, slug=None):
        """Return the state for a workspace id, creating it on first use.
        None returns the server's own (default) state."""
        if workspace_id is None:
            return self._states[None]
        workspace_id = canonical_id(workspace_id)
        with self._lock:
            state = self._states.get(workspace_id)
            if state is None:
                state = self._create_space(workspace_id, slug)
                self._states[workspace_id] = state
            if slug and state.slug != slug:
                state.slug = slug
            return state

    def spaces(self):
        """Every state built so far, the server's own included.

        Returned as a list rather than a live view so the autosave timer can walk
        it without holding the lock while it writes to disk.
        """
        with self._lock:
            return list(self._states.values())

    def workspace_spaces(self):
        """Every state that belongs to a workspace, as (id, state) pairs.

        Excludes the default one, which no proxy ever routes to.
        """
        with self._lock:
            return [
                (wid, state) for wid, state in self._states.items() if wid is not None
            ]

    async def on_scan_thread(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self._scan_pool, fn, *args
        )

    async def stored_workspaces_off_loop(self):
        return await asyncio.get_running_loop().run_in_executor(
            self._scan_pool, self.stored_workspaces
        )

    def stored_workspaces(self):
        """Every workspace with a directory on disk, with its size and last write.

        workspace_spaces only knows the workspaces something has touched since
        this process started, so on its own it reports a freshly restarted server
        as having no workspaces at all. Disk is the durable record, and it is what
        makes a dormant workspace distinguishable from one that has merely not
        been visited yet.

        Cached, because this walks every workspace's files and neither a size nor
        a last write needs to be accurate to the second.
        """
        if self.base_env_path is None:
            return {}

        now = time.monotonic()
        with self._disk_lock:
            if (
                self._disk_scanned_at is not None
                and now - self._disk_scanned_at < DISK_SCAN_TTL
            ):
                return self._disk_cache

        root = os.path.join(self.base_env_path, "workspaces")
        found = {}
        try:
            entries = list(os.scandir(root))
        except OSError:
            entries = []

        for entry in entries:
            if not entry.is_dir():
                continue
            total = 0
            newest = 0.0
            try:
                for item in os.scandir(entry.path):
                    try:
                        stat = item.stat()
                    except OSError:
                        continue
                    total += stat.st_size
                    newest = max(newest, stat.st_mtime)
            except OSError:
                continue
            found[entry.name] = {"bytes": total, "last_active_at": newest or None}

        with self._disk_lock:
            self._disk_cache = found
            self._disk_scanned_at = now
            return self._disk_cache

    def loaded_space(self, workspace_id):
        """The state for a workspace only if something has already built it.

        ``space`` creates one on demand, which is right for a request arriving
        for that workspace and wrong for a caller sweeping every workspace on
        disk: building a state writes a fresh ``main`` into a workspace that had
        been dormant, so a tidy-up would leave a file behind everywhere it went.
        """
        with self._lock:
            return self._states.get(canonical_id(workspace_id))

    def workspace_storage(self, workspace_id):
        """A store over one workspace's directory, without building its state.

        For acting on the files of a workspace nothing has loaded. A store is
        just a path, so this costs nothing and keeps the file layout in the one
        place that knows it.
        """
        if self.base_env_path is None:
            return JSONStore(None)
        return JSONStore(self._workspace_path(workspace_id))

    def workspace_directory(self, workspace_id):
        """Where one workspace's files live, or ``None`` for anything else.

        Only a well-formed workspace id names a directory, so an id arriving
        over the wire cannot point this anywhere else on the disk.
        """
        if self.base_env_path is None:
            return None
        try:
            canonical = str(uuid.UUID(str(workspace_id)))
        except ValueError:
            return None
        return os.path.join(self.base_env_path, "workspaces", canonical)

    def forget(self, workspace_id):
        """Stop holding a workspace, returning the state it had, or ``None``.

        Autosave walks the states held here, so a forgotten workspace is never
        written out again.
        """
        if workspace_id is None:
            return None
        with self._lock:
            state = self._states.pop(canonical_id(workspace_id), None)
        with self._disk_lock:
            self._disk_scanned_at = None
        return state

    def expired_envs(self, workspace_id, older_than_days, keep=("main",)):
        """Environments in one workspace nobody has written to for that long.

        Read from disk rather than from memory, because a workspace nothing has
        touched since this process started holds no state here at all, and a
        dormant workspace is exactly the one with the oldest environments in it.

        ``main`` is kept whatever its age. It is the environment a client writes
        to when it names none, so removing it makes a workspace look broken
        rather than tidied.
        """
        if self.base_env_path is None or older_than_days is None:
            return []

        cutoff = time.time() - (older_than_days * 86400)
        directory = self._workspace_path(workspace_id)
        expired = []
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return []

        for entry in entries:
            if not entry.is_file() or not entry.name.endswith(".json"):
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            if stat.st_mtime >= cutoff:
                continue
            eid = _stored_eid(entry)
            if eid is not None and eid not in keep:
                expired.append(
                    {"eid": eid, "bytes": stat.st_size, "last_written": stat.st_mtime}
                )
        return sorted(expired, key=lambda item: item["last_written"])

    def _workspace_path(self, workspace_id):
        name = canonical_id(workspace_id)
        root = os.path.realpath(os.path.join(self.base_env_path, "workspaces"))
        path = os.path.join(root, name)
        if (
            name in ("", ".", "..")
            or os.path.basename(name) != name
            or os.path.dirname(os.path.realpath(path)) != root
        ):
            raise ValueError("invalid workspace id: {!r}".format(workspace_id))
        return path

    def _create_space(self, workspace_id, slug=None):
        """Build a workspace's state, inheriting the server's configuration.

        The containers and the storage are new; everything about how the server
        behaves is copied, so a workspace cannot end up with different limits or
        a different save interval from the server it runs in.
        """
        if self.base_env_path is None:
            # A store over no path, not the absence of a store: the application
            # does the same for its own state, and the persistence calls then
            # no-op instead of having to be guarded at every call site.
            storage = JSONStore(None)
            env_path = None
        else:
            env_path = self._workspace_path(workspace_id)
            ensure_dir_exists(env_path)
            storage = JSONStore(env_path)

        settings = {
            name: getattr(self.default_state, name) for name in _INHERITED_SETTINGS
        }
        state = WorkspaceState(
            slug=slug,
            storage_executor=self.default_state.storage_executor,
            state=build_state(storage, eager=self.eager),
            subs={},
            sources={},
            storage=storage,
            env_path=env_path,
            **settings,
        )
        state.live_updates = None if self.live_queue is None else self.live_queue(state)
        # A handler bound to this workspace has to be able to rebind, so the
        # managers travel with the state rather than only with the server's.
        state.workspace_manager = getattr(self.default_state, "workspace_manager", None)
        state.workspace_env_manager = self
        state.dirty_envs = Counter()
        return state


def canonical_id(workspace_id):
    if workspace_id is None:
        return None
    try:
        return str(uuid.UUID(str(workspace_id)))
    except ValueError:
        return str(workspace_id)


def remove_directory(path):
    """Delete a workspace directory, returning the bytes it held.

    ``None`` when there was no directory, which is the normal answer from every
    instance but the first one asked, since they share the disk.
    """
    if path is None or not os.path.isdir(path):
        return None
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return None
    return total


def _stored_eid(entry):
    stem = entry.name[: -len(".json")]
    if not HASHED_ENV_RE.match(entry.name):
        return stem
    try:
        with open(entry.path, "r", encoding="utf-8") as fn:
            data = json.load(fn)
    except (OSError, UnicodeError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("name"), str):
        return data["name"]
    return stem
