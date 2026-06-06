"""
Tests for the HTTP polling socket protocol (SocketWrap and VisSocketWrap).
These are the fallback mechanisms when WebSocket is unavailable.
"""

import json
import shutil
import tempfile
import unittest

import tornado.testing

from visdom.server.app import Application
from visdom.server.handlers.socket_handlers import SocketFailureReason


class TestSocketPolling(tornado.testing.AsyncHTTPTestCase):
    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_test_")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def get_app(self):
        return Application(
            port=self.get_http_port(),
            env_path=self._tmp_dir,
            use_frontend_client_polling=True,
        )

    def post_json(self, path, body):
        return self.fetch(
            path,
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def test_socket_wrap_get_creates_socket(self):
        resp = self.fetch("/socket_wrap")
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertTrue(body["success"])
        self.assertIn("sid", body)

    def test_socket_wrap_query_returns_messages(self):
        resp = self.fetch("/socket_wrap")
        sid = json.loads(resp.body)["sid"]
        resp = self.post_json(
            "/socket_wrap",
            {
                "message_type": "query",
                "sid": sid,
            },
        )
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertTrue(body["success"])
        self.assertIsInstance(body["messages"], list)
        has_register = any("register" in str(m) for m in body["messages"])
        self.assertTrue(has_register, "No register message found in socket messages")

    def test_socket_wrap_query_drains_messages(self):
        resp = self.fetch("/socket_wrap")
        sid = json.loads(resp.body)["sid"]
        self.post_json("/socket_wrap", {"message_type": "query", "sid": sid})
        resp = self.post_json("/socket_wrap", {"message_type": "query", "sid": sid})
        body = json.loads(resp.body)
        self.assertTrue(body["success"])
        self.assertEqual(len(body["messages"]), 0)

    def test_socket_wrap_invalid_sid(self):
        resp = self.post_json(
            "/socket_wrap",
            {
                "message_type": "query",
                "sid": "nonexistent_sid",
            },
        )
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertFalse(body["success"])
        self.assertEqual(body["reason"], SocketFailureReason.CONNECTION_CLOSED.value)

    def test_socket_wrap_invalid_message_type(self):
        resp = self.fetch("/socket_wrap")
        sid = json.loads(resp.body)["sid"]
        resp = self.post_json(
            "/socket_wrap",
            {
                "message_type": "invalid_type",
                "sid": sid,
            },
        )
        body = json.loads(resp.body)
        self.assertFalse(body["success"])
        self.assertEqual(body["reason"], SocketFailureReason.INVALID_MESSAGE_TYPE.value)

    def test_socket_wrap_send_without_message(self):
        resp = self.fetch("/socket_wrap")
        sid = json.loads(resp.body)["sid"]
        resp = self.post_json(
            "/socket_wrap",
            {
                "message_type": "send",
                "sid": sid,
            },
        )
        body = json.loads(resp.body)
        self.assertFalse(body["success"])
        self.assertEqual(body["reason"], SocketFailureReason.MISSING_MESSAGE.value)

    def test_vis_socket_wrap_invalid_sid(self):
        resp = self.post_json(
            "/vis_socket_wrap",
            {
                "sid": "nonexistent",
                "message_type": "query",
            },
        )
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertFalse(body["success"])
        self.assertEqual(body["reason"], SocketFailureReason.CONNECTION_CLOSED.value)

    def test_vis_socket_wrap_invalid_message_type(self):
        from unittest.mock import MagicMock

        mock_source = MagicMock()
        sid = "test_vis_sid"
        self._app.sources[sid] = mock_source
        resp = self.post_json(
            "/vis_socket_wrap",
            {
                "sid": sid,
                "message_type": "invalid_type",
            },
        )
        body = json.loads(resp.body)
        self.assertFalse(body["success"])
        self.assertEqual(body["reason"], SocketFailureReason.INVALID_MESSAGE_TYPE.value)

    def test_failure_response_includes_detail(self):
        """Failure responses should include a human-readable 'detail' field."""
        resp = self.post_json(
            "/socket_wrap",
            {
                "message_type": "query",
                "sid": "nonexistent_sid",
            },
        )
        body = json.loads(resp.body)
        self.assertFalse(body["success"])
        self.assertIn("detail", body)
        self.assertIsInstance(body["detail"], str)

    def test_socket_receives_window_creation(self):
        """When a window is created, polling sockets should receive it."""
        resp = self.fetch("/socket_wrap")
        sid = json.loads(resp.body)["sid"]
        self.post_json("/socket_wrap", {"message_type": "query", "sid": sid})

        self.post_json(
            "/events",
            {
                "data": [{"type": "text", "content": "broadcast test"}],
                "eid": "main",
            },
        )

        resp = self.post_json("/socket_wrap", {"message_type": "query", "sid": sid})
        body = json.loads(resp.body)
        self.assertTrue(body["success"])
        has_window = any("broadcast test" in str(m) for m in body["messages"])
        self.assertTrue(has_window, "Socket didn't receive window creation broadcast")

    def test_socket_receives_close_broadcast(self):
        """When a window is closed, polling sockets should receive close command."""
        resp = self.fetch("/socket_wrap")
        sid = json.loads(resp.body)["sid"]
        self.post_json("/socket_wrap", {"message_type": "query", "sid": sid})

        resp = self.post_json(
            "/events",
            {
                "data": [{"type": "text", "content": "close me"}],
                "eid": "main",
            },
        )
        win_id = resp.body.decode()
        self.post_json("/socket_wrap", {"message_type": "query", "sid": sid})
        self.post_json("/close", {"win": win_id, "eid": "main"})

        resp = self.post_json("/socket_wrap", {"message_type": "query", "sid": sid})
        body = json.loads(resp.body)
        has_close = any("close" in str(m) for m in body["messages"])
        self.assertTrue(has_close, "Socket didn't receive close broadcast")


if __name__ == "__main__":
    unittest.main()
