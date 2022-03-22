#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Server"""

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
import uuid
import warnings
import platform
from os.path import expanduser
from collections import OrderedDict
from collections.abc import Mapping
try:
    # for after python 3.8
    from collections.abc import Mapping, Sequence
except ImportError:
    # for python 3.7 and below
    from collections import Mapping, Sequence

from zmq.eventloop import ioloop
ioloop.install()  # Needs to happen before any tornado imports!

import tornado.ioloop     # noqa E402: gotta install ioloop first
import tornado.web        # noqa E402: gotta install ioloop first
import tornado.websocket  # noqa E402: gotta install ioloop first
import tornado.escape     # noqa E402: gotta install ioloop first

LAYOUT_FILE = 'layouts.json'
DEFAULT_ENV_PATH = '%s/.visdom/' % expanduser("~")
DEFAULT_PORT = 8097
DEFAULT_HOSTNAME = "localhost"
DEFAULT_BASE_URL = "/"

here = os.path.abspath(os.path.dirname(__file__))
COMPACT_SEPARATORS = (',', ':')

_seen_warnings = set()

MAX_SOCKET_WAIT = 15

assert sys.version_info[0] >= 3, 'To use visdom with python 2, downgrade to v0.1.8.9'


def warn_once(msg, warningtype=None):
    """
    Raise a warning, but only once.
    :param str msg: Message to display
    :param Warning warningtype: Type of warning, e.g. DeprecationWarning
    """
    global _seen_warnings
    if msg not in _seen_warnings:
        _seen_warnings.add(msg)
        warnings.warn(msg, warningtype, stacklevel=2)


def check_auth(f):
    def _check_auth(self, *args, **kwargs):
        self.last_access = time.time()
        if self.login_enabled and not self.current_user:
            self.set_status(400)
            return
        f(self, *args, **kwargs)
    return _check_auth


def get_rand_id():
    return str(uuid.uuid4())


def ensure_dir_exists(path):
    """Make sure the parent dir exists for path so we can write a file."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)))
    except OSError as e1:
        assert e1.errno == 17  # errno.EEXIST


def get_path(filename):
    """Get the path to an asset."""
    cwd = os.path.dirname(
        os.path.abspath(inspect.getfile(inspect.currentframe())))
    return os.path.join(cwd, filename)


def escape_eid(eid):
    """Replace slashes with underscores, to avoid recognizing them
    as directories.
    """

    return eid.replace('/', '_')


def extract_eid(args):
    """Extract eid from args. If eid does not exist in args,
    it returns 'main'."""

    eid = 'main' if args.get('eid') is None else args.get('eid')
    return escape_eid(eid)


def set_cookie(value=None):
    """Create cookie secret key for authentication"""
    if value is not None:
        cookie_secret = value
    else:
        cookie_secret = input("Please input your cookie secret key here: ")
    with open(DEFAULT_ENV_PATH + "COOKIE_SECRET", "w") as cookie_file:
        cookie_file.write(cookie_secret)


def hash_password(password):
    """Hashing Password with SHA-256"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()




class LazyEnvData(Mapping):
    def __init__(self, env_path_file):
        self._env_path_file = env_path_file
        self._raw_dict = None

    def lazy_load_data(self):
        if self._raw_dict is not None:
            return

        try:
            with open(self._env_path_file, 'r') as fn:
                env_data = tornado.escape.json_decode(fn.read())
        except Exception as e:
            raise ValueError(
                "Failed loading environment json: {} - {}".format(
                    self._env_path_file, repr(e)))
        self._raw_dict = {
                'jsons': env_data['jsons'],
                'reload': env_data['reload']
        }

    def __getitem__(self, key):
        self.lazy_load_data()
        return self._raw_dict.__getitem__(key)

    def __setitem__(self, key, value):
        self.lazy_load_data()
        return self._raw_dict.__setitem__(key, value)

    def __iter__(self):
        self.lazy_load_data()
        return iter(self._raw_dict)

    def __len__(self):
        self.lazy_load_data()
        return len(self._raw_dict)


tornado_settings = {
    "autoescape": None,
    "debug": "/dbg/" in __file__,
    "static_path": get_path('static'),
    "template_path": get_path('static'),
    "compiled_template_cache": False
}


def serialize_env(state, eids, env_path=DEFAULT_ENV_PATH):
    env_ids = [i for i in eids if i in state]
    if env_path is not None:
        for env_id in env_ids:
            env_path_file = os.path.join(env_path, "{0}.json".format(env_id))
            with open(env_path_file, 'w') as fn:
                if isinstance(state[env_id], LazyEnvData):
                    fn.write(json.dumps(state[env_id]._raw_dict))
                else:
                    fn.write(json.dumps(state[env_id]))
    return env_ids


def serialize_all(state, env_path=DEFAULT_ENV_PATH):
    serialize_env(state, list(state.keys()), env_path=env_path)


class Application(tornado.web.Application):
    def __init__(self, port=DEFAULT_PORT, base_url='',
                 env_path=DEFAULT_ENV_PATH, readonly=False,
                 user_credential=None, use_frontend_client_polling=False,
                 eager_data_loading=False):
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

        tornado_settings['static_url_prefix'] = self.base_url + "/static/"
        tornado_settings['debug'] = True
        handlers = [
            (r"%s/events" % self.base_url, PostHandler, {'app': self}),
            (r"%s/update" % self.base_url, UpdateHandler, {'app': self}),
            (r"%s/close" % self.base_url, CloseHandler, {'app': self}),
            (r"%s/socket" % self.base_url, SocketHandler, {'app': self}),
            (r"%s/socket_wrap" % self.base_url, SocketWrap, {'app': self}),
            (r"%s/vis_socket" % self.base_url,
                VisSocketHandler, {'app': self}),
            (r"%s/vis_socket_wrap" % self.base_url,
                VisSocketWrap, {'app': self}),
            (r"%s/env/(.*)" % self.base_url, EnvHandler, {'app': self}),
            (r"%s/compare/(.*)" % self.base_url,
                CompareHandler, {'app': self}),
            (r"%s/save" % self.base_url, SaveHandler, {'app': self}),
            (r"%s/error/(.*)" % self.base_url, ErrorHandler, {'app': self}),
            (r"%s/win_exists" % self.base_url, ExistsHandler, {'app': self}),
            (r"%s/win_data" % self.base_url, DataHandler, {'app': self}),
            (r"%s/delete_env" % self.base_url,
                DeleteEnvHandler, {'app': self}),
            (r"%s/win_hash" % self.base_url, HashHandler, {'app': self}),
            (r"%s/env_state" % self.base_url, EnvStateHandler, {'app': self}),
            (r"%s/fork_env" % self.base_url, ForkEnvHandler, {'app': self}),
            (r"%s/user/(.*)" % self.base_url, UserSettingsHandler, {'app': self}),
            (r"%s(.*)" % self.base_url, IndexHandler, {'app': self}),
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
                'Saving and loading to disk has no effect when running with '
                'env_path=None.',
                RuntimeWarning
            )
            return
        layout_filepath = os.path.join(self.env_path, 'view', LAYOUT_FILE)
        with open(layout_filepath, 'w') as fn:
            fn.write(self.layouts)

    def load_layouts(self):
        if self.env_path is None:
            warn_once(
                'Saving and loading to disk has no effect when running with '
                'env_path=None.',
                RuntimeWarning
            )
            return ""
        layout_filepath = os.path.join(self.env_path, 'view', LAYOUT_FILE)
        ensure_dir_exists(layout_filepath)
        if os.path.isfile(layout_filepath):
            with open(layout_filepath, 'r') as fn:
                return fn.read()
        else:
            return ""

    def load_state(self):
        state = {}
        env_path = self.env_path
        if env_path is None:
            warn_once(
                'Saving and loading to disk has no effect when running with '
                'env_path=None.',
                RuntimeWarning
            )
            return {'main': {'jsons': {}, 'reload': {}}}
        ensure_dir_exists(env_path)
        env_jsons = [i for i in os.listdir(env_path) if '.json' in i]
        for env_json in env_jsons:
            eid = env_json.replace('.json', '')
            env_path_file = os.path.join(env_path, env_json)

            if self.eager_data_loading:
                try:
                    with open(env_path_file, 'r') as fn:
                        env_data = tornado.escape.json_decode(fn.read())
                except Exception as e:
                    logging.warn(
                        "Failed loading environment json: {} - {}".format(
                            env_path_file, repr(e)))
                    continue

                state[eid] = {'jsons': env_data['jsons'],
                        'reload': env_data['reload']}
            else:
                state[eid] = LazyEnvData(env_path_file)

        if 'main' not in state and 'main.json' not in env_jsons:
            state['main'] = {'jsons': {}, 'reload': {}}
            serialize_env(state, ['main'], env_path=self.env_path)

        return state

    def load_user_settings(self):
        settings = {}

        """Determines & uses the platform-specific root directory for user configurations."""
        if platform.system() == "Windows":
            base_dir = os.getenv('APPDATA')
        elif platform.system() == "Darwin": # osx
            base_dir = os.path.expanduser('~/Library/Preferences')
        else:
            base_dir = os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        config_dir = os.path.join(base_dir, "visdom")

        # initialize user style
        user_css = ""
        logging.error("initializing")
        home_style_path = os.path.join(config_dir, "style.css")
        if os.path.exists(home_style_path):
            with open(home_style_path, "r") as f:
                user_css += "\n" + f.read()
        project_style_path = os.path.join(self.env_path, "style.css")
        if os.path.exists(project_style_path):
            with open(project_style_path, "r") as f:
                user_css += "\n" + f.read()

        settings['config_dir'] = config_dir
        settings['user_css'] = user_css

        return settings



