#!/usr/bin/env python3

# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Handlers for the different types of web request events. Mostly handles parsing
and processing the web events themselves and interfacing with the server as
necessary, but defers underlying manipulations of the server's data to
the data_model itself.
"""

# TODO fix these imports
from visdom.utils.shared_utils import *
from visdom.utils.server_utils import *
from visdom.server.handlers.base_handlers import BaseHandler
import copy
import getpass
import hashlib
import json
import jsonpatch
import logging
import math
import os
import time
from collections import OrderedDict
try:
    # for after python 3.8
    from collections.abc import Mapping, Sequence
except ImportError:
    # for python 3.7 and below
    from collections import Mapping, Sequence

import tornado.escape

MAX_SOCKET_WAIT = 15


# TODO move the logic that actually parses environments and layouts to
# new classes in the data_model folder.
# TODO move generalized initialization logic from these handlers into the
# basehandler
# TODO abstract out any direct references to the app where possible from
# all handlers. Can instead provide accessor functions on the state?
class PostHandler(BaseHandler):
    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled

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
                or p['content']['data'][0]['type'] in
                ['scatter', 'scattergl', 'custom']):
            handler.write(
                'win is not scatter, custom, image_history, embeddings, or text; '
                'was {}'.format(p['content']['data'][0]['type']))
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


class ErrorHandler(BaseHandler):
    def get(self, text):
        error_text = text or "test error"
        raise Exception(error_text)
