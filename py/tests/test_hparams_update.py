"""Tests for the hyper-parameter pane update endpoint.

``POST /experiments/hparams/update`` is the dedicated write path for
``hparams`` windows — the generic ``/update`` endpoint only understands
plot-shaped content. These tests run end-to-end through a real
:class:`~visdom.server.app.Application` with Tornado's ``AsyncHTTPTestCase``:
a pane is created via ``/experiments/hparams``, updated, and inspected both in
the app state and in the env file on disk, since the endpoint promises the two
stay in step.

The endpoint reads and saves on the storage worker, so the loop keeps serving
while a pane is rebuilt; the last two classes check that no store call it makes
runs on the loop, and that a pane changed underneath a parked rebuild is
answered from what it is now rather than what it was when the rebuild started.
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

from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore
from visdom.server.app import Application
from visdom.server.handlers.experiments_handler import ExperimentHparamsHandler

from testutils.fakes import SpyStore

pytestmark = pytest.mark.integration


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


def seed_runs(store):
    """Log two runs whose ``lr`` puts them on either side of 0.01."""
    store.log_experiment("run-a", params={"lr": 0.1})
    store.log_metric("run-a", "acc", 0.80)
    store.log_experiment("run-b", params={"lr": 0.001})
    store.log_metric("run-b", "acc", 0.95)


def seed_pane(env_path, eid, win, spec):
    """Write an env holding one hparams pane straight to disk."""
    JSONStore(env_path).save_env(
        eid,
        {
            "jsons": {
                win: {
                    "id": win,
                    "i": 0,
                    "type": "hparams",
                    "title": "Sweep",
                    "content": {"records": []},
                    "contentID": "seeded",
                    "hparams": spec,
                }
            },
            "reload": {},
        },
    )


class TestHparamsUpdateStaysOffTheLoop(tornado.testing.AsyncHTTPTestCase):
    """Rebuilding a pane reads and writes disk, and none of it on the loop.

    A bare refresh re-runs a selection that may read every environment file the
    store knows. The live refresh drives the same code from a timer, once per
    logged burst, so on the loop it would stall the server for every run that
    logs while a pane shows it.
    """

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_hparams_update_loop_")
        # Seeded before the app is built, so the runs and the pane's env exist
        # only on disk: the server knows them by their files alone.
        seed_runs(ExperimentStore(JSONStore(self._tmp_dir)))
        seed_pane(
            self._tmp_dir,
            "dash",
            "hp1",
            {"query": None, "env_ids": ["run-a", "run-b"], "mode": "env_ids"},
        )
        super().setUp()
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

    def update(self, body):
        return self.fetch(
            "/experiments/hparams/update",
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def records(self):
        win = self._app.state["dash"]["jsons"]["hp1"]
        return {record["env_id"]: record for record in win["content"]["records"]}

    def on_loop(self):
        return [
            (method, name)
            for method, name in self.spy.threads
            if not name.startswith("visdom-storage")
        ]

    def assertReachedOffLoop(self, *methods):
        """Each of ``methods`` reached the store, and only on the storage worker."""
        for method in methods:
            ran = [name for called, name in self.spy.threads if called == method]
            self.assertTrue(ran, "{0} never reached the store".format(method))
            for name in ran:
                self.assertTrue(name.startswith("visdom-storage"), (method, name))

    def test_a_refresh_reads_its_selection_on_the_storage_worker(self):
        resp = self.update({"eid": "dash", "win": "hp1"})

        self.assertEqual(resp.code, 200)
        self.assertEqual(sorted(self.records()), ["run-a", "run-b"])
        self.assertReachedOffLoop("load_experiment")

    def test_a_new_query_reads_on_the_storage_worker(self):
        resp = self.update({"eid": "dash", "win": "hp1", "query": "lr < 0.01"})

        self.assertEqual(resp.code, 200)
        self.assertEqual(list(self.records()), ["run-b"])
        self.assertReachedOffLoop("list_envs", "load_experiment")

    def test_the_rebuilt_pane_is_saved_on_the_storage_worker(self):
        resp = self.update({"eid": "dash", "win": "hp1"})

        self.assertEqual(resp.code, 200)
        self.assertIn("dash", self.spy.calls["save_env"])
        self.assertReachedOffLoop("save_env")

    def test_no_store_call_the_request_makes_runs_on_the_loop(self):
        """Finding the pane reads its env too; that read is not exempt.

        ``dash`` is known only by its file, so looking the window up has to
        bring the env in off disk first.
        """
        resp = self.update({"eid": "dash", "win": "hp1"})

        self.assertEqual(resp.code, 200)
        self.assertIn("dash", self.spy.calls["load_env"])
        self.assertEqual(self.on_loop(), [])

    def test_a_pane_in_an_env_known_only_by_its_file_is_found(self):
        """An update to a cold env is not a 404 for the window it holds."""
        resp = self.update({"eid": "dash", "win": "hp1", "opts": {"title": "v2"}})

        self.assertEqual(resp.code, 200)
        self.assertEqual(self._app.state["dash"]["jsons"]["hp1"]["title"], "v2")

    def test_a_live_refresh_touches_disk_only_on_the_storage_worker(self):
        """The queue drives the same rebuild, and holds the same line."""
        self.update({"eid": "dash", "win": "hp1"})
        drains = []
        self._app.live_updates._schedule = lambda delay, drain: drains.append(drain)
        before = self._app.state["dash"]["jsons"]["hp1"]["contentID"]
        self.spy.threads.clear()

        self._app.live_updates.mark("run-a")
        self.io_loop.run_sync(drains[0])

        self.assertNotEqual(
            self._app.state["dash"]["jsons"]["hp1"]["contentID"], before
        )
        self.assertReachedOffLoop("load_experiment", "save_env")
        self.assertEqual(self.on_loop(), [])


class TestHparamsUpdateRaces(tornado.testing.AsyncHTTPTestCase):
    """The loop serves other requests while a rebuild reads its selection.

    Each test parks one rebuild on its selection, changes the pane from the
    loop, then lets the rebuild go. The rebuild is held with events rather than
    by yielding a few times, so the interleaving does not depend on how quickly
    the storage worker happens to answer.
    """

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_hparams_update_race_")
        super().setUp()
        seed_runs(ExperimentStore(self._app.storage))
        self.held = []

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def get_app(self):
        self._app = Application(port=self.get_http_port(), env_path=self._tmp_dir)
        return self._app

    def post(self, path, body):
        return self.http_client.fetch(
            self.get_url(path),
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
            raise_error=False,
        )

    def hold_selections(self):
        """Park every selection until the test releases it.

        Returns a patch whose selections announce themselves on ``self.held``
        as ``(started, release)`` event pairs, in the order they begin.
        """
        build = ExperimentHparamsHandler._build_content_off_loop

        async def held_build(handler, spec):
            started, release = asyncio.Event(), asyncio.Event()
            self.held.append((started, release))
            started.set()
            await release.wait()
            return await build(handler, spec)

        return mock.patch.object(
            ExperimentHparamsHandler,
            "_build_content_off_loop",
            staticmethod(held_build),
        )

    async def wait_held(self, count):
        """Wait until ``count`` selections are parked."""
        while len(self.held) < count:
            await asyncio.sleep(0.001)
        await self.held[count - 1][0].wait()

    def window(self, eid="main"):
        return self._app.state[eid]["jsons"].get("hp1")

    @tornado.testing.gen_test
    async def test_a_window_closed_during_the_read_is_404(self):
        await self.post("/experiments/hparams", {"env_ids": ["run-a"], "win": "hp1"})

        with self.hold_selections():
            pending = self.post("/experiments/hparams/update", {"win": "hp1"})
            await self.wait_held(1)
            del self._app.state["main"]["jsons"]["hp1"]
            self.held[0][1].set()
            resp = await pending

        self.assertEqual(resp.code, 404)
        self.assertIsNone(self.window())

    @tornado.testing.gen_test
    async def test_a_window_retyped_during_the_read_is_400(self):
        await self.post("/experiments/hparams", {"env_ids": ["run-a"], "win": "hp1"})

        with self.hold_selections():
            pending = self.post("/experiments/hparams/update", {"win": "hp1"})
            await self.wait_held(1)
            self._app.state["main"]["jsons"]["hp1"] = {"id": "hp1", "type": "text"}
            self.held[0][1].set()
            resp = await pending

        self.assertEqual(resp.code, 400)
        self.assertEqual(self.window()["type"], "text")

    @tornado.testing.gen_test
    async def test_an_env_deleted_during_the_read_is_not_brought_back(self):
        await self.post(
            "/experiments/hparams",
            {"env_ids": ["run-a"], "win": "hp1", "eid": "dash"},
        )

        with self.hold_selections():
            pending = self.post(
                "/experiments/hparams/update", {"win": "hp1", "eid": "dash"}
            )
            await self.wait_held(1)
            del self._app.state["dash"]
            self.held[0][1].set()
            resp = await pending

        self.assertEqual(resp.code, 404)
        self.assertNotIn("dash", self._app.state)

    @tornado.testing.gen_test
    async def test_a_refresh_does_not_undo_a_newer_selection(self):
        """A refresh that read the old selection must not write it back.

        The explicit update starts first and the refresh starts while it is
        still reading, so the refresh has the old selection in hand when the
        new one lands. Rebuilding from it would silently put the pane back.
        """
        await self.post("/experiments/hparams", {"query": "lr < 0.01", "win": "hp1"})

        with self.hold_selections():
            replace = self.post(
                "/experiments/hparams/update", {"win": "hp1", "query": "lr < 1"}
            )
            await self.wait_held(1)
            refresh = self.post("/experiments/hparams/update", {"win": "hp1"})
            await self.wait_held(2)

            self.held[0][1].set()
            replaced = await replace
            content_id = self.window()["contentID"]
            self.held[1][1].set()
            refreshed = await refresh

        self.assertEqual((replaced.code, refreshed.code), (200, 200))
        self.assertEqual(refreshed.body.decode(), "hp1")
        self.assertEqual(self.window()["hparams"]["query"], "lr < 1")
        self.assertEqual(self.window()["contentID"], content_id)
        records = self.window()["content"]["records"]
        self.assertEqual(
            sorted(record["env_id"] for record in records), ["run-a", "run-b"]
        )

    @tornado.testing.gen_test
    async def test_an_explicit_update_does_not_undo_a_newer_rebuild(self):
        """The older of two overlapping selections must not win the pane.

        Both name their own selection, so neither is caught by the refresh
        check; the one that started first finishes last, and writing it would
        replace the newer pane with older content and queue a snapshot of it
        behind the newer save.
        """
        await self.post("/experiments/hparams", {"query": "lr < 0.01", "win": "hp1"})

        with self.hold_selections():
            older = self.post(
                "/experiments/hparams/update", {"win": "hp1", "query": "lr < 1"}
            )
            await self.wait_held(1)
            newer = self.post(
                "/experiments/hparams/update", {"win": "hp1", "env_ids": ["run-b"]}
            )
            await self.wait_held(2)

            self.held[1][1].set()
            newer_resp = await newer
            content_id = self.window()["contentID"]
            self.held[0][1].set()
            older_resp = await older

        self.assertEqual((older_resp.code, newer_resp.code), (200, 200))
        self.assertEqual(older_resp.body.decode(), "hp1")
        self.assertEqual(self.window()["hparams"]["env_ids"], ["run-b"])
        self.assertEqual(self.window()["contentID"], content_id)
        records = self.window()["content"]["records"]
        self.assertEqual([record["env_id"] for record in records], ["run-b"])

    @tornado.testing.gen_test
    async def test_an_explicit_update_outlives_an_edit_to_the_window(self):
        """Only a rebuild of the pane drops one: a rename is not content.

        The window dict is replaced while the selection is read, but no new
        content came with it, so the update it was racing still lands -- and on
        the window as it is now.
        """
        await self.post("/experiments/hparams", {"env_ids": ["run-a"], "win": "hp1"})

        with self.hold_selections():
            pending = self.post(
                "/experiments/hparams/update", {"win": "hp1", "env_ids": ["run-b"]}
            )
            await self.wait_held(1)
            self._app.state["main"]["jsons"]["hp1"] = dict(
                self.window(), title="renamed"
            )
            self.held[0][1].set()
            resp = await pending

        self.assertEqual(resp.code, 200)
        self.assertEqual(self.window()["title"], "renamed")
        self.assertEqual(self.window()["hparams"]["env_ids"], ["run-b"])
        records = self.window()["content"]["records"]
        self.assertEqual([record["env_id"] for record in records], ["run-b"])

    @tornado.testing.gen_test
    async def test_opts_changed_during_the_read_are_kept(self):
        """The rebuilt pane takes its title from the window as it is now."""
        await self.post("/experiments/hparams", {"env_ids": ["run-a"], "win": "hp1"})

        with self.hold_selections():
            pending = self.post("/experiments/hparams/update", {"win": "hp1"})
            await self.wait_held(1)
            self._app.state["main"]["jsons"]["hp1"] = dict(
                self.window(), title="renamed"
            )
            self.held[0][1].set()
            resp = await pending

        self.assertEqual(resp.code, 200)
        self.assertEqual(self.window()["title"], "renamed")


if __name__ == "__main__":
    unittest.main()
