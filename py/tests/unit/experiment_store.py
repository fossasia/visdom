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

import math

import pytest

from visdom.data_model import JSONStore
from visdom.utils.server_utils import LazyEnvData
from visdom.experiments import (
    build_record,
    Experiment,
    ExperimentFinishedError,
    ExperimentStore,
    LazyMetricList,
    Metric,
    normalize_tags,
    Param,
    Tag,
    tags_to_mapping,
    STATUS_FAILED,
    STATUS_FINISHED,
    STATUS_RUNNING,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def experiments(store):
    """ExperimentStore over the shared temp-directory JSONStore."""
    return ExperimentStore(store)


@pytest.fixture
def live_state():
    """Stand-in for the server's ``state`` dict of live environments."""
    return {}


@pytest.fixture
def live_experiments(store, live_state):
    """ExperimentStore reading live envs through an ``env_provider``."""
    return ExperimentStore(store, env_provider=live_state.get)


# -- Models -------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, dtype",
    [(0.01, "float"), (10, "int"), ("resnet", "str"), (True, "bool")],
    ids=["float", "int", "str", "bool"],
)
def test_param_infers_dtype(value, dtype):
    """Param.dtype is inferred from the value when not given explicitly.

    ``bool`` must not be mislabelled as ``int``, since bool subclasses int.
    """
    assert Param("k", value).dtype == dtype


def test_param_respects_explicit_dtype():
    """An explicit dtype is kept rather than being overwritten."""
    assert Param("k", "1", dtype="int").dtype == "int"


def test_experiment_defaults():
    """A new experiment defaults name to env_id and starts running."""
    exp = Experiment(env_id="main")
    assert exp.name == "main"
    assert exp.status == STATUS_RUNNING
    assert exp.finished_at is None


def test_experiment_rejects_bad_status():
    """Constructing with an unknown status raises ValueError."""
    with pytest.raises(ValueError):
        Experiment(env_id="main", status="bogus")


def test_set_param_replaces_by_key():
    """set_param overwrites an existing param of the same name in place."""
    exp = Experiment(env_id="main")
    exp.set_param("lr", 0.1)
    exp.set_param("lr", 0.01)
    assert len(exp.params) == 1
    assert exp.get_param("lr").value == 0.01


def test_set_tag_replaces_by_key():
    """set_tag overwrites an existing tag of the same name in place."""
    exp = Experiment(env_id="main")
    exp.set_tag("dataset", "mnist")
    exp.set_tag("dataset", "cifar")
    assert len(exp.tags) == 1
    assert exp.tags[0].value == "cifar"


def test_add_metric_appends_time_series():
    """add_metric appends (never replaces); latest_metric reads the last."""
    exp = Experiment(env_id="main")
    exp.add_metric("acc", 0.5, step=1)
    exp.add_metric("acc", 0.9, step=2)
    assert len(exp.metrics) == 2
    assert exp.latest_metric("acc").value == 0.9
    assert exp.latest_metric("missing") is None


def test_finish_sets_terminal_state():
    """finish stamps finished_at and only accepts terminal statuses."""
    exp = Experiment(env_id="main")
    exp.finish()
    assert exp.status == STATUS_FINISHED
    assert exp.finished_at is not None

    failed = Experiment(env_id="two")
    failed.finish(STATUS_FAILED)
    assert failed.status == STATUS_FAILED

    with pytest.raises(ValueError):
        Experiment(env_id="three").finish(STATUS_RUNNING)


def test_round_trip_serialisation():
    """to_dict/from_dict preserve every field of a populated experiment."""
    exp = Experiment(env_id="main", description="run 1")
    exp.set_param("lr", 0.01)
    exp.set_tag("dataset", "mnist")
    exp.add_metric("acc", 0.9, step=3)
    exp.finish()

    rebuilt = Experiment.from_dict(exp.to_dict())

    assert rebuilt.to_dict() == exp.to_dict()
    assert isinstance(rebuilt.params[0], Param)
    assert isinstance(rebuilt.metrics[0], Metric)
    assert isinstance(rebuilt.tags[0], Tag)


