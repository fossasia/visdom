#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import json
import time

import pytest
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

from visdom.utils.server_utils import broadcast

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


async def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting on the server"
        await asyncio.sleep(0.01)


class TestClosedSocketWrites(VisdomHTTPTestCase):
    async def open_tab(self):
        before = set(self._app.subs)
        connection = await websocket_connect(
            "ws://127.0.0.1:%d/socket" % self.get_http_port()
        )
        await wait_for(lambda: set(self._app.subs) - before)
        (sid,) = set(self._app.subs) - before
        for _ in range(3):
            await connection.read_message()
        return connection, self._app.subs[sid]

    @gen_test
    async def test_a_closed_tab_does_not_stop_the_broadcast(self):
        closed, closed_handler = await self.open_tab()
        healthy, _ = await self.open_tab()
        try:
            closed_handler.ws_connection.stream.close()
            assert closed_handler in self._app.subs.values()

            broadcast(closed_handler, json.dumps({"command": "probe"}), "main")

            message = await asyncio.wait_for(healthy.read_message(), 5)
            assert json.loads(message)["command"] == "probe"
        finally:
            closed.close()
            healthy.close()
            await wait_for(lambda: not self._app.subs)

    @gen_test
    async def test_writing_to_a_closed_tab_returns_quietly(self):
        connection, handler = await self.open_tab()
        try:
            handler.ws_connection.stream.close()

            assert handler.write_message("{}") is None
        finally:
            connection.close()
            await wait_for(lambda: not self._app.subs)
