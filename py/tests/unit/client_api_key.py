#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import base64
import hashlib
import logging
import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import websocket

from visdom import Visdom, _KeyedWebSocket
from visdom.async_client import _AsyncTransport

pytestmark = pytest.mark.unit


def _client(api_key=None, workspace=None):
    client = Visdom.__new__(Visdom)
    client._session_lock = threading.Lock()
    client._session = None
    client._pid = None
    client.proxies = None
    client.ssl_verify = True
    client.username = None
    client.api_key = api_key
    client.workspace = workspace
    return client


def test_the_session_carries_the_key_and_the_workspace():
    headers = _client("visdom_live_abc", "lab").session.headers

    assert headers["X-API-KEY"] == "visdom_live_abc"
    assert headers["X-Visdom-Workspace"] == "lab"


def test_without_a_key_neither_header_is_set():
    headers = _client().session.headers

    assert "X-API-KEY" not in headers
    assert "X-Visdom-Workspace" not in headers


def test_a_key_without_a_workspace_is_refused():
    with pytest.raises(AssertionError, match="workspace is required"):
        Visdom(api_key="visdom_live_abc", offline=True)


def test_a_key_and_a_workspace_are_kept_on_the_client(tmp_path):
    client = Visdom(
        api_key="visdom_live_abc",
        workspace="lab",
        offline=True,
        log_to_filename=str(tmp_path / "log"),
    )

    assert client.api_key == "visdom_live_abc"
    assert client.workspace == "lab"


def _redirect(client, from_url, to_url):
    original = requests.Request("POST", from_url).prepare()
    original.headers.update(client.session.headers)
    following = original.copy()
    following.url = to_url
    client.session.rebuild_auth(following, SimpleNamespace(request=original))
    return following.headers


def test_a_redirect_to_another_host_drops_the_key():
    headers = _redirect(
        _client("visdom_live_abc", "lab"),
        "https://visdom.example/events",
        "https://elsewhere.example/events",
    )

    assert "X-API-KEY" not in headers
    assert "X-Visdom-Workspace" not in headers


def test_a_redirect_on_the_same_host_keeps_the_key():
    headers = _redirect(
        _client("visdom_live_abc", "lab"),
        "https://visdom.example/events",
        "https://visdom.example/vis/events",
    )

    assert headers["X-API-KEY"] == "visdom_live_abc"
    assert headers["X-Visdom-Workspace"] == "lab"


def test_a_redirect_from_https_to_http_on_the_same_host_drops_the_key():
    headers = _redirect(
        _client("visdom_live_abc", "lab"),
        "https://visdom.example/events",
        "http://visdom.example/events",
    )

    assert "X-API-KEY" not in headers
    assert "X-Visdom-Workspace" not in headers


def test_the_clear_text_warning_leaves_out_credentials_in_the_url(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="visdom"):
        Visdom(
            server="http://someone:secret@visdom.example",
            api_key="visdom_live_abc",
            workspace="lab",
            offline=True,
            log_to_filename=str(tmp_path / "log"),
        )

    assert "unencrypted connection" in caplog.text
    assert "visdom.example" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize(
    "server, warned",
    [
        ("http://visdom.example", True),
        ("https://visdom.example", False),
        ("http://localhost", False),
        ("http://127.0.0.1", False),
    ],
)
def test_a_key_sent_in_the_clear_is_warned_about(tmp_path, caplog, server, warned):
    with caplog.at_level(logging.WARNING, logger="visdom"):
        Visdom(
            server=server,
            api_key="visdom_live_abc",
            workspace="lab",
            offline=True,
            log_to_filename=str(tmp_path / "log"),
        )

    assert ("unencrypted connection" in caplog.text) is warned


def test_the_async_client_does_not_follow_redirects_with_a_key():
    keyed = _AsyncTransport(
        "https://visdom.example", 443, api_key="visdom_live_abc", workspace="lab"
    )
    plain = _AsyncTransport("https://visdom.example", 443)

    assert (
        keyed._request("https://visdom.example:443/events", "{}").follow_redirects
        is False
    )
    assert (
        plain._request("https://visdom.example:443/events", "{}").follow_redirects
        is True
    )


