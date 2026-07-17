"""Tests for the hyper-parameter pane (Layer 3, PR A1).

Covers the two pieces ``Visdom.hparams`` is built from: the module-level
``_flatten_experiments`` helper, which collapses experiment dicts (as returned
by ``experiments/search``) into the compact records payload the pane renders;
and the ``Visdom.hparams`` message shape with ``send=False`` (no server), which
pins the window type and the search-then-flatten wiring. Realistic input is
produced through a real ``ExperimentStore`` over a temporary ``JSONStore``, the
same way the other experiment tests seed their fixtures.
"""

import tempfile
import unittest

from visdom import Visdom, _flatten_experiments
from visdom.data_model import JSONStore
from visdom.experiments import ExperimentStore


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
    store.finish_experiment("run-b")

    store.log_experiment("run-c", name="gamma", params={"momentum": 0.9})


def search_dicts(store):
    """Return experiment dicts as the search endpoint would hand them back."""
    return [experiment.to_dict() for experiment in store.search()]


class TestFlattenExperiments(unittest.TestCase):
    """_flatten_experiments collapses lists of params/metrics into per-run maps."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ExperimentStore(JSONStore(self._tmp.name))
        seed_experiments(self.store)
        self.payload = _flatten_experiments(search_dicts(self.store))

    def tearDown(self):
        self._tmp.cleanup()

    def _record(self, env_id):
        for record in self.payload["records"]:
            if record["env_id"] == env_id:
                return record
        self.fail("no record for {0!r}".format(env_id))

    def test_one_record_per_run(self):
        """Every experiment becomes exactly one flattened row."""
        self.assertEqual(len(self.payload["records"]), 3)

    def test_param_keys_are_sorted_union(self):
        """param_keys is the sorted union of every run's param names."""
        self.assertEqual(self.payload["param_keys"], ["epochs", "lr", "momentum"])

    def test_metric_keys_are_sorted_union(self):
        """metric_keys is the sorted union of every run's metric names."""
        self.assertEqual(self.payload["metric_keys"], ["acc", "loss"])

    def test_tag_keys_are_sorted_union(self):
        """tag_keys is the sorted union of every run's tag names."""
        self.assertEqual(self.payload["tag_keys"], ["dataset", "owner"])

    def test_tags_collapse_to_a_map(self):
        """A run's tags flatten to a {name: value} map on the record."""
        self.assertEqual(
            self._record("run-b")["tags"], {"dataset": "cifar10", "owner": "mira"}
        )

    def test_run_without_tags_has_empty_tag_map(self):
        """A run with no tags still exposes a tags key (an empty map)."""
        self.assertEqual(self._record("run-c")["tags"], {})

    def test_params_collapse_to_a_map(self):
        """A run's params flatten to a {name: value} map."""
        self.assertEqual(self._record("run-a")["params"], {"lr": 0.1, "epochs": 10})

    def test_latest_metric_value_is_kept(self):
        """Metrics are a time series; only the last value per key survives."""
        self.assertEqual(self._record("run-b")["metrics"]["acc"], 0.95)

    def test_record_carries_identity_fields(self):
        """Name and status ride along for the table header."""
        record = self._record("run-b")
        self.assertEqual(record["name"], "beta")
        self.assertEqual(record["status"], "finished")

    def test_missing_param_is_absent_not_null(self):
        """A run without a param simply omits it (columns are unioned client-side)."""
        self.assertNotIn("momentum", self._record("run-a")["params"])
        self.assertNotIn("lr", self._record("run-c")["params"])

    def test_empty_input_is_empty_payload(self):
        """No experiments yields empty records and empty key unions."""
        payload = _flatten_experiments([])
        self.assertEqual(payload["records"], [])
        self.assertEqual(payload["param_keys"], [])
        self.assertEqual(payload["metric_keys"], [])
        self.assertEqual(payload["tag_keys"], [])

    def test_non_dict_entries_are_skipped(self):
        """Defensive: a malformed entry does not abort the whole flatten."""
        payload = _flatten_experiments([None, "oops", {"env_id": "x"}])
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["env_id"], "x")


