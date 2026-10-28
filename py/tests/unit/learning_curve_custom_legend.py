#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for learning_curve traces created with custom legend labels.

Creation names each trace after the matching entry of ``opts['legend']``, but the
named updates addressed the metric keys instead, so an append left a second set
of traces behind and a remove could not find the displayed one.
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def messages(send):
    """Every message a patched ``_send`` received."""
    return [call[0][0] for call in send.call_args_list]


def updates(send):
    return [
        call[0][0]
        for call in send.call_args_list
        if call[1].get("endpoint", "events") == "update"
    ]


def test_learning_curve_append_targets_the_legend_named_traces(offline_client):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1") as create:
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], opts=opts
        )

    created = messages(create)[0]["data"]
    assert [t["name"] for t in created] == ["Training loss", "Validation loss"]

    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"train": [0.8], "val": [0.9]},
            step=[1],
            win="w1",
            opts=opts,
            update="append",
        )

    assert [m["name"] for m in updates(send)] == ["Training loss", "Validation loss"]


def test_learning_curve_remove_deletes_the_legend_named_trace(offline_client):
    opts = {"legend": ["Training loss"]}
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"train": [1.0]}, win="w1", opts=opts, update="remove"
        )

    (removal,) = updates(send)
    assert removal["name"] == "Training loss"
    assert removal["delete"] is True


def test_learning_curve_subset_append_resolves_the_full_legend(offline_client):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], opts=opts
        )

    # The legend is the one the creation call used, longer than the metric list
    # of this update: the label is looked up by the metric it was created for,
    # so the values go to the validation trace rather than to the first label.
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"val": [0.9]}, step=[1], win="w1", opts=opts, update="append"
        )

    sent = {m["name"]: m["data"][0]["y"] for m in updates(send)}
    assert sent == {"Validation loss": [0.9]}

    # A label that disagrees with the one the trace was created under cannot
    # rename it, so the created name is still what the update addresses.
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"val": [0.95]},
            step=[2],
            win="w1",
            opts={"legend": ["val loss"]},
            update="append",
        )

    assert [m["name"] for m in updates(send)] == ["Validation loss"]


def test_learning_curve_update_without_a_creation_reads_the_legend_in_order(
    offline_client,
):
    """There is no stored label to look a metric up in, so one entry per metric."""
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"val": [0.9]},
            step=[1],
            win="w1",
            opts={"legend": ["Validation loss"]},
            update="append",
        )

    assert [m["name"] for m in updates(send)] == ["Validation loss"]


def test_learning_curve_update_without_a_creation_keeps_the_metric_key(
    offline_client,
):
    """A legend longer than the metric list names nothing this client can tell
    apart, so the metric key is used rather than a label that may belong to
    another metric's trace, and the call is not refused."""
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"val": [0.9]},
            step=[1],
            win="w1",
            opts={"legend": ["Training loss", "Validation loss"]},
            update="append",
        )

    assert [m["name"] for m in updates(send)] == ["val"]


def test_learning_curve_append_that_creates_the_window_records_its_names(
    offline_client,
):
    """An append is what created the window here, so the names it was created
    under have to be kept for the updates that follow it."""
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1") as created:
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]},
            step=[0],
            win="w1",
            opts=opts,
            update="append",
        )

    assert [m["name"] for m in updates(created)] == [
        "Training loss",
        "Validation loss",
    ]

    # The legend is left out, so the names the window carries are the ones to
    # address: the metric keys would add a second set of traces.
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"train": [0.7], "val": [0.9]}, step=[1], win="w1", update="append"
        )

    assert [m["name"] for m in updates(send)] == [
        "Training loss",
        "Validation loss",
    ]


def test_learning_curve_subset_update_uses_the_label_it_is_given(offline_client):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], opts=opts
        )

    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"val": [0.9]},
            step=[1],
            win="w1",
            opts={"legend": ["Validation loss"]},
            update="append",
        )

    assert [m["name"] for m in updates(send)] == ["Validation loss"]


def test_learning_curve_append_maps_each_label_back_to_its_metric(offline_client):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="w1", opts=opts
        )

    # The labels are listed in the order of the creation call, the metrics are
    # not: reading the legend positionally would put val on the train trace.
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"val": [0.9], "train": [0.7]},
            step=[1],
            win="w1",
            opts=opts,
            update="append",
        )

    sent = {m["name"]: m["data"][0]["y"] for m in updates(send)}
    assert sent == {"Training loss": [0.7], "Validation loss": [0.9]}


def test_learning_curve_append_without_a_legend_reuses_the_created_names(
    offline_client,
):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="w1", opts=opts
        )

    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"train": [0.7], "val": [0.9]}, step=[1], win="w1", update="append"
        )

    assert [m["name"] for m in updates(send)] == ["Training loss", "Validation loss"]


