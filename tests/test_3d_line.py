"""
Tests for 3D line plot support in vis.line().

Verifies Z parameter handling, data assembly, shape validation,
fillarea warning, and that 2D line plots remain unaffected.
"""

import unittest
import warnings
from unittest.mock import patch, MagicMock

import numpy as np

from visdom import Visdom


def _make_vis():
    """Create a Visdom instance without connecting to a server."""
    with patch.object(Visdom, "__init__", lambda self, **kw: None):
        vis = Visdom.__new__(Visdom)
    vis.win_exists = MagicMock(return_value=False)
    vis._send = MagicMock(return_value="win_id")
    return vis


class TestLineDataAssembly2D(unittest.TestCase):
    """Existing 2D line plots should be unaffected by the Z parameter."""

    def test_2d_line_1d_input(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0, 3.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y)
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape, (3, 2))

    def test_2d_line_no_z_creates_nx2(self):
        vis = _make_vis()
        Y = np.array([10.0, 20.0, 30.0])
        X = np.array([1.0, 2.0, 3.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X)
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape, (3, 2))

    def test_2d_multi_line_no_z(self):
        vis = _make_vis()
        Y = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        X = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X)
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape[1], 2)


class TestLineDataAssembly3D(unittest.TestCase):
    """3D line plots should produce Nx3 data arrays."""

    def test_3d_line_1d_input(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0, 3.0])
        X = np.array([4.0, 5.0, 6.0])
        Z = np.array([7.0, 8.0, 9.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X, Z=Z)
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape, (3, 3))
            np.testing.assert_array_equal(scatter_X[:, 0], X)
            np.testing.assert_array_equal(scatter_X[:, 1], Y)
            np.testing.assert_array_equal(scatter_X[:, 2], Z)

    def test_3d_multi_line(self):
        vis = _make_vis()
        Y = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        X = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
        Z = np.array([[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X, Z=Z)
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape[1], 3)


class TestZBroadcasting(unittest.TestCase):
    """Z should be tiled when it is 1D but Y is 2D (shared Z across lines)."""

    def test_1d_z_broadcast_to_2d_y(self):
        vis = _make_vis()
        Y = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        X = np.array([0.0, 1.0, 2.0])
        Z = np.array([10.0, 20.0, 30.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X, Z=Z)
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape[1], 3)


class TestZColumnFlattening(unittest.TestCase):
    """Single-column Z (Nx1) should be raveled like Y and X."""

    def test_nx1_z_raveled(self):
        vis = _make_vis()
        Y = np.array([[5.0], [10.0]])
        X = np.array([[1.0], [2.0]])
        Z = np.array([[7.0], [8.0]])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X, Z=Z)
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape, (2, 3))


class TestZShapeValidation(unittest.TestCase):
    """Z must match Y shape after broadcasting, and must be 1D or 2D."""

    def test_z_shape_mismatch_raises(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0, 3.0])
        X = np.array([1.0, 2.0, 3.0])
        Z = np.array([1.0, 2.0])

        with self.assertRaises(AssertionError):
            vis.line(Y=Y, X=X, Z=Z)

    def test_z_3d_raises(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0])
        X = np.array([1.0, 2.0])
        Z = np.ones((2, 2, 2))

        with self.assertRaises(AssertionError):
            vis.line(Y=Y, X=X, Z=Z)


class TestFillareaWarning(unittest.TestCase):
    """fillarea=True with Z should warn and be disabled."""

    def test_fillarea_warns_with_z(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0, 3.0])
        X = np.array([1.0, 2.0, 3.0])
        Z = np.array([1.0, 2.0, 3.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                vis.line(Y=Y, X=X, Z=Z, opts={"fillarea": True})
                self.assertEqual(len(w), 1)
                self.assertIn("fillarea", str(w[0].message))

    def test_fillarea_disabled_with_z(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0, 3.0])
        X = np.array([1.0, 2.0, 3.0])
        Z = np.array([1.0, 2.0, 3.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                vis.line(Y=Y, X=X, Z=Z, opts={"fillarea": True})
                passed_opts = mock_scatter.call_args[1]["opts"]
                self.assertFalse(passed_opts["fillarea"])

    def test_no_warning_without_fillarea(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0, 3.0])
        X = np.array([1.0, 2.0, 3.0])
        Z = np.array([1.0, 2.0, 3.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                vis.line(Y=Y, X=X, Z=Z)
                fillarea_warnings = [x for x in w if "fillarea" in str(x.message)]
                self.assertEqual(len(fillarea_warnings), 0)


class TestAppendWithoutZ(unittest.TestCase):
    """Appending to a line plot without Z should produce 2D data."""

    def test_append_without_z_produces_nx2(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0])
        X = np.array([1.0, 2.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X, update="append")
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape, (2, 2))

    def test_append_with_z_produces_nx3(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0])
        X = np.array([1.0, 2.0])
        Z = np.array([1.0, 2.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X, Z=Z, update="append")
            scatter_X = mock_scatter.call_args[1]["X"]
            self.assertEqual(scatter_X.shape, (2, 3))


class TestModeOption(unittest.TestCase):
    """Mode should be set correctly for both 2D and 3D."""

    def test_default_mode_is_lines(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0])
        X = np.array([1.0, 2.0])
        Z = np.array([1.0, 2.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X, Z=Z)
            passed_opts = mock_scatter.call_args[1]["opts"]
            self.assertEqual(passed_opts["mode"], "lines")

    def test_markers_mode(self):
        vis = _make_vis()
        Y = np.array([1.0, 2.0])
        X = np.array([1.0, 2.0])
        Z = np.array([1.0, 2.0])

        with patch.object(vis, "scatter") as mock_scatter:
            mock_scatter.return_value = "win"
            vis.line(Y=Y, X=X, Z=Z, opts={"markers": True})
            passed_opts = mock_scatter.call_args[1]["opts"]
            self.assertEqual(passed_opts["mode"], "lines+markers")


if __name__ == "__main__":
    unittest.main()