# -- Tag helpers --------------------------------------------------------------


def test_tags_to_mapping_preserves_values():
    """Converting model tags never drops their key/value data."""
    tags = [Tag("dataset", "cifar10"), Tag("stable", "")]

    assert tags_to_mapping(tags) == {"dataset": "cifar10", "stable": ""}


def test_normalize_tags_trims_names_and_preserves_values():
    """Normalization changes tag names only, leaving values untouched."""
    normalized = normalize_tags({" dataset ": " cifar10 ", "": "ignored"})

    assert normalized == {"dataset": " cifar10 "}


@pytest.mark.parametrize(
    "tags",
    [["stable"], {1: "stable"}, {"priority": 1}],
    ids=["not_a_mapping", "non_string_name", "non_string_value"],
)
def test_normalize_tags_rejects_invalid_types(tags):
    """The domain accepts only string-to-string mappings."""
    with pytest.raises(TypeError):
        normalize_tags(tags)


@pytest.mark.parametrize(
    "tags",
    [{"x" * 51: "value"}, {"tag-{0}".format(i): "" for i in range(21)}],
    ids=["name_too_long", "too_many_tags"],
)
def test_normalize_tags_enforces_limits(tags):
    """Tag names and per-environment tag counts stay bounded."""
    with pytest.raises(ValueError):
        normalize_tags(tags)


# -- ExperimentStore over a real backend --------------------------------------


def test_log_experiment_persists_to_disk(experiments, env_path):
    """A logged experiment is readable by a brand-new store over the dir."""
    experiments.log_experiment(
        "main", params={"lr": 0.01, "epochs": 10}, tags={"dataset": "mnist"}
    )

    # A fresh store instance proves the data survives on disk, not just in the
    # object we wrote through.
    exp = ExperimentStore(JSONStore(env_path)).get_experiment("main")

    assert exp is not None
    assert exp.get_param("lr").value == 0.01
    assert exp.get_param("epochs").dtype == "int"
    assert exp.tags[0].value == "mnist"


def test_get_missing_experiment_returns_none(experiments):
    """Envs with no experiment blob yield None (feature is opt-in)."""
    assert experiments.get_experiment("never_logged") is None


def test_log_experiment_updates_in_place(experiments):
    """Re-logging merges params and keeps prior metrics rather than resetting."""
    experiments.log_experiment("main", params={"lr": 0.1})
    experiments.log_metric("main", "acc", 0.7)

    exp = experiments.log_experiment(
        "main", description="updated", params={"lr": 0.01, "wd": 0.0}
    )

    assert exp.description == "updated"
    assert exp.get_param("lr").value == 0.01
    assert exp.get_param("wd").value == 0.0
    assert len(exp.metrics) == 1  # the metric logged before the update survives


def test_log_metric_auto_creates_experiment(experiments):
    """Logging a metric for an env with no experiment creates one."""
    experiments.log_metric("main", "loss", 1.5, step=0)

    exp = experiments.get_experiment("main")
    assert exp is not None
    assert exp.latest_metric("loss").value == 1.5


def test_update_tags_replaces_and_preserves_values(experiments, store, env_path):
    """Replacing tags persists the complete key/value mapping."""
    experiments.log_experiment("main", tags={"old": "value"})

    updated = experiments.update_tags("main", {" dataset ": "cifar10", "stable": ""})

    assert tags_to_mapping(updated.tags) == {"dataset": "cifar10", "stable": ""}
    reopened = ExperimentStore(JSONStore(env_path))
    assert tags_to_mapping(reopened.get_experiment("main").tags) == {
        "dataset": "cifar10",
        "stable": "",
    }


def test_update_tags_appends_and_updates_by_key(experiments):
    """Append mode keeps unrelated values and updates matching keys."""
    experiments.log_experiment("main", tags={"dataset": "mnist", "owner": "alice"})

    updated = experiments.update_tags(
        "main", {"dataset": "cifar10", "stable": ""}, append=True
    )

    assert tags_to_mapping(updated.tags) == {
        "dataset": "cifar10",
        "owner": "alice",
        "stable": "",
    }


