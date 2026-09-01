#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for live hyper-parameter panes.

Logging a run marks its environment on a queue
(:class:`~visdom.experiments.live.LiveUpdateQueue`); a drain asks
:func:`~visdom.experiments.live.resolve_targets` which panes that could affect
and refreshes each through the ``experiments/hparams/update`` handler.

The two decisions are tested on their own — which panes a change reaches, and
when a burst of marks turns into a rebuild — and then end to end through a real
:class:`~visdom.server.app.Application`, where a pane is created, a run is
logged, and the pane is expected to grow without anyone asking it to.
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest

import pytest
import tornado.testing
import tornado.web

from visdom.experiments import ExperimentStore, LiveUpdateQueue, resolve_targets
from visdom.server.app import Application


def hparams_window(mode, query=None, env_ids=None):
    """A stored hparams window, as the pane endpoints write it."""
    return {
        "type": "hparams",
        "content": {"records": []},
        "hparams": {"query": query, "env_ids": env_ids, "mode": mode},
    }


@pytest.mark.unit
class TestResolveTargets(unittest.TestCase):
    """resolve_targets names the panes a set of changed envs could affect."""

    def test_query_pane_is_affected_by_any_change(self):
        """A query can start matching a run it did not match before."""
        state = {"main": {"jsons": {"hp1": hparams_window("query", query="lr < 1")}}}
        self.assertEqual(resolve_targets(state, {"unrelated"}), [("main", "hp1")])

    def test_env_ids_pane_only_follows_the_runs_it_names(self):
        """An explicit selection cannot grow, so unnamed runs leave it alone."""
        state = {
            "main": {"jsons": {"hp1": hparams_window("env_ids", env_ids=["run-a"])}}
        }
        self.assertEqual(resolve_targets(state, {"run-a"}), [("main", "hp1")])
        self.assertEqual(resolve_targets(state, {"run-b"}), [])

    def test_unhashable_env_ids_entries_are_ignored(self):
        """A stored id that is not a string names no run and cannot be hashed."""
        state = {
            "main": {
                "jsons": {
                    "hp1": hparams_window(
                        "env_ids", env_ids=[{"eid": "run-b"}, "run-a"]
                    )
                }
            }
        }
        self.assertEqual(resolve_targets(state, {"run-a"}), [("main", "hp1")])
        self.assertEqual(resolve_targets(state, {"run-b"}), [])

    def test_env_ids_that_are_not_a_list_name_nothing(self):
        """``env_ids`` written as a mapping is not a selection, so nothing matches."""
        state = {
            "main": {"jsons": {"hp1": hparams_window("env_ids", env_ids={"run-a": 1})}}
        }
        self.assertEqual(resolve_targets(state, {"run-a"}), [])

    def test_both_pane_is_affected_by_any_change(self):
        """``both`` still holds a query, so it is re-run like any other query."""
        state = {
            "main": {
                "jsons": {
                    "hp1": hparams_window("both", query="lr < 1", env_ids=["run-a"])
                }
            }
        }
        self.assertEqual(resolve_targets(state, {"run-b"}), [("main", "hp1")])

    def test_other_window_types_are_left_alone(self):
        """Only hparams panes are rebuilt from a selection."""
        state = {
            "main": {
                "jsons": {
                    "plot": {"type": "plot", "content": {}},
                    "text": {"type": "text", "content": ""},
                    "hp1": hparams_window("query", query="lr < 1"),
                }
            }
        }
        self.assertEqual(resolve_targets(state, {"run-a"}), [("main", "hp1")])

    def test_hparams_window_without_a_stored_spec_is_skipped(self):
        """A pane predating stored selections has nothing to re-run."""
        state = {"main": {"jsons": {"hp1": {"type": "hparams", "content": {}}}}}
        self.assertEqual(resolve_targets(state, {"run-a"}), [])

    def test_no_changes_resolves_to_nothing(self):
        """An empty drain does not walk the state at all."""
        state = {"main": {"jsons": {"hp1": hparams_window("query", query="lr < 1")}}}
        self.assertEqual(resolve_targets(state, set()), [])

    def test_panes_across_envs_are_all_named(self):
        """A run can be shown by panes living in several environments."""
        state = {
            "main": {"jsons": {"hp1": hparams_window("query", query="lr < 1")}},
            "other": {"jsons": {"hp2": hparams_window("query", query="acc > 0")}},
        }
        self.assertEqual(
            sorted(resolve_targets(state, {"run-a"})),
            [("main", "hp1"), ("other", "hp2")],
        )

    def test_unloaded_envs_are_not_paged_in(self):
        """A cold env is skipped: nobody is watching it, and reading it costs a file."""

        class ColdEnv(dict):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.touched = False

            @property
            def is_loaded(self):
                return False

            def get(self, key, default=None):
                self.touched = True
                return super().get(key, default)

        cold = ColdEnv({"jsons": {"hp1": hparams_window("query", query="lr < 1")}})
        self.assertEqual(resolve_targets({"main": cold}, {"run-a"}), [])
        self.assertFalse(cold.touched)


