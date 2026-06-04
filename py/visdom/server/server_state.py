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

import os

import tornado.ioloop

from visdom.utils.shared_utils import warn_once, ensure_dir_exists
from visdom.server.defaults import LAYOUT_FILE


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


class ServerState:
    """Single shared facade over the server's data containers, configuration,
    and runtime state. Handlers depend on this rather than on ``Application``.
    """

    def __init__(
        self,
        app,
        *,
        state,
        subs,
        sources,
        env_path,
        port,
        login_enabled,
        readonly,
        user_credential,
        base_url,
        wrap_socket,
        user_settings,
    ):
        # Retained solely to construct nested socket wrappers (see
        # ``spawn_socket``); handlers must not touch the app directly.
        self._app = app

        # Shared mutable containers (passed by reference, never rebound here).
        self.state = state
        self.subs = subs
        self.sources = sources

        # Startup configuration (effectively immutable after construction).
        self.env_path = env_path
        self.port = port
        self.login_enabled = login_enabled
        self.readonly = readonly
        self.user_credential = user_credential
        self.base_url = base_url
        self.wrap_socket = wrap_socket
        self.user_settings = user_settings

        # Runtime values that get reassigned while the server runs. These are
        # the reason this facade exists: a value copied onto a handler would go
        # stale, but a call through ``server_state`` never does.
        self._layouts = self._load_layouts()
        self._socket_wrap_monitor = None

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
        layout_dir = os.path.join(self.env_path, "view")
        ensure_dir_exists(layout_dir)

        layout_filepath = os.path.join(layout_dir, LAYOUT_FILE)
        with open(layout_filepath, "w") as fn:
            fn.write(self._layouts)

    def _load_layouts(self):
        if self.env_path is None:
            warn_once(
                "Saving and loading to disk has no effect when running with "
                "env_path=None.",
                RuntimeWarning,
            )
            return ""
        layout_dir = os.path.join(self.env_path, "view")
        layout_filepath = os.path.join(layout_dir, LAYOUT_FILE)
        if os.path.isfile(layout_filepath):
            with open(layout_filepath, "r") as fn:
                return fn.read()
        else:
            ensure_dir_exists(layout_dir)
            return ""

    # ----- polling socket monitor ----- #

    def ensure_socket_monitor(self, callback, interval_ms=15000):
        """Start the periodic monitor that reaps stale polling sockets,
        creating it on first use."""
        if self._socket_wrap_monitor is None:
            self._socket_wrap_monitor = tornado.ioloop.PeriodicCallback(
                callback, interval_ms
            )
        if not self._socket_wrap_monitor.is_running():
            self._socket_wrap_monitor.start()

    def stop_socket_monitor(self):
        if self._socket_wrap_monitor is not None:
            self._socket_wrap_monitor.stop()

    # ----- nested socket wrapper construction ----- #

    def spawn_socket(self, cls, request=None):
        """Construct and initialize a polling socket wrapper.

        This is the one place that still needs the ``Application`` (tornado
        wrappers are initialized from it), keeping that coupling out of the
        handlers themselves.
        """
        wrapper = cls()
        if request is not None:
            wrapper.request = request
        wrapper.initialize(self._app)
        return wrapper
