#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Fixtures shared by the whole suite.

Everything here is hermetic: temporary directories only, no listening sockets,
no network. Tests that genuinely need an externally launched visdom must carry
``@pytest.mark.server`` so CI can deselect them.
"""

import asyncio
import types
from concurrent.futures import Future
from unittest.mock import Mock, patch

import pytest
import tornado.ioloop

from visdom.data_model.json_store import JSONStore
from visdom.server.app import Application
from visdom.utils import shared_utils

from testutils.fakes import FakeHandler, FakeSocket, SpyStore


@pytest.fixture
def env_path(tmp_path):
    """Disposable environment directory."""
    return str(tmp_path)


@pytest.fixture
def store(env_path):
    """JSONStore backed by a temporary directory."""
    return JSONStore(env_path)


@pytest.fixture
def spy_store(env_path):
    """JSONStore that records which backend methods the server calls."""
    return SpyStore(env_path)


@pytest.fixture
def app(env_path):
    """Application instance with temporary persistence and no listener.

    The port is only recorded on the instance; nothing binds it, so this is
    safe to construct in parallel with other tests.
    """
    return Application(port=8097, env_path=env_path)


@pytest.fixture
def app_factory(env_path):
    """Build Applications sharing one ``env_path``, for reload assertions."""

    def build(**kwargs):
        kwargs.setdefault("port", 8097)
        kwargs.setdefault("env_path", env_path)
        return Application(**kwargs)

    return build


@pytest.fixture
def inline_executor(monkeypatch):
    """Run ``IOLoop.current().run_in_executor`` calls immediately, in-thread.

    Records ``(func, args)`` so a test can assert what was scheduled as well as
    what it did. A settled ``Future`` is handed back rather than the bare
    result, because that is what the real call returns and callers attach a
    done-callback to it.

    Every path that touches an environment file off the loop -- the autosave
    flush, ``save_all``, the env reads and the deletes -- goes through here, so
    a test that takes this fixture sees the disk settled by the time the call
    it made returns.
    """
    scheduled = []

    def new_future():
        """Hand back the future type the caller can actually wait on.

        Inside a running loop the result is awaited, which needs the loop's own
        future; outside one, a settled ``Future`` is what the real call returns.
        """
        try:
            return asyncio.get_running_loop().create_future()
        except RuntimeError:
            return Future()

    def run_in_executor(_self_executor, func, *args):
        scheduled.append((func, args))
        future = new_future()
        try:
            future.set_result(func(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future

    loop = types.SimpleNamespace(
        run_in_executor=lambda executor, func, *args: run_in_executor(
            executor, func, *args
        )
    )
    monkeypatch.setattr(tornado.ioloop.IOLoop, "current", staticmethod(lambda: loop))
    return scheduled


@pytest.fixture
def fake_socket():
    return FakeSocket()


@pytest.fixture
def handler(env_path):
    """Duck-typed handler with its own empty state and store."""
    return FakeHandler(env_path=env_path)


@pytest.fixture
def app_handler(app):
    """Handler sharing a real Application's state, storage and subscribers."""
    return FakeHandler(
        state=app.state,
        storage=app.storage,
        subs=app.subs,
        sources=app.sources,
        env_path=app.env_path,
    )


@pytest.fixture
def offline_client():
    """Visdom client that never opens a connection.

    The transport is mocked out from construction onwards, so plot methods can
    be asserted as pure functions. ``_handle_post`` is then armed to raise, so a
    call that slips past a test's own patch fails loudly instead of reaching the
    network -- pair this with ``capture_send`` to assert on a payload.
    """
    import visdom

    with (
        patch.object(visdom.Visdom, "_handle_post", return_value=True),
        patch.object(visdom.Visdom, "_start_session_reaper"),
        patch.object(visdom.logger, "warning"),
    ):
        client = visdom.Visdom(use_incoming_socket=False)

    client._handle_post = Mock(
        side_effect=AssertionError("unexpected transport call in unit test")
    )
    return client


@pytest.fixture
def capture_send(offline_client):
    """Run a client call and return the payload it would have transmitted.

    Usage::

        sent = capture_send(lambda v: v.line(Y=[1, 2, 3]))
        assert sent["payload"]["data"][0]["type"] == "scatter"
    """

    def run(call, win_exists=None):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win_capture"

        patches = [patch.object(offline_client, "_send", side_effect=capture)]
        if win_exists is not None:
            patches.append(
                patch.object(offline_client, "win_exists", return_value=win_exists)
            )
        for p in patches:
            p.start()
        try:
            call(offline_client)
        finally:
            for p in reversed(patches):
                p.stop()
        return sent

    return run


@pytest.fixture(autouse=True)
def reset_warn_once():
    """Isolate ``shared_utils.warn_once`` between tests.

    It dedupes against a module-level set, so without this a warning raised by
    an earlier test silently suppresses the same warning in a later one, and
    assertions on it pass or fail depending on execution order.
    """
    previous = set(shared_utils._seen_warnings)
    shared_utils._seen_warnings.clear()
    yield
    shared_utils._seen_warnings.clear()
    shared_utils._seen_warnings.update(previous)
