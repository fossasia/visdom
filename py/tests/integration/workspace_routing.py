#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import json
import os
import types
from unittest import mock

import pytest

from visdom.server.app import Application
from visdom.server.handlers.socket_handlers import (
    WS_POLICY_VIOLATION,
    WS_TRY_AGAIN_LATER,
    SocketFailureReason,
    _spawned,
    SocketWrapper,
    VisSocketWrapper,
)
from visdom.server.workspace_manager import WorkspaceAuthError

from testutils.http import VisdomHTTPTestCase
from testutils.sockets import socket_double

pytestmark = pytest.mark.integration

KEYS = {
    ("key-a", "alpha"): ("ws-a", "member"),
    ("key-b", "beta"): ("ws-b", "member"),
    ("key-v", "alpha"): ("ws-a", "viewer"),
}


class Gateway:
    def __init__(self, refusal=None):
        self.refusal = refusal
        self.sessions = []
        self.full = {}

    def resolve(self, api_key, slug):
        if self.refusal is not None:
            raise self.refusal
        if (api_key, slug) not in KEYS:
            raise WorkspaceAuthError(403, "Not a member of this workspace")
        return KEYS[(api_key, slug)]

    def resolve_session(self, token, slug):
        self.sessions.append((token, slug))
        return ("ws-a", "member")

    async def resolve_off_loop(self, method, credential, slug):
        return getattr(self, method)(credential, slug)

    def storage_refusal(self, workspace_id):
        return self.full.get(workspace_id)


def with_gateway(app, gateway):
    app.workspace_manager = gateway
    app.server_state.workspace_manager = gateway
    return app


def windows(state, eid="main"):
    env = state.state.get(eid)
    return {} if env is None else env["jsons"]


class WorkspaceRoutingCase(VisdomHTTPTestCase):
    def get_app(self):
        self.gateway = Gateway()
        return with_gateway(super().get_app(), self.gateway)

    def space(self, workspace_id):
        return self._app.workspace_env_manager.space(workspace_id)

    def write(self, headers, eid="main"):
        body = {"data": [{"content": "hi", "type": "text"}], "eid": eid}
        return self.fetch(
            "/events",
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json", **headers},
        )


class TestRequestsFindTheirWorkspace(WorkspaceRoutingCase):
    def test_a_keyed_write_lands_in_its_workspace(self):
        response = self.write({"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"})

        self.assertEqual(response.code, 200)
        self.assertEqual(len(windows(self.space("ws-a"))), 1)
        self.assertEqual(windows(self._app.server_state), {})

    def test_a_keyed_write_records_the_workspace_slug(self):
        self.write({"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"})

        self.assertEqual(self.space("ws-a").slug, "alpha")

    def test_two_workspaces_keep_the_same_environment_apart(self):
        self.write({"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"})
        self.write({"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"})
        self.write({"X-Visdom-Workspace": "beta", "X-API-KEY": "key-b"})

        self.assertEqual(len(windows(self.space("ws-a"))), 2)
        self.assertEqual(len(windows(self.space("ws-b"))), 1)

    def test_a_request_without_a_workspace_uses_the_servers_own_state(self):
        response = self.write({})

        self.assertEqual(response.code, 200)
        self.assertEqual(len(windows(self._app.server_state)), 1)
        self.assertEqual(self._app.workspace_env_manager.workspace_spaces(), [])

    def test_a_browser_session_resolves_through_its_cookie(self):
        response = self.write(
            {"X-Visdom-Workspace": "alpha", "Cookie": "session_token=browser"}
        )

        self.assertEqual(response.code, 200)
        self.assertEqual(self.gateway.sessions, [("browser", "alpha")])
        self.assertEqual(len(windows(self.space("ws-a"))), 1)

    def test_a_workspace_without_a_credential_is_refused(self):
        response = self.write({"X-Visdom-Workspace": "alpha"})

        self.assertEqual(response.code, 401)
        self.assertEqual(self._app.workspace_env_manager.workspace_spaces(), [])
        self.assertEqual(windows(self._app.server_state), {})