def test_learning_curve_remembers_no_names_when_the_creation_fails(offline_client):
    """A failed post answers False and no window was created to name."""
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value=False):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="w1", opts=opts
        )

    assert offline_client._learning_curve_names == {}


def test_closing_a_window_forgets_the_names_it_created(offline_client):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="w1", opts=opts
        )

    with patch.object(offline_client, "_send", return_value="w1") as closed:
        offline_client.close(win="w1")

    assert closed.call_args[1]["endpoint"] == "close"
    assert offline_client._learning_curve_names == {}

    # The window is gone, so an update that leaves the legend out reads the
    # metric keys again instead of names nothing can be sent to.
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"train": [0.7], "val": [0.9]}, step=[1], win="w1", update="append"
        )

    assert [m["name"] for m in updates(send)] == ["train", "val"]


def test_closing_all_windows_forgets_the_names_of_that_env_only(offline_client):
    opts = {"legend": ["Training loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve({"train": [1.0]}, step=[0], win="w1", opts=opts)
    with patch.object(offline_client, "_send", return_value="w2"):
        offline_client.learning_curve(
            {"train": [1.0]}, step=[0], win="w2", env="other", opts=opts
        )

    with patch.object(offline_client, "_send", return_value="1"):
        offline_client.close(win=None)

    assert list(offline_client._learning_curve_names) == [("other", "w2")]


def test_deleting_the_main_env_keeps_its_window_names(offline_client):
    """The server refuses to drop `main`, so its windows keep their names."""
    opts = {"legend": ["Training loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve({"train": [1.0]}, step=[0], win="w1", opts=opts)

    with patch.object(offline_client, "_send", return_value=None) as deleted:
        offline_client.delete_env("main")

    # `None` is what the server answers for the env it protects.
    assert deleted.call_args[1]["endpoint"] == "delete_env"
    assert list(offline_client._learning_curve_names) == [("main", "w1")]

    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"train": [0.7]}, step=[1], win="w1", update="append"
        )

    assert [m["name"] for m in updates(send)] == ["Training loss"]


def test_learning_curve_replace_targets_the_legend_named_traces(offline_client):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="w1", opts=opts
        )

    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"train": [0.8], "val": [0.9]},
            step=[1],
            win="w1",
            opts=opts,
            update="replace",
        )

    replaced = updates(send)
    assert [m["name"] for m in replaced] == ["Training loss", "Validation loss"]
    assert [m["append"] for m in replaced] == [False, False]


def test_learning_curve_subset_update_maps_each_label_back_to_its_metric(
    offline_client,
):
    opts = {"legend": ["Training loss", "Validation loss", "Test loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2], "test": [1.4]}, step=[0], win="w1", opts=opts
        )

    # Two of the three metrics, under their own labels, listed in the order of
    # the creation call: reading that legend positionally puts val on the train
    # trace, because the update's metric order is val first.
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"val": [0.9], "train": [0.7]},
            step=[1],
            win="w1",
            opts={"legend": ["Training loss", "Validation loss"]},
            update="append",
        )

    sent = {m["name"]: m["data"][0]["y"] for m in updates(send)}
    assert sent == {"Training loss": [0.7], "Validation loss": [0.9]}


def test_learning_curve_reports_an_update_that_partly_failed(offline_client):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], win="w1", opts=opts
        )

    # The first metric's update is refused, the second goes through: the answer
    # has to say the call failed rather than carry the last success.
    seen = []

    def post(msg, endpoint="events", **kwargs):
        seen.append(endpoint)
        if endpoint == "update" and seen.count("update") == 1:
            return False
        return "w1"

    with patch.object(offline_client, "_send", side_effect=post) as send:
        result = offline_client.learning_curve(
            {"train": [0.7], "val": [0.9]},
            step=[1],
            win="w1",
            opts=opts,
            update="append",
        )

    assert len(updates(send)) == 2
    assert result is False


def test_deleting_an_env_forgets_its_window_names(offline_client):
    opts = {"legend": ["Training loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve({"train": [1.0]}, step=[0], win="w1", opts=opts)
    with patch.object(offline_client, "_send", return_value="w2"):
        offline_client.learning_curve(
            {"train": [1.0]}, step=[0], win="w2", env="other", opts=opts
        )

    with patch.object(offline_client, "_send", return_value="1") as deleted:
        offline_client.delete_env("other")

    assert deleted.call_args[1]["endpoint"] == "delete_env"
    assert list(offline_client._learning_curve_names) == [("main", "w1")]