def broadcast_envs(handler, target_subs=None):
    if target_subs is None:
        target_subs = handler.subs.values()
    for sub in target_subs:
        sub.write_message(json.dumps(
            {'command': 'env_update', 'data': list(handler.state.keys())}
        ))


def send_to_sources(handler, msg):
    target_sources = handler.sources.values()
    for source in target_sources:
        source.write_message(json.dumps(msg))


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


class VisSocketHandler(BaseWebSocketHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled

    def check_origin(self, origin):
        return True

    def open(self):
        if self.login_enabled and not self.current_user:
            self.close()
            return
        self.sid = str(hex(int(time.time() * 10000000))[2:])
        if self not in list(self.sources.values()):
            self.eid = 'main'
            self.sources[self.sid] = self
        logging.info('Opened visdom socket from ip: {}'.format(
            self.request.remote_ip))

        self.write_message(
            json.dumps({'command': 'alive', 'data': 'vis_alive'}))

    def on_message(self, message):
        logging.info('from visdom client: {}'.format(message))
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))

        cmd = msg.get('cmd')
        if cmd == 'echo':
            for sub in self.sources.values():
                sub.write_message(json.dumps(msg))

    def on_close(self):
        if self in list(self.sources.values()):
            self.sources.pop(self.sid, None)


class VisSocketWrapper():
    def __init__(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
        self.app = app
        self.messages = []
        self.last_read_time = time.time()
        self.open()
        try:
            if not self.app.socket_wrap_monitor.is_running():
                self.app.socket_wrap_monitor.start()
        except AttributeError:
            self.app.socket_wrap_monitor = tornado.ioloop.PeriodicCallback(
                self.socket_wrap_monitor_thread, 15000
            )
            self.app.socket_wrap_monitor.start()

    # TODO refactor the two socket wrappers into a wrapper class
    def socket_wrap_monitor_thread(self):
        if len(self.subs) > 0 or len(self.sources) > 0:
            for sub in list(self.subs.values()):
                if time.time() - sub.last_read_time > MAX_SOCKET_WAIT:
                    sub.close()
            for sub in list(self.sources.values()):
                if time.time() - sub.last_read_time > MAX_SOCKET_WAIT:
                    sub.close()
        else:
            self.app.socket_wrap_monitor.stop()

    def open(self):
        if self.login_enabled and not self.current_user:
            print("AUTH Failed in SocketHandler")
            self.close()
            return
        self.sid = get_rand_id()
        if self not in list(self.sources.values()):
            self.eid = 'main'
            self.sources[self.sid] = self
        logging.info('Mocking visdom socket: {}'.format(self.sid))

        self.write_message(
            json.dumps({'command': 'alive', 'data': 'vis_alive'}))

    def on_message(self, message):
        logging.info('from visdom client: {}'.format(message))
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))

        cmd = msg.get('cmd')
        if cmd == 'echo':
            for sub in self.sources.values():
                sub.write_message(json.dumps(msg))

    def close(self):
        if self in list(self.sources.values()):
            self.sources.pop(self.sid, None)

    def write_message(self, msg):
        self.messages.append(msg)

    def get_messages(self):
        to_send = []
        while len(self.messages) > 0:
            message = self.messages.pop()
            if isinstance(message, dict):
                # Not all messages are being formatted the same way (JSON)
                # TODO investigate
                message = json.dumps(message)
            to_send.append(message)
        self.last_read_time = time.time()
        return to_send


