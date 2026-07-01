import unittest
from unittest.mock import patch
import numpy as np
import visdom


class TestLine(unittest.TestCase):
    def setUp(self):
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)

    def _line(self, Y, X=None, **kwargs):
        sent = {}

        def capture(msg, endpoint="events"):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.line(Y, X=X, **kwargs)
        return sent

    def test_y_1d_no_x(self):
        sent = self._line(np.array([1.0, 2.0, 3.0]))
        self.assertIn("data", sent["payload"])

    def test_y_0d_raises(self):
        with self.assertRaises(AssertionError):
            self.viz.line(np.float64(1.0))

    def test_y_3d_raises(self):
        with self.assertRaises(AssertionError):
            self.viz.line(np.ones((2, 3, 4)))

    def test_y_empty_last_dim_raises(self):
        with self.assertRaises(AssertionError):
            self.viz.line(np.empty((5, 0)))

    def test_x_3d_raises(self):
        with self.assertRaises(AssertionError):
            self.viz.line(np.array([1.0, 2.0]), X=np.ones((2, 1, 1)))

    def test_x_shape_mismatch_raises(self):
        with self.assertRaises(AssertionError):
            self.viz.line(np.array([1.0, 2.0, 3.0]), X=np.array([0.0, 1.0]))

    def test_single_line_one_trace(self):
        sent = self._line(np.array([1.0, 2.0, 3.0]))
        self.assertEqual(len(sent["payload"]["data"]), 1)

    def test_multi_line_2d_y(self):
        Y = np.array([[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])
        sent = self._line(Y)
        self.assertEqual(len(sent["payload"]["data"]), 2)

    def test_y_2d_single_col_one_trace(self):
        sent = self._line(np.array([[1.0], [2.0], [3.0]]))
        self.assertEqual(len(sent["payload"]["data"]), 1)

    def test_y_2d_x_1d_broadcasts(self):
        Y = np.array([[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])
        X = np.array([0.0, 1.0, 2.0])
        sent = self._line(Y, X=X)
        self.assertIn("data", sent["payload"])

    def test_update_append_requires_x(self):
        with self.assertRaises(AssertionError):
            self.viz.line(np.array([1.0, 2.0]), win="w", update="append")

    def test_update_append_sets_append_true(self):
        Y = np.array([1.0, 2.0])
        X = np.array([0.0, 1.0])
        with patch.object(self.viz, "win_exists", return_value=True):
            sent = self._line(Y, X=X, win="w", update="append")
        self.assertTrue(sent["payload"]["append"])

    def test_update_replace_sets_append_false(self):
        Y = np.array([1.0, 2.0])
        X = np.array([0.0, 1.0])
        sent = self._line(Y, X=X, win="w", update="replace")
        self.assertFalse(sent["payload"]["append"])

    def test_update_replace_uses_update_endpoint(self):
        Y = np.array([1.0, 2.0])
        X = np.array([0.0, 1.0])
        sent = self._line(Y, X=X, win="w", update="replace")
        self.assertEqual(sent["endpoint"], "update")

    def test_update_append_new_window_no_append_key(self):
        Y = np.array([1.0, 2.0])
        X = np.array([0.0, 1.0])
        with patch.object(self.viz, "win_exists", return_value=False):
            sent = self._line(Y, X=X, win="w", update="append")
        self.assertNotIn("append", sent["payload"])

    def test_update_remove_sends_delete(self):
        sent = self._line(None, win="w", name="trace1", update="remove")
        self.assertTrue(sent["payload"]["delete"])

    def test_nan_y_passes_through(self):
        Y = np.array([np.nan, np.nan, np.nan])
        X = np.array([0.0, 1.0, 2.0])
        with patch.object(self.viz, "win_exists", return_value=True):
            sent = self._line(Y, X=X, win="w", update="append")
        y_vals = sent["payload"]["data"][0]["y"]
        self.assertTrue(all(np.isnan(v) for v in y_vals))


class TestScatter(unittest.TestCase):
    def setUp(self):
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)

    def _scatter(self, X, Y=None, **kwargs):
        sent = {}

        def capture(msg, endpoint="events"):
            sent["payload"] = msg
            sent["endpoint"] = endpoint
            return "win1"

        with patch.object(self.viz, "_send", side_effect=capture):
            self.viz.scatter(X, Y=Y, **kwargs)
        return sent

    def test_nx2_input(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        sent = self._scatter(X)
        self.assertEqual(sent["payload"]["data"][0]["type"], "scatter")

    def test_nx3_input_produces_scatter3d(self):
        X = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        sent = self._scatter(X)
        self.assertEqual(sent["payload"]["data"][0]["type"], "scatter3d")

    def test_x_1d_raises(self):
        with self.assertRaises(AssertionError):
            self.viz.scatter(np.array([1.0, 2.0, 3.0]))

    def test_x_wrong_cols_raises(self):
        with self.assertRaises(AssertionError):
            self.viz.scatter(np.ones((3, 4)))

    def test_y_size_mismatch_raises(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        Y = np.array([1, 2, 3])
        with self.assertRaises(AssertionError):
            self.viz.scatter(X, Y=Y)

    def test_nan_label_raises(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        Y = np.array([1.0, np.nan])
        with self.assertRaises(AssertionError):
            self.viz.scatter(X, Y=Y)

    def test_multiple_labels_produce_multiple_traces(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        Y = np.array([1, 1, 2])
        sent = self._scatter(X, Y=Y)
        self.assertEqual(len(sent["payload"]["data"]), 2)

    def test_name_with_multiple_labels_raises(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        Y = np.array([1, 2])
        with self.assertRaises(AssertionError):
            self.viz.scatter(X, Y=Y, name="trace1")

    def test_store_history_with_update_raises(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        with self.assertRaises(ValueError):
            self.viz.scatter(X, opts={"store_history": True}, update="append", win="w")

    def test_update_without_win_raises(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        with self.assertRaises(ValueError):
            self.viz.scatter(X, update="replace")

    def test_update_remove_requires_name(self):
        with self.assertRaises(AssertionError):
            self.viz.scatter(None, win="w", update="remove")

    def test_update_remove_sends_delete(self):
        sent = self._scatter(None, win="w", name="trace1", update="remove")
        self.assertTrue(sent["payload"]["delete"])

    def test_update_append_sets_append_true(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        with patch.object(self.viz, "win_exists", return_value=True):
            sent = self._scatter(X, win="w", update="append")
        self.assertTrue(sent["payload"]["append"])

    def test_update_replace_sets_append_false(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        sent = self._scatter(X, win="w", update="replace")
        self.assertFalse(sent["payload"]["append"])

    def test_name_based_update_1d_x_1d_y(self):
        X = np.array([1.0, 2.0, 3.0])
        Y = np.array([4.0, 5.0, 6.0])
        with patch.object(self.viz, "win_exists", return_value=True):
            sent = self._scatter(X, Y=Y, win="w", update="append", name="t1")
        data = sent["payload"]["data"][0]
        self.assertEqual(data["x"], [1.0, 2.0, 3.0])
        self.assertEqual(data["y"], [4.0, 5.0, 6.0])


if __name__ == "__main__":
    unittest.main()
