#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Append updates, which build their patch instead of diffing the pane.

A wrong patch here wouldn't raise anything -- the frontend just applies it and
the pane drifts from the data. So rather than assert on the patch contents,
these check against the diff implementation that used to do this: same
resulting pane, and applying the patch to the old pane gives the new one.
"""

import copy
import json

import jsonpatch
import pytest

from visdom.server.handlers.web_handlers import (
    UpdateHandler,
    _planned_extensions,
    pane_fits_in,
)

pytestmark = pytest.mark.unit


MAXES = (100, 10, 10, 10)

# what the client actually sends for a bare vis.line(..., update='append') --
# opts is never empty, the defaults get filled in
CLIENT_OPTS = {
    "markers": False,
    "fillarea": False,
    "mode": "lines",
    "markersymbol": "dot",
    "markersize": 10,
    "markerborderwidth": 0.5,
}


def reference_update_packet(p, args):
    """update_packet() as it was before the append fast path."""
    old_p = p.copy()
    if "content" in p:
        old_p["content"] = copy.deepcopy(p["content"])
    if "old_content" in p:
        old_p["old_content"] = copy.deepcopy(p["old_content"])
    p = UpdateHandler.update(p, args, *MAXES)
    p["contentID"] = "fixed-content-id"
    return p, jsonpatch.make_patch(old_p, p).patch


def plot_pane(points=3, traces=1, trace_type="scatter", marker_color=False):
    data = []
    for index in range(traces):
        trace = {
            "x": [float(i) for i in range(points)],
            "y": [i * 0.1 for i in range(points)],
            "name": str(index + 1),
            "type": trace_type,
            "mode": "lines",
            "marker": {"size": 10, "symbol": "dot"},
        }
        if trace_type == "scatter3d":
            trace["z"] = [i * 0.2 for i in range(points)]
        if marker_color:
            trace["marker"]["color"] = ["#ff0000"] * points
        data.append(trace)
    return {
        "id": "w",
        "type": "plot",
        "contentID": "before",
        "version": 1,
        "title": "loss",
        "content": {"data": data, "layout": {"title": "loss"}, "caption": None},
        "layout": {},
    }


def sample(name="1", trace_type="scatter", count=1, marker_color=False, x=None):
    trace = {
        "x": [99.0] * count if x is None else x,
        "y": [0.5] * count,
        "name": name,
        "type": trace_type,
        "mode": "lines",
        "marker": {"size": 10, "symbol": "dot"},
    }
    if trace_type == "scatter3d":
        trace["z"] = [0.7] * count
    if marker_color:
        trace["marker"]["color"] = ["#0000ff"] * count
    return trace


def append_args(data, **extra):
    args = {
        "win": "w",
        "append": True,
        "name": None,
        "layout": {},
        "opts": dict(CLIENT_OPTS),
        "data": data,
    }
    args.update(extra)
    return args


# handled by the fast path
FAST_CASES = {
    "plain append": (plot_pane(), append_args([sample()])),
    "several samples at once": (plot_pane(), append_args([sample(count=4)])),
    "an opt changes too": (
        plot_pane(),
        append_args([sample()], opts=dict(CLIENT_OPTS, title="new title")),
    ),
    "a caption changes too": (
        plot_pane(),
        append_args([sample()], opts=dict(CLIENT_OPTS, caption="cap")),
    ),
    "the layout changes too": (
        plot_pane(),
        append_args([sample()], layout={"showlegend": True}),
    ),
    "two traces": (
        plot_pane(traces=2),
        append_args([sample("1"), sample("2")]),
    ),
    "one named trace": (
        plot_pane(traces=2),
        append_args([sample("2")], name="2"),
    ),
    "a 3d trace": (
        plot_pane(trace_type="scatter3d"),
        append_args([sample(trace_type="scatter3d")]),
    ),
    "per-point marker colours": (
        plot_pane(marker_color=True),
        append_args([sample(marker_color=True)]),
    ),
    "a masked (all-NaN) sample": (
        plot_pane(),
        append_args([sample(x=[float("nan")])]),
    ),
    "fewer entries than the pane has traces": (
        plot_pane(traces=3),
        append_args([sample("1")]),
    ),
}

# not plain appends -- these have to reach the differ untouched
FALLBACK_CASES = {
    "a replace rather than an append": (
        plot_pane(),
        append_args([sample()], append=False),
    ),
    "a trace deletion": (
        plot_pane(traces=2),
        append_args([sample("2")], delete=True, name="2"),
    ),
    "a named trace that does not exist yet": (
        plot_pane(),
        append_args([sample("new")], name="new"),
    ),
    "a legend rename": (
        plot_pane(traces=2),
        append_args(
            [sample("1"), sample("2")],
            opts=dict(CLIENT_OPTS, legend=["a", "b"]),
        ),
    ),
    "a heatmap": (
        {
            "id": "w",
            "type": "plot",
            "contentID": "before",
            "version": 1,
            "content": {
                "data": [
                    {"type": "heatmap", "z": [[1, 2], [3, 4]], "x": None, "y": None}
                ],
                "layout": {},
            },
            "layout": {},
        },
        append_args(
            [{"type": "heatmap", "z": [[5, 6]], "x": None, "y": None}],
            updateDir="appendRow",
        ),
    ),
    "a text pane": (
        {
            "id": "w",
            "type": "text",
            "contentID": "before",
            "version": 1,
            "content": "hello",
            "layout": {},
        },
        append_args([{"content": "world", "type": "text"}]),
    ),
}

ALL_CASES = dict(FAST_CASES, **FALLBACK_CASES)


def normalized(pane):
    """Pin the random content id so two runs compare equal."""
    pane = dict(pane)
    pane["contentID"] = "fixed-content-id"
    return json.loads(json.dumps(pane, default=str))


@pytest.mark.parametrize("label", sorted(FAST_CASES))
def test_fast_path_is_taken_for_appends(label):
    pane, args = FAST_CASES[label]
    assert _planned_extensions(copy.deepcopy(pane), copy.deepcopy(args)) is not None


@pytest.mark.parametrize("label", sorted(FALLBACK_CASES))
def test_other_updates_fall_back_to_the_differ(label):
    pane, args = FALLBACK_CASES[label]
    assert _planned_extensions(copy.deepcopy(pane), copy.deepcopy(args)) is None


@pytest.mark.parametrize("label", sorted(ALL_CASES))
def test_pane_matches_the_implementation_it_replaced(label):
    pane, args = ALL_CASES[label]
    fast, _ = UpdateHandler.update_packet(
        copy.deepcopy(pane), copy.deepcopy(args), *MAXES
    )
    slow, _ = reference_update_packet(copy.deepcopy(pane), copy.deepcopy(args))
    assert normalized(fast) == normalized(slow)


@pytest.mark.parametrize("label", sorted(ALL_CASES))
def test_patch_rebuilds_the_updated_pane(label):
    """Subscribers get the patch instead of the pane, so it has to carry the
    same update."""
    pane, args = ALL_CASES[label]
    updated, ops = UpdateHandler.update_packet(
        copy.deepcopy(pane), copy.deepcopy(args), *MAXES
    )
    rebuilt = jsonpatch.JsonPatch(ops).apply(copy.deepcopy(pane))
    assert normalized(rebuilt) == normalized(updated)


def test_appending_does_not_diff_the_samples(monkeypatch):
    """Regression guard for the quadratic.

    Timing this would be flaky, so check the cause instead: whatever reaches
    make_patch has to be the same size at 10 points and at 10k, which only
    holds if the sample arrays never get there.
    """
    seen = []
    real_make_patch = jsonpatch.make_patch

    def recording_make_patch(src, dst):
        seen.append(len(json.dumps(src, default=str)))
        return real_make_patch(src, dst)

    monkeypatch.setattr(jsonpatch, "make_patch", recording_make_patch)

    sizes = []
    for points in (10, 10000):
        seen.clear()
        UpdateHandler.update_packet(
            plot_pane(points=points), append_args([sample()]), *MAXES
        )
        sizes.append(sum(seen))

    assert sizes[0] == sizes[1]


def test_patch_size_does_not_grow_with_the_plot():
    counts = []
    for points in (10, 10000):
        _, ops = UpdateHandler.update_packet(
            plot_pane(points=points), append_args([sample()]), *MAXES
        )
        counts.append(len(ops))
    assert counts[0] == counts[1]


def test_appended_samples_land_at_the_end():
    pane = plot_pane(points=3)
    updated, _ = UpdateHandler.update_packet(
        pane, append_args([sample(count=2)]), *MAXES
    )
    trace = updated["content"]["data"][0]
    assert trace["x"] == [0.0, 1.0, 2.0, 99.0, 99.0]
    assert trace["y"] == [0.0, 0.1, 0.2, 0.5, 0.5]


def test_pane_fits_in_answers_the_size_question():
    small = {"a": 1}
    assert pane_fits_in(small, 10_000) is True
    assert pane_fits_in({"a": "x" * 100}, 10) is False


def test_pane_fits_in_stops_once_the_limit_is_passed():
    """A pane far past the limit shouldn't be serialized in full to find out."""
    big = {"data": ["x" * 1000 for _ in range(1000)]}
    encoded = len(json.dumps(big, separators=(",", ":")))
    assert encoded > 1_000_000
    assert pane_fits_in(big, 50) is False