class TestPagesCarryTheWorkspace(WorkspaceRoutingCase):
    def test_every_page_names_its_workspace(self):
        for path in ["/", "/env/main", "/compare/main+main"]:
            with self.subTest(path=path):
                response = self.fetch(
                    path,
                    headers={
                        "X-Visdom-Workspace": "alpha",
                        "Cookie": "session_token=browser",
                    },
                )

                self.assertEqual(response.code, 200)
                self.assertIn(b'"slug": "alpha"', response.body)

    def test_pages_without_a_workspace_leave_the_badge_out(self):
        for path in ["/", "/env/main", "/compare/main+main"]:
            with self.subTest(path=path):
                response = self.fetch(path)

                self.assertEqual(response.code, 200)
                self.assertNotIn(b"VISDOM_CLOUD", response.body)


class TestRequestsAreRefusedAtTheDoor(WorkspaceRoutingCase):
    def test_a_viewer_cannot_write(self):
        response = self.write({"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-v"})

        self.assertEqual(response.code, 403)
        self.assertEqual(windows(self.space("ws-a")), {})

    def post_as(self, api_key, path, body):
        return self.fetch(
            path,
            method="POST",
            body=json.dumps(body),
            headers={
                "Content-Type": "application/json",
                "X-Visdom-Workspace": "alpha",
                "X-API-KEY": api_key,
            },
        )

    def test_a_viewer_cannot_create_an_environment(self):
        response = self.post_as("key-v", "/env/new", {"eid": "new"})

        self.assertEqual(response.code, 403)
        self.assertNotIn("new", self.space("ws-a").state)

    def test_a_viewer_can_load_an_environment_that_exists(self):
        self.space("ws-a").state["old"] = {"jsons": {}, "reload": {}}

        response = self.post_as("key-v", "/env/old", {"eid": "old"})

        self.assertEqual(response.code, 200)

    def test_a_member_can_still_create_an_environment(self):
        response = self.post_as("key-a", "/env/new", {"eid": "new"})

        self.assertEqual(response.code, 200)
        self.assertIn("new", self.space("ws-a").state)

    def test_a_viewer_cannot_change_experiments(self):
        for path, body in [
            ("/experiments/log", {"eid": "main", "name": "run"}),
            ("/experiments/tags", {"action": "set", "eid": "main", "tags": ["a"]}),
            ("/experiments/hparams/update", {"eid": "main", "values": {}}),
        ]:
            with self.subTest(path=path):
                response = self.post_as("key-v", path, body)

                self.assertEqual(response.code, 403)
                self.assertNotIn("experiment", self.space("ws-a").state["main"])
                self.assertEqual(windows(self.space("ws-a")), {})

    def test_a_viewer_can_open_an_environment_named_like_a_write(self):
        self.space("ws-a").state["save"] = {"jsons": {}, "reload": {}}

        response = self.fetch(
            "/env/save",
            headers={"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-v"},
        )

        self.assertEqual(response.code, 200)

    def test_a_viewer_can_still_read(self):
        response = self.post_as("key-v", "/env_state", {})

        self.assertEqual(response.code, 200)

    def test_a_full_workspace_refuses_new_plots_and_says_why(self):
        self.gateway.full["ws-a"] = "out of storage"

        response = self.write({"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"})

        self.assertEqual(response.code, 402)
        self.assertEqual(json.loads(response.body), {"error": "out of storage"})
        self.assertEqual(windows(self.space("ws-a")), {})

    def test_a_full_workspace_refuses_experiment_logs(self):
        self.gateway.full["ws-a"] = "out of storage"

        response = self.post_as("key-a", "/experiments/log", {"eid": "main"})

        self.assertEqual(response.code, 402)
        self.assertEqual(json.loads(response.body), {"error": "out of storage"})

    def test_a_full_workspace_can_still_be_read_and_cleared(self):
        self.space("ws-a").state["old"] = {"jsons": {"w": {}}, "reload": {}}
        self.gateway.full["ws-a"] = "out of storage"

        read = self.post_as("key-a", "/env_state", {})
        closed = self.post_as("key-a", "/close", {"eid": "old", "win": "w"})
        deleted = self.post_as("key-a", "/delete_env", {"eid": "old"})

        self.assertEqual(read.code, 200)
        self.assertEqual(closed.code, 200)
        self.assertEqual(deleted.code, 200)
        self.assertNotIn("old", self.space("ws-a").state)

    def test_a_key_from_another_workspace_gets_the_gateways_answer(self):
        response = self.write({"X-Visdom-Workspace": "beta", "X-API-KEY": "key-a"})

        self.assertEqual(response.code, 403)
        self.assertEqual(
            json.loads(response.body), {"error": "Not a member of this workspace"}
        )
        self.assertEqual(windows(self._app.server_state), {})

    def test_an_unreachable_gateway_is_passed_on_as_such(self):
        self.gateway.refusal = WorkspaceAuthError(503, "workspace resolve unavailable")

        response = self.write({"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"})

        self.assertEqual(response.code, 503)


