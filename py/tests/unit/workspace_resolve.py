#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import threading
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


def test_a_full_workspace_is_remembered_until_the_gateway_says_otherwise(gateway):
    manager = WorkspaceManager(gateway_url="http://gateway:8085", cache_ttl=0)
    full = {"workspace_id": "ws-a", "role": "member", "storage_full": "out of room"}
    gateway.return_value = answer(200, full)

    manager.resolve("key-a", "alpha")
    assert manager.storage_refusal("ws-a") == "out of room"
    assert manager.storage_refusal("ws-b") is None

    gateway.return_value = answer(200, {"workspace_id": "ws-a", "role": "member"})
    manager.resolve_session("token", "alpha")
    assert manager.storage_refusal("ws-a") is None


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
    gateway.side_effect = requests.ConnectionError(
        "HTTPConnectionPool(host='gateway', port=8085): refused"
    )
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    with pytest.raises(WorkspaceAuthError) as refused:
        manager.resolve("key-a", "alpha")

    assert refused.value.status_code == 503
    assert "gateway" not in refused.value.message
    assert "8085" not in refused.value.message


def unreadable():
    raise ValueError("not json")


@pytest.mark.parametrize(
    "reply",
    [
        types.SimpleNamespace(status_code=200, json=unreadable),
        answer(200, {"role": "member"}),
        answer(200, {"workspace_id": "ws-a"}),
        answer(200, ["ws-a", "member"]),
        answer(200, {"workspace_id": None, "role": "member"}),
        answer(200, {"workspace_id": ["ws-a"], "role": "member"}),
        answer(200, {"workspace_id": "ws-a", "role": None}),
        answer(200, {"workspace_id": "ws-a", "role": ["viewer"]}),
        answer(200, {"workspace_id": "", "role": "member"}),
        answer(200, {"workspace_id": 42, "role": "member"}),
    ],
)
def test_an_unreadable_answer_is_a_remembered_502(gateway, reply):
    gateway.return_value = reply
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    for _ in range(2):
        with pytest.raises(WorkspaceAuthError) as refused:
            manager.resolve("key-a", "alpha")

    assert refused.value.status_code == 502
    assert gateway.call_count == 1


@pytest.mark.parametrize("body", [["denied"], "denied", None, 7, {"detail": ["x"]}])
def test_a_refusal_with_an_odd_body_keeps_the_gateways_status(gateway, body):
    gateway.return_value = answer(403, body)
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    for _ in range(2):
        with pytest.raises(WorkspaceAuthError) as refused:
            manager.resolve("key-a", "alpha")

    assert refused.value.status_code == 403
    assert refused.value.message == "workspace resolution denied"
    assert gateway.call_count == 1


def test_the_caches_stay_within_their_limits(gateway, monkeypatch):
    monkeypatch.setattr("visdom.server.workspace_manager.MAX_CACHE_ENTRIES", 5)
    monkeypatch.setattr("visdom.server.workspace_manager.MAX_ERROR_ENTRIES", 5)
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    gateway.return_value = answer(200, {"workspace_id": "ws-a", "role": "member"})
    for number in range(20):
        manager.resolve("key-%d" % number, "alpha")
    gateway.return_value = answer(401, {"detail": "Invalid API key"})
    for number in range(20):
        with pytest.raises(WorkspaceAuthError):
            manager.resolve("bad-%d" % number, "alpha")

    assert len(manager._cache) <= 5
    assert len(manager._errors) <= 5
    assert any("key-19" in key for key in manager._cache)


def test_a_miss_is_resolved_off_the_calling_thread(gateway):
    seen = []

    def post(*args, **kwargs):
        seen.append(threading.current_thread())
        return answer(200, {"workspace_id": "ws-a", "role": "member"})

    gateway.side_effect = post
    manager = WorkspaceManager(gateway_url="http://gateway:8085")

    found = asyncio.run(manager.resolve_off_loop("resolve", "key-a", "alpha"))
    again = asyncio.run(manager.resolve_off_loop("resolve", "key-a", "alpha"))

    assert found == again == ("ws-a", "member")
    assert seen and seen[0] is not threading.current_thread()
    assert gateway.call_count == 1


def test_a_remembered_refusal_is_raised_without_a_thread(gateway):
    gateway.return_value = answer(403, {"detail": "Not a member"})
    manager = WorkspaceManager(gateway_url="http://gateway:8085")
    with pytest.raises(WorkspaceAuthError):
        manager.resolve_session("token", "alpha")

    with pytest.raises(WorkspaceAuthError) as refused:
        asyncio.run(manager.resolve_off_loop("resolve_session", "token", "alpha"))

    assert refused.value.status_code == 403
    assert gateway.call_count == 1