class SocketHandler(BaseWebSocketHandler):
    def initialize(self, app):
        self.port = app.port
        self.env_path = app.env_path
        self.app = app
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.broadcast_layouts()
        self.readonly = app.readonly
        self.login_enabled = app.login_enabled

    def check_origin(self, origin):
        return True

    def broadcast_layouts(self, target_subs=None):
        if target_subs is None:
            target_subs = self.subs.values()
        for sub in target_subs:
            sub.write_message(json.dumps(
                {'command': 'layout_update', 'data': self.app.layouts}
            ))

    def open(self):
        if self.login_enabled and not self.current_user:
            print("AUTH Failed in SocketHandler")
            self.close()
            return
        self.sid = get_rand_id()
        if self not in list(self.subs.values()):
            self.eid = 'main'
            self.subs[self.sid] = self
        logging.info(
            'Opened new socket from ip: {}'.format(self.request.remote_ip))

        self.write_message(
            json.dumps({'command': 'register', 'data': self.sid,
                        'readonly': self.readonly}))
        self.broadcast_layouts([self])
        broadcast_envs(self, [self])

    def on_message(self, message):
        logging.info('from web client: {}'.format(message))
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))

        cmd = msg.get('cmd')

        if self.readonly:
            return

        if cmd == 'close':
            if 'data' in msg and 'eid' in msg:
                logging.info('closing window {}'.format(msg['data']))
                p_data = self.state[msg['eid']]['jsons'].pop(msg['data'], None)
                event = {
                    'event_type': 'close',
                    'target': msg['data'],
                    'eid': msg['eid'],
                    'pane_data': p_data,
                }
                send_to_sources(self, event)
        elif cmd == 'save':
            # save localStorage window metadata
            if 'data' in msg and 'eid' in msg:
                msg['eid'] = escape_eid(msg['eid'])
                self.state[msg['eid']] = \
                    copy.deepcopy(self.state[msg['prev_eid']])
                self.state[msg['eid']]['reload'] = msg['data']
                self.eid = msg['eid']
                serialize_env(self.state, [self.eid], env_path=self.env_path)
        elif cmd == 'delete_env':
            if 'eid' in msg:
                logging.info('closing environment {}'.format(msg['eid']))
                del self.state[msg['eid']]
                if self.env_path is not None:
                    p = os.path.join(
                        self.env_path,
                        "{0}.json".format(msg['eid'])
                    )
                    os.remove(p)
                broadcast_envs(self)
        elif cmd == 'save_layouts':
            if 'data' in msg:
                self.app.layouts = msg.get('data')
                self.app.save_layouts()
                self.broadcast_layouts()
        elif cmd == 'forward_to_vis':
            packet = msg.get('data')
            environment = self.state[packet['eid']]
            if packet.get('pane_data') is not False:
                packet['pane_data'] = environment['jsons'][packet['target']]
            send_to_sources(self, msg.get('data'))
        elif cmd == 'layout_item_update':
            eid = msg.get('eid')
            win = msg.get('win')
            self.state[eid]['reload'][win] = msg.get('data')
        elif cmd == 'pop_embeddings_pane':
            packet = msg.get('data')
            eid = packet['eid']
            win = packet['target']
            p = self.state[eid]['jsons'][win]
            p['content']['selected'] = None
            p['content']['data'] = p['old_content'].pop()
            if len(p['old_content']) == 0:
                p['content']['has_previous'] = False
            p['contentID'] = get_rand_id()
            broadcast(self, p, eid)

    def on_close(self):
        if self in list(self.subs.values()):
            self.subs.pop(self.sid, None)


# TODO condense some of the functionality between this class and the
# original SocketHandler class
class ClientSocketWrapper():
    """
    Wraps all of the socket actions in regular request handling, thus
    allowing all of the same information to be sent via a polling interface
    """
    def __init__(self, app):
        self.port = app.port
        self.env_path = app.env_path
        self.app = app
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.readonly = app.readonly
        self.login_enabled = app.login_enabled
        self.messages = []
        self.last_read_time = time.time()
        self.open()
        try:
            if not self.app.socket_wrap_monitor.is_running():
                self.app.socket_wrap_monitor.start()
        except AttributeError:
            self.app.socket_wrap_monitor = tornado.ioloop.PeriodicCallback(
                self.socket_wrap_monitor_thread, 15000
            )
            self.app.socket_wrap_monitor.start()

    def socket_wrap_monitor_thread(self):
        # TODO mark wrapped subs and sources separately
        if len(self.subs) > 0 or len(self.sources) > 0:
            for sub in list(self.subs.values()):
                if time.time() - sub.last_read_time > MAX_SOCKET_WAIT:
                    sub.close()
            for sub in list(self.sources.values()):
                if time.time() - sub.last_read_time > MAX_SOCKET_WAIT:
                    sub.close()
        else:
            self.app.socket_wrap_monitor.stop()

    def broadcast_layouts(self, target_subs=None):
        if target_subs is None:
            target_subs = self.subs.values()
        for sub in target_subs:
            sub.write_message(json.dumps(
                {'command': 'layout_update', 'data': self.app.layouts}
            ))

    def open(self):
        self.sid = get_rand_id()
        if self not in list(self.subs.values()):
            self.eid = 'main'
            self.subs[self.sid] = self
        logging.info('Mocking new socket: {}'.format(self.sid))

        self.write_message(
            json.dumps({'command': 'register', 'data': self.sid,
                        'readonly': self.readonly}))
        self.broadcast_layouts([self])
        broadcast_envs(self, [self])

    def on_message(self, message):
        logging.info('from web client: {}'.format(message))
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))

        cmd = msg.get('cmd')

        if self.readonly:
            return

        if cmd == 'close':
            if 'data' in msg and 'eid' in msg:
                logging.info('closing window {}'.format(msg['data']))
                p_data = self.state[msg['eid']]['jsons'].pop(msg['data'], None)
                event = {
                    'event_type': 'close',
                    'target': msg['data'],
                    'eid': msg['eid'],
                    'pane_data': p_data,
                }
                send_to_sources(self, event)
        elif cmd == 'save':
            # save localStorage window metadata
            if 'data' in msg and 'eid' in msg:
                msg['eid'] = escape_eid(msg['eid'])
                self.state[msg['eid']] = \
                    copy.deepcopy(self.state[msg['prev_eid']])
                self.state[msg['eid']]['reload'] = msg['data']
                self.eid = msg['eid']
                serialize_env(self.state, [self.eid], env_path=self.env_path)
        elif cmd == 'delete_env':
            if 'eid' in msg:
                logging.info('closing environment {}'.format(msg['eid']))
                del self.state[msg['eid']]
                if self.env_path is not None:
                    p = os.path.join(
                        self.env_path,
                        "{0}.json".format(msg['eid'])
                    )
                    os.remove(p)
                broadcast_envs(self)
        elif cmd == 'save_layouts':
            if 'data' in msg:
                self.app.layouts = msg.get('data')
                self.app.save_layouts()
                self.broadcast_layouts()
        elif cmd == 'forward_to_vis':
            packet = msg.get('data')
            environment = self.state[packet['eid']]
            packet['pane_data'] = environment['jsons'][packet['target']]
            send_to_sources(self, msg.get('data'))
        elif cmd == 'layout_item_update':
            eid = msg.get('eid')
            win = msg.get('win')
            self.state[eid]['reload'][win] = msg.get('data')

    def close(self):
        if self in list(self.subs.values()):
            self.subs.pop(self.sid, None)

    def write_message(self, msg):
        self.messages.append(msg)

    def get_messages(self):
        to_send = []
        while len(self.messages) > 0:
            message = self.messages.pop()
            if isinstance(message, dict):
                # Not all messages are being formatted the same way (JSON)
                # TODO investigate
                message = json.dumps(message)
            to_send.append(message)
        self.last_read_time = time.time()
        return to_send


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


def update_window(p, args):
    """Adds new args to a window if they exist"""
    content = p['content']
    layout_update = args.get('layout', {})
    for layout_name, layout_val in layout_update.items():
        if layout_val is not None:
            content['layout'][layout_name] = layout_val
    opts = args.get('opts', {})
    for opt_name, opt_val in opts.items():
        if opt_val is not None:
            p[opt_name] = opt_val

    if 'legend' in opts:
        pdata = p['content']['data']
        for i, d in enumerate(pdata):
            d['name'] = opts['legend'][i]
    return p


