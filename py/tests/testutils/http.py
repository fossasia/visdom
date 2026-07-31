#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""In-process HTTP client for tests that drive a real ``Application``.

``AsyncHTTPTestCase`` is a ``unittest.TestCase``, and pytest refuses to inject
fixtures into those. So instead of a base class the server runs on a background
event loop and tests talk to it over real HTTP with ``requests``, which is
already a runtime dependency. No new test dependency, no async test functions.

The ``Application`` must be built and told to listen *inside* the running loop:
constructing it on the worker thread before the loop starts hangs.
"""

import asyncio
import json
import threading

import requests

from visdom.server.app import Application

STARTUP_TIMEOUT = 10


def run_loop_in_thread():
    """Start an asyncio loop on a daemon thread; return ``(loop, stop)``."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run():
        asyncio.set_event_loop(loop)
        loop.call_soon(ready.set)
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(STARTUP_TIMEOUT)

    def stop():
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=STARTUP_TIMEOUT)
        loop.close()

    return loop, stop


class VisdomServer:
    """A listening ``Application`` plus the helpers the old base class had."""

    def __init__(self, loop, env_path, **app_kwargs):
        self._loop = loop

        async def boot():
            app = Application(port=0, env_path=env_path, **app_kwargs)
            server = app.listen(0, address="127.0.0.1")
            port = list(server._sockets.values())[0].getsockname()[1]
            app.port = port
            return app, server, port

        self.app, self._server, self.port = self._call(boot()).result(STARTUP_TIMEOUT)
        self.env_path = env_path
        self.base_url = "http://127.0.0.1:{}".format(self.port)
        self.session = requests.Session()

    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def close(self):
        async def shutdown():
            self._server.stop()

        try:
            self._call(shutdown()).result(STARTUP_TIMEOUT)
        finally:
            self.session.close()

    # -- Raw requests ---------------------------------------------------------

    def get(self, path, **kwargs):
        kwargs.setdefault("timeout", STARTUP_TIMEOUT)
        return self.session.get(self.base_url + path, **kwargs)

    def post_json(self, path, body):
        return self.session.post(
            self.base_url + path,
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
            timeout=STARTUP_TIMEOUT,
        )

    # -- Window helpers -------------------------------------------------------

    def create_window(self, data, eid="main", win=None, opts=None, layout=None):
        """POST to ``/events`` and return the assigned window id."""
        payload = {"data": data, "eid": eid, "layout": {} if layout is None else layout}
        if win is not None:
            payload["win"] = win
        if opts is not None:
            payload["opts"] = opts
        resp = self.post_json("/events", payload)
        assert resp.status_code == 200, resp.text
        return resp.text

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
        return self.post_json("/win_exists", {"eid": eid, "win": win}).text == "true"

    def get_win_data(self, win=None, eid="main"):
        """Raw pane JSON for one window, or the whole env when ``win`` is None."""
        return self.post_json("/win_data", {"eid": eid, "win": win}).json()

    # -- Environment helpers --------------------------------------------------

    def get_envs(self):
        return self.post_json("/env_state", {}).json()

    def save(self, eids):
        return self.post_json("/save", {"data": eids})

    def panes(self, eid="main"):
        """Live pane dict for ``eid`` straight off the application state."""
        return self.app.state[eid]["jsons"]
