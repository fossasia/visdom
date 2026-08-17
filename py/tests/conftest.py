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

from unittest.mock import patch

import pytest

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

    With ``send=False`` the client's ``_send`` returns the payload instead of
    performing I/O, so plot methods can be asserted as pure functions.
    """
    import visdom

    return visdom.Visdom(send=False, use_incoming_socket=False)


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
