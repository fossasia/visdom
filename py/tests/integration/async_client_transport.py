#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""End-to-end tests for ``AsyncVisdom`` against a real Application.

These drive the actual transport -- ``AsyncHTTPClient`` over a loopback socket
-- so the wire format, the status-code semantics and the concurrency claim are
tested for real rather than against a stub. ``VisdomHTTPTestCase`` gives the
in-process app on an ephemeral port, and ``@gen_test`` runs the coroutine
bodies on that same IOLoop, which is what makes this a true test of the bridge:
one loop serving the requests that the worker threads are blocked on.
"""

import asyncio
import json
import time

import pytest
from tornado.testing import gen_test

from visdom.async_client import AsyncVisdom

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


async def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting for the backchannel"
        await asyncio.sleep(0.01)


class AsyncClientTestCase(VisdomHTTPTestCase):
    """Adds a client factory bound to this test's server."""

    async def connect(self, **kwargs):
        kwargs.setdefault("raise_exceptions", True)
        client = await AsyncVisdom.create(
            server="http://localhost", port=self.get_http_port(), **kwargs
        )
        self.addCleanup(lambda: client.client.transport.close())
        return client


class TestAsyncVisdomAgainstServer(AsyncClientTestCase):
    @gen_test
    async def test_create_registers_the_env(self):
        await self.connect(env="demo")
        assert "demo" in self._app.state

    @gen_test
    async def test_text_creates_a_window_on_the_server(self):
        client = await self.connect()
        win = await client.text("hello", win="w1")
        assert win == "w1"
        assert self.panes("main")["w1"]["content"] == "hello"

    @gen_test
    async def test_line_round_trips_through_the_real_transport(self):
        client = await self.connect()
        win = await client.line(Y=[1.0, 2.0, 3.0], win="plot")
        pane = self.panes("main")[win]
        assert pane["type"] == "plot"
        assert pane["content"]["data"][0]["y"] == [1.0, 2.0, 3.0]

    @gen_test
    async def test_win_exists_reads_the_response_body(self):
        client = await self.connect()
        await client.text("hello", win="w1")
        assert await client.win_exists("w1") is True
        assert await client.win_exists("nope") is False

    @gen_test
    async def test_close_removes_the_window(self):
        client = await self.connect()
        await client.text("hello", win="w1")
        await client.close(win="w1")
        assert "w1" not in self.panes("main")

    @gen_test
    async def test_get_env_list_parses_the_json_response(self):
        client = await self.connect(env="listed")
        assert "listed" in await client.get_env_list()

    @gen_test
    async def test_update_appends_to_an_existing_window(self):
        client = await self.connect()
        win = await client.line(Y=[1.0, 2.0], X=[1.0, 2.0], win="appended")
        await client.line(Y=[3.0], X=[3.0], win=win, update="append")
        assert self.panes("main")[win]["content"]["data"][0]["y"] == [1.0, 2.0, 3.0]

    @gen_test
    async def test_concurrent_plots_all_land(self):
        """Five plots in flight at once on one loop -- the point of the bridge.

        The synchronous client would serialize these; here the loop is serving
        every request while five worker threads wait on their POSTs.
        """
        client = await self.connect()
        wins = await asyncio.gather(
            *[client.text("m%d" % i, win="w%d" % i) for i in range(5)]
        )
        assert sorted(wins) == ["w0", "w1", "w2", "w3", "w4"]
        panes = self.panes("main")
        for i in range(5):
            assert panes["w%d" % i]["content"] == "m%d" % i

    @gen_test
    async def test_more_concurrent_plots_than_workers_all_land(self):
        """Regression guard, against the real transport this time.

        A gather wider than the client's worker pool used to deadlock: the
        proxies ran on asyncio's default executor, which is also where the loop
        resolves hostnames, so a full pool left no thread to resolve the very
        connections the pool was waiting on. Every request then sat until its
        20s connect timeout. Twenty-four calls through a pool of four is a
        batch the old code could not finish at all.
        """
        client = await self.connect(max_concurrency=4)
        wins = await asyncio.gather(
            *[client.text("m%d" % i, win="many%d" % i) for i in range(24)]
        )
        assert len(set(wins)) == 24
        panes = self.panes("main")
        assert all("many%d" % i in panes for i in range(24))

    @gen_test
    async def test_the_loop_serves_requests_while_a_plot_is_blocked(self):
        """A plain ``self.fetch`` completes while a proxied call is in flight.

        This is the guarantee the synchronous client cannot make: its POST owns
        the calling thread outright.
        """
        client = await self.connect()
        plot = asyncio.ensure_future(client.text("slow", win="slow"))
        response = await self.http_client.fetch(
            self.get_url("/env_state"), method="POST", body="{}"
        )
        assert response.code == 200
        await plot

    @gen_test
    async def test_save_persists_the_env_to_disk(self):
        client = await self.connect(env="saved")
        await client.text("hello", win="w1", env="saved")
        await client.save(["saved"])
        with open("%s/saved.json" % self.env_path) as handle:
            assert "w1" in json.load(handle)["jsons"]


class TestAsyncVisdomBackchannel(AsyncClientTestCase):
    """The real handshake, over a real socket, against the real routes."""

    async def connect_with_events(self, **kwargs):
        client = await self.connect(**kwargs)
        self.addCleanup(client.client.close_backchannel)
        return client

    async def push(self, message):
        """What ``forward_to_vis`` does when the browser reports an event."""
        await wait_for(lambda: self._app.sources)
        for source in list(self._app.sources.values()):
            source.write_message(json.dumps(message))

    @gen_test
    async def test_the_websocket_handshake_completes(self):
        client = await self.connect_with_events(use_incoming_socket=True)

        assert client.socket_alive is True
        assert len(self._app.sources) == 1
        await client.shutdown()

    @gen_test
    async def test_an_event_reaches_a_handler(self):
        client = await self.connect_with_events(use_incoming_socket=True)
        seen = []
        client.register_event_handler(seen.append, "w1")

        await client.text("hello", win="w1")
        await self.push({"target": "w1", "eid": "main", "event_type": "Click"})
        await wait_for(lambda: seen)

        assert seen[0]["event_type"] == "Click"
        await client.shutdown()

    @gen_test
    async def test_polling_delivers_the_same_events(self):
        """The fallback for deployments that cannot hold a websocket open."""
        client = await self.connect_with_events(use_polling=True)
        seen = []
        client.register_event_handler(seen.append, "w1")

        await self.push({"target": "w1", "eid": "main", "event_type": "Click"})
        await wait_for(lambda: seen)

        assert client.socket_alive is True
        assert seen[0]["event_type"] == "Click"
        await client.shutdown()

    @gen_test
    async def test_shutdown_drops_the_connection_server_side(self):
        client = await self.connect_with_events(use_incoming_socket=True)
        await client.shutdown()
        await wait_for(lambda: not self._app.sources)

        assert self._app.sources == {}


class TestAsyncVisdomAgainstReadonlyServer(AsyncClientTestCase):
    """A refused write has to look exactly like it does for ``requests``."""

    app_kwargs = {"readonly": True}

    @gen_test
    async def test_error_status_returns_the_body_instead_of_raising(self):
        """``requests`` does not raise on 4xx, so neither may the transport:
        ``_send`` is written to hand the response text back to the caller."""
        client = await self.connect()
        result = await client.text("hello", win="w1")
        assert "read" in result.lower()
        assert "w1" not in self._app.state.get("main", {}).get("jsons", {})
