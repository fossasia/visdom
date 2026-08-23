#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for experiment comparison.

Covers the four pieces the compare layer is built from: the pure
``build_comparison`` diff over experiment objects; ``ExperimentStore.compare``
over the named runs against a real ``JSONStore`` over a temporary
directory; the ``/experiments/compare`` endpoint end-to-end through a real
:class:`~visdom.server.app.Application` with Tornado's ``AsyncHTTPTestCase``; and
the ``Visdom.compare_experiments`` message shape with a mocked transport (no
server).
"""

import json
import math
import tempfile
import unittest
from unittest.mock import Mock, patch

import tornado.testing

from visdom import Visdom
from visdom.data_model import JSONStore
from visdom.experiments import Experiment, ExperimentStore, build_comparison
from visdom.server.app import Application


def seed_experiments(store):
    """Log three experiments with known params/metrics/tags and created_at order.

    run-a and run-b share ``epochs`` and differ on ``lr``; run-c has neither
    ``epochs`` nor any metric, so it exercises the missing-field paths.
    ``created_at`` is stamped explicitly rather than left to wall-clock time,
    since the runs are logged microseconds apart.
    """
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
        params={"lr": 0.001, "epochs": 10},
        tags={"dataset": "cifar10"},
    )
    store.log_metric("run-b", "acc", 0.55)
    store.log_metric("run-b", "acc", 0.95)
    store.finish_experiment("run-b")

    store.log_experiment("run-c", name="gamma", params={"lr": 0.5})

    for env_id, created_at in (("run-a", 100.0), ("run-b", 200.0), ("run-c", 300.0)):
        env, experiment = store._read(env_id)
        experiment.created_at = created_at
        store._write(env_id, env, experiment)


def make_experiment(env_id, params=None, metrics=None, tags=None):
    """Build an in-memory Experiment, for the storage-free diff tests."""
    experiment = Experiment(env_id=env_id)
    for key, value in (params or {}).items():
        experiment.set_param(key, value)
    for key, value in metrics or []:
        experiment.add_metric(key, value)
    for key, value in (tags or {}).items():
        experiment.set_tag(key, value)
    return experiment


class TestBuildComparison(unittest.TestCase):
    """build_comparison diffs experiment objects without touching storage."""

    def test_reports_shared_and_differing_params(self):
        """A field all runs agree on is shared; one that varies is differing."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"lr": 0.1, "epochs": 10}),
                make_experiment("b", params={"lr": 0.2, "epochs": 10}),
            ]
        )
        params = comparison["params"]
        self.assertEqual(params["fields"], ["epochs", "lr"])
        self.assertEqual(params["shared"], {"epochs": 10})
        self.assertEqual(params["differing"], ["lr"])
        self.assertEqual(params["values"]["lr"], {"a": 0.1, "b": 0.2})

    def test_echoes_compared_runs_in_order(self):
        """env_ids and experiments come back in the order compared."""
        comparison = build_comparison(
            [make_experiment("b"), make_experiment("a")],
        )
        self.assertEqual(comparison["env_ids"], ["b", "a"])
        self.assertEqual([e["env_id"] for e in comparison["experiments"]], ["b", "a"])

    def test_field_missing_from_one_run_is_differing(self):
        """A field only some runs carry is a difference, not a consensus."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"lr": 0.1, "seed": 7}),
                make_experiment("b", params={"lr": 0.1}),
            ]
        )
        params = comparison["params"]
        self.assertEqual(params["shared"], {"lr": 0.1})
        self.assertEqual(params["differing"], ["seed"])
        self.assertEqual(params["values"]["seed"], {"a": 7})

    def test_metrics_compare_on_latest_value(self):
        """Metrics are a time series; the comparison uses the most recent one."""
        comparison = build_comparison(
            [
                make_experiment("a", metrics=[("acc", 0.5), ("acc", 0.9)]),
                make_experiment("b", metrics=[("acc", 0.9)]),
            ]
        )
        self.assertEqual(comparison["metrics"]["shared"], {"acc": 0.9})

    def test_tags_are_compared(self):
        """Tags get the same treatment as params and metrics."""
        comparison = build_comparison(
            [
                make_experiment("a", tags={"owner": "mk", "stage": "dev"}),
                make_experiment("b", tags={"owner": "mk", "stage": "prod"}),
            ]
        )
        self.assertEqual(comparison["tags"]["shared"], {"owner": "mk"})
        self.assertEqual(comparison["tags"]["differing"], ["stage"])

    def test_bool_is_not_the_same_as_one(self):
        """True == 1 in Python, but a run using amp=True is not one using amp=1."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"amp": True}),
                make_experiment("b", params={"amp": 1}),
            ]
        )
        self.assertEqual(comparison["params"]["differing"], ["amp"])

    def test_nan_agrees_with_itself(self):
        """NaN != NaN, but a metric NaN in every run is not a difference."""
        comparison = build_comparison(
            [
                make_experiment("a", metrics=[("loss", float("nan"))]),
                make_experiment("b", metrics=[("loss", float("nan"))]),
            ]
        )
        self.assertEqual(comparison["metrics"]["differing"], [])
        self.assertTrue(math.isnan(comparison["metrics"]["shared"]["loss"]))

    def test_single_experiment_shares_everything(self):
        """Comparing one run is degenerate but legal: nothing can differ."""
        comparison = build_comparison([make_experiment("a", params={"lr": 0.1})])
        self.assertEqual(comparison["params"]["shared"], {"lr": 0.1})
        self.assertEqual(comparison["params"]["differing"], [])

    def test_no_experiments_yields_empty_sections(self):
        """Comparing nothing is empty, not an error."""
        comparison = build_comparison([])
        self.assertEqual(comparison["env_ids"], [])
        for section in ("params", "metrics", "tags"):
            self.assertEqual(comparison[section]["fields"], [])
            self.assertEqual(comparison[section]["shared"], {})

    def test_groups_cluster_the_runs_that_agree(self):
        """groups answers which runs match, not just whether all of them do."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"lr": 0.1}),
                make_experiment("b", params={"lr": 0.001}),
                make_experiment("c", params={"lr": 0.1}),
            ]
        )
        self.assertEqual(comparison["params"]["differing"], ["lr"])
        self.assertEqual(
            comparison["params"]["groups"]["lr"],
            [
                {"value": 0.1, "env_ids": ["a", "c"]},
                {"value": 0.001, "env_ids": ["b"]},
            ],
        )

    def test_a_shared_field_is_one_group_of_everyone(self):
        """shared and groups cannot disagree: shared == a single full cluster."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"epochs": 10}),
                make_experiment("b", params={"epochs": 10}),
            ]
        )
        self.assertEqual(comparison["params"]["shared"], {"epochs": 10})
        self.assertEqual(
            comparison["params"]["groups"]["epochs"],
            [{"value": 10, "env_ids": ["a", "b"]}],
        )

    def test_a_run_missing_the_field_is_in_no_group(self):
        """Groups cover only the runs that logged the field."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"lr": 0.1}),
                make_experiment("b", params={"lr": 0.1}),
                make_experiment("c", params={"seed": 7}),
            ]
        )
        self.assertEqual(
            comparison["params"]["groups"]["lr"],
            [{"value": 0.1, "env_ids": ["a", "b"]}],
        )
        self.assertEqual(comparison["params"]["differing"], ["lr", "seed"])

    def test_groups_do_not_merge_a_bool_with_one(self):
        """A dict keyed by value would merge these: hash(True) == hash(1)."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"amp": True}),
                make_experiment("b", params={"amp": 1}),
            ]
        )
        self.assertEqual(
            comparison["params"]["groups"]["amp"],
            [
                {"value": True, "env_ids": ["a"]},
                {"value": 1, "env_ids": ["b"]},
            ],
        )

    def test_groups_cluster_nan_together(self):
        """NaN never equals itself, so a dict would never group these."""
        comparison = build_comparison(
            [
                make_experiment("a", metrics=[("loss", float("nan"))]),
                make_experiment("b", metrics=[("loss", float("nan"))]),
            ]
        )
        groups = comparison["metrics"]["groups"]["loss"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["env_ids"], ["a", "b"])

    def test_groups_handle_unhashable_values(self):
        """A param may hold a list, which could not be a dict key."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"layers": [64, 32]}),
                make_experiment("b", params={"layers": [64, 32]}),
                make_experiment("c", params={"layers": [128]}),
            ]
        )
        self.assertEqual(
            comparison["params"]["groups"]["layers"],
            [
                {"value": [64, 32], "env_ids": ["a", "b"]},
                {"value": [128], "env_ids": ["c"]},
            ],
        )

    def test_group_order_follows_the_compared_order(self):
        """Groups appear in the order their value was first seen."""
        comparison = build_comparison(
            [
                make_experiment("b", params={"lr": 0.001}),
                make_experiment("a", params={"lr": 0.1}),
                make_experiment("c", params={"lr": 0.1}),
            ]
        )
        self.assertEqual(
            [g["value"] for g in comparison["params"]["groups"]["lr"]], [0.001, 0.1]
        )
        self.assertEqual(comparison["params"]["groups"]["lr"][1]["env_ids"], ["a", "c"])

    def test_sections_are_independent(self):
        """A name used as both a param and a tag is not conflated across sections."""
        comparison = build_comparison(
            [
                make_experiment("a", params={"mode": "fast"}, tags={"mode": "slow"}),
                make_experiment("b", params={"mode": "fast"}, tags={"mode": "slow"}),
            ]
        )
        self.assertEqual(comparison["params"]["shared"], {"mode": "fast"})
        self.assertEqual(comparison["tags"]["shared"], {"mode": "slow"})


class TestStoreCompare(unittest.TestCase):
    """ExperimentStore.compare diffs the runs it is given by name."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_compare_")
        self.store = ExperimentStore(JSONStore(self._tmp_dir))
        seed_experiments(self.store)

    def test_compare_by_env_ids(self):
        """An explicit list compares exactly those runs, in order."""
        comparison = self.store.compare(env_ids=["run-b", "run-a"])
        self.assertEqual(comparison["env_ids"], ["run-b", "run-a"])
        self.assertEqual(comparison["params"]["shared"], {"epochs": 10})
        self.assertEqual(comparison["params"]["differing"], ["lr"])

    def test_compare_reads_from_storage(self):
        """Runs come off disk, so a fresh store compares the same experiments."""
        fresh = ExperimentStore(JSONStore(self._tmp_dir))
        comparison = fresh.compare(env_ids=["run-a", "run-b"])
        self.assertEqual(
            comparison["metrics"]["values"]["acc"],
            {
                "run-a": 0.80,
                "run-b": 0.95,
            },
        )

    def test_duplicate_env_ids_collapse(self):
        """Naming a run twice cannot mean anything beyond naming it once."""
        comparison = self.store.compare(env_ids=["run-a", "run-a"])
        self.assertEqual(comparison["env_ids"], ["run-a"])

    def test_unknown_env_id_raises_key_error(self):
        """A comparison silently missing a requested run would mislead."""
        with self.assertRaises(KeyError) as ctx:
            self.store.compare(env_ids=["run-a", "nope"])
        self.assertIn("nope", str(ctx.exception))

    def test_env_without_experiment_raises_key_error(self):
        """An env that exists but has no experiment is still nothing to compare."""
        self.store.datastore.save_env("plain", {"jsons": {}, "reload": {}})
        with self.assertRaises(KeyError):
            self.store.compare(env_ids=["run-a", "plain"])

    def test_empty_env_ids_raises_value_error(self):
        """Comparing an empty list cannot mean anything."""
        with self.assertRaises(ValueError):
            self.store.compare(env_ids=[])

    def test_string_env_ids_raises_type_error(self):
        """A bare string would iterate into a comparison of single characters."""
        with self.assertRaises(TypeError):
            self.store.compare(env_ids="run-a")

    def test_non_string_env_id_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.store.compare(env_ids=["run-a", 7])

    def test_experiment_answers_to_the_env_it_is_stored_under(self):
        """A stale env_id in the blob loses to the env the blob was read from.

        Cloning an env copies its metadata verbatim, so a copy can name the env
        it was cloned from; the env it is stored under is the real one.
        """
        clone = self.store.datastore.load_env("run-a")
        self.store.datastore.save_env("run-a-fork", clone)
        self.assertEqual(clone["experiment"]["env_id"], "run-a")
        self.assertEqual(self.store.get_experiment("run-a-fork").env_id, "run-a-fork")

    def test_cloned_env_compares_as_its_own_run(self):
        """A clone and its source are two runs, not one column keyed twice.

        Comparison is keyed by env_id, so trusting the copied blob's stale id
        would fold the two into a single entry and silently drop a run the
        caller asked for.
        """
        self.store.datastore.save_env(
            "run-a-fork", self.store.datastore.load_env("run-a")
        )
        self.store.log_metric("run-a-fork", "acc", 0.42)

        comparison = self.store.compare(env_ids=["run-a", "run-a-fork"])
        self.assertEqual(comparison["env_ids"], ["run-a", "run-a-fork"])
        self.assertEqual(
            comparison["metrics"]["values"]["acc"],
            {"run-a": 0.80, "run-a-fork": 0.42},
        )
        self.assertEqual(comparison["params"]["shared"], {"lr": 0.1, "epochs": 10})

    def test_searching_then_comparing_the_matches(self):
        """Comparing a query's matches is search's job, then compare's.

        The two compose: search answers which runs match, compare answers how
        they differ. This is the path that replaced compare's own query mode.
        """
        found = self.store.search(query="lr > 0.05", descending=False)
        comparison = self.store.compare([e.env_id for e in found])
        self.assertEqual(comparison["env_ids"], ["run-a", "run-c"])
        self.assertEqual(comparison["params"]["differing"], ["epochs", "lr"])


