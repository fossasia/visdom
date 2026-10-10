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


def test_no_match_at_all_stays_positional():
    """A line renamed by its legend still appends with the default names."""
    pairs = paired(traces("train", "val"), traces("1", "2"))
    assert pairs == [(0, "1"), (1, "2")]


def test_positional_pairing_stops_at_the_shorter_side():
    assert paired(traces("a", "b", "c"), traces("1")) == [(0, "1")]


def test_repeated_names_take_the_traces_in_order():
    pairs = paired(traces("x", "x"), traces("x", "x", "x"))
    assert pairs == [(0, "x"), (1, "x"), (None, "x")]
