#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the client's plot payload builders.

Each plot method is a pure transform from arrays to the message the browser
receives, so these run on the ``capture_send`` fixture, which intercepts the
payload, and on ``offline_client`` where only the input validation is under
test. Neither opens a socket or reaches a server.
"""
import math
import unittest
from unittest.mock import patch
import numpy as np
import pytest
import visdom

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------- line ----


def test_line_y_1d_no_x(capture_send):
    """Basic 1D Y without X auto-generates x-axis."""
    sent = capture_send(lambda v: v.line(np.array([1.0, 2.0, 3.0])))
    assert "data" in sent["payload"]


def test_line_y_0d_raises(offline_client):
    """Scalar Y raises before reaching scatter."""
    with pytest.raises(AssertionError):
        offline_client.line(np.float64(1.0))


def test_line_y_3d_raises(offline_client):
    """3D Y raises on the ndim check."""
    with pytest.raises(AssertionError):
        offline_client.line(np.ones((2, 3, 4)))


def test_line_y_empty_last_dim_raises(offline_client):
    """Zero-column Y raises on the empty check."""
    with pytest.raises(AssertionError):
        offline_client.line(np.empty((5, 0)))


def test_line_x_3d_raises(offline_client):
    """3D X raises on the ndim check."""
    with pytest.raises(AssertionError):
        offline_client.line(np.array([1.0, 2.0]), X=np.ones((2, 1, 1)))


def test_line_x_shape_mismatch_raises(offline_client):
    """X and Y with different lengths raise on the shape check."""
    with pytest.raises(AssertionError):
        offline_client.line(np.array([1.0, 2.0, 3.0]), X=np.array([0.0, 1.0]))


def test_line_single_line_one_trace(capture_send):
    """1D Y produces exactly one trace."""
    sent = capture_send(lambda v: v.line(np.array([1.0, 2.0, 3.0])))
    assert len(sent["payload"]["data"]) == 1


def test_line_multi_line_2d_y(capture_send):
    """2D Y with M columns produces M traces."""
    Y = np.array([[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])
    sent = capture_send(lambda v: v.line(Y))
    assert len(sent["payload"]["data"]) == 2


def test_line_y_2d_single_col_one_trace(capture_send):
    """(N,1) Y is squeezed to 1D before building linedata."""
    sent = capture_send(lambda v: v.line(np.array([[1.0], [2.0], [3.0]])))
    assert len(sent["payload"]["data"]) == 1


def test_line_y_2d_x_1d_broadcasts(capture_send):
    """1D X is tiled to match the shape of 2D Y."""
    Y = np.array([[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])
    X = np.array([0.0, 1.0, 2.0])
    sent = capture_send(lambda v: v.line(Y, X=X))
    assert "data" in sent["payload"]


def test_line_update_append_requires_x(offline_client):
    """update='append' without X raises before sending."""
    with pytest.raises(AssertionError):
        offline_client.line(np.array([1.0, 2.0]), win="w", update="append")


def test_line_update_append_sets_append_true(capture_send):
    """Existing window with update='append' sets append=True in payload."""
    Y = np.array([1.0, 2.0])
    X = np.array([0.0, 1.0])
    sent = capture_send(
        lambda v: v.line(Y, X=X, win="w", update="append"), win_exists=True
    )
    assert sent["payload"]["append"]


def test_line_update_replace_sets_append_false(capture_send):
    """update='replace' sets append=False in payload."""
    Y = np.array([1.0, 2.0])
    X = np.array([0.0, 1.0])
    sent = capture_send(lambda v: v.line(Y, X=X, win="w", update="replace"))
    assert not sent["payload"]["append"]


def test_line_update_replace_uses_update_endpoint(capture_send):
    """update='replace' routes to the update endpoint."""
    Y = np.array([1.0, 2.0])
    X = np.array([0.0, 1.0])
    sent = capture_send(lambda v: v.line(Y, X=X, win="w", update="replace"))
    assert sent["endpoint"] == "update"


def test_line_update_append_new_window_no_append_key(capture_send):
    """New window with update='append' falls back to creation, no append key."""
    Y = np.array([1.0, 2.0])
    X = np.array([0.0, 1.0])
    sent = capture_send(
        lambda v: v.line(Y, X=X, win="w", update="append"), win_exists=False
    )
    assert "append" not in sent["payload"]


def test_line_update_remove_sends_delete(capture_send):
    """update='remove' sends delete=True without touching Y."""
    sent = capture_send(lambda v: v.line(None, win="w", name="trace1", update="remove"))
    assert sent["payload"]["delete"]


def test_line_nan_y_passes_through(capture_send):
    """All-NaN Y values survive into the payload for use as update mask."""
    Y = np.array([np.nan, np.nan, np.nan])
    X = np.array([0.0, 1.0, 2.0])
    sent = capture_send(
        lambda v: v.line(Y, X=X, win="w", update="append"), win_exists=True
    )
    assert all(np.isnan(value) for value in sent["payload"]["data"][0]["y"])


def test_line_inf_y_passes_through(capture_send):
    """Inf Y values pass through without raising."""
    Y = np.array([np.inf, 1.0, -np.inf])
    X = np.array([0.0, 1.0, 2.0])
    sent = capture_send(lambda v: v.line(Y, X=X))
    y_vals = sent["payload"]["data"][0]["y"]
    assert np.isinf(y_vals[0])
    assert np.isinf(y_vals[2])


# ------------------------------------------------------------------- scatter ----


def test_scatter_nx2_input(capture_send):
    """Nx2 X produces a scatter trace."""
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    sent = capture_send(lambda v: v.scatter(X))
    assert sent["payload"]["data"][0]["type"] == "scatter"


def test_scatter_nx3_input_produces_scatter3d(capture_send):
    """Nx3 X produces a scatter3d trace."""
    X = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    sent = capture_send(lambda v: v.scatter(X))
    assert sent["payload"]["data"][0]["type"] == "scatter3d"


def test_scatter_x_1d_raises(offline_client):
    """1D X raises on the ndim check."""
    with pytest.raises(AssertionError):
        offline_client.scatter(np.array([1.0, 2.0, 3.0]))


def test_scatter_x_wrong_cols_raises(offline_client):
    """X with column count other than 2 or 3 raises."""
    with pytest.raises(AssertionError):
        offline_client.scatter(np.ones((3, 4)))


def test_scatter_y_size_mismatch_raises(offline_client):
    """Y length not matching X row count raises."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(AssertionError):
        offline_client.scatter(X, Y=np.array([1, 2, 3]))


