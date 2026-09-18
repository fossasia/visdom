#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The server's websocket heartbeat.

A client that disappears without a close frame -- a killed process, a laptop
lid, a dropped route -- used to stay in ``sources`` or ``subs`` until TCP gave
up, and the server kept writing events to it. The server now pings every
websocket and closes one that misses the pong.

The silent client is a raw TCP connection that completes the upgrade and then
ignores the ping. tornado answers pings on its own, so a ``websocket_connect``
client cannot play that part; it plays the healthy one instead.
"""

import asyncio
import base64
import contextlib
import json
import os
import time

import pytest
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

from visdom.server.defaults import WEBSOCKET_PING_INTERVAL

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration

FAST_PING_INTERVAL = 0.1
CLOSE_OPCODE = 0x8


def test_the_application_pings_its_websockets(app):
    assert app.settings["websocket_ping_interval"] == WEBSOCKET_PING_INTERVAL


async def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting on the server"
        await asyncio.sleep(0.01)


async def read_frame(reader):
    """One unmasked server frame, as ``(opcode, payload)``."""
    head = await reader.readexactly(2)
    length = head[1] & 0x7F
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    return head[0] & 0x0F, await reader.readexactly(length)


class TestWebsocketHeartbeat(VisdomHTTPTestCase):
    def get_app(self):
        app = super().get_app()
        app.settings["websocket_ping_interval"] = FAST_PING_INTERVAL
        return app

    @gen_test
    async def test_a_client_that_stops_answering_pings_is_dropped(self):
        port = self.get_http_port()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            writer.write(
                (
                    "GET /vis_socket HTTP/1.1\r\n"
                    "Host: 127.0.0.1:%d\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    "Sec-WebSocket-Key: %s\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n" % (port, key)
                ).encode()
            )
            await writer.drain()
            response = await reader.readuntil(b"\r\n\r\n")
            assert response.startswith(b"HTTP/1.1 101")
            await wait_for(lambda: self._app.sources)

            # The alive frame and the pings go unanswered until the server
            # gives up and says why.
            while True:
                opcode, payload = await asyncio.wait_for(read_frame(reader), 5)
                if opcode == CLOSE_OPCODE:
                    break
            assert b"ping timed out" in payload
        finally:
            writer.close()
            # Awaited, so the connection is gone before the assertion below
            # rather than being closed somewhere in the loop's next few turns.
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

        await wait_for(lambda: not self._app.sources)

    @gen_test
    async def test_a_client_that_answers_pings_stays_registered(self):
        connection = await websocket_connect(
            "ws://127.0.0.1:%d/vis_socket" % self.get_http_port()
        )
        try:
            alive = json.loads(await connection.read_message())
            assert alive["command"] == "alive"

            await asyncio.sleep(FAST_PING_INTERVAL * 8)

            assert len(self._app.sources) == 1
            assert connection.close_code is None
        finally:
            connection.close()
            await wait_for(lambda: not self._app.sources)
