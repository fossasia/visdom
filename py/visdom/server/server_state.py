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
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import tornado.ioloop

from visdom.server.defaults import MAX_SOCKET_WAIT, MIN_ENV_IDLE_SECONDS
from visdom.utils.server_utils import (
    LazyEnvData,
    run_on_storage_executor,
    snapshot_env,
)
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

    def track_saved_changes(self, future, covered):
        self.server_state.track_saved_changes(future, covered)

    @property
    def dirty_envs(self):
        return self.server_state.dirty_envs

    @property
    def held_envs(self):
        return self.server_state.held_envs

    @property
    def deleting_envs(self):
        return self.server_state.deleting_envs

    @property
    def env_delete_watches(self):
        return self.server_state.env_delete_watches

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
        env_idle_seconds=0,
    ):
        # Shared mutable containers (passed by reference, never rebound here).
        self.state = state
        self.subs = subs
        self.sources = sources
        self.storage = storage

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
        if env_idle_seconds < 0 or 0 < env_idle_seconds < MIN_ENV_IDLE_SECONDS:
            raise ValueError(
                "env_idle_seconds must be 0 (off) or at least %d seconds"
                % MIN_ENV_IDLE_SECONDS
            )
        self.env_idle_seconds = env_idle_seconds

        # Runtime values that get reassigned while the server runs. These are
        # the reason this facade exists: a value copied onto a handler would go
        # stale, but a call through ``server_state`` never does.
        self._layouts = self._load_layouts()
        self._socket_wrap_monitor = None
        self.dirty_envs = Counter()
        self._pending_save_counts = {}
        # When each environment last took a write, on the monotonic clock. Read
        # by ``evict_idle_envs`` to tell an env that is merely resident from one
        # that is in use; only kept while eviction is on, and pruned by it.
        self.last_dirty = {}
        # Envs a request is relying on staying resident -- one being written
        # directly, or read across awaits. Kept apart from ``dirty_envs``: that
        # counter belongs to the autosave, which subtracts what it recorded when
        # its write settles, and a second owner would be released twice.
        self.held_envs = Counter()
        self.env_eviction = None
        self.saving_envs = set()
        # Environments whose removal is queued or running on the worker. A read
        # that started before one of those deletes must not file what it read
        # back into ``state`` when it resumes, or the deleted env is listed
        # again for as long as the server runs.
        self.deleting_envs = {}
        # Watches held by requests that are off the loop with an env in mind,
        # keyed by that env. ``deleting_envs`` is dropped as soon as the delete
        # lands, so a request that resumes after it would see no trace of it;
        # these are told as the delete starts and keep saying so until their
        # holder is done.
        self.env_delete_watches = {}
        self.autosave = None
        # Disk work is handed to one worker thread rather than run on the loop.
        # A single worker keeps the writes serialized, so two saves of the same
        # environment cannot interleave and leave a half-written file behind.
        self.storage_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="visdom-storage"
        )
        self._storage_shut_down = False
        # ``shutdown_storage`` has two callers -- the graceful stop and the
        # ``atexit`` hook -- and nothing orders them: a server embedded in a
        # thread runs the first off the main thread, where the second always
        # runs. Only the flag above keeps the second pass from saving again,
        # and it is not set until the final save has returned, so without this
        # both could be inside ``save_all`` at once, writing the same files
        # from two threads.
        self._storage_shutdown_lock = threading.Lock()
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
        if self.env_idle_seconds > 0:
            self.last_dirty[eid] = time.monotonic()
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
        self.track_saved_changes(future, pending)
        future.add_done_callback(lambda done: self._settle_flush(done, pending))
        return future

    def _settle_flush(self, future, pending):
        """Release the autosave slot and report storage errors."""
        self.saving_envs.difference_update(pending)
        if future.cancelled():
            return
        try:
            future.result()
        except Exception:
            logging.exception("Automatic environment save failed; will retry")
            return

    def track_saved_changes(self, future, covered):
        """Share acknowledgement of dirty marks across manual and automatic saves.

        Two snapshots can cover the same edits. Each successful write takes
        those marks out of the other pending counts before they can settle.
        """
        token = object()
        originals = {eid: dict.get(self.state, eid) for eid in covered}
        for eid, count in covered.items():
            self._pending_save_counts.setdefault(eid, {})[token] = count

        def settle(done):
            written = (
                set(done.result())
                if not done.cancelled() and done.exception() is None
                else set()
            )
            for eid in covered:
                pending = self._pending_save_counts[eid]
                count = pending.pop(token)
                if eid in written and dict.get(self.state, eid) is originals[eid]:
                    remaining = self.dirty_envs[eid] - count
                    if remaining > 0:
                        self.dirty_envs[eid] = remaining
                    else:
                        self.dirty_envs.pop(eid, None)
                    for other in pending:
                        pending[other] = max(0, pending[other] - count)
                if not pending:
                    del self._pending_save_counts[eid]

        future.add_done_callback(settle)

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

    def _last_touched(self, eid, env):
        """When ``eid`` was last read or written, or ``None`` if never this run."""
        stamps = [self.last_dirty.get(eid)]
        if isinstance(env, LazyEnvData):
            stamps.append(env.last_access)
        accessed = getattr(self.state, "accessed", None)
        if accessed is not None:
            stamps.append(accessed.get(eid))
        stamps = [stamp for stamp in stamps if stamp is not None]
        return max(stamps) if stamps else None

    def _evictable(self, eid, env, now):
        """Whether ``eid`` is idle, resident and safe to drop right now."""
        if (
            env is None
            or eid in self.dirty_envs
            or eid in self.saving_envs
            or eid in self.deleting_envs
            or self.held_envs.get(eid)
            or self.env_delete_watches.get(eid)
        ):
            return False
        if isinstance(env, LazyEnvData) and not env.is_loaded:
            return False
        touched = self._last_touched(eid, env)
        return touched is not None and now - touched >= self.env_idle_seconds

    def _viewed_envs(self):
        viewed = set()
        for subscriber in self.subs.values():
            selection = getattr(subscriber, "eid", None)
            if isinstance(selection, str):
                viewed.add(selection)
            elif isinstance(selection, (list, tuple)):
                viewed.update(selection)
        return viewed

    def _existing_envs(self, eids):
        return {eid for eid in eids if self.storage.env_exists(eid)}

    async def evict_idle_envs(self):
        """Drop saved, idle environments from memory; return the ids dropped.

        Without this every environment a client has ever opened or written to
        stays in ``state`` until it is deleted or the server restarts, so a
        long-lived server only ever grows. An env goes back to a cold
        ``LazyEnvData`` -- the same thing it was at startup -- once it has been
        untouched for ``env_idle_seconds`` and its on-disk copy is current, and
        is read back transparently the next time anything asks for it.

        Skipped, because dropping them would lose or resurrect data: anything
        dirty, being written, or being deleted; anything with no file on disk;
        and anything not touched at all since startup, such as an env loaded
        with ``-eager_data_loading`` that nobody has asked for. Browser views
        and requests using an env across awaits keep it resident.

        The file check runs on the storage worker, behind any queued write, so a
        slow filesystem never stalls the loop. Everything is decided again on
        the loop once it answers, because the env may have been used meanwhile.
        """
        if self.env_idle_seconds <= 0 or self.env_path is None:
            return []
        now = time.monotonic()
        accessed = getattr(self.state, "accessed", None)
        # Startup can register thousands of disk-only environments. Only an
        # access or write can have made one eligible for eviction.
        touched = (
            self.last_dirty.keys() | accessed.keys()
            if accessed is not None
            else self.state.keys()
        )
        viewed = self._viewed_envs()
        candidates = []
        for eid in touched:
            env = dict.get(self.state, eid)
            if env is None or (isinstance(env, LazyEnvData) and not env.is_loaded):
                self.last_dirty.pop(eid, None)
                if accessed is not None:
                    accessed.pop(eid, None)
            elif eid not in viewed and self._evictable(eid, env, now):
                candidates.append(eid)
        evicted = []
        if candidates:
            try:
                present = await tornado.ioloop.IOLoop.current().run_in_executor(
                    self.storage_executor, self._existing_envs, candidates
                )
            except Exception:
                logging.warning(
                    "Idle environment check failed; will retry", exc_info=True
                )
                return []
            now = time.monotonic()
            viewed = self._viewed_envs()
            for eid in candidates:
                env = dict.get(self.state, eid)
                if eid in viewed or not self._evictable(eid, env, now):
                    continue
                if eid not in present:
                    logging.debug("Not evicting %r: no file on disk", eid)
                    continue
                if isinstance(env, LazyEnvData):
                    env.unload()
                else:
                    self.state[eid] = LazyEnvData(self.storage, eid)
                self.last_dirty.pop(eid, None)
                if accessed is not None:
                    accessed.pop(eid, None)
                evicted.append(eid)
        return evicted

    def eviction_interval_ms(self):
        """How often the idle sweep runs.

        A few times per idle period keeps an env from overstaying by much,
        without scanning ``state`` more than once a second or waiting longer
        than a minute between sweeps.
        """
        return max(1.0, min(60.0, self.env_idle_seconds / 4.0)) * 1000

    def stop_env_eviction(self):
        """Stop the idle sweep; started by ``Application.start_env_eviction``."""
        if self.env_eviction is not None:
            self.env_eviction.stop()
            self.env_eviction = None

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

        Idempotent: the graceful shutdown calls this, and the ``atexit`` hook
        that covers a teardown which never reaches it calls it again. A second
        pass must not re-run ``save_all`` -- the executor is already gone, so
        anything written after the first pass could only be state the process
        never served.

        Only a final save that succeeded counts as shut down. If ``save_all``
        raises, the ``atexit`` call tries it again instead of returning early
        and leaving the changed environments in memory only. Stopping the timer
        and the executor again on that retry is harmless.

        That retry is also why the flag alone cannot be the whole guard: it is
        not set until the save has returned, so two callers arriving at once
        would both find it clear and write the same environment files from two
        threads. The lock serializes them -- the second waits, then finds the
        flag set and returns, which also makes it a real barrier rather than a
        hint, so ``atexit`` never outruns a save still running on the loop. A
        caller unwound out of the save, a signal handler raising ``SystemExit``
        mid-write being the usual one, releases the lock on the way out, so the
        retry can still take it.
        """
        with self._storage_shutdown_lock:
            if self._storage_shut_down:
                return
            self.stop_autosave()
            self.stop_env_eviction()
            self.storage_executor.shutdown(wait=True)
            self.storage.save_all(self.state)
            self._storage_shut_down = True
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

    # ----- shutdown ----- #

    def close_connections(self):
        """Close every open client connection and forget it.

        Shutdown used to rebind ``Application.subs``/``sources`` to empty
        lists, which left the sockets themselves open and this state -- the
        holder of the real dictionaries every handler registers into --
        untouched. Closing a connection lets its handler unregister itself;
        clearing the containers afterwards covers a connection whose close
        path never ran, and a handler that closes twice is harmless.
        """
        self.stop_socket_monitor()
        for connections in (self.subs, self.sources):
            for connection in list(connections.values()):
                try:
                    connection.close()
                except Exception:
                    logging.exception("Failed to close a client connection")
            connections.clear()
