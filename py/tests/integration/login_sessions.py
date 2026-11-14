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

import hashlib
import os
from unittest.mock import patch

import pytest
import tornado.web

from visdom.server import app as app_module
from visdom.server.app import Application
from visdom.utils.server_utils import hash_password

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration

USERNAME = "visdom_user"
COOKIE_SECRET = "test_cookie_secret"
OLD_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a different password entirely"


def credential(password):
    """What ``run_server`` builds: a freshly salted hash plus the client hash."""
    client_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return {
        "username": USERNAME,
        "password": hash_password(client_hash),
        "client_hash": client_hash,
    }


class TestLoginSessions(VisdomHTTPTestCase):
    def build_app(self, password):
        with open(os.path.join(self.env_path, "COOKIE_SECRET"), "w") as secret_file:
            secret_file.write(COOKIE_SECRET)
        with patch.object(app_module, "DEFAULT_ENV_PATH", self.env_path + os.sep):
            return Application(
                port=self.get_http_port(),
                env_path=self.env_path,
                user_credential=credential(password),
            )

    def get_app(self):
        return self.build_app(OLD_PASSWORD)

    def restart_with(self, password):
        """Serve a new Application, as restarting ``visdom`` would."""
        old = self._app
        old.server_state.stop_socket_monitor()
        old.server_state.stop_autosave()
        old.server_state.storage_executor.shutdown(wait=True)
        self._app = self.build_app(password)
        self.http_server.request_callback = self._app

    def login(self, password):
        client_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        resp = self.post_json("/", {"username": USERNAME, "password": client_hash})
        self.assertEqual(resp.code, 200)
        cookies = resp.headers.get_list("Set-Cookie")
        return "; ".join(c.split(";")[0] for c in cookies)

    def read_envs(self, cookie):
        return self.fetch(
            "/env_state", method="POST", body="{}", headers={"Cookie": cookie}
        )

    def test_cookie_carries_no_password_hash(self):
        cookie = self.login(OLD_PASSWORD)
        signed = cookie.split("=", 1)[1].strip('"')
        value = tornado.web.decode_signed_value(
            COOKIE_SECRET, "user_password", signed
        ).decode()
        self.assertNotIn(self._app.user_credential["password"], value)
        self.assertNotIn(credential(OLD_PASSWORD)["client_hash"], value)
        self.assertNotIn("$", value)

    def test_session_survives_a_restart_with_the_same_password(self):
        cookie = self.login(OLD_PASSWORD)
        # The stored hash gets a new salt on every start; the session must not
        # depend on it.
        self.restart_with(OLD_PASSWORD)
        self.assertEqual(self.read_envs(cookie).code, 200)

    def test_changing_the_password_ends_existing_sessions(self):
        cookie = self.login(OLD_PASSWORD)
        self.restart_with(NEW_PASSWORD)
        self.assertEqual(self.read_envs(cookie).code, 401)

    def test_the_new_password_logs_in_after_a_change(self):
        self.restart_with(NEW_PASSWORD)
        self.assertEqual(self.read_envs(self.login(NEW_PASSWORD)).code, 200)

    def test_the_server_does_not_keep_the_client_hash(self):
        # It is what the browser sends to log in, so holding it would hold a
        # working password.
        self.assertNotIn("client_hash", self._app.user_credential)