def test_update_tags_creates_and_can_update_terminal_experiment(experiments):
    """Tag management creates missing records and remains organizational."""
    created = experiments.update_tags("main", {"owner": "alice"})
    assert tags_to_mapping(created.tags) == {"owner": "alice"}

    experiments.finish_experiment("main")
    updated = experiments.update_tags("main", {"stage": "production"}, append=True)

    assert updated.status == STATUS_FINISHED
    assert tags_to_mapping(updated.tags) == {"owner": "alice", "stage": "production"}


def test_finish_experiment(experiments):
    """finish_experiment persists a terminal status."""
    experiments.log_experiment("main")
    experiments.finish_experiment("main", STATUS_FAILED)
    assert experiments.get_experiment("main").status == STATUS_FAILED


def test_finish_missing_experiment_raises(experiments):
    """Finishing an env that never logged an experiment raises KeyError."""
    with pytest.raises(KeyError):
        experiments.finish_experiment("nope")


@pytest.mark.parametrize("status", [None, STATUS_FAILED], ids=["default", "failed"])
def test_finish_on_finished_raises(experiments, status):
    """Finishing a terminal experiment is rejected, whatever status is asked for."""
    experiments.log_experiment("main")
    experiments.finish_experiment("main")
    finished_at = experiments.get_experiment("main").finished_at

    with pytest.raises(ExperimentFinishedError):
        if status is None:
            experiments.finish_experiment("main")
        else:
            experiments.finish_experiment("main", status)

    stored = experiments.get_experiment("main")
    assert stored.status == STATUS_FINISHED
    assert stored.finished_at == finished_at


def test_log_experiment_on_finished_raises(experiments):
    """Updating an experiment that is already terminal is rejected."""
    experiments.log_experiment("main", params={"lr": 0.1})
    experiments.finish_experiment("main")

    with pytest.raises(ExperimentFinishedError):
        experiments.log_experiment("main", params={"lr": 0.2})

    assert experiments.get_experiment("main").get_param("lr").value == 0.1


def test_log_metric_on_finished_raises(experiments):
    """Appending a metric to a terminal experiment is rejected."""
    experiments.log_metric("main", "acc", 0.9)
    experiments.finish_experiment("main", STATUS_FAILED)

    with pytest.raises(ExperimentFinishedError):
        experiments.log_metric("main", "acc", 0.95)

    assert len(experiments.get_experiment("main").metrics) == 1


def test_list_experiments(experiments, store):
    """list_experiments returns only envs that actually have a blob."""
    experiments.log_experiment("a")
    experiments.log_experiment("b")
    # An ordinary env with window data but no experiment must be skipped.
    store.save_env("plain", {"jsons": {"w": {"id": "w"}}, "reload": {}})

    listed = sorted(exp.env_id for exp in experiments.list_experiments())
    assert listed == ["a", "b"]


def test_delete_experiment_keeps_env(experiments, store):
    """delete_experiment drops the blob but leaves the environment intact."""
    store.save_env("main", {"jsons": {"w": {"id": "w"}}, "reload": {}})
    experiments.log_experiment("main", params={"lr": 0.01})

    assert experiments.delete_experiment("main")
    assert experiments.get_experiment("main") is None

    env = store.load_env("main")
    assert "w" in env["jsons"]  # the window data the env had before is untouched
    assert "experiment" not in env


def test_delete_missing_experiment_returns_false(experiments):
    """Deleting from an env with no experiment reports False."""
    assert not experiments.delete_experiment("nope")


def test_experiment_coexists_with_window_data(experiments, store):
    """Logging onto an env with windows preserves those windows on disk."""
    store.save_env("main", {"jsons": {"win_0": {"id": "win_0"}}, "reload": {"foo": 1}})

    experiments.log_experiment("main", params={"lr": 0.01})

    env = store.load_env("main")
    assert "win_0" in env["jsons"]
    assert env["reload"] == {"foo": 1}
    assert env["experiment"]["params"][0]["value"] == 0.01


