#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import json
import os
import shutil
import socket
import ssl
import subprocess
import uuid
from unittest import mock

import pytest
import tornado.httpclient

from visdom.server import internal, run_server
from visdom.server.app import Application

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration

KEYS = {
    "VISDOM_INTERNAL_READ_KEYS": "read-key",
    "VISDOM_INTERNAL_ADMIN_KEYS": "admin-key",
    "VISDOM_METRICS_TOKENS": "scrape-token",
}


class KeysSetCase(VisdomHTTPTestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, KEYS)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()


class InternalPortCase(KeysSetCase):
    def get_app(self):
        self.visdom = Application(port=self.get_http_port(), env_path=self.env_path)
        return self.visdom.internal_application()

    def tearDown(self):
        self._app = self.visdom
        super().tearDown()

    def signed_get(self, path, key="read-key"):
        return self.fetch(path, headers=internal.signed_headers(key, "GET", path))


class TestTheInternalPort(InternalPortCase):
    def test_a_signed_request_gets_the_activity(self):
        response = self.signed_get("/_activity")

        self.assertEqual(response.code, 200)
        self.assertIn("workspaces", json.loads(response.body))

    def test_an_unsigned_request_is_refused(self):
        for path in ["/_activity", "/_metrics"]:
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path).code, 401)

    def test_the_admin_key_does_not_read(self):
        self.assertEqual(self.signed_get("/_activity", key="admin-key").code, 401)

    def test_metrics_take_a_signature_or_the_token(self):
        by_token = self.fetch(
            "/_metrics", headers={"Authorization": "Bearer scrape-token"}
        )

        self.assertEqual(by_token.code, 200)
        self.assertEqual(self.signed_get("/_metrics").code, 200)

    def signed_post(self, path, body, key):
        raw = json.dumps(body).encode()
        return self.fetch(
            path,
            method="POST",
            body=raw,
            headers=internal.signed_headers(key, "POST", path, raw),
        )

    def test_evicting_needs_the_admin_key(self):
        body = {"workspace_slug": "alpha"}

        self.assertEqual(self.signed_post("/_evict", body, "read-key").code, 401)
        allowed = self.signed_post("/_evict", body, "admin-key")
        self.assertEqual(allowed.code, 200)
        self.assertEqual(
            json.loads(allowed.body), {"workspace_slug": "alpha", "closed": 0}
        )

    def test_retiring_needs_the_admin_key(self):
        body = {"workspace_id": "ws-a", "older_than_days": 7}

        self.assertEqual(self.signed_post("/_retire", body, "read-key").code, 401)
        allowed = self.signed_post("/_retire", body, "admin-key")
        self.assertEqual(allowed.code, 200)
        self.assertEqual(json.loads(allowed.body)["dry_run"], True)

    def test_retiring_refuses_a_bad_request(self):
        for body in [
            {"older_than_days": 7},
            {"workspace_id": "ws-a", "older_than_days": "soon"},
            {"workspace_id": "ws-a", "older_than_days": 0},
            {"workspace_id": "ws-a", "older_than_days": "nan"},
            {"workspace_id": "ws-a", "older_than_days": "inf"},
            {"workspace_id": "../outside", "older_than_days": 7},
        ]:
            with self.subTest(body=body):
                self.assertEqual(
                    self.signed_post("/_retire", body, "admin-key").code, 400
                )

    def test_dropping_needs_the_admin_key(self):
        workspace_id = str(uuid.uuid4())
        os.makedirs(os.path.join(self.env_path, "workspaces", workspace_id))
        body = {"workspace_id": workspace_id}

        self.assertEqual(self.signed_post("/_drop", body, "read-key").code, 401)
        allowed = self.signed_post("/_drop", body, "admin-key")
        self.assertEqual(allowed.code, 200)
        self.assertTrue(json.loads(allowed.body)["removed"])
        self.assertFalse(
            os.path.exists(os.path.join(self.env_path, "workspaces", workspace_id))
        )

    def test_dropping_refuses_an_id_that_is_not_a_workspace(self):
        self.assertEqual(
            self.signed_post("/_drop", {"workspace_id": "../.."}, "admin-key").code,
            400,
        )

    def test_the_rest_of_visdom_is_not_on_this_port(self):
        self.assertEqual(self.fetch("/events", method="POST", body="{}").code, 404)


class TestThePublicPort(KeysSetCase):
    def test_the_internal_endpoints_are_not_served(self):
        for path in ["/_activity", "/_metrics", "/_evict", "/_retire", "/_drop"]:
            with self.subTest(path=path):
                response = self.fetch(
                    path, headers=internal.signed_headers("read-key", "GET", path)
                )

                self.assertNotIn(b"workspaces", response.body)
                self.assertNotIn(b"visdom_workspace", response.body)


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _self_signed(tmp_path):
    cert, key = tmp_path / "internal.crt", tmp_path / "internal.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=visdom-internal",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl")
def test_the_server_serves_the_internal_endpoints_on_their_own_port(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VISDOM_INTERNAL_READ_KEYS", "read-key")
    cert, key = _self_signed(tmp_path)
    pinned = ssl.create_default_context(cafile=str(cert))
    pinned.check_hostname = False
    public, private = _free_port(), _free_port()
    stops = []
    monkeypatch.setattr(run_server, "_install_stop_handlers", stops.append)

    async def serve_and_ask():
        serving = asyncio.ensure_future(
            run_server._serve(
                port=public,
                hostname="localhost",
                base_url="",
                env_path=str(tmp_path),
                readonly=False,
                print_func=lambda port: None,
                user_credential=None,
                use_frontend_client_polling=False,
                bind_local=True,
                eager_data_loading=False,
                ssl_ctx=None,
                save_interval=run_server.DEFAULT_SAVE_INTERVAL,
                save_threshold=run_server.DEFAULT_SAVE_THRESHOLD,
                internal_port=private,
                internal_ssl_ctx=run_server._build_ssl_context(str(cert), str(key)),
            )
        )
        while not stops:
            if serving.done():
                serving.result()
                raise AssertionError("the server stopped before it started")
            await asyncio.sleep(0.01)
        client = tornado.httpclient.AsyncHTTPClient()
        try:
            inside = await client.fetch(
                "https://127.0.0.1:%d/_activity" % private,
                headers=internal.signed_headers("read-key", "GET", "/_activity"),
                ssl_options=pinned,
                raise_error=False,
            )
            try:
                in_the_clear = await client.fetch(
                    "http://127.0.0.1:%d/_activity" % private, raise_error=False
                )
            except (OSError, tornado.httpclient.HTTPClientError):
                in_the_clear = None
            outside = await client.fetch(
                "http://127.0.0.1:%d/_activity" % public, raise_error=False
            )
        finally:
            stops[0].set()
            await serving
        return inside, in_the_clear, outside

    inside, in_the_clear, outside = asyncio.run(serve_and_ask())

    assert inside.code == 200
    assert in_the_clear is None or in_the_clear.code != 200
    assert "workspaces" in json.loads(inside.body)
    assert b"workspaces" not in outside.body
