"""
Tests that the server routes persistence through ``Application.storage``
(the DataStore backend) rather than calling ``serialize_env`` directly.

These guard the PR-#2 wiring: end-to-end save/fork/reload behavior is already
covered in ``test_environment_lifecycle``; here we assert the abstraction itself
is in place so a future refactor cannot silently bypass the backend.
"""

import json
import tempfile
import unittest

import tornado.testing

from visdom.data_model.base import DataStore
from visdom.data_model.json_store import JSONStore
from visdom.server.app import Application


class TestStorageWiring(tornado.testing.AsyncHTTPTestCase):
    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_wire_")
        super().setUp()

    def get_app(self):
        return Application(port=self.get_http_port(), env_path=self._tmp_dir)

    def post_json(self, path, body):
        return self.fetch(
            path,
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def test_application_has_json_store(self):
        self.assertIsInstance(self._app.storage, DataStore)
        self.assertIsInstance(self._app.storage, JSONStore)
        self.assertEqual(self._app.storage.env_path, self._tmp_dir)

    def test_save_routes_through_storage(self):
        calls = []
        real_save_envs = self._app.storage.save_envs

        def spy(state, eids):
            calls.append(list(eids))
            return real_save_envs(state, eids)

        self._app.storage.save_envs = spy

        resp = self.post_json("/save", {"data": ["main"]})

        self.assertEqual(len(calls), 1)
        self.assertIn("main", calls[0])
        self.assertIn("main", json.loads(resp.body))


if __name__ == "__main__":
    unittest.main()
