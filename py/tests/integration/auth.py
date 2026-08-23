#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Who may talk to the server, and what they may ask it to do.

Two independent gates, both off by default:

* ``-enable_login`` makes the server issue a signed ``user_password`` cookie
  from ``IndexHandler.post`` and refuse every ``@check_auth`` route without
  one. The browser sends ``sha256(password)``, never the password itself, and
  the server stores ``hash_password`` of that.
* ``-readonly`` leaves reads alone and refuses writes, over sockets and now
  over HTTP too.

A login-enabled ``Application`` reads its cookie secret from
``DEFAULT_ENV_PATH``, which is the developer's real ``~/.visdom``. Every
fixture here points that at a temporary directory first, so nothing touches a
real installation.
"""

import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

import pytest

from visdom.server import app as app_module
from visdom.server.app import Application
from visdom.server.handlers import web_handlers
from visdom.server.handlers.socket_handlers import SocketWrapper, VisSocketWrapper
from visdom.utils.server_utils import hash_password

from testutils import socket_double
from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration

USERNAME = "visdom_user"
PASSWORD = "correct horse battery staple"
# What the login page actually posts: sjcl.hash.sha256 of the typed password.
CLIENT_HASH = hashlib.sha256(PASSWORD.encode("utf-8")).hexdigest()
COOKIE_SECRET = "test_cookie_secret"

CREDENTIAL = {"username": USERNAME, "password": hash_password(CLIENT_HASH)}


class LoginTestCase(VisdomHTTPTestCase):
    """Server started the way ``visdom -enable_login`` starts it."""

    app_kwargs = {"user_credential": CREDENTIAL}

    def get_app(self):
        with open(os.path.join(self.env_path, "COOKIE_SECRET"), "w") as secret_file:
            secret_file.write(COOKIE_SECRET)
        # Application reads DEFAULT_ENV_PATH + "COOKIE_SECRET" at construction
        # and never again, so the patch only has to span the build.
        with patch.object(app_module, "DEFAULT_ENV_PATH", self.env_path + os.sep):
            return super().get_app()

    def login(self, username=USERNAME, password=CLIENT_HASH):
        return self.fetch(
            "/",
            method="POST",
            body=json.dumps({"username": username, "password": password}),
            headers={"Content-Type": "application/json"},
        )

    def session_headers(self):
        """Headers carrying the cookie a successful login just issued."""
        resp = self.login()
        self.assertEqual(resp.code, 200)
        cookies = resp.headers.get_list("Set-Cookie")
        self.assertTrue(cookies, "login issued no cookie")
        return {
            "Cookie": "; ".join(c.split(";")[0] for c in cookies),
            "Content-Type": "application/json",
        }

    def post_as_user(self, path, body):
        return self.fetch(
            path, method="POST", body=json.dumps(body), headers=self.session_headers()
        )


# -- The login page and its form ---------------------------------------------


class TestLoginPage(LoginTestCase):
    def test_the_root_serves_the_login_page_to_a_stranger(self):
        resp = self.fetch("/")

        self.assertEqual(resp.code, 200)
        self.assertIn("Visdom Login", resp.body.decode())

    def test_the_dashboard_is_not_served_to_a_stranger(self):
        self.assertNotIn("visdom-container", self.fetch("/").body.decode())

    def test_the_dashboard_is_served_once_logged_in(self):
        resp = self.fetch("/", headers=self.session_headers())

        self.assertEqual(resp.code, 200)
        self.assertNotIn("Visdom Login", resp.body.decode())


class TestLoginCredentials(LoginTestCase):
    def test_the_right_credentials_are_accepted(self):
        self.assertEqual(self.login().code, 200)

    def test_the_right_credentials_issue_a_cookie(self):
        cookies = self.login().headers.get_list("Set-Cookie")

        self.assertTrue(any("user_password" in c for c in cookies))

    def _assert_rejected(self, resp):
        self.assertEqual(resp.code, 400)
        self.assertEqual(resp.headers.get_list("Set-Cookie"), [])

    def test_a_wrong_password_is_rejected(self):
        self._assert_rejected(self.login(password=hashlib.sha256(b"nope").hexdigest()))

    def test_a_wrong_username_is_rejected(self):
        self._assert_rejected(self.login(username="somebody_else"))

    def test_the_raw_password_is_not_the_password(self):
        """The server only ever sees the client-side sha256."""
        self._assert_rejected(self.login(password=PASSWORD))

    def test_an_empty_password_is_rejected(self):
        self._assert_rejected(self.login(password=""))

    def test_both_halves_are_always_compared(self):
        """A wrong username must still cost a password comparison.

        The regression: ``==`` short-circuited, so a bad username skipped the
        second check entirely and the response came back measurably sooner.
        """
        with patch.object(
            web_handlers.hmac, "compare_digest", wraps=hmac.compare_digest
        ) as compare:
            self.login(username="somebody_else")

        self.assertEqual(compare.call_count, 2)

    def test_the_stored_credential_is_not_the_client_hash(self):
        """What is kept in memory is salted and derived, not the wire value."""
        stored = CREDENTIAL["password"]

        self.assertNotIn(CLIENT_HASH, stored)
        self.assertEqual(len(stored.split("$")), 2)


# -- Authorization on the routes ---------------------------------------------


class TestUnauthenticatedRequests(LoginTestCase):
    """``@check_auth`` answers 401 and does nothing else."""

    def _assert_401(self, path, body):
        resp = self.post_json(path, body)
        self.assertEqual(resp.code, 401, path)
        return resp

    def test_creating_a_window_is_unauthorized(self):
        self._assert_401(
            "/events", {"eid": "main", "data": [{"type": "text", "content": "hi"}]}
        )
        self.assertEqual(self.panes(), {})

    def test_updating_a_window_is_unauthorized(self):
        self._assert_401(
            "/update", {"eid": "main", "win": "w", "data": [{"content": "hi"}]}
        )

    def test_closing_a_window_is_unauthorized(self):
        self._assert_401("/close", {"eid": "main", "win": "w"})

    def test_deleting_an_environment_is_unauthorized(self):
        self._app.state["expt"] = {"jsons": {}, "reload": {}}

        self._assert_401("/delete_env", {"eid": "expt"})

        self.assertIn("expt", self._app.state)

    def test_saving_is_unauthorized(self):
        self._assert_401("/save", {"data": ["main"]})

    def test_forking_is_unauthorized(self):
        self._assert_401("/fork_env", {"prev_eid": "main", "eid": "copy"})
        self.assertNotIn("copy", self._app.state)

    def test_reading_window_data_is_unauthorized(self):
        self._assert_401("/win_data", {"eid": "main", "win": None})

    def test_asking_whether_a_window_exists_is_unauthorized(self):
        self._assert_401("/win_exists", {"eid": "main", "win": "w"})

    def test_reading_the_environment_list_is_unauthorized(self):
        self._assert_401("/env_state", {})

    def test_logging_an_experiment_is_unauthorized(self):
        self._assert_401("/experiments/log", {"eid": "main", "params": {"lr": 0.1}})

    def test_an_unauthorized_response_carries_no_body(self):
        self.assertEqual(self._assert_401("/env_state", {}).body, b"")


class TestAuthenticatedRequests(LoginTestCase):
    """The same routes, with the cookie the login just issued."""

    def test_a_window_can_be_created(self):
        resp = self.post_as_user(
            "/events", {"eid": "main", "data": [{"type": "text", "content": "hi"}]}
        )

        self.assertEqual(resp.code, 200)
        self.assertIn(resp.body.decode(), self.panes())

    def test_the_environment_list_can_be_read(self):
        resp = self.post_as_user("/env_state", {})

        self.assertEqual(resp.code, 200)
        self.assertEqual(json.loads(resp.body), ["main"])

    def test_a_forged_cookie_is_not_a_session(self):
        resp = self.fetch(
            "/env_state",
            method="POST",
            body="{}",
            headers={"Cookie": "user_password=made_up"},
        )

        self.assertEqual(resp.code, 401)


class TestHealthIsPublic(LoginTestCase):
    def test_health_answers_without_a_session(self):
        """Deliberately unauthenticated: it is what a load balancer polls."""
        resp = self.fetch("/health")

        self.assertEqual(resp.code, 200)
        self.assertEqual(json.loads(resp.body), {"status": "ok"})


class TestAuthDisabledByDefault(VisdomHTTPTestCase):
    def test_no_login_means_no_cookie_is_needed(self):
        self.assertEqual(self.post_json("/env_state", {}).code, 200)

    def test_the_root_serves_the_dashboard(self):
        self.assertNotIn("Visdom Login", self.fetch("/").body.decode())


# -- Sockets under login -----------------------------------------------------


@pytest.fixture
def login_app(env_path, monkeypatch):
    """Login-enabled Application whose cookie secret lives in ``env_path``."""
    with open(os.path.join(env_path, "COOKIE_SECRET"), "w") as secret_file:
        secret_file.write(COOKIE_SECRET)
    monkeypatch.setattr(app_module, "DEFAULT_ENV_PATH", env_path + os.sep)
    return Application(port=8097, env_path=env_path, user_credential=CREDENTIAL)


def test_login_is_enabled_by_supplying_a_credential(login_app):
    assert login_app.login_enabled is True


def test_an_unauthenticated_subscriber_socket_is_closed(login_app):
    """``open`` closes before registering, so the socket never joins subs."""
    sub = socket_double(SocketWrapper, login_app)

    sub.open()

    assert login_app.subs == {}
    assert list(sub.messages) == []


def test_an_unauthenticated_source_socket_is_closed(login_app):
    source = socket_double(VisSocketWrapper, login_app)

    source.open()

    assert login_app.sources == {}
    assert list(source.messages) == []


def test_a_socket_opens_when_login_is_disabled(app):
    """The same double registers fine against a server without login."""
    sub = socket_double(SocketWrapper, app)

    sub.open()

    assert list(app.subs) == [sub.sid]


# -- Readonly enforcement ----------------------------------------------------


class TestReadonlyRejectsWrites(VisdomHTTPTestCase):
    """Every mutating route answers 403 and changes nothing."""

    app_kwargs = {"readonly": True}

    def _assert_403(self, path, body):
        resp = self.post_json(path, body)
        self.assertEqual(resp.code, 403, path)
        self.assertFalse(json.loads(resp.body)["success"])
        self.assertIn("readonly", json.loads(resp.body)["error"])
        return resp

    def _seed(self, eid="main"):
        """Put a pane in state directly, since /events is refused here."""
        self._app.state.setdefault(eid, {"jsons": {}, "reload": {}})
        self._app.state[eid]["jsons"]["win_seed"] = {
            "id": "win_seed",
            "type": "text",
            "content": "seeded",
            "i": 0,
            "version": 1,
        }
        return "win_seed"

    def test_creating_a_window_is_refused(self):
        self._assert_403(
            "/events", {"eid": "main", "data": [{"type": "text", "content": "hi"}]}
        )

        self.assertEqual(self.panes(), {})

    def test_updating_a_window_is_refused(self):
        win = self._seed()

        self._assert_403(
            "/update",
            {"eid": "main", "win": win, "data": [{"type": "text", "content": "new"}]},
        )

        self.assertEqual(self.panes()[win]["content"], "seeded")

    def test_closing_a_window_is_refused(self):
        win = self._seed()

        self._assert_403("/close", {"eid": "main", "win": win})

        self.assertIn(win, self.panes())

    def test_deleting_an_environment_is_refused(self):
        self._app.state["expt"] = {"jsons": {}, "reload": {}}

        self._assert_403("/delete_env", {"eid": "expt"})

        self.assertIn("expt", self._app.state)

    def test_saving_is_refused(self):
        """The pane held in memory never reaches the env file on disk.

        ``main.json`` itself exists either way — ``load_state`` writes it at
        startup, before any request has been served — so the assertion is on
        its contents.
        """
        self._seed()

        self._assert_403("/save", {"data": ["main"]})

        with open(os.path.join(self.env_path, "main.json")) as env_file:
            self.assertEqual(json.load(env_file)["jsons"], {})

    def test_forking_is_refused(self):
        self._assert_403("/fork_env", {"prev_eid": "main", "eid": "copy"})

        self.assertNotIn("copy", self._app.state)

    def test_pushing_window_data_is_refused(self):
        """The write behind /win_data, which also serves reads."""
        self._assert_403(
            "/win_data", {"eid": "main", "win": None, "data": json.dumps({})}
        )

    def test_uploading_an_environment_is_refused(self):
        resp = self.post_json("/upload_env", {})

        self.assertEqual(resp.code, 403)
        self.assertFalse(json.loads(resp.body)["success"])

    def test_logging_an_experiment_is_refused(self):
        resp = self.post_json("/experiments/log", {"eid": "main", "params": {"a": 1}})

        self.assertEqual(resp.code, 403)


class TestReadonlyAllowsReads(VisdomHTTPTestCase):
    app_kwargs = {"readonly": True}

    def test_the_environment_list_is_served(self):
        resp = self.post_json("/env_state", {})

        self.assertEqual(resp.code, 200)
        self.assertEqual(json.loads(resp.body), ["main"])

    def test_window_data_is_served(self):
        resp = self.post_json("/win_data", {"eid": "main", "win": None})

        self.assertEqual(resp.code, 200)
        self.assertEqual(json.loads(resp.body), {})

    def test_window_existence_is_answered(self):
        resp = self.post_json("/win_exists", {"eid": "main", "win": "nope"})

        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body, b"false")

    def test_the_environment_page_renders(self):
        self.assertEqual(self.fetch("/env/main").code, 200)

    def test_health_is_served(self):
        self.assertEqual(self.fetch("/health").code, 200)


class TestWritesSurviveWithoutReadonly(VisdomHTTPTestCase):
    """The decorator must not be refusing writes on an ordinary server."""

    def test_every_guarded_route_still_answers_200(self):
        win = self.create_text_window(content="writable")

        self.assertEqual(
            [
                self.update(win, [{"type": "text", "content": "more"}]).code,
                self.post_json("/save", {"data": ["main"]}).code,
                self.post_json("/fork_env", {"prev_eid": "main", "eid": "copy"}).code,
                self.post_json(
                    "/win_data", {"eid": "main", "win": None, "data": json.dumps({})}
                ).code,
                self.close_window(win).code,
                self.post_json("/delete_env", {"eid": "copy"}).code,
            ],
            [200] * 6,
        )


if __name__ == "__main__":
    unittest.main()
