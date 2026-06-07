"""
Tests for authentication flow: login, cookie, protected endpoints.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

import tornado.testing

from visdom.server.app import Application
from visdom.utils.server_utils import hash_password


class TestNoAuth(tornado.testing.AsyncHTTPTestCase):
    """Tests when authentication is disabled (default)."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_test_")
        super().setUp()

    def get_app(self):
        return Application(port=self.get_http_port(), env_path=self._tmp_dir)

    def test_index_without_auth_returns_200(self):
        resp = self.fetch("/")
        self.assertEqual(resp.code, 200)

    def test_health_returns_200(self):
        resp = self.fetch("/health")
        self.assertEqual(resp.code, 200)

    def test_events_accessible_without_auth(self):
        resp = self.fetch(
            "/events",
            method="POST",
            body=json.dumps({"data": [{"type": "text", "content": "hi"}], "eid": "main"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 200)


class TestWithAuth(tornado.testing.AsyncHTTPTestCase):
    """Tests when authentication is enabled."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_test_")
        self._cookie_secret = "test_secret_key_12345"
        cookie_path = os.path.join(self._tmp_dir, "COOKIE_SECRET")
        with open(cookie_path, "w") as f:
            f.write(self._cookie_secret)
        super().setUp()

    def get_app(self):
        with mock.patch("visdom.server.app.DEFAULT_ENV_PATH", self._tmp_dir + "/"):
            app = Application(
                port=self.get_http_port(),
                env_path=self._tmp_dir,
                user_credential={
                    "username": "admin",
                    "password": hash_password("admin123"),
                },
            )
        return app

    def post_json(self, path, body, **kwargs):
        return self.fetch(
            path,
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
            **kwargs,
        )

    def test_login_success_sets_cookie(self):
        resp = self.post_json("/", {
            "username": "admin",
            "password": "admin123",
        })
        self.assertEqual(resp.code, 200)
        set_cookie = resp.headers.get("Set-Cookie", "")
        self.assertIn("user_password", set_cookie)

    def test_login_failure_returns_400(self):
        resp = self.post_json("/", {
            "username": "admin",
            "password": "wrong_password",
        })
        self.assertEqual(resp.code, 400)

    def test_login_wrong_username_returns_400(self):
        resp = self.post_json("/", {
            "username": "wrong_user",
            "password": "admin123",
        })
        self.assertEqual(resp.code, 400)

    def test_events_blocked_without_auth(self):
        resp = self.post_json("/events", {
            "data": [{"type": "text", "content": "hi"}],
            "eid": "main",
        })
        self.assertEqual(resp.code, 401)

    def test_env_state_blocked_without_auth(self):
        resp = self.post_json("/env_state", {})
        self.assertEqual(resp.code, 401)

    def test_win_exists_blocked_without_auth(self):
        resp = self.post_json("/win_exists", {"win": "x", "eid": "main"})
        self.assertEqual(resp.code, 401)

    def test_save_blocked_without_auth(self):
        resp = self.post_json("/save", {"data": ["main"]})
        self.assertEqual(resp.code, 401)

    def test_close_blocked_without_auth(self):
        resp = self.post_json("/close", {"win": None, "eid": "main"})
        self.assertEqual(resp.code, 401)

    def test_delete_env_blocked_without_auth(self):
        resp = self.post_json("/delete_env", {"eid": "test"})
        self.assertEqual(resp.code, 401)

    def test_fork_env_blocked_without_auth(self):
        resp = self.post_json("/fork_env", {"prev_eid": "main", "eid": "fork"})
        self.assertEqual(resp.code, 401)

    def test_win_data_blocked_without_auth(self):
        resp = self.post_json("/win_data", {"eid": "main", "win": None})
        self.assertEqual(resp.code, 401)

    def test_health_not_protected(self):
        resp = self.fetch("/health")
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["status"], "ok")

    def test_user_style_css_not_protected(self):
        resp = self.fetch("/user/style.css")
        self.assertEqual(resp.code, 200)

    def test_authenticated_access_works(self):
        resp = self.post_json("/", {
            "username": "admin",
            "password": "admin123",
        }, follow_redirects=False)
        self.assertEqual(resp.code, 200)

        cookie = resp.headers.get("Set-Cookie", "")
        self.assertIn("user_password", cookie)

        resp = self.fetch(
            "/env_state",
            method="POST",
            body=json.dumps({}),
            headers={
                "Content-Type": "application/json",
                "Cookie": cookie.split(";")[0],
            },
        )
        self.assertEqual(resp.code, 200)
        envs = json.loads(resp.body)
        self.assertIn("main", envs)


if __name__ == "__main__":
    unittest.main()
