#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Exercise keyed socket shutdown against a real, silent WebSocket peer."""

import base64
import hashlib
import socket
import threading
from unittest.mock import Mock

import pytest
import websocket

from visdom import Visdom

pytestmark = pytest.mark.integration


@pytest.mark.slow
@pytest.mark.parametrize(
    "prefix, suffix",
    [
        (b"", b""),
        (b"\x81\x05hello", b""),
        (b"\x81\x05he", b""),
        (b"\x81\x05he", b"llo"),
    ],
)
def test_keyed_socket_can_stop_while_peer_keeps_connection_open(
    monkeypatch, prefix, suffix
):
    client = Visdom.__new__(Visdom)
    client.use_socket = True
    client_socket, peer_socket = socket.socketpair()
    release_peer = threading.Event()
    read_timed_out = threading.Event()
    peer_errors = []

    def serve():
        try:
            with peer_socket:
                peer_socket.settimeout(5)
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = peer_socket.recv(4096)
                    if not chunk:
                        return
                    request += chunk
                key = next(
                    line.split(b":", 1)[1].strip()
                    for line in request.split(b"\r\n")
                    if line.lower().startswith(b"sec-websocket-key:")
                )
                accept = base64.b64encode(
                    hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
                )
                peer_socket.sendall(
                    b"HTTP/1.1 101 Switching Protocols\r\n"
                    b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n" + prefix
                )
                release_peer.wait(10)
        except Exception as error:
            peer_errors.append(error)

    create_connection = websocket.create_connection

    def connect(*args, **kwargs):
        ws = create_connection(*args, **kwargs)
        recv = ws.recv

        def observed_recv():
            try:
                return recv()
            except websocket.WebSocketTimeoutException:
                read_timed_out.set()
                raise

        monkeypatch.setattr(ws, "recv", observed_recv)
        return ws

    monkeypatch.setattr("visdom.websocket.create_connection", connect)
    on_message, on_error, on_close = Mock(), Mock(), Mock()
    if suffix:
        on_message.side_effect = lambda ws, message: setattr(
            client, "use_socket", False
        )
    peer = threading.Thread(target=serve, daemon=True)
    runner = threading.Thread(
        target=client._run_keyed_websocket,
        args=(
            "ws://localhost/vis_socket",
            {"X-API-KEY": "test-key"},
            {"socket": client_socket},
            on_message,
            on_error,
            on_close,
        ),
        daemon=True,
    )
    try:
        peer.start()
        runner.start()
        assert read_timed_out.wait(3), "socket read has no finite timeout"
        if suffix:
            peer_socket.sendall(suffix)
        else:
            client.use_socket = False
        # websocket-client also allows three seconds for the close handshake.
        runner.join(6)

        assert not runner.is_alive(), "silent peer blocked socket shutdown"
        assert peer.is_alive(), "peer must remain open until the worker exits"
        assert not peer_errors
        assert [call.args[1] for call in on_message.call_args_list] == (
            ["hello"] if prefix == b"\x81\x05hello" or suffix else []
        )
        on_error.assert_not_called()
        on_close.assert_called_once()
    finally:
        client.use_socket = False
        release_peer.set()
        client_socket.close()
        runner.join(3)
        peer.join(3)
