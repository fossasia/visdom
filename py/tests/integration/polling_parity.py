#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The polling transport, and its parity with the WebSocket one.

``AGENTS.md`` requires every socket feature to work over both transports.
Polling replaces the socket with two routes: ``/socket_wrap`` for subscribers
and ``/vis_socket_wrap`` for sources. A client asks for a sid, then POSTs
``message_type: "send"`` to push a command and ``message_type: "query"`` to
drain whatever the server has queued for it. Server-side each sid owns a
``SocketWrapper`` whose ``write_message`` appends to a deque instead of writing
to a connection, so the same ``on_message`` dispatch runs either way.

The HTTP round trip is what is under test here, so these are
``VisdomHTTPTestCase`` subclasses. The reaper and the queue are reachable
without a request and stay plain functions.
"""

import json
import time
import unittest
from unittest import mock

import pytest

from visdom.server.defaults import MAX_SOCKET_WAIT
from visdom.server.handlers.socket_handlers import SocketWrapper, VisSocketWrapper

from testutils import socket_double
from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


class PollingTestCase(VisdomHTTPTestCase):
    """Server configured the way ``visdom -use_frontend_client_polling`` runs.

    ``sub_sid`` / ``source_sid`` mint an id the way the two client kinds do:
    the browser GETs ``/socket_wrap``, the python client POSTs to
    ``/vis_socket_wrap`` without one.
    """

    app_kwargs = {"use_frontend_client_polling": True}

    def sub_sid(self):
        return json.loads(self.fetch("/socket_wrap").body)["sid"]

    def source_sid(self):
        return json.loads(self.poll("/vis_socket_wrap", None, "query").body)["sid"]

    def poll(self, route, sid, message_type, message=None):
        body = {"sid": sid, "message_type": message_type}
        if message is not None:
            body["message"] = message
        return self.post_json(route, body)

    def query(self, sid, route="/socket_wrap"):
        """Drain the queued messages for ``sid``, decoded."""
        resp = json.loads(self.poll(route, sid, "query").body)
        self.assertTrue(resp["success"], resp)
        return [json.loads(m) for m in resp["messages"]]

    def send(self, sid, command, route="/socket_wrap"):
        return self.poll(route, sid, "send", json.dumps(command))


# -- Minting a connection ----------------------------------------------------


class TestSubscriberHandshake(PollingTestCase):
    def test_get_mints_a_sid(self):
        resp = json.loads(self.fetch("/socket_wrap").body)

        self.assertTrue(resp["success"])
        self.assertTrue(resp["sid"])

    def test_each_client_gets_its_own_sid(self):
        self.assertNotEqual(self.sub_sid(), self.sub_sid())

    def test_the_sid_is_registered_as_a_subscriber(self):
        sid = self.sub_sid()

        self.assertIn(sid, self._app.subs)
        self.assertEqual(self._app.sources, {})

    def test_the_first_query_returns_the_register_handshake(self):
        """register, layouts, envs — then a fourth, redundant layout push.

        ``SocketHandlerOrWrapper.initialize`` broadcasts layouts to every
        subscriber, and on this path the socket has already registered itself
        by then, because ``AnySocketWrapper.initialize`` opens it first. So it
        receives its own broadcast. A WebSocket subscriber opens *after*
        ``initialize`` and sees three messages. Idempotent either way, but it
        is the one place the transports differ, so it is pinned here rather
        than left to surprise the next reader.
        """
        sid = self.sub_sid()

        messages = self.query(sid)

        self.assertEqual(
            [m["command"] for m in messages],
            ["register", "layout_update", "env_update", "layout_update"],
        )
        self.assertEqual(messages[0]["data"], sid)

    def test_a_new_client_re_pushes_layouts_to_the_existing_ones(self):
        """Same cause as above, seen from the other side of the registry."""
        first = self.sub_sid()
        self.query(first)

        self.sub_sid()

        self.assertEqual([m["command"] for m in self.query(first)], ["layout_update"])

    def test_the_handshake_is_delivered_only_once(self):
        sid = self.sub_sid()
        self.query(sid)

        self.assertEqual(self.query(sid), [])


class TestSourceHandshake(PollingTestCase):
    def test_a_post_without_a_sid_mints_one(self):
        resp = json.loads(self.poll("/vis_socket_wrap", None, "query").body)

        self.assertTrue(resp["success"])
        self.assertTrue(resp["sid"])

    def test_the_sid_is_registered_as_a_source(self):
        sid = self.source_sid()

        self.assertIn(sid, self._app.sources)
        self.assertEqual(self._app.subs, {})

    def test_the_source_handshake_is_an_alive_ping(self):
        sid = self.source_sid()

        self.assertEqual(
            self.query(sid, route="/vis_socket_wrap"),
            [{"command": "alive", "data": "vis_alive"}],
        )

    def test_minting_twice_yields_two_sources(self):
        self.source_sid()
        self.source_sid()

        self.assertEqual(len(self._app.sources), 2)


# -- Protocol errors ---------------------------------------------------------


class TestPollingProtocolErrors(PollingTestCase):
    def _assert_failure(self, resp, reason):
        body = json.loads(resp.body)
        self.assertEqual(resp.code, 200)
        self.assertFalse(body["success"])
        self.assertEqual(body["reason"], reason)
        self.assertTrue(body["detail"])
        return body

    def test_an_unknown_sid_is_reported_as_closed(self):
        body = self._assert_failure(
            self.poll("/socket_wrap", "never_minted", "query"), "closed"
        )

        self.assertIn("never_minted", body["message"])

    def test_a_subscriber_sid_is_not_a_source_sid(self):
        """The two registries are separate; a sid is only valid on its route."""
        sid = self.sub_sid()

        self._assert_failure(self.poll("/vis_socket_wrap", sid, "query"), "closed")

    def test_send_without_a_message_is_rejected(self):
        sid = self.sub_sid()

        self._assert_failure(self.poll("/socket_wrap", sid, "send"), "no msg")

    def test_an_unknown_message_type_is_rejected(self):
        sid = self.sub_sid()

        body = self._assert_failure(
            self.poll("/socket_wrap", sid, "subscribe"), "invalid"
        )

        self.assertIn("subscribe", body["message"])

    def test_a_missing_message_type_is_rejected(self):
        sid = self.sub_sid()

        self._assert_failure(self.post_json("/socket_wrap", {"sid": sid}), "invalid")

    def test_a_closed_socket_stops_answering(self):
        sid = self.sub_sid()
        self._app.subs[sid].close()

        self._assert_failure(self.poll("/socket_wrap", sid, "query"), "closed")


# -- Commands over the polling transport -------------------------------------


class TestPollingCommandParity(PollingTestCase):
    """Each command has the same effect as it does over a WebSocket."""

    def test_close_removes_the_pane(self):
        win = self.create_text_window(content="polled")
        sid = self.sub_sid()

        resp = self.send(sid, {"cmd": "close", "eid": "main", "data": win})

        self.assertTrue(json.loads(resp.body)["success"])
        self.assertNotIn(win, self.panes())

    def test_close_reaches_the_sources(self):
        win = self.create_text_window(content="polled")
        source_sid = self.source_sid()
        self.query(source_sid, route="/vis_socket_wrap")
        sid = self.sub_sid()

        self.send(sid, {"cmd": "close", "eid": "main", "data": win})

        forwarded = self.query(source_sid, route="/vis_socket_wrap")
        self.assertEqual(forwarded[0]["event_type"], "close")
        self.assertEqual(forwarded[0]["target"], win)
        self.assertIsNotNone(forwarded[0]["pane_data"])

    def test_undo_restores_the_pane(self):
        win = self.create_text_window(content="polled")
        sid = self.sub_sid()
        self.send(sid, {"cmd": "close", "eid": "main", "data": win})

        self.send(sid, {"cmd": "undo", "eid": "main"})

        self.assertIn(win, self.panes())

    def test_save_has_persisted_before_the_response_returns(self):
        """The bridge awaits dispatch, so a command's disk work is done by then.

        Dispatch hands the write to the storage worker; answering the POST
        without waiting for it would tell the client the env was saved while
        the file was still queued behind whatever else that worker had.
        """
        self.create_text_window(eid="expt", content="polled")
        sid = self.sub_sid()

        resp = self.send(
            sid, {"cmd": "save", "eid": "copy", "prev_eid": "expt", "data": {}}
        )

        self.assertTrue(json.loads(resp.body)["success"])
        self.assertTrue(self._app.storage.env_exists("copy"))

    def test_delete_env_removes_the_environment(self):
        self.create_text_window(eid="expt", content="polled")
        sid = self.sub_sid()

        self.send(sid, {"cmd": "delete_env", "eid": "expt"})

        self.assertNotIn("expt", self._app.state)

    def test_save_layouts_updates_the_application(self):
        sid = self.sub_sid()
        layouts = '[["view A", {"win_0": [0, 0, 3, 3]}]]'

        self.send(sid, {"cmd": "save_layouts", "data": layouts})

        self.assertEqual(self._app.layouts, layouts)

    def test_save_layouts_is_broadcast_back_to_the_poller(self):
        sid = self.sub_sid()
        self.query(sid)
        layouts = '[["view B", {}]]'

        self.send(sid, {"cmd": "save_layouts", "data": layouts})

        self.assertEqual(
            self.query(sid), [{"command": "layout_update", "data": layouts}]
        )

    def test_a_source_can_save_layouts_too(self):
        """The command is handled on the shared base, not the subscriber."""
        sid = self.source_sid()
        layouts = '[["view C", {}]]'

        resp = self.send(
            sid, {"cmd": "save_layouts", "data": layouts}, "/vis_socket_wrap"
        )

        self.assertTrue(json.loads(resp.body)["success"])
        self.assertEqual(self._app.layouts, layouts)

    def test_update_comment_lands_on_the_pane(self):
        win = self.create_text_window(content="polled")
        sid = self.sub_sid()

        self.send(
            sid, {"cmd": "update_comment", "eid": "main", "win": win, "data": "note"}
        )

        self.assertEqual(self.panes()[win]["comment"], "note")

    def test_layout_item_update_is_recorded(self):
        win = self.create_text_window(content="polled")
        sid = self.sub_sid()

        self.send(
            sid,
            {"cmd": "layout_item_update", "eid": "main", "win": win, "data": [0, 0]},
        )

        self.assertEqual(self._app.state["main"]["reload"][win], [0, 0])

    def test_echo_comes_back_on_the_source_route(self):
        sid = self.source_sid()
        self.query(sid, route="/vis_socket_wrap")

        self.send(sid, {"cmd": "echo", "data": "ping"}, "/vis_socket_wrap")

        self.assertEqual(
            self.query(sid, route="/vis_socket_wrap"),
            [{"cmd": "echo", "data": "ping"}],
        )

    def test_a_broadcast_reaches_every_polling_subscriber(self):
        first, second = self.sub_sid(), self.sub_sid()
        self.query(first)
        self.query(second)

        self.create_text_window(content="broadcast")

        self.assertEqual(len(self.query(first)), 1)
        self.assertEqual(len(self.query(second)), 1)


class TestPollingUnderReadonly(PollingTestCase):
    app_kwargs = {"use_frontend_client_polling": True, "readonly": True}

    def test_the_handshake_reports_the_mode(self):
        sid = self.sub_sid()

        self.assertTrue(self.query(sid)[0]["readonly"])

    def test_a_command_is_accepted_but_dropped(self):
        self._app.state["expt"] = {"jsons": {}, "reload": {}}
        sid = self.sub_sid()

        resp = self.send(sid, {"cmd": "delete_env", "eid": "expt"})

        self.assertTrue(json.loads(resp.body)["success"])
        self.assertIn("expt", self._app.state)


# -- The idle reaper ---------------------------------------------------------
#
# ``socket_wrap_monitor_thread`` runs on a 15s PeriodicCallback and closes
# polling clients that have stopped reading. Calling it directly needs no loop.


def _reaper(app, sockets):
    """Register ``sockets`` and return the wrapper the monitor runs on."""
    for sock in sockets:
        sock.open()
    return sockets[0] if sockets else socket_double(SocketWrapper, app)


def test_the_reaper_closes_an_idle_subscriber(app):
    sub = _reaper(app, [socket_double(SocketWrapper, app)])
    sub.last_read_time = time.time() - MAX_SOCKET_WAIT - 1

    sub.socket_wrap_monitor_thread()

    assert app.subs == {}


def test_the_reaper_keeps_a_subscriber_that_still_polls(app):
    sub = _reaper(app, [socket_double(SocketWrapper, app)])
    sub.last_read_time = time.time()

    sub.socket_wrap_monitor_thread()

    assert list(app.subs) == [sub.sid]


def test_the_reaper_closes_an_idle_source(app):
    source = _reaper(app, [socket_double(VisSocketWrapper, app)])
    source.last_read_time = time.time() - MAX_SOCKET_WAIT - 1

    source.socket_wrap_monitor_thread()

    assert app.sources == {}


def test_the_reaper_leaves_the_other_clients_alone(app):
    idle = socket_double(SocketWrapper, app)
    active = socket_double(SocketWrapper, app)
    _reaper(app, [idle, active])
    idle.last_read_time = time.time() - MAX_SOCKET_WAIT - 1
    active.last_read_time = time.time()

    idle.socket_wrap_monitor_thread()

    assert list(app.subs) == [active.sid]


def test_the_reaper_stops_itself_once_everyone_has_gone(app):
    sub = _reaper(app, [socket_double(SocketWrapper, app)])
    sub.on_close()

    with mock.patch.object(app.server_state, "stop_socket_monitor") as stop:
        sub.socket_wrap_monitor_thread()

    stop.assert_called_once_with()


def test_a_query_postpones_the_reaper(app):
    sub = _reaper(app, [socket_double(SocketWrapper, app)])
    sub.last_read_time = time.time() - MAX_SOCKET_WAIT - 1

    sub.get_messages()
    sub.socket_wrap_monitor_thread()

    assert list(app.subs) == [sub.sid]


# -- The pending-message queue -----------------------------------------------


def test_the_queue_holds_everything_written_between_polls(app):
    """Nothing bounds ``messages``; a client that stops polling accumulates.

    Pinned down as current behaviour. The reaper above is what keeps it from
    growing forever, so the two belong together: drop the reaper and this deque
    is an unbounded leak per abandoned client.
    """
    sub = socket_double(SocketWrapper, app)
    for n in range(200):
        sub.write_message(json.dumps({"n": n}))

    drained = sub.get_messages()

    assert len(drained) == 200
    assert [json.loads(m)["n"] for m in drained] == list(range(200))


def test_the_queue_is_drained_in_arrival_order(app):
    sub = socket_double(SocketWrapper, app)
    sub.write_message("first")
    sub.write_message("second")

    assert sub.get_messages() == ["first", "second"]
    assert sub.get_messages() == []


if __name__ == "__main__":
    unittest.main()
