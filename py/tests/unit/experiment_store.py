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

import pytest

from visdom.data_model import JSONStore
from visdom.utils.server_utils import LazyEnvData
from visdom.experiments import (
    Experiment,
    ExperimentFinishedError,
    ExperimentStore,
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