def test_experiment_survives_lazy_env_reload_and_save(experiments, store, env_path):
    """A prior-session experiment is not clobbered by a later full-env save.

    Mirrors the server's cross-restart path: an env logged in one session is
    reloaded as a LazyEnvData, materialised by an unrelated window write, and
    persisted again by the shutdown save_all. The experiment blob must ride
    through rather than being stripped to jsons/reload.
    """
    experiments.log_experiment("main", params={"lr": 0.01})

    state = {"main": LazyEnvData(store, "main")}
    state["main"]["jsons"]["win_1"] = {"id": "win_1"}
    store.save_all(state)

    exp = ExperimentStore(JSONStore(env_path)).get_experiment("main")
    assert exp is not None, "experiment was clobbered by the full-env save"
    assert exp.get_param("lr").value == 0.01


# -- ExperimentStore with a live env provider ---------------------------------
#
# The server passes ``state.get`` so that persisting experiment metadata can
# never rewrite an env file from a copy that is missing windows created - or
# reviving windows closed - since the file was last written.


def test_write_persists_live_windows(live_experiments, live_state, store):
    """A window living only in memory reaches disk on the next log."""
    live_state["main"] = {"jsons": {"hp": {"id": "hp"}}, "reload": {}}

    live_experiments.log_metric("main", "acc", 0.9)

    env = store.load_env("main")
    assert "hp" in env["jsons"]
    assert env["experiment"]["metrics"][0]["value"] == 0.9


def test_write_lands_in_the_live_env(live_experiments, live_state):
    """The experiment blob is set on the state env itself, not a copy."""
    live_state["main"] = {"jsons": {}, "reload": {}}

    live_experiments.log_experiment("main", params={"lr": 0.01})

    assert live_state["main"]["experiment"]["params"][0]["value"] == 0.01


def test_closed_window_stays_gone(live_experiments, live_state, store):
    """A window closed in memory is not resurrected from the stale file."""
    store.save_env("main", {"jsons": {"doomed": {"id": "doomed"}}, "reload": {}})
    live_state["main"] = {"jsons": {}, "reload": {}}

    live_experiments.log_metric("main", "acc", 0.9)

    assert "doomed" not in store.load_env("main")["jsons"]


def test_env_not_in_state_falls_back_to_disk(live_experiments, store):
    """An env the provider does not serve is read from (and keeps) its file."""
    store.save_env("other", {"jsons": {"w": {"id": "w"}}, "reload": {}})

    live_experiments.log_experiment("other", params={"lr": 0.1})

    env = store.load_env("other")
    assert "w" in env["jsons"]
    assert env["experiment"]["params"][0]["value"] == 0.1


def test_lazy_env_data_round_trips(live_experiments, live_state, store):
    """A LazyEnvData env is written through and persisted with its windows."""
    store.save_env("main", {"jsons": {"w": {"id": "w"}}, "reload": {}})
    live_state["main"] = LazyEnvData(store, "main")

    live_experiments.log_metric("main", "acc", 0.5)

    env = store.load_env("main")
    assert "w" in env["jsons"]
    assert env["experiment"]["metrics"][0]["value"] == 0.5


def test_delete_experiment_through_lazy_env(live_experiments, live_state, store):
    """delete_experiment removes the blob from a LazyEnvData live env."""
    store.save_env("main", {"jsons": {"w": {"id": "w"}}, "reload": {}})
    live_state["main"] = LazyEnvData(store, "main")
    live_experiments.log_experiment("main", params={"lr": 0.01})

    assert live_experiments.delete_experiment("main") is True

    assert "experiment" not in live_state["main"]
    env = store.load_env("main")
    assert "experiment" not in env
    assert "w" in env["jsons"]


# -- ExperimentStore with persistence disabled --------------------------------


def test_log_returns_experiment_but_read_is_empty():
    """log_* still returns a valid object though nothing is persisted."""
    store = ExperimentStore(JSONStore(None))

    assert isinstance(store.log_experiment("main", params={"lr": 0.01}), Experiment)
    assert store.get_experiment("main") is None
    assert store.list_experiments() == []


