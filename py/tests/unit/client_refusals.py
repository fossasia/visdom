#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""What a client says when the server turns a request down.

A hosted server refuses a wrong, revoked or read-only key, and a plan that is
out of storage. The response body has always gone back to the caller, where it
reads as a window id, so a script whose every plot was refused looked as if it
had worked. The client now warns. It still does not raise and still returns
the body, because a refused write has to look the way it does for ``requests``.
"""

import asyncio
import logging
import os
import threading

import pytest

import visdom
from visdom import Visdom, _refusal_reason
from visdom.async_client import _AsyncTransport, _BridgedVisdom

pytestmark = pytest.mark.unit

BAD_KEY = '{"detail":"Invalid or expired API key"}'
MESSAGE = "The visdom server refused this request (401): Invalid or expired API key"


class _Response:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _Session:
    def __init__(self, response):
        self.response = response

    def post(self, url, data=None, timeout=None):
        return self.response


def _client(status, body, raise_exceptions=None):
    client = Visdom.__new__(Visdom)
    client._session = _Session(_Response(status, body))
    client._session_lock = threading.Lock()
    client._pid = os.getpid()
    client._last_post_time = 0
    client.raise_exceptions = raise_exceptions
    return client


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize(
    "body, reason",
    [
        (BAD_KEY, "Invalid or expired API key"),
        ('{"error": "this server is read-only"}', "this server is read-only"),
        ("plain words from the server", "plain words from the server"),
        ("<html><body>403 Forbidden</body></html>", "no reason given"),
        ("", "no reason given"),
        (None, "no reason given"),
        (
            '{"detail": [{"msg": "not a string"}]}',
            '{"detail": [{"msg": "not a string"}]}',
        ),
    ],
)
def test_the_reason_is_read_out_of_whatever_the_server_sent(body, reason):
    assert _refusal_reason(body) == reason


@pytest.mark.parametrize("status", visdom.REFUSED_STATUSES)
def test_a_refusal_is_warned_about_and_the_body_still_comes_back(status, caplog):
    client = _client(status, BAD_KEY)

    with caplog.at_level(logging.WARNING, logger="visdom"):
        returned = client._handle_post("http://x/events", "{}")

    assert returned == BAD_KEY
    assert _warnings(caplog) == [MESSAGE.replace("401", str(status))]


def test_it_never_raises_even_when_exceptions_were_asked_for(caplog):
    client = _client(403, BAD_KEY, raise_exceptions=True)

    with caplog.at_level(logging.WARNING, logger="visdom"):
        assert client._handle_post("http://x/events", "{}") == BAD_KEY

    assert len(_warnings(caplog)) == 1


def test_the_same_reason_is_only_said_once(caplog):
    client = _client(401, BAD_KEY)

    with caplog.at_level(logging.WARNING, logger="visdom"):
        for _ in range(50):
            client._handle_post("http://x/events", "{}")

    assert _warnings(caplog) == [MESSAGE]


def test_a_different_reason_is_said_as_well(caplog):
    client = _client(401, BAD_KEY)

    with caplog.at_level(logging.WARNING, logger="visdom"):
        client._handle_post("http://x/events", "{}")
        client._session.response = _Response(402, '{"detail":"out of storage"}')
        client._handle_post("http://x/events", "{}")

    assert len(_warnings(caplog)) == 2
    assert "out of storage" in _warnings(caplog)[1]


@pytest.mark.parametrize("status", [200, 400, 404, 500])
def test_other_answers_are_left_alone(status, caplog):
    client = _client(status, "window_abc")

    with caplog.at_level(logging.WARNING, logger="visdom"):
        assert client._handle_post("http://x/events", "{}") == "window_abc"

    assert _warnings(caplog) == []


class _AsyncResponse:
    def __init__(self, code, body):
        self.code = code
        self.body = body


def _transport(code, body):
    transport = _AsyncTransport("https://visdom.dev", 443)

    async def fetch(request):
        return _AsyncResponse(code, body)

    transport._fetch = fetch
    return transport


def test_the_asyncio_transport_reports_a_refusal_and_returns_the_body():
    transport = _transport(403, BAD_KEY.encode())
    seen = []
    transport.on_refusal = lambda status, body: seen.append((status, body))

    returned = asyncio.run(transport.post("https://visdom.dev/vis/events", "{}"))

    assert returned == BAD_KEY
    assert seen == [(403, BAD_KEY)]


def test_the_asyncio_transport_with_nobody_listening_just_returns():
    transport = _transport(403, BAD_KEY.encode())

    assert asyncio.run(transport.post("https://visdom.dev/vis/events", "{}")) == BAD_KEY


def test_the_asyncio_client_listens_to_its_transport(caplog):
    inner = _BridgedVisdom.__new__(_BridgedVisdom)
    inner._transport = _transport(401, BAD_KEY.encode())
    inner.raise_exceptions = True

    transport = inner.transport
    with caplog.at_level(logging.WARNING, logger="visdom"):
        asyncio.run(transport.post("https://visdom.dev/vis/events", "{}"))

    assert _warnings(caplog) == [MESSAGE]
