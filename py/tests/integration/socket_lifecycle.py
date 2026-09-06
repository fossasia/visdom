#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Socket connection lifecycle: open, register, close.

Subscriber sockets (``SocketHandlerOrWrapper``) and source sockets
(``VisSocketHandlerOrWrapper``) share a base ``open`` that mints a sid and adds
the socket to one of the app's two registries, then each layers its own
handshake on top. These tests drive the real classes through
``testutils.socket_double``; see that module for why a duck type is not enough.

There is no HTTP here, but there is a real ``Application`` and real handler
dispatch, which is what ``integration`` means in this suite.
"""

import asyncio
import json

import pytest

from visdom.server.app import Application
from visdom.server.handlers.socket_handlers import (
    SocketFailureReason,
    SocketWrapper,
    VisSocketWrapper,
)

from testutils import commands, last, open_source, open_sub, sent, socket_double

pytestmark = pytest.mark.integration


@pytest.fixture
def readonly_app(env_path):
    """Application started the way ``visdom -readonly`` starts it."""
    return Application(port=8097, env_path=env_path, readonly=True)


# -- Opening a subscriber ----------------------------------------------------


def test_open_assigns_a_sid(app):
    """Every socket gets its own id at open time."""
    first = open_sub(app)
    second = open_sub(app)

    assert first.sid
    assert second.sid
    assert first.sid != second.sid


def test_open_registers_the_subscriber(app):
    """The socket lands in ``app.subs`` under its own sid."""
    sub = open_sub(app)

    assert app.subs[sub.sid] is sub
    assert app.sources == {}


def test_open_defaults_the_environment_to_main(app):
    """A fresh socket is subscribed to ``main`` until it says otherwise."""
    assert open_sub(app).eid == "main"


def test_register_payload_carries_the_sid(app):
    """The first message back is the register handshake."""
    sub = open_sub(app)
    register = sent(sub)[0]

    assert register["command"] == "register"
    assert register["data"] == sub.sid


def test_register_payload_reports_writable_server(app):
    """``readonly`` is false on a normal server."""
    assert sent(open_sub(app))[0]["readonly"] is False


def test_register_payload_reports_readonly_server(readonly_app):
    """A ``-readonly`` server says so in the handshake."""
    assert sent(open_sub(readonly_app))[0]["readonly"] is True


def test_register_payload_lists_environments_sorted(app):
    """``envList`` is the sorted env ids, so the client need not sort."""
    app.state["zebra"] = {"jsons": {}, "reload": {}}
    app.state["alpha"] = {"jsons": {}, "reload": {}}

    assert sent(open_sub(app))[0]["envList"] == ["alpha", "main", "zebra"]


def test_open_follows_up_with_layouts_and_environments(app):
    """Register, then the saved layouts, then the env list — in that order."""
    assert commands(open_sub(app)) == ["register", "layout_update", "env_update"]


def test_layout_update_carries_the_saved_layouts(app):
    """The layout message ships whatever the app has loaded."""
    app.layouts = '[["view A", {"win_0": [0, 0, 3, 3]}]]'
    sub = open_sub(app)

    assert last(sub, "layout_update")["data"] == app.layouts


def test_env_update_carries_the_environment_ids(app):
    """The env message ships the live state keys."""
    app.state["expt"] = {"jsons": {}, "reload": {}}
    sub = open_sub(app)

    assert sorted(last(sub, "env_update")["data"]) == ["expt", "main"]


def test_opening_only_notifies_the_new_socket(app):
    """An existing subscriber is not re-sent the handshake of a new one."""
    first = open_sub(app)
    before = len(first.messages)

    open_sub(app)

    assert len(first.messages) == before


# -- Opening a source --------------------------------------------------------


def test_source_registers_separately_from_subscribers(app):
    """Sources and subscribers live in different registries."""
    source = open_source(app)

    assert app.sources[source.sid] is source
    assert app.subs == {}


def test_source_handshake_is_an_alive_ping(app):
    """A source is told the server is up; it gets no layouts or env list."""
    source = open_source(app)

    assert sent(source) == [{"command": "alive", "data": "vis_alive"}]


def test_both_socket_kinds_can_be_open_at_once(app):
    """The two registries do not collide."""
    sub = open_sub(app)
    source = open_source(app)

    assert list(app.subs) == [sub.sid]
    assert list(app.sources) == [source.sid]


# -- Closing -----------------------------------------------------------------


def test_close_deregisters_a_subscriber(app):
    """``on_close`` removes the socket from ``app.subs``."""
    sub = open_sub(app)
    sub.on_close()

    assert app.subs == {}


def test_close_deregisters_a_source(app):
    """``on_close`` removes the socket from ``app.sources``."""
    source = open_source(app)
    source.on_close()

    assert app.sources == {}


def test_close_leaves_other_sockets_registered(app):
    """Closing one subscriber does not disturb the others."""
    first = open_sub(app)
    second = open_sub(app)
    first.on_close()

    assert list(app.subs) == [second.sid]


def test_close_on_an_unopened_socket_is_a_noop(app):
    """A socket that never registered can still be closed."""
    socket_double(SocketWrapper, app).on_close()
    socket_double(VisSocketWrapper, app).on_close()

    assert app.subs == {}
    assert app.sources == {}


def test_close_twice_is_a_noop(app):
    """A second close does not raise on the already-removed sid."""
    sub = open_sub(app)
    sub.on_close()
    sub.on_close()

    assert app.subs == {}


def test_polling_close_routes_through_on_close(app):
    """``close()`` on a polling wrapper is the deregistration path."""
    sub = open_sub(app)
    sub.close()

    assert app.subs == {}


def test_reopening_keeps_the_socket_under_its_first_sid(app):
    """A second ``open`` mints a new sid but does not re-register.

    ``open`` assigns ``self.sid`` before checking membership, so an already
    registered socket keeps its registry entry under the *old* sid while
    carrying the new one. ``on_close`` pops ``self.sid``, so the entry then
    outlives the socket. Pinned down here as current behaviour; nothing in the
    server reopens a live socket today.
    """
    sub = open_sub(app)
    first_sid = sub.sid

    sub.open()

    assert sub.sid != first_sid
    assert list(app.subs) == [first_sid]

    sub.on_close()
    assert list(app.subs) == [first_sid]


# -- Message queue -----------------------------------------------------------


def test_get_messages_drains_the_queue(app):
    """A polling client reads each message once."""
    sub = open_sub(app)

    drained = sub.get_messages()

    assert len(drained) == 3
    assert sub.get_messages() == []


def test_get_messages_stamps_the_read_time(app):
    """Reading refreshes the idle timer the reaper watches."""
    sub = open_sub(app)
    sub.last_read_time = 0

    sub.get_messages()

    assert sub.last_read_time > 0


# -- Readonly short-circuit --------------------------------------------------


def test_readonly_socket_ignores_commands(readonly_app):
    """A readonly server drops every socket command before dispatch."""
    readonly_app.state["expt"] = {"jsons": {}, "reload": {}}
    sub = open_sub(readonly_app)

    asyncio.run(sub.on_message(json.dumps({"cmd": "delete_env", "eid": "expt"})))

    assert "expt" in readonly_app.state


def test_readonly_socket_ignores_an_unknown_command(readonly_app):
    """The short-circuit happens before the command is even recognised."""
    sub = open_sub(readonly_app)
    before = len(sub.messages)

    asyncio.run(sub.on_message(json.dumps({"cmd": "not_a_command"})))

    assert len(sub.messages) == before


# -- SocketFailureReason -----------------------------------------------------


@pytest.mark.parametrize(
    "reason,value",
    [
        (SocketFailureReason.CONNECTION_CLOSED, "closed"),
        (SocketFailureReason.MISSING_MESSAGE, "no msg"),
        (SocketFailureReason.INVALID_MESSAGE_TYPE, "invalid"),
    ],
)
def test_failure_reason_wire_value(reason, value):
    """The short code is what goes on the wire; the detail explains it."""
    assert reason.value == value
    assert reason.detail


def test_failure_response_shape():
    """A failure response always reports success false with a reason."""
    resp = SocketFailureReason.CONNECTION_CLOSED.to_failure_response()

    assert resp["success"] is False
    assert resp["reason"] == "closed"
    assert resp["detail"] == SocketFailureReason.CONNECTION_CLOSED.detail
    assert "message" not in resp


def test_failure_response_carries_an_optional_message():
    """Callers can attach the offending value for debugging."""
    resp = SocketFailureReason.MISSING_MESSAGE.to_failure_response("sid=None")

    assert resp["message"] == "sid=None"


def test_failure_reasons_have_distinct_codes():
    """No two reasons share a wire value."""
    values = [reason.value for reason in SocketFailureReason]

    assert len(values) == len(set(values))