# -- ranking a field that holds mixed types -----------------------------------


def _ranked(experiments, descending):
    result = experiments.search(sort_by="acc", descending=descending)
    found = result["experiments"] if isinstance(result, dict) else result
    return [experiment.env_id for experiment in found]


def test_a_string_never_outranks_the_highest_number(experiments):
    """Numbers lead in both directions, so a string cannot top the ranking.

    ``_order_key`` tags numbers ahead of everything else; reversing the whole
    key for a descending sort used to reverse that tag too, putting the run
    whose value is a string above the run holding the largest number.
    """
    experiments.log_experiment("run_five", params={"acc": 5})
    experiments.log_experiment("run_ten", params={"acc": 10})
    experiments.log_experiment("run_str", params={"acc": "pending"})

    assert _ranked(experiments, descending=True) == ["run_ten", "run_five", "run_str"]
    assert _ranked(experiments, descending=False) == ["run_five", "run_ten", "run_str"]


def test_a_bounded_page_is_not_filled_by_a_string(experiments):
    """The heap path ranks like the sort path, so a page keeps the numbers.

    ``search_page`` selects through ``heapq`` rather than sorting, on the same
    key. Ranking a string first there does not merely misorder the page: it
    takes a slot, evicting a run that belongs on it.
    """
    experiments.log_experiment("run_five", params={"acc": 5})
    experiments.log_experiment("run_ten", params={"acc": 10})
    experiments.log_experiment("run_str", params={"acc": "pending"})

    page, total = experiments.search_page(sort_by="acc", descending=True, limit=2)
    assert [experiment.env_id for experiment in page] == ["run_ten", "run_five"]
    assert total == 3

    page, total = experiments.search_page(sort_by="acc", descending=False, limit=2)
    assert [experiment.env_id for experiment in page] == ["run_five", "run_ten"]
    assert total == 3


def test_equal_values_keep_their_scan_order_in_both_directions(experiments):
    """Reversing the comparison must not reverse ties."""
    for env_id in ("first", "second", "third"):
        experiments.log_experiment(env_id, params={"acc": 7})

    assert _ranked(experiments, descending=True) == ["first", "second", "third"]
    assert _ranked(experiments, descending=False) == ["first", "second", "third"]


# -- Metric history: read lazily, appended copy-on-write ----------------------


@pytest.fixture
def metric_builds(monkeypatch):
    """Count every ``Metric`` built, however it was built."""
    built = []
    original = Metric.__init__

    def counting(self, *args, **kwargs):
        built.append(1)
        original(self, *args, **kwargs)

    monkeypatch.setattr(Metric, "__init__", counting)
    return built


def _series(count, key="acc"):
    """``count`` stored observations, in the form the server writes them."""
    return [
        {"key": key, "value": float(i), "step": i, "timestamp": 1000.0 + i}
        for i in range(count)
    ]


def _seed_history(store, env_id, count):
    """Persist an env whose experiment already holds ``count`` observations."""
    ExperimentStore(store).log_experiment(env_id, name=env_id)
    env = store.load_env(env_id)
    env["experiment"]["metrics"] = _series(count)
    store.save_env(env_id, env)


@pytest.mark.parametrize("count", [500, 4000])
def test_logging_one_observation_costs_one_metric(store, count, metric_builds):
    """Appending to a 4,000-observation history builds what 500 does: one.

    The shape assertion the PR rests on, rather than a timing one. Logging
    used to rebuild the series as objects on the way in and as dicts on the
    way out, so this count was ``count + 1`` and the run it belonged to got
    slower with every step it logged.
    """
    _seed_history(store, "run", count)
    metric_builds.clear()

    ExperimentStore(store).log_metric("run", "acc", 1.0, step=count)

    assert len(metric_builds) == 1
    assert len(store.load_experiment("run")["metrics"]) == count + 1


