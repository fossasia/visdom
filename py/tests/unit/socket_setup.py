#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import json
from types import SimpleNamespace
from unittest import mock

import pytest

import visdom
from visdom import Visdom


def _client():
    client = Visdom.__new__(Visdom)
    client.event_handlers = {}
    client.socket_alive = False
    client.socket_connection_achieved = False
    return client


def test_shared_incoming_handler_accepts_alive_handshake():
    client = _client()

    client._handle_incoming_message(
        json.dumps({"command": "alive", "data": "vis_alive"})
    )

    assert client.socket_alive
    assert client.socket_connection_achieved


def test_shared_incoming_handler_isolates_callback_failures():
    client = _client()
    calls = []

    def failing_handler(message):
        calls.append(("failing", message))
        raise RuntimeError("callback failed")

    def env_handler(message):
        calls.append(("env", message))

    def global_handler(message):
        calls.append(("global", message))

    client.event_handlers = {
        ("train", "pane"): [failing_handler, env_handler],
        (None, "pane"): [global_handler],
    }
    message = {"target": "pane", "eid": "train", "event_type": "Click"}

    with mock.patch.object(visdom.traceback, "print_exc") as print_exc:
        client._handle_incoming_message(json.dumps(message))

    assert [name for name, _ in calls] == ["failing", "env", "global"]
    assert all(received == message for _, received in calls)
    print_exc.assert_called_once_with()


def test_polling_runner_uses_shared_message_handler():
    client = _client()
    client.server = "http://localhost"
    client.port = 8097
    client.base_url = ""
    client.use_socket = True
    client.socket_alive = True
    raw_message = json.dumps({"target": "pane", "eid": "train"})
    requests = []

    def handle_post(url, data):
        requests.append((url, json.loads(data)))
        if len(requests) == 1:
            return json.dumps({"success": True, "sid": "source-1"})
        client.use_socket = False
        return json.dumps({"success": True, "messages": [raw_message]})

    client._handle_post = mock.Mock(side_effect=handle_post)
    client._handle_incoming_message = mock.Mock()

    with mock.patch.object(visdom.time, "sleep") as sleep:
        client._run_polling()

    assert client.vis_sid == "source-1"
    assert requests == [
        (
            "http://localhost:8097/vis_socket_wrap",
            {"message_type": "init"},
        ),
        (
            "http://localhost:8097/vis_socket_wrap",
            {"message_type": "query", "sid": "source-1"},
        ),
    ]
    client._handle_incoming_message.assert_called_once_with(raw_message)
    sleep.assert_called_once_with(0.1)
    assert not client.socket_alive


def test_polling_ignores_bad_messages_and_isolates_handler_failures(caplog):
    client = _client()
    client.server = "http://localhost"
    client.port = 8097
    client.base_url = ""
    client.use_socket = True
    calls = []

    def failing_handler(message):
        calls.append(("failing", message))
        raise RuntimeError("callback failed")

    def healthy_handler(message):
        calls.append(("healthy", message))

    client.event_handlers = {
        ("train", "pane"): [failing_handler, healthy_handler],
    }
    message = {"target": "pane", "eid": "train", "event_type": "Click"}
    requests = []

    def handle_post(_url, data):
        request = json.loads(data)
        requests.append(request)
        if request["message_type"] == "init":
            return json.dumps({"success": True, "sid": "source-1"})

        client.use_socket = False
        return json.dumps(
            {
                "success": True,
                "messages": ["not-json", json.dumps(message)],
            }
        )

    client._handle_post = mock.Mock(side_effect=handle_post)

    with (
        mock.patch.object(visdom.time, "sleep") as sleep,
        mock.patch.object(visdom.traceback, "print_exc") as print_exc,
    ):
        client._run_polling()

    assert [name for name, _ in calls] == ["failing", "healthy"]
    assert all(received == message for _, received in calls)
    assert requests == [
        {"message_type": "init"},
        {"message_type": "query", "sid": "source-1"},
    ]
    assert "failed to decode incoming message" in caplog.text
    print_exc.assert_called_once_with()
    sleep.assert_called_once_with(0.1)
    assert not client.socket_alive


def test_websocket_runner_uses_shared_message_handler():
    client = _client()
    client.server = "http://localhost"
    client.server_base_name = "localhost"
    client.port = 8097
    client.base_url = ""
    client.http_proxy_host = None
    client.http_proxy_port = None
    client.ssl_verify = True
    client.use_socket = True
    client._handle_incoming_message = mock.Mock()
    ws = mock.Mock()
    ws.run_forever.side_effect = lambda **kwargs: setattr(client, "use_socket", False)

    with (
        mock.patch.object(
            Visdom,
            "session",
            new_callable=mock.PropertyMock,
            return_value=SimpleNamespace(cookies={}),
        ),
        mock.patch.object(
            visdom.websocket, "WebSocketApp", return_value=ws
        ) as websocket_app,
        mock.patch.object(visdom.time, "sleep"),
    ):
        client._run_websocket()

    on_message = websocket_app.call_args.kwargs["on_message"]
    on_message(ws, "raw-message")

    client._handle_incoming_message.assert_called_once_with("raw-message")
    ws.run_forever.assert_called_once_with(
        http_proxy_host=None,
        http_proxy_port=None,
        ping_timeout=100.0,
    )
    ws.close.assert_called_once_with()


def test_websocket_runner_preserves_wss_ssl_options():
    client = _client()
    client.server = "https://localhost"
    client.server_base_name = "localhost"
    client.port = 8097
    client.base_url = ""
    client.http_proxy_host = None
    client.http_proxy_port = None
    client.ssl_verify = False
    client.use_socket = True
    ws = mock.Mock()
    ws.run_forever.side_effect = lambda **kwargs: setattr(client, "use_socket", False)

    with (
        mock.patch.object(
            Visdom,
            "session",
            new_callable=mock.PropertyMock,
            return_value=SimpleNamespace(cookies={}),
        ),
        mock.patch.object(
            visdom.websocket, "WebSocketApp", return_value=ws
        ) as websocket_app,
        mock.patch.object(visdom.time, "sleep"),
    ):
        client._run_websocket()

    assert websocket_app.call_args.args[0] == "wss://localhost:8097/vis_socket"
    ws.run_forever.assert_called_once_with(
        http_proxy_host=None,
        http_proxy_port=None,
        ping_timeout=100.0,
        sslopt={"cert_reqs": visdom.ssl.CERT_NONE},
    )


def test_setup_polling_uses_merged_socket_setup():
    client = _client()
    client.setup_socket = mock.Mock()

    client.setup_polling()

    client.setup_socket.assert_called_once_with(polling=True)


@pytest.mark.parametrize(
    ("polling", "runner_name"),
    [
        (False, "_run_websocket"),
        (True, "_run_polling"),
    ],
)
def test_setup_socket_selects_daemon_runner(polling, runner_name):
    client = _client()
    thread = mock.Mock()

    with mock.patch.object(
        visdom.threading, "Thread", return_value=thread
    ) as thread_class:
        client.setup_socket(polling=polling)

    thread_class.assert_called_once_with(
        target=getattr(client, runner_name),
        name="Visdom-Socket-Thread",
        daemon=True,
    )
    thread.start.assert_called_once_with()
    assert client.socket_thread is thread