class _FakeSocketServer:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with conn:
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    request += chunk
                text = request.decode("latin-1")
                self.requests.append(text)
                conn.sendall(self.reply(text))

    def close(self):
        self.listener.close()


def _upgrade(request):
    key = next(
        line.split(":", 1)[1].strip()
        for line in request.split("\r\n")
        if line.lower().startswith("sec-websocket-key:")
    )
    accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode()
    payload = b'{"command": "alive", "data": "vis_alive"}'
    return (
        (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n".format(accept)
        ).encode()
        + bytes([0x81, len(payload)])
        + payload
        + bytes([0x88, 0])
    )


def _socket_client(port):
    client = _client("visdom_live_abc", "lab")
    client.use_socket = True
    client.socket_alive = False
    client.socket_connection_achieved = False
    client.server = "http://127.0.0.1"
    client.server_base_name = "127.0.0.1"
    client.port = port
    client.base_url = ""
    client.http_proxy_host = None
    client.http_proxy_port = None
    return client


def test_a_socket_with_a_key_does_not_follow_a_redirect():
    elsewhere = _FakeSocketServer(_upgrade)
    redirecting = _FakeSocketServer(
        lambda request: (
            "HTTP/1.1 302 Found\r\nLocation: ws://127.0.0.1:{}/vis_socket\r\n"
            "Content-Length: 0\r\n\r\n".format(elsewhere.port)
        ).encode()
    )
    client = _socket_client(redirecting.port)
    try:
        runner = threading.Thread(target=client._run_websocket, daemon=True)
        runner.start()
        runner.join(5)

        assert "X-API-KEY: visdom_live_abc" in redirecting.requests[0]
        assert elsewhere.requests == []
        assert not runner.is_alive()
        assert client.use_socket is False
    finally:
        client.use_socket = False
        redirecting.close()
        elsewhere.close()


def test_a_socket_with_a_key_still_receives_messages():
    server = _FakeSocketServer(_upgrade)
    client = _socket_client(server.port)
    received = []
    try:
        client._run_keyed_websocket(
            "ws://127.0.0.1:{}/vis_socket".format(server.port),
            {"X-API-KEY": "visdom_live_abc", "X-Visdom-Workspace": "lab"},
            {},
            lambda ws, message: received.append(message),
            lambda ws, error: received.append(error),
            lambda ws: None,
        )

        assert received == ['{"command": "alive", "data": "vis_alive"}']
        assert "X-Visdom-Workspace: lab" in server.requests[0]
    finally:
        server.close()


