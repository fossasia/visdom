#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for experiment search.

Covers the three pieces the search layer is built from: ``ExperimentStore.search``
(filtering via the query parser, plus sorting) against a real ``JSONStore`` over a
temporary directory; the ``/experiments/search`` endpoint end-to-end through a real
:class:`~visdom.server.app.Application` with Tornado's ``AsyncHTTPTestCase``; and
the ``Visdom.search_experiments`` message shape with a mocked transport (no server).
"""

import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import tornado.testing

from visdom import Visdom
from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore, QueryParseError
from visdom.server.app import Application


def seed_experiments(store):
    """Log three experiments with known params/metrics/tags and created_at order.

    ``created_at`` is stamped explicitly rather than left to wall-clock time:
    the runs are logged microseconds apart, so the default newest-first sort
    would otherwise be testing the resolution of ``time.time()``.
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
        params={"lr": 0.001, "epochs": 20},
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


def env_ids(experiments):
    return [experiment.env_id for experiment in experiments]


class TestStoreSearch(unittest.TestCase):
    """ExperimentStore.search filters by query and sorts the results."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_search_")
        self.store = ExperimentStore(JSONStore(self._tmp_dir))
        seed_experiments(self.store)

    def test_no_query_returns_all(self):
        """A None query matches every logged experiment."""
        self.assertEqual(
            sorted(env_ids(self.store.search())), ["run-a", "run-b", "run-c"]
        )

    def test_blank_query_returns_all(self):
        """A blank/whitespace query matches everything rather than failing to parse."""
        self.assertEqual(len(self.store.search(query="")), 3)
        self.assertEqual(len(self.store.search(query="   ")), 3)

    def test_search_ignores_envs_without_experiments(self):
        """Environments that carry no experiment blob are simply not results."""
        self.store.datastore.save_env("plain", {"jsons": {}, "reload": {}})
        self.assertEqual(len(self.store.search()), 3)

    def test_filters_by_param(self):
        """A comparison on a param name selects on that param's value."""
        self.assertEqual(env_ids(self.store.search(query="lr < 0.01")), ["run-b"])

    def test_filters_by_latest_metric(self):
        """Metrics compare on their most recent value, not their first.

        run-b logged acc 0.55 and then 0.95; only the latter should match.
        """
        self.assertEqual(env_ids(self.store.search(query="acc > 0.9")), ["run-b"])

    def test_filters_by_namespaced_name(self):
        """The namespaced spelling reaches the same values as the bare one."""
        self.assertEqual(env_ids(self.store.search(query="param.lr = 0.5")), ["run-c"])
        self.assertEqual(
            env_ids(self.store.search(query="tag.dataset contains mnist")), ["run-a"]
        )

    def test_filters_by_builtin_field(self):
        """Built-in fields (status, name) are queryable alongside user data."""
        self.assertEqual(
            env_ids(self.store.search(query="status = finished")), ["run-b"]
        )
        self.assertEqual(env_ids(self.store.search(query="name = alpha")), ["run-a"])

    def test_filters_with_boolean_operators(self):
        """AND/OR/parentheses combine comparisons as the parser defines."""
        self.assertEqual(
            env_ids(self.store.search(query="lr > 0.05 AND epochs = 10")), ["run-a"]
        )
        self.assertEqual(
            sorted(env_ids(self.store.search(query="lr < 0.01 OR lr > 0.4"))),
            ["run-b", "run-c"],
        )

    def test_no_matches_returns_empty(self):
        """A query nothing satisfies returns an empty list, not an error."""
        self.assertEqual(self.store.search(query="lr > 100"), [])

    def test_unknown_field_matches_nothing(self):
        """A field no experiment has is absent, and absent never matches."""
        self.assertEqual(self.store.search(query="nonexistent > 1"), [])

    def test_invalid_query_raises_parse_error(self):
        """Malformed query syntax surfaces as QueryParseError."""
        with self.assertRaises(QueryParseError):
            self.store.search(query="lr <")

    def test_non_string_query_raises_type_error(self):
        """A non-string query is a caller bug, not a parse error."""
        with self.assertRaises(TypeError):
            self.store.search(query=42)

    def test_sorts_newest_first_by_default(self):
        """The default sort is created_at, descending."""
        self.assertEqual(env_ids(self.store.search()), ["run-c", "run-b", "run-a"])

    def test_sort_ascending(self):
        """descending=False reverses the order."""
        self.assertEqual(
            env_ids(self.store.search(descending=False)), ["run-a", "run-b", "run-c"]
        )

    def test_sort_by_param(self):
        """Sorting works on any queryable name, not just built-ins."""
        self.assertEqual(
            env_ids(self.store.search(sort_by="lr")), ["run-c", "run-a", "run-b"]
        )

    def test_sort_by_metric_puts_missing_last_in_both_directions(self):
        """A run missing the sort field sorts last however the sort is directed.

        run-c logged no metrics at all, so it has no "acc" to be ranked by.
        """
        self.assertEqual(
            env_ids(self.store.search(sort_by="acc")), ["run-b", "run-a", "run-c"]
        )
        self.assertEqual(
            env_ids(self.store.search(sort_by="acc", descending=False)),
            ["run-a", "run-b", "run-c"],
        )

    def test_sort_by_none_keeps_backend_order(self):
        """sort_by=None leaves the store's own ordering untouched."""
        unsorted = env_ids(self.store.search(sort_by=None))
        self.assertEqual(sorted(unsorted), ["run-a", "run-b", "run-c"])

    def test_sort_by_mixed_types_does_not_raise(self):
        """A field holding a number in one run and a string in another still sorts.

        Numbers order among themselves and ahead of the string.
        """
        self.store.log_experiment("run-d", params={"lr": "auto"})
        results = env_ids(self.store.search(sort_by="lr", descending=False))
        self.assertEqual(results, ["run-b", "run-a", "run-c", "run-d"])

    def test_filter_and_sort_combine(self):
        """Sorting applies to the filtered set."""
        self.assertEqual(
            env_ids(self.store.search(query="lr > 0.01", sort_by="lr")),
            ["run-c", "run-a"],
        )

    def test_search_reads_what_another_store_wrote(self):
        """Results come off disk, so a fresh store sees the same experiments."""
        fresh = ExperimentStore(JSONStore(self._tmp_dir))
        self.assertEqual(env_ids(fresh.search(query="acc > 0.9")), ["run-b"])


