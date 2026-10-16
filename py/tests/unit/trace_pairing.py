#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""``pair_traces``: which existing trace each entry of an unnamed update hits."""

import pytest

from visdom.server.handlers.web_handlers import pair_traces

pytestmark = pytest.mark.unit


def traces(*names):
    return [{"name": n} for n in names]


def paired(pdata, new_data):
    return [(i, e["name"]) for i, e in pair_traces(pdata, new_data)]


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


def test_default_names_on_numbered_traces_are_new_labels():
    """Traces named only by numbers were never renamed, so the positional
    fallback for a legend-renamed line doesn't apply."""
    assert paired(traces("2", "3"), traces("1")) == [(None, "1")]


def test_a_batch_of_only_new_classes_becomes_new_traces():
    assert paired(traces("cat", "dog"), traces("bird")) == [(None, "bird")]


def test_non_default_names_with_no_match_become_new_traces():
    """Only "1", "2", ... in order is the client's default naming."""
    assert paired(traces("a", "b"), traces("2")) == [(None, "2")]


def test_entries_without_names_stay_positional():
    pairs = pair_traces(traces("cat", "dog"), [{"x": [1]}, {"x": [2]}])
    assert [i for i, _ in pairs] == [0, 1]


def test_positional_pairing_stops_at_the_shorter_side():
    assert paired(traces("a", "b", "c"), traces("1")) == [(0, "1")]


def test_repeated_names_take_the_traces_in_order():
    pairs = paired(traces("x", "x"), traces("x", "x", "x"))
    assert pairs == [(0, "x"), (1, "x"), (None, "x")]
