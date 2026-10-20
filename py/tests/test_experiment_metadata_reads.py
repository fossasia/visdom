"""Tests for reading experiment metadata without materialising environments.

Searching means visiting every environment, and an environment carries all of
its window data — plot traces, encoded images — while its experiment metadata
is a few hundred bytes. Reading the former to reach the latter is expensive
once (the parse) and expensive forever (a ``LazyEnvData`` caches what it was
made to load, in the state the server keeps).

So the read path is a projection: :meth:`DataStore.load_experiment` returns the
blob alone, and ``ExperimentStore`` prefers the live env only when it is already
resident. These tests pin both halves — that the projection is correct, and that
a bulk read leaves untouched environments untouched.
"""

import json
import os
import shutil
import tempfile
import unittest

import pytest

from visdom.data_model import JSONStore
from visdom.data_model.base import DataStore
from visdom.experiments import (
    ExperimentFinishedError,
    ExperimentStore,
    STATUS_FINISHED,
    STATUS_RUNNING,
    tags_to_mapping,
)
from visdom.utils.server_utils import LazyEnvData

pytestmark = pytest.mark.unit

# Sentinel for blob(): "drop this key" rather than "set it to None", since None
# is itself a value a blob can legitimately hold.
MISSING = object()


class TestJSONStoreProjection(unittest.TestCase):
    """JSONStore.load_experiment returns the blob, or None, and never raises."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_meta_read_")
        self.store = JSONStore(self._tmp_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _write_raw(self, eid, payload):
        with open(os.path.join(self._tmp_dir, eid + ".json"), "w") as fn:
            fn.write(json.dumps(payload))

    def test_returns_the_logged_blob(self):
        ExperimentStore(self.store).log_experiment("run-a", params={"lr": 0.1})
        blob = self.store.load_experiment("run-a")
        self.assertEqual(blob["env_id"], "run-a")
        self.assertEqual(blob["params"][0]["key"], "lr")

    def test_returns_none_for_env_without_experiment(self):
        self.store.save_env("plain", {"jsons": {}, "reload": {}})
        self.assertIsNone(self.store.load_experiment("plain"))

    def test_returns_none_for_unknown_env(self):
        self.assertIsNone(self.store.load_experiment("never-existed"))

    def test_traversal_id_cannot_read_outside_env_path(self):
        """A crafted id names no experiment instead of reaching a parent file.

        The projection opens a file, so it is a path sink like ``load_env``:
        the id is escaped and the resolved path is checked against
        ``env_path`` before anything is read, which leaves ``../<name>``
        pointing at a sibling that does not exist rather than at the real file
        one directory up.
        """
        outside = os.path.join(os.path.dirname(self._tmp_dir), "outside_meta.json")
        with open(outside, "w") as fn:
            fn.write(json.dumps({"jsons": {}, "reload": {}, "experiment": {"a": 1}}))
        self.addCleanup(os.remove, outside)

        for eid in ("../outside_meta", "../../outside_meta", "/etc/passwd"):
            self.assertIsNone(self.store.load_experiment(eid))

    def test_returns_none_for_unreadable_file(self):
        self._write_raw("broken", {"jsons": {}, "reload": {}})
        with open(os.path.join(self._tmp_dir, "broken.json"), "w") as fn:
            fn.write("{not json")
        self.assertIsNone(self.store.load_experiment("broken"))

    def test_returns_none_when_blob_is_not_an_object(self):
        self._write_raw("odd", {"jsons": {}, "reload": {}, "experiment": "nope"})
        self.assertIsNone(self.store.load_experiment("odd"))

    def test_agrees_with_load_env(self):
        ExperimentStore(self.store).log_experiment("run-b", params={"lr": 0.2})
        self.assertEqual(
            self.store.load_experiment("run-b"),
            self.store.load_env("run-b")["experiment"],
        )

    def test_projection_ignores_window_data(self):
        """An env full of windows still yields only its metadata."""
        store = ExperimentStore(self.store)
        store.log_experiment("run-c", params={"lr": 0.3})
        env = self.store.load_env("run-c")
        env["jsons"] = {"win": {"content": "x" * 10000}}
        self.store.save_env("run-c", env)
        blob = self.store.load_experiment("run-c")
        self.assertEqual(blob["env_id"], "run-c")
        self.assertNotIn("jsons", blob)


class TestInterfaceRequiresTheProjection(unittest.TestCase):
    """Every backend answers load_experiment itself; the interface has no default.

    A default reading through ``load_env`` would be inherited silently by a
    backend that reads whole environments — the one thing the projection exists
    to avoid — and would look correct until someone measured it.
    """

    def test_load_experiment_is_abstract(self):
        self.assertIn("load_experiment", DataStore.__abstractmethods__)


class TestLiveEnvsAreNotMaterialised(unittest.TestCase):
    """A bulk read leaves lazily-loaded envs lazy."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_meta_lazy_")
        self.backing = JSONStore(self._tmp_dir)
        seed = ExperimentStore(self.backing)
        for i in range(5):
            eid = "run-%d" % i
            seed.log_experiment(eid, params={"lr": 0.1 * i})
            env = self.backing.load_env(eid)
            env["jsons"] = {"win": {"content": "x" * 5000}}
            self.backing.save_env(eid, env)
        self.state = {
            eid: LazyEnvData(self.backing, eid) for eid in self.backing.list_envs()
        }
        self.store = ExperimentStore(self.backing, env_provider=self.state.get)

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _loaded(self):
        return [eid for eid, env in self.state.items() if env.is_loaded]

    def test_search_materialises_nothing(self):
        found = self.store.search(query="lr < 0.25")
        self.assertEqual(sorted(e.env_id for e in found), ["run-0", "run-1", "run-2"])
        self.assertEqual(self._loaded(), [])

    def test_get_experiment_materialises_nothing(self):
        self.assertIsNotNone(self.store.get_experiment("run-3"))
        self.assertEqual(self._loaded(), [])

    def test_iter_experiments_materialises_nothing(self):
        self.assertEqual(len(list(self.store.iter_experiments())), 5)
        self.assertEqual(self._loaded(), [])

    def test_results_match_a_store_reading_only_disk(self):
        """The env_provider must not change what a search finds, only its cost."""
        disk_only = ExperimentStore(self.backing)
        self.assertEqual(
            [e.env_id for e in self.store.search(query="lr > 0.15")],
            [e.env_id for e in disk_only.search(query="lr > 0.15")],
        )

    def test_a_resident_env_still_wins(self):
        """An env already in memory may hold changes the file has not seen."""
        live = self.state["run-4"]
        live["experiment"] = dict(live["experiment"], name="renamed-in-memory")
        self.assertTrue(live.is_loaded)
        self.assertEqual(self.store.get_experiment("run-4").name, "renamed-in-memory")

    def test_writes_still_go_through_the_live_env(self):
        """Logging keeps writing into the object the server is serving."""
        self.store.log_experiment("run-0", params={"momentum": 0.9})
        self.assertTrue(self.state["run-0"].is_loaded)
        self.assertEqual(
            self.state["run-0"]["experiment"]["params"][-1]["key"], "momentum"
        )


