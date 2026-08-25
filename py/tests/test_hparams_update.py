"""Tests for the hyper-parameter pane update endpoint.

``POST /experiments/hparams/update`` is the dedicated write path for
``hparams`` windows — the generic ``/update`` endpoint only understands
plot-shaped content. These tests run end-to-end through a real
:class:`~visdom.server.app.Application` with Tornado's ``AsyncHTTPTestCase``:
a pane is created via ``/experiments/hparams``, updated, and inspected both in
the app state and in the env file on disk, since the endpoint promises the two
stay in step.
"""

import json
import os
import shutil
import tempfile
import unittest

import tornado.testing

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore
from visdom.server.app import Application


class TestHparamsUpdateEndpoint(tornado.testing.AsyncHTTPTestCase):
    """POST /experiments/hparams/update rebuilds a pane in state and on disk."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_hparams_update_")
        super().setUp()
        self.store = ExperimentStore(self._app.storage)
        self.store.log_experiment("run-a", params={"lr": 0.1})
        self.store.log_metric("run-a", "acc", 0.80)
        self.store.log_experiment("run-b", params={"lr": 0.001})
        self.store.log_metric("run-b", "acc", 0.95)

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def get_app(self):
        self._app = Application(port=self.get_http_port(), env_path=self._tmp_dir)
        return self._app

    def _post(self, path, body):
        return self.fetch(
            path,
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def create(self, body):
        return self._post("/experiments/hparams", body)

    def update(self, body):
        return self._post("/experiments/hparams/update", body)

    def _window(self, win_id, eid="main"):
        return self._app.state[eid]["jsons"][win_id]

    def _env_ids(self, win_id):
        return [
            record["env_id"] for record in self._window(win_id)["content"]["records"]
        ]

    def _disk_env(self, eid="main"):
        with open(os.path.join(self._tmp_dir, eid + ".json")) as fn:
            return json.load(fn)

    def test_new_query_replaces_selection_and_content(self):
        """A new query becomes the pane's selection and reselects the runs."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.assertEqual(self._env_ids("hp1"), ["run-b"])
        resp = self.update({"win": "hp1", "query": "lr < 1"})
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body.decode(), "hp1")
        self.assertEqual(sorted(self._env_ids("hp1")), ["run-a", "run-b"])
        self.assertEqual(self._window("hp1")["hparams"]["query"], "lr < 1")

    def test_update_mints_a_fresh_content_id(self):
        """The client re-renders on contentID, so an update must change it."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        before = self._window("hp1")["contentID"]
        self.update({"win": "hp1", "query": "lr < 1"})
        self.assertNotEqual(self._window("hp1")["contentID"], before)

    def test_bare_update_reruns_the_stored_selection(self):
        """With only win, the stored selection is re-run and picks up new runs."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.assertEqual(self._env_ids("hp1"), ["run-b"])
        self.store.log_experiment("run-c", params={"lr": 0.0001})
        resp = self.update({"win": "hp1"})
        self.assertEqual(resp.code, 200)
        self.assertEqual(sorted(self._env_ids("hp1")), ["run-b", "run-c"])
        self.assertEqual(self._window("hp1")["hparams"]["query"], "lr < 0.01")

    def test_update_reaches_disk_immediately(self):
        """The env file reflects the update without an explicit save."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.update({"win": "hp1", "query": "lr < 1"})
        window = self._disk_env()["jsons"]["hp1"]
        self.assertEqual(window["hparams"]["query"], "lr < 1")
        self.assertEqual(
            sorted(record["env_id"] for record in window["content"]["records"]),
            ["run-a", "run-b"],
        )

    def test_window_keeps_its_id_and_position(self):
        """The rebuilt window keeps id and pane order (the 'i' slot)."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        before = self._window("hp1")["i"]
        self.update({"win": "hp1", "query": "lr < 1"})
        self.assertEqual(self._window("hp1")["i"], before)

    def test_opts_absent_keeps_title(self):
        """Without opts the pane's current title survives the rebuild."""
        self.create({"query": "lr < 0.01", "win": "hp1", "opts": {"title": "Sweep"}})
        self.update({"win": "hp1", "query": "lr < 1"})
        self.assertEqual(self._window("hp1")["title"], "Sweep")

    def test_opts_override_title(self):
        """Opts passed with the update replace the pane's current ones."""
        self.create({"query": "lr < 0.01", "win": "hp1", "opts": {"title": "Sweep"}})
        self.update({"win": "hp1", "opts": {"title": "Sweep v2"}})
        self.assertEqual(self._window("hp1")["title"], "Sweep v2")

    def test_missing_win_is_400(self):
        self.assertEqual(self.update({"query": "lr < 1"}).code, 400)

    def test_unknown_window_is_404(self):
        self.assertEqual(self.update({"win": "ghost"}).code, 404)

    def test_unknown_env_is_404(self):
        self.assertEqual(self.update({"win": "hp1", "eid": "ghost"}).code, 404)

    def test_non_hparams_window_is_400(self):
        """The endpoint refuses to become a generic write path."""
        self._app.state["main"]["jsons"]["plot1"] = {"id": "plot1", "type": "plot"}
        self.assertEqual(self.update({"win": "plot1", "query": "lr < 1"}).code, 400)

    def test_window_without_stored_selection_is_400(self):
        """A pre-spec window cannot be bare-refreshed, only re-selected."""
        self._app.state["main"]["jsons"]["legacy"] = {
            "id": "legacy",
            "type": "hparams",
            "content": {"records": []},
        }
        self.assertEqual(self.update({"win": "legacy"}).code, 400)

    def test_selection_rules_match_create(self):
        """Selection arguments are validated exactly as on create."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        resp = self.update(
            {"win": "hp1", "query": "lr < 1", "env_ids": ["run-a"], "mode": "query"}
        )
        self.assertEqual(resp.code, 400)

    def test_bad_query_is_400(self):
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.assertEqual(self.update({"win": "hp1", "query": "lr <<< 3"}).code, 400)


if __name__ == "__main__":
    unittest.main()