def window(args):
    """ Build a window dict structure for sending to client """
    uid = args.get('win', 'window_' + get_rand_id())
    if uid is None:
        uid = 'window_' + get_rand_id()
    opts = args.get('opts', {})

    ptype = args['data'][0]['type']

    p = {
        'command': 'window',
        'id': str(uid),
        'title': opts.get('title', ''),
        'inflate': opts.get('inflate', True),
        'width': opts.get('width'),
        'height': opts.get('height'),
        'contentID': get_rand_id(),   # to detected updated windows
    }

    if ptype == 'image_history':
        p.update({
            'content': [args['data'][0]['content']],
            'selected': 0,
            'type': ptype,
            'show_slider': opts.get('show_slider', True)
        })
    elif ptype in ['image', 'text', 'properties']:
        p.update({'content': args['data'][0]['content'], 'type': ptype})
    elif ptype == 'network':
        p.update({
            'content': args['data'][0]['content'] ,
            'type': ptype,
            'directed': opts.get("directed", False),
            'showEdgeLabels' : opts.get("showEdgeLabels", "hover"),
            'showVertexLabels' : opts.get("showVertexLabels", "hover"),
        })
    elif ptype in ['embeddings']:
        p.update({
            'content': args['data'][0]['content'],
            'type': ptype,
            'old_content': [],  # Used to cache previous to prevent recompute
        })
        p['content']['has_previous'] = False
    else:
        p['content'] = {'data': args['data'], 'layout': args['layout']}
        p['type'] = 'plot'

    return p


def broadcast(self, msg, eid):
    for s in self.subs:
        if isinstance(self.subs[s].eid, dict):
            if eid in self.subs[s].eid:
                self.subs[s].write_message(msg)
        else:
            if self.subs[s].eid == eid:
                self.subs[s].write_message(msg)


def register_window(self, p, eid):
    # in case env doesn't exist
    is_new_env = False
    if eid not in self.state:
        is_new_env = True
        self.state[eid] = {'jsons': {}, 'reload': {}}

    env = self.state[eid]['jsons']

    if p['id'] in env:
        p['i'] = env[p['id']]['i']
    else:
        p['i'] = len(env)

    env[p['id']] = p

    broadcast(self, p, eid)
    if is_new_env:
        broadcast_envs(self)
    self.write(p['id'])


class PostHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
        self.handlers = {
            'update': UpdateHandler,
            'save': SaveHandler,
            'close': CloseHandler,
            'win_exists': ExistsHandler,
            'delete_env': DeleteEnvHandler,
        }

    @check_auth
    def post(self):
        req = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )

        if req.get('func') is not None:
            raise Exception(
                'Support for Lua Torch was deprecated following `v0.1.8.4`. '
                "If you'd like to use torch support, you'll need to download "
                "that release. You can follow the usage instructions there, "
                "but it is no longer officially supported."
            )

        eid = extract_eid(req)
        p = window(req)

        register_window(self, p, eid)


class ExistsHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)
        if args['win'] in handler.state[eid]['jsons']:
            handler.write('true')
        else:
            handler.write('false')

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


def order_by_key(kv):
    key, val = kv
    return key


# Based on json-stable-stringify-python from @haochi with some usecase modifications
def recursive_order(node):
    if isinstance(node, Mapping):
        ordered_mapping = OrderedDict(sorted(node.items(), key=order_by_key))
        for key, value in ordered_mapping.items():
            ordered_mapping[key] = recursive_order(value)
        return ordered_mapping
    elif isinstance(node, Sequence):
        if isinstance(node, (bytes,)):
            return node
        elif isinstance(node, (str,)):
            return node
        else:
            return [recursive_order(item) for item in node]
    if isinstance(node, float) and node.is_integer():
        return int(node)
    return node


def stringify(node):
    return json.dumps(recursive_order(node), separators=COMPACT_SEPARATORS)


def hash_md_window(window_json):
    json_string = stringify(window_json).encode("utf-8")
    return hashlib.md5(json_string).hexdigest()


class UpdateHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled

    @staticmethod
    def update_packet(p, args):
        old_p = copy.deepcopy(p)
        p = UpdateHandler.update(p, args)
        p['contentID'] = get_rand_id()
        # TODO: make_patch isn't high performance.
        # If bottlenecked we should build the patch ourselves.
        patch = jsonpatch.make_patch(old_p, p)
        return p, patch.patch

    @staticmethod
    def update(p, args):
        # Update text in window, separated by a line break
        if p['type'] == 'text':
            p['content'] += "<br>" + args['data'][0]['content']
            return p
        if p['type'] == 'embeddings':
            # TODO embeddings updates should be handled outside of the regular
            # update flow, as update packets are easy to create manually and
            # expensive to calculate otherwise
            if args['data']['update_type'] == 'EntitySelected':
                p['content']['selected'] = args['data']['selected']
            elif args['data']['update_type'] == 'RegionSelected':
                p['content']['selected'] = None
                print(len(p['content']['data']))
                p['old_content'].append(p['content']['data'])
                p['content']['has_previous'] = True
                p['content']['data'] = args['data']['points']
                print(len(p['content']['data']))
            return p
        if p['type'] == 'image_history':
            utype = args['data'][0]['type']
            if utype == 'image_history':
                p['content'].append(args['data'][0]['content'])
                p['selected'] = len(p['content']) - 1
            elif utype == 'image_update_selected':
                # TODO implement python client function for this
                # Bound the update to within the dims of the array
                selected = args['data']
                selected_not_neg = max(0, selected)
                selected_exists = min(len(p['content'])-1, selected_not_neg)
                p['selected'] = selected_exists
            return p

        pdata = p['content']['data']

        new_data = args.get('data')
        p = update_window(p, args)
        name = args.get('name')
        if name is None and new_data is None:
            return p  # we only updated the opts or layout
        append = args.get('append')

        idxs = list(range(len(pdata)))

        if name is not None:
            assert len(new_data) == 1 or args.get('delete')
            idxs = [i for i in idxs if pdata[i]['name'] == name]

        # Delete a trace
        if args.get('delete'):
            for idx in idxs:
                del pdata[idx]
            return p

        # add new heatmap data if plot has been deleted previously
        if len(idxs) == 0 and new_data[0]['type'] == 'heatmap':
            pdata.append(new_data[0])
            return p

        # update heatmap
        if len(idxs) == 1 and pdata[idxs[0]]['type'] == 'heatmap':
            plot = pdata[idxs[0]]
            new_data = new_data[0]
            dz = new_data["z"]
            updateDir = args["updateDir"]


            # first check if operation is valid
            if updateDir != "replace":
                del new_data["z"]

                if updateDir in ["appendRow", "prependRow"]:
                    checkdir = "y" 
                    if len(plot["z"][0]) != len(dz[0]):
                        logging.error("ERROR: There is a mismatch between the number of columns in existing plot ('%i') and new data ('%i')." % (len(plot["z"]), len(dz)))
                        return p
                else:
                    checkdir = "x" 
                    if len(plot["z"]) != len(dz):
                        logging.error("ERROR: There is a mismatch between the number of rows in existing plot ('%i') and new data ('%i')." % (len(plot["z"]), len(dz)))
                        return p
                updateNames = False
                if plot[checkdir] is not None and new_data[checkdir] is not None:
                    updateNames = True
                    if plot[checkdir] is not None and any(label in plot[checkdir] for label in new_data[checkdir]):
                        logging.error("ERROR: The new column names appear already in the plot. Please make sure to specify unique column names.")
                        return p
                elif plot[checkdir] is not None:
                    logging.error("ERROR: The column names have been specified in plot, however the requested update does not specify column names.")
                    return p
                elif new_data[checkdir] is not None:
                    logging.error("ERROR: The column names have been specified for update, however the plot to update does not specify column names.")
                    return p

            # append according to direction
            if updateDir == "appendRow":
                plot["z"] += dz
                if updateNames:
                    plot["y"] += new_data["y"]

            elif updateDir == "prependRow":
                plot["z"] = dz + plot["z"]
                if updateNames:
                    plot["y"] = new_data["y"] + plot["y"]

            elif updateDir == "appendColumn":
                for i, dzi in enumerate(dz):
                    plot["z"][i] += dzi
                if updateNames:
                    plot["x"] += new_data["x"]

            elif updateDir == "prependColumn":
                for i, dzi in enumerate(dz):
                    plot["z"][i] = dzi + plot["z"][i]
                if updateNames:
                    plot["x"] = new_data["x"] + plot["x"]

            # update opts
            # note: if we are appending, we do not want to modify the labels, as they have already been altered above
            if append:
                if "x" in new_data:
                    del new_data["x"]
                if "y" in new_data:
                    del new_data["y"]
            for k in new_data:
                if new_data[k] is not None or not append:
                    plot[k] = new_data[k]

            return p


        # inject new trace
        if len(idxs) == 0:
            idx = len(pdata)
            pdata.append(dict(pdata[0]))  # plot is not empty, clone an entry
            idxs = [idx]
            append = False
            pdata[idx] = new_data[0]
            for k, v in new_data[0].items():
                pdata[idx][k] = v
            pdata[idx]['name'] = name
            return p

        # Update traces
        for n, idx in enumerate(idxs):
            if all(math.isnan(i) or i is None for i in new_data[n]['x']):
                continue
            # handle data for plotting
            for axis in ['x', 'y']:
                pdata[idx][axis] = (pdata[idx][axis] + new_data[n][axis]) \
                    if append else new_data[n][axis]

            # handle marker properties
            if 'marker' not in new_data[n]:
                continue
            if 'marker' not in pdata[idx]:
                pdata[idx]['marker'] = {}
            pdata_marker = pdata[idx]['marker']
            for marker_prop in ['color']:
                if marker_prop not in new_data[n]['marker']:
                    continue
                if marker_prop not in pdata[idx]['marker']:
                    pdata[idx]['marker'][marker_prop] = []
                pdata_marker[marker_prop] = (
                    pdata_marker[marker_prop] +
                    new_data[n]['marker'][marker_prop]) if append else \
                    new_data[n]['marker'][marker_prop]

        return p

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)

        if args['win'] not in handler.state[eid]['jsons']:
            # Append to a window that doesn't exist attempts to create
            # that window
            append = args.get('append')
            if append:
                p = window(args)
                register_window(handler, p, eid)
            else:
                handler.write('win does not exist')
            return

        p = handler.state[eid]['jsons'][args['win']]

        if not (p['type'] == 'text' or p['type'] == 'image_history'
                or p['type'] == 'embeddings'
                or (len(p['content']['data']) == 0 or p['content']['data'][0]['type'] in
                ['scatter', 'scattergl', 'custom', 'heatmap'])):
            handler.write(
                'win is not scatter, heatmap, custom, image_history, embeddings, or text; '
                'was {}'.format(p['content']['data'][0]['type'] if len(p['content']['data']) > 0 else "empty"))
            return

        p, diff_packet = UpdateHandler.update_packet(p, args)
        # send the smaller of the patch and the updated pane
        if len(stringify(p)) <= len(stringify(diff_packet)):
            broadcast(handler, p, eid)
        else:
            hashed = hash_md_window(p)
            broadcast_packet = {
                'command': 'window_update',
                'win': args['win'],
                'env': eid,
                'content': diff_packet,
                'finalHash': hashed
            }
            broadcast(handler, broadcast_packet, eid)
        handler.write(p['id'])

    @check_auth
    def post(self):
        if self.login_enabled and not self.current_user:
            self.set_status(400)
            return
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class CloseHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)
        win = args.get('win')

        keys = \
            list(handler.state[eid]['jsons'].keys()) if win is None else [win]
        for win in keys:
            handler.state[eid]['jsons'].pop(win, None)
            broadcast(
                handler, json.dumps({'command': 'close', 'data': win}), eid
            )

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class SocketWrap(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
        self.app = app

    @check_auth
    def post(self):
        """Either write a message to the socket, or query what's there"""
        # TODO formalize failure reasons
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        type = args.get('message_type')
        sid = args.get('sid')
        socket_wrap = self.subs.get(sid)
        # ensure a wrapper still exists for this connection
        if socket_wrap is None:
            self.write(json.dumps({'success': False, 'reason': 'closed'}))
            return

        # handle the requests
        if type == 'query':
            messages = socket_wrap.get_messages()
            self.write(json.dumps({
                'success': True, 'messages': messages
            }))
        elif type == 'send':
            msg = args.get('message')
            if msg is None:
                self.write(json.dumps({'success': False, 'reason': 'no msg'}))
            else:
                socket_wrap.on_message(msg)
                self.write(json.dumps({'success': True}))
        else:
            self.write(json.dumps({'success': False, 'reason': 'invalid'}))

    @check_auth
    def get(self):
        """Create a new socket wrapper for this requester, return the id"""
        new_sub = ClientSocketWrapper(self.app)
        self.write(json.dumps({'success': True, 'sid': new_sub.sid}))


# TODO refactor socket wrappers to one class
class VisSocketWrap(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
        self.app = app

    @check_auth
    def post(self):
        """Either write a message to the socket, or query what's there"""
        # TODO formalize failure reasons
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        type = args.get('message_type')
        sid = args.get('sid')

        if sid is None:
            new_sub = VisSocketWrapper(self.app)
            self.write(json.dumps({'success': True, 'sid': new_sub.sid}))
            return

        socket_wrap = self.sources.get(sid)
        # ensure a wrapper still exists for this connection
        if socket_wrap is None:
            self.write(json.dumps({'success': False, 'reason': 'closed'}))
            return

        # handle the requests
        if type == 'query':
            messages = socket_wrap.get_messages()
            self.write(json.dumps({
                'success': True, 'messages': messages
            }))
        elif type == 'send':
            msg = args.get('message')
            if msg is None:
                self.write(json.dumps({'success': False, 'reason': 'no msg'}))
            else:
                socket_wrap.on_message(msg)
                self.write(json.dumps({'success': True}))
        else:
            self.write(json.dumps({'success': False, 'reason': 'invalid'}))


class DeleteEnvHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)
        if eid is not None:
            del handler.state[eid]
            if handler.env_path is not None:
                p = os.path.join(handler.env_path, "{0}.json".format(eid))
                os.remove(p)
            broadcast_envs(handler)

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class EnvStateHandler(BaseHandler):
    def initialize(self, app):
        self.app = app
        self.state = app.state
        self.login_enabled = app.login_enabled

    @staticmethod
    def wrap_func(handler, args):
        # TODO if an env is provided return the state of that env
        all_eids = list(handler.state.keys())
        handler.write(json.dumps(all_eids))

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class ForkEnvHandler(BaseHandler):
    def initialize(self, app):
        self.app = app
        self.state = app.state
        self.subs = app.subs
        self.login_enabled = app.login_enabled

    @staticmethod
    def wrap_func(handler, args):
        prev_eid = escape_eid(args.get('prev_eid'))
        eid = escape_eid(args.get('eid'))

        assert prev_eid in handler.state, 'env to be forked doesn\'t exit'

        handler.state[eid] = copy.deepcopy(handler.state[prev_eid])
        serialize_env(handler.state, [eid], env_path=handler.app.env_path)
        broadcast_envs(handler)

        handler.write(eid)

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class HashHandler(BaseHandler):
    def initialize(self, app):
        self.app = app
        self.state = app.state
        self.login_enabled = app.login_enabled

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)
        handler_json = handler.state[eid]['jsons']
        if args['win'] in handler_json:
            hashed = hash_md_window(handler_json[args['win']])
            handler.write(hashed)
        else:
            handler.write('false')

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


