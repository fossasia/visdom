"""Endpoint-level tests for the readonly write guard.

A readonly server must refuse every request that changes stored state, and must
still serve every request that only reads it. The guard is a decorator applied
per handler (:func:`~visdom.utils.server_utils.check_readonly_message`), so what needs
testing is coverage rather than mechanism: each write endpoint refuses, each
read endpoint does not, and nothing reaches disk on the way out.

These tests exist because the guard was lost twice while the experiment
endpoints were being developed — once for ``/experiments/log``, then again for
the hparams endpoints — and a per-handler check is only as good as the list of
handlers that remembered to apply it.
"""

import json
import shutil
import tempfile
import unittest

import pytest
import tornado.testing

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore
from visdom.server.app import Application

pytestmark = pytest.mark.integration


class ReadonlyEndpointCase(tornado.testing.AsyncHTTPTestCase):
    """Base: a readonly app over a temp env dir, with one experiment on disk."""

    readonly = True

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_readonly_test_")
        seed = ExperimentStore(JSONStore(self._tmp_dir))
        seed.log_experiment("run-a", params={"lr": 0.1})
        seed.log_metric("run-a", "acc", 0.9)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def get_app(self):
        self._app = Application(
            port=self.get_http_port(),
            env_path=self._tmp_dir,
            readonly=self.readonly,
        )
        return self._app

    def post_json(self, path, body):
        return self.fetch(
            path,
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def on_disk(self, env_id="run-a"):
        """Read the persisted experiment through a fresh store, bypassing state."""
        return ExperimentStore(JSONStore(self._tmp_dir)).get_experiment(env_id)

    def assertRefused(self, response):
        self.assertEqual(response.code, 403)
        body = json.loads(response.body)
        self.assertFalse(body["success"])
        self.assertIn("readonly", body["error"])


class TestReadonlyRefusesExperimentLog(ReadonlyEndpointCase):
    """Every /experiments/log action is a write, so every action is refused."""

    def test_log_is_refused(self):
        self.assertRefused(
            self.post_json("/experiments/log", {"eid": "new-run", "params": {"lr": 1}})
        )
        self.assertIsNone(self.on_disk("new-run"))

    def test_metrics_is_refused(self):
        self.assertRefused(
            self.post_json(
                "/experiments/log",
                {"eid": "run-a", "action": "metrics", "metrics": {"acc": 0.1}},
            )
        )
        self.assertEqual([m.value for m in self.on_disk().metrics], [0.9])

    def test_finish_is_refused(self):
        self.assertRefused(
            self.post_json("/experiments/log", {"eid": "run-a", "action": "finish"})
        )
        self.assertEqual(self.on_disk().status, "running")

    def test_refusal_does_not_create_the_env(self):
        self.assertRefused(
            self.post_json("/experiments/log", {"eid": "brand-new", "params": {"a": 1}})
        )
        self.assertNotIn("brand-new", self._app.state)


class TestReadonlyRefusesHparamsPanes(ReadonlyEndpointCase):
    """The hparams endpoints register windows and save envs, so both are refused."""

    def test_create_pane_is_refused(self):
        self.assertRefused(
            self.post_json("/experiments/hparams", {"eid": "main", "query": "lr = 0.1"})
        )
        self.assertEqual(self._app.state["main"]["jsons"], {})

    def test_update_pane_is_refused(self):
        self.assertRefused(
            self.post_json(
                "/experiments/hparams/update", {"eid": "main", "win": "whatever"}
            )
        )

    def test_update_refusal_precedes_validation(self):
        """A readonly refusal outranks the 404 an unknown window would earn.

        The request is rejected for what it would do, not for whether it could
        have succeeded — otherwise the guard would leak which windows exist.
        """
        response = self.post_json(
            "/experiments/hparams/update", {"eid": "no-such-env", "win": "w1"}
        )
        self.assertEqual(response.code, 403)


class TestReadonlyRefusesUpload(ReadonlyEndpointCase):
    """/upload_env writes a whole new env, and keeps its own refusal message."""

    def test_upload_is_refused(self):
        boundary = "----visdomtest"
        payload = json.dumps({"jsons": {}, "reload": {}})
        body = (
            "--{0}\r\n"
            'Content-Disposition: form-data; name="file"; filename="env.json"\r\n'
            "Content-Type: application/json\r\n\r\n"
            "{1}\r\n"
            "--{0}--\r\n"
        ).format(boundary, payload)
        response = self.fetch(
            "/upload_env",
            method="POST",
            body=body,
            headers={
                "Content-Type": "multipart/form-data; boundary={0}".format(boundary)
            },
        )
        self.assertEqual(response.code, 403)
        self.assertIn("Uploads", json.loads(response.body)["error"])


class TestReadonlyAllowsReads(ReadonlyEndpointCase):
    """Readonly disables writing, not reading: the query endpoints still answer."""

    def test_search_is_allowed(self):
        response = self.post_json("/experiments/search", {"query": "lr = 0.1"})
        self.assertEqual(response.code, 200)
        body = json.loads(response.body)
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["experiments"][0]["env_id"], "run-a")

    def test_compare_is_allowed(self):
        response = self.post_json("/experiments/compare", {"env_ids": ["run-a"]})
        self.assertEqual(response.code, 200)


class TestWritableServerStillWrites(ReadonlyEndpointCase):
    """The same requests succeed with readonly off — the guard is the only gate."""

    readonly = False

    def test_log_is_accepted(self):
        response = self.post_json(
            "/experiments/log", {"eid": "run-a", "params": {"lr": 0.5}}
        )
        self.assertEqual(response.code, 200)
        self.assertEqual(self.on_disk().get_param("lr").value, 0.5)

    def test_hparams_pane_is_accepted(self):
        response = self.post_json(
            "/experiments/hparams", {"eid": "main", "query": "lr = 0.1"}
        )
        self.assertEqual(response.code, 200)


if __name__ == "__main__":
    unittest.main()
