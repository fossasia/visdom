#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Shared server state facade.

Collects the server-wide data containers, configuration, and runtime state that
request handlers need, so that handlers depend on a single ``ServerState``
object instead of reaching directly into the ``Application`` instance. This is
the "accessor functions on the state" abstraction referenced by the handler
TODOs, and a natural future home for the data_model classes.
"""

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import tornado.ioloop

from visdom.server.defaults import MAX_SOCKET_WAIT
from visdom.utils.server_utils import run_on_storage_executor, snapshot_env
from visdom.utils.shared_utils import warn_once


class StateAccessorsMixin:
    """Expose the commonly used ``ServerState`` fields as ``self.<attr>`` on a
    handler, so existing handler method bodies keep working unchanged while the
    handler stores only a single ``self.server_state`` reference.

    These are read-only views: handlers mutate the underlying containers in
    place (e.g. ``self.state[eid] = ...``) but never rebind the attribute.
    """

    @property
    def state(self):
        return self.server_state.state

    @property
    def subs(self):
        return self.server_state.subs

    @property
    def sources(self):
        return self.server_state.sources

    @property
    def storage(self):
        return self.server_state.storage

    @property
    def storage_executor(self):
        return self.server_state.storage_executor

    @property
    def env_path(self):
        return self.server_state.env_path

    @property
    def port(self):
        return self.server_state.port

    @property
    def login_enabled(self):
        return self.server_state.login_enabled

    @property
    def readonly(self):
        return self.server_state.readonly

    @property
    def wrap_socket(self):
        return self.server_state.wrap_socket

    @property
    def user_credential(self):
        return self.server_state.user_credential

    @property
    def user_settings(self):
        return self.server_state.user_settings

    @property
    def max_text_lines(self):
        return self.server_state.max_text_lines

    @property
    def max_old_content(self):
        return self.server_state.max_old_content

    @property
    def max_image_history(self):
        return self.server_state.max_image_history

    @property
    def max_plot_history(self):
        return self.server_state.max_plot_history

    @property
    def live_updates(self):
        return self.server_state.live_updates

    @property
    def deleting_envs(self):
        return self.server_state.deleting_envs

    def mark_dirty(self, eid):
        """Mark an environment for persistence through the shared state."""
        return self.server_state.mark_dirty(eid)


class ServerState:
    """Single shared facade over the server's data containers, configuration,
    and runtime state. Handlers depend on this rather than on ``Application``.
    """

    def __init__(
        self,
        *,
        state,
        subs,
        sources,
        storage,
        env_path,
        port,
        login_enabled,
        readonly,
        user_credential,
        base_url,
        wrap_socket,
        user_settings,
        max_text_lines,
        max_old_content,
        max_image_history,
        max_plot_history,
        save_interval,
        save_threshold,
    ):
        # Shared mutable containers (passed by reference, never rebound here).
        self.state = state
        self.subs = subs
        self.sources = sources
        self.storage = storage

        # Disk work runs on a single worker, so writes stay ordered with
        # respect to each other and to the deletes queued behind them.
        self.storage_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="visdom-storage"
        )

        # Startup configuration (effectively immutable after construction).
        self.env_path = env_path
        self.port = port
        self.login_enabled = login_enabled
        self.readonly = readonly
        self.user_credential = user_credential
        self.base_url = base_url
        self.wrap_socket = wrap_socket
        self.user_settings = user_settings
        self.max_text_lines = max_text_lines
        self.max_old_content = max_old_content
        self.max_image_history = max_image_history
        self.max_plot_history = max_plot_history
        self.save_interval = save_interval
        self.save_threshold = save_threshold

        # Runtime values that get reassigned while the server runs. These are
        # the reason this facade exists: a value copied onto a handler would go
        # stale, but a call through ``server_state`` never does.
        self._layouts = self._load_layouts()
        self._socket_wrap_monitor = None
        self.dirty_envs = Counter()
        self.saving_envs = set()
        # Environments whose removal is queued or running on the worker. A read
        # that started before one of those deletes must not file what it read
        # back into ``state`` when it resumes, or the deleted env is listed
        # again for as long as the server runs.
        self.deleting_envs = {}
        self.autosave = None
        # Disk work is handed to one worker thread rather than run on the loop.
        # A single worker keeps the writes serialized, so two saves of the same
        # environment cannot interleave and leave a half-written file behind.
        self.storage_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="visdom-storage"
        )
        # Set by the application once the handlers it drives can be imported;
        # a queue built here would need experiments_handler, which needs the
        # handlers that need this module.
        self.live_updates = None

    # ----- layouts ----- #

    def get_layouts(self):
        return self._layouts

    def set_layouts(self, layouts):
        self._layouts = layouts

    def save_layouts(self, layouts=None):
        """Persist the layout blob, defaulting to the one held in memory.

        A caller writing from the storage worker passes the snapshot it took on
        the loop, so the write records the layouts as they were when it was
        scheduled rather than whatever a later edit has since installed.
        """
        if self.env_path is None:
            warn_once(
                "Saving and loading to disk has no effect when running with "
                "env_path=None.",
                RuntimeWarning,
            )
            return
        self.storage.save_layouts(self._layouts if layouts is None else layouts)

    def _load_layouts(self):
        if self.env_path is None:
            warn_once(
                "Saving and loading to disk has no effect when running with "
                "env_path=None.",
                RuntimeWarning,
            )
            return ""
        return self.storage.load_layouts()

    # ----- environment persistence ----- #

    def mark_dirty(self, eid):
        """Record that ``eid`` has changed in memory and is not yet on disk.

        Environments are saved on a timer rather than on every write, so a busy
        one would otherwise sit unsaved for a whole interval; once it has taken
        ``save_threshold`` updates its write is queued straight away instead of
        waiting for the next tick.
        """
        self.dirty_envs[eid] += 1
        if 0 < self.save_threshold <= self.dirty_envs[eid]:
            self.flush_envs([eid])

    def flush_envs(self, eids):
        """Persist the named environments off the loop; return the write future.

        Serializing an environment is the expensive half of a save, so it
        happens on the storage worker rather than here. Only a deep copy taken
        on the loop travels there: handing a thread ``state`` itself would have
        it walking dictionaries that request handlers are still mutating.

        ``None`` comes back when there is nothing to do -- nothing marked, or
        everything marked has since been deleted or was never read off disk, in
        which case the copy on disk is already current and the mark is dropped.
        Environments with a write already in flight keep their mark and are
        picked up by the next pass instead of queueing a second write.
        """
        pending = {}
        snapshots = {}
        for eid in eids:
            marked = self.dirty_envs.get(eid)
            if not marked or eid in self.saving_envs:
                continue
            env = self.state.get(eid)
            snapshot = None if env is None else snapshot_env(env)
            if snapshot is None:
                del self.dirty_envs[eid]
                continue
            pending[eid] = marked
            snapshots[eid] = snapshot

        if not snapshots:
            return None

        self.saving_envs.update(snapshots)
        future = run_on_storage_executor(
            self, self.storage.save_envs, snapshots, list(snapshots)
        )
        future.add_done_callback(lambda done: self._settle_flush(done, pending))
        return future

    def _settle_flush(self, future, pending):
        """Clear the marks the completed write covered, and only those.

        An environment changed while its write was in flight was not in the
        snapshot the worker serialized, so its mark is decremented by what was
        written rather than cleared: the change stays pending for the next
        pass. One the backend declined, or a write that raised, keeps its mark
        in full and is retried.
        """
        self.saving_envs.difference_update(pending)
        try:
            written = future.result()
        except Exception:
            logging.exception("Automatic environment save failed; will retry")
            return
        for eid in written:
            remaining = self.dirty_envs.get(eid, 0) - pending[eid]
            if remaining > 0:
                self.dirty_envs[eid] = remaining
            else:
                self.dirty_envs.pop(eid, None)

    def flush_dirty(self):
        """Persist every environment changed since the last save."""
        return self.flush_envs(list(self.dirty_envs))

    def start_autosave(self):
        """Begin saving changed environments every ``save_interval`` seconds.

        A no-op when autosaving is disabled or already running. Ticks with
        nothing dirty cost no IO.
        """
        if self.autosave is None and self.save_interval > 0:
            self.autosave = tornado.ioloop.PeriodicCallback(
                self.flush_dirty, self.save_interval * 1000
            )
            self.autosave.start()
        return self.autosave

    def stop_autosave(self):
        """Stop the timer, so no further tick can queue a write."""
        if self.autosave is not None:
            self.autosave.stop()
            self.autosave = None

    def shutdown_storage(self):
        """Stop autosaving, drain queued writes, then flush the final state.

        The timer goes first so a tick cannot queue work behind the drain.
        Draining next stops an already-queued write from landing after the
        final save and putting a stale env back on disk. The final save covers
        whatever was still marked dirty, so the marks are cleared with it.
        """
        self.stop_autosave()
        self.storage_executor.shutdown(wait=True)
        self.storage.save_all(self.state)
        self.dirty_envs.clear()
        self.saving_envs.clear()

    # ----- polling socket monitor ----- #

    def ensure_socket_monitor(self, interval_ms=15000):
        """Start the periodic monitor that reaps stale polling sockets,
        creating it on first use."""
        if self._socket_wrap_monitor is None:
            self._socket_wrap_monitor = tornado.ioloop.PeriodicCallback(
                self.reap_stale_connections, interval_ms
            )
        if not self._socket_wrap_monitor.is_running():
            self._socket_wrap_monitor.start()

    def reap_stale_connections(self):
        """Close polling connections that have stopped reading."""
        if len(self.subs) > 0 or len(self.sources) > 0:
            for connection in list(self.subs.values()):
                if (
                    hasattr(connection, "last_read_time")
                    and time.time() - connection.last_read_time > MAX_SOCKET_WAIT
                ):
                    connection.close()
            for connection in list(self.sources.values()):
                if (
                    hasattr(connection, "last_read_time")
                    and time.time() - connection.last_read_time > MAX_SOCKET_WAIT
                ):
                    connection.close()
        else:
            self.stop_socket_monitor()

    def stop_socket_monitor(self):
        if self._socket_wrap_monitor is not None:
            self._socket_wrap_monitor.stop()
