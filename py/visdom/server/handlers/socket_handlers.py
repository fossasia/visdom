#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Handlers for the different types of socket events. Mostly handles parsing and
processing the web events themselves and interfacing with the server as
necessary, but defers underlying manipulations of the server's data to
the data_model itself.
"""

import copy
import json
import logging
import os
import time
import types

import tornado.ioloop
import tornado.escape
from visdom.server.handlers.base_handlers import BaseWebSocketHandler, BaseHandler
from visdom.utils.shared_utils import get_rand_id
from visdom.utils.server_utils import (
    check_auth,
    broadcast_envs,
    serialize_env,
    send_to_sources,
    broadcast,
    escape_eid,
)
from visdom.server.defaults import MAX_SOCKET_WAIT

# TODO move the logic that actually parses environments and layouts to
# new classes in the data_model folder.
# TODO move generalized initialization logic from these handlers into the
# basehandler
# TODO abstract out any direct references to the app where possible from
# all handlers. Can instead provide accessor functions on the state?
# TODO Try to standardize the code between the client-server and
# visdom-server socket edges.


# ============== #
# About & Naming #
# ============== #

# 1. *Handler- & *Wrap-classes are intended to have the same functionality
#   - *Handler (e.g. VisSocketHandler) use WebSockets
#   - *Wrap (e.g. VisSocketWrap) use polling-based connections instead
#   - *Wrapper (e.g. VisSocketWrapper) is just a helper class for the respective *Wrap-class
#     to process the current state (instead of the state at the time of polling)
# 2. VisSocket* classes (VisSocketHandler, VisSocketWrap & VisSocketWrapper)
#   Their goal is to register clients with write access of actual data.
# 3. Socket* classes (SocketHandler, SocketWrap & SocketWrapper)
#   Their goal is to register clients with read access of data.
#   Write access is limited to data and view organization (i.e. layout settings, env removal and env saving)


class AnySocketHandlerOrWrapper(BaseWebSocketHandler):
    def __init__(self, *args, **kwargs):
        self.polling = False
        super().__init__(*args, **kwargs)

    def initialize(self, app):
        self.state = app.state
        self.subs = app.subs
        self.sources = app.sources
        self.port = app.port
        self.env_path = app.env_path
        self.login_enabled = app.login_enabled
        self.app = app
        self.readonly = app.readonly

    def open(self, register_to="sources"):
        # self.sid = str(hex(int(time.time() * 10000000))[2:]) # TODO: was previously used for websockets+vis only
        self.sid = get_rand_id()
        register_list = self.sources if register_to == "sources" else self.subs
        if self not in list(register_list.values()):
            self.eid = "main"
            register_list[self.sid] = self

    def broadcast_layouts(self):
        raise ValueError("Should be replaced in child class")

    def on_message(self, message):
        logging.info(f"from visdom client: {message}")
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))

        cmd = msg.get("cmd")
        if self.readonly:
            return

        elif cmd == "close":
            if "data" in msg and "eid" in msg:
                logging.info(f"closing window {msg['data']}")
                p_data = self.state[msg["eid"]]["jsons"].pop(msg["data"], None)
                event = {
                    "event_type": "close",
                    "target": msg["data"],
                    "eid": msg["eid"],
                    "pane_data": p_data,
                }
                send_to_sources(self, event)

        elif cmd == "save":
            # save localStorage window metadata
            if "data" in msg and "eid" in msg:
                msg["eid"] = escape_eid(msg["eid"])
                self.state[msg["eid"]] = copy.deepcopy(self.state[msg["prev_eid"]])
                self.state[msg["eid"]]["reload"] = msg["data"]
                self.eid = msg["eid"]
                serialize_env(self.state, [self.eid], env_path=self.env_path)

        elif cmd == "delete_env":
            if "eid" in msg:
                logging.info(f"closing environment {msg['eid']}")
                del self.state[msg["eid"]]
                if self.env_path is not None:
                    p = os.path.join(self.env_path, "{0}.json".format(msg["eid"]))
                    os.remove(p)
                broadcast_envs(self)

        elif cmd == "save_layouts":
            if "data" in msg:
                self.app.layouts = msg.get("data")
                self.app.save_layouts()
                self.broadcast_layouts()

        elif cmd == "forward_to_vis":
            packet = msg.get("data")
            environment = self.state[packet["eid"]]
            if packet.get("pane_data") is not False:
                packet["pane_data"] = environment["jsons"][packet["target"]]
            send_to_sources(self, msg.get("data"))

        elif cmd == "layout_item_update":
            eid = msg.get("eid")
            win = msg.get("win")
            self.state[eid]["reload"][win] = msg.get("data")

        elif cmd == "pop_embeddings_pane":
            packet = msg.get("data")
            eid = packet["eid"]
            win = packet["target"]
            p = self.state[eid]["jsons"][win]
            p["content"]["selected"] = None
            p["content"]["data"] = p["old_content"].pop()
            if len(p["old_content"]) == 0:
                p["content"]["has_previous"] = False
            p["contentID"] = get_rand_id()
            broadcast(self, p, eid)


class AnySocketWrapper(AnySocketHandlerOrWrapper):
    def __init__(self, *args, **kwargs):
        self.polling = True
        super().__init__(*args, **kwargs)

    def initialize(self, app):
        super().initialize(app)

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
        if len(self.subs) > 0 or len(self.sources) > 0:
            for sub in list(self.subs.values()):
                if (
                    hasattr(sub, "last_read_time")
                    and time.time() - sub.last_read_time > MAX_SOCKET_WAIT
                ):
                    sub.close()
            for sub in list(self.sources.values()):
                if (
                    hasattr(sub, "last_read_time")
                    and time.time() - sub.last_read_time > MAX_SOCKET_WAIT
                ):
                    sub.close()
        else:
            self.app.socket_wrap_monitor.stop()

    def close(self):
        self.on_close()

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


class VisSocketHandlerOrWrapper(AnySocketHandlerOrWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def open(self):
        logging.info(
            f'{"Mocking" if self.polling else "Opened"} visdom source socket from ip: {self.request.remote_ip}'
        )
        if self.login_enabled and not self.current_user:
            self.close()
            return
        super().open("sources")
        self.write_message(json.dumps({"command": "alive", "data": "vis_alive"}))

    def on_close(self):
        if self in list(self.sources.values()):
            self.sources.pop(self.sid, None)

    def on_message(self, message):
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))
        cmd = msg.get("cmd")

        if cmd == "echo":
            logging.info(f"from visdom client: {message}")
            for sub in self.sources.values():
                sub.write_message(json.dumps(msg))
            return

        super().on_message(message)


class VisSocketHandler(VisSocketHandlerOrWrapper):
    pass


class VisSocketWrapper(VisSocketHandlerOrWrapper, AnySocketWrapper):
    # this ignores tornados initialization
    def __init__(self):
        self.polling = True
        pass


class SocketHandlerOrWrapper(AnySocketHandlerOrWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def open(self):
        logging.info(
            f'{"Mocking" if self.polling else "Opened"} visdom sub socket from ip: {self.request.remote_ip}'
        )

        if self.login_enabled and not self.current_user:
            print("AUTH Failed in SocketHandler")
            self.close()
            return

        super().open("subs")

        self.write_message(
            json.dumps(
                {"command": "register", "data": self.sid, "readonly": self.readonly}
            )
        )
        self.broadcast_layouts([self])
        broadcast_envs(self, [self])

    def broadcast_layouts(self, target_subs=None):
        if target_subs is None:
            target_subs = self.subs.values()
        for sub in target_subs:
            sub.write_message(
                json.dumps({"command": "layout_update", "data": self.app.layouts})
            )

    def initialize(self, app):
        super().initialize(app)
        self.broadcast_layouts()

    def on_close(self):
        if self in list(self.subs.values()):
            self.subs.pop(self.sid, None)


class SocketHandler(SocketHandlerOrWrapper):
    pass


class SocketWrapper(SocketHandlerOrWrapper, AnySocketWrapper):
    # this ignores tornados initialization
    def __init__(self):
        self.polling = True
        pass


def WrapSocketWrapper(BaseWrapper):
    class WrappedSocketWrap(BaseHandler):
        def initialize(self, app):
            self.state = app.state
            self.subs = app.subs
            self.sources = app.sources
            self.port = app.port
            self.env_path = app.env_path
            self.login_enabled = app.login_enabled
            self.app = app

        def post(self):
            """Either write a message to the socket, or query what's there"""
            # TODO formalize failure reasons
            args = tornado.escape.json_decode(
                tornado.escape.to_basestring(self.request.body)
            )
            msg_type = args.get("message_type")
            sid = args.get("sid")

            if BaseWrapper == VisSocketWrapper and sid is None:
                new_sub = VisSocketWrapper()
                new_sub.initialize(self.app)
                self.write(json.dumps({"success": True, "sid": new_sub.sid}))
                return

            socket_wrap = (
                self.subs if BaseWrapper == SocketWrapper else self.sources
            ).get(sid)

            # ensure a wrapper still exists for this connection
            if socket_wrap is None:
                self.write(json.dumps({"success": False, "reason": "closed"}))
                return

            # handle the requests
            if msg_type == "query":
                messages = socket_wrap.get_messages()
                self.write(json.dumps({"success": True, "messages": messages}))
            elif msg_type == "send":
                msg = args.get("message")
                if msg is None:
                    self.write(json.dumps({"success": False, "reason": "no msg"}))
                else:
                    socket_wrap.on_message(msg)
                    self.write(json.dumps({"success": True}))
            else:
                self.write(json.dumps({"success": False, "reason": "invalid"}))

    if BaseWrapper == SocketWrapper:

        @check_auth
        def _get(self):
            """Create a new socket wrapper for this requester, return the id"""
            new_sub = SocketWrapper()
            new_sub.request = self.request
            new_sub.initialize(self.app)
            self.write(json.dumps({"success": True, "sid": new_sub.sid}))

        WrappedSocketWrap.get = _get

    return WrappedSocketWrap


SocketWrap = WrapSocketWrapper(SocketWrapper)
VisSocketWrap = WrapSocketWrapper(VisSocketWrapper)