@pytest.mark.parametrize("bad", [np.nan, np.inf], ids=["nan", "inf"])
def test_scatter_non_finite_label_raises(offline_client, bad):
    """A non-finite Y label raises via the isfinite check in _normalize_labels."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(AssertionError):
        offline_client.scatter(X, Y=np.array([1.0, bad]))


def test_scatter_multiple_labels_produce_multiple_traces(capture_send):
    """Distinct Y label values produce one trace each."""
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    sent = capture_send(lambda v: v.scatter(X, Y=np.array([1, 1, 2])))
    assert len(sent["payload"]["data"]) == 2


def test_scatter_name_with_multiple_labels_raises(offline_client):
    """name= combined with multiple label groups raises."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(AssertionError):
        offline_client.scatter(X, Y=np.array([1, 2]), name="trace1")


def test_scatter_store_history_with_update_raises(offline_client):
    """store_history=True combined with update raises ValueError."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(ValueError):
        offline_client.scatter(
            X, opts={"store_history": True}, update="append", win="w"
        )


def test_scatter_update_without_win_raises(offline_client):
    """update without a win raises ValueError."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(ValueError):
        offline_client.scatter(X, update="replace")


def test_scatter_update_remove_requires_name(offline_client):
    """update='remove' without name raises."""
    with pytest.raises(AssertionError):
        offline_client.scatter(None, win="w", update="remove")


def test_scatter_update_remove_sends_delete(capture_send):
    """update='remove' sends delete=True in payload."""
    sent = capture_send(
        lambda v: v.scatter(None, win="w", name="trace1", update="remove")
    )
    assert sent["payload"]["delete"]