def load_env(state, eid, socket, env_path=DEFAULT_ENV_PATH):
    """ load an environment to a client by socket """
    env = {}
    if eid in state:
        env = state.get(eid)
    elif env_path is not None:
        p = os.path.join(env_path, eid.strip(), '.json')
        if os.path.exists(p):
            with open(p, 'r') as fn:
                env = tornado.escape.json_decode(fn.read())
                state[eid] = env

    if 'reload' in env:
        socket.write_message(
            json.dumps({'command': 'reload', 'data': env['reload']})
        )

    jsons = list(env.get('jsons', {}).values())
    windows = sorted(jsons, key=lambda k: ('i' not in k, k.get('i', None)))
    for v in windows:
        socket.write_message(v)

    socket.write_message(json.dumps({'command': 'layout'}))
    socket.eid = eid


def gather_envs(state, env_path=DEFAULT_ENV_PATH):
    if env_path is not None:
        items = [i.replace('.json', '') for i in os.listdir(env_path)
                 if '.json' in i]
    else:
        items = []
    return sorted(list(set(items + list(state.keys()))))


def compare_envs(state, eids, socket, env_path=DEFAULT_ENV_PATH):
    logging.info('comparing envs')

    # queries from eids-list
    # - envs: a list of all (eid -> env) pairs. (directly loads envs if not yet loaded)
    # - res: a single env containing all windows with titles
    # - title2Win: a dict of all (title -> win) pairs
    # note: In case multiple windows share the same title, any window
    #   could be used. we use the first occurence as a compare view
    envs, res, title2Win = [], {'jsons': {}, 'reload': {}}, {}
    for eid in eids:

        if eid in state:
            env = state.get(eid)
        elif env_path is not None:
            p = os.path.join(env_path, eid.strip(), '.json')
            if os.path.exists(p):
                with open(p, 'r') as fn:
                    env = tornado.escape.json_decode(fn.read())
                    state[eid] = env
            else:
                continue

        envs.append(env)
        for winId, win in env['jsons'].items():
            if "title" in win and win["title"] and win["title"] not in title2Win:
                comparewinId = winId + "_compare"
                title2Win[win["title"]] = comparewinId
                res['jsons'][comparewinId] = copy.deepcopy(env['jsons'][winId])
                if isinstance(res['jsons'][comparewinId]['content'], dict):
                    res['jsons'][comparewinId]['content']["data"] = []
                else:
                    res['jsons'][comparewinId]['content'] = ""
                res['jsons'][comparewinId]["compare_content"] = []
                res['jsons'][comparewinId]["compare_selection_i"] = 0
                res['jsons'][comparewinId]['has_compare'] = True
                res['jsons'][comparewinId]['compare_view_mode'] = "select"
                res['jsons'][comparewinId]['compare_content_info'] = []
                res['jsons'][comparewinId]['contentID'] = get_rand_id()
    logging.error("compare")

    # TODO: next, merge 
    tableRows = []
    for eidNum, env in enumerate(envs):

        perEnvTitleCount = {}
        for wid in env.get('jsons', {}).keys():
            win = env['jsons'][wid]
            if 'content' not in win:
                continue
            if 'title' not in win or not win["title"]:
                continue

            # set up the window to show compare data in
            title = win["title"]
            content_copy = copy.deepcopy(win['content'])
            destwin = res['jsons'][title2Win[title]]
            if title not in perEnvTitleCount:
                perEnvTitleCount[title] = 0
            else:
                perEnvTitleCount[title] += 1
            destwin['compare_content_info'].append({
                "envId": eidNum,
                "plot_name": str(eidNum)+"_"+str(perEnvTitleCount[title]),
                "content_i": len(destwin['compare_content']),
            })
            destwin['compare_content'].append(content_copy)

            # If plot data source was labeled "name" in the legend, rename to
            # "envId_legend" where envId is enumeration of the selected
            # environments (not the long environment id string). This makes plot
            # lines more readable.
            if isinstance(content_copy, dict) and "data" in content_copy:
                for _dataIdx, data in enumerate(content_copy["data"]):
                    if 'name' in data:
                        data['compare_name'] = '{}_{}'.format(eidNum, data['name'])

        # create legend mapping environment names to environment numbers so one can
        # look it up for the new legend
        tableRows.append("<tr> <td> {} </td> <td> {} </td> </tr>".format(eids[eidNum], eidNum))

    # in case all plot types in a window are line plot, we can use merge-mode
    for win in res['jsons'].values():
        all_scatter = True
        if isinstance(win['content'], dict) and 'layout' in win['content']:
            for content_list in win['compare_content']:
                for data in content_list["data"]:
                    if data['type'] != 'scatter':
                        all_scatter = False
                        break
                if not all_scatter:
                    break
            if all_scatter:
                win['content']['layout']['showlegend'] = True
                win['compare_view_mode'] = 'merge'
        else:
            if isinstance(win['content'], dict) and 'layout' in win['content'] and 'margin' in win['content']['layout']:
                win['content']['layout']['margin']['b'] += 20

    tbl = """"<style>
    table, th, td {{
        border: 1px solid black;
    }}
    </style>
    <table> {} </table>
    """.format(' '.join(tableRows))

    res['jsons']['window_compare_legend'] = {
        "command": "window",
        "id": "window_compare_legend",
        "title": "compare_legend",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": "compare_legend",
        "content": tbl,
        "type": "text",
        "layout": {"title": "compare_legend"},
        "i": 1,
        "has_compare": True,
    }
    # TODO needed?
    # if 'reload' in res:
    #     socket.write_message(
    #         json.dumps({'command': 'reload', 'data': res['reload']})
    #     )

    jsons = list(res.get('jsons', {}).values())
    windows = sorted(jsons, key=lambda k: ('i' not in k, k.get('i', None)))
    for v in windows:
        socket.write_message(v)

    socket.write_message(json.dumps({'command': 'layout'}))
    socket.eid = eids


class EnvHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
        self.wrap_socket = app.wrap_socket

    @check_auth
    def get(self, eid):
        items = gather_envs(self.state, env_path=self.env_path)
        active = '' if eid not in items else eid
        self.render(
            'index.html',
            user=getpass.getuser(),
            items=items,
            active_item=active,
            wrap_socket=self.wrap_socket,
        )

    @check_auth
    def post(self, args):
        msg_args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        if 'sid' in msg_args:
            sid = msg_args['sid']
            if sid in self.subs:
                load_env(self.state, args, self.subs[sid],
                         env_path=self.env_path)
        if 'eid' in msg_args:
            eid = msg_args['eid']
            if eid not in self.state:
                self.state[eid] = {'jsons': {}, 'reload': {}}
                broadcast_envs(self)


class CompareHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
        self.wrap_socket = app.wrap_socket

    @check_auth
    def get(self, eids):
        items = gather_envs(self.state)
        eids = eids.split('+')
        # Filter out eids that don't exist
        eids = [x for x in eids if x in items]
        eids = '+'.join(eids)
        self.render(
            'index.html',
            user=getpass.getuser(),
            items=items,
            active_item=eids,
            wrap_socket=self.wrap_socket,
        )

    @check_auth
    def post(self, args):
        sid = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )['sid']
        if sid in self.subs:
            compare_envs(self.state, args.split('+'), self.subs[sid],
                         self.env_path)


class SaveHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled

    @staticmethod
    def wrap_func(handler, args):
        envs = args['data']
        envs = [escape_eid(eid) for eid in envs]
        # this drops invalid env ids
        ret = serialize_env(handler.state, envs, env_path=handler.env_path)
        handler.write(json.dumps(ret))

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class DataHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled

    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)

        if 'data' in args:
            # Load data from client
            data = json.loads(args['data'])

            if eid not in handler.state:
                handler.state[eid] = {'jsons': {}, 'reload': {}}

            if 'win' in args and args['win'] is None:
                handler.state[eid]['jsons'] = data
            else:
                handler.state[eid]['jsons'][args['win']] = data

            broadcast_envs(handler)
        else:
            # Dump data to client
            if 'win' in args and args['win'] is None:
                handler.write(json.dumps(handler.state[eid]['jsons']))
            else:
                assert args['win'] in handler.state[eid]['jsons'], \
                    "Window {} doesn't exist in env {}".format(args['win'], eid)
                handler.write(json.dumps(handler.state[eid]['jsons'][args['win']]))

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class IndexHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
        self.user_credential = app.user_credential
        self.base_url = app.base_url if app.base_url != '' else '/'
        self.wrap_socket = app.wrap_socket

    def get(self, args, **kwargs):
        items = gather_envs(self.state, env_path=self.env_path)
        if (not self.login_enabled) or self.current_user:
            """self.current_user is an authenticated user provided by Tornado,
            available when we set self.get_current_user in BaseHandler,
            and the default value of self.current_user is None
            """
            self.render(
                'index.html',
                user=getpass.getuser(),
                items=items,
                active_item='',
                wrap_socket=self.wrap_socket,
            )
        elif self.login_enabled:
            self.render(
                'login.html',
                user=getpass.getuser(),
                items=items,
                active_item='',
                base_url=self.base_url
            )

    def post(self, arg, **kwargs):
        json_obj = tornado.escape.json_decode(self.request.body)
        username = json_obj["username"]
        password = hash_password(json_obj["password"])

        if ((username == self.user_credential["username"]) and
                (password == self.user_credential["password"])):
            self.set_secure_cookie("user_password", username + password)
        else:
            self.set_status(400)


class UserSettingsHandler(BaseHandler):
    def initialize(self, app):
        self.user_settings = app.user_settings

    def get(self, path):
        if path == "style.css":
            self.set_status(200)
            self.set_header("Content-type", "text/css")
            self.write(self.user_settings['user_css'])


class ErrorHandler(BaseHandler):
    def get(self, text):
        error_text = text or "test error"
        raise Exception(error_text)


# function that downloads and installs javascript, css, and font dependencies:
def download_scripts(proxies=None, install_dir=None):
    import visdom
    print("Checking for scripts.")

    # location in which to download stuff:
    if install_dir is None:
        install_dir = os.path.dirname(visdom.__file__)

    # all files that need to be downloaded:
    b = 'https://unpkg.com/'
    bb = '%sbootstrap@3.3.7/dist/' % b
    ext_files = {
        # - js
        '%sjquery@3.1.1/dist/jquery.min.js' % b: 'jquery.min.js',
        '%sbootstrap@3.3.7/dist/js/bootstrap.min.js' % b: 'bootstrap.min.js',
        '%sreact@16.2.0/umd/react.production.min.js' % b: 'react-react.min.js',
        '%sreact-dom@16.2.0/umd/react-dom.production.min.js' % b:
            'react-dom.min.js',
        '%sreact-modal@3.1.10/dist/react-modal.min.js' % b:
            'react-modal.min.js',
        # here is another url in case the cdn breaks down again.
        # https://raw.githubusercontent.com/plotly/plotly.js/master/dist/plotly.min.js
        'https://cdn.plot.ly/plotly-latest.min.js': 'plotly-plotly.min.js',
        # Stanford Javascript Crypto Library for Password Hashing
        '%ssjcl@1.0.7/sjcl.js' % b: 'sjcl.js',
        '%slayout-bin-packer@1.4.0/dist/layout-bin-packer.js.map' % b: 'layout-bin-packer.js.map',
        # d3 Libraries for plotting d3 graphs!
        'http://d3js.org/d3.v3.min.js' : 'd3.v3.min.js',
        'https://d3js.org/d3-selection-multi.v1.js' : 'd3-selection-multi.v1.js',
        # Library to download the svg to png
        '%ssave-svg-as-png@1.4.17/lib/saveSvgAsPng.js' % b: 'saveSvgAsPng.js',

        # - css
        '%sreact-resizable@1.4.6/css/styles.css' % b:
            'react-resizable-styles.css',
        '%sreact-grid-layout@0.16.3/css/styles.css' % b:
            'react-grid-layout-styles.css',
        '%scss/bootstrap.min.css' % bb: 'bootstrap.min.css',

        # - fonts
        '%sclassnames@2.2.5' % b: 'classnames',
        '%slayout-bin-packer@1.4.0/dist/layout-bin-packer.js' % b:
            'layout_bin_packer.js',
        '%sfonts/glyphicons-halflings-regular.eot' % bb:
            'glyphicons-halflings-regular.eot',
        '%sfonts/glyphicons-halflings-regular.woff2' % bb:
            'glyphicons-halflings-regular.woff2',
        '%sfonts/glyphicons-halflings-regular.woff' % bb:
            'glyphicons-halflings-regular.woff',
        '%sfonts/glyphicons-halflings-regular.ttf' % bb:
            'glyphicons-halflings-regular.ttf',
        '%sfonts/glyphicons-halflings-regular.svg#glyphicons_halflingsregular' % bb:  # noqa
            'glyphicons-halflings-regular.svg#glyphicons_halflingsregular',
    }

    # make sure all relevant folders exist:
    dir_list = [
        '%s' % install_dir,
        '%s/static' % install_dir,
        '%s/static/js' % install_dir,
        '%s/static/css' % install_dir,
        '%s/static/fonts' % install_dir,
    ]
    for directory in dir_list:
        if not os.path.exists(directory):
            os.makedirs(directory)

    # set up proxy handler:
    from urllib import request
    from urllib.error import HTTPError, URLError
    handler = request.ProxyHandler(proxies) if proxies is not None \
        else request.BaseHandler()
    opener = request.build_opener(handler)
    request.install_opener(opener)

    built_path = os.path.join(here, 'static/version.built')
    is_built = visdom.__version__ == 'no_version_file'
    if os.path.exists(built_path):
        with open(built_path, 'r') as build_file:
            build_version = build_file.read().strip()
        if build_version == visdom.__version__:
            is_built = True
        else:
            os.remove(built_path)
    if not is_built:
        print('Downloading scripts, this may take a little while')

    # download files one-by-one:
    for (key, val) in ext_files.items():

        # set subdirectory:
        if val.endswith('.js') or val.endswith('.js.map'):
            sub_dir = 'js'
        elif val.endswith('.css'):
            sub_dir = 'css'
        else:
            sub_dir = 'fonts'

        # download file:
        filename = '%s/static/%s/%s' % (install_dir, sub_dir, val)
        if not os.path.exists(filename) or not is_built:
            req = request.Request(key,
                                  headers={'User-Agent': 'Chrome/30.0.0.0'})
            try:
                data = opener.open(req).read()
                with open(filename, 'wb') as fwrite:
                    fwrite.write(data)
            except HTTPError as exc:
                logging.error('Error {} while downloading {}'.format(
                    exc.code, key))
            except URLError as exc:
                logging.error('Error {} while downloading {}'.format(
                    exc.reason, key))

    # Download MathJax Js Files
    import requests
    cdnjs_url = 'https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.5/'
    mathjax_dir = os.path.join(*cdnjs_url.split('/')[-3:])
    mathjax_path = [
        'config/Safe.js?V=2.7.5',
        'config/TeX-AMS-MML_HTMLorMML.js?V=2.7.5',
        'extensions/Safe.js?V=2.7.5',
        'jax/output/SVG/fonts/TeX/fontdata.js?V=2.7.5',
        'jax/output/SVG/jax.js?V=2.7.5',
        'jax/output/SVG/fonts/TeX/Size1/Regular/Main.js?V=2.7.5',
        'jax/output/SVG/config.js?V=2.7.5',
        'MathJax.js?config=TeX-AMS-MML_HTMLorMML%2CSafe.js&#038;ver=4.1',
    ]
    mathjax_dir_path = '%s/static/%s/%s' % (install_dir, 'js', mathjax_dir)

    for path in mathjax_path:
        filename = path.split("/")[-1].split("?")[0]
        extracted_directory = os.path.join(mathjax_dir_path, *path.split('/')[:-1])
        if not os.path.exists(extracted_directory):
            os.makedirs(extracted_directory)
        if not os.path.exists(os.path.join(extracted_directory, filename)):
            js_file = requests.get(cdnjs_url + path)
            with open(os.path.join(extracted_directory, filename), "wb+") as file:
                file.write(js_file.content)

    if not is_built:
        with open(built_path, 'w+') as build_file:
            build_file.write(visdom.__version__)


