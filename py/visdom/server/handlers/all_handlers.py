#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Server"""

# TODO fix these imports
from visdom.utils.shared_utils import *
from visdom.utils.server_utils import *
from visdom.server.handlers.base_handlers import *
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
from collections.abc import Mapping
try:
    # for after python 3.8
    from collections.abc import Mapping, Sequence
except ImportError:
    # for python 3.7 and below
    from collections import Mapping, Sequence

import tornado.ioloop     # noqa E402: gotta install ioloop first
import tornado.web        # noqa E402: gotta install ioloop first
import tornado.websocket  # noqa E402: gotta install ioloop first
import tornado.escape     # noqa E402: gotta install ioloop first

LAYOUT_FILE = 'layouts.json'

here = os.path.abspath(os.path.dirname(__file__))
COMPACT_SEPARATORS = (',', ':')

MAX_SOCKET_WAIT = 15

# TODO Split this file up it's terrible

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
        if eid in handler.state and args['win'] in handler.state[eid]['jsons']:
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
