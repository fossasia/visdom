#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Main application class that pulls handlers together and maintains
all of the required state about the currently running server.
"""

import asyncio
import logging
import os
import platform
import threading
import time
from concurrent.futures import Future

import tornado.ioloop
import tornado.web  # noqa E402: gotta install ioloop first

from visdom.utils.shared_utils import warn_once, ensure_dir_exists, get_visdom_path
from visdom.utils.server_utils import LazyEnvData
from visdom.data_model.json_store import JSONStore
from visdom.server.workspace_manager import WorkspaceManager
from visdom.server.workspace_env_manager import WorkspaceEnvManager
from visdom.server.handlers.socket_handlers import (
    SocketHandler,
    SocketWrap,
    VisSocketHandler,
    VisSocketWrap,
)
from visdom.server.handlers.experiments_handler import (
    ExperimentHparamsHandler,
    ExperimentHparamsUpdateHandler,
    make_live_queue,
)
from visdom.server.handlers.web_handlers import (
    CloseHandler,
    CompareHandler,
    DataHandler,
    DeleteEnvHandler,
    EnvHandler,
    EnvStateHandler,
    ErrorHandler,
    ExistsHandler,
    ExperimentCompareHandler,
    ExperimentLogHandler,
    ExperimentSearchHandler,
    ExperimentSuggestHandler,
    ForkEnvHandler,
    HealthHandler,
    IndexHandler,
    PostHandler,
    SaveHandler,
    TagsHandler,
    UpdateHandler,
    UploadEnvHandler,
    UserSettingsHandler,
)
from visdom.server.server_state import ServerState
from visdom.server.defaults import (
    DEFAULT_BASE_URL,
    DEFAULT_ENV_PATH,
    DEFAULT_HOSTNAME,
    DEFAULT_MAX_IMAGE_HISTORY,
    DEFAULT_MAX_OLD_CONTENT,
    DEFAULT_MAX_PLOT_HISTORY,
    DEFAULT_MAX_TEXT_LINES,
    DEFAULT_PORT,
    DEFAULT_SAVE_INTERVAL,
    DEFAULT_SAVE_THRESHOLD,
    WEBSOCKET_PING_INTERVAL,
)

# Template only -- never mutate it. ``__init__`` copies it per instance because
# several of these values are derived from constructor arguments, and writing
# them back here leaked one server's base_url and cookie secret into the next
# ``Application`` built in the same process.
tornado_settings = {
    "autoescape": None,
    "debug": "/dbg/" in __file__,
    "static_path": get_visdom_path("static"),
    "template_path": get_visdom_path("static"),
    "compiled_template_cache": False,
}


def _combine_written(futures):
    """One future over several writes, resolving to every id that reached disk.

    The writes come back as futures belonging to the IO loop, which resolve on
    the loop rather than blocking, so they cannot be waited on from the storage
    worker or from any other thread. Completion is followed with callbacks
    instead: each write reports as it settles, and the combined future is
    resolved once the last one has. The first failure is what the caller sees,
    since a write that raised has already been logged and retried by the state
    that owns it.
    """
    if len(futures) == 1:
        return futures[0]
    first = futures[0]
    if isinstance(first, asyncio.Future):
        combined = first.get_loop().create_future()
    else:
        combined = Future()
    settled = []
    lock = threading.Lock()

    def settle(future):
        with lock:
            settled.append(future)
            if len(settled) < len(futures):
                return
        failures = [
            done.exception()
            for done in futures
            if not done.cancelled() and done.exception() is not None
        ]
        if failures:
            combined.set_exception(failures[0])
        elif any(done.cancelled() for done in futures):
            combined.cancel()
        else:
            combined.set_result([eid for done in futures for eid in done.result()])

    for future in futures:
        future.add_done_callback(settle)
    return combined


class Application(tornado.web.Application):
    def __init__(
        self,
        port=DEFAULT_PORT,
        base_url="",
        env_path=DEFAULT_ENV_PATH,
        readonly=False,
        user_credential=None,
        use_frontend_client_polling=False,
        eager_data_loading=False,
        save_interval=DEFAULT_SAVE_INTERVAL,
        save_threshold=DEFAULT_SAVE_THRESHOLD,
    ):
        self.eager_data_loading = eager_data_loading
        self.max_image_history = DEFAULT_MAX_IMAGE_HISTORY
        self.max_old_content = DEFAULT_MAX_OLD_CONTENT
        self.max_plot_history = DEFAULT_MAX_PLOT_HISTORY
        self.max_text_lines = DEFAULT_MAX_TEXT_LINES
        self.env_path = env_path
        self.storage = JSONStore(env_path)
        self.workspace_manager = (
            WorkspaceManager() if os.environ.get("VISDOM_GATEWAY_URL") else None
        )
        self.state = self.load_state()
        self.user_settings = self.load_user_settings()
        self.subs = {}
        self.sources = {}
        self.port = port
        self.base_url = base_url
        self.readonly = readonly
        self.user_credential = user_credential
        self.login_enabled = False
        self.last_access = time.time()
        self.wrap_socket = use_frontend_client_polling

        settings = dict(tornado_settings)
        # Polling wrappers are reaped by ``ServerState`` instead; this reaches
        # only real websockets. The pong deadline is left at tornado's default,
        # which is the interval itself.
        settings["websocket_ping_interval"] = WEBSOCKET_PING_INTERVAL

        if user_credential:
            self.login_enabled = True
            with open(DEFAULT_ENV_PATH + "COOKIE_SECRET", "r") as fn:
                settings["cookie_secret"] = fn.read()

        self.server_state = ServerState(
            state=self.state,
            subs=self.subs,
            sources=self.sources,
            storage=self.storage,
            env_path=self.env_path,
            port=self.port,
            login_enabled=self.login_enabled,
            readonly=self.readonly,
            user_credential=self.user_credential,
            base_url=self.base_url,
            wrap_socket=self.wrap_socket,
            user_settings=self.user_settings,
            max_text_lines=self.max_text_lines,
            max_old_content=self.max_old_content,
            max_image_history=self.max_image_history,
            max_plot_history=self.max_plot_history,
            save_interval=save_interval,
            save_threshold=save_threshold,
        )
        self.server_state.live_updates = make_live_queue(self.server_state)

        self.workspace_env_manager = WorkspaceEnvManager(
            base_env_path=env_path,
            default_state=self.server_state,
            eager=self.eager_data_loading,
            live_queue=make_live_queue,
        )
        self.server_state.workspace_manager = self.workspace_manager
        self.server_state.workspace_env_manager = self.workspace_env_manager
        self._workspaces_shut_down = False
        self._workspaces_shutdown_lock = threading.Lock()

        settings["static_url_prefix"] = self.base_url + "/static/"
        # A traceback and the raw request are debugging aids, not something to
        # hand to whoever provoked the error. `debug` was forced on for every
        # server, which put both on the 500 page -- and, being tornado's debug
        # flag, also turned on autoreload. Follow the operator's logging level
        # instead, and keep the two concerns separate.
        settings["show_error_details"] = logging.getLogger().isEnabledFor(logging.DEBUG)
        experiments_url = "%s/experiments" % self.base_url
        server_state_args = {"server_state": self.server_state}
        handlers = [
            (r"%s/events" % self.base_url, PostHandler, server_state_args),
            (r"%s/update" % self.base_url, UpdateHandler, server_state_args),
            (r"%s/close" % self.base_url, CloseHandler, server_state_args),
            (r"%s/socket" % self.base_url, SocketHandler, server_state_args),
            (r"%s/socket_wrap" % self.base_url, SocketWrap, server_state_args),
            (r"%s/vis_socket" % self.base_url, VisSocketHandler, server_state_args),
            (
                r"%s/vis_socket_wrap" % self.base_url,
                VisSocketWrap,
                server_state_args,
            ),
            (r"%s/env/(.*)" % self.base_url, EnvHandler, server_state_args),
            (r"%s/compare/(.*)" % self.base_url, CompareHandler, server_state_args),
            (r"%s/save" % self.base_url, SaveHandler, server_state_args),
            (r"%s/upload_env" % self.base_url, UploadEnvHandler, server_state_args),
            (r"%s/error/(.*)" % self.base_url, ErrorHandler, server_state_args),
            (r"%s/win_exists" % self.base_url, ExistsHandler, server_state_args),
            (r"%s/win_data" % self.base_url, DataHandler, server_state_args),
            (r"%s/delete_env" % self.base_url, DeleteEnvHandler, server_state_args),
            (r"%s/env_state" % self.base_url, EnvStateHandler, server_state_args),
            (r"%s/fork_env" % self.base_url, ForkEnvHandler, server_state_args),
            (r"%s/log" % experiments_url, ExperimentLogHandler, server_state_args),
            (
                r"%s/search" % experiments_url,
                ExperimentSearchHandler,
                server_state_args,
            ),
            (
                r"%s/compare" % experiments_url,
                ExperimentCompareHandler,
                server_state_args,
            ),
            (
                r"%s/suggest" % experiments_url,
                ExperimentSuggestHandler,
                server_state_args,
            ),
            (
                r"%s/hparams" % experiments_url,
                ExperimentHparamsHandler,
                server_state_args,
            ),
            (
                r"%s/hparams/update" % experiments_url,
                ExperimentHparamsUpdateHandler,
                server_state_args,
            ),
            (r"%s/tags" % experiments_url, TagsHandler, server_state_args),
            (
                r"%s/user/(.*)" % self.base_url,
                UserSettingsHandler,
                server_state_args,
            ),
            (r"%s/health" % self.base_url, HealthHandler),
            (r"%s(.*)" % self.base_url, IndexHandler, server_state_args),
        ]
        super(Application, self).__init__(handlers, **settings)

    def get_last_access(self):
        if len(self.subs) > 0 or len(self.sources) > 0:
            # update the last access time to now, as someone
            # is currently connected to the server
            self.last_access = time.time()
        return self.last_access

    @property
    def layouts(self):
        """Compatibility view of layouts owned by ``ServerState``."""
        return self.server_state.get_layouts()

    @layouts.setter
    def layouts(self, layouts):
        self.server_state.set_layouts(layouts)

    @property
    def save_interval(self):
        """Compatibility view of the ServerState autosave interval."""
        return self.server_state.save_interval

    @property
    def save_threshold(self):
        """Compatibility view of the ServerState update threshold."""
        return self.server_state.save_threshold

    @property
    def dirty_envs(self):
        """Compatibility view of environments pending persistence."""
        return self.server_state.dirty_envs

    @property
    def autosave(self):
        """Compatibility view of the ServerState autosave timer."""
        return self.server_state.autosave

    @property
    def storage_executor(self):
        """Compatibility view of the ServerState storage worker."""
        return self.server_state.storage_executor

    @property
    def saving_envs(self):
        """Compatibility view of environments with a write in flight."""
        return self.server_state.saving_envs

    @property
    def live_updates(self):
        """Compatibility view of the ServerState hparams refresh queue."""
        return self.server_state.live_updates

    def mark_dirty(self, eid):
        """Compatibility wrapper for the ServerState dirty tracker."""
        return self.server_state.mark_dirty(eid)

    def flush_envs(self, eids):
        """Compatibility wrapper for selective ServerState persistence."""
        return self.server_state.flush_envs(eids)

    def flush_dirty(self):
        """Persist changed environments in every workspace, not just this one.

        ``ServerState.flush_dirty`` only knows its own state, which on a
        multi-tenant server is the state no tenant is using. A workspace nobody
        happens to be looking at when the timer fires still has to be written.

        One future comes back for all of them, so a caller waits the same way
        it would for a single state.
        """
        futures = [
            future
            for future in (
                state.flush_dirty() for state in self.workspace_env_manager.spaces()
            )
            if future is not None
        ]
        if not futures:
            return None
        return _combine_written(futures)

    def start_autosave(self):
        """Save changed environments on a timer, across every workspace.

        Started here rather than on ``ServerState`` so the callback is the
        application's ``flush_dirty``, which walks all of them.
        """
        if self.server_state.autosave is None and self.server_state.save_interval > 0:
            self.server_state.autosave = tornado.ioloop.PeriodicCallback(
                self.flush_dirty, self.server_state.save_interval * 1000
            )
            self.server_state.autosave.start()
        return self.server_state.autosave

    def stop_autosave(self):
        """Compatibility wrapper for stopping the ServerState autosave."""
        return self.server_state.stop_autosave()

    def shutdown_storage(self):
        """Drain and save every workspace, not just this server's own state.

        ``ServerState.shutdown_storage`` saves the one state it belongs to,
        which on a multi-tenant server holds nothing a tenant wrote. The worker
        is shared, so the drain it performs covers every workspace's queued
        writes; the final save is then per space, or a workspace keeps only
        whatever happened to reach disk before the drain.

        Idempotent for the same reason the base is: the graceful stop calls it
        and the ``atexit`` hook calls it again, and a second pass must not
        re-save through an executor that is already gone.

        Only a pass in which every save succeeded counts as shut down, the same
        rule the base follows. If any save raises, the ``atexit`` call runs the
        whole thing again instead of returning early with a workspace's changes
        still only in memory. The lock keeps two callers from writing the same
        files at once while the flag is still clear.
        """
        with self._workspaces_shutdown_lock:
            if self._workspaces_shut_down:
                return
            failures = []
            try:
                self.server_state.shutdown_storage()
            except Exception as error:
                failures.append(error)
            for _workspace_id, state in self.workspace_env_manager.workspace_spaces():
                try:
                    if state.env_path is not None:
                        state.storage.save_all(state.state)
                except Exception as error:
                    failures.append(error)
                    continue
                state.dirty_envs.clear()
                state.saving_envs.clear()
            if failures:
                raise failures[0]
            self._workspaces_shut_down = True

    def save_layouts(self, layouts=None):
        """Compatibility wrapper for callers that still use ``Application``."""
        self.server_state.save_layouts(layouts)

    def load_layouts(self):
        """Read layouts through the configured ``DataStore`` backend."""
        if self.env_path is None:
            warn_once(
                "Saving and loading to disk has no effect when running with "
                "env_path=None.",
                RuntimeWarning,
            )
            return ""
        return self.storage.load_layouts()

    def load_state(self):
        state = {}
        env_path = self.env_path
        if env_path is None:
            warn_once(
                "Saving and loading to disk has no effect when running with "
                "env_path=None.",
                RuntimeWarning,
            )
            return {"main": {"jsons": {}, "reload": {}}}
        ensure_dir_exists(env_path)
        for eid in self.storage.list_envs():
            if self.eager_data_loading:
                env_data = self.storage.load_env(eid)
                if not isinstance(env_data, dict):
                    env_data = {}

                if "jsons" not in env_data or "reload" not in env_data:
                    logging.warning(
                        "Environment '%s' is malformed or missing expected fields.",
                        eid,
                    )

                # Copy the whole env rather than picking out jsons/reload, so
                # keys the server does not read itself (such as the experiment
                # metadata blob) survive the load and are still there when the
                # env is saved back. LazyEnvData keeps them for the lazy path.
                state[eid] = dict(env_data)
                state[eid].setdefault("jsons", {})
                state[eid].setdefault("reload", {})
            else:
                state[eid] = LazyEnvData(self.storage, eid)

        if "main" not in state:
            state["main"] = {"jsons": {}, "reload": {}}
            self.storage.save_env("main", state["main"])

        return state

    def load_user_settings(self):
        settings = {}

        """Determines & uses the platform-specific root directory for user configurations."""
        if platform.system() == "Windows":
            base_dir = os.getenv("APPDATA")

            if not base_dir:
                fallback = os.path.expanduser("~")

                if not fallback or fallback == "~":
                    raise RuntimeError(
                        "Could not determine base directory for user configurations."
                    )
                logging.warning("APPDATA not set, falling back to base directory")
                base_dir = fallback

        elif platform.system() == "Darwin":  # osx
            base_dir = os.path.expanduser("~/Library/Preferences")
        else:
            base_dir = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        config_dir = os.path.join(base_dir, "visdom")

        # initialize user style
        user_css = ""
        home_style_path = os.path.join(config_dir, "style.css")
        if os.path.exists(home_style_path):
            with open(home_style_path, "r") as f:
                user_css += "\n" + f.read()
        if self.env_path is not None:
            project_style_path = os.path.join(self.env_path, "style.css")
            if os.path.exists(project_style_path):
                with open(project_style_path, "r") as f:
                    user_css += "\n" + f.read()

        settings["config_dir"] = config_dir
        settings["user_css"] = user_css

        return settings
