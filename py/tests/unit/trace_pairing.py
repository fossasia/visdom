#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""``pair_traces``: which existing trace each entry of an unnamed update hits."""

import pytest

from visdom.server.handlers.web_handlers import pair_traces
from visdom.utils.server_utils import label_number

pytestmark = pytest.mark.unit


def traces(*names):
    return [{"name": n} for n in names]


def paired(pdata, new_data, legend=None):
    return [(i, e["name"]) for i, e in pair_traces(pdata, new_data, legend)]


def test_a_matching_name_wins_over_position():
    assert paired(traces("cat", "dog"), traces("dog")) == [(1, "dog")]


def test_order_of_the_entries_does_not_matter():
    pairs = paired(traces("cat", "dog"), traces("dog", "cat"))
    assert pairs == [(1, "dog"), (0, "cat")]


def test_an_unmatched_entry_becomes_a_new_trace():
    pairs = paired(traces("cat", "dog"), traces("bird", "dog"))
    assert pairs == [(None, "bird"), (1, "dog")]


def test_default_names_with_no_match_stay_positional():
    """A line renamed by its legend still appends with the default names."""
    pairs = paired(traces("train", "val"), traces("1", "2"))
    assert pairs == [(0, "1"), (1, "2")]


def test_default_names_on_a_partly_renamed_line_stay_positional():
    """Only "val" was renamed; "1" still sits at its own position."""
    pairs = paired(traces("1", "val"), traces("1", "2"))
    assert pairs == [(0, "1"), (1, "2")]


def test_a_label_number_on_traces_named_otherwise_stays_positional():
    """Nothing says which of "cat" and "dog" label 1 is, so it isn't a new trace."""
    pdata = [{"name": n, "mode": "markers"} for n in ("cat", "dog")]
    assert paired(pdata, traces("1")) == [(0, "1")]


def test_a_label_number_on_a_trace_given_its_own_name_stays_positional():
    """``scatter(X, name="foo")``, then appended to without a name."""
    pdata = [{"name": "foo", "mode": "markers"}]
    assert paired(pdata, traces("1")) == [(0, "1")]


def test_label_numbers_on_unnamed_traces_stay_positional():
    pdata = [{"x": [0]}, {"x": [1]}]
    assert paired(pdata, traces("2")) == [(0, "2")]
    assert paired(pdata, traces("1", "2")) == [(0, "1"), (1, "2")]


def test_default_names_on_a_line_with_markers_stay_positional():
    pdata = [{"name": n, "mode": "lines+markers"} for n in ("train", "val")]
    assert paired(pdata, traces("1", "2")) == [(0, "1"), (1, "2")]


def test_default_names_on_numbered_traces_are_new_labels():
    """Traces named only by numbers were never renamed, so the positional
    fallback for a legend-renamed line doesn't apply."""
    assert paired(traces("2", "3"), traces("1")) == [(None, "1")]


def test_a_batch_of_only_new_classes_becomes_new_traces():
    assert paired(traces("cat", "dog"), traces("bird")) == [(None, "bird")]


@pytest.mark.parametrize(
    "labels, expected",
    [(["2"], [1]), (["1", "2"], [0, 1]), (["2", "1"], [1, 0])],
    ids=["one", "both", "reversed"],
)
def test_a_label_number_joins_the_trace_its_legend_entry_named(labels, expected):
    """A plot created with a legend, appended to without it."""
    pairs = paired(traces("cat", "dog"), traces(*labels), legend=["cat", "dog"])
    assert [i for i, _ in pairs] == expected


def test_a_label_past_the_legend_becomes_a_new_trace():
    pairs = paired(traces("cat", "dog"), traces("3"), legend=["cat", "dog"])
    assert pairs == [(None, "3")]


def test_a_legend_entry_without_a_trace_yet_becomes_a_new_trace():
    pairs = paired(traces("cat", "dog"), traces("3"), legend=["cat", "dog", "bird"])
    assert pairs == [(None, "3")]


def test_a_trace_added_under_its_number_keeps_that_label():
    pairs = paired(traces("cat", "dog", "3"), traces("3"), legend=["cat", "dog"])
    assert pairs == [(2, "3")]


def test_names_still_match_by_name_on_a_plot_with_a_legend():
    pairs = paired(traces("cat", "dog"), traces("dog", "bird"), legend=["cat", "dog"])
    assert pairs == [(1, "dog"), (None, "bird")]


def test_a_legend_that_is_not_a_list_is_ignored():
    assert paired(traces("cat", "dog"), traces("2"), legend="cat") == [(0, "2")]


@pytest.mark.parametrize(
    "name, number",
    [
        ("1", 1),
        ("12", 12),
        ("0", None),
        ("01", None),
        ("-1", None),
        ("1.0", None),
        ("\u0663", None),
        ("", None),
        (3, None),
        (None, None),
    ],
)
def test_label_number_is_only_the_clients_own_numbering(name, number):
    assert label_number(name) == number


def test_entries_without_names_stay_positional():
    pairs = pair_traces(traces("cat", "dog"), [{"x": [1]}, {"x": [2]}])
    assert [i for i, _ in pairs] == [0, 1]


def test_positional_pairing_stops_at_the_shorter_side():
    assert paired(traces("a", "b", "c"), traces("1")) == [(0, "1")]


def test_repeated_names_take_the_traces_in_order():
    pairs = paired(traces("x", "x"), traces("x", "x", "x"))
    assert pairs == [(0, "x"), (1, "x"), (None, "x")]
