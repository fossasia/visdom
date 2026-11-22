#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""What a login session is tied to, and what ends it.

A session cookie is only signed, not encrypted, so anyone who sees it can
read it, and a valid signature alone used to be enough to stay logged in. The
cookie now carries a token derived from the current credential: it survives a
restart with the same password, stops working once the password changes, and
holds nothing that could be cracked back into the password.
"""

import json
import os
from unittest.mock import patch

import pytest
import tornado.web

from visdom.server import app as app_module
from visdom.server.app import Application
from visdom.utils.server_utils import hash_password, session_token

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration

USERNAME = "visdom_user"
SIGNING_VALUE = "test_signing_value"
# What the browser sends to log in: the SHA-256 of the password typed. Fixed
# values stand in for two different passwords, so no password is hashed here.
OLD_LOGIN = "c4bbcb1fbec99d65bf59d85c8cb62ee2db963f0fe106f483d9afa73bd4e39a8a"
NEW_LOGIN = "14dff91a22df24671c8fcf49b3fa0a9b3773bdf1802b7a3d91623f8d71b94f44"


def credential(client_hash):
    """What ``run_server`` builds: a freshly salted hash plus the client hash."""
    return {
        "username": USERNAME,
        "password": hash_password(client_hash),
        "client_hash": client_hash,
    }


class TestLoginSessions(VisdomHTTPTestCase):
    def build_app(self, password):
        with open(os.path.join(self.env_path, "COOKIE_SECRET"), "w") as fn:
            fn.write(SIGNING_VALUE)
        with patch.object(app_module, "DEFAULT_ENV_PATH", self.env_path + os.sep):
            return Application(
                port=self.get_http_port(),
                env_path=self.env_path,
                user_credential=credential(password),
            )

    def get_app(self):
        return self.build_app(OLD_LOGIN)

    def restart_with(self, password):
        """Serve a new Application, as restarting ``visdom`` would."""
        old = self._app
        old.server_state.stop_socket_monitor()
        old.server_state.stop_autosave()
        old.server_state.storage_executor.shutdown(wait=True)
        self._app = self.build_app(password)
        self.http_server.request_callback = self._app

    def login(self, client_hash):
        resp = self.post_json("/", {"username": USERNAME, "password": client_hash})
        self.assertEqual(resp.code, 200)
        cookies = resp.headers.get_list("Set-Cookie")
        return "; ".join(c.split(";")[0] for c in cookies)

    def read_envs(self, cookie):
        return self.fetch(
            "/env_state", method="POST", body="{}", headers={"Cookie": cookie}
        )

    def test_cookie_carries_no_password_hash(self):
        cookie = self.login(OLD_LOGIN)
        signed = cookie.split("=", 1)[1].strip('"')
        value = tornado.web.decode_signed_value(
            SIGNING_VALUE, "user_password", signed
        ).decode()
        self.assertNotIn(self._app.user_credential["password"], value)
        self.assertNotIn(OLD_LOGIN, value)
        self.assertNotIn("$", value)

    def test_cookie_is_hidden_from_scripts_and_other_sites(self):
        resp = self.post_json("/", {"username": USERNAME, "password": OLD_LOGIN})
        (set_cookie,) = resp.headers.get_list("Set-Cookie")
        self.assertIn("httponly", set_cookie.lower())
        self.assertIn("samesite=lax", set_cookie.lower())

    def test_cookie_is_secure_when_reached_over_https(self):
        body = json.dumps({"username": USERNAME, "password": OLD_LOGIN})
        plain = self.fetch("/", method="POST", body=body)
        (set_cookie,) = plain.headers.get_list("Set-Cookie")
        self.assertNotIn("; secure", set_cookie.lower())
        tls = self.fetch(
            "/", method="POST", body=body, headers={"X-Forwarded-Proto": "https"}
        )
        (set_cookie,) = tls.headers.get_list("Set-Cookie")
        self.assertIn("; secure", set_cookie.lower())

    def test_without_client_hash_the_token_ignores_the_stored_hash(self):
        stored = {"username": USERNAME, "password": hash_password("x")}
        self.assertNotEqual(
            session_token(SIGNING_VALUE, stored), session_token(SIGNING_VALUE, stored)
        )

    def test_session_survives_a_restart_with_the_same_password(self):
        cookie = self.login(OLD_LOGIN)
        # The stored hash gets a new salt on every start; the session must not
        # depend on it.
        self.restart_with(OLD_LOGIN)
        self.assertEqual(self.read_envs(cookie).code, 200)

    def test_changing_the_password_ends_existing_sessions(self):
        cookie = self.login(OLD_LOGIN)
        self.restart_with(NEW_LOGIN)
        self.assertEqual(self.read_envs(cookie).code, 401)

    def test_the_new_password_logs_in_after_a_change(self):
        self.restart_with(NEW_LOGIN)
        self.assertEqual(self.read_envs(self.login(NEW_LOGIN)).code, 200)

    def test_the_server_does_not_keep_the_client_hash(self):
        # It is what the browser sends to log in, so holding it would hold a
        # working password.
        self.assertNotIn("client_hash", self._app.user_credential)
