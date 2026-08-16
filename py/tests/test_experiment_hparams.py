#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the hyper-parameter endpoint.

Covers the two pieces the endpoint is built from: the ``flatten_experiments``
transform, and the ``/experiments/hparams`` endpoint end-to-end through a real
:class:`~visdom.server.app.Application` with Tornado's ``AsyncHTTPTestCase``.
The endpoint selects experiments (the strict query/env_ids/both modes the
client used to resolve itself), flattens them, and registers an ``hparams``
window; the tests inspect the created window in the app state. Experiments are
seeded through a real ``ExperimentStore`` over a temporary directory.
"""

import json
import shutil
import tempfile
import unittest

import tornado.testing

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore, flatten_experiments
from visdom.server.app import Application


def seed_experiments(store):
    """Log three runs with heterogeneous params/tags and a metric time series."""
    store.log_experiment(
        "run-a",
        name="alpha",
        params={"lr": 0.1, "epochs": 10},
        tags={"dataset": "mnist"},
    )
    store.log_metric("run-a", "acc", 0.80)

    store.log_experiment(
        "run-b",
        name="beta",
        params={"lr": 0.001, "epochs": 20},
        tags={"dataset": "cifar10", "owner": "mira"},
    )
    store.log_metric("run-b", "acc", 0.55)
    store.log_metric("run-b", "acc", 0.95)
    store.log_metric("run-b", "loss", 0.1)

    store.log_experiment("run-c", name="gamma", params={"momentum": 0.9})


class TestFlattenTransform(unittest.TestCase):
    """flatten_experiments collapses experiment dicts into the records payload."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ExperimentStore(JSONStore(self._tmp.name))
        seed_experiments(self.store)
        dicts = [experiment.to_dict() for experiment in self.store.search()]
        self.payload = flatten_experiments(dicts)

    def tearDown(self):
        self._tmp.cleanup()

    def _record(self, env_id):
        for record in self.payload["records"]:
            if record["env_id"] == env_id:
                return record
        self.fail("no record for {0!r}".format(env_id))

    def test_one_record_per_run(self):
        self.assertEqual(len(self.payload["records"]), 3)

    def test_key_unions_are_sorted(self):
        self.assertEqual(self.payload["param_keys"], ["epochs", "lr", "momentum"])
        self.assertEqual(self.payload["metric_keys"], ["acc", "loss"])
        self.assertEqual(self.payload["tag_keys"], ["dataset", "owner"])

    def test_latest_metric_value_is_kept(self):
        self.assertEqual(self._record("run-b")["metrics"]["acc"], 0.95)

    def test_params_and_tags_are_maps(self):
        record = self._record("run-a")
        self.assertEqual(record["params"], {"lr": 0.1, "epochs": 10})
        self.assertEqual(record["tags"], {"dataset": "mnist"})

    def test_missing_key_is_absent(self):
        self.assertNotIn("momentum", self._record("run-a")["params"])
        self.assertEqual(self._record("run-c")["tags"], {})

    def test_empty_input_is_empty_payload(self):
        payload = flatten_experiments([])
        self.assertEqual(payload["records"], [])
        self.assertEqual(payload["param_keys"], [])
        self.assertEqual(payload["metric_keys"], [])
        self.assertEqual(payload["tag_keys"], [])

    def test_non_dict_entries_are_skipped(self):
        payload = flatten_experiments([None, "oops", {"env_id": "x"}])
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["env_id"], "x")


class TestHparamsEndpoint(tornado.testing.AsyncHTTPTestCase):
    """POST /experiments/hparams selects runs and registers the pane window."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_hparams_api_")
        super().setUp()
        seed_experiments(ExperimentStore(self._app.storage))

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def get_app(self):
        self._app = Application(port=self.get_http_port(), env_path=self._tmp_dir)
        return self._app

    def hparams(self, body):
        return self.fetch(
            "/experiments/hparams",
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def _window(self, resp):
        win_id = resp.body.decode()
        return self._app.state["main"]["jsons"][win_id]

    def _env_ids(self, resp):
        return [record["env_id"] for record in self._window(resp)["content"]["records"]]

    def test_query_creates_hparams_window(self):
        """A query registers an hparams window holding the matching runs."""
        resp = self.hparams({"query": "lr < 0.01"})
        self.assertEqual(resp.code, 200)
        window = self._window(resp)
        self.assertEqual(window["type"], "hparams")
        self.assertEqual(self._env_ids(resp), ["run-b"])

    def test_content_carries_column_unions(self):
        """The window content is the flattened matrix with column-name unions."""
        resp = self.hparams({"query": "epochs > 0"})
        content = self._window(resp)["content"]
        self.assertEqual(content["param_keys"], ["epochs", "lr"])
        self.assertEqual(content["metric_keys"], ["acc", "loss"])

    def test_env_ids_selects_and_orders(self):
        """env_ids alone selects only the named runs, in the order given."""
        resp = self.hparams({"env_ids": ["run-c", "run-a"]})
        self.assertEqual(self._env_ids(resp), ["run-c", "run-a"])

    def test_unknown_env_id_is_404(self):
        """An env_id without an experiment is an error, not a quiet omission."""
        resp = self.hparams({"env_ids": ["run-a", "ghost"]})
        self.assertEqual(resp.code, 404)
        self.assertIn("ghost", resp.reason)

    def test_unknown_env_id_reason_is_ascii(self):
        """A non-latin-1 id is escaped into the reason rather than crashing it."""
        resp = self.hparams({"env_ids": ["ruñ-✓"]})
        self.assertEqual(resp.code, 404)
        resp.reason.encode("ascii")

    def test_both_intersects_ordered(self):
        """query + env_ids returns the intersection, ordered by env_ids."""
        resp = self.hparams({"query": "acc > 0.9", "env_ids": ["run-b", "run-a"]})
        self.assertEqual(self._env_ids(resp), ["run-b"])

    def test_both_rejects_unknown_env_id(self):
        """Under both, an id that names no experiment is still a 404."""
        resp = self.hparams({"query": "acc > 0.9", "env_ids": ["run-b", "ghost"]})
        self.assertEqual(resp.code, 404)

    def test_win_id_is_honoured(self):
        """A supplied win id is the window the pane is registered under."""
        resp = self.hparams({"query": "epochs > 0", "win": "hp1"})
        self.assertEqual(resp.body.decode(), "hp1")
        self.assertIn("hp1", self._app.state["main"]["jsons"])

    def test_no_selection_is_400(self):
        """With neither query nor env_ids there is nothing to select."""
        self.assertEqual(self.hparams({}).code, 400)

    def test_mode_query_rejects_env_ids(self):
        resp = self.hparams(
            {"query": "acc > 0.9", "env_ids": ["run-a"], "mode": "query"}
        )
        self.assertEqual(resp.code, 400)

    def test_mode_env_ids_rejects_query(self):
        resp = self.hparams(
            {"query": "acc > 0.9", "env_ids": ["run-b"], "mode": "env_ids"}
        )
        self.assertEqual(resp.code, 400)

    def test_mode_both_requires_both(self):
        self.assertEqual(self.hparams({"query": "acc > 0.9", "mode": "both"}).code, 400)

    def test_bad_query_is_400(self):
        self.assertEqual(self.hparams({"query": "lr <<< 3"}).code, 400)

    def test_env_ids_must_be_a_list(self):
        self.assertEqual(self.hparams({"env_ids": "run-a"}).code, 400)

    def test_unknown_mode_is_400(self):
        self.assertEqual(
            self.hparams({"query": "acc > 0.9", "mode": "sideways"}).code, 400
        )


if __name__ == "__main__":
    unittest.main()
