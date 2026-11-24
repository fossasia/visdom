#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the webhook request itself, with no socket involved.

The delivery against a real receiver is an integration test
(``experiment_alerts_webhooks.py``). What is asserted here is which answers
count as delivered, which are reported, and that none of them ever raises.
Coroutine bodies run under ``tornado.testing.AsyncTestCase`` + ``@gen_test``,
the way the other async unit tests here do; there is no pytest-asyncio.
"""

import asyncio
import json

import pytest
import tornado.testing
from tornado.testing import gen_test

from visdom.experiments.alerts import AlertEvent, build_alert
from visdom.server import webhooks
from visdom.server.webhooks import WebhookPolicy

pytestmark = pytest.mark.unit

URL = "https://hooks.example.com/t"


def allowing():
    return WebhookPolicy(enabled=True, hosts="hooks.example.com")


def firing(**kwargs):
    """A fired webhook rule, as ``_dispatch_alerts`` would have it."""
    kwargs.setdefault("action", "webhook")
    kwargs.setdefault("url", URL)
    alert = build_alert("loss", "> 2.0", **kwargs)
    alert.fire_count, alert.last_fired_at = 1, 1700000000.0
    return AlertEvent(alert=alert, value=2.5, step=4)


class Answering:
    """A client that answers with one code, and records what it was asked."""

    def __init__(self, code=200, raises=None):
        self.code = code
        self.raises = raises
        self.calls = []

    async def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.raises is not None:
            raise self.raises
        return type("Response", (), {"code": self.code})()


class TestPayload:
    def test_the_body_takes_the_firing_apart(self):
        body = webhooks.payload(firing(), "run-7", "run-7: loss is 2.5, > 2")

        assert body["env"] == "run-7"
        assert body["metric"] == "loss"
        assert body["condition"] == ">"
        assert body["threshold"] == 2.0
        assert body["value"] == 2.5
        assert body["step"] == 4
        assert body["fire_count"] == 1
        assert body["fired_at"] == 1700000000.0

    def test_the_sentence_is_carried_as_well_as_the_fields(self):
        body = webhooks.payload(firing(), "run-7", "the loss diverged")
        assert body["message"] == "the loss diverged"

    def test_the_body_is_json_a_standard_parser_can_read(self):
        # A receiver using a standard parser chokes on a NaN.
        event = AlertEvent(alert=firing().alert, value=None, step=None)
        raw = json.dumps(webhooks.payload(event, "main", "diverged"))
        assert json.loads(raw)["value"] is None


class TestPost(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_a_2xx_is_a_delivery(self):
        for code in (200, 201, 204):
            assert await webhooks.post(URL, {}, client=Answering(code)) is None

    @gen_test
    async def test_the_request_is_fixed_and_the_redirect_is_not_followed(self):
        client = Answering()
        await webhooks.post(URL, {"a": 1}, client=client)

        url, kwargs = client.calls[0]
        assert url == URL
        assert kwargs["method"] == "POST"
        assert kwargs["follow_redirects"] is False
        assert kwargs["raise_error"] is False
        assert kwargs["headers"] == {"Content-Type": "application/json"}
        assert json.loads(kwargs["body"]) == {"a": 1}
        assert kwargs["request_timeout"] == webhooks.REQUEST_TIMEOUT
        assert kwargs["connect_timeout"] == webhooks.CONNECT_TIMEOUT

    @gen_test
    async def test_a_redirect_is_reported_as_a_delivery_that_did_not_happen(self):
        refusal = await webhooks.post(URL, {}, client=Answering(302))
        assert "redirect" in refusal

    @gen_test
    async def test_an_error_response_is_reported(self):
        assert "500" in await webhooks.post(URL, {}, client=Answering(500))
        assert "404" in await webhooks.post(URL, {}, client=Answering(404))
        # Tornado's code for a connection that never got anywhere.
        assert "599" in await webhooks.post(URL, {}, client=Answering(599))

    @gen_test
    async def test_a_client_that_raises_is_reported_rather_than_raised(self):
        refusal = await webhooks.post(
            URL, {}, client=Answering(raises=OSError("no route to host"))
        )
        assert "could not be reached" in refusal
        assert "no route to host" in refusal


class TestDispatch(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_a_delivery_is_started_and_registered(self):
        pending = set()
        client = Answering()

        task = webhooks.dispatch(
            allowing(), firing(), "main", "fired", pending, client=client
        )

        assert task in pending
        await webhooks.drain(pending)
        assert client.calls
        # Discarded when it finishes, so the set is not a leak.
        assert pending == set()

    @gen_test
    async def test_the_policy_is_asked_again_here(self):
        # A rule outlives the flags it was set under.
        pending = set()
        client = Answering()

        assert (
            webhooks.dispatch(
                WebhookPolicy(), firing(), "main", "fired", pending, client=client
            )
            is None
        )
        assert pending == set()
        assert client.calls == []

    @gen_test
    async def test_a_host_outside_the_allowlist_is_not_posted_to(self):
        pending = set()
        client = Answering()
        event = firing(url="https://attacker.example/t")

        assert (
            webhooks.dispatch(
                allowing(), event, "main", "fired", pending, client=client
            )
            is None
        )
        assert client.calls == []

    @gen_test
    async def test_a_failed_delivery_does_not_surface_as_an_exception(self):
        pending = set()
        webhooks.dispatch(
            allowing(),
            firing(),
            "main",
            "fired",
            pending,
            client=Answering(raises=OSError("down")),
        )

        await webhooks.drain(pending)
        assert pending == set()


class TestDrain(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_draining_nothing_returns_at_once(self):
        await webhooks.drain(set())

    @gen_test
    async def test_a_bounded_drain_gives_up_rather_than_holding_a_shutdown_open(self):
        hanging = asyncio.ensure_future(asyncio.Event().wait())
        pending = {hanging}
        try:
            await webhooks.drain(pending, timeout=0.05)
            assert pending == {hanging}
        finally:
            hanging.cancel()