class TestCompareEndpoint(tornado.testing.AsyncHTTPTestCase):
    """POST /experiments/compare diffs the named experiments."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_compare_api_")
        super().setUp()
        seed_experiments(ExperimentStore(JSONStore(self._tmp_dir)))

    def get_app(self):
        return Application(port=self.get_http_port(), env_path=self._tmp_dir)

    def compare(self, body):
        return self.fetch(
            "/experiments/compare",
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def post_raw(self, body):
        """POST a body verbatim, so malformed JSON reaches the handler."""
        return self.fetch(
            "/experiments/compare",
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )

    def compare_ok(self, body):
        resp = self.compare(body)
        self.assertEqual(resp.code, 200)
        return json.loads(resp.body)

    def post_raw(self, body):
        """POST a body that is not necessarily valid JSON."""
        return self.fetch(
            "/experiments/compare",
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )

    def test_compare_by_env_ids(self):
        """The named runs are compared, in the order given."""
        body = self.compare_ok({"env_ids": ["run-a", "run-b"]})
        self.assertEqual(body["env_ids"], ["run-a", "run-b"])
        self.assertEqual(body["params"]["shared"], {"epochs": 10})
        self.assertEqual(body["params"]["differing"], ["lr"])
        self.assertEqual(body["params"]["values"]["lr"], {"run-a": 0.1, "run-b": 0.001})

    def test_all_sections_are_present(self):
        """params, metrics and tags each come back diffed."""
        body = self.compare_ok({"env_ids": ["run-a", "run-b"]})
        self.assertEqual(body["metrics"]["values"]["acc"]["run-b"], 0.95)
        self.assertEqual(body["tags"]["differing"], ["dataset"])
        self.assertEqual(
            body["tags"]["values"]["dataset"], {"run-a": "mnist", "run-b": "cifar10"}
        )

    def test_groups_survive_the_json_round_trip(self):
        """The clusters reach the client intact, epochs shared and lr split."""
        body = self.compare_ok({"env_ids": ["run-a", "run-b"]})
        self.assertEqual(
            body["params"]["groups"]["epochs"],
            [{"value": 10, "env_ids": ["run-a", "run-b"]}],
        )
        self.assertEqual(
            body["params"]["groups"]["lr"],
            [
                {"value": 0.1, "env_ids": ["run-a"]},
                {"value": 0.001, "env_ids": ["run-b"]},
            ],
        )

    def test_experiments_are_returned_in_full(self):
        """The compared runs are echoed as full experiment dicts."""
        body = self.compare_ok({"env_ids": ["run-a", "run-b"]})
        experiment = body["experiments"][0]
        self.assertEqual(experiment["name"], "alpha")
        self.assertEqual(experiment["params"][0]["key"], "lr")

    def test_unknown_env_id_is_404(self):
        """A run that has no experiment is named in the error."""
        resp = self.compare({"env_ids": ["run-a", "nope"]})
        self.assertEqual(resp.code, 404)
        self.assertIn("nope", resp.reason)

    def test_missing_env_ids_is_400(self):
        """env_ids is the only way to select runs, so it is required."""
        resp = self.compare({})
        self.assertEqual(resp.code, 400)
        self.assertIn("required", resp.reason)
        self.assertEqual(self.compare({"env_ids": None}).code, 400)

    def test_empty_env_ids_is_400(self):
        resp = self.compare({"env_ids": []})
        self.assertEqual(resp.code, 400)

    def test_string_env_ids_is_400(self):
        """A bare string is rejected rather than iterated into characters."""
        resp = self.compare({"env_ids": "run-a"})
        self.assertEqual(resp.code, 400)
        self.assertIn("env_ids", resp.reason)

    def test_non_string_env_id_is_400(self):
        self.assertEqual(self.compare({"env_ids": ["run-a", 7]}).code, 400)

    def test_malformed_json_is_400(self):
        """A body that is not JSON is the caller's error, not a 500.

        Compare decodes the body with the same helper as search, so the two
        endpoints reject the same bodies the same way.
        """
        resp = self.post_raw("{not json")
        self.assertEqual(resp.code, 400)
        self.assertIn("JSON", resp.reason)

    def test_non_object_body_is_400(self):
        """A JSON list or scalar carries no env_ids to read, so reject it."""
        self.assertEqual(self.post_raw('["run-a"]').code, 400)
        self.assertEqual(self.post_raw('"run-a"').code, 400)
        self.assertEqual(self.post_raw("null").code, 400)

    def test_empty_body_is_400(self):
        """Unlike search, compare has nothing to do without env_ids."""
        resp = self.post_raw("")
        self.assertEqual(resp.code, 400)
        self.assertIn("required", resp.reason)

    def test_unknown_keys_are_ignored(self):
        """A stale caller still sending query/limit is not an error, just ignored.

        The endpoint took a `query` until compare's query mode was dropped in
        favour of search; an old client's extra keys must not 500.
        """
        body = self.compare_ok(
            {"env_ids": ["run-a", "run-b"], "query": "lr > 0", "limit": 1}
        )
        self.assertEqual(body["env_ids"], ["run-a", "run-b"])

    def test_traversal_env_id_is_404_not_a_file_read(self):
        """A crafted id cannot escape env_path; it simply names no experiment.

        JSONStore._primary_path resolves the id under env_path and rejects
        anything that would climb out, so this degrades to "no such experiment"
        rather than reading the filesystem.
        """
        resp = self.compare({"env_ids": ["run-a", "../../../../etc/passwd"]})
        self.assertEqual(resp.code, 404)

    def test_compare_sees_an_experiment_logged_over_http(self):
        """An experiment logged through /experiments/log is comparable at once."""
        self.fetch(
            "/experiments/log",
            method="POST",
            body=json.dumps({"eid": "run-e", "action": "log", "params": {"lr": 0.1}}),
            headers={"Content-Type": "application/json"},
        )
        body = self.compare_ok({"env_ids": ["run-a", "run-e"]})
        self.assertEqual(body["params"]["shared"], {"lr": 0.1})


class TestCompareForkedEnv(tornado.testing.AsyncHTTPTestCase):
    """A forked env compares as a run of its own, not as its parent.

    The experiments are seeded before the app is built so the server loads them
    into its state and ``/fork_env`` has something to fork.
    """

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_compare_fork_")
        seed_experiments(ExperimentStore(JSONStore(self._tmp_dir)))
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

    def fork(self, prev_eid, eid):
        resp = self.post_json("/fork_env", {"prev_eid": prev_eid, "eid": eid})
        self.assertEqual(resp.code, 200)
        return resp

    def test_fork_retargets_the_experiment_metadata(self):
        """The clone's stored experiment names the env it now lives in."""
        self.fork("run-a", "run-a-fork")
        store = ExperimentStore(JSONStore(self._tmp_dir))
        self.assertEqual(store.get_experiment("run-a-fork").env_id, "run-a-fork")
        self.assertEqual(store.get_experiment("run-a").env_id, "run-a")

    def test_compare_keeps_a_fork_and_its_parent_apart(self):
        """Comparing a fork against its source diffs two runs, not one."""
        self.fork("run-a", "run-a-fork")
        resp = self.post_json(
            "/experiments/compare", {"env_ids": ["run-a", "run-a-fork"]}
        )
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["env_ids"], ["run-a", "run-a-fork"])
        self.assertEqual(len(body["experiments"]), 2)
        self.assertEqual(
            body["params"]["values"]["lr"], {"run-a": 0.1, "run-a-fork": 0.1}
        )
        self.assertEqual(
            body["params"]["groups"]["lr"],
            [{"value": 0.1, "env_ids": ["run-a", "run-a-fork"]}],
        )


