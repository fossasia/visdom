#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Matching a labelled scatter append to the traces of its labels.

The client sends the label of each trace as ``trace_labels``, and the pane
keeps them. Only an update that sends labels, to a pane that holds them, is
matched by label; everything else is matched by position, as before.
"""

import numpy as np
import pytest

from visdom.utils.server_utils import (
    labelled_update,
    pair_by_label,
    trace_labels_ok,
    update_window,
    window,
)

pytestmark = pytest.mark.unit


def pane(names, labels=None, legend=None):
    args = {
        "win": "w",
        "eid": "main",
        "data": [{"type": "scatter", "x": [0], "y": [0], "name": n} for n in names],
        "layout": {},
        "opts": {} if legend is None else {"legend": legend},
    }
    if labels is not None:
        args["trace_labels"] = labels
    return window(args)


def append(labels, legend=None, name=None):
    args = {
        "data": [{"type": "scatter", "x": [1], "y": [1]} for _ in labels],
        "trace_labels": list(labels),
        "opts": {} if legend is None else {"legend": legend},
    }
    if name is not None:
        args["name"] = name
    return args


def names(p):
    return [d["name"] for d in p["content"]["data"]]


@pytest.mark.parametrize(
    "labels, ok",
    [
        ([1, 2], True),
        (["cat", "1"], True),
        ([3, "dog"], True),
        ([1], False),
        ([1, 2, 3], False),
        ([0, 1], False),
        ([-1, 1], False),
        ([True, 1], False),
        ([1.0, 2], False),
        ([None, 1], False),
        ([[1], 2], False),
        ("12", False),
        ({"a": 1, "b": 2}, False),
        (None, False),
    ],
)
def test_trace_labels_give_one_number_or_string_per_entry(labels, ok):
    assert trace_labels_ok(labels, [{}, {}]) is ok


def test_trace_labels_need_a_data_list():
    assert trace_labels_ok([1], None) is False


def test_a_label_joins_the_trace_holding_it():
    assert pair_by_label([1, 2], [2]) == [1]
    assert pair_by_label([1, 2], [2, 1]) == [1, 0]
    assert pair_by_label(["cat", "dog"], ["dog"]) == [1]


def test_a_label_the_pane_lacks_is_a_new_trace():
    assert pair_by_label([1, 2], [3, 1]) == [None, 0]
    assert pair_by_label([], [1]) == [None]


def test_a_label_number_is_the_same_label_as_its_digits():
    """0-based class ids send values while a batch has 0, numbers once it hasn't."""
    assert pair_by_label(["0", "1", "2"], [2]) == [2]
    assert pair_by_label([2], ["2"]) == [0]


def test_a_trace_without_a_label_is_never_matched():
    assert pair_by_label([None, 1], [1, 2]) == [1, None]


def test_repeated_labels_take_their_traces_in_order():
    assert pair_by_label([1, 1], [1, 1, 1]) == [0, 1, None]


def test_the_pane_keeps_the_labels_it_was_created_with():
    assert pane(["2", "1"], [1, 2])["trace_labels"] == [1, 2]


@pytest.mark.parametrize("labels", [None, [1], [0, 1], "12"])
def test_a_pane_keeps_no_labels_unless_one_per_trace_was_sent(labels):
    assert "trace_labels" not in pane(["a", "b"], labels)


def test_a_labelled_update_reads_the_panes_labels():
    p = pane(["2", "1"], [1, 2])
    assert labelled_update(p, append([1])) == [1, 2]


@pytest.mark.parametrize(
    "p, args",
    [
        (pane(["a", "b"]), append([1])),
        (pane(["a", "b"], [1, 2]), {"data": [{"x": [1]}]}),
        (pane(["a", "b"], [1, 2]), append([1, 2], name="a")),
        (pane(["a", "b"], [1, 2]), dict(append([1]), trace_labels=[1, 2])),
    ],
    ids=["pane without labels", "update without", "named update", "bad labels"],
)
def test_anything_else_is_not_a_labelled_update(p, args):
    assert labelled_update(p, args) is None


