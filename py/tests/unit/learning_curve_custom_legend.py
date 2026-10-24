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


def test_learning_curve_subset_update_rejects_the_full_legend(offline_client):
    opts = {"legend": ["Training loss", "Validation loss"]}
    with patch.object(offline_client, "_send", return_value="w1"):
        offline_client.learning_curve(
            {"train": [1.0], "val": [1.2]}, step=[0], opts=opts
        )

    # A subset update cannot be read against a legend longer than its metric
    # list: the first label would send the values to another metric's trace.
    with patch.object(offline_client, "_send", return_value="w1"):
        with pytest.raises(AssertionError, match="one legend entry per metric"):
            offline_client.learning_curve(
                {"val": [0.9]}, step=[1], win="w1", opts=opts, update="append"
            )


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
