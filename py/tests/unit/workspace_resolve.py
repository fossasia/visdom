#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import types
from unittest import mock

import pytest
import requests

from visdom.server.workspace_manager import WorkspaceAuthError, WorkspaceManager

pytestmark = pytest.mark.unit


def answer(status, body):
    return types.SimpleNamespace(status_code=status, json=lambda: body)


@pytest.fixture
def gateway():
    with mock.patch("visdom.server.workspace_manager.requests.post") as post:
        yield post


def test_a_key_resolves_to_the_workspace_and_role(gateway):
    gateway.return_value = answer(200, {"workspace_id": "ws-a", "role": "member"})
    manager = WorkspaceManager(gateway_url="http://gateway:8085/")

    assert manager.resolve("key-a", "alpha") == ("ws-a", "member")

    url = gateway.call_args.args[0]
    assert url == "http://gateway:8085/api/v1/visdom/resolve"
    assert gateway.call_args.kwargs["headers"] == {"X-API-KEY": "key-a"}
    assert gateway.call_args.kwargs["json"] == {"workspace_slug": "alpha"}


def test_a_browser_session_resolves_through_its_own_endpoint(gateway):
    gateway.return_value = answer(200, {"workspace_id": "ws-a", "role": "viewer"})
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    assert manager.resolve_session("token", "alpha") == ("ws-a", "viewer")

    assert gateway.call_args.args[0].endswith("/api/v1/visdom/resolve-session")
    assert gateway.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}


def test_a_resolved_caller_is_not_asked_about_again(gateway):
    gateway.return_value = answer(200, {"workspace_id": "ws-a", "role": "member"})
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    manager.resolve("key-a", "alpha")
    manager.resolve("key-a", "alpha")

    assert gateway.call_count == 1


def test_the_cache_is_per_key_and_workspace(gateway):
    gateway.return_value = answer(200, {"workspace_id": "ws-a", "role": "member"})
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    manager.resolve("key-a", "alpha")
    manager.resolve("key-a", "beta")
    manager.resolve("key-b", "alpha")

    assert gateway.call_count == 3


def test_a_refusal_carries_the_gateways_status_and_reason(gateway):
    gateway.return_value = answer(403, {"detail": "Not a member of this workspace"})
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    with pytest.raises(WorkspaceAuthError) as refused:
        manager.resolve("key-a", "alpha")

    assert refused.value.status_code == 403
    assert refused.value.message == "Not a member of this workspace"


def test_a_refusal_is_remembered_for_a_short_while(gateway):
    gateway.return_value = answer(401, {"detail": "Invalid API key"})
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    for _ in range(3):
        with pytest.raises(WorkspaceAuthError):
            manager.resolve("bad", "alpha")

    assert gateway.call_count == 1


def test_a_remembered_refusal_runs_out(gateway):
    gateway.return_value = answer(401, {"detail": "Invalid API key"})
    manager = WorkspaceManager(gateway_url="http://gateway:8085", error_cache_ttl=0)

    for _ in range(2):
        with pytest.raises(WorkspaceAuthError):
            manager.resolve("bad", "alpha")

    assert gateway.call_count == 2


def test_an_unreachable_gateway_is_a_503(gateway):
    gateway.side_effect = requests.ConnectionError("refused")
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    with pytest.raises(WorkspaceAuthError) as refused:
        manager.resolve("key-a", "alpha")

    assert refused.value.status_code == 503
