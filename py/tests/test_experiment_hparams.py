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

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import pytest
import tornado.testing
import tornado.web

from visdom.data_model import JSONStore
from visdom.experiments import METADATA_KEY, ExperimentStore, flatten_experiments
from visdom.server.app import Application
from visdom.server.handlers.experiments_handler import (
    ExperimentHparamsHandler,
    _select_hparams,
)
from visdom.utils.server_utils import LazyEnvData

from testutils.fakes import FakeHandler, SpyStore
from testutils.payloads import env_payload

pytestmark = pytest.mark.integration


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

    def test_window_carries_its_selection(self):
        """The resolved selection is stored on the window for later updates."""
        resp = self.hparams({"query": "lr < 0.01"})
        self.assertEqual(
            self._window(resp)["hparams"],
            {"query": "lr < 0.01", "env_ids": None, "mode": "query"},
        )

    def test_pane_is_on_disk_at_creation(self):
        """Creating the pane saves the env, so the pane survives a crash."""
        resp = self.hparams({"query": "lr < 0.01", "win": "hp1"})
        self.assertEqual(resp.code, 200)
        with open(os.path.join(self._tmp_dir, "main.json")) as fn:
            env = json.load(fn)
        window = env["jsons"]["hp1"]
        self.assertEqual(window["type"], "hparams")
        self.assertEqual(window["hparams"]["query"], "lr < 0.01")
        self.assertEqual(
            [record["env_id"] for record in window["content"]["records"]],
            ["run-b"],
        )

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


def edit_tags_in_memory(env_path, env_id, tags):
    """Load ``env_id`` whole and retag it without writing the change to disk.

    Returns the env, which now answers with ``tags`` while its file still holds
    the old ones -- the state an env is in between an edit and the autosave.
    """
    env = JSONStore(env_path).load_env(env_id)
    ExperimentStore(
        JSONStore(env_path),
        env_provider=lambda eid: env if eid == env_id else None,
        persist=lambda eid, data: None,
    ).update_tags(env_id, tags)
    return env


