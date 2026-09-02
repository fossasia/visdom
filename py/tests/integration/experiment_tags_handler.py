#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Integration tests for the environment tags HTTP API and broadcast."""

import json

import pytest

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore, tags_to_mapping

from testutils.fakes import FakeSocket
from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


class TestTagsEndpoint(VisdomHTTPTestCase):
    def read_tags(self, eid="main"):
        experiment = ExperimentStore(JSONStore(self.env_path)).get_experiment(eid)
        return tags_to_mapping(experiment.tags)

    def test_set_and_get_preserve_tag_values(self):
        response = self.post_json(
            "/experiments/tags",
            {
                "eid": "main",
                "tags": {"dataset": "cifar10", "stable": ""},
            },
        )

        self.assertEqual(response.code, 200)
        self.assertEqual(
            json.loads(response.body), {"dataset": "cifar10", "stable": ""}
        )
        self.assertEqual(self.read_tags(), {"dataset": "cifar10", "stable": ""})

        response = self.fetch("/experiments/tags?eid=main")
        self.assertEqual(response.code, 200)
        self.assertEqual(
            json.loads(response.body), {"dataset": "cifar10", "stable": ""}
        )

    def test_append_and_replace_tags(self):
        self.post_json(
            "/experiments/tags",
            {"eid": "main", "tags": {"dataset": "mnist", "old": "1"}},
        )
        response = self.post_json(
            "/experiments/tags",
            {
                "eid": "main",
                "tags": {"dataset": "cifar10", "stage": "production"},
                "append": True,
            },
        )
        self.assertEqual(
            json.loads(response.body),
            {"dataset": "cifar10", "old": "1", "stage": "production"},
        )

        response = self.post_json("/experiments/tags", {"eid": "main", "tags": {}})
        self.assertEqual(json.loads(response.body), {})
        self.assertEqual(self.read_tags(), {})

    def test_get_action_returns_all_tagged_environments(self):
        self.post_json(
            "/experiments/tags", {"eid": "run-a", "tags": {"owner": "alice"}}
        )
        self.post_json("/experiments/tags", {"eid": "run-b", "tags": {"owner": "bob"}})

        response = self.post_json("/experiments/tags", {"action": "get"})
        self.assertEqual(
            json.loads(response.body),
            {"run-a": {"owner": "alice"}, "run-b": {"owner": "bob"}},
        )

    def corrupt_env(self, eid, blob):
        """Make ``eid`` a resident env whose experiment blob will not rebuild.

        Put into live state rather than written to disk, because that is the
        branch the handler parses itself: ``_experiment_from_env`` reads the
        blob straight off a materialized env instead of going through the
        store's guarded read.
        """
        self._app.state[eid] = {"jsons": {}, "reload": {}, "experiment": blob}

    def test_a_corrupt_blob_does_not_500_the_tag_map(self):
        """The tag map walks every resident env, so one bad blob must not empty it."""
        self.post_json(
            "/experiments/tags", {"eid": "run-a", "tags": {"owner": "alice"}}
        )
        self.corrupt_env("bad", {"env_id": "bad", "status": "cancelled"})

        response = self.post_json("/experiments/tags", {"action": "get"})

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {"run-a": {"owner": "alice"}})

    def test_reading_one_envs_tags_survives_a_corrupt_blob(self):
        """A single-env read answers "no tags" rather than failing."""
        self.corrupt_env("bad", {"env_id": "bad", "params": {"lr": 0.1}})

        response = self.fetch("/experiments/tags?eid=bad")

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {})

    def test_tagging_an_env_with_a_corrupt_blob_repairs_it(self):
        """Tagging is a recovery path, so it must not be the thing that fails."""
        self.corrupt_env("bad", {"name": "bad", "status": "cancelled"})

        response = self.post_json(
            "/experiments/tags", {"eid": "bad", "tags": {"owner": "alice"}}
        )

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {"owner": "alice"})
        self.assertEqual(self.read_tags("bad"), {"owner": "alice"})

    def test_set_broadcasts_one_transport_neutral_message(self):
        websocket = FakeSocket("websocket")
        polling = FakeSocket("polling")
        self._app.subs.update({"websocket": websocket, "polling": polling})

        response = self.post_json(
            "/experiments/tags",
            {"eid": "main", "tags": {"stage": "production"}},
        )

        self.assertEqual(response.code, 200)
        expected = {
            "command": "tags_update",
            "data": {"eid": "main", "tags": {"stage": "production"}},
        }
        self.assertEqual(websocket.last("tags_update"), expected)
        self.assertEqual(polling.last("tags_update"), expected)

    def test_invalid_tag_mapping_and_append_flag_return_400(self):
        response = self.post_json(
            "/experiments/tags", {"eid": "main", "tags": ["stable"]}
        )
        self.assertEqual(response.code, 400)

        response = self.post_json(
            "/experiments/tags",
            {"eid": "main", "tags": {}, "append": "false"},
        )
        self.assertEqual(response.code, 400)

    def test_missing_tags_is_400_and_preserves_existing_tags(self):
        """Omitting tags is invalid rather than an implicit request to clear."""
        self.post_json("/experiments/tags", {"eid": "main", "tags": {"owner": "alice"}})

        response = self.post_json("/experiments/tags", {"eid": "main"})

        self.assertEqual(response.code, 400)
        self.assertIn("tags", response.reason)
        self.assertEqual(self.read_tags(), {"owner": "alice"})


class TestTagsEndpointReadonly(VisdomHTTPTestCase):
    app_kwargs = {"readonly": True}

    def test_reads_are_allowed_but_writes_are_rejected(self):
        ExperimentStore(self._app.storage).update_tags("main", {"dataset": "cifar10"})

        response = self.fetch("/experiments/tags?eid=main")
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {"dataset": "cifar10"})

        response = self.post_json(
            "/experiments/tags",
            {"eid": "main", "tags": {"dataset": "mnist"}},
        )
        self.assertEqual(response.code, 403)
        self.assertEqual(
            tags_to_mapping(
                ExperimentStore(self._app.storage).get_experiment("main").tags
            ),
            {"dataset": "cifar10"},
        )
