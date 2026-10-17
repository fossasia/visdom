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

import os
import threading
from collections import Counter

from visdom.data_model.json_store import JSONStore
from visdom.server.server_state import ServerState
from visdom.utils.server_utils import LazyEnvData
from visdom.utils.shared_utils import ensure_dir_exists

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
    """One workspace's state, a ``ServerState`` in every respect the handlers
    care about."""

    def __init__(self, *, storage_executor=None, **kwargs):
        super().__init__(**kwargs)
        if storage_executor is not None:
            # One worker per workspace would mean a thread per tenant held for
            # the life of the process, and the ordering the single worker exists
            # to guarantee holds just as well across workspaces as within one.
            self.storage_executor.shutdown(wait=False)
            self.storage_executor = storage_executor

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


class WorkspaceEnvManager:
    def __init__(self, base_env_path, default_state, eager=False, live_queue=None):
        self.base_env_path = base_env_path
        self.default_state = default_state
        self.eager = eager
        self.live_queue = live_queue
        self._states = {None: default_state}
        self._lock = threading.Lock()

    def space(self, workspace_id):
        """Return the state for a workspace id, creating it on first use.
        ``None`` returns the server's own (default) state."""
        if workspace_id is None:
            return self._states[None]
        with self._lock:
            state = self._states.get(workspace_id)
            if state is None:
                state = self._create_space(workspace_id)
                self._states[workspace_id] = state
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

    def _create_space(self, workspace_id):
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
            name = str(workspace_id)
            root = os.path.realpath(os.path.join(self.base_env_path, "workspaces"))
            env_path = os.path.join(root, name)
            if (
                name in ("", ".", "..")
                or os.path.basename(name) != name
                or os.path.dirname(os.path.realpath(env_path)) != root
            ):
                raise ValueError("invalid workspace id: {!r}".format(workspace_id))
            ensure_dir_exists(env_path)
            storage = JSONStore(env_path)

        settings = {
            name: getattr(self.default_state, name) for name in _INHERITED_SETTINGS
        }
        state = WorkspaceState(
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