def start_server(port=DEFAULT_PORT, hostname=DEFAULT_HOSTNAME,
                 base_url=DEFAULT_BASE_URL, env_path=DEFAULT_ENV_PATH,
                 readonly=False, print_func=None, user_credential=None,
                 use_frontend_client_polling=False, bind_local=False,
                 eager_data_loading=False):
    print("It's Alive!")
    app = Application(port=port, base_url=base_url, env_path=env_path,
                      readonly=readonly, user_credential=user_credential,
                      use_frontend_client_polling=use_frontend_client_polling,
                      eager_data_loading=eager_data_loading)
    if bind_local:
        app.listen(port, max_buffer_size=1024 ** 3, address='127.0.0.1')
    else:
        app.listen(port, max_buffer_size=1024 ** 3)
    logging.info("Application Started")

    if "HOSTNAME" in os.environ and hostname == DEFAULT_HOSTNAME:
        hostname = os.environ["HOSTNAME"]
    else:
        hostname = hostname
    if print_func is None:
        print(
            "You can navigate to http://%s:%s%s" % (hostname, port, base_url))
    else:
        print_func(port)
    ioloop.IOLoop.instance().start()
    app.subs = []
    app.sources = []


def main(print_func=None):
    parser = argparse.ArgumentParser(description='Start the visdom server.')
    parser.add_argument('-port', metavar='port', type=int,
                        default=DEFAULT_PORT,
                        help='port to run the server on.')
    parser.add_argument('--hostname', metavar='hostname', type=str,
                        default=DEFAULT_HOSTNAME,
                        help='host to run the server on.')
    parser.add_argument('-base_url', metavar='base_url', type=str,
                        default=DEFAULT_BASE_URL,
                        help='base url for server (default = /).')
    parser.add_argument('-env_path', metavar='env_path', type=str,
                        default=DEFAULT_ENV_PATH,
                        help='path to serialized session to reload.')
    parser.add_argument('-logging_level', metavar='logger_level',
                        default='INFO',
                        help='logging level (default = INFO). Can take '
                             'logging level name or int (example: 20)')
    parser.add_argument('-readonly', help='start in readonly mode',
                        action='store_true')
    parser.add_argument('-enable_login', default=False, action='store_true',
                        help='start the server with authentication')
    parser.add_argument('-force_new_cookie', default=False,
                        action='store_true',
                        help='start the server with the new cookie, '
                             'available when -enable_login provided')
    parser.add_argument('-use_frontend_client_polling', default=False,
                        action='store_true',
                        help='Have the frontend communicate via polling '
                             'rather than over websockets.')
    parser.add_argument('-bind_local', default=False,
                        action='store_true',
                        help='Make server only accessible only from '
                             'localhost.')
    parser.add_argument('-eager_data_loading', default=False,
                        action='store_true',
                        help='Load data from filesystem when starting server (and not lazily upon first request).')
    FLAGS = parser.parse_args()

    # Process base_url
    base_url = FLAGS.base_url if FLAGS.base_url != DEFAULT_BASE_URL else ""
    assert base_url == '' or base_url.startswith('/'), \
        'base_url should start with /'
    assert base_url == '' or not base_url.endswith('/'), \
        'base_url should not end with / as it is appended automatically'

    try:
        logging_level = int(FLAGS.logging_level)
    except ValueError:
        try:
            logging_level = logging._checkLevel(FLAGS.logging_level)
        except ValueError:
            raise KeyError(
                "Invalid logging level : {0}".format(FLAGS.logging_level)
            )

    logging.getLogger().setLevel(logging_level)

    if FLAGS.enable_login:
        enable_env_login = 'VISDOM_USE_ENV_CREDENTIALS'
        use_env = os.environ.get(enable_env_login, False)
        if use_env:
            username_var = 'VISDOM_USERNAME'
            password_var = 'VISDOM_PASSWORD'
            username = os.environ.get(username_var)
            password = os.environ.get(password_var)
            if not (username and password):
                print(
                    '*** Warning ***\n'
                    'You have set the {0} env variable but probably '
                    'forgot to setup one (or both) {{ {1}, {2} }} '
                    'variables.\nYou should setup these variables with '
                    'proper username and password to enable logging. Try to '
                    'setup the variables, or unset {0} to input credentials '
                    'via command line prompt instead.\n'
                    .format(enable_env_login, username_var, password_var))
                sys.exit(1)

        else:
            username = input("Please input your username: ")
            password = getpass.getpass(prompt="Please input your password: ")

        user_credential = {
            "username": username,
            "password": hash_password(hash_password(password))
        }

        need_to_set_cookie = (
            not os.path.isfile(DEFAULT_ENV_PATH + "COOKIE_SECRET")
            or FLAGS.force_new_cookie)

        if need_to_set_cookie:
            if use_env:
                cookie_var = 'VISDOM_COOKIE'
                env_cookie = os.environ.get(cookie_var)
                if env_cookie is None:
                    print(
                        'The cookie file is not found. Please setup {0} env '
                        'variable to provide a cookie value, or unset {1} env '
                        'variable to input credentials and cookie via command '
                        'line prompt.'.format(cookie_var, enable_env_login))
                    sys.exit(1)
            else:
                env_cookie = None
            set_cookie(env_cookie)

    else:
        user_credential = None

    start_server(port=FLAGS.port, hostname=FLAGS.hostname, base_url=base_url,
                 env_path=FLAGS.env_path, readonly=FLAGS.readonly,
                 print_func=print_func, user_credential=user_credential,
                 use_frontend_client_polling=FLAGS.use_frontend_client_polling,
                 bind_local=FLAGS.bind_local,
                 eager_data_loading=FLAGS.eager_data_loading)

def download_scripts_and_run():
    download_scripts()
    main()


if __name__ == "__main__":
    download_scripts_and_run()