class MalformedBlobCase(unittest.TestCase):
    """A store holding one healthy run, plus the means to corrupt a blob.

    Not collected on its own (pytest wants a ``Test*`` name): it carries only
    the fixture the read-path and write-path cases share.
    """

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="visdom_meta_bad_")
        self.backing = JSONStore(self._tmp_dir)
        self.store = ExperimentStore(self.backing)
        self.store.log_experiment("healthy", params={"lr": 0.1})
        self.healthy = self.backing.load_experiment("healthy")

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def blob(self, **overrides):
        """A copy of the healthy blob with ``overrides`` applied.

        A key set to ``MISSING`` is removed rather than overwritten, which is
        how the absent-``env_id`` case is spelled.
        """
        blob = dict(self.healthy)
        for key, value in overrides.items():
            if value is MISSING:
                blob.pop(key, None)
            else:
                blob[key] = value
        return blob

    def write(self, eid, blob):
        """Persist ``blob`` as ``eid``'s metadata, bypassing the model.

        The corruption this guards against did not come through
        :class:`Experiment`, so neither does the fixture: the file is written
        by hand, exactly as a stray editor or a half-finished write would
        leave it.
        """
        path = os.path.join(self._tmp_dir, eid + ".json")
        with open(path, "w") as fn:
            fn.write(json.dumps({"jsons": {}, "reload": {}, "experiment": blob}))
        return eid


