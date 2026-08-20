#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the experiments metadata model and store.

Exercises :mod:`visdom.experiments` against a real ``JSONStore`` over a
temporary directory, so no running visdom server is needed. These cover the
model schemas (validation and round-trip (de)serialisation) and the
``ExperimentStore`` CRUD/list operations, including that experiment metadata
persists to disk and coexists with ordinary environment window data.
"""

import tempfile
import unittest

from visdom.data_model import JSONStore
from visdom.utils.server_utils import LazyEnvData
from visdom.experiments import (
    Experiment,
    ExperimentFinishedError,
    ExperimentStore,
    Metric,
    Param,
    Tag,
    normalize_tags,
    STATUS_FAILED,
    STATUS_FINISHED,
    STATUS_RUNNING,
    tags_to_mapping,
)


class TestModels(unittest.TestCase):
    """The Experiment/Param/Metric/Tag schemas validate and round-trip."""

    def test_param_infers_dtype(self):
        """Param.dtype is inferred from the value when not given explicitly."""
        self.assertEqual(Param("lr", 0.01).dtype, "float")
        self.assertEqual(Param("epochs", 10).dtype, "int")
        self.assertEqual(Param("name", "resnet").dtype, "str")
        # bool must not be mislabelled as int (bool subclasses int).
        self.assertEqual(Param("amp", True).dtype, "bool")

    def test_param_respects_explicit_dtype(self):
        """An explicit dtype is kept rather than being overwritten."""
        self.assertEqual(Param("k", "1", dtype="int").dtype, "int")

    def test_experiment_defaults(self):
        """A new experiment defaults name to env_id and starts running."""
        exp = Experiment(env_id="main")
        self.assertEqual(exp.name, "main")
        self.assertEqual(exp.status, STATUS_RUNNING)
        self.assertIsNone(exp.finished_at)

    def test_experiment_rejects_bad_status(self):
        """Constructing with an unknown status raises ValueError."""
        with self.assertRaises(ValueError):
            Experiment(env_id="main", status="bogus")

    def test_set_param_replaces_by_key(self):
        """set_param overwrites an existing param of the same name in place."""
        exp = Experiment(env_id="main")
        exp.set_param("lr", 0.1)
        exp.set_param("lr", 0.01)
        self.assertEqual(len(exp.params), 1)
        self.assertEqual(exp.get_param("lr").value, 0.01)

    def test_set_tag_replaces_by_key(self):
        """set_tag overwrites an existing tag of the same name in place."""
        exp = Experiment(env_id="main")
        exp.set_tag("dataset", "mnist")
        exp.set_tag("dataset", "cifar")
        self.assertEqual(len(exp.tags), 1)
        self.assertEqual(exp.tags[0].value, "cifar")

    def test_add_metric_appends_time_series(self):
        """add_metric appends (never replaces); latest_metric reads the last."""
        exp = Experiment(env_id="main")
        exp.add_metric("acc", 0.5, step=1)
        exp.add_metric("acc", 0.9, step=2)
        self.assertEqual(len(exp.metrics), 2)
        self.assertEqual(exp.latest_metric("acc").value, 0.9)
        self.assertIsNone(exp.latest_metric("missing"))

    def test_finish_sets_terminal_state(self):
        """finish stamps finished_at and only accepts terminal statuses."""
        exp = Experiment(env_id="main")
        exp.finish()
        self.assertEqual(exp.status, STATUS_FINISHED)
        self.assertIsNotNone(exp.finished_at)
        exp2 = Experiment(env_id="two")
        exp2.finish(STATUS_FAILED)
        self.assertEqual(exp2.status, STATUS_FAILED)
        with self.assertRaises(ValueError):
            Experiment(env_id="three").finish(STATUS_RUNNING)

    def test_round_trip_serialisation(self):
        """to_dict/from_dict preserve every field of a populated experiment."""
        exp = Experiment(env_id="main", description="run 1")
        exp.set_param("lr", 0.01)
        exp.set_tag("dataset", "mnist")
        exp.add_metric("acc", 0.9, step=3)
        exp.finish()
        rebuilt = Experiment.from_dict(exp.to_dict())
        self.assertEqual(rebuilt.to_dict(), exp.to_dict())
        self.assertIsInstance(rebuilt.params[0], Param)
        self.assertIsInstance(rebuilt.metrics[0], Metric)
        self.assertIsInstance(rebuilt.tags[0], Tag)


class TestTagHelpers(unittest.TestCase):
    """Tag helpers preserve model values and validate the public mapping."""

    def test_tags_to_mapping_preserves_values(self):
        """Converting model tags never drops their key/value data."""
        tags = [Tag("dataset", "cifar10"), Tag("stable", "")]
        self.assertEqual(tags_to_mapping(tags), {"dataset": "cifar10", "stable": ""})

    def test_normalize_tags_trims_names_and_preserves_values(self):
        """Normalization changes tag names only, leaving values untouched."""
        self.assertEqual(
            normalize_tags({" dataset ": " cifar10 ", "": "ignored"}),
            {"dataset": " cifar10 "},
        )

    def test_normalize_tags_rejects_invalid_types(self):
        """The domain accepts only string-to-string mappings."""
        with self.assertRaises(TypeError):
            normalize_tags(["stable"])
        with self.assertRaises(TypeError):
            normalize_tags({1: "stable"})
        with self.assertRaises(TypeError):
            normalize_tags({"priority": 1})

    def test_normalize_tags_enforces_limits(self):
        """Tag names and per-environment tag counts stay bounded."""
        with self.assertRaises(ValueError):
            normalize_tags({"x" * 51: "value"})
        with self.assertRaises(ValueError):
            normalize_tags({"tag-{0}".format(i): "" for i in range(21)})


class TestExperimentStore(unittest.TestCase):
    """ExperimentStore CRUD/list operations over a real JSONStore backend."""

    def setUp(self):
        """Give each test a fresh temp env_path and a store over it."""
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = self._tmp.name
        self.backend = JSONStore(self.env_path)
        self.store = ExperimentStore(self.backend)

    def tearDown(self):
        self._tmp.cleanup()

    def test_log_experiment_persists_to_disk(self):
        """A logged experiment is readable by a brand-new store over the dir."""
        self.store.log_experiment(
            "main", params={"lr": 0.01, "epochs": 10}, tags={"dataset": "mnist"}
        )
        # A fresh store instance proves the data survives on disk, not just in
        # the object we wrote through.
        reopened = ExperimentStore(JSONStore(self.env_path))
        exp = reopened.get_experiment("main")
        self.assertIsNotNone(exp)
        self.assertEqual(exp.get_param("lr").value, 0.01)
        self.assertEqual(exp.get_param("epochs").dtype, "int")
        self.assertEqual(exp.tags[0].value, "mnist")

    def test_get_missing_experiment_returns_none(self):
        """Envs with no experiment blob yield None (feature is opt-in)."""
        self.assertIsNone(self.store.get_experiment("never_logged"))

    def test_log_experiment_updates_in_place(self):
        """Re-logging merges params and keeps prior metrics rather than resetting."""
        self.store.log_experiment("main", params={"lr": 0.1})
        self.store.log_metric("main", "acc", 0.7)
        exp = self.store.log_experiment(
            "main", description="updated", params={"lr": 0.01, "wd": 0.0}
        )
        self.assertEqual(exp.description, "updated")
        self.assertEqual(exp.get_param("lr").value, 0.01)
        self.assertEqual(exp.get_param("wd").value, 0.0)
        # The metric logged before the update is still present.
        self.assertEqual(len(exp.metrics), 1)

    def test_log_metric_auto_creates_experiment(self):
        """Logging a metric for an env with no experiment creates one."""
        self.store.log_metric("main", "loss", 1.5, step=0)
        exp = self.store.get_experiment("main")
        self.assertIsNotNone(exp)
        self.assertEqual(exp.latest_metric("loss").value, 1.5)

    def test_update_tags_replaces_and_preserves_values(self):
        """Replacing tags persists the complete key/value mapping."""
        self.store.log_experiment("main", tags={"old": "value"})
        updated = self.store.update_tags("main", {" dataset ": "cifar10", "stable": ""})
        self.assertEqual(
            tags_to_mapping(updated.tags), {"dataset": "cifar10", "stable": ""}
        )
        reopened = ExperimentStore(JSONStore(self.env_path))
        self.assertEqual(
            tags_to_mapping(reopened.get_experiment("main").tags),
            {"dataset": "cifar10", "stable": ""},
        )

    def test_update_tags_appends_and_updates_by_key(self):
        """Append mode keeps unrelated values and updates matching keys."""
        self.store.log_experiment("main", tags={"dataset": "mnist", "owner": "alice"})
        updated = self.store.update_tags(
            "main", {"dataset": "cifar10", "stable": ""}, append=True
        )
        self.assertEqual(
            tags_to_mapping(updated.tags),
            {"dataset": "cifar10", "owner": "alice", "stable": ""},
        )

    def test_update_tags_creates_and_can_update_terminal_experiment(self):
        """Tag management creates missing records and remains organizational."""
        created = self.store.update_tags("main", {"owner": "alice"})
        self.assertEqual(tags_to_mapping(created.tags), {"owner": "alice"})

        self.store.finish_experiment("main")
        updated = self.store.update_tags("main", {"stage": "production"}, append=True)
        self.assertEqual(updated.status, STATUS_FINISHED)
        self.assertEqual(
            tags_to_mapping(updated.tags),
            {"owner": "alice", "stage": "production"},
        )

    def test_finish_experiment(self):
        """finish_experiment persists a terminal status."""
        self.store.log_experiment("main")
        self.store.finish_experiment("main", STATUS_FAILED)
        self.assertEqual(self.store.get_experiment("main").status, STATUS_FAILED)

    def test_finish_missing_experiment_raises(self):
        """Finishing an env that never logged an experiment raises KeyError."""
        with self.assertRaises(KeyError):
            self.store.finish_experiment("nope")

    def test_finish_on_finished_raises(self):
        """Finishing a terminal experiment is rejected, whatever status is asked for."""
        self.store.log_experiment("main")
        self.store.finish_experiment("main")
        finished_at = self.store.get_experiment("main").finished_at
        with self.assertRaises(ExperimentFinishedError):
            self.store.finish_experiment("main")
        with self.assertRaises(ExperimentFinishedError):
            self.store.finish_experiment("main", STATUS_FAILED)
        stored = self.store.get_experiment("main")
        self.assertEqual(stored.status, STATUS_FINISHED)
        self.assertEqual(stored.finished_at, finished_at)

    def test_log_experiment_on_finished_raises(self):
        """Updating an experiment that is already terminal is rejected."""
        self.store.log_experiment("main", params={"lr": 0.1})
        self.store.finish_experiment("main")
        with self.assertRaises(ExperimentFinishedError):
            self.store.log_experiment("main", params={"lr": 0.2})
        self.assertEqual(self.store.get_experiment("main").get_param("lr").value, 0.1)

    def test_log_metric_on_finished_raises(self):
        """Appending a metric to a terminal experiment is rejected."""
        self.store.log_metric("main", "acc", 0.9)
        self.store.finish_experiment("main", STATUS_FAILED)
        with self.assertRaises(ExperimentFinishedError):
            self.store.log_metric("main", "acc", 0.95)
        self.assertEqual(len(self.store.get_experiment("main").metrics), 1)

    def test_list_experiments(self):
        """list_experiments returns only envs that actually have a blob."""
        self.store.log_experiment("a")
        self.store.log_experiment("b")
        # An ordinary env with window data but no experiment must be skipped.
        self.backend.save_env("plain", {"jsons": {"w": {"id": "w"}}, "reload": {}})
        listed = sorted(exp.env_id for exp in self.store.list_experiments())
        self.assertEqual(listed, ["a", "b"])

    def test_delete_experiment_keeps_env(self):
        """delete_experiment drops the blob but leaves the environment intact."""
        self.backend.save_env("main", {"jsons": {"w": {"id": "w"}}, "reload": {}})
        self.store.log_experiment("main", params={"lr": 0.01})
        self.assertTrue(self.store.delete_experiment("main"))
        self.assertIsNone(self.store.get_experiment("main"))
        # The window data the env had before is untouched.
        env = self.backend.load_env("main")
        self.assertIn("w", env["jsons"])
        self.assertNotIn("experiment", env)

    def test_delete_missing_experiment_returns_false(self):
        """Deleting from an env with no experiment reports False."""
        self.assertFalse(self.store.delete_experiment("nope"))

    def test_experiment_coexists_with_window_data(self):
        """Logging onto an env with windows preserves those windows on disk."""
        self.backend.save_env(
            "main", {"jsons": {"win_0": {"id": "win_0"}}, "reload": {"foo": 1}}
        )
        self.store.log_experiment("main", params={"lr": 0.01})
        env = self.backend.load_env("main")
        self.assertIn("win_0", env["jsons"])
        self.assertEqual(env["reload"], {"foo": 1})
        self.assertEqual(env["experiment"]["params"][0]["value"], 0.01)

    def test_experiment_survives_lazy_env_reload_and_save(self):
        """A prior-session experiment is not clobbered by a later full-env save.

        Mirrors the server's cross-restart path: an env logged in one session is
        reloaded as a LazyEnvData, materialised by an unrelated window write, and
        persisted again by the shutdown save_all. The experiment blob must ride
        through rather than being stripped to jsons/reload.
        """
        self.store.log_experiment("main", params={"lr": 0.01})

        state = {"main": LazyEnvData(self.backend, "main")}
        state["main"]["jsons"]["win_1"] = {"id": "win_1"}
        self.backend.save_all(state)

        reopened = ExperimentStore(JSONStore(self.env_path))
        exp = reopened.get_experiment("main")
        self.assertIsNotNone(exp, "experiment was clobbered by the full-env save")
        self.assertEqual(exp.get_param("lr").value, 0.01)


class TestExperimentStoreNoPersistence(unittest.TestCase):
    """With persistence disabled the store degrades gracefully (no crashes)."""

    def setUp(self):
        self.store = ExperimentStore(JSONStore(None))

    def test_log_returns_experiment_but_read_is_empty(self):
        """log_* still returns a valid object though nothing is persisted."""
        exp = self.store.log_experiment("main", params={"lr": 0.01})
        self.assertIsInstance(exp, Experiment)
        # Nothing is stored, so a subsequent read finds no experiment.
        self.assertIsNone(self.store.get_experiment("main"))
        self.assertEqual(self.store.list_experiments(), [])


if __name__ == "__main__":
    unittest.main()
