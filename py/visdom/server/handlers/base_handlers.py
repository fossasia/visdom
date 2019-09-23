#!/usr/bin/env python3

# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Server"""

from visdom.utils.shared_utils import (
    warn_once,
    get_rand_id,
    get_new_window_id,
    ensure_dir_exists,
)
import argparse
import copy
import getpass
import hashlib
import inspect
import json
import jsonpatch
import logging
import math
import os
import sys
import time
import traceback
from collections import OrderedDict
try:
    # for after python 3.8
    from collections.abc import Mapping, Sequence
except ImportError:
    # for python 3.7 and below
    from collections import Mapping, Sequence

# from zmq.eventloop import ioloop
# ioloop.install()  # Needs to happen before any tornado imports!

import tornado.ioloop     # noqa E402: gotta install ioloop first
import tornado.web        # noqa E402: gotta install ioloop first
import tornado.websocket  # noqa E402: gotta install ioloop first
import tornado.escape     # noqa E402: gotta install ioloop first

LAYOUT_FILE = 'layouts.json'

COMPACT_SEPARATORS = (',', ':')

MAX_SOCKET_WAIT = 15

class BaseWebSocketHandler(tornado.websocket.WebSocketHandler):
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
            logging.info('Traceback: {}'.format(
                traceback.format_exception(*kwargs["exc_info"])))
        if self.settings.get("debug") and "exc_info" in kwargs:
            logging.error("rendering error page")
            exc_info = kwargs["exc_info"]
            # exc_info is a tuple consisting of:
            # 1. The class of the Exception
            # 2. The actual Exception that was thrown
            # 3. The traceback opbject
            try:
                params = {
                    'error': exc_info[1],
                    'trace_info': traceback.format_exception(*exc_info),
                    'request': self.request.__dict__
                }

                self.render("error.html", **params)
                logging.error("rendering complete")
            except Exception as e:
                logging.error(e)
