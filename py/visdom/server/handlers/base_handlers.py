#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Contain the basic web request handlers that all other handlers derive from
"""

import logging
import traceback
import http.client
import time

import tornado.web
import tornado.websocket


_COMMON_APP_ATTRIBUTES = (
    "state",
    "subs",
    "sources",
    "port",
    "env_path",
    "storage",
    "login_enabled",
    "mark_dirty",
)

_WEB_APP_ATTRIBUTES = _COMMON_APP_ATTRIBUTES + (
    "max_text_lines",
    "max_old_content",
    "max_image_history",
    "max_plot_history",
)

_SOCKET_APP_ATTRIBUTES = _COMMON_APP_ATTRIBUTES + ("readonly",)


def _copy_app_attributes(handler, app, attrs, store_app=False):
    if app is None:
        return

    if store_app:
        handler.app = app

    for attr in attrs:
        setattr(handler, attr, getattr(app, attr))


class BaseWebSocketHandler(tornado.websocket.WebSocketHandler):
    """
    Implements any required overriden functionality from the basic tornado
    websocket handler. Also contains some shared logic for all WebSocketHandler
    classes.
    """

    def initialize(self, app=None):
        """Common initialization shared by WebSocket handlers."""
        _copy_app_attributes(self, app, _SOCKET_APP_ATTRIBUTES, store_app=True)

    def get_current_user(self):
        """
        This method determines the self.current_user
        based the value of cookies that set in POST method
        at IndexHandler by self.set_secure_cookie
        """
        try:
            return self.get_secure_cookie("user_password")
        except Exception:  # Not using secure cookies
            return None


class BaseHandler(tornado.web.RequestHandler):
    """
    Implements any required overriden functionality from the basic tornado
    request handlers, and contains any convenient shared logic helpers.
    """

    def initialize(self, app=None):
        """Common initialization shared by most handlers.

        Copies frequently-used attributes from the application instance.
        Subclasses that need additional attributes should call
        ``super().initialize(app)`` and then set their own.

        The ``app`` parameter defaults to ``None`` so that handlers
        registered without an ``app`` dict (e.g. HealthHandler) still work.
        """
        _copy_app_attributes(self, app, _WEB_APP_ATTRIBUTES)

    def is_authorized(self):
        """Update access time and validate authentication for protected methods."""
        self.last_access = time.time()
        if self.login_enabled and not self.current_user:
            self.set_status(401)
            return False
        return True

    def __init__(self, *request, **kwargs):
        self.include_host = False
        super(BaseHandler, self).__init__(*request, **kwargs)

    def get_current_user(self):
        """
        This method determines the self.current_user
        based the value of cookies that set in POST method
        at IndexHandler by self.set_secure_cookie
        """
        try:
            return self.get_secure_cookie("user_password")
        except Exception:  # Not using secure cookies
            return None

    def write_error(self, status_code, **kwargs):
        logging.error("ERROR: %s: %s" % (status_code, kwargs))
        if "exc_info" in kwargs:
            logging.info(
                "Traceback: {}".format(traceback.format_exception(*kwargs["exc_info"]))
            )
            debug = self.settings.get("debug")
            title = http.client.responses.get(status_code, "Unknown Error")
            logging.error("rendering error page")
            exc_info = kwargs["exc_info"]
            # exc_info is a tuple consisting of:
            # 1. The class of the Exception
            # 2. The actual Exception that was thrown
            # 3. The traceback object
            try:
                params = {
                    "error": exc_info[1] if debug else None,
                    "trace_info": (
                        traceback.format_exception(*exc_info) if debug else None
                    ),
                    "request": self.request.__dict__ if debug else None,
                    "status_code": status_code,
                    "title": title,
                }
                self.render("error.html", **params)
                logging.error("rendering complete")
                return
            except Exception as e:
                logging.error(e)
            self.set_status(status_code)
            self.write(
                f"""
                <h1>{status_code} - {title}</h1>
                """
            )