class TestHparamsClientMessage(unittest.TestCase):
    """Visdom.hparams builds the window the pane expects."""

    def setUp(self):
        self.vis = Visdom(send=False, raise_exceptions=True)

    def test_creates_an_hparams_window(self):
        """The message posts to events and carries a single hparams pane."""
        msg, endpoint = self.vis.hparams()
        self.assertEqual(endpoint, "events")
        self.assertEqual(len(msg["data"]), 1)
        self.assertEqual(msg["data"][0]["type"], "hparams")

    def test_content_has_records_shape(self):
        """The pane content always exposes the keys the frontend reads."""
        msg, _ = self.vis.hparams()
        content = msg["data"][0]["content"]
        self.assertIn("records", content)
        self.assertIn("param_keys", content)
        self.assertIn("metric_keys", content)
        self.assertIn("tag_keys", content)

    def test_env_and_win_pass_through(self):
        """win/env target a specific pane like the other plotting methods."""
        msg, _ = self.vis.hparams(win="hp1", env="run-x")
        self.assertEqual(msg["win"], "hp1")
        self.assertEqual(msg["eid"], "run-x")

    def test_rejects_non_list_env_ids(self):
        """env_ids must be a list/tuple of ids, not a bare string."""
        with self.assertRaises(TypeError):
            self.vis.hparams(env_ids="run-a")

    def test_rejects_non_string_env_ids(self):
        """env_ids must contain strings."""
        with self.assertRaises(TypeError):
            self.vis.hparams(env_ids=["run-a", 3])

    def _stub_search(self):
        """Stub search_experiments to record its query and return three runs."""
        self._seen = {}
        canned = {
            "experiments": [
                {"env_id": "run-a", "name": "a", "params": [], "metrics": []},
                {"env_id": "run-b", "name": "b", "params": [], "metrics": []},
                {"env_id": "run-c", "name": "c", "params": [], "metrics": []},
            ]
        }

        def fake_search(query=None, limit=None):
            self._seen["query"] = query
            return canned

        self.vis.search_experiments = fake_search

    def _ordered(self, msg):
        return [r["env_id"] for r in msg["data"][0]["content"]["records"]]

    def test_env_ids_filter_and_order(self):
        """env_ids selects and orders runs out of the fetched set (default mode)."""
        self._stub_search()
        msg, _ = self.vis.hparams(env_ids=["run-c", "run-a"])
        self.assertEqual(self._ordered(msg), ["run-c", "run-a"])

    def test_mode_query_ignores_env_ids(self):
        """mode='query' forwards the query and does not narrow by env_ids."""
        self._stub_search()
        msg, _ = self.vis.hparams(query="acc > 0.9", env_ids=["run-a"], mode="query")
        self.assertEqual(self._seen["query"], "acc > 0.9")
        self.assertEqual(self._ordered(msg), ["run-a", "run-b", "run-c"])

    def test_mode_env_ids_ignores_query(self):
        """mode='env_ids' sends no query and narrows to the named runs."""
        self._stub_search()
        msg, _ = self.vis.hparams(query="acc > 0.9", env_ids=["run-b"], mode="env_ids")
        self.assertIsNone(self._seen["query"])
        self.assertEqual(self._ordered(msg), ["run-b"])

    def test_mode_both_intersects(self):
        """mode='both' forwards the query and then narrows by env_ids."""
        self._stub_search()
        msg, _ = self.vis.hparams(
            query="acc > 0.9", env_ids=["run-c", "run-a"], mode="both"
        )
        self.assertEqual(self._seen["query"], "acc > 0.9")
        self.assertEqual(self._ordered(msg), ["run-c", "run-a"])

    def test_mode_env_ids_requires_env_ids(self):
        """mode='env_ids' without env_ids is a usage error."""
        with self.assertRaises(ValueError):
            self.vis.hparams(mode="env_ids")

    def test_rejects_unknown_mode(self):
        """An unrecognised mode is rejected before any request."""
        with self.assertRaises(ValueError):
            self.vis.hparams(mode="sideways")


if __name__ == "__main__":
    unittest.main()