class TestWithoutAGateway(VisdomHTTPTestCase):
    def test_plain_visdom_ignores_the_workspace_headers(self):
        self.assertIsNone(self._app.workspace_manager)

        body = {"data": [{"content": "hi", "type": "text"}], "eid": "main"}
        response = self.fetch(
            "/events",
            method="POST",
            body=json.dumps(body),
            headers={"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"},
        )

        self.assertEqual(response.code, 200)
        self.assertEqual(len(windows(self._app.server_state)), 1)
        self.assertEqual(self._app.workspace_env_manager.workspace_spaces(), [])


def test_the_gateway_is_used_only_when_one_is_configured(env_path):
    with mock.patch.dict(os.environ, {"VISDOM_GATEWAY_URL": "http://gateway:8085"}):
        configured = Application(port=8097, env_path=env_path)
    with mock.patch.dict(os.environ):
        os.environ.pop("VISDOM_GATEWAY_URL", None)
        plain = Application(port=8097, env_path=env_path)

    assert configured.workspace_manager.gateway_url == "http://gateway:8085"
    assert plain.workspace_manager is None


def keyed_socket(cls, app, headers):
    sock = socket_double(cls, app)
    sock.request = types.SimpleNamespace(
        remote_ip="127.0.0.1", cookies={}, headers=headers
    )
    return sock


@pytest.fixture
def gated_app(app):
    return with_gateway(app, Gateway())


def test_a_viewer_socket_joins_its_workspace(gated_app):
    sub = keyed_socket(
        SocketWrapper, gated_app, {"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"}
    )
    sub.open()

    space = gated_app.workspace_env_manager.space("ws-a")
    assert space.subs[sub.sid] is sub
    assert space.slug == "alpha"
    assert gated_app.subs == {}


def test_a_source_socket_joins_its_workspace(gated_app):
    source = keyed_socket(
        VisSocketWrapper,
        gated_app,
        {"X-Visdom-Workspace": "beta", "X-API-KEY": "key-b"},
    )
    source.open()

    space = gated_app.workspace_env_manager.space("ws-b")
    assert space.sources[source.sid] is source
    assert gated_app.sources == {}


def test_a_refused_socket_is_closed_as_a_policy_violation(gated_app):
    sub = keyed_socket(
        SocketWrapper, gated_app, {"X-Visdom-Workspace": "beta", "X-API-KEY": "key-a"}
    )
    with mock.patch.object(SocketWrapper, "close") as close:
        sub.open()

    close.assert_called_once_with(WS_POLICY_VIOLATION, "Not a member of this workspace")
    assert list(sub.messages) == []
    assert gated_app.subs == {}


def test_a_socket_without_a_credential_is_refused(gated_app):
    sub = keyed_socket(SocketWrapper, gated_app, {"X-Visdom-Workspace": "alpha"})
    with mock.patch.object(SocketWrapper, "close") as close:
        sub.open()

    close.assert_called_once_with(WS_POLICY_VIOLATION, "Sign in to use this workspace.")
    assert gated_app.subs == {}


