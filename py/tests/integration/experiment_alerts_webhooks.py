#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Integration tests for the webhook an alert rule fires.

The receiver is a real Tornado application on a real port, on the same loop as
the server under test, so these assert an actual outbound request: nothing
patches ``AsyncHTTPClient``. The test that matters most is the one about the
endpoint being down -- a receiver that refuses the connection, answers 500 or
redirects must leave ``/experiments/log`` answering 200 with the metric
recorded, and leave nothing behind but a log line.
"""

import json

import pytest
import tornado.web
from tornado.httpserver import HTTPServer
from tornado.testing import bind_unused_port

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore
from visdom.server import webhooks
from visdom.server.webhooks import WebhookPolicy

from testutils.fakes import FakeSocket
from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


class Capture(tornado.web.RequestHandler):
    """A receiver that records what arrived, and answers how it was told to."""

    def initialize(self, sink, code=200, location=None):
        self.sink = sink
        self.code = code
        self.location = location

    def post(self):
        self.sink.append(
            {
                "path": self.request.path,
                "content_type": self.request.headers.get("Content-Type"),
                "body": json.loads(self.request.body),
            }
        )
        if self.location is not None:
            self.set_status(302)
            self.set_header("Location", self.location)
            return
        self.set_status(self.code)


class WebhookTestCase(VisdomHTTPTestCase):
    app_kwargs = {
        "allow_webhooks": True,
        # The receiver is on this machine, so both flags are needed.
        "webhook_hosts": ["127.0.0.1"],
        "allow_local_webhooks": True,
    }

    def setUp(self):
        self.sink = []
        self.hook_socket, self.hook_port = bind_unused_port()
        # A port nothing listens on: taken the same way, then released.
        dead_socket, self.dead_port = bind_unused_port()
        dead_socket.close()
        super().setUp()
        self.hook_server = HTTPServer(
            tornado.web.Application(
                [
                    (r"/hook", Capture, {"sink": self.sink}),
                    (r"/boom", Capture, {"sink": self.sink, "code": 500}),
                    (
                        r"/bounce",
                        Capture,
                        {"sink": self.sink, "location": self.hook_url("/hook")},
                    ),
                ]
            )
        )
        self.hook_server.add_sockets([self.hook_socket])

    def tearDown(self):
        # So a delivery still in flight is not reported against the next test.
        self.drain()
        self.hook_server.stop()
        super().tearDown()

    def hook_url(self, path="/hook", port=None):
        return "http://127.0.0.1:{0}{1}".format(
            self.hook_port if port is None else port, path
        )

    def drain(self):
        """Let the deliveries this request started finish."""
        pending = self._app.server_state.pending_webhooks
        self.io_loop.run_sync(lambda: webhooks.drain(pending))

    def set_webhook(self, metric="loss", condition="> 2.0", path="/hook", port=None):
        return self.post_json(
            "/experiments/alerts",
            {
                "action": "set",
                "eid": "main",
                "alert": {
                    "metric": metric,
                    "condition": condition,
                    "action": "webhook",
                    "url": self.hook_url(path, port),
                },
            },
        )

    def log_metric(self, value, metric="loss", step=None):
        return self.post_json(
            "/experiments/log",
            {
                "action": "metrics",
                "eid": "main",
                "metrics": {metric: value},
                "step": step,
            },
        )

    def stored_alerts(self, eid="main"):
        experiment = ExperimentStore(JSONStore(self.env_path)).get_experiment(eid)
        return [] if experiment is None else [a.to_dict() for a in experiment.alerts]


class TestWebhookDelivery(WebhookTestCase):
    def test_a_fired_rule_posts_to_its_url(self):
        self.set_webhook()
        response = self.log_metric(2.5, step=4)
        self.drain()

        self.assertEqual(response.code, 200)
        self.assertEqual(len(self.sink), 1)
        delivered = self.sink[0]
        self.assertEqual(delivered["path"], "/hook")
        self.assertEqual(delivered["content_type"], "application/json")

    def test_the_body_carries_the_firing_taken_apart(self):
        self.set_webhook()
        self.log_metric(2.5, step=4)
        self.drain()

        body = self.sink[0]["body"]
        self.assertEqual(body["env"], "main")
        self.assertEqual(body["metric"], "loss")
        self.assertEqual(body["condition"], ">")
        self.assertEqual(body["threshold"], 2.0)
        self.assertEqual(body["value"], 2.5)
        self.assertEqual(body["step"], 4)
        self.assertEqual(body["fire_count"], 1)
        self.assertIsNotNone(body["fired_at"])

    def test_the_body_also_carries_the_sentence_a_toast_would_have_shown(self):
        # A chat endpoint reads 'message' and ignores the rest.
        self.set_webhook()
        self.log_metric(2.5, step=4)
        self.drain()

        self.assertEqual(
            self.sink[0]["body"]["message"], "main: loss is 2.5, > 2 at step 4"
        )

    def test_a_diverged_metric_arrives_as_null_not_as_nan(self):
        # The same reason the rule matches None: standard JSON has no NaN.
        self.set_webhook(condition="nan")
        self.log_metric(None)
        self.drain()

        raw = json.dumps(self.sink[0]["body"])
        self.assertIn('"value": null', raw)
        self.assertNotIn("NaN", raw)

    def test_a_webhook_rule_does_not_also_toast(self):
        sub = FakeSocket("sub", "main")
        self._app.subs["sub"] = sub
        self.set_webhook()
        self.log_metric(2.5)
        self.drain()

        self.assertEqual(len(self.sink), 1)
        self.assertEqual(
            [m for m in sub.sent if m.get("command") == "notification"], []
        )

    def test_a_debounced_rule_posts_only_once_the_streak_completes(self):
        self.post_json(
            "/experiments/alerts",
            {
                "action": "set",
                "eid": "main",
                "alert": {
                    "metric": "loss",
                    "condition": "> 2.0",
                    "for_steps": 2,
                    "action": "webhook",
                    "url": self.hook_url(),
                },
            },
        )

        self.log_metric(2.5)
        self.drain()
        self.assertEqual(self.sink, [])

        self.log_metric(2.6)
        self.drain()
        self.assertEqual(len(self.sink), 1)

    def test_a_cleared_rule_posts_nothing(self):
        self.set_webhook()
        self.post_json(
            "/experiments/alerts",
            {"action": "clear", "eid": "main", "metric": "loss", "condition": None},
        )
        self.log_metric(2.5)
        self.drain()

        self.assertEqual(self.sink, [])


class TestWebhookFailuresAreNotTheCallersProblem(WebhookTestCase):
    """What an endpoint that is down costs the request that fired the rule:
    nothing. The observation is recorded, the response is 200, and the rule's
    state is written.
    """

    def test_a_port_nothing_listens_on_leaves_the_request_at_200(self):
        self.set_webhook(port=self.dead_port)
        response = self.log_metric(2.5, step=9)
        self.drain()

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body)["metrics"][0]["value"], 2.5)

    def test_and_the_firing_is_still_recorded(self):
        # Re-arming it would spend the next crossing on an endpoint that is
        # still down.
        self.set_webhook(port=self.dead_port)
        self.log_metric(2.5, step=9)
        self.drain()

        stored = self.stored_alerts()[0]
        self.assertEqual(stored["fire_count"], 1)
        self.assertEqual(stored["last_fired_step"], 9)

    def test_a_receiver_that_answers_500_is_not_an_error_either(self):
        self.set_webhook(path="/boom")
        response = self.log_metric(2.5)
        self.drain()

        self.assertEqual(response.code, 200)
        self.assertEqual(len(self.sink), 1)

    def test_a_redirect_is_not_followed(self):
        # Otherwise an allowlisted host could bounce the request anywhere.
        self.set_webhook(path="/bounce")
        response = self.log_metric(2.5)
        self.drain()

        self.assertEqual(response.code, 200)
        self.assertEqual([arrived["path"] for arrived in self.sink], ["/bounce"])


class TestThePolicyIsAskedAgainAtDispatch(WebhookTestCase):
    def test_a_rule_that_outlived_its_flags_posts_nothing(self):
        # Restarting without the flags is the case this stands in for.
        self.set_webhook()
        self._app.server_state.webhook_policy = WebhookPolicy()

        response = self.log_metric(2.5)
        self.drain()

        self.assertEqual(response.code, 200)
        self.assertEqual(self.sink, [])

    def test_the_rule_stays_on_the_record(self):
        # Refused at dispatch, not deleted: the operator may put the flag back.
        self.set_webhook()
        self._app.server_state.webhook_policy = WebhookPolicy()
        self.log_metric(2.5)
        self.drain()

        self.assertEqual(len(self.stored_alerts()), 1)

    def test_a_host_dropped_from_the_allowlist_posts_nothing(self):
        self.set_webhook()
        self._app.server_state.webhook_policy = WebhookPolicy(
            enabled=True, hosts="hooks.example.com", allow_local=True
        )

        self.log_metric(2.5)
        self.drain()

        self.assertEqual(self.sink, [])