class TestMalformedMetadataIsSkipped(MalformedBlobCase):
    """An unreadable blob is skipped by the read, never raised out of it.

    ``_read_metadata`` is the read every bulk walk goes through, so an
    exception escaping it costs far more than the run it came from: ``search``
    and ``iter_experiments`` visit every environment, and one blob that was
    hand-edited or only half-written would fail every query until someone
    found and deleted the file. The storage layer underneath already refuses
    to behave that way — ``load_env`` and ``list_envs`` skip a file they
    cannot parse — and these pin the same contract one layer up.
    """

    def cases(self):
        """The malformed shapes, each named by what a reader would hit on it."""
        return (
            ("status outside VALID_STATUSES", self.blob(status="cancelled")),
            ("env_id missing entirely", self.blob(env_id=MISSING)),
            ("params holding an object", self.blob(params={"lr": 0.1})),
            ("params holding a scalar", self.blob(params=7)),
            ("a param that is not an object", self.blob(params=["lr"])),
            ("a param without a key", self.blob(params=[{"value": 0.1}])),
            ("a metric that is not an object", self.blob(metrics=[3])),
            ("a tag without a key", self.blob(tags=[{"value": "mnist"}])),
        )

    def test_get_experiment_returns_none_for_every_bad_blob(self):
        """Each shape reads as "this env has no experiment", not as an error."""
        for label, blob in self.cases():
            with self.subTest(label):
                eid = self.write("bad", blob)
                self.assertIsNone(self.store.get_experiment(eid))

    def test_search_survives_a_bad_blob(self):
        """One unreadable env does not take the whole scan with it."""
        for label, blob in self.cases():
            with self.subTest(label):
                self.write("bad", blob)
                found = [e.env_id for e in self.store.search()]
                self.assertEqual(found, ["healthy"])

    def test_a_sorted_and_filtered_search_survives_it_too(self):
        """The guard is in the read, so every entry point past it is covered."""
        self.write("bad", self.blob(status="cancelled"))
        self.assertEqual(
            [e.env_id for e in self.store.search(query="lr > 0.01", sort_by="lr")],
            ["healthy"],
        )
        page, total = self.store.search_page(sort_by="lr", limit=10)
        self.assertEqual([e.env_id for e in page], ["healthy"])
        self.assertEqual(total, 1)

    def test_iter_experiments_skips_it(self):
        """The generator yields the readable runs and stops at none of them."""
        self.write("bad", self.blob(env_id=MISSING))
        self.store.log_experiment("healthy-2", params={"lr": 0.2})
        self.assertEqual(
            sorted(e.env_id for e in self.store.iter_experiments()),
            ["healthy", "healthy-2"],
        )

    def test_the_skip_is_logged_with_the_env_id(self):
        """Skipping silently would leave the bad file impossible to find."""
        self.write("bad", self.blob(status="cancelled"))
        with self.assertLogs(level="WARNING") as captured:
            self.assertIsNone(self.store.get_experiment("bad"))
        self.assertTrue(any("bad" in line for line in captured.output))

    def test_a_resident_live_env_is_guarded_as_well(self):
        """The live-env branch reads the same blob and must not raise either."""
        state = {"bad": {"jsons": {}, "reload": {}, "experiment": self.blob(params=7)}}
        store = ExperimentStore(self.backing, env_provider=state.get)
        self.assertIsNone(store.get_experiment("bad"))

    def test_a_healthy_blob_is_still_read(self):
        """The guard catches corruption, not everything: valid runs still load."""
        self.write("bad", self.blob(status="cancelled"))
        experiment = self.store.get_experiment("healthy")
        self.assertIsNotNone(experiment)
        self.assertEqual(experiment.env_id, "healthy")
        self.assertEqual(experiment.get_param("lr").value, 0.1)