class TestHparamsPaneStaysOffTheLoop(tornado.testing.AsyncHTTPTestCase):
    """Building a pane reads and writes disk, and none of it on the loop.

    A query selection reads the metadata of every environment the store knows,
    and an ``env_ids`` one a file per id -- each of them a whole environment
    file to parse. Done on the loop, that is every other request and socket
    stalled for as long as the reads take.
    """

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_hparams_loop_")
        # Seeded before the app is built, so the runs exist only on disk: the
        # server knows them by their files and has never materialised them.
        seed_experiments(ExperimentStore(JSONStore(self._tmp_dir)))
        super().setUp()
        # Booting lists the env directory to build the lazy state; only what a
        # request goes on to do counts here.
        self.spy.threads.clear()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def get_app(self):
        # ``ServerState`` takes its own reference to the store at construction,
        # so the spy has to be the store the app builds for itself.
        with mock.patch("visdom.server.app.JSONStore", SpyStore):
            self._app = Application(port=self.get_http_port(), env_path=self._tmp_dir)
        self.spy = self._app.storage
        return self._app

    def hparams(self, body):
        return self.fetch(
            "/experiments/hparams",
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def records(self, resp):
        win = self._app.state["main"]["jsons"][resp.body.decode()]
        return {record["env_id"]: record for record in win["content"]["records"]}

    def assertReachedOffLoop(self, *methods):
        """Each of ``methods`` reached the store, and only on the storage worker."""
        for method in methods:
            ran = [name for called, name in self.spy.threads if called == method]
            self.assertTrue(ran, "{0} never reached the store".format(method))
            for name in ran:
                self.assertTrue(name.startswith("visdom-storage"), (method, name))

    def test_a_query_selection_reads_on_the_storage_worker(self):
        resp = self.hparams({"query": "lr < 0.01"})

        self.assertEqual(resp.code, 200)
        self.assertEqual(list(self.records(resp)), ["run-b"])
        self.assertReachedOffLoop("list_envs", "load_experiment")

    def test_an_env_ids_selection_reads_on_the_storage_worker(self):
        resp = self.hparams({"env_ids": ["run-c", "run-a"]})

        self.assertEqual(resp.code, 200)
        self.assertEqual(self.spy.calls["load_experiment"], ["run-c", "run-a"])
        self.assertReachedOffLoop("load_experiment")

    def test_the_pane_is_saved_on_the_storage_worker(self):
        resp = self.hparams({"env_ids": ["run-a"]})

        self.assertEqual(resp.code, 200)
        self.assertIn("main", self.spy.calls["save_env"])
        self.assertReachedOffLoop("save_env")

    def test_no_store_call_the_request_makes_runs_on_the_loop(self):
        """Registering the window reads its env too; that read is not exempt.

        The pane goes into ``run-a``, which the server knows only by its file,
        so putting a window in it has to bring the env in off disk first.
        """
        resp = self.hparams({"query": "epochs > 0", "eid": "run-a", "win": "hp"})

        self.assertEqual(resp.code, 200)
        self.assertTrue(self.spy.threads)
        on_loop = [
            (method, name)
            for method, name in self.spy.threads
            if not name.startswith("visdom-storage")
        ]
        self.assertEqual(on_loop, [])

    def test_a_disk_only_env_keeps_the_windows_its_file_holds(self):
        """A pane lands in an env the server has never seen without losing it.

        The file is written after the app has booted, so ``state`` has no entry
        for it at all -- not even a cold one. Registering a window into an id
        ``state`` does not know creates an empty env, and saving that env is
        what puts an empty file over one full of windows, so the env has to be
        read back off disk before the pane goes into it.
        """
        JSONStore(self._tmp_dir).save_env("late", env_payload("plot_0"))

        resp = self.hparams({"env_ids": ["run-a"], "eid": "late"})

        self.assertEqual(resp.code, 200)
        self.assertIn("plot_0", self._app.state["late"]["jsons"])
        saved = JSONStore(self._tmp_dir).load_env("late")
        self.assertEqual(sorted(saved["jsons"]), sorted(["plot_0", resp.body.decode()]))
        self.assertReachedOffLoop("load_env")

    def test_an_env_held_in_memory_wins_over_its_file(self):
        """The worker reads files, but an env the server is holding answers
        from the copy the loop took of it, never from its stale file."""
        self._app.state["run-a"] = edit_tags_in_memory(
            self._tmp_dir, "run-a", {"dataset": "memory-only"}
        )
        self.spy.calls["load_experiment"].clear()

        resp = self.hparams({"env_ids": ["run-a", "run-b"]})

        self.assertEqual(resp.code, 200)
        self.assertEqual(
            self.records(resp)["run-a"]["tags"], {"dataset": "memory-only"}
        )
        self.assertEqual(self.spy.calls["load_experiment"], ["run-b"])


class TestSelectHparams(unittest.TestCase):
    """The worker half of the endpoint, driven without a server."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        seed_experiments(ExperimentStore(JSONStore(self._tmp.name)))
        self.store = SpyStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def spec(self, env_ids):
        return ExperimentHparamsHandler._resolve_spec(None, env_ids, None)

    def test_a_resident_copy_is_served_without_reading_its_file(self):
        env = edit_tags_in_memory(self._tmp.name, "run-a", {"dataset": "memory-only"})
        resident = {"run-a": {METADATA_KEY: env[METADATA_KEY]}}

        content = _select_hparams(self.store, self.spec(["run-a"]), resident)

        self.assertEqual(content["records"][0]["tags"], {"dataset": "memory-only"})
        self.assertEqual(self.store.calls["load_experiment"], [])

    def test_an_id_with_no_experiment_is_still_a_404(self):
        with self.assertRaises(tornado.web.HTTPError) as caught:
            _select_hparams(self.store, self.spec(["run-a", "ghost"]), {})

        self.assertEqual(caught.exception.status_code, 404)


class TestHparamsPaneRejectsAStaleEnv(unittest.TestCase):
    """The env a pane targets has to be the same env when the pane is written.

    Selecting the runs and materialising the destination both yield the loop,
    and a delete or a fork landing in between leaves a different env -- or none
    at all -- under the id the request named. Registering the window regardless
    would put the pane in an env nobody asked for, or bring a just-deleted one
    back, and then save it there.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        seed_experiments(ExperimentStore(JSONStore(self._tmp.name)))
        self.store = SpyStore(self._tmp.name)
        self.handler = FakeHandler(state={}, storage=self.store)

    def tearDown(self):
        self._tmp.cleanup()

    def build_pane(self, eid, meanwhile=None):
        """Run the endpoint, letting ``meanwhile`` edit state mid-build.

        It stands in for whatever else the loop ran while the selection was on
        the storage worker: the selection itself has no bearing on the check,
        so it is replaced rather than raced against.
        """

        async def selection(handler, spec):
            if meanwhile is not None:
                meanwhile(handler)
            return flatten_experiments([])

        with mock.patch.object(
            ExperimentHparamsHandler,
            "_build_content_off_loop",
            staticmethod(selection),
        ):
            asyncio.run(
                ExperimentHparamsHandler.wrap_func(
                    self.handler, {"env_ids": ["run-a"], "eid": eid}
                )
            )

    def delete_env(self, handler):
        """Take an env out of state the way ``DeleteEnvHandler`` does."""
        handler.state.pop("main", None)
        handler.deleting_envs["main"] = 1

    def test_an_env_replaced_mid_build_is_rejected(self):
        self.handler.state["main"] = env_payload("plot_0")
        replacement = env_payload("other_0")

        def replace(handler):
            handler.state["main"] = replacement

        with self.assertRaises(tornado.web.HTTPError) as caught:
            self.build_pane("main", replace)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(list(replacement["jsons"]), ["other_0"])
        self.assertEqual(self.store.calls["save_env"], [])

    def test_an_env_deleted_mid_build_is_not_recreated(self):
        self.handler.state["main"] = env_payload("plot_0")

        with self.assertRaises(tornado.web.HTTPError) as caught:
            self.build_pane("main", self.delete_env)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertNotIn("main", self.handler.state)
        self.assertEqual(self.store.calls["save_env"], [])

    def test_an_env_absent_from_the_start_is_created(self):
        """Nothing was there to go stale, so the pane creates the env."""
        self.build_pane("fresh")

        self.assertEqual(self.store.calls["save_env"], ["fresh"])
        window_id = self.handler.body
        self.assertEqual(
            self.handler.state["fresh"]["jsons"][window_id]["type"], "hparams"
        )

    def test_a_cold_env_primed_in_place_is_not_stale(self):
        """Priming a ``LazyEnvData`` edits the object state already holds.

        The identity the check compares is the entry's, not its contents', so
        the read every cold destination needs must not read as a replacement.
        """
        self.store.save_env("cold", env_payload("plot_0"))
        self.handler.state["cold"] = LazyEnvData(self.store, "cold")
        self.store.calls["save_env"].clear()

        self.build_pane("cold")

        self.assertEqual(self.store.calls["save_env"], ["cold"])
        self.assertIn("plot_0", self.handler.state["cold"]["jsons"])