@pytest.mark.parametrize("count", [500, 4000])
def test_scanning_experiments_builds_no_metric_objects(store, count, metric_builds):
    """A search reads the newest value per key without materialising a series.

    Every environment on disk is read to answer one search, so a ``Metric``
    per observation per environment was the dominant cost of the endpoint.
    """
    _seed_history(store, "run", count)
    metric_builds.clear()

    page, total = ExperimentStore(store).search_page(limit=10)

    assert total == 1
    assert metric_builds == []
    assert page[0].latest_metric_values()["acc"] == float(count - 1)


def test_a_metric_batch_shares_one_read_and_one_write(store, monkeypatch):
    """Observations logged together are read and persisted once, not once each."""
    reads, writes = [], []
    read, write = ExperimentStore._read, ExperimentStore._write

    def counting_read(self, env_id):
        reads.append(env_id)
        return read(self, env_id)

    def counting_write(self, env_id, env, experiment):
        writes.append(env_id)
        return write(self, env_id, env, experiment)

    monkeypatch.setattr(ExperimentStore, "_read", counting_read)
    monkeypatch.setattr(ExperimentStore, "_write", counting_write)

    ExperimentStore(store).log_metrics(
        "run", {"acc": 0.9, "loss": 0.1, "f1": 0.5}, step=7
    )

    assert reads == ["run"]
    assert writes == ["run"]
    stored = store.load_experiment("run")["metrics"]
    assert [observation["key"] for observation in stored] == ["acc", "loss", "f1"]
    assert {observation["step"] for observation in stored} == {7}


def test_a_published_series_never_grows_under_its_reader():
    """``to_dict`` hands back the stored list, so appending copies it first.

    ``_resident_experiments`` hands a stored blob to the storage worker
    without copying it, and the dict a write rebinds is shallow, so the list
    inside it can be one a worker is already iterating. Growing that list in
    place is what this must never do.
    """
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = _series(3)
    exp = Experiment.from_dict(blob)

    published = exp.to_dict()["metrics"]
    assert published is blob["metrics"]

    exp.add_metric("acc", 9.0, step=3)

    assert len(published) == 3
    assert len(exp.metrics) == 4
    assert exp.to_dict()["metrics"] is not published


def test_appending_rebinds_the_series_the_server_is_holding(
    live_experiments, live_state
):
    """Each logged observation leaves the previous blob's series untouched."""
    live_state["run"] = {"jsons": {}, "reload": {}}
    live_experiments.log_metric("run", "acc", 0.1)
    first = live_state["run"]["experiment"]["metrics"]

    live_experiments.log_metric("run", "acc", 0.2)
    second = live_state["run"]["experiment"]["metrics"]

    assert len(first) == 1
    assert second is not first
    assert [observation["value"] for observation in second] == [0.1, 0.2]


def test_a_tag_write_reuses_the_series_it_does_not_touch(live_experiments, live_state):
    """Writing tags stops rebuilding the metric series it never reads."""
    live_state["run"] = {"jsons": {}, "reload": {}}
    live_experiments.log_metric("run", "acc", 0.1)
    series = live_state["run"]["experiment"]["metrics"]

    live_experiments.update_tags("run", {"owner": "bob"})

    assert live_state["run"]["experiment"]["metrics"] is series


def test_stored_observations_are_returned_as_they_were_written(store):
    """A stored observation is echoed verbatim; only a new one is normalised.

    Rebuilding the series used to launder it on every read -- stamping a
    missing ``timestamp`` with the time of the read, and dropping anything it
    did not recognise. Handing the stored form back instead means what a
    reader sees is what is on disk.
    """
    _seed_history(store, "run", 0)
    env = store.load_env("run")
    env["experiment"]["metrics"] = [{"key": "acc", "value": 1.0, "unit": "%"}]
    store.save_env("run", env)

    ExperimentStore(store).log_metric("run", "loss", 2.0)

    stored = store.load_experiment("run")["metrics"]
    assert stored[0] == {"key": "acc", "value": 1.0, "unit": "%"}
    assert set(stored[1]) == {"key", "value", "step", "timestamp"}


