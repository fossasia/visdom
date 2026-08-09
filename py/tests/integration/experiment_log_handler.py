#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""End-to-end tests for the ``/experiments/log`` endpoint.

Drives a real :class:`~visdom.server.app.Application` over a temp env dir with
Tornado's ``AsyncHTTPTestCase``, so the full route -> handler -> ``ExperimentStore``
-> ``JSONStore`` path is exercised. Also unit-tests the client-side
``Visdom.experiment``/``log_metrics``/``finish_experiment`` message shapes with
a mocked transport (no server needed).
"""

import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import tornado.testing

from visdom import Visdom
from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore
from visdom.server.app import Application


class TestExperimentLogEndpoint(tornado.testing.AsyncHTTPTestCase):
    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_test_")
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

    def read_experiment(self, eid):
        """Read the persisted experiment straight from disk via a fresh store."""
        return ExperimentStore(JSONStore(self._tmp_dir)).get_experiment(eid)

    def test_log_creates_and_persists_experiment(self):
        resp = self.post_json(
            "/experiments/log",
            {
                "eid": "main",
                "action": "log",
                "name": "run-1",
                "params": {"lr": 0.01, "epochs": 10},
                "tags": {"dataset": "mnist"},
                "description": "first run",
            },
        )
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["name"], "run-1")
        self.assertEqual(body["params"][0]["key"], "lr")

        exp = self.read_experiment("main")
        self.assertIsNotNone(exp)
        self.assertEqual(exp.get_param("epochs").value, 10)
        self.assertEqual(exp.get_param("epochs").dtype, "int")
        self.assertEqual(exp.tags[0].value, "mnist")

    def test_action_defaults_to_log(self):
        resp = self.post_json(
            "/experiments/log", {"eid": "main", "params": {"lr": 0.5}}
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(self.read_experiment("main").get_param("lr").value, 0.5)

    def test_metrics_append_and_autocreate(self):
        resp = self.post_json(
            "/experiments/log",
            {
                "eid": "main",
                "action": "metrics",
                "metrics": {"acc": 0.9, "loss": 0.1},
                "step": 3,
            },
        )
        self.assertEqual(resp.code, 200)
        exp = self.read_experiment("main")
        self.assertEqual(len(exp.metrics), 2)
        self.assertEqual(exp.latest_metric("acc").value, 0.9)
        self.assertEqual(exp.latest_metric("acc").step, 3)

    def test_finish_sets_terminal_status(self):
        self.post_json("/experiments/log", {"eid": "main", "params": {"lr": 0.01}})
        resp = self.post_json(
            "/experiments/log",
            {"eid": "main", "action": "finish", "status": "failed"},
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(self.read_experiment("main").status, "failed")

    def test_finish_without_experiment_is_404(self):
        resp = self.post_json("/experiments/log", {"eid": "ghost", "action": "finish"})
        self.assertEqual(resp.code, 404)

    def test_finish_with_running_status_is_400(self):
        self.post_json("/experiments/log", {"eid": "main", "params": {"lr": 0.01}})
        resp = self.post_json(
            "/experiments/log",
            {"eid": "main", "action": "finish", "status": "running"},
        )
        self.assertEqual(resp.code, 400)

    def test_finish_on_finished_is_409(self):
        self.post_json("/experiments/log", {"eid": "main", "params": {"lr": 0.01}})
        self.post_json("/experiments/log", {"eid": "main", "action": "finish"})
        finished_at = self.read_experiment("main").finished_at
        resp = self.post_json(
            "/experiments/log",
            {"eid": "main", "action": "finish", "status": "failed"},
        )
        self.assertEqual(resp.code, 409)
        stored = self.read_experiment("main")
        self.assertEqual(stored.status, "finished")
        self.assertEqual(stored.finished_at, finished_at)

    def test_log_to_finished_is_409(self):
        self.post_json("/experiments/log", {"eid": "main", "params": {"lr": 0.01}})
        self.post_json("/experiments/log", {"eid": "main", "action": "finish"})
        resp = self.post_json(
            "/experiments/log", {"eid": "main", "params": {"lr": 0.02}}
        )
        self.assertEqual(resp.code, 409)
        self.assertEqual(self.read_experiment("main").get_param("lr").value, 0.01)

    def test_metrics_to_finished_is_409(self):
        self.post_json(
            "/experiments/log",
            {"eid": "main", "action": "metrics", "metrics": {"acc": 0.9}},
        )
        self.post_json("/experiments/log", {"eid": "main", "action": "finish"})
        resp = self.post_json(
            "/experiments/log",
            {"eid": "main", "action": "metrics", "metrics": {"acc": 0.95}},
        )
        self.assertEqual(resp.code, 409)
        self.assertEqual(len(self.read_experiment("main").metrics), 1)

    def test_unknown_action_is_400(self):
        resp = self.post_json("/experiments/log", {"eid": "main", "action": "bogus"})
        self.assertEqual(resp.code, 400)

    def test_empty_metrics_is_400(self):
        resp = self.post_json(
            "/experiments/log", {"eid": "main", "action": "metrics", "metrics": {}}
        )
        self.assertEqual(resp.code, 400)

    def test_non_mapping_params_is_400(self):
        resp = self.post_json("/experiments/log", {"eid": "main", "params": [1, 2, 3]})
        self.assertEqual(resp.code, 400)

    def test_experiment_survives_full_env_save(self):
        """A window save must not clobber a previously logged experiment.

        This guards the in-memory/on-disk sync: logging writes the blob to disk
        and mirrors it into server state, so persisting that env (which writes
        the in-memory state) keeps the experiment instead of dropping it.
        """
        self.post_json("/experiments/log", {"eid": "main", "params": {"lr": 0.01}})
        win_resp = self.post_json(
            "/events", {"eid": "main", "data": [{"type": "text", "content": "hi"}]}
        )
        self.assertEqual(win_resp.code, 200)
        save_resp = self.post_json("/save", {"data": ["main"]})
        self.assertEqual(save_resp.code, 200)

        exp = self.read_experiment("main")
        self.assertIsNotNone(exp, "experiment was clobbered by the env save")
        self.assertEqual(exp.get_param("lr").value, 0.01)


class TestExperimentLogReadonly(tornado.testing.AsyncHTTPTestCase):
    """A readonly server must reject every write action with 403."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_ro_test_")
        super().setUp()

    def get_app(self):
        return Application(
            port=self.get_http_port(), env_path=self._tmp_dir, readonly=True
        )

    def post_json(self, body):
        return self.fetch(
            "/experiments/log",
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def test_log_is_403(self):
        resp = self.post_json({"eid": "main", "params": {"lr": 0.01}})
        self.assertEqual(resp.code, 403)
        self.assertFalse(json.loads(resp.body)["success"])
        store = ExperimentStore(JSONStore(self._tmp_dir))
        self.assertIsNone(store.get_experiment("main"))

    def test_metrics_is_403(self):
        resp = self.post_json(
            {"eid": "main", "action": "metrics", "metrics": {"acc": 0.9}}
        )
        self.assertEqual(resp.code, 403)

    def test_finish_is_403(self):
        resp = self.post_json({"eid": "main", "action": "finish"})
        self.assertEqual(resp.code, 403)


class TestClientMessageShapes(unittest.TestCase):
    """Client methods build the right request without needing a server.

    The transport is mocked to return the ``(msg, endpoint)`` it would have
    posted, so we can assert on it directly.
    """

    def _client(self):
        with (
            patch.object(Visdom, "_handle_post", return_value=True),
            patch.object(Visdom, "_start_session_reaper"),
        ):
            client = Visdom(env="expenv", use_incoming_socket=False)

        client._send = Mock(
            side_effect=lambda msg, endpoint="events", **_: (msg, endpoint)
        )
        return client

    def test_experiment_message(self):
        msg, endpoint = self._client().experiment(
            name="r1", params={"lr": 0.01}, tags={"ds": "mnist"}, description="d"
        )
        self.assertEqual(endpoint, "experiments/log")
        self.assertEqual(msg["action"], "log")
        self.assertEqual(msg["eid"], "expenv")
        self.assertEqual(msg["params"], {"lr": 0.01})
        self.assertEqual(msg["tags"], {"ds": "mnist"})

    def test_experiment_env_override(self):
        msg, _ = self._client().experiment(params={"lr": 0.01}, env="other")
        self.assertEqual(msg["eid"], "other")

    def test_log_metrics_message(self):
        msg, endpoint = self._client().log_metrics({"acc": 0.9}, step=5)
        self.assertEqual(endpoint, "experiments/log")
        self.assertEqual(msg["action"], "metrics")
        self.assertEqual(msg["metrics"], {"acc": 0.9})
        self.assertEqual(msg["step"], 5)

    def test_finish_experiment_message(self):
        msg, _ = self._client().finish_experiment(status="failed")
        self.assertEqual(msg["action"], "finish")
        self.assertEqual(msg["status"], "failed")

    def test_experiment_rejects_bad_params(self):
        with self.assertRaises(TypeError):
            self._client().experiment(params=[1, 2, 3])

    def test_log_metrics_rejects_empty(self):
        with self.assertRaises(TypeError):
            self._client().log_metrics({})


if __name__ == "__main__":
    unittest.main()