class TestMalformedMetadataOnWritePaths(MalformedBlobCase):
    """Updating or deleting an env is not blocked by its blob being unreadable.

    A guard on the read alone would leave the corrupt environment visible-but-
    frozen: search would skip it, and every attempt to fix it — log to it, tag
    it, delete it — would still raise. Recovering would mean shell access to
    the env directory. So the write paths are guarded too: logging to the env
    or tagging it makes its metadata readable again, deleting removes it, and
    the operations that genuinely need an existing run refuse with their
    ordinary ``KeyError``.

    What a write *keeps* while doing that is pinned next door, in
    :class:`TestWritesRepairRatherThanReset` — these only pin that it goes
    through at all.
    """

    def test_log_experiment_replaces_an_unreadable_blob(self):
        """Logging repairs the env instead of failing on it forever."""
        self.write("bad", self.blob(status="cancelled"))
        self.store.log_experiment("bad", params={"lr": 0.5})
        experiment = self.store.get_experiment("bad")
        self.assertIsNotNone(experiment)
        self.assertEqual(experiment.env_id, "bad")
        self.assertEqual(experiment.status, STATUS_RUNNING)
        self.assertEqual(experiment.get_param("lr").value, 0.5)

    def test_log_metric_replaces_an_unreadable_blob(self):
        """The metric path starts a run the same way, rather than raising."""
        self.write("bad", self.blob(env_id=MISSING))
        self.store.log_metric("bad", "acc", 0.9)
        experiment = self.store.get_experiment("bad")
        self.assertIsNotNone(experiment)
        self.assertEqual(experiment.latest_metric("acc").value, 0.9)

    def test_update_tags_replaces_an_unreadable_blob(self):
        """Tagging is how an env gets organised; a bad blob must not block it."""
        self.write("bad", self.blob(params=7))
        experiment = self.store.update_tags("bad", {"dataset": "mnist"})
        self.assertEqual(tags_to_mapping(experiment.tags), {"dataset": "mnist"})
        self.assertEqual(
            tags_to_mapping(self.store.get_experiment("bad").tags),
            {"dataset": "mnist"},
        )

    def test_update_tags_is_guarded_on_the_supplied_env_too(self):
        """The env_data branch parses a blob of its own, so it needs the guard.

        The tags handler passes the server's live env rather than making the
        store read one back, which is a second place the same corrupt blob is
        rebuilt.
        """
        env = {"jsons": {}, "reload": {}, "experiment": self.blob(status="cancelled")}
        experiment = self.store.update_tags("bad", {"stage": "eval"}, env_data=env)
        self.assertEqual(tags_to_mapping(experiment.tags), {"stage": "eval"})

    def test_finish_experiment_refuses_the_way_it_refuses_an_empty_env(self):
        """An unreadable run reads as no run, so finishing it is a KeyError.

        The distinction that matters is not that it raises but *what*: a
        KeyError is the store's ordinary "no experiment logged" answer, which
        the handler already turns into a 400 rather than a 500.
        """
        self.write("bad", self.blob(status="cancelled"))
        with self.assertRaises(KeyError):
            self.store.finish_experiment("bad")

    def test_compare_names_the_unreadable_env(self):
        """compare() reports the env as having no experiment, and says which."""
        self.write("bad", self.blob(env_id=MISSING))
        with self.assertRaises(KeyError) as caught:
            self.store.compare(["healthy", "bad"])
        self.assertIn("bad", str(caught.exception))

    def test_delete_experiment_removes_an_unreadable_blob(self):
        """The blob an operator most needs to delete is the one that will not load."""
        for label, blob in (
            ("status outside VALID_STATUSES", self.blob(status="cancelled")),
            ("env_id missing entirely", self.blob(env_id=MISSING)),
            ("params holding a scalar", self.blob(params=7)),
            ("a blob that is not an object at all", "nope"),
        ):
            with self.subTest(label):
                self.write("bad", blob)
                self.assertTrue(self.store.delete_experiment("bad"))
                self.assertIsNone(self.backing.load_experiment("bad"))
                self.assertIsNone(self.store.get_experiment("bad"))

    def test_deleting_an_unreadable_blob_keeps_the_environment(self):
        """Only the metadata goes; the env and its windows survive."""
        path = os.path.join(self._tmp_dir, "bad.json")
        with open(path, "w") as fn:
            fn.write(
                json.dumps(
                    {
                        "jsons": {"win_1": {"content": "keep me"}},
                        "reload": {},
                        "experiment": self.blob(status="cancelled"),
                    }
                )
            )
        self.assertTrue(self.store.delete_experiment("bad"))
        env = self.backing.load_env("bad")
        self.assertEqual(env["jsons"], {"win_1": {"content": "keep me"}})
        self.assertNotIn("experiment", env)

    def test_delete_experiment_still_reports_an_env_that_had_none(self):
        """Keying off the blob's presence must not turn "nothing" into "deleted"."""
        self.backing.save_env("plain", {"jsons": {}, "reload": {}})
        self.assertFalse(self.store.delete_experiment("plain"))
        self.assertFalse(self.store.delete_experiment("never-existed"))

    def test_one_unreadable_env_does_not_block_writes_to_another(self):
        """The corrupt env is contained: its neighbours write as they always did."""
        self.write("bad", self.blob(status="cancelled"))
        self.store.log_metric("healthy", "acc", 0.75)
        self.assertEqual(
            self.store.get_experiment("healthy").latest_metric("acc").value, 0.75
        )