def test_scatter_update_append_sets_append_true(capture_send):
    """Existing window with update='append' sets append=True."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(
        lambda v: v.scatter(X, win="w", update="append"), win_exists=True
    )
    assert sent["payload"]["append"]


def test_scatter_update_replace_sets_append_false(capture_send):
    """update='replace' sets append=False in payload."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(lambda v: v.scatter(X, win="w", update="replace"))
    assert not sent["payload"]["append"]


def test_scatter_name_based_update_1d_x_1d_y(capture_send):
    """Name-based update stacks 1D X and Y into Nx2 before sending."""
    X = np.array([1.0, 2.0, 3.0])
    Y = np.array([4.0, 5.0, 6.0])
    sent = capture_send(
        lambda v: v.scatter(X, Y=Y, win="w", update="append", name="t1"),
        win_exists=True,
    )
    data = sent["payload"]["data"][0]
    assert data["x"] == [1.0, 2.0, 3.0]
    assert data["y"] == [4.0, 5.0, 6.0]


# ------------------------------------------------------------------- heatmap ----


def test_heatmap_nx_m_input(capture_send):
    """NxM X produces a heatmap trace."""
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    sent = capture_send(lambda v: v.heatmap(X))
    assert sent["payload"]["data"][0]["type"] == "heatmap"


def test_heatmap_x_not_2d_raises(offline_client):
    """1D X raises on the 2D check."""
    with pytest.raises(AssertionError):
        offline_client.heatmap(np.array([1.0, 2.0, 3.0]))


def test_heatmap_invalid_update_raises(offline_client):
    """Unknown update value raises before building data."""
    with pytest.raises(AssertionError):
        offline_client.heatmap(np.ones((3, 3)), update="badvalue")


def test_heatmap_colormap_defaults_to_viridis(capture_send):
    """colormap defaults to Viridis when not specified."""
    sent = capture_send(lambda v: v.heatmap(np.ones((2, 2))))
    assert sent["payload"]["opts"]["colormap"] == "Viridis"


def test_heatmap_append_row_sets_update_dir(capture_send):
    """appendRow sets updateDir and append=True on the update endpoint."""
    sent = capture_send(
        lambda v: v.heatmap(np.ones((2, 2)), update="appendRow", win="w")
    )
    assert sent["payload"]["updateDir"] == "appendRow"
    assert sent["payload"]["append"]
    assert sent["endpoint"] == "update"


def test_heatmap_append_column_sets_update_dir(capture_send):
    """appendColumn sets updateDir and append=True."""
    sent = capture_send(
        lambda v: v.heatmap(np.ones((2, 2)), update="appendColumn", win="w")
    )
    assert sent["payload"]["updateDir"] == "appendColumn"
    assert sent["payload"]["append"]


def test_heatmap_replace_sets_append_false(capture_send):
    """replace sets append=False on the update endpoint."""
    sent = capture_send(lambda v: v.heatmap(np.ones((2, 2)), update="replace", win="w"))
    assert not sent["payload"]["append"]


def test_heatmap_nan_values_pass_through(capture_send):
    """NaN values in X pass through to the payload without raising."""
    X = np.array([[1.0, np.nan], [np.nan, 4.0]])
    sent = capture_send(lambda v: v.heatmap(X))
    z = sent["payload"]["data"][0]["z"]
    assert np.isnan(z[0][1])
    assert np.isnan(z[1][0])


# ----------------------------------------------------------------------- bar ----


def test_bar_1d_x_one_trace(capture_send):
    """1D X produces a single bar trace."""
    sent = capture_send(lambda v: v.bar(np.array([1.0, 2.0, 3.0])))
    assert len(sent["payload"]["data"]) == 1
    assert sent["payload"]["data"][0]["type"] == "bar"


def test_bar_2d_x_one_trace_per_column(capture_send):
    """NxM X produces M bar traces."""
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    sent = capture_send(lambda v: v.bar(X))
    assert len(sent["payload"]["data"]) == 2


