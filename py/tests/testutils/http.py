#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Base class for tests that drive a real Application over HTTP.

``AsyncHTTPTestCase`` starts the Tornado app in-process on an ephemeral port, so
these stay hermetic: no externally launched server, nothing bound to 8097, and
therefore no ``server`` marker.
"""

import json
import shutil
import tempfile

import tornado.testing

from visdom.server.app import Application


class VisdomHTTPTestCase(tornado.testing.AsyncHTTPTestCase):
    """Application-backed HTTP fixture with a disposable ``env_path``.

    Subclasses override ``app_kwargs`` to vary server configuration (for
    example ``{"readonly": True}``) without reimplementing ``get_app``.
    """

    app_kwargs = {}

    def setUp(self):
        self.env_path = tempfile.mkdtemp(prefix="visdom_test_")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.env_path, ignore_errors=True)

    def get_app(self):
        return Application(
            port=self.get_http_port(), env_path=self.env_path, **self.app_kwargs
        )

    def post_json(self, path, body):
        return self.fetch(
            path,
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    # -- Window helpers -------------------------------------------------------

    def create_window(self, data, eid="main", win=None, opts=None, layout=None):
        """POST to ``/events`` and return the assigned window id."""
        payload = {"data": data, "eid": eid, "layout": {} if layout is None else layout}
        if win is not None:
            payload["win"] = win
        if opts is not None:
            payload["opts"] = opts
        return self.post_json("/events", payload).body.decode()

    def create_text_window(self, eid="main", content="test", win=None, opts=None):
        return self.create_window(
            [{"type": "text", "content": content}], eid=eid, win=win, opts=opts
        )

    def update(self, win, data, eid="main", **extra):
        payload = {"win": win, "eid": eid, "data": data}
        payload.update(extra)
        return self.post_json("/update", payload)

    def close_window(self, win, eid="main"):
        return self.post_json("/close", {"win": win, "eid": eid})

    def win_exists(self, win, eid="main"):
        return self.post_json("/win_exists", {"eid": eid, "win": win}).body == b"true"

    def get_win_data(self, win=None, eid="main"):
        """Raw pane JSON for one window, or the whole env when ``win`` is None."""
        return json.loads(self.post_json("/win_data", {"eid": eid, "win": win}).body)

    # -- Environment helpers --------------------------------------------------

    def get_envs(self):
        return json.loads(self.post_json("/env_state", {}).body)

    def save(self, eids):
        return self.post_json("/save", {"data": eids})

    def panes(self, eid="main"):
        """Live pane dict for ``eid`` straight off the application state."""
        return self._app.state[eid]["jsons"]
