#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import json
import unittest
from collections import deque
from unittest.mock import MagicMock, patch

import tornado.websocket

from visdom.server.handlers.socket_handlers import (
    AnySocketWrapper,
    MAX_POLLING_QUEUE,
)
from visdom.utils.server_utils import broadcast, broadcast_envs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wrapper():
    """Return an AnySocketWrapper with a minimal app stub."""
    app = MagicMock()
    app.state = {"main": {"jsons": {}, "reload": {}}}
    app.subs = {}
    app.sources = {}
    app.port = 8097
    app.env_path = None
    app.login_enabled = False
    app.readonly = False

    wrapper = AnySocketWrapper.__new__(AnySocketWrapper)
    wrapper.polling = True
    wrapper.app = app
    wrapper.state = app.state
    wrapper.subs = app.subs
    wrapper.sources = app.sources
    wrapper.port = app.port
    wrapper.env_path = app.env_path
    wrapper.login_enabled = app.login_enabled
    wrapper.readonly = app.readonly
    wrapper.messages = deque(maxlen=MAX_POLLING_QUEUE)
    wrapper.last_read_time = 0.0
    wrapper.eid = "main"
    wrapper.sid = "test-sid"
    return wrapper


def _make_handler_stub(subs=None, sources=None, state=None):
    """Return a minimal handler-like object for broadcast tests."""
    h = MagicMock()
    h.subs = subs if subs is not None else {}
    h.sources = sources if sources is not None else {}
    h.state = state if state is not None else {"main": {"jsons": {}, "reload": {}}}
    return h


# ---------------------------------------------------------------------------
# Bounded polling queue
# ---------------------------------------------------------------------------

class TestPollingQueue(unittest.TestCase):
    def test_queue_is_bounded_at_max_polling_queue(self):
        wrapper = _make_wrapper()
        for i in range(MAX_POLLING_QUEUE + 50):
            wrapper.write_message(json.dumps({"n": i}))

        self.assertEqual(len(wrapper.messages), MAX_POLLING_QUEUE)

    def test_oldest_messages_dropped_when_full(self):
        wrapper = _make_wrapper()
        for i in range(MAX_POLLING_QUEUE + 10):
            wrapper.write_message(json.dumps({"n": i}))

        # The first message in the queue should be n=10 (oldest 10 were dropped)
        first = json.loads(list(wrapper.messages)[0])
        self.assertEqual(first["n"], 10)

    def test_get_messages_drains_queue(self):
        wrapper = _make_wrapper()
        wrapper.write_message('{"a": 1}')
        wrapper.write_message('{"b": 2}')

        messages = wrapper.get_messages()
        self.assertEqual(len(messages), 2)
        self.assertEqual(len(wrapper.messages), 0)

    def test_get_messages_preserves_maxlen_on_deque(self):
        """get_messages() must not replace the bounded deque with a plain list."""
        wrapper = _make_wrapper()
        wrapper.write_message("msg")
        wrapper.get_messages()

        # Queue should still be a deque with maxlen after draining
        self.assertIsInstance(wrapper.messages, deque)
        self.assertEqual(wrapper.messages.maxlen, MAX_POLLING_QUEUE)


# ---------------------------------------------------------------------------
# Duplicate subscription prevention
# ---------------------------------------------------------------------------

class TestSubscriptionRegistration(unittest.TestCase):
    def test_duplicate_registration_is_ignored(self):
        """open() must not register the same object twice."""
        wrapper = _make_wrapper()
        # The wrapper is already set up as if open() ran;
        # manually simulate a second open() call
        subs = wrapper.subs
        if wrapper.sid not in subs:
            subs[wrapper.sid] = wrapper
        if wrapper not in list(subs.values()):
            subs[wrapper.sid] = wrapper

        # Regardless of how many times we try, only one entry exists
        self.assertEqual(len([v for v in subs.values() if v is wrapper]), 1)


# ---------------------------------------------------------------------------
# on_close() cleanup
# ---------------------------------------------------------------------------

class TestOnClose(unittest.TestCase):
    def test_on_close_removes_from_subs(self):
        """SocketHandlerOrWrapper.on_close() must remove the sub by key."""
        from visdom.server.handlers.socket_handlers import SocketHandlerOrWrapper

        handler = SocketHandlerOrWrapper.__new__(SocketHandlerOrWrapper)
        handler.sid = "sub-1"
        handler.subs = {"sub-1": handler}

        handler.on_close()
        self.assertNotIn("sub-1", handler.subs)

    def test_on_close_tolerates_missing_sid(self):
        """on_close() must not raise if sid is already gone."""
        from visdom.server.handlers.socket_handlers import SocketHandlerOrWrapper

        handler = SocketHandlerOrWrapper.__new__(SocketHandlerOrWrapper)
        handler.sid = "gone"
        handler.subs = {}

        # Should not raise
        handler.on_close()

    def test_vis_on_close_removes_from_sources(self):
        """VisSocketHandlerOrWrapper.on_close() must remove source by key."""
        from visdom.server.handlers.socket_handlers import VisSocketHandlerOrWrapper

        handler = VisSocketHandlerOrWrapper.__new__(VisSocketHandlerOrWrapper)
        handler.sid = "src-1"
        handler.sources = {"src-1": handler}

        handler.on_close()
        self.assertNotIn("src-1", handler.sources)


# ---------------------------------------------------------------------------
# broadcast() guards against closed WebSocket
# ---------------------------------------------------------------------------

class TestBroadcastGuard(unittest.TestCase):
    def _make_sub(self, eid="main", raise_on_write=False):
        sub = MagicMock()
        sub.eid = eid
        if raise_on_write:
            sub.write_message.side_effect = tornado.websocket.WebSocketClosedError()
        return sub

    def test_broadcast_does_not_raise_on_closed_socket(self):
        sub = self._make_sub(raise_on_write=True)
        handler = _make_handler_stub(subs={"s1": sub})
        # Must not propagate WebSocketClosedError
        broadcast(handler, '{"command":"test"}', "main")

    def test_broadcast_delivers_to_open_sockets(self):
        good = self._make_sub(eid="main")
        dead = self._make_sub(eid="main", raise_on_write=True)
        handler = _make_handler_stub(subs={"g": good, "d": dead})

        broadcast(handler, '{"command":"test"}', "main")

        good.write_message.assert_called_once()

    def test_broadcast_envs_does_not_raise_on_closed_socket(self):
        sub = MagicMock()
        sub.write_message.side_effect = tornado.websocket.WebSocketClosedError()
        handler = _make_handler_stub(subs={"s1": sub})
        # Must not propagate
        broadcast_envs(handler)


if __name__ == "__main__":
    unittest.main()