def test_bar_3d_x_raises(offline_client):
    """3D X raises on the ndim check."""
    with pytest.raises(AssertionError):
        offline_client.bar(np.ones((2, 3, 4)))


def test_bar_x_y_length_mismatch_raises(offline_client):
    """Y with a different length than X raises."""
    with pytest.raises(AssertionError):
        offline_client.bar(np.array([1.0, 2.0, 3.0]), Y=np.array([1.0, 2.0]))


def test_bar_default_x_axis_is_one_based(capture_send):
    """Without Y the x-axis is 1..N."""
    sent = capture_send(lambda v: v.bar(np.array([1.0, 2.0, 3.0])))
    assert sent["payload"]["data"][0]["x"] == [1, 2, 3]


def test_bar_y_sets_x_axis_values(capture_send):
    """Y supplies the x-axis values."""
    sent = capture_send(lambda v: v.bar(np.array([1.0, 2.0]), Y=np.array([10.0, 20.0])))
    assert sent["payload"]["data"][0]["x"] == [10.0, 20.0]


def test_bar_column_values_go_to_y(capture_send):
    """Each trace carries its own column of X as bar heights."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(lambda v: v.bar(X))
    assert sent["payload"]["data"][0]["y"] == [1.0, 3.0]
    assert sent["payload"]["data"][1]["y"] == [2.0, 4.0]


def test_bar_rownames_replace_x_axis(capture_send):
    """rownames are used as x-axis labels instead of Y."""
    sent = capture_send(
        lambda v: v.bar(np.array([1.0, 2.0, 3.0]), opts={"rownames": ["a", "b", "c"]})
    )
    assert sent["payload"]["data"][0]["x"] == ["a", "b", "c"]


def test_bar_rownames_length_mismatch_raises(offline_client):
    """rownames shorter than the number of rows raises."""
    with pytest.raises(AssertionError):
        offline_client.bar(np.array([1.0, 2.0, 3.0]), opts={"rownames": ["a", "b"]})


def test_bar_legend_sets_trace_names(capture_send):
    """legend labels name each column trace."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(lambda v: v.bar(X, opts={"legend": ["first", "second"]}))
    assert [trace["name"] for trace in sent["payload"]["data"]] == ["first", "second"]


def test_bar_legend_length_mismatch_raises(offline_client):
    """legend length not matching the column count raises."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(AssertionError):
        offline_client.bar(X, opts={"legend": ["only_one"]})


def test_bar_legend_on_1d_x_transposes(capture_send):
    """1D X with a legend is treated as one row of grouped bars."""
    sent = capture_send(
        lambda v: v.bar(np.array([1.0, 2.0, 3.0]), opts={"legend": ["a", "b", "c"]})
    )
    assert len(sent["payload"]["data"]) == 3


def test_bar_legend_with_rownames_on_1d_raises(offline_client):
    """legend and rownames together on 1D X raise."""
    opts = {"legend": ["a", "b", "c"], "rownames": ["x", "y", "z"]}
    with pytest.raises(AssertionError):
        offline_client.bar(np.array([1.0, 2.0, 3.0]), opts=opts)


def test_bar_stacked_sets_barmode(capture_send):
    """stacked=True stacks the columns instead of grouping them."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(lambda v: v.bar(X, opts={"stacked": True}))
    assert sent["payload"]["layout"]["barmode"] == "stack"


# ----------------------------------------------------------------- histogram ----


def test_histogram_2d_x_raises(offline_client):
    """2D X raises on the one-dimensional check."""
    with pytest.raises(AssertionError):
        offline_client.histogram(np.ones((3, 3)))


def test_histogram_default_bin_count_capped_at_30(capture_send):
    """A large sample is drawn with 30 bars by default."""
    sent = capture_send(lambda v: v.histogram(np.arange(100.0)))
    assert len(sent["payload"]["data"][0]["y"]) == 30


def test_histogram_default_bin_count_is_sample_count_when_small(capture_send):
    """A sample smaller than 30 gets one bar per value by default."""
    sent = capture_send(lambda v: v.histogram(np.arange(5.0)))
    assert len(sent["payload"]["data"][0]["y"]) == 5


