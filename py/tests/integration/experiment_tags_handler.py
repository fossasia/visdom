#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Integration tests for the environment tags HTTP API and broadcast."""

import asyncio
import json
import threading
from unittest import mock

import pytest
import tornado.testing

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


class TestTagWritesTheLiveEnv(VisdomHTTPTestCase):
    """Setting a tag rewrites the whole environment, so it must rewrite all of it.

    A tag lives in the same file as the experiment it organises and every window
    of the environment it names. Anything the write is not looking at when it
    happens -- a window the file has not seen, a window only the file has seen --
    is gone once the file lands.
    """

    def stored_env(self, eid="main"):
        return JSONStore(self.env_path).load_env(eid)

    def read_tags(self, eid="main"):
        experiment = ExperimentStore(JSONStore(self.env_path)).get_experiment(eid)
        return tags_to_mapping(experiment.tags)

    def test_tagging_keeps_windows_the_file_has_not_seen(self):
        win = self.create_text_window(eid="main", content="unsaved")
        JSONStore(self.env_path).save_env("main", {"jsons": {}, "reload": {}})

        response = self.post_json(
            "/experiments/tags", {"eid": "main", "tags": {"stage": "dev"}}
        )
        self.assertEqual(response.code, 200)

        stored = self.stored_env()
        self.assertIn(win, stored["jsons"], "tagging dropped an unsaved window")
        self.assertEqual(self.read_tags(), {"stage": "dev"})

    def test_tagging_keeps_the_windows_of_an_env_it_has_never_read(self):
        """An env the server knows only by its file is tagged, not replaced."""
        JSONStore(self.env_path).save_env(
            "offline", {"jsons": {"window_1": {"id": "window_1"}}, "reload": {}}
        )

        response = self.post_json(
            "/experiments/tags", {"eid": "offline", "tags": {"stage": "prod"}}
        )
        self.assertEqual(response.code, 200)

        stored = self.stored_env("offline")
        self.assertIn("window_1", stored["jsons"], "tagging wiped the environment")
        self.assertEqual(self.read_tags("offline"), {"stage": "prod"})


class TestConcurrentMetadataWrites(VisdomHTTPTestCase):
    """Two requests writing one environment must not overwrite each other.

    Tags and experiments share a file, so two requests that arrive together are
    two writers of the same bytes. Neither one is told it lost: both answer 200,
    and whichever write reaches the file second is the only one that survives.
    """

    def post(self, path, body):
        return self.http_client.fetch(
            self.get_url(path),
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(body),
        )

    @tornado.testing.gen_test
    async def test_a_tag_and_a_param_written_together_both_survive(self):
        responses = await asyncio.gather(
            self.post(
                "/experiments/log",
                {"eid": "main", "action": "log", "params": {"lr": 0.01}},
            ),
            self.post("/experiments/tags", {"eid": "main", "tags": {"stage": "dev"}}),
        )
        self.assertEqual([response.code for response in responses], [200, 200])

        experiment = ExperimentStore(JSONStore(self.env_path)).get_experiment("main")
        self.assertEqual(
            experiment.get_param("lr").value, 0.01, "the tag write lost the param"
        )
        self.assertEqual(
            tags_to_mapping(experiment.tags),
            {"stage": "dev"},
            "the experiment write lost the tag",
        )

    @tornado.testing.gen_test
    async def test_a_window_survives_a_metric_written_alongside_it(self):
        responses = await asyncio.gather(
            self.post(
                "/experiments/log",
                {"eid": "main", "action": "metrics", "metrics": {"acc": 0.9}},
            ),
            self.post(
                "/events", {"eid": "main", "data": [{"type": "text", "content": "hi"}]}
            ),
        )
        self.assertEqual([response.code for response in responses], [200, 200])
        win = responses[1].body.decode()

        await self.post("/save", {"data": ["main"]})
        stored = JSONStore(self.env_path).load_env("main")
        self.assertIn(win, stored["jsons"])
        self.assertEqual(stored["experiment"]["metrics"][0]["key"], "acc")


class ThreadRecordingStore(JSONStore):
    """JSONStore that remembers which thread each metadata read ran on."""

    def __init__(self, env_path):
        super().__init__(env_path)
        self.read_threads = []

    def list_envs(self):
        self.read_threads.append(threading.current_thread().name)
        return super().list_envs()

    def load_experiment(self, eid):
        self.read_threads.append(threading.current_thread().name)
        return super().load_experiment(eid)


class TestTagReadsStayOffTheLoop(VisdomHTTPTestCase):
    """Answering a tag read must not park the loop on a file read.

    Tags are a few hundred bytes, but they are stored inside the environment
    that carries them, so reading one off disk means opening and parsing an
    environment file -- megabytes of window data for a busy env, and every
    environment the store knows when no ``eid`` is named. Done on the loop, that
    is the whole server stopped: no other request is served, no socket is
    written, for as long as the read takes.
    """

    COLD = "cold"

    def get_app(self):
        # Seeded before the app is built so the tags exist only on disk: the
        # server knows the env by its file and has never materialised it, which
        # is the case that has to reach the store at all.
        ExperimentStore(JSONStore(self.env_path)).update_tags(
            self.COLD, {"owner": "alice"}
        )
        # The recorder has to be the store the app builds for itself:
        # ``ServerState`` takes its own reference at construction, so one
        # swapped onto the app afterwards would be read by nobody.
        with mock.patch("visdom.server.app.JSONStore", ThreadRecordingStore):
            app = super().get_app()
        self.recorder = app.storage
        return app

    def setUp(self):
        super().setUp()
        # Booting reads the env directory to build the lazy state; only what a
        # request goes on to do counts here.
        self.recorder.read_threads.clear()

    def assertReadOffLoop(self):
        """The read reached the store, and not on the thread serving requests."""
        self.assertTrue(self.recorder.read_threads, "the read never reached the store")
        for name in self.recorder.read_threads:
            self.assertNotEqual(name, threading.current_thread().name)
            self.assertTrue(name.startswith("visdom-storage"), name)

    def test_one_envs_tags_are_read_on_the_storage_worker(self):
        response = self.fetch("/experiments/tags?eid={0}".format(self.COLD))

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {"owner": "alice"})
        self.assertReadOffLoop()

    def test_every_envs_tags_are_read_on_the_storage_worker(self):
        """The unfiltered read walks the whole store, so it especially must."""
        response = self.post_json("/experiments/tags", {"action": "get"})

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {self.COLD: {"owner": "alice"}})
        self.assertReadOffLoop()

    def test_a_resident_env_answers_without_reaching_the_store(self):
        """An env already in memory is served from it, off no thread at all."""
        self.post_json("/experiments/tags", {"eid": "warm", "tags": {"stage": "dev"}})
        self.recorder.read_threads.clear()

        response = self.fetch("/experiments/tags?eid=warm")

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {"stage": "dev"})
        self.assertEqual(self.recorder.read_threads, [])