@pytest.mark.unit
class TestLiveUpdateQueue(unittest.TestCase):
    """The queue coalesces marks and survives a rebuild that fails."""

    def setUp(self):
        self.scheduled = []
        self.resolved = []
        self.rebuilt = []

    def schedule(self, delay, callback):
        self.scheduled.append((delay, callback))

    def resolve(self, changed):
        self.resolved.append(set(changed))
        return [("main", "hp1")]

    def rebuild(self, eid, win_id):
        self.rebuilt.append((eid, win_id))

    def queue(self, **kwargs):
        kwargs.setdefault("resolve", self.resolve)
        kwargs.setdefault("rebuild", self.rebuild)
        kwargs.setdefault("schedule", self.schedule)
        return LiveUpdateQueue(**kwargs)

    def test_a_burst_of_marks_costs_one_drain(self):
        """A training loop logging every step must not rebuild every step."""
        queue = self.queue()
        for _ in range(5):
            queue.mark("run-a")
        queue.mark("run-b")

        self.assertEqual(len(self.scheduled), 1)
        self.scheduled[0][1]()
        self.assertEqual(self.resolved, [{"run-a", "run-b"}])
        self.assertEqual(self.rebuilt, [("main", "hp1")])

    def test_the_delay_is_handed_to_the_scheduler(self):
        """The debounce window is the queue's, not the scheduler's."""
        self.queue(delay=2.5).mark("run-a")
        self.assertEqual(self.scheduled[0][0], 2.5)

    def test_marks_after_a_drain_schedule_the_next_one(self):
        """The queue re-arms rather than going quiet after its first drain."""
        queue = self.queue()
        queue.mark("run-a")
        self.scheduled[0][1]()
        queue.mark("run-b")

        self.assertEqual(len(self.scheduled), 2)
        self.scheduled[1][1]()
        self.assertEqual(self.resolved, [{"run-a"}, {"run-b"}])

    def test_a_mark_during_a_drain_is_not_swallowed(self):
        """Marks are taken before rebuilding, so a late one opens a new round."""
        queue = self.queue()

        def rebuild_and_mark(eid, win_id):
            self.rebuilt.append((eid, win_id))
            queue.mark("run-late")

        queue._rebuild = rebuild_and_mark
        queue.mark("run-a")
        self.scheduled[0][1]()

        self.assertEqual(len(self.scheduled), 2)
        self.scheduled[1][1]()
        self.assertEqual(self.resolved, [{"run-a"}, {"run-late"}])

    def test_an_empty_drain_does_nothing(self):
        """A drain with nothing pending must not resolve or rebuild."""
        self.queue().drain()
        self.assertEqual(self.resolved, [])
        self.assertEqual(self.rebuilt, [])

    def test_a_failing_rebuild_does_not_stop_the_others(self):
        """One unbuildable pane must not cost the rest their update."""
        attempted = []

        def rebuild(eid, win_id):
            attempted.append(win_id)
            if win_id == "hp1":
                raise RuntimeError("boom")

        queue = self.queue(
            resolve=lambda changed: [("main", "hp1"), ("main", "hp2")],
            rebuild=rebuild,
        )
        queue.mark("run-a")
        with self.assertLogs(level="ERROR"):
            self.scheduled[0][1]()

        self.assertEqual(attempted, ["hp1", "hp2"])

    def test_a_failing_resolve_does_not_take_the_drain_down(self):
        """A resolver that raises is logged, not propagated into the caller."""

        def resolve(changed):
            raise RuntimeError("bad state")

        queue = self.queue(resolve=resolve)
        queue.mark("run-a")
        with self.assertLogs(level="ERROR"):
            self.scheduled[0][1]()

        self.assertEqual(self.rebuilt, [])

    def test_the_queue_re_arms_after_a_failing_resolve(self):
        """A lost batch must not leave the queue permanently disarmed."""
        failing = [True]

        def resolve(changed):
            if failing[0]:
                raise RuntimeError("bad state")
            return [("main", "hp1")]

        queue = self.queue(resolve=resolve)
        queue.mark("run-a")
        with self.assertLogs(level="ERROR"):
            self.scheduled[0][1]()

        failing[0] = False
        queue.mark("run-b")
        self.assertEqual(len(self.scheduled), 2)
        self.scheduled[1][1]()
        self.assertEqual(self.rebuilt, [("main", "hp1")])

    def test_a_failing_schedule_leaves_the_queue_usable(self):
        """A queue that could not arm itself must still arm on the next mark."""

        def schedule(delay, callback):
            raise RuntimeError("no loop")

        queue = self.queue(schedule=schedule)
        with self.assertLogs(level="ERROR"):
            queue.mark("run-a")

        queue._schedule = self.schedule
        queue.mark("run-b")
        self.assertEqual(len(self.scheduled), 1)
        self.scheduled[0][1]()
        self.assertEqual(self.resolved, [{"run-a", "run-b"}])

    def test_without_a_scheduler_a_mark_drains_inline(self):
        """With no loop to defer onto the work still happens, just immediately."""
        self.queue(schedule=None).mark("run-a")
        self.assertEqual(self.resolved, [{"run-a"}])
        self.assertEqual(self.rebuilt, [("main", "hp1")])


