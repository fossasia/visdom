#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import socket
import threading
import time

import pytest
import requests

import visdom
from visdom import Visdom

pytestmark = pytest.mark.unit


def _client(port):
    client = Visdom.__new__(Visdom)
    client._session_lock = threading.Lock()
    client._session = None
    client._pid = None
    client.proxies = None
    client.ssl_verify = True
    client.api_key = None
    client.workspace = None
    client.server = "http://127.0.0.1"
    client.port = port
    client.base_url = ""
    client.username = "user"
    client.password = "pass"
    return client


@pytest.fixture
def silent_server():
    """A server that accepts connections and never answers them."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    accepted = []
    stop = threading.Event()

    def accept():
        server.settimeout(0.1)
        while not stop.is_set():
            try:
                accepted.append(server.accept()[0])
            except OSError:
                pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    for conn in accepted:
        conn.close()
    server.close()


def test_the_login_has_a_read_timeout():
    connect, read = visdom.LOGIN_TIMEOUT

    assert connect is not None
    assert read is not None


def test_a_login_the_server_never_answers_times_out(silent_server, monkeypatch):
    monkeypatch.setattr(visdom, "LOGIN_TIMEOUT", (1, 1))
    client = _client(silent_server)

    started = time.monotonic()
    with pytest.raises(requests.exceptions.Timeout):
        client.session
    assert time.monotonic() - started < 10
