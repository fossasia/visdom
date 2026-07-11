import unittest
from unittest.mock import patch
import numpy as np
import visdom


class TestLine(unittest.TestCase):
    def setUp(self):
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)

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
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)

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
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)

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


if __name__ == "__main__":
    unittest.main()
