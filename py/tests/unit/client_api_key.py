#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import threading

import pytest

from visdom import Visdom

pytestmark = pytest.mark.unit


def _client(api_key=None, workspace=None):
    client = Visdom.__new__(Visdom)
    client._session_lock = threading.Lock()
    client._session = None
    client._pid = None
    client.proxies = None
    client.ssl_verify = True
    client.username = None
    client.api_key = api_key
    client.workspace = workspace
    return client


def test_the_session_carries_the_key_and_the_workspace():
    headers = _client("visdom_live_abc", "lab").session.headers

    assert headers["X-API-KEY"] == "visdom_live_abc"
    assert headers["X-Visdom-Workspace"] == "lab"


def test_without_a_key_neither_header_is_set():
    headers = _client().session.headers

    assert "X-API-KEY" not in headers
    assert "X-Visdom-Workspace" not in headers


def test_a_key_without_a_workspace_is_refused():
    with pytest.raises(AssertionError, match="workspace is required"):
        Visdom(api_key="visdom_live_abc", offline=True)


def test_a_key_and_a_workspace_are_kept_on_the_client(tmp_path):
    client = Visdom(
        api_key="visdom_live_abc",
        workspace="lab",
        offline=True,
        log_to_filename=str(tmp_path / "log"),
    )

    assert client.api_key == "visdom_live_abc"
    assert client.workspace == "lab"
