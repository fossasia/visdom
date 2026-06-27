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
import hashlib
from collections import deque
from enum import Enum

import tornado.ioloop
import tornado.escape
from visdom.server.handlers.base_handlers import BaseWebSocketHandler, BaseHandler
from visdom.utils.shared_utils import get_rand_id, NanSafeEncoder
from visdom.utils.server_utils import (
    check_auth,
    broadcast_envs,
    serialize_env,
    serialize_all,
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
                env = self.state.get(msg["eid"])
                if env is None:
                    return
                p_data = env["jsons"].pop(msg["data"], None)
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
                prev_eid = escape_eid(msg["prev_eid"]) if msg.get("prev_eid") else None
                if prev_eid not in self.state:
                    return
                self.state[msg["eid"]] = copy.deepcopy(self.state[prev_eid])
                self.state[msg["eid"]]["reload"] = msg["data"]
                self.eid = msg["eid"]
                serialize_env(self.state, [self.eid], env_path=self.env_path)

        elif cmd == "save_all":
            tornado.ioloop.IOLoop.current().run_in_executor(
                None, serialize_all, self.state, self.env_path
            )

        elif cmd == "delete_env":
            if "eid" in msg:
                eid = escape_eid(msg["eid"])
                if eid == "main":
                    return
                logging.info(f"closing environment {eid}")
                self.state.pop(eid, None)
                if self.env_path is not None:
                    p = os.path.join(self.env_path, "{0}.json".format(eid))
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except FileNotFoundError:
                            pass
                        except OSError as e:
                            logging.error(f"Failed to delete {p}: {e}")
                    else:
                        hashed_id = hashlib.sha256(eid.encode("utf-8")).hexdigest()
                        p_hashed = os.path.join(
                            self.env_path, "hash_{0}.json".format(hashed_id)
                        )
                        if os.path.exists(p_hashed):
                            try:
                                os.remove(p_hashed)
                            except FileNotFoundError:
                                pass
                            except OSError as e:
                                logging.error(f"Failed to delete {p_hashed}: {e}")
                broadcast_envs(self)

        elif cmd == "save_layouts":
            if "data" in msg:
                self.app.layouts = msg.get("data")
                self.app.save_layouts()
                self.broadcast_layouts()

        elif cmd == "forward_to_vis":
            packet = msg.get("data")
            if not isinstance(packet, dict):
                logging.warning(
                    f"forward_to_vis: expected dict payload, got {type(packet).__name__!r}, dropping event"
                )
                return
            eid = packet.get("eid")
            target = packet.get("target")
            if eid is None or target is None:
                logging.warning(
                    f"forward_to_vis: malformed packet (eid={eid!r},"
                    f" target={target!r}), dropping event"
                )
                return
            environment = self.state.get(eid)
            if environment is None:
                logging.warning(
                    f"forward_to_vis: env {eid!r} not found, dropping event"
                )
                return
            if packet.get("pane_data") is not False:
                pane = environment["jsons"].get(target)
                if pane is None:
                    logging.warning(
                        f"forward_to_vis: pane {target!r} not found"
                        f" in env {eid!r}, dropping event"
                    )
                    return
                packet["pane_data"] = pane
            send_to_sources(self, msg.get("data"))

        elif cmd == "layout_item_update":
            eid = msg.get("eid")
            win = msg.get("win")
            if eid is None or win is None or eid not in self.state:
                logging.warning(
                    f"layout_item_update: env {eid!r} or win {win!r}"
                    f" not found, dropping event"
                )
                return
            self.state[eid]["reload"][win] = msg.get("data")

        elif cmd == "pop_embeddings_pane":
            packet = msg.get("data")
            if not isinstance(packet, dict):
                logging.warning(
                    f"pop_embeddings_pane: expected dict payload,"
                    f" got {type(packet).__name__!r}, dropping event"
                )
                return
            eid = packet.get("eid")
            win = packet.get("target")
            if eid is None or win is None:
                logging.warning(
                    f"pop_embeddings_pane: malformed packet"
                    f" (eid={eid!r}, target={win!r}), dropping event"
                )
                return
            env = self.state.get(eid)
            if env is None:
                logging.warning(
                    f"pop_embeddings_pane: env {eid!r} not found, dropping event"
                )
                return
            if win not in env["jsons"]:
                logging.warning(
                    f"pop_embeddings_pane: pane {win!r} not found"
                    f" in env {eid!r}, dropping event"
                )
                return
            p = env["jsons"][win]
            p["content"]["selected"] = None
            p["content"]["data"] = p["old_content"].pop()
            if len(p["old_content"]) == 0:
                p["content"]["has_previous"] = False
            p["contentID"] = get_rand_id()
            # Attach eid so the frontend can filter stale messages after env switch.
            broadcast_msg = dict(p)
            broadcast_msg["eid"] = eid
            broadcast(self, json.dumps(broadcast_msg, cls=NanSafeEncoder), eid)


class AnySocketWrapper(AnySocketHandlerOrWrapper):
    def __init__(self, *args, **kwargs):
        self.polling = True
        super().__init__(*args, **kwargs)

    def initialize(self, app):
        super().initialize(app)

        self.messages = deque()
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
            message = self.messages.popleft()
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
        self.write_message(
            json.dumps({"command": "alive", "data": "vis_alive"}, cls=NanSafeEncoder)
        )

    def on_close(self):
        if self in list(self.sources.values()):
            self.sources.pop(self.sid, None)

    def on_message(self, message):
        msg = tornado.escape.json_decode(tornado.escape.to_basestring(message))
        cmd = msg.get("cmd")

        if cmd == "echo":
            logging.info(f"from visdom client: {message}")
            for sub in self.sources.values():
                sub.write_message(json.dumps(msg, cls=NanSafeEncoder))
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
                {
                    "command": "register",
                    "data": self.sid,
                    "readonly": self.readonly,
                    "envList": sorted(list(self.state.keys())),
                },
                cls=NanSafeEncoder,
            )
        )
        self.broadcast_layouts([self])
        broadcast_envs(self, [self])

    def broadcast_layouts(self, target_subs=None):
        if target_subs is None:
            target_subs = self.subs.values()
        for sub in target_subs:
            sub.write_message(
                json.dumps(
                    {"command": "layout_update", "data": self.app.layouts},
                    cls=NanSafeEncoder,
                )
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


class SocketFailureReason(Enum):
    """Failure reason codes for the HTTP polling socket protocol."""

    CONNECTION_CLOSED = (
        "closed",
        "No active socket found for the given sid; "
        "it may have been closed or never existed",
    )
    MISSING_MESSAGE = (
        "no msg",
        "POST body must include a 'message' field when message_type is 'send'",
    )
    INVALID_MESSAGE_TYPE = (
        "invalid",
        "Unrecognized message_type; expected 'query' or 'send'",
    )

    def __new__(cls, value, detail=""):
        obj = object.__new__(cls)
        obj._value_ = value
        obj._detail = detail
        return obj

    @property
    def detail(self):
        return self._detail

    def to_failure_response(self, message=""):
        resp = {"success": False, "reason": self.value, "detail": self.detail}
        if message:
            resp["message"] = message
        return resp


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

            if socket_wrap is None:
                self.write(
                    json.dumps(
                        SocketFailureReason.CONNECTION_CLOSED.to_failure_response(
                            f"sid={sid!r}"
                        )
                    )
                )
                return

            if msg_type == "query":
                messages = socket_wrap.get_messages()
                self.write(json.dumps({"success": True, "messages": messages}))
            elif msg_type == "send":
                msg = args.get("message")
                if msg is None:
                    self.write(
                        json.dumps(
                            SocketFailureReason.MISSING_MESSAGE.to_failure_response()
                        )
                    )
                else:
                    socket_wrap.on_message(msg)
                    self.write(json.dumps({"success": True}))
            else:
                self.write(
                    json.dumps(
                        SocketFailureReason.INVALID_MESSAGE_TYPE.to_failure_response(
                            f"message_type={msg_type!r}"
                        )
                    )
                )

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
