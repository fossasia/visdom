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

import time
from collections import Counter

import tornado.ioloop

from visdom.server.defaults import MAX_SOCKET_WAIT
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
        self.autosave = None

    # ----- layouts ----- #

    def get_layouts(self):
        return self._layouts

    def set_layouts(self, layouts):
        self._layouts = layouts

    def save_layouts(self):
        if self.env_path is None:
            warn_once(
                "Saving and loading to disk has no effect when running with "
                "env_path=None.",
                RuntimeWarning,
            )
            return
        self.storage.save_layouts(self._layouts)

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
        ``save_threshold`` updates it is written out immediately.
        """
        self.dirty_envs[eid] += 1
        if 0 < self.save_threshold <= self.dirty_envs[eid]:
            self.flush_envs([eid])

    def flush_envs(self, eids):
        """Persist the named environments, skipping any already saved.

        Runs on the IO loop rather than in an executor: saving serializes
        ``state``, and a background thread would be doing that while request
        handlers mutate the very dictionaries it is walking.

        Only environments the backend reports as written lose their mark, so one
        it declines is retried on the next pass rather than silently dropped. An
        environment deleted since it was marked has nothing left to save and is
        cleared too.
        """
        pending = [eid for eid in eids if self.dirty_envs.get(eid)]
        if not pending:
            return []
        written = self.storage.save_envs(self.state, pending)
        saved = set(written)
        for eid in pending:
            if eid in saved or eid not in self.state:
                del self.dirty_envs[eid]
        return written

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
