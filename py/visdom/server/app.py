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

import copy
import hashlib
import logging
import os
import platform
import time

import tornado.web  # noqa E402: gotta install ioloop first
import tornado.escape  # noqa E402: gotta install ioloop first

from visdom.utils.shared_utils import warn_once, ensure_dir_exists, get_visdom_path
from visdom.utils.server_utils import serialize_env, LazyEnvData
from visdom.server.handlers.socket_handlers import (
    SocketHandler,
    SocketWrap,
    VisSocketHandler,
    VisSocketWrap,
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
    ForkEnvHandler,
    HashHandler,
    IndexHandler,
    PostHandler,
    SaveHandler,
    UpdateHandler,
    UserSettingsHandler,
)
from visdom.server.defaults import (
    DEFAULT_BASE_URL,
    DEFAULT_ENV_PATH,
    DEFAULT_HOSTNAME,
    DEFAULT_PORT,
    LAYOUT_FILE,
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
    ):
        self.eager_data_loading = eager_data_loading
        self.env_path = env_path
        self.state = self.load_state()
        self.layouts = self.load_layouts()
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

        if user_credential:
            self.login_enabled = True
            with open(DEFAULT_ENV_PATH + "COOKIE_SECRET", "r") as fn:
                tornado_settings["cookie_secret"] = fn.read()

        tornado_settings["static_url_prefix"] = self.base_url + "/static/"
        tornado_settings["debug"] = True
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
            (r"%s/error/(.*)" % self.base_url, ErrorHandler, {"app": self}),
            (r"%s/win_exists" % self.base_url, ExistsHandler, {"app": self}),
            (r"%s/win_data" % self.base_url, DataHandler, {"app": self}),
            (r"%s/delete_env" % self.base_url, DeleteEnvHandler, {"app": self}),
            (r"%s/win_hash" % self.base_url, HashHandler, {"app": self}),
            (r"%s/env_state" % self.base_url, EnvStateHandler, {"app": self}),
            (r"%s/fork_env" % self.base_url, ForkEnvHandler, {"app": self}),
            (r"%s/user/(.*)" % self.base_url, UserSettingsHandler, {"app": self}),
            (r"%s(.*)" % self.base_url, IndexHandler, {"app": self}),
        ]
        super(Application, self).__init__(handlers, **tornado_settings)

    def get_last_access(self):
        if len(self.subs) > 0 or len(self.sources) > 0:
            # update the last access time to now, as someone
            # is currently connected to the server
            self.last_access = time.time()
        return self.last_access

    def save_layouts(self):
        if self.env_path is None:
            warn_once(
                "Saving and loading to disk has no effect when running with "
                "env_path=None.",
                RuntimeWarning,
            )
            return
        layout_filepath = os.path.join(self.env_path, "view", LAYOUT_FILE)
        with open(layout_filepath, "w") as fn:
            fn.write(self.layouts)

    def load_layouts(self):
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
        env_jsons = [i for i in os.listdir(env_path) if ".json" in i]
        for env_json in env_jsons:
            eid = env_json.replace(".json", "")
            env_path_file = os.path.join(env_path, env_json)

            if self.eager_data_loading:
                try:
                    with open(env_path_file, "r") as fn:
                        env_data = tornado.escape.json_decode(fn.read())
                except Exception as e:
                    logging.warn(
                        "Failed loading environment json: {} - {}".format(
                            env_path_file, repr(e)
                        )
                    )
                    continue

                state[eid] = {"jsons": env_data["jsons"], "reload": env_data["reload"]}
            else:
                state[eid] = LazyEnvData(env_path_file)

        if "main" not in state and "main.json" not in env_jsons:
            state["main"] = {"jsons": {}, "reload": {}}
            serialize_env(state, ["main"], env_path=self.env_path)

        return state

    def load_user_settings(self):
        settings = {}

        """Determines & uses the platform-specific root directory for user configurations."""
        if platform.system() == "Windows":
            base_dir = os.getenv("APPDATA")
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
        project_style_path = os.path.join(self.env_path, "style.css")
        if os.path.exists(project_style_path):
            with open(project_style_path, "r") as f:
                user_css += "\n" + f.read()

        settings["config_dir"] = config_dir
        settings["user_css"] = user_css

        return settings
