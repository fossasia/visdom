#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import unittest
from unittest.mock import Mock, patch
import numpy as np
import visdom


def _unconnected_visdom():
    with (
        patch.object(visdom.Visdom, "_handle_post", return_value=True),
        patch.object(visdom.Visdom, "_start_session_reaper"),
        patch.object(visdom.logger, "warning"),
    ):
        client = visdom.Visdom(use_incoming_socket=False)
    client._handle_post = Mock(
        side_effect=AssertionError("unexpected transport call in unit test")
    )
    return client


class TestLine(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()

    def _line(self, Y, X=None, **kwargs):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.line(Y, X=X, **kwargs)
        return sent

    def test_y_1d_no_x(self):
        """Basic 1D Y without X auto-generates x-axis."""
        sent = self._line(np.array([1.0, 2.0, 3.0]))
        self.assertIn("data", sent["payload"])

    def test_y_0d_raises(self):
        """Scalar Y raises before reaching scatter."""
        with self.assertRaises(AssertionError):
            self.viz.line(np.float64(1.0))

    def test_y_3d_raises(self):
        """3D Y raises on the ndim check."""
        with self.assertRaises(AssertionError):
            self.viz.line(np.ones((2, 3, 4)))

    def test_y_empty_last_dim_raises(self):
        """Zero-column Y raises on the empty check."""
        with self.assertRaises(AssertionError):
            self.viz.line(np.empty((5, 0)))

    def test_x_3d_raises(self):
        """3D X raises on the ndim check."""
        with self.assertRaises(AssertionError):
            self.viz.line(np.array([1.0, 2.0]), X=np.ones((2, 1, 1)))

    def test_x_shape_mismatch_raises(self):
        """X and Y with different lengths raise on the shape check."""
        with self.assertRaises(AssertionError):
            self.viz.line(np.array([1.0, 2.0, 3.0]), X=np.array([0.0, 1.0]))

    def test_single_line_one_trace(self):
        """1D Y produces exactly one trace."""
        sent = self._line(np.array([1.0, 2.0, 3.0]))
        self.assertEqual(len(sent["payload"]["data"]), 1)

    def test_multi_line_2d_y(self):
        """2D Y with M columns produces M traces."""
        Y = np.array([[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])
        sent = self._line(Y)
        self.assertEqual(len(sent["payload"]["data"]), 2)

    def test_y_2d_single_col_one_trace(self):
        """(N,1) Y is squeezed to 1D before building linedata."""
        sent = self._line(np.array([[1.0], [2.0], [3.0]]))
        self.assertEqual(len(sent["payload"]["data"]), 1)

    def test_y_2d_x_1d_broadcasts(self):
        """1D X is tiled to match the shape of 2D Y."""
        Y = np.array([[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])
        X = np.array([0.0, 1.0, 2.0])
        sent = self._line(Y, X=X)
        self.assertIn("data", sent["payload"])

    def test_update_append_requires_x(self):
        """update='append' without X raises before sending."""
        with self.assertRaises(AssertionError):
            self.viz.line(np.array([1.0, 2.0]), win="w", update="append")

    def test_update_append_sets_append_true(self):
        """Existing window with update='append' sets append=True in payload."""
        Y = np.array([1.0, 2.0])
        X = np.array([0.0, 1.0])
        with patch.object(self.viz, "win_exists", return_value=True):
            sent = self._line(Y, X=X, win="w", update="append")
        self.assertTrue(sent["payload"]["append"])

    def test_update_replace_sets_append_false(self):
        """update='replace' sets append=False in payload."""
        Y = np.array([1.0, 2.0])
        X = np.array([0.0, 1.0])
        sent = self._line(Y, X=X, win="w", update="replace")
        self.assertFalse(sent["payload"]["append"])

    def test_update_replace_uses_update_endpoint(self):
        """update='replace' routes to the update endpoint."""
        Y = np.array([1.0, 2.0])
        X = np.array([0.0, 1.0])
        sent = self._line(Y, X=X, win="w", update="replace")
        self.assertEqual(sent["endpoint"], "update")

    def test_update_append_new_window_no_append_key(self):
        """New window with update='append' falls back to creation, no append key."""
        Y = np.array([1.0, 2.0])
        X = np.array([0.0, 1.0])
        with patch.object(self.viz, "win_exists", return_value=False):
            sent = self._line(Y, X=X, win="w", update="append")
        self.assertNotIn("append", sent["payload"])

    def test_update_remove_sends_delete(self):
        """update='remove' sends delete=True without touching Y."""
        sent = self._line(None, win="w", name="trace1", update="remove")
        self.assertTrue(sent["payload"]["delete"])

    def test_nan_y_passes_through(self):
        """All-NaN Y values survive into the payload for use as update mask."""
        Y = np.array([np.nan, np.nan, np.nan])
        X = np.array([0.0, 1.0, 2.0])
        with patch.object(self.viz, "win_exists", return_value=True):
            sent = self._line(Y, X=X, win="w", update="append")
        y_vals = sent["payload"]["data"][0]["y"]
        self.assertTrue(all(np.isnan(v) for v in y_vals))

    def test_inf_y_passes_through(self):
        """Inf Y values pass through without raising."""
        Y = np.array([np.inf, 1.0, -np.inf])
        X = np.array([0.0, 1.0, 2.0])
        sent = self._line(Y, X=X)
        y_vals = sent["payload"]["data"][0]["y"]
        self.assertTrue(np.isinf(y_vals[0]))
        self.assertTrue(np.isinf(y_vals[2]))


class TestScatter(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()

    def _scatter(self, X, Y=None, **kwargs):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.scatter(X, Y=Y, **kwargs)
        return sent

    def test_nx2_input(self):
        """Nx2 X produces a scatter trace."""
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        sent = self._scatter(X)
        self.assertEqual(sent["payload"]["data"][0]["type"], "scatter")

    def test_nx3_input_produces_scatter3d(self):
        """Nx3 X produces a scatter3d trace."""
        X = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        sent = self._scatter(X)
        self.assertEqual(sent["payload"]["data"][0]["type"], "scatter3d")

    def test_x_1d_raises(self):
        """1D X raises on the ndim check."""
        with self.assertRaises(AssertionError):
            self.viz.scatter(np.array([1.0, 2.0, 3.0]))

    def test_x_wrong_cols_raises(self):
        """X with column count other than 2 or 3 raises."""
        with self.assertRaises(AssertionError):
            self.viz.scatter(np.ones((3, 4)))

    def test_y_size_mismatch_raises(self):
        """Y length not matching X row count raises."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        Y = np.array([1, 2, 3])
        with self.assertRaises(AssertionError):
            self.viz.scatter(X, Y=Y)

    def test_nan_label_raises(self):
        """NaN in Y labels raises via the isfinite check in _normalize_labels."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        Y = np.array([1.0, np.nan])
        with self.assertRaises(AssertionError):
            self.viz.scatter(X, Y=Y)

    def test_inf_label_raises(self):
        """Inf in Y labels raises via the same isfinite check as NaN."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        Y = np.array([1.0, np.inf])
        with self.assertRaises(AssertionError):
            self.viz.scatter(X, Y=Y)

    def test_multiple_labels_produce_multiple_traces(self):
        """Distinct Y label values produce one trace each."""
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        Y = np.array([1, 1, 2])
        sent = self._scatter(X, Y=Y)
        self.assertEqual(len(sent["payload"]["data"]), 2)

    def test_name_with_multiple_labels_raises(self):
        """name= combined with multiple label groups raises."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        Y = np.array([1, 2])
        with self.assertRaises(AssertionError):
            self.viz.scatter(X, Y=Y, name="trace1")

    def test_store_history_with_update_raises(self):
        """store_history=True combined with update raises ValueError."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        with self.assertRaises(ValueError):
            self.viz.scatter(X, opts={"store_history": True}, update="append", win="w")

    def test_update_without_win_raises(self):
        """update without a win raises ValueError."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        with self.assertRaises(ValueError):
            self.viz.scatter(X, update="replace")

    def test_update_remove_requires_name(self):
        """update='remove' without name raises."""
        with self.assertRaises(AssertionError):
            self.viz.scatter(None, win="w", update="remove")

    def test_update_remove_sends_delete(self):
        """update='remove' sends delete=True in payload."""
        sent = self._scatter(None, win="w", name="trace1", update="remove")
        self.assertTrue(sent["payload"]["delete"])

    def test_update_append_sets_append_true(self):
        """Existing window with update='append' sets append=True."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        with patch.object(self.viz, "win_exists", return_value=True):
            sent = self._scatter(X, win="w", update="append")
        self.assertTrue(sent["payload"]["append"])

    def test_update_replace_sets_append_false(self):
        """update='replace' sets append=False in payload."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._scatter(X, win="w", update="replace")
        self.assertFalse(sent["payload"]["append"])

    def test_name_based_update_1d_x_1d_y(self):
        """Name-based update stacks 1D X and Y into Nx2 before sending."""
        X = np.array([1.0, 2.0, 3.0])
        Y = np.array([4.0, 5.0, 6.0])
        with patch.object(self.viz, "win_exists", return_value=True):
            sent = self._scatter(X, Y=Y, win="w", update="append", name="t1")
        data = sent["payload"]["data"][0]
        self.assertEqual(data["x"], [1.0, 2.0, 3.0])
        self.assertEqual(data["y"], [4.0, 5.0, 6.0])


class TestHeatmap(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()

    def _heatmap(self, X, **kwargs):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.heatmap(X, **kwargs)
        return sent

    def test_nx_m_input(self):
        """NxM X produces a heatmap trace."""
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        sent = self._heatmap(X)
        self.assertEqual(sent["payload"]["data"][0]["type"], "heatmap")

    def test_x_not_2d_raises(self):
        """1D X raises on the 2D check."""
        with self.assertRaises(AssertionError):
            self.viz.heatmap(np.array([1.0, 2.0, 3.0]))

    def test_invalid_update_raises(self):
        """Unknown update value raises before building data."""
        X = np.ones((3, 3))
        with self.assertRaises(AssertionError):
            self.viz.heatmap(X, update="badvalue")

    def test_colormap_defaults_to_viridis(self):
        """colormap defaults to Viridis when not specified."""
        X = np.ones((2, 2))
        sent = self._heatmap(X)
        self.assertEqual(sent["payload"]["opts"]["colormap"], "Viridis")

    def test_append_row_sets_update_dir(self):
        """appendRow sets updateDir and append=True on the update endpoint."""
        X = np.ones((2, 2))
        sent = self._heatmap(X, update="appendRow", win="w")
        self.assertEqual(sent["payload"]["updateDir"], "appendRow")
        self.assertTrue(sent["payload"]["append"])
        self.assertEqual(sent["endpoint"], "update")

    def test_append_column_sets_update_dir(self):
        """appendColumn sets updateDir and append=True."""
        X = np.ones((2, 2))
        sent = self._heatmap(X, update="appendColumn", win="w")
        self.assertEqual(sent["payload"]["updateDir"], "appendColumn")
        self.assertTrue(sent["payload"]["append"])

    def test_replace_sets_append_false(self):
        """replace sets append=False on the update endpoint."""
        X = np.ones((2, 2))
        sent = self._heatmap(X, update="replace", win="w")
        self.assertFalse(sent["payload"]["append"])

    def test_nan_values_pass_through(self):
        """NaN values in X pass through to the payload without raising."""
        X = np.array([[1.0, np.nan], [np.nan, 4.0]])
        sent = self._heatmap(X)
        z = sent["payload"]["data"][0]["z"]
        self.assertTrue(np.isnan(z[0][1]))
        self.assertTrue(np.isnan(z[1][0]))


class TestBar(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()

    def _bar(self, X, Y=None, **kwargs):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.bar(X, Y=Y, **kwargs)
        return sent

    def test_1d_x_one_trace(self):
        """1D X produces a single bar trace."""
        sent = self._bar(np.array([1.0, 2.0, 3.0]))
        self.assertEqual(len(sent["payload"]["data"]), 1)
        self.assertEqual(sent["payload"]["data"][0]["type"], "bar")

    def test_2d_x_one_trace_per_column(self):
        """NxM X produces M bar traces."""
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        sent = self._bar(X)
        self.assertEqual(len(sent["payload"]["data"]), 2)

    def test_3d_x_raises(self):
        """3D X raises on the ndim check."""
        with self.assertRaises(AssertionError):
            self.viz.bar(np.ones((2, 3, 4)))

    def test_x_y_length_mismatch_raises(self):
        """Y with a different length than X raises."""
        with self.assertRaises(AssertionError):
            self.viz.bar(np.array([1.0, 2.0, 3.0]), Y=np.array([1.0, 2.0]))

    def test_default_x_axis_is_one_based(self):
        """Without Y the x-axis is 1..N."""
        sent = self._bar(np.array([1.0, 2.0, 3.0]))
        self.assertEqual(sent["payload"]["data"][0]["x"], [1, 2, 3])

    def test_y_sets_x_axis_values(self):
        """Y supplies the x-axis values."""
        sent = self._bar(np.array([1.0, 2.0]), Y=np.array([10.0, 20.0]))
        self.assertEqual(sent["payload"]["data"][0]["x"], [10.0, 20.0])

    def test_column_values_go_to_y(self):
        """Each trace carries its own column of X as bar heights."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._bar(X)
        self.assertEqual(sent["payload"]["data"][0]["y"], [1.0, 3.0])
        self.assertEqual(sent["payload"]["data"][1]["y"], [2.0, 4.0])

    def test_rownames_replace_x_axis(self):
        """rownames are used as x-axis labels instead of Y."""
        opts = {"rownames": ["a", "b", "c"]}
        sent = self._bar(np.array([1.0, 2.0, 3.0]), opts=opts)
        self.assertEqual(sent["payload"]["data"][0]["x"], ["a", "b", "c"])

    def test_rownames_length_mismatch_raises(self):
        """rownames shorter than the number of rows raises."""
        with self.assertRaises(AssertionError):
            self.viz.bar(np.array([1.0, 2.0, 3.0]), opts={"rownames": ["a", "b"]})

    def test_legend_sets_trace_names(self):
        """legend labels name each column trace."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._bar(X, opts={"legend": ["first", "second"]})
        names = [trace["name"] for trace in sent["payload"]["data"]]
        self.assertEqual(names, ["first", "second"])

    def test_legend_length_mismatch_raises(self):
        """legend length not matching the column count raises."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        with self.assertRaises(AssertionError):
            self.viz.bar(X, opts={"legend": ["only_one"]})

    def test_legend_on_1d_x_transposes(self):
        """1D X with a legend is treated as one row of grouped bars."""
        sent = self._bar(np.array([1.0, 2.0, 3.0]), opts={"legend": ["a", "b", "c"]})
        self.assertEqual(len(sent["payload"]["data"]), 3)

    def test_legend_with_rownames_on_1d_raises(self):
        """legend and rownames together on 1D X raise."""
        opts = {"legend": ["a", "b", "c"], "rownames": ["x", "y", "z"]}
        with self.assertRaises(AssertionError):
            self.viz.bar(np.array([1.0, 2.0, 3.0]), opts=opts)

    def test_stacked_sets_barmode(self):
        """stacked=True stacks the columns instead of grouping them."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._bar(X, opts={"stacked": True})
        self.assertEqual(sent["payload"]["layout"]["barmode"], "stack")


class TestHistogram(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()

    def _histogram(self, X, **kwargs):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.histogram(X, **kwargs)
        return sent

    def test_2d_x_raises(self):
        """2D X raises on the one-dimensional check."""
        with self.assertRaises(AssertionError):
            self.viz.histogram(np.ones((3, 3)))

    def test_default_bin_count_capped_at_30(self):
        """A large sample is drawn with 30 bars by default."""
        sent = self._histogram(np.arange(100.0))
        self.assertEqual(len(sent["payload"]["data"][0]["y"]), 30)

    def test_default_bin_count_is_sample_count_when_small(self):
        """A sample smaller than 30 gets one bar per value by default."""
        sent = self._histogram(np.arange(5.0))
        self.assertEqual(len(sent["payload"]["data"][0]["y"]), 5)

    def test_numbins_opt_sets_bin_count(self):
        """numbins controls how many bars are produced."""
        sent = self._histogram(np.arange(100.0), opts={"numbins": 10})
        self.assertEqual(len(sent["payload"]["data"][0]["y"]), 10)

    def test_counts_sum_to_sample_count(self):
        """Every sample lands in exactly one bin."""
        sent = self._histogram(np.arange(100.0), opts={"numbins": 10})
        self.assertEqual(sum(sent["payload"]["data"][0]["y"]), 100)

    def test_bin_edges_span_data_range(self):
        """The x-axis runs from the minimum to the maximum of X."""
        sent = self._histogram(np.arange(100.0), opts={"numbins": 10})
        x = sent["payload"]["data"][0]["x"]
        self.assertEqual(x[0], 0.0)
        self.assertEqual(x[-1], 99.0)


class TestBoxplot(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()

    def _boxplot(self, X, **kwargs):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.boxplot(X, **kwargs)
        return sent

    def test_1d_x_one_box(self):
        """1D X produces a single box trace."""
        sent = self._boxplot(np.array([1.0, 2.0, 3.0]))
        self.assertEqual(len(sent["payload"]["data"]), 1)
        self.assertEqual(sent["payload"]["data"][0]["type"], "box")

    def test_2d_x_one_box_per_column(self):
        """NxM X produces M box traces."""
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        sent = self._boxplot(X)
        self.assertEqual(len(sent["payload"]["data"]), 2)

    def test_3d_x_raises(self):
        """3D X raises on the ndim check."""
        with self.assertRaises(AssertionError):
            self.viz.boxplot(np.ones((2, 3, 4)))

    def test_column_values_go_to_y(self):
        """Each box carries the values of its own column."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._boxplot(X)
        self.assertEqual(sent["payload"]["data"][0]["y"], [1.0, 3.0])
        self.assertEqual(sent["payload"]["data"][1]["y"], [2.0, 4.0])

    def test_default_names_are_column_indexed(self):
        """Without a legend each box is named after its column index."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._boxplot(X)
        names = [trace["name"] for trace in sent["payload"]["data"]]
        self.assertEqual(names, ["column 0", "column 1"])

    def test_legend_sets_box_names(self):
        """legend labels replace the default column names."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._boxplot(X, opts={"legend": ["train", "test"]})
        names = [trace["name"] for trace in sent["payload"]["data"]]
        self.assertEqual(names, ["train", "test"])

    def test_legend_length_mismatch_raises(self):
        """legend length not matching the column count raises."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        with self.assertRaises(AssertionError):
            self.viz.boxplot(X, opts={"legend": ["only_one"]})


class TestSurf(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()

    def _surf(self, X, **kwargs):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.surf(X, **kwargs)
        return sent

    def test_1d_x_raises(self):
        """1D X raises on the two-dimensional check."""
        with self.assertRaises(AssertionError):
            self.viz.surf(np.array([1.0, 2.0, 3.0]))

    def test_type_is_surface(self):
        """surf produces a surface trace."""
        sent = self._surf(np.ones((3, 3)))
        self.assertEqual(sent["payload"]["data"][0]["type"], "surface")

    def test_z_matches_input(self):
        """X is sent verbatim as the z values."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._surf(X)
        self.assertEqual(sent["payload"]["data"][0]["z"], [[1.0, 2.0], [3.0, 4.0]])

    def test_colormap_defaults_to_viridis(self):
        """colormap defaults to Viridis when not specified."""
        sent = self._surf(np.ones((2, 2)))
        self.assertEqual(sent["payload"]["data"][0]["colorscale"], "Viridis")

    def test_colormap_opt_forwarded(self):
        """An explicit colormap reaches the trace."""
        sent = self._surf(np.ones((2, 2)), opts={"colormap": "Hot"})
        self.assertEqual(sent["payload"]["data"][0]["colorscale"], "Hot")

    def test_range_defaults_to_data_range(self):
        """xmin and xmax default to the minimum and maximum of X."""
        X = np.array([[1.0, 5.0], [3.0, 9.0]])
        sent = self._surf(X)
        self.assertEqual(sent["payload"]["data"][0]["cmin"], 1.0)
        self.assertEqual(sent["payload"]["data"][0]["cmax"], 9.0)

    def test_range_opts_override_data_range(self):
        """xmin and xmax opts clip the color range."""
        X = np.array([[1.0, 5.0], [3.0, 9.0]])
        sent = self._surf(X, opts={"xmin": 2.0, "xmax": 4.0})
        self.assertEqual(sent["payload"]["data"][0]["cmin"], 2.0)
        self.assertEqual(sent["payload"]["data"][0]["cmax"], 4.0)

    def test_nan_ignored_in_range(self):
        """NaN values do not leak into the default color range."""
        X = np.array([[1.0, np.nan], [3.0, 9.0]])
        sent = self._surf(X)
        self.assertEqual(sent["payload"]["data"][0]["cmin"], 1.0)
        self.assertEqual(sent["payload"]["data"][0]["cmax"], 9.0)

    def test_layout_is_3d(self):
        """surf builds a 3D scene layout."""
        sent = self._surf(np.ones((2, 2)))
        self.assertIn("scene", sent["payload"]["layout"])


class TestContour(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()

    def _contour(self, X, **kwargs):
        sent = {}

        def capture(msg, endpoint="events", **_):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.contour(X, **kwargs)
        return sent

    def test_type_is_contour(self):
        """contour produces a contour trace."""
        sent = self._contour(np.ones((3, 3)))
        self.assertEqual(sent["payload"]["data"][0]["type"], "contour")

    def test_layout_is_flat(self):
        """contour renders flat, without the 3D scene surf builds."""
        sent = self._contour(np.ones((2, 2)))
        self.assertNotIn("scene", sent["payload"]["layout"])


if __name__ == "__main__":
    unittest.main()
