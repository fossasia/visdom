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

import logging
import os
import platform
import time
from collections import Counter

import tornado.web  # noqa E402: gotta install ioloop first
from tornado.ioloop import PeriodicCallback

from visdom.utils.shared_utils import warn_once, ensure_dir_exists, get_visdom_path
from visdom.utils.server_utils import LazyEnvData
from visdom.data_model.json_store import JSONStore
from visdom.server.handlers.socket_handlers import (
    SocketHandler,
    SocketWrap,
    VisSocketHandler,
    VisSocketWrap,
)
from visdom.server.handlers.experiments_handler import ExperimentHparamsHandler
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
)


tornado_settings = {
    "autoescape": None,
    "debug": "/dbg/" in __file__,
    "static_path": get_visdom_path("static"),
    "template_path": get_visdom_path("static"),
    "compiled_template_cache": False,
}


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
        self.state = self.load_state()
        self.layouts = self.load_layouts()
        self.user_settings = self.load_user_settings()
        self.save_interval = save_interval
        self.save_threshold = save_threshold
        self.dirty_envs = Counter()
        self.autosave = None
        self.subs = {}
        self.sources = {}
        self.port = port
        self.base_url = base_url
        self.readonly = readonly
        self.user_credential = user_credential
        self.login_enabled = False
        self.last_access = time.time()
        self.wrap_socket = use_frontend_client_polling

        if user_credential:
            self.login_enabled = True
            with open(DEFAULT_ENV_PATH + "COOKIE_SECRET", "r") as fn:
                tornado_settings["cookie_secret"] = fn.read()

        tornado_settings["static_url_prefix"] = self.base_url + "/static/"
        tornado_settings["debug"] = True
        experiments_url = "%s/experiments" % self.base_url
        handlers = [
            (r"%s/events" % self.base_url, PostHandler, {"app": self}),
            (r"%s/update" % self.base_url, UpdateHandler, {"app": self}),
            (r"%s/close" % self.base_url, CloseHandler, {"app": self}),
            (r"%s/socket" % self.base_url, SocketHandler, {"app": self}),
            (r"%s/socket_wrap" % self.base_url, SocketWrap, {"app": self}),
            (r"%s/vis_socket" % self.base_url, VisSocketHandler, {"app": self}),
            (r"%s/vis_socket_wrap" % self.base_url, VisSocketWrap, {"app": self}),
            (r"%s/env/(.*)" % self.base_url, EnvHandler, {"app": self}),
            (r"%s/compare/(.*)" % self.base_url, CompareHandler, {"app": self}),
            (r"%s/save" % self.base_url, SaveHandler, {"app": self}),
            (r"%s/upload_env" % self.base_url, UploadEnvHandler, {"app": self}),
            (r"%s/error/(.*)" % self.base_url, ErrorHandler, {"app": self}),
            (r"%s/win_exists" % self.base_url, ExistsHandler, {"app": self}),
            (r"%s/win_data" % self.base_url, DataHandler, {"app": self}),
            (r"%s/delete_env" % self.base_url, DeleteEnvHandler, {"app": self}),
            (r"%s/env_state" % self.base_url, EnvStateHandler, {"app": self}),
            (r"%s/fork_env" % self.base_url, ForkEnvHandler, {"app": self}),
            (r"%s/log" % experiments_url, ExperimentLogHandler, {"app": self}),
            (r"%s/search" % experiments_url, ExperimentSearchHandler, {"app": self}),
            (r"%s/compare" % experiments_url, ExperimentCompareHandler, {"app": self}),
            (r"%s/suggest" % experiments_url, ExperimentSuggestHandler, {"app": self}),
            (r"%s/hparams" % experiments_url, ExperimentHparamsHandler, {"app": self}),
            (r"%s/tags" % experiments_url, TagsHandler, {"app": self}),
            (r"%s/user/(.*)" % self.base_url, UserSettingsHandler, {"app": self}),
            (r"%s/health" % self.base_url, HealthHandler),
            (r"%s(.*)" % self.base_url, IndexHandler, {"app": self}),
        ]
        super(Application, self).__init__(handlers, **tornado_settings)

    def get_last_access(self):
        if len(self.subs) > 0 or len(self.sources) > 0:
            # update the last access time to now, as someone
            # is currently connected to the server
            self.last_access = time.time()
        return self.last_access

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
            self.autosave = PeriodicCallback(
                self.flush_dirty, self.save_interval * 1000
            )
            self.autosave.start()
        return self.autosave

    def save_layouts(self):
        if self.env_path is None:
            warn_once(
                "Saving and loading to disk has no effect when running with "
                "env_path=None.",
                RuntimeWarning,
            )
            return
        self.storage.save_layouts(self.layouts)

    def load_layouts(self):
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