def test_a_pane_whose_labels_fell_out_of_step_is_not_labelled():
    p = pane(["a", "b"], [1, 2])
    p["content"]["data"].append({"name": "c"})
    assert labelled_update(p, append([1])) is None


def test_a_legend_renames_each_trace_by_its_label_number():
    """A scatter created from labels 2 and 3 holds them out of position."""
    p = pane(["2", "3"], [2, 3])
    update_window(p, append([2, 3], legend=["a", "b", "c"]))
    assert names(p) == ["b", "c"]


def test_a_legend_renames_traces_the_update_has_no_points_for():
    p = pane(["1", "2"], [1, 2])
    update_window(p, append([1], legend=["a", "b"]))
    assert names(p) == ["a", "b"]


def test_a_legend_leaves_traces_past_its_end_and_label_values_alone():
    p = pane(["2", "3", "cat"], [2, 3, "cat"])
    update_window(p, append([2], legend=["a", "b"]))
    assert names(p) == ["b", "3", "cat"]


def test_a_legend_without_labels_still_renames_by_position():
    p = pane(["2", "3"], [2, 3])
    update_window(p, {"opts": {"legend": ["a", "b", "c"]}})
    assert names(p) == ["a", "b"]


def test_a_legend_on_a_pane_without_labels_still_renames_by_position():
    p = pane(["2", "3"])
    update_window(p, append([2, 3], legend=["a", "b", "c"]))
    assert names(p) == ["a", "b"]


# ---------------------------------------------------------------- client ----


def sent(capture_send, call):
    return capture_send(call)["payload"]


XY = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])


def test_scatter_sends_the_label_number_of_each_trace(capture_send):
    msg = sent(capture_send, lambda v: v.scatter(XY, Y=[3, 1, 3]))
    assert msg["trace_labels"] == [1, 3]
    assert [d["name"] for d in msg["data"]] == ["1", "3"]


def test_scatter_sends_label_numbers_under_a_legend(capture_send):
    msg = sent(
        capture_send, lambda v: v.scatter(XY, Y=[2, 1, 2], opts={"legend": ["2", "1"]})
    )
    assert msg["trace_labels"] == [1, 2]
    assert [d["name"] for d in msg["data"]] == ["2", "1"]


@pytest.mark.parametrize(
    "Y, labels",
    [
        (["dog", "cat", "dog"], ["cat", "dog"]),
        ([0, 1, 2], ["0", "1", "2"]),
        ([0.0, 1.0, 1.5], ["0", "1", "1.5"]),
        ([True, False, True], ["False", "True"]),
    ],
    ids=["strings", "0-based ints", "floats", "bools"],
)
def test_scatter_sends_label_values_as_strings(capture_send, Y, labels):
    msg = sent(capture_send, lambda v: v.scatter(XY, Y=Y))
    assert msg["trace_labels"] == labels


def test_scatter_sends_labels_on_an_append(capture_send):
    msg = sent(
        capture_send,
        lambda v: v.scatter(XY[:1], Y=[2], win="w", update="append"),
    )
    assert msg["trace_labels"] == [2]


@pytest.mark.parametrize(
    "call",
    [
        lambda v: v.scatter(XY),
        lambda v: v.scatter(XY, Y=[1, 1, 1], name="train"),
        lambda v: v.scatter(XY, Y=[1, 2, 1], opts={"store_history": True}),
    ],
    ids=["no labels", "named", "plot history"],
)
def test_scatter_sends_no_labels_without_labelled_traces(capture_send, call):
    msg = sent(capture_send, call)
    assert "trace_labels" not in msg


def test_line_sends_the_number_of_each_line(capture_send):
    msg = sent(capture_send, lambda v: v.line(Y=np.array([[1, 2], [3, 4]])))
    assert msg["trace_labels"] == [1, 2]