class TestWritesRepairRatherThanReset(MalformedBlobCase):
    """A write over an unreadable blob keeps everything still legible in it.

    Reading an unreadable blob as "no experiment" is right for a read, and
    wrong for a write: the creating writers turn "no experiment" into a brand
    new one and persist it, so the answer that makes ``search`` resilient also
    made ``update_tags`` destructive. One unrecognised status, or an
    ``env_id`` a half-finished save never reached, and adding a tag would quietly
    drop the run's params, metrics, name and history — reporting success.

    So a write salvages instead: every field that still parses is carried over
    and only the unusable ones are defaulted. The env ends up readable *and*
    intact, which is the whole point of letting the write through.
    """

    def setUp(self):
        super().setUp()
        self.store.log_experiment(
            "rich",
            name="sweep-7",
            description="a real run",
            params={"lr": 0.1, "batch": 32},
            tags={"dataset": "mnist"},
        )
        self.store.log_metric("rich", "acc", 0.91, step=3)
        self.rich = self.backing.load_experiment("rich")

    def corrupt(self, **overrides):
        """Write the rich run to env ``bad``, damaged by ``overrides``.

        Returns the blob exactly as written, for the case that asserts a
        refused write left it untouched.
        """
        blob = dict(self.rich)
        for key, value in overrides.items():
            if value is MISSING:
                blob.pop(key, None)
            else:
                blob[key] = value
        self.write("bad", blob)
        return blob

    def test_logging_a_metric_keeps_what_the_blob_still_holds(self):
        """The run is repaired, not restarted."""
        self.corrupt(status="cancelled")
        self.store.log_metric("bad", "loss", 0.4)

        experiment = self.store.get_experiment("bad")
        self.assertEqual(experiment.name, "sweep-7")
        self.assertEqual(experiment.description, "a real run")
        self.assertEqual(experiment.get_param("lr").value, 0.1)
        self.assertEqual(experiment.get_param("batch").value, 32)
        self.assertEqual(tags_to_mapping(experiment.tags), {"dataset": "mnist"})
        self.assertEqual([m.key for m in experiment.metrics], ["acc", "loss"])
        self.assertEqual(experiment.created_at, self.rich["created_at"])

    def test_log_experiment_merges_into_the_repaired_run(self):
        """A re-log updates the salvaged record rather than starting over."""
        self.corrupt(status="cancelled")
        self.store.log_experiment("bad", params={"lr": 0.5})

        experiment = self.store.get_experiment("bad")
        self.assertEqual(experiment.get_param("lr").value, 0.5)
        self.assertEqual(experiment.get_param("batch").value, 32)
        self.assertEqual(experiment.latest_metric("acc").value, 0.91)
        self.assertEqual(experiment.status, STATUS_RUNNING)

    def test_tagging_keeps_the_runs_params_and_metrics(self):
        """A tag update is the smallest write there is; it must cost nothing.

        The previous tags do go, but only because a non-appending update
        replaces them — that is what the caller asked for, and it is what an
        intact blob would have done too.
        """
        self.corrupt(env_id=MISSING)
        self.store.update_tags("bad", {"owner": "alice"})

        experiment = self.store.get_experiment("bad")
        self.assertEqual(experiment.name, "sweep-7")
        self.assertEqual(experiment.get_param("lr").value, 0.1)
        self.assertEqual(experiment.latest_metric("acc").value, 0.91)
        self.assertEqual(tags_to_mapping(experiment.tags), {"owner": "alice"})

    def test_the_supplied_env_branch_repairs_too(self):
        """The server hands its live env to ``update_tags``; same rule there."""
        env = {
            "jsons": {},
            "reload": {},
            "experiment": dict(self.rich, status="cancelled"),
        }
        experiment = self.store.update_tags("bad", {"owner": "alice"}, env_data=env)

        self.assertEqual(experiment.get_param("lr").value, 0.1)
        self.assertEqual(experiment.latest_metric("acc").value, 0.91)

    def test_only_the_unreadable_field_is_lost(self):
        """``params`` that is no longer a list holds nothing to keep."""
        self.corrupt(params={"lr": 0.1})
        self.store.log_metric("bad", "loss", 0.4)

        experiment = self.store.get_experiment("bad")
        self.assertEqual(experiment.params, [])
        self.assertEqual(experiment.name, "sweep-7")
        self.assertEqual([m.key for m in experiment.metrics], ["acc", "loss"])
        self.assertEqual(tags_to_mapping(experiment.tags), {"dataset": "mnist"})

    def test_one_bad_entry_does_not_cost_the_whole_list(self):
        """A keyless param is dropped; the ones beside it are not."""
        self.corrupt(params=[{"value": 0.1}] + list(self.rich["params"]))
        self.store.log_metric("bad", "loss", 0.4)

        experiment = self.store.get_experiment("bad")
        self.assertEqual(sorted(p.key for p in experiment.params), ["batch", "lr"])

    def test_an_entry_with_an_unhashable_key_is_dropped(self):
        """A list key parses, but the writers set and map by key, so it goes.

        Keeping it made an appending tag update raise ``TypeError`` before it
        saved anything, which left the env as unreadable as it started.
        """
        self.corrupt(
            status="cancelled",
            tags=[{"key": ["dataset"], "value": "x"}] + list(self.rich["tags"]),
            params=[{"key": {"lr": 1}, "value": 0.1}] + list(self.rich["params"]),
        )
        experiment = self.store.update_tags("bad", {"owner": "alice"}, append=True)

        self.assertEqual(
            tags_to_mapping(experiment.tags), {"dataset": "mnist", "owner": "alice"}
        )
        self.assertEqual(sorted(p.key for p in experiment.params), ["batch", "lr"])
        self.assertIsNotNone(self.store.get_experiment("bad"))

    def test_a_salvaged_terminal_run_still_refuses_new_logs(self):
        """Damage elsewhere in the blob must not un-finish the run.

        Resetting to an empty experiment did exactly that: the replacement was
        ``running``, so a finished run silently accepted new metrics and lost
        its ``finished_at``.
        """
        self.store.finish_experiment("rich")
        self.rich = self.backing.load_experiment("rich")
        blob = self.corrupt(env_id=MISSING)

        with self.assertRaises(ExperimentFinishedError):
            self.store.log_metric("bad", "loss", 0.4)
        self.assertEqual(self.backing.load_experiment("bad"), blob)

    def test_a_repaired_terminal_run_keeps_its_finish(self):
        """Tagging is allowed after a finish, and must not undo one."""
        self.store.finish_experiment("rich")
        self.rich = self.backing.load_experiment("rich")
        self.corrupt(env_id=MISSING)

        experiment = self.store.update_tags("bad", {"owner": "alice"})

        self.assertEqual(experiment.status, STATUS_FINISHED)
        self.assertEqual(experiment.finished_at, self.rich["finished_at"])

    def test_an_env_with_no_metadata_still_starts_a_run(self):
        """Repair must not invent a run for an env that never had one."""
        self.backing.save_env("plain", {"jsons": {}, "reload": {}})
        self.store.log_metric("plain", "acc", 0.5)

        experiment = self.store.get_experiment("plain")
        self.assertEqual(experiment.env_id, "plain")
        self.assertEqual(experiment.name, "plain")
        self.assertEqual([m.key for m in experiment.metrics], ["acc"])

    def test_a_blob_that_was_never_metadata_starts_a_run_too(self):
        """A non-mapping blob has nothing to salvage, so it reads as absent."""
        self.write("bad", "nope")
        self.store.log_metric("bad", "acc", 0.5)

        self.assertEqual(
            self.store.get_experiment("bad").latest_metric("acc").value, 0.5
        )


if __name__ == "__main__":
    unittest.main()