class TestSearchEndpoint(tornado.testing.AsyncHTTPTestCase):
    """POST /experiments/search returns a paged, sorted, filtered result set."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_exp_search_api_")
        super().setUp()
        seed_experiments(ExperimentStore(JSONStore(self._tmp_dir)))

    def get_app(self):
        return Application(port=self.get_http_port(), env_path=self._tmp_dir)

    def search(self, body):
        return self.fetch(
            "/experiments/search",
            method="POST",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def post_raw(self, body):
        return self.fetch(
            "/experiments/search",
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )

    def search_ok(self, body):
        resp = self.search(body)
        self.assertEqual(resp.code, 200)
        return json.loads(resp.body)

    def test_empty_body_returns_everything(self):
        """A search with no query returns all experiments, newest first."""
        body = self.search_ok({})
        self.assertEqual(
            [e["env_id"] for e in body["experiments"]], ["run-c", "run-b", "run-a"]
        )
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["offset"], 0)
        self.assertEqual(body["query"], "")

    def test_query_filters_results(self):
        """The query reaches the parser and filters the reply."""
        body = self.search_ok({"query": "lr < 0.01 AND acc > 0.9"})
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["experiments"][0]["env_id"], "run-b")
        self.assertEqual(body["query"], "lr < 0.01 AND acc > 0.9")

    def test_experiments_are_returned_in_full(self):
        """Each result is the full experiment dict, params/metrics/tags included."""
        body = self.search_ok({"query": "name = alpha"})
        experiment = body["experiments"][0]
        self.assertEqual(experiment["name"], "alpha")
        self.assertEqual(experiment["params"][0]["key"], "lr")
        self.assertEqual(experiment["metrics"][0]["key"], "acc")
        self.assertEqual(experiment["tags"][0]["value"], "mnist")

    def test_limit_pages_results_and_total_ignores_it(self):
        """limit caps the page while total still counts every match."""
        body = self.search_ok({"limit": 2})
        self.assertEqual([e["env_id"] for e in body["experiments"]], ["run-c", "run-b"])
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["limit"], 2)

    def test_offset_walks_the_pages(self):
        """offset skips the results already seen."""
        body = self.search_ok({"limit": 2, "offset": 2})
        self.assertEqual([e["env_id"] for e in body["experiments"]], ["run-a"])
        self.assertEqual(body["total"], 3)

    def test_offset_past_the_end_is_empty(self):
        """Paging past the last result is an empty page, not an error."""
        body = self.search_ok({"offset": 99})
        self.assertEqual(body["experiments"], [])
        self.assertEqual(body["total"], 3)

    def test_limit_zero_returns_count_only(self):
        """limit=0 is a legitimate way to ask only how many match."""
        body = self.search_ok({"limit": 0})
        self.assertEqual(body["experiments"], [])
        self.assertEqual(body["total"], 3)

    def test_null_limit_returns_all(self):
        """An explicit null limit lifts the cap."""
        body = self.search_ok({"limit": None})
        self.assertEqual(len(body["experiments"]), 3)
        self.assertIsNone(body["limit"])

    def test_default_limit_is_applied(self):
        """A body that omits limit is capped at the handler's default."""
        body = self.search_ok({})
        self.assertEqual(body["limit"], 100)

    def test_integral_float_limit_is_accepted(self):
        """JSON has no int type, so 2.0 is honoured as the index 2."""
        body = self.search_ok({"limit": 2.0})
        self.assertEqual(len(body["experiments"]), 2)

    def test_sort_by_and_direction(self):
        """sort_by/descending order the reply."""
        body = self.search_ok({"sort_by": "lr", "descending": False})
        self.assertEqual(
            [e["env_id"] for e in body["experiments"]], ["run-b", "run-a", "run-c"]
        )

    def test_invalid_query_is_400(self):
        """A malformed query is the caller's error, and says why."""
        resp = self.search({"query": "lr <"})
        self.assertEqual(resp.code, 400)
        self.assertIn("end of query", resp.reason)

    def test_query_wrong_type_is_400(self):
        """A non-string query is rejected before it reaches the parser."""
        resp = self.search({"query": {"lr": 1}})
        self.assertEqual(resp.code, 400)
        self.assertIn("query", resp.reason)

    def test_negative_offset_is_400(self):
        """A negative index would silently wrap around the list, so reject it."""
        self.assertEqual(self.search({"offset": -1}).code, 400)
        self.assertEqual(self.search({"limit": -5}).code, 400)

    def test_non_integer_limit_is_400(self):
        """limit must be a whole number."""
        self.assertEqual(self.search({"limit": "10"}).code, 400)
        self.assertEqual(self.search({"limit": 1.5}).code, 400)

    def test_non_string_sort_by_is_400(self):
        """sort_by must name a field."""
        self.assertEqual(self.search({"sort_by": 7}).code, 400)

    def test_missing_body_returns_everything(self):
        """The body is optional, so no body at all is a search for everything."""
        resp = self.post_raw("")
        self.assertEqual(resp.code, 200)
        self.assertEqual(json.loads(resp.body)["total"], 3)

    def test_malformed_json_is_400(self):
        """A body that is not JSON is the caller's error, not a 500."""
        resp = self.post_raw("{not json")
        self.assertEqual(resp.code, 400)

    def test_non_object_body_is_400(self):
        """A JSON list or scalar carries no arguments to read, so reject it."""
        self.assertEqual(self.post_raw("[1, 2]").code, 400)
        self.assertEqual(self.post_raw('"query"').code, 400)
        self.assertEqual(self.post_raw("null").code, 400)

    def test_non_boolean_descending_is_400(self):
        """The string "false" is rejected rather than coerced to true."""
        self.assertEqual(self.search({"descending": "false"}).code, 400)

    def test_sql_injection_payload_is_inert(self):
        """A SQL-ish payload is either a parse error or a plain string compare.

        Whatever happened, the data must be untouched.
        """
        resp = self.search({"query": "name = 'x'; DROP TABLE experiments'"})
        self.assertIn(resp.code, (200, 400))
        self.assertEqual(self.search_ok({})["total"], 3)

    def test_search_sees_an_experiment_logged_over_http(self):
        """An experiment logged through /experiments/log is searchable at once."""
        self.fetch(
            "/experiments/log",
            method="POST",
            body=json.dumps({"eid": "run-e", "action": "log", "params": {"lr": 0.02}}),
            headers={"Content-Type": "application/json"},
        )
        body = self.search_ok({"query": "lr = 0.02"})
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["experiments"][0]["env_id"], "run-e")


class TestSearchClientMessage(unittest.TestCase):
    """Visdom.search_experiments builds the message the endpoint expects.

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

    def test_search_message_shape(self):
        """The client sends the query and paging to the search endpoint."""
        msg, endpoint = self.vis.search_experiments("acc > 0.9", limit=5, offset=10)
        self.assertEqual(endpoint, "experiments/search")
        self.assertEqual(msg["query"], "acc > 0.9")
        self.assertEqual(msg["limit"], 5)
        self.assertEqual(msg["offset"], 10)
        self.assertTrue(msg["descending"])

    def test_search_defaults(self):
        """Called bare, it asks for the first page of everything."""
        msg, _ = self.vis.search_experiments()
        self.assertIsNone(msg["query"])
        self.assertIsNone(msg["sort_by"])
        self.assertEqual(msg["limit"], 100)
        self.assertEqual(msg["offset"], 0)

    def test_search_rejects_non_string_query(self):
        """The client type-checks the query before any request is made."""
        with self.assertRaises(TypeError):
            self.vis.search_experiments(query=42)
        with self.assertRaises(TypeError):
            self.vis.search_experiments(sort_by=42)


if __name__ == "__main__":
    unittest.main()