def test_an_observation_with_no_key_is_skipped_rather_than_fatal():
    """Reading an experiment no longer parses observations nothing asks for.

    One hand-edited env file used to make every scan that walked past it
    fail, because the series was rebuilt whether or not it was read. The
    readers that summarise a series now skip the entry, as the flatten path
    always has, and asking for that observation itself still raises.
    """
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = [{"value": 1.0}]
    exp = Experiment.from_dict(blob)

    assert exp.latest_metric_values() == {}
    assert exp.latest_metric("acc") is None
    assert build_record(exp)["env_id"] == "run"
    with pytest.raises(KeyError):
        exp.metrics[0]


def test_a_series_that_is_not_a_list_parses_as_it_always_did():
    """Only a list can be held in its stored form; anything else still raises."""
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = "acc"

    with pytest.raises(TypeError):
        Experiment.from_dict(blob)


def test_latest_metric_values_matches_a_reverse_walk():
    """The accessor answers exactly what walking the series in reverse did."""
    exp = Experiment(env_id="run")
    for key, value in (
        ("acc", 1.0),
        ("loss", 9.0),
        ("acc", 2.0),
        ("f1", float("nan")),
        ("loss", 8.0),
    ):
        exp.add_metric(key, value)
    walked = {}
    for metric in reversed(exp.metrics):
        walked.setdefault(metric.key, metric.value)

    latest = Experiment.from_dict(exp.to_dict()).latest_metric_values()

    assert list(latest) == list(walked)
    assert latest["acc"] == walked["acc"] == 2.0
    assert latest["loss"] == walked["loss"] == 8.0
    assert math.isnan(latest["f1"])


def test_a_stored_series_reads_like_the_list_it_replaced():
    """Every way the series was read as a list reads the same, and caches."""
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = _series(3)
    series = Experiment.from_dict(blob).metrics

    assert isinstance(series, LazyMetricList)
    assert len(series) == 3
    assert series[0].value == 0.0
    assert series[-1].step == 2
    assert [observation.value for observation in series] == [0.0, 1.0, 2.0]
    assert [observation.step for observation in reversed(series)] == [2, 1, 0]
    assert [observation.value for observation in series[1:]] == [1.0, 2.0]
    assert series[0] is series[0]
    assert series == [Metric.from_dict(data) for data in _series(3)]
    with pytest.raises(IndexError):
        series[3]


def test_an_edited_metric_is_published_as_edited(store):
    """Editing an indexed observation still persists, as it did when it was a list.

    Indexing hands out a live ``Metric``; the eager serialiser called
    ``to_dict`` on every one of them, so changing a value and writing was a
    workflow that worked. Publishing the stored dicts untouched would have
    dropped the edit silently.
    """
    _seed_history(store, "run", 3)
    experiments = ExperimentStore(store)
    exp = experiments.get_experiment("run")

    exp.metrics[1].value = 99.0
    experiments._write("run", store.load_env("run"), exp)

    assert store.load_experiment("run")["metrics"][1]["value"] == 99.0


def test_an_edit_does_not_reach_the_list_already_handed_out():
    """A write-back copies first, for the reason an append does."""
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = _series(3)
    exp = Experiment.from_dict(blob)

    published = exp.to_dict()["metrics"]
    exp.metrics[0].value = 42.0
    republished = exp.to_dict()["metrics"]

    assert published is blob["metrics"]
    assert published[0]["value"] == 0.0
    assert republished is not published
    assert republished[0]["value"] == 42.0


def test_reading_an_observation_does_not_count_as_editing_it(store):
    """An observation that was only read is still echoed as it was stored.

    ``Metric.from_dict`` stamps a missing ``timestamp`` with the time of the
    read, so comparing the rebuilt object against the stored dict would call
    every such observation edited and launder it on the next write. The
    comparison is against what the object held when it was built instead.
    """
    _seed_history(store, "run", 0)
    env = store.load_env("run")
    env["experiment"]["metrics"] = [{"key": "acc", "value": 1.0, "unit": "%"}]
    store.save_env("run", env)
    experiments = ExperimentStore(store)
    exp = experiments.get_experiment("run")

    assert exp.metrics[0].value == 1.0
    experiments._write("run", store.load_env("run"), exp)

    assert store.load_experiment("run")["metrics"][0] == {
        "key": "acc",
        "value": 1.0,
        "unit": "%",
    }


