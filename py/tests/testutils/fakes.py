#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Test doubles for handler, socket and storage collaborators.

The server's handler entry points (``wrap_func``, ``on_message``) read a fixed
set of attributes off the handler rather than off ``self.app`` -- see the
``initialize()`` contract in ``visdom/server/handlers/base_handlers.py``. That
makes them drivable without a Tornado request, which is what ``FakeHandler``
exploits.
"""

import json
import threading

from visdom.data_model.json_store import JSONStore


class FakeSocket:
    """Stand-in for a subscriber or source socket.

    Records every message written to it. ``messages`` holds the raw arguments
    passed to ``write_message``; ``sent`` decodes the JSON ones for assertions.
    """

    def __init__(self, sid="sid_0", eid="main"):
        self.sid = sid
        self.eid = eid
        self.messages = []
        self.closed = False

    def write_message(self, msg):
        self.messages.append(msg)

    def close(self):
        self.closed = True

    @property
    def sent(self):
        decoded = []
        for msg in self.messages:
            decoded.append(json.loads(msg) if isinstance(msg, str) else msg)
        return decoded

    def commands(self):
        """Every ``command`` value seen, in order."""
        return [m.get("command") for m in self.sent if isinstance(m, dict)]

    def last(self, command=None):
        """Most recent decoded message, optionally filtered by ``command``."""
        for msg in reversed(self.sent):
            if command is None or (
                isinstance(msg, dict) and msg.get("command") == command
            ):
                return msg
        return None


class FakeHandler:
    """Duck-typed handler carrying the attributes the server functions read.

    Mirrors the fields ``StateAccessorsMixin`` exposes off ``ServerState`` so
    the same object can drive both ``web_handlers`` wrap functions and socket
    ``on_message`` dispatch. ``write`` captures HTTP response bodies and
    ``set_status`` captures the status code.
    """

    def __init__(
        self,
        state=None,
        storage=None,
        subs=None,
        sources=None,
        readonly=False,
        login_enabled=False,
        env_path=None,
        port=8097,
        max_text_lines=500,
        max_old_content=50,
        max_image_history=4,
        max_plot_history=4,
    ):
        self.state = {} if state is None else state
        self.storage = JSONStore(env_path) if storage is None else storage
        self.subs = {} if subs is None else subs
        self.sources = {} if sources is None else sources
        self.readonly = readonly
        self.login_enabled = login_enabled
        self.env_path = env_path
        self.port = port
        self.max_text_lines = max_text_lines
        self.max_old_content = max_old_content
        self.max_image_history = max_image_history
        self.max_plot_history = max_plot_history

        # Envs with a delete on its way to disk, as ``ServerState`` tracks
        # them; readers that resume after yielding the loop consult it.
        self.deleting_envs = {}

        self.written = []
        self.status = None
        self.eid = "main"
        self.sid = "sid_handler"
        self.broadcasted = []
        self.dirtied = []

    def mark_dirty(self, eid):
        """Record an environment the server flagged as needing a save."""
        self.dirtied.append(eid)

    def write(self, chunk):
        self.written.append(chunk)

    def set_status(self, code, reason=None):
        self.status = code

    def write_message(self, msg):
        self.broadcasted.append(msg)

    @property
    def body(self):
        """Concatenated response body as a string."""
        return "".join(
            c.decode() if isinstance(c, bytes) else str(c) for c in self.written
        )

    def json_body(self):
        return json.loads(self.body)

    def add_sub(self, sid="sub_0", eid="main"):
        sub = FakeSocket(sid=sid, eid=eid)
        self.subs[sid] = sub
        return sub

    def add_source(self, sid="src_0", eid="main"):
        source = FakeSocket(sid=sid, eid=eid)
        self.sources[sid] = source
        return source


class SpyStore(JSONStore):
    """JSONStore that counts backend calls while delegating to the real impl.

    Used to prove the server reaches persistence through the DataStore
    abstraction instead of touching ``env_path`` directly. Every call also
    records the thread it ran on, in ``threads``, which is how a test tells
    disk work handed to the storage executor from disk work still done on the
    IOLoop.
    """

    def __init__(self, env_path):
        super().__init__(env_path)
        self.calls = {
            "list_envs": 0,
            "load_env": [],
            "save_env": [],
            "save_envs": [],
            "save_layouts": [],
            "delete_env": [],
            "load_undo": [],
            "save_undo": [],
            "clear_undo": [],
        }
        self.threads = []

    def _record(self, method, detail=None):
        """Log one backend call: what it was asked for, and from where."""
        if isinstance(self.calls[method], int):
            self.calls[method] += 1
        else:
            self.calls[method].append(detail)
        self.threads.append((method, threading.current_thread().name))

    def list_envs(self):
        self._record("list_envs")
        return super().list_envs()

    def load_env(self, eid):
        self._record("load_env", eid)
        return super().load_env(eid)

    def save_env(self, eid, env_data):
        self._record("save_env", eid)
        return super().save_env(eid, env_data)

    def save_envs(self, state, eids):
        self._record("save_envs", list(eids))
        return super().save_envs(state, eids)

    def save_layouts(self, layouts):
        self._record("save_layouts", layouts)
        return super().save_layouts(layouts)

    def delete_env(self, eid):
        self._record("delete_env", eid)
        return super().delete_env(eid)

    def load_undo(self, eid):
        self._record("load_undo", eid)
        return super().load_undo(eid)

    def save_undo(self, eid, stack):
        self._record("save_undo", eid)
        return super().save_undo(eid, stack)

    def clear_undo(self, eid):
        self._record("clear_undo", eid)
        return super().clear_undo(eid)
