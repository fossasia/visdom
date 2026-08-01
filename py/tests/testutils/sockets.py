#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Real socket handlers, built without a WebSocket connection.

``FakeHandler`` is enough to drive ``AnySocketHandlerOrWrapper.on_message`` as
an unbound function, and ``test_storage_wiring.py`` does exactly that. It runs
out of road for three things this suite needs:

* ``save_layouts`` calls ``self.broadcast_layouts()`` and reads ``self.app`` —
  neither exists on a duck type.
* ``VisSocketHandlerOrWrapper.on_message`` ends in a zero-argument ``super()``
  call, which raises ``TypeError`` unless ``self`` really is an instance.
* ``open`` / ``on_close`` are the subject of the lifecycle tests, so they have
  to be the real methods on a real object.

The polling wrappers already exist for a related reason: ``SocketWrapper`` and
``VisSocketWrapper`` deliberately skip Tornado's ``__init__`` so the server can
mint one per polling client. That makes them constructible in a test, and their
``write_message`` records to a ``deque`` instead of a socket, so assertions read
straight off ``messages``.

``socket_double`` finishes the object by hand rather than calling
``initialize``: the wrapper's own ``initialize`` starts a 15-second
``PeriodicCallback`` reaper and needs a running ``IOLoop``, which is polling's
business and belongs with the polling tests.
"""

import json
import time
import types
from collections import deque

from visdom.server.handlers.base_handlers import BaseWebSocketHandler
from visdom.server.handlers.socket_handlers import SocketWrapper, VisSocketWrapper


def socket_double(cls, app, remote_ip="127.0.0.1"):
    """Build a ``cls`` bound to ``app`` with no network underneath it.

    ``cls`` is :class:`SocketWrapper` (a subscriber) or
    :class:`VisSocketWrapper` (a source). The returned object is not registered
    yet — call ``open()`` to exercise the registration path under test.

    ``request`` is a stub carrying only ``remote_ip``, which is all ``open()``
    reads off it. The server assigns the real one the same way, in
    ``WrapSocketWrapper``'s GET route.
    """
    sock = cls()
    sock.request = types.SimpleNamespace(remote_ip=remote_ip)
    sock.messages = deque()
    sock.last_read_time = time.time()
    BaseWebSocketHandler.initialize(sock, app)
    return sock


def open_sub(app, remote_ip="127.0.0.1"):
    """An opened subscriber socket, registered in ``app.subs``."""
    sub = socket_double(SocketWrapper, app, remote_ip)
    sub.open()
    return sub


def open_source(app, remote_ip="127.0.0.1"):
    """An opened source socket, registered in ``app.sources``."""
    source = socket_double(VisSocketWrapper, app, remote_ip)
    source.open()
    return source


def sent(sock):
    """Every message written to ``sock``, decoded, oldest first."""
    return [json.loads(m) if isinstance(m, str) else m for m in sock.messages]


def commands(sock):
    """The ``command`` value of every dict message written to ``sock``."""
    return [m.get("command") for m in sent(sock) if isinstance(m, dict)]


def last(sock, command=None):
    """Most recent decoded message, optionally filtered by ``command``."""
    for msg in reversed(sent(sock)):
        if command is None or (isinstance(msg, dict) and msg.get("command") == command):
            return msg
    return None
