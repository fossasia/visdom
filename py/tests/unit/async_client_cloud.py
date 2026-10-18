#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The asyncio client against a hosted deployment.

A hosted deployment reads an API key and a workspace from two request headers.
The blocking client puts them on its ``requests`` session; the asyncio client
builds every request itself, so it has to add them, on the POSTs and on the
socket handshake both. Without them every call is refused.
"""

import pytest

from visdom.async_client import _AsyncTransport, _BridgedVisdom

pytestmark = pytest.mark.unit

KEY_HEADERS = {"X-API-KEY": "visdom_live_abc", "X-Visdom-Workspace": "lab"}


def keyed():
    return _AsyncTransport(
        "https://visdom.dev", 443, api_key="visdom_live_abc", workspace="lab"
    )


def test_a_post_carries_the_key_and_the_workspace():
    request = keyed()._request("https://visdom.dev/vis/events", "{}")

    for name, value in KEY_HEADERS.items():
        assert request.headers[name] == value


def test_the_socket_handshake_carries_them_too():
    request = keyed().websocket_request()

    for name, value in KEY_HEADERS.items():
        assert request.headers[name] == value


def test_they_sit_alongside_a_login_cookie_and_extra_headers():
    transport = keyed()
    transport.cookie = "user_password=abc"

    request = transport._request(
        "https://visdom.dev/vis/events", "{}", {"Content-Type": "application/json"}
    )

    assert request.headers["Cookie"] == "user_password=abc"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["X-API-KEY"] == "visdom_live_abc"


def test_without_a_key_neither_header_is_sent():
    transport = _AsyncTransport("http://localhost", 8097)

    for request in (
        transport._request("http://localhost:8097/events", "{}"),
        transport.websocket_request(),
    ):
        assert "X-API-KEY" not in request.headers
        assert "X-Visdom-Workspace" not in request.headers


def test_the_client_hands_its_key_to_the_transport_it_builds():
    inner = _BridgedVisdom.__new__(_BridgedVisdom)
    inner._transport = None
    inner.server = "https://visdom.dev"
    inner.port = 443
    inner.base_url = "/vis"
    inner.username = None
    inner.ssl_verify = True
    inner._max_clients = 4
    inner.api_key = "visdom_live_abc"
    inner.workspace = "lab"

    transport = inner.transport

    assert transport.api_key == "visdom_live_abc"
    assert transport.workspace == "lab"