def test_a_socket_with_a_key_waits_before_it_reconnects(monkeypatch):
    client = _socket_client(1)
    client.socket_connection_achieved = True
    attempts = []
    waits = []

    def stop_after_two_waits(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            client.use_socket = False

    def connect(*args):
        attempts.append(args)
        if len(attempts) == 3:
            client.use_socket = False

    monkeypatch.setattr(client, "_run_keyed_websocket", connect)
    monkeypatch.setattr("visdom.time.sleep", stop_after_two_waits)
    client._run_websocket()

    assert len(attempts) == 2
    assert waits == [3, 3]


@pytest.mark.parametrize(
    ("read_timeout", "setup_timeout"), [(None, 20), (0, 0), (3, 3), (45, 20)]
)
def test_keyed_socket_stop_aborts_read_and_cleans_up(
    monkeypatch, read_timeout, setup_timeout
):
    monkeypatch.setattr("visdom.websocket.getdefaulttimeout", lambda: read_timeout)
    client = _socket_client(1)
    ws = Mock()
    ws.getstatus.return_value = 101

    def stop_during_read():
        client.use_socket = False
        raise OSError("read interrupted by shutdown")

    ws.recv.side_effect = stop_during_read
    connect = Mock(return_value=ws)
    monkeypatch.setattr("visdom.websocket.create_connection", connect)
    on_message, on_error, on_close = Mock(), Mock(), Mock()
    options = {"sslopt": {"cert_reqs": 0}, "http_proxy_host": "proxy"}
    header = {"X-API-KEY": "visdom_live_abc"}

    client._run_keyed_websocket(
        "wss://visdom.example/vis_socket",
        header,
        options,
        on_message,
        on_error,
        on_close,
    )

    connect.assert_called_once_with(
        "wss://visdom.example/vis_socket",
        header=header,
        redirect_limit=0,
        class_=_KeyedWebSocket,
        timeout=setup_timeout,
        **options,
    )
    ws.settimeout.assert_called_once_with(read_timeout)
    on_message.assert_not_called()
    on_error.assert_not_called()
    ws.abort.assert_called_once_with()
    ws.shutdown.assert_called_once_with()
    on_close.assert_called_once_with(ws)
    assert client._keyed_websocket is None


@pytest.mark.parametrize("transport_closed", [True, False])
def test_disabling_keyed_socket_handles_transport_cleared_during_abort(
    transport_closed,
):
    client = _socket_client(1)
    ws = Mock()
    client._keyed_websocket = ws
    error = AttributeError("shutdown")

    def abort():
        if transport_closed:
            ws.sock = None
        raise error

    ws.abort.side_effect = abort

    if transport_closed:
        client.use_socket = False
    else:
        with pytest.raises(AttributeError) as raised:
            client.use_socket = False
        assert raised.value is error

    assert client.use_socket is False
    ws.abort.assert_called_once_with()


def test_disabling_keyed_socket_tolerates_oserror_from_abort():
    client = _socket_client(1)
    ws = Mock()
    ws.abort.side_effect = OSError("socket already closed")
    client._keyed_websocket = ws

    client.use_socket = False

    assert client.use_socket is False
    ws.abort.assert_called_once_with()


def test_keyed_socket_connection_timeout_reports_error_and_closes(monkeypatch):
    client = _socket_client(1)
    error = websocket.WebSocketTimeoutException("handshake timed out")
    connect = Mock(side_effect=error)
    ws = Mock()
    monkeypatch.setattr("visdom.websocket.create_connection", connect)
    monkeypatch.setattr("visdom.websocket.WebSocket", Mock(return_value=ws))
    on_message, on_error, on_close = Mock(), Mock(), Mock()

    client._run_keyed_websocket(
        "ws://visdom.example/vis_socket",
        {},
        {},
        on_message,
        on_error,
        on_close,
    )

    assert connect.call_args.kwargs["timeout"] == 20
    on_message.assert_not_called()
    on_error.assert_called_once_with(ws, error)
    ws.close.assert_called_once_with()
    on_close.assert_called_once_with(ws)


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_keyed_socket_stop_during_setup_skips_read(monkeypatch, cleanup_fails):
    client = _socket_client(1)
    ws = Mock()
    ws.getstatus.return_value = 101
    if cleanup_fails:
        ws.shutdown.side_effect = OSError("shutdown failed")

    def connect(*args, **kwargs):
        client.use_socket = False
        return ws

    monkeypatch.setattr("visdom.websocket.create_connection", connect)
    on_message, on_error, on_close = Mock(), Mock(), Mock()

    def run():
        client._run_keyed_websocket(
            "ws://visdom.example/vis_socket", {}, {}, on_message, on_error, on_close
        )

    if cleanup_fails:
        with pytest.raises(OSError, match="shutdown failed"):
            run()
    else:
        run()

    ws.recv.assert_not_called()
    ws.shutdown.assert_called_once_with()
    on_message.assert_not_called()
    on_error.assert_not_called()
    on_close.assert_called_once_with(ws)
    assert client._keyed_websocket is None


def test_keyed_handshake_deadline_interrupts_transport(monkeypatch):
    transport = Mock()
    interrupted = threading.Event()
    transport.shutdown.side_effect = lambda how: interrupted.set()
    ws = _KeyedWebSocket()

    def pending_upgrade(self, url, **options):
        self.sock = transport
        assert interrupted.wait(5)

    monkeypatch.setattr("visdom._KEYED_WEBSOCKET_SETUP_TIMEOUT", 0.02)
    monkeypatch.setattr(websocket.WebSocket, "connect", pending_upgrade)
    with pytest.raises(
        websocket.WebSocketTimeoutException, match="handshake timed out"
    ):
        ws.connect("ws://visdom.example/vis_socket")
    transport.shutdown.assert_called_once_with(socket.SHUT_RDWR)
    assert ws.sock is None
