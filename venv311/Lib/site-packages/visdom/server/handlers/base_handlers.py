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

import tornado.web
import tornado.websocket


class BaseWebSocketHandler(tornado.websocket.WebSocketHandler):
    """
    Implements any required overriden functionality from the basic tornado
    websocket handler. Also contains some shared logic for all WebSocketHandler
    classes.
    """

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
        if self.settings.get("debug") and "exc_info" in kwargs:
            logging.error("rendering error page")
            exc_info = kwargs["exc_info"]
            # exc_info is a tuple consisting of:
            # 1. The class of the Exception
            # 2. The actual Exception that was thrown
            # 3. The traceback opbject
            try:
                params = {
                    "error": exc_info[1],
                    "trace_info": traceback.format_exception(*exc_info),
                    "request": self.request.__dict__,
                }

                # TODO make an error.html page
                self.render("error.html", **params)
                logging.error("rendering complete")
            except Exception as e:
                logging.error(e)