class TestCompareClientMessage(unittest.TestCase):
    """Visdom.compare_experiments builds the message the endpoint expects.

    The transport is mocked to return the ``(msg, endpoint)`` it would have
    posted, so we can assert on it directly.
    """

    def setUp(self):
        with (
            patch.object(Visdom, "_handle_post", return_value=True),
            patch.object(Visdom, "_start_session_reaper"),
        ):
            self.vis = Visdom(raise_exceptions=True, use_incoming_socket=False)

        self.vis._send = Mock(
            side_effect=lambda msg, endpoint="events", **_: (msg, endpoint)
        )

    def test_compare_message_shape(self):
        """The message names the runs and carries no selection knobs."""
        msg, endpoint = self.vis.compare_experiments(["run-a", "run-b"])
        self.assertEqual(endpoint, "experiments/compare")
        self.assertEqual(msg["env_ids"], ["run-a", "run-b"])
        for dropped in ("query", "limit", "sort_by", "descending"):
            self.assertNotIn(dropped, msg)

    def test_tuple_env_ids_is_sent_as_a_list(self):
        """A tuple is a fine way to name runs, but JSON only has arrays."""
        msg, _ = self.vis.compare_experiments(("run-a", "run-b"))
        self.assertEqual(msg["env_ids"], ["run-a", "run-b"])

    def test_client_rejects_bad_types(self):
        """The client type-checks before any request is made."""
        with self.assertRaises(TypeError):
            self.vis.compare_experiments("run-a")
        with self.assertRaises(TypeError):
            self.vis.compare_experiments([1, 2])

    def test_env_ids_is_required(self):
        """There is no other way to select runs, so it cannot be omitted."""
        with self.assertRaises(TypeError):
            self.vis.compare_experiments()


if __name__ == "__main__":
    unittest.main()