def test_histogram_numbins_opt_sets_bin_count(capture_send):
    """numbins controls how many bars are produced."""
    sent = capture_send(lambda v: v.histogram(np.arange(100.0), opts={"numbins": 10}))
    assert len(sent["payload"]["data"][0]["y"]) == 10


def test_histogram_counts_sum_to_sample_count(capture_send):
    """Every sample lands in exactly one bin."""
    sent = capture_send(lambda v: v.histogram(np.arange(100.0), opts={"numbins": 10}))
    assert sum(sent["payload"]["data"][0]["y"]) == 100


def test_histogram_bin_edges_span_data_range(capture_send):
    """The x-axis runs from the minimum to the maximum of X."""
    sent = capture_send(lambda v: v.histogram(np.arange(100.0), opts={"numbins": 10}))
    x = sent["payload"]["data"][0]["x"]
    assert x[0] == 0.0
    assert x[-1] == 99.0


# ------------------------------------------------------------------- boxplot ----


def test_boxplot_1d_x_one_box(capture_send):
    """1D X produces a single box trace."""
    sent = capture_send(lambda v: v.boxplot(np.array([1.0, 2.0, 3.0])))
    assert len(sent["payload"]["data"]) == 1
    assert sent["payload"]["data"][0]["type"] == "box"


def test_boxplot_2d_x_one_box_per_column(capture_send):
    """NxM X produces M box traces."""
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    sent = capture_send(lambda v: v.boxplot(X))
    assert len(sent["payload"]["data"]) == 2


def test_boxplot_3d_x_raises(offline_client):
    """3D X raises on the ndim check."""
    with pytest.raises(AssertionError):
        offline_client.boxplot(np.ones((2, 3, 4)))


def test_boxplot_column_values_go_to_y(capture_send):
    """Each box carries the values of its own column."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(lambda v: v.boxplot(X))
    assert sent["payload"]["data"][0]["y"] == [1.0, 3.0]
    assert sent["payload"]["data"][1]["y"] == [2.0, 4.0]


def test_boxplot_default_names_are_column_indexed(capture_send):
    """Without a legend each box is named after its column index."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(lambda v: v.boxplot(X))
    names = [trace["name"] for trace in sent["payload"]["data"]]
    assert names == ["column 0", "column 1"]


def test_boxplot_legend_sets_box_names(capture_send):
    """legend labels replace the default column names."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(lambda v: v.boxplot(X, opts={"legend": ["train", "test"]}))
    names = [trace["name"] for trace in sent["payload"]["data"]]
    assert names == ["train", "test"]


def test_boxplot_legend_length_mismatch_raises(offline_client):
    """legend length not matching the column count raises."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(AssertionError):
        offline_client.boxplot(X, opts={"legend": ["only_one"]})


# ---------------------------------------------------------------------- surf ----


def test_surf_1d_x_raises(offline_client):
    """1D X raises on the two-dimensional check."""
    with pytest.raises(AssertionError):
        offline_client.surf(np.array([1.0, 2.0, 3.0]))


def test_surf_type_is_surface(capture_send):
    """surf produces a surface trace."""
    sent = capture_send(lambda v: v.surf(np.ones((3, 3))))
    assert sent["payload"]["data"][0]["type"] == "surface"


def test_surf_z_matches_input(capture_send):
    """X is sent verbatim as the z values."""
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    sent = capture_send(lambda v: v.surf(X))
    assert sent["payload"]["data"][0]["z"] == [[1.0, 2.0], [3.0, 4.0]]


def test_surf_colormap_defaults_to_viridis(capture_send):
    """colormap defaults to Viridis when not specified."""
    sent = capture_send(lambda v: v.surf(np.ones((2, 2))))
    assert sent["payload"]["data"][0]["colorscale"] == "Viridis"


def test_surf_colormap_opt_forwarded(capture_send):
    """An explicit colormap reaches the trace."""
    sent = capture_send(lambda v: v.surf(np.ones((2, 2)), opts={"colormap": "Hot"}))
    assert sent["payload"]["data"][0]["colorscale"] == "Hot"


