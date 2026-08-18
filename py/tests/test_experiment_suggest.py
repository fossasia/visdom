#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the experiment suggest stub.

``/experiments/suggest`` is a reserved endpoint: the suggestion strategy
(Optuna-backed) lands in a later release, so for now the server replies
``501 Not Implemented`` with a JSON stub. These tests pin that contract from
both ends — the endpoint through a real
:class:`~visdom.server.app.Application` with Tornado's ``AsyncHTTPTestCase``,
and the ``Visdom.suggest_experiment`` message shape with a mocked transport (no
server) — so the surface stays stable until the strategy is wired in.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

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
        return self.post_raw(json.dumps(body))

    def post_raw(self, body):
        """POST a body verbatim, so malformed JSON reaches the handler."""
        return self.fetch(
            "/experiments/suggest",
            method="POST",
            body=body,
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

    def test_missing_body_is_still_the_stub(self):
        """The body is optional, so no body at all still reaches the stub."""
        self.assertEqual(self.post_raw("").code, 501)

    def test_malformed_json_is_400(self):
        """A body that is not JSON is the caller's error, not a 500."""
        resp = self.post_raw("{not json")
        self.assertEqual(resp.code, 400)

    def test_non_object_body_is_400(self):
        """A JSON list or scalar carries no search space to read, so reject it."""
        self.assertEqual(self.post_raw("[1, 2]").code, 400)
        self.assertEqual(self.post_raw('"lr"').code, 400)
        self.assertEqual(self.post_raw("null").code, 400)


class TestSuggestClientMessage(unittest.TestCase):
    """Visdom.suggest_experiment builds the message the endpoint expects.

    Only the transport under ``_send`` is mocked, so the message asserted on is
    the one that would have gone over the wire, ``eid`` defaulting included.
    """

    def setUp(self):
        with (
            patch.object(Visdom, "_handle_post", return_value=True),
            patch.object(Visdom, "_start_session_reaper"),
        ):
            self.vis = Visdom(raise_exceptions=True, use_incoming_socket=False)

    def suggest(self, **kwargs):
        """Return the (msg, endpoint) suggest_experiment would have posted."""
        posted = {}
        prefix = "{0}:{1}{2}/".format(self.vis.server, self.vis.port, self.vis.base_url)

        def capture(url, data=None):
            posted["msg"] = json.loads(data)
            posted["endpoint"] = url[len(prefix) :]
            return True

        with patch.object(self.vis, "_handle_post", side_effect=capture):
            self.vis.suggest_experiment(**kwargs)
        return posted["msg"], posted["endpoint"]

    def test_suggest_message_shape(self):
        """The message posts to the suggest endpoint and carries params.

        ``_send`` stamps an ``eid`` on every message; the stub ignores it.
        """
        msg, endpoint = self.suggest()
        self.assertEqual(endpoint, "experiments/suggest")
        self.assertIsNone(msg["params"])
        self.assertIn("eid", msg)

    def test_params_are_passed_through(self):
        """The search space rides along untouched for the eventual strategy."""
        msg, _ = self.suggest(params={"lr": [0.1, 0.01]})
        self.assertEqual(msg["params"], {"lr": [0.1, 0.01]})

    def test_env_overrides_the_target_eid(self):
        """An explicit env names the study to suggest against."""
        msg, _ = self.suggest(env="run-x")
        self.assertEqual(msg["eid"], "run-x")

    def test_client_rejects_bad_params(self):
        """The client type-checks before any request is made."""
        with self.assertRaises(TypeError):
            self.vis.suggest_experiment(params="lr")


class TestExperimentQueriesOffline(unittest.TestCase):
    """The query endpoints say there is no answer offline, rather than True.

    An offline client never reaches a server, so search/compare/suggest have
    nothing to report. Left to the generic ``_send`` short circuit they would
    return ``True``, which a caller expecting a reply dict cannot use and cannot
    tell apart from a real one.
    """

    def setUp(self):
        self._log = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
        self._log.close()
        self.vis = Visdom(
            offline=True,
            log_to_filename=self._log.name,
            use_incoming_socket=False,
        )

    def tearDown(self):
        os.unlink(self._log.name)

    def test_search_returns_none(self):
        self.assertIsNone(self.vis.search_experiments("lr < 0.01"))

    def test_compare_returns_none(self):
        self.assertIsNone(self.vis.compare_experiments(["run-a", "run-b"]))

    def test_suggest_returns_none(self):
        self.assertIsNone(self.vis.suggest_experiment({"lr": [0.1, 0.01]}))

    def test_the_argument_checks_still_run_offline(self):
        """Being offline is no reason to accept a call that is malformed."""
        with self.assertRaises(TypeError):
            self.vis.search_experiments(query=42)
        with self.assertRaises(TypeError):
            self.vis.compare_experiments("run-a")
        with self.assertRaises(TypeError):
            self.vis.suggest_experiment(params="lr")

    def test_a_query_never_reaches_the_transport(self):
        """No request is attempted, so nothing can be waiting on a timeout."""
        with patch.object(Visdom, "_handle_post") as post:
            self.assertIsNone(self.vis.search_experiments())
            self.assertIsNone(self.vis.compare_experiments(["run-a"]))
            self.assertIsNone(self.vis.suggest_experiment())
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