def test_a_socket_refused_by_an_unreachable_gateway_is_told_to_retry(gated_app):
    gated_app.workspace_manager.refusal = WorkspaceAuthError(503, "unavailable")
    source = keyed_socket(
        VisSocketWrapper,
        gated_app,
        {"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"},
    )
    with mock.patch.object(VisSocketWrapper, "close") as close:
        source.open()

    close.assert_called_once_with(WS_TRY_AGAIN_LATER, "unavailable")
    assert list(source.messages) == []
    assert gated_app.sources == {}


def test_a_long_refusal_fits_in_a_close_frame(gated_app):
    gated_app.workspace_manager.refusal = WorkspaceAuthError(403, "é" * 100)
    source = keyed_socket(
        VisSocketWrapper,
        gated_app,
        {"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"},
    )
    with mock.patch.object(VisSocketWrapper, "close") as close:
        source.open()

    reason = close.call_args.args[1]
    assert len(reason.encode("utf-8")) <= 123
    assert reason == "é" * 61


def test_a_refused_polling_socket_is_not_reported_as_opened(gated_app):
    sub = keyed_socket(SocketWrapper, gated_app, {"X-Visdom-Workspace": "alpha"})
    sub.open()

    assert _spawned(sub) == {
        "success": False,
        "reason": "closed",
        "detail": SocketFailureReason.CONNECTION_CLOSED.detail,
        "message": "Sign in to use this workspace.",
    }


@pytest.mark.parametrize("key, kept", [("key-v", True), ("key-a", False)])
def test_a_viewer_socket_cannot_change_its_workspace(
    gated_app, inline_executor, key, kept
):
    space = gated_app.workspace_env_manager.space("ws-a")
    space.state["doomed"] = {"jsons": {}, "reload": {}}
    sub = keyed_socket(
        SocketWrapper, gated_app, {"X-Visdom-Workspace": "alpha", "X-API-KEY": key}
    )
    sub.open()

    register = json.loads(sub.messages[0])
    asyncio.run(sub.on_message(json.dumps({"cmd": "delete_env", "eid": "doomed"})))

    assert register["readonly"] is kept
    assert ("doomed" in space.state) is kept


@pytest.mark.parametrize("full, copied", [(None, True), ("out of storage", False)])
def test_a_full_workspace_refuses_a_socket_save(
    gated_app, inline_executor, full, copied
):
    gated_app.workspace_manager.full["ws-a"] = full
    space = gated_app.workspace_env_manager.space("ws-a")
    space.state["main"] = {"jsons": {}, "reload": {}}
    sub = keyed_socket(
        SocketWrapper, gated_app, {"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"}
    )
    sub.open()
    sub.messages.clear()

    save = {"cmd": "save", "data": {}, "eid": "copy", "prev_eid": "main"}
    asyncio.run(sub.on_message(json.dumps(save)))

    assert ("copy" in space.state) is copied
    told = [
        json.loads(m)["data"]["message"] for m in sub.messages if "notification" in m
    ]
    assert told == ([] if copied else ["out of storage"])


@pytest.mark.parametrize("full, kept", [(None, True), ("out of storage", False)])
def test_a_full_workspace_refuses_a_socket_layout_save(
    gated_app, inline_executor, full, kept
):
    gated_app.workspace_manager.full["ws-a"] = full
    space = gated_app.workspace_env_manager.space("ws-a")
    before = space.get_layouts()
    sub = keyed_socket(
        SocketWrapper, gated_app, {"X-Visdom-Workspace": "alpha", "X-API-KEY": "key-a"}
    )
    sub.open()
    sub.messages.clear()

    layouts = json.dumps({"main": {"wide": {}}})
    asyncio.run(sub.on_message(json.dumps({"cmd": "save_layouts", "data": layouts})))

    assert space.get_layouts() == (layouts if kept else before)
    told = [
        json.loads(m)["data"]["message"] for m in sub.messages if "notification" in m
    ]
    assert told == ([] if kept else ["out of storage"])