def test_surf_range_defaults_to_data_range(capture_send):
    """xmin and xmax default to the minimum and maximum of X."""
    X = np.array([[1.0, 5.0], [3.0, 9.0]])
    sent = capture_send(lambda v: v.surf(X))
    assert sent["payload"]["data"][0]["cmin"] == 1.0
    assert sent["payload"]["data"][0]["cmax"] == 9.0


def test_surf_range_opts_override_data_range(capture_send):
    """xmin and xmax opts clip the color range."""
    X = np.array([[1.0, 5.0], [3.0, 9.0]])
    sent = capture_send(lambda v: v.surf(X, opts={"xmin": 2.0, "xmax": 4.0}))
    assert sent["payload"]["data"][0]["cmin"] == 2.0
    assert sent["payload"]["data"][0]["cmax"] == 4.0


def test_surf_nan_ignored_in_range(capture_send):
    """NaN values do not leak into the default color range."""
    X = np.array([[1.0, np.nan], [3.0, 9.0]])
    sent = capture_send(lambda v: v.surf(X))
    assert sent["payload"]["data"][0]["cmin"] == 1.0
    assert sent["payload"]["data"][0]["cmax"] == 9.0


def test_surf_layout_is_3d(capture_send):
    """surf builds a 3D scene layout."""
    sent = capture_send(lambda v: v.surf(np.ones((2, 2))))
    assert "scene" in sent["payload"]["layout"]


# ------------------------------------------------------------------- contour ----


def test_contour_type_is_contour(capture_send):
    """contour produces a contour trace."""
    sent = capture_send(lambda v: v.contour(np.ones((3, 3))))
    assert sent["payload"]["data"][0]["type"] == "contour"


def test_contour_layout_is_flat(capture_send):
    """contour renders flat, without the 3D scene surf builds."""
    sent = capture_send(lambda v: v.contour(np.ones((2, 2))))
    assert "scene" not in sent["payload"]["layout"]


# --------------------------------------------------------- matplot resizable ----


class _FakePlot:
    """Minimal stand-in for a matplotlib figure.

    ``matplot()`` only ever calls ``savefig(buffer, format="svg")`` on the plot
    object, so we just emit an SVG string carrying the given point dimensions
    and ignore everything else. This lets us test the pt-stripping math without
    importing matplotlib or opening a socket.
    """

    def __init__(self, width_pt, height_pt):
        self._svg = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<svg width="{width_pt}pt" height="{height_pt}pt" '
            'xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink">'
            "<g></g></svg>"
        )

    def savefig(self, buffer, format=None):
        buffer.write(self._svg)


@pytest.mark.skipif(not visdom.BS4_AVAILABLE, reason="requires bs4/lxml")
class TestMatplotResizable(unittest.TestCase):
    def setUp(self):
        self.viz = visdom.Visdom(use_incoming_socket=False)

    def _matplot(self, plot, **extra_opts):
        """Run matplot(resizable=True) and capture the opts handed to svg()."""
        captured = {}

        def fake_svg(svgstr=None, opts=None, env=None, win=None):
            captured["opts"] = opts
            return "win"

        with patch.object(self.viz, "svg", side_effect=fake_svg):
            self.viz.matplot(plot, opts=dict(resizable=True, **extra_opts))
        return captured["opts"]

    def test_whole_number_pt_not_inflated(self):
        # 432pt must strip to "432", not "43200". ceil(432) * 1.4 == 604.8
        opts = self._matplot(_FakePlot(width_pt="432", height_pt="432"))
        self.assertEqual(opts["height"], 1.4 * math.ceil(432))  # 604.8
        self.assertEqual(opts["width"], 1.35 * math.ceil(432))  # 583.2

    def test_decimal_pt_still_correct(self):
        # decimal points still round up via ceil after stripping "pt"
        opts = self._matplot(_FakePlot(width_pt="100.5", height_pt="200.5"))
        self.assertEqual(opts["height"], 1.4 * math.ceil(200.5))  # 1.4 * 201
        self.assertEqual(opts["width"], 1.35 * math.ceil(100.5))  # 1.35 * 101