def test_an_empty_batch_creates_no_experiment(store):
    """A batch recording nothing brings no run into being.

    An experiment is created by an observation; a request carrying none would
    otherwise persist a run with an empty series, which then shows up in every
    search as a run nobody logged to.
    """
    assert ExperimentStore(store).log_metrics("run", {}) is None
    assert store.load_experiment("run") is None


def test_an_empty_batch_writes_nothing_to_an_existing_experiment(store, monkeypatch):
    """It is a no-op on a run that does exist, too -- not a rewrite of it."""
    experiments = ExperimentStore(store)
    experiments.log_metric("run", "acc", 0.9)
    writes = []
    monkeypatch.setattr(
        ExperimentStore,
        "_write",
        lambda self, env_id, env, experiment: writes.append(env_id),
    )

    returned = experiments.log_metrics("run", {})

    assert writes == []
    assert returned.latest_metric("acc").value == 0.9


def test_an_empty_batch_is_still_refused_by_a_terminal_experiment(store):
    """What a finished run refuses is the attempt, not what it carried."""
    experiments = ExperimentStore(store)
    experiments.log_metric("run", "acc", 0.9)
    experiments.finish_experiment("run")

    with pytest.raises(ExperimentFinishedError):
        experiments.log_metrics("run", {})


def test_an_edit_to_an_indexed_metric_is_the_latest_value():
    """A summarising read sees the edit, not the number it replaced.

    Indexing hands out a live ``Metric`` and editing one is how the series is
    edited, but the edit only reaches the stored dicts on the next publish.
    A comparison or a query record built in between would otherwise report
    the pre-edit number while :meth:`latest_metric` reported the new one.
    """
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = _series(3)
    exp = Experiment.from_dict(blob)

    exp.metrics[-1].value = 42.0

    assert exp.latest_metric_values() == {"acc": 42.0}
    assert exp.latest_metric("acc").value == 42.0
    assert build_record(exp)["metric.acc"] == 42.0


def test_a_renamed_metric_is_found_under_the_name_it_now_carries():
    """Renaming an indexed observation moves it, rather than duplicating it."""
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = _series(2)
    exp = Experiment.from_dict(blob)

    exp.metrics[1].key = "loss"

    assert exp.latest_metric_values() == {"loss": 1.0, "acc": 0.0}
    assert exp.latest_metric("loss").value == 1.0
    assert exp.latest_metric("acc").value == 0.0


def test_an_edit_seen_by_a_summarising_read_is_still_published():
    """Reading the edit neither persists it nor disturbs the stored list.

    The read folds the edit into a copy, so the list a caller is already
    holding keeps the value it was published with and the write that follows
    still has the edit to make.
    """
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = _series(2)
    exp = Experiment.from_dict(blob)

    exp.metrics[0].value = 7.0
    assert exp.latest_metric_values() == {"acc": 1.0}
    assert blob["metrics"][0]["value"] == 0.0

    assert exp.to_dict()["metrics"][0]["value"] == 7.0


def test_an_observation_that_was_only_read_is_not_treated_as_an_edit():
    """Indexing alone leaves the stored dicts authoritative for a summary.

    ``Metric.from_dict`` stamps a missing ``timestamp`` with the time of the
    read, so an observation that was merely indexed must not count as edited
    -- the same rule publishing applies, and what keeps the summarising walk
    off the objects on every series a reader has looked at.
    """
    blob = Experiment(env_id="run").to_dict()
    blob["metrics"] = [{"key": "acc", "value": 1.0, "unit": "%"}]
    exp = Experiment.from_dict(blob)

    assert exp.metrics[0].value == 1.0

    assert exp.metrics._edits() == {}
    assert exp.latest_metric_values() == {"acc": 1.0}
    assert exp.to_dict()["metrics"] is blob["metrics"]