@pytest.mark.integration
class TestLiveHparamsPanes(tornado.testing.AsyncHTTPTestCase):
    """Logging a run refreshes the panes that show it, in state and on disk."""

    DEBOUNCE = 0.05

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_hparams_live_")
        super().setUp()
        self._app.live_updates._delay = self.DEBOUNCE
        self.store = ExperimentStore(self._app.storage)
        self.store.log_experiment("run-a", params={"lr": 0.005})
        self.store.log_metric("run-a", "acc", 0.80)

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

    def log(self, body):
        return self._post("/experiments/log", body)

    def settle(self):
        """Let the debounced drain run."""
        self.io_loop.run_sync(lambda: asyncio.sleep(self.DEBOUNCE * 4))

    def _window(self, win_id, eid="main"):
        return self._app.state[eid]["jsons"][win_id]

    def _env_ids(self, win_id, eid="main"):
        return sorted(
            record["env_id"]
            for record in self._window(win_id, eid)["content"]["records"]
        )

    def _disk_env(self, eid="main"):
        with open(os.path.join(self._tmp_dir, eid + ".json")) as fn:
            return json.load(fn)

    def test_a_newly_logged_run_joins_a_matching_pane(self):
        """The pane picks up a run that did not exist when it was built."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.assertEqual(self._env_ids("hp1"), ["run-a"])

        self.log({"eid": "run-b", "params": {"lr": 0.001}})
        self.settle()

        self.assertEqual(self._env_ids("hp1"), ["run-a", "run-b"])

    def test_the_refresh_reaches_disk(self):
        """A live rebuild saves the env, as a requested update does."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.log({"eid": "run-b", "params": {"lr": 0.001}})
        self.settle()

        records = self._disk_env()["jsons"]["hp1"]["content"]["records"]
        self.assertEqual(
            sorted(record["env_id"] for record in records), ["run-a", "run-b"]
        )

    def test_the_pane_keeps_its_id_and_gets_a_new_contentID(self):
        """The client re-renders on contentID, and the pane keeps its place."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        before = self._window("hp1")
        content_id, position = before["contentID"], before["i"]

        self.log({"eid": "run-b", "params": {"lr": 0.001}})
        self.settle()

        after = self._window("hp1")
        self.assertEqual(after["id"], "hp1")
        self.assertEqual(after["i"], position)
        self.assertNotEqual(after["contentID"], content_id)

    def test_logged_metrics_reach_the_pane(self):
        """The metric values shown are the latest ones logged, not the first."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.log({"eid": "run-a", "action": "metrics", "metrics": {"acc": 0.99}})
        self.settle()

        records = self._window("hp1")["content"]["records"]
        by_env = {record["env_id"]: record for record in records}
        self.assertEqual(by_env["run-a"]["metrics"]["acc"], 0.99)

    def test_finishing_a_run_refreshes_the_pane(self):
        """``finish`` changes the status a pane displays, so it counts as a change."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.log({"eid": "run-a", "action": "finish", "status": "finished"})
        self.settle()

        records = self._window("hp1")["content"]["records"]
        by_env = {record["env_id"]: record for record in records}
        self.assertEqual(by_env["run-a"]["status"], "finished")

    def test_an_env_ids_pane_ignores_an_unrelated_run(self):
        """An explicit selection is not rebuilt by a run it does not name."""
        self.create({"env_ids": ["run-a"], "win": "hp1"})
        content_id = self._window("hp1")["contentID"]

        self.log({"eid": "run-b", "params": {"lr": 0.001}})
        self.settle()

        self.assertEqual(self._env_ids("hp1"), ["run-a"])
        self.assertEqual(self._window("hp1")["contentID"], content_id)

    def test_a_burst_of_metrics_rebuilds_the_pane_once(self):
        """Marks coalesce across requests, not just within one.

        The drain is held rather than outrun. Leaving the debounce armed makes
        the claim "five requests finish inside ``DEBOUNCE``", and a burst that
        misses that deadline -- a loaded machine, coverage tracing -- drains
        mid-loop and rebuilds the pane while the marks are still arriving,
        failing on the clock rather than on any coalescing. Capturing the
        callback instead of arming the loop leaves the queue to say it itself:
        five marks arrange exactly one drain.
        """
        self.create({"query": "lr < 0.01", "win": "hp1"})
        queue = self._app.live_updates
        drains = []
        queue._schedule = lambda delay, callback: drains.append(callback)
        content_ids = set()

        for step in range(5):
            self.log(
                {
                    "eid": "run-a",
                    "action": "metrics",
                    "metrics": {"acc": 0.5 + step / 100},
                    "step": step,
                }
            )
            content_ids.add(self._window("hp1")["contentID"])

        self.assertEqual(len(drains), 1)
        self.assertEqual(len(content_ids), 1)

        drains[0]()
        self.assertNotIn(self._window("hp1")["contentID"], content_ids)

    def test_a_pane_closed_before_the_drain_is_skipped(self):
        """Closing a pane mid-flight is a race, not a failure."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        self.create({"query": "lr < 0.01", "win": "hp2"})

        self.log({"eid": "run-b", "params": {"lr": 0.001}})
        del self._app.state["main"]["jsons"]["hp1"]
        self.settle()

        self.assertEqual(self._env_ids("hp2"), ["run-a", "run-b"])
        self.assertNotIn("hp1", self._app.state["main"]["jsons"])

    def test_panes_in_other_envs_are_refreshed_too(self):
        """A pane is refreshed wherever it lives, not only in the logged env."""
        self.create({"query": "lr < 0.01", "win": "hp1", "eid": "dashboard"})

        self.log({"eid": "run-b", "params": {"lr": 0.001}})
        self.settle()

        self.assertEqual(self._env_ids("hp1", eid="dashboard"), ["run-a", "run-b"])

    def test_readonly_servers_never_mark(self):
        """Logging is refused in readonly mode, so no rebuild can follow it."""
        self.create({"query": "lr < 0.01", "win": "hp1"})
        content_id = self._window("hp1")["contentID"]

        self._app.server_state.readonly = True
        resp = self.log({"eid": "run-b", "params": {"lr": 0.001}})
        self.settle()

        self.assertEqual(resp.code, 403)
        self.assertEqual(self._env_ids("hp1"), ["run-a"])
        self.assertEqual(self._window("hp1")["contentID"], content_id)


if __name__ == "__main__":
    unittest.main()
