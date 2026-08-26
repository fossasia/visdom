#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the client's vector, stem, pie, mesh and dual-axis payloads.

These five methods turn a user's arrays into the Plotly traces the browser
draws, and none of them had a direct test. ``quiver`` and ``stem`` are the
awkward pair: neither emits a trace of its own, they reshape their input into a
single flat scatter whose segments are separated by ``NaN`` sentinels, so a
regression shows up as a plot with the wrong number of line breaks rather than
as an exception.

Every test runs through the ``capture_send`` fixture, which patches ``_send``
on a ``Visdom(send=False)`` client — no server, no I/O, no sockets.
"""

import math

import numpy as np
import pytest

pytestmark = pytest.mark.unit

requires_assertions = pytest.mark.skipif(
    not __debug__, reason="assert-based validation is stripped under python -O"
)


def trace(sent, index=0):
    """The n-th trace of a captured payload."""
    return sent["payload"]["data"][index]


def segments(values):
    """Split a flat coordinate list on its NaN separators."""
    out, current = [], []
    for value in values:
        if isinstance(value, float) and math.isnan(value):
            out.append(current)
            current = []
        else:
            current.append(value)
    if current:
        out.append(current)
    return out


# ---------------------------------------------------------------- quiver ----


def test_quiver_is_sent_as_a_line_mode_scatter(capture_send):
    """quiver has no trace type of its own; it delegates to scatter."""
    sent = capture_send(lambda v: v.quiver(X=np.ones((2, 2)), Y=np.ones((2, 2))))
    assert sent["endpoint"] == "events"
    assert trace(sent)["type"] == "scatter"
    assert trace(sent)["mode"] == "lines"


def test_quiver_emits_three_points_per_arrow_without_heads(capture_send):
    """Each arrow is start, tip and a NaN break, so the shaft does not join."""
    sent = capture_send(
        lambda v: v.quiver(
            X=np.ones((2, 3)), Y=np.ones((2, 3)), opts=dict(arrowheads=False)
        )
    )
    assert len(trace(sent)["x"]) == 2 * 3 * 3
    assert all(len(seg) == 2 for seg in segments(trace(sent)["x"]))


def test_quiver_adds_four_more_points_per_arrow_for_the_heads(capture_send):
    """Arrowheads are three more points (left, tip, right) plus a break."""
    sent = capture_send(lambda v: v.quiver(X=np.ones((2, 2)), Y=np.ones((2, 2))))
    assert len(trace(sent)["x"]) == 2 * 2 * 3 + 2 * 2 * 4


def test_quiver_defaults_to_a_regular_grid(capture_send):
    """Without gridX/gridY the arrows start on integer row/column positions."""
    sent = capture_send(
        lambda v: v.quiver(
            X=np.ones((2, 2)), Y=np.ones((2, 2)), opts=dict(arrowheads=False)
        )
    )
    starts = [
        (seg[0], sy[0])
        for seg, sy in zip(*map(segments, (trace(sent)["x"], trace(sent)["y"])))
    ]
    assert starts == [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]


def test_quiver_offsets_the_arrows_onto_a_supplied_grid(capture_send):
    """gridX/gridY move the origin of every arrow; the tip follows it."""
    sent = capture_send(
        lambda v: v.quiver(
            X=np.ones((1, 1)),
            Y=np.ones((1, 1)),
            gridX=np.array([[5.0]]),
            gridY=np.array([[7.0]]),
            opts=dict(arrowheads=False),
        )
    )
    assert trace(sent)["x"][:2] == [5.0, 6.0]
    assert trace(sent)["y"][:2] == [7.0, 8.0]


def test_quiver_normalize_rescales_the_longest_arrow(capture_send):
    """opts.normalize is the length the longest arrow should end up with."""
    sent = capture_send(
        lambda v: v.quiver(
            X=np.array([[3.0, 0.0]]),
            Y=np.array([[4.0, 0.0]]),
            opts=dict(normalize=2.5, arrowheads=False),
        )
    )
    assert trace(sent)["x"][:2] == [0.0, 1.5]
    assert trace(sent)["y"][:2] == [0.0, 2.0]


def test_quiver_normalize_of_zero_is_skipped_silently(capture_send):
    """0 is falsy, so it reads as "no normalization" rather than as an error."""
    sent = capture_send(
        lambda v: v.quiver(
            X=np.ones((1, 1)),
            Y=np.ones((1, 1)),
            opts=dict(normalize=0, arrowheads=False),
        )
    )
    assert trace(sent)["x"][:2] == [0.0, 1.0]


def test_quiver_warns_when_every_magnitude_is_non_finite(capture_send):
    """Normalizing NaN input would scale everything to NaN, so it is skipped."""
    with pytest.warns(RuntimeWarning, match="all magnitudes are non-finite"):
        capture_send(
            lambda v: v.quiver(
                X=np.full((1, 1), np.nan),
                Y=np.full((1, 1), np.nan),
                opts=dict(normalize=2),
            )
        )


def test_quiver_warns_when_the_longest_arrow_has_zero_length(capture_send):
    """A zero maximum would divide by zero, so it is skipped."""
    with pytest.warns(RuntimeWarning, match="max magnitude is zero"):
        capture_send(
            lambda v: v.quiver(
                X=np.zeros((1, 1)), Y=np.zeros((1, 1)), opts=dict(normalize=2)
            )
        )


def test_quiver_writes_its_defaults_onto_the_callers_opts(capture_send):
    """mode and arrowheads are set in place, and travel with the payload."""
    opts = {}
    sent = capture_send(
        lambda v: v.quiver(X=np.ones((1, 1)), Y=np.ones((1, 1)), opts=opts)
    )
    assert opts["mode"] == "lines"
    assert opts["arrowheads"] is True
    assert sent["payload"]["opts"]["arrowheads"] is True


def test_quiver_passes_win_and_env_through(capture_send):
    sent = capture_send(
        lambda v: v.quiver(X=np.ones((1, 1)), Y=np.ones((1, 1)), win="w1", env="e1")
    )
    assert sent["payload"]["win"] == "w1"
    assert sent["payload"]["eid"] == "e1"


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(X=np.ones(2), Y=np.ones((1, 2))), "X should be two-dimensional"),
        (dict(X=np.ones((1, 2)), Y=np.ones(2)), "Y should be two-dimensional"),
        (
            dict(X=np.ones((1, 2)), Y=np.ones((2, 1))),
            "X and Y should have the same size",
        ),
        (
            dict(X=np.ones((1, 2)), Y=np.ones((1, 2)), gridX=np.ones((2, 2))),
            "X and gridX should have the same size",
        ),
        (
            dict(X=np.ones((1, 2)), Y=np.ones((1, 2)), gridY=np.ones((2, 2))),
            "Y and gridY should have the same size",
        ),
        (
            dict(X=np.ones((1, 1)), Y=np.ones((1, 1)), opts=dict(normalize=-1)),
            "opts.normalize should be a finite positive number",
        ),
        (
            dict(X=np.ones((1, 1)), Y=np.ones((1, 1)), opts=dict(normalize=np.inf)),
            "opts.normalize should be a finite positive number",
        ),
    ],
)
def test_quiver_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.quiver(**kwargs)


# ------------------------------------------------------------------ stem ----


def test_stem_draws_each_point_as_a_line_to_the_baseline(capture_send):
    """A stem is baseline, value, NaN break — three points per sample."""
    sent = capture_send(lambda v: v.stem(X=np.array([1.0, 2.0, 3.0])))
    assert len(trace(sent)["x"]) == 9
    assert segments(trace(sent)["y"]) == [[0.0, 1.0], [0.0, 2.0], [0.0, 3.0]]


def test_stem_numbers_the_samples_from_one_when_no_y_is_given(capture_send):
    """The default timestamps are 1..N, not 0..N-1."""
    sent = capture_send(lambda v: v.stem(X=np.array([1.0, 2.0])))
    assert segments(trace(sent)["x"]) == [[1.0, 1.0], [2.0, 2.0]]


def test_stem_uses_supplied_timestamps(capture_send):
    sent = capture_send(
        lambda v: v.stem(X=np.array([1.0, 2.0]), Y=np.array([10.0, 20.0]))
    )
    assert segments(trace(sent)["x"]) == [[10.0, 10.0], [20.0, 20.0]]


def test_stem_splits_columns_into_separate_traces(capture_send):
    """Each column of X is a series, labelled 1..M for scatter to group on."""
    sent = capture_send(lambda v: v.stem(X=np.array([[1.0, 2.0], [3.0, 4.0]])))
    assert len(sent["payload"]["data"]) == 2
    assert [t["name"] for t in sent["payload"]["data"]] == ["1", "2"]


def test_stem_tiles_a_single_timestamp_column_across_every_series(capture_send):
    """One Y column means all M series share those timestamps."""
    sent = capture_send(
        lambda v: v.stem(
            X=np.array([[1.0, 2.0], [3.0, 4.0]]), Y=np.array([[7.0], [8.0]])
        )
    )
    for column in sent["payload"]["data"]:
        assert segments(column["x"]) == [[7.0, 7.0], [8.0, 8.0]]


def test_stem_is_sent_as_a_line_mode_scatter(capture_send):
    sent = capture_send(lambda v: v.stem(X=np.array([1.0, 2.0])))
    assert sent["endpoint"] == "events"
    assert trace(sent)["type"] == "scatter"
    assert sent["payload"]["opts"]["mode"] == "lines"


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(X=np.ones((2, 2, 2))), "X should be one or two-dimensional"),
        (
            dict(X=np.ones((3, 1)), Y=np.ones((2, 1))),
            "number of rows in X and Y must match",
        ),
        (
            dict(X=np.ones((2, 3)), Y=np.ones((2, 2))),
            "Y should be a single column or the same number of columns as X",
        ),
    ],
)
def test_stem_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.stem(**kwargs)


# ------------------------------------------------------------------- pie ----


def test_pie_sends_values_and_legend_labels(capture_send):
    sent = capture_send(
        lambda v: v.pie(X=np.array([1, 2, 3]), opts=dict(legend=["a", "b", "c"]))
    )
    assert trace(sent)["type"] == "pie"
    assert trace(sent)["values"] == [1, 2, 3]
    assert trace(sent)["labels"] == ["a", "b", "c"]


def test_pie_leaves_labels_unset_without_a_legend(capture_send):
    """Plotly falls back to numbering the slices itself."""
    sent = capture_send(lambda v: v.pie(X=np.array([1, 2])))
    assert trace(sent)["labels"] is None


def test_pie_squeezes_a_column_vector(capture_send):
    sent = capture_send(lambda v: v.pie(X=np.array([[1], [2], [3]])))
    assert trace(sent)["values"] == [1, 2, 3]


def test_pie_carries_the_layout_built_from_opts(capture_send):
    sent = capture_send(lambda v: v.pie(X=np.array([1, 2]), opts=dict(title="share")))
    assert sent["payload"]["layout"]["title"] == {"text": "share"}


@requires_assertions
@pytest.mark.parametrize(
    "X, message",
    [
        (np.ones((2, 2)), "X should be one-dimensional"),
        (np.array([1, -2]), "X cannot contain negative values"),
    ],
)
def test_pie_rejects_malformed_input(offline_client, X, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.pie(X=X)


# ------------------------------------------------------------------ mesh ----


def test_mesh_two_column_vertices_stay_two_dimensional(capture_send):
    """Without a z column the trace is a flat mesh and z/i/j/k are empty."""
    sent = capture_send(lambda v: v.mesh(X=np.array([[0, 0], [1, 0], [1, 1]])))
    assert trace(sent)["type"] == "mesh"
    assert trace(sent)["x"] == [0, 1, 1]
    assert trace(sent)["y"] == [0, 0, 1]
    assert trace(sent)["z"] is None
    assert trace(sent)["i"] is None


def test_mesh_three_column_vertices_become_mesh3d(capture_send):
    sent = capture_send(lambda v: v.mesh(X=np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0]])))
    assert trace(sent)["type"] == "mesh3d"
    assert trace(sent)["z"] == [0, 0, 0]


def test_mesh_polygons_populate_the_vertex_indices(capture_send):
    sent = capture_send(
        lambda v: v.mesh(
            X=np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0]]), Y=np.array([[0, 1, 2]])
        )
    )
    assert (trace(sent)["i"], trace(sent)["j"], trace(sent)["k"]) == ([0], [1], [2])


def test_mesh_two_dimensional_polygons_have_no_third_index(capture_send):
    """k only exists on a 3D mesh, even when polygons are given."""
    sent = capture_send(
        lambda v: v.mesh(X=np.array([[0, 0], [1, 0], [1, 1]]), Y=np.array([[0, 1]]))
    )
    assert trace(sent)["i"] == [0]
    assert trace(sent)["j"] == [1]
    assert trace(sent)["k"] is None


def test_mesh_reads_color_and_opacity_from_opts(capture_send):
    sent = capture_send(
        lambda v: v.mesh(
            X=np.array([[0, 0], [1, 0]]), opts=dict(color="red", opacity=0.25)
        )
    )
    assert trace(sent)["color"] == "red"
    assert trace(sent)["opacity"] == 0.25


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(X=np.ones(3)), "X must have 2 dimensions"),
        (dict(X=np.ones((3, 4))), "X must have 2 or 3 columns"),
        (dict(X=np.ones((3, 2)), Y=np.ones(3)), "Y must have 2 dimensions"),
        (
            dict(X=np.ones((3, 2)), Y=np.ones((1, 3))),
            "X and Y must have same number of columns",
        ),
    ],
)
def test_mesh_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.mesh(**kwargs)


# -------------------------------------------------------- dual_axis_lines ----


def test_dual_axis_lines_sends_two_traces_on_separate_axes(capture_send):
    sent = capture_send(
        lambda v: v.dual_axis_lines(
            X=np.arange(3), Y1=np.arange(3), Y2=np.arange(3) * 2
        )
    )
    first, second = sent["payload"]["data"]
    assert (first["type"], second["type"]) == ("scatter", "scatter")
    assert "yaxis" not in first
    assert second["yaxis"] == "y2"
    assert second["y"] == [0.0, 2.0, 4.0]


def test_dual_axis_lines_coerces_the_input_to_floats(capture_send):
    """Integer arrays would otherwise reach json as numpy scalars."""
    sent = capture_send(
        lambda v: v.dual_axis_lines(X=np.arange(2), Y1=np.arange(2), Y2=np.arange(2))
    )
    assert all(isinstance(x, float) for x in trace(sent)["x"])


def test_dual_axis_lines_has_a_full_set_of_defaults(capture_send):
    """Every layout field falls back to a value rather than being dropped."""
    sent = capture_send(
        lambda v: v.dual_axis_lines(X=np.arange(2), Y1=np.arange(2), Y2=np.arange(2))
    )
    layout = sent["payload"]["layout"]
    assert layout["title"] == {"text": "Example Double Y axis"}
    assert layout["yaxis"]["title"]["text"] == "Y1 axis"
    assert layout["yaxis2"]["title"]["text"] == "Y2 axis"
    assert layout["yaxis2"]["overlaying"] == "y"
    assert layout["yaxis2"]["side"] == "right"
    assert layout["showlegend"] is True
    assert layout["margin"] == {"b": 60, "r": 60, "t": 60, "l": 60}


def test_dual_axis_lines_takes_names_colors_and_side_from_opts(capture_send):
    sent = capture_send(
        lambda v: v.dual_axis_lines(
            X=np.arange(2),
            Y1=np.arange(2),
            Y2=np.arange(2),
            opts=dict(
                title="two scales",
                name_y1="loss",
                name_y2="accuracy",
                color_title_y1="blue",
                color_tick_y1="navy",
                color_title_y2="green",
                color_tick_y2="olive",
                side="left",
                showlegend=False,
            ),
        )
    )
    layout = sent["payload"]["layout"]
    assert layout["title"] == {"text": "two scales"}
    assert layout["yaxis"]["title"]["text"] == "loss"
    assert layout["yaxis"]["title"]["font"]["color"] == "blue"
    assert layout["yaxis"]["tickfont"]["color"] == "navy"
    assert layout["yaxis2"]["title"]["font"]["color"] == "green"
    assert layout["yaxis2"]["tickfont"]["color"] == "olive"
    assert layout["yaxis2"]["side"] == "left"
    assert layout["showlegend"] is False


def test_dual_axis_lines_takes_the_margins_from_opts(capture_send):
    sent = capture_send(
        lambda v: v.dual_axis_lines(
            X=np.arange(2),
            Y1=np.arange(2),
            Y2=np.arange(2),
            opts=dict(top=1, bottom=2, left=3, right=4),
        )
    )
    assert sent["payload"]["layout"]["margin"] == {"t": 1, "b": 2, "l": 3, "r": 4}


def test_dual_axis_lines_fills_in_a_pane_size(capture_send):
    """Opts that omit height/width still get one, so the pane is not collapsed."""
    sent = capture_send(
        lambda v: v.dual_axis_lines(
            X=np.arange(2), Y1=np.arange(2), Y2=np.arange(2), opts=dict(title="t")
        )
    )
    assert sent["payload"]["opts"]["height"] == 300
    assert sent["payload"]["opts"]["width"] == 500


def test_dual_axis_lines_resolves_the_environment_itself(capture_send, offline_client):
    """The odd one out: every other method leaves eid None for the server."""
    sent = capture_send(
        lambda v: v.dual_axis_lines(X=np.arange(2), Y1=np.arange(2), Y2=np.arange(2))
    )
    assert sent["payload"]["eid"] == offline_client.env


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(Y1=np.arange(2), Y2=np.arange(2)), "X Cannot be None"),
        (dict(X=np.arange(2), Y2=np.arange(2)), "Y1 Cannot be None"),
        (dict(X=np.arange(2), Y1=np.arange(2)), "Y2 Cannot be None"),
        (
            dict(X=np.arange(3), Y1=np.arange(2), Y2=np.arange(3)),
            "values of X and Y1 are not in proper shape",
        ),
        (
            dict(X=np.arange(3), Y1=np.arange(3), Y2=np.arange(2)),
            "values of X and Y2 are not in proper shape",
        ),
    ],
)
def test_dual_axis_lines_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.dual_axis_lines(**kwargs)
