"""Tests for the experiment suggest stub (Layer 2, PR 6).

``/experiments/suggest`` is a reserved endpoint: the suggestion strategy
(Optuna-backed) lands in a later layer, so for now the server replies
``501 Not Implemented`` with a JSON stub. These tests pin that contract from
both ends — the endpoint through a real
:class:`~visdom.server.app.Application` with Tornado's ``AsyncHTTPTestCase``,
and the ``Visdom.suggest_experiment`` message shape with the transport mocked
(no server) — so the surface stays stable until the strategy is wired in.
"""

import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import tornado.testing

from visdom import Visdom
from visdom.server.app import Application


class TestSuggestEndpoint(tornado.testing.AsyncHTTPTestCase):
    """POST /experiments/suggest is a 501 stub with a JSON body."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_suggest_api_")
        super().setUp()

    def get_app(self):
        return Application(port=self.get_http_port(), env_path=self._tmp_dir)

    def suggest(self, body):
        return self.fetch(
            "/experiments/suggest",
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def test_stub_returns_501(self):
        """The reserved endpoint reports that it is not implemented."""
        self.assertEqual(self.suggest({}).code, 501)

    def test_stub_body_is_json_not_implemented(self):
        """The body is a decodable stub a caller can recognise as such."""
        body = json.loads(self.suggest({}).body)
        self.assertEqual(body["status"], "not_implemented")
        self.assertIsNone(body["suggestion"])
        self.assertIn("detail", body)

    def test_params_body_is_accepted_and_ignored(self):
        """A search space in the body is parsed without error, then ignored."""
        resp = self.suggest({"eid": "run-a", "params": {"lr": [0.1, 0.01]}})
        self.assertEqual(resp.code, 501)
        self.assertIsNone(json.loads(resp.body)["suggestion"])


class TestSuggestClientMessage(unittest.TestCase):
    """Visdom.suggest_experiment builds the message the endpoint expects.

    The transport is mocked to return the ``(msg, endpoint)`` it would have
    posted, stamping a default ``eid`` the way the real ``_send`` does.
    """

    def setUp(self):
        with (
            patch.object(Visdom, "_handle_post", return_value=True),
            patch.object(Visdom, "_start_session_reaper"),
        ):
            self.vis = Visdom(raise_exceptions=True, use_incoming_socket=False)

        def capture(msg, endpoint="events", **_):
            if msg.get("eid") is None:
                msg["eid"] = self.vis.env
            return msg, endpoint

        self.vis._send = Mock(side_effect=capture)

    def test_suggest_message_shape(self):
        """The message posts to the suggest endpoint and carries params.

        ``_send`` stamps an ``eid`` on every message; the stub ignores it.
        """
        msg, endpoint = self.vis.suggest_experiment()
        self.assertEqual(endpoint, "experiments/suggest")
        self.assertIsNone(msg["params"])
        self.assertIn("eid", msg)

    def test_params_are_passed_through(self):
        """The search space rides along untouched for the eventual strategy."""
        msg, _ = self.vis.suggest_experiment(params={"lr": [0.1, 0.01]})
        self.assertEqual(msg["params"], {"lr": [0.1, 0.01]})

    def test_env_overrides_the_target_eid(self):
        """An explicit env names the study to suggest against."""
        msg, _ = self.vis.suggest_experiment(env="run-x")
        self.assertEqual(msg["eid"], "run-x")

    def test_client_rejects_bad_params(self):
        """The client type-checks before any request is made."""
        with self.assertRaises(TypeError):
            self.vis.suggest_experiment(params="lr")


if __name__ == "__main__":
    unittest.main()
