"""
Tests for the vis.parallel_coordinates() client method.

Validates input checking, dimension construction, color configuration,
max_experiments filtering, and all supported opts.
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np


class TestParallelCoordinates(unittest.TestCase):
    """Unit tests for Visdom.parallel_coordinates()."""

    def setUp(self):
        with patch("visdom.Visdom.__init__", return_value=None):
            from visdom import Visdom

            self.viz = Visdom()
        self.viz._send = MagicMock(return_value="win_abc")

    def _last_payload(self):
        """Return the dict passed to _send in the most recent call."""
        return self.viz._send.call_args[0][0]

    def test_basic_two_dimensions(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        self.viz.parallel_coordinates(X)

        payload = self._last_payload()
        self.assertEqual(len(payload["data"]), 1)
        trace = payload["data"][0]
        self.assertEqual(trace["type"], "parcoords")
        self.assertEqual(len(trace["dimensions"]), 2)
        self.assertEqual(trace["dimensions"][0]["label"], "Dim 1")
        self.assertEqual(trace["dimensions"][1]["label"], "Dim 2")
        self.assertEqual(trace["dimensions"][0]["values"], [1.0, 3.0])
        self.assertEqual(trace["dimensions"][1]["values"], [2.0, 4.0])
        self.assertIsNone(trace.get("line"))

    def test_returns_send_result(self):
        ret = self.viz.parallel_coordinates(np.array([[1, 2], [3, 4]]))
        self.assertEqual(ret, "win_abc")

    def test_y_color_values(self):
        X = np.array([[1, 2], [3, 4], [5, 6]])
        Y = np.array([10, 20, 30])
        self.viz.parallel_coordinates(X, Y=Y)

        trace = self._last_payload()["data"][0]
        line = trace["line"]
        self.assertEqual(line["color"], [10.0, 20.0, 30.0])
        self.assertEqual(line["colorscale"], "Electric")
        self.assertTrue(line["showscale"])
        self.assertEqual(line["cmin"], 10.0)
        self.assertEqual(line["cmax"], 30.0)

    def test_y_custom_colormap(self):
        X = np.array([[1, 2], [3, 4]])
        Y = np.array([0.1, 0.9])
        self.viz.parallel_coordinates(X, Y=Y, opts={"colormap": "Jet"})

        line = self._last_payload()["data"][0]["line"]
        self.assertEqual(line["colorscale"], "Jet")

    def test_y_reversescale(self):
        X = np.array([[1, 2], [3, 4]])
        Y = np.array([0.1, 0.9])
        self.viz.parallel_coordinates(X, Y=Y, opts={"reversescale": True})

        line = self._last_payload()["data"][0]["line"]
        self.assertTrue(line["reversescale"])

    def test_custom_dimension_labels(self):
        X = np.array([[1, 2, 3], [4, 5, 6]])
        self.viz.parallel_coordinates(X, opts={"dimensions": ["LR", "BS", "Acc"]})

        dims = self._last_payload()["data"][0]["dimensions"]
        self.assertEqual([d["label"] for d in dims], ["LR", "BS", "Acc"])

    def test_custom_ranges(self):
        X = np.array([[1, 2], [3, 4]])
        self.viz.parallel_coordinates(X, opts={"ranges": {0: [0, 10]}})

        dims = self._last_payload()["data"][0]["dimensions"]
        self.assertEqual(dims[0]["range"], [0, 10])
        self.assertNotEqual(dims[1]["range"], [0, 10])

    def test_constraint_ranges(self):
        X = np.array([[1, 2], [3, 4]])
        self.viz.parallel_coordinates(
            X, opts={"constraintranges": {1: [2.5, 4.5]}}
        )

        dims = self._last_payload()["data"][0]["dimensions"]
        self.assertNotIn("constraintrange", dims[0])
        self.assertEqual(dims[1]["constraintrange"], [2.5, 4.5])

    def test_tickvals_and_ticktext(self):
        X = np.array([[0, 1], [1, 2], [2, 0]])
        self.viz.parallel_coordinates(
            X,
            opts={
                "tickvals": {0: [0, 1, 2]},
                "ticktext": {0: ["low", "mid", "high"]},
            },
        )

        dim0 = self._last_payload()["data"][0]["dimensions"][0]
        self.assertEqual(dim0["tickvals"], [0, 1, 2])
        self.assertEqual(dim0["ticktext"], ["low", "mid", "high"])

    def test_max_experiments_filters_top_n(self):
        X = np.array([[1, 2], [3, 4], [5, 6], [7, 8]])
        Y = np.array([10, 40, 30, 20])
        self.viz.parallel_coordinates(X, Y=Y, opts={"max_experiments": 2})

        trace = self._last_payload()["data"][0]
        self.assertEqual(len(trace["dimensions"][0]["values"]), 2)
        line = trace["line"]
        self.assertIn(40.0, line["color"])
        self.assertIn(30.0, line["color"])
        self.assertNotIn(10.0, line["color"])

    def test_max_experiments_no_filter_when_n_less_than_max(self):
        X = np.array([[1, 2], [3, 4]])
        Y = np.array([10, 20])
        self.viz.parallel_coordinates(X, Y=Y, opts={"max_experiments": 5})

        trace = self._last_payload()["data"][0]
        self.assertEqual(len(trace["dimensions"][0]["values"]), 2)

    def test_title_in_layout(self):
        X = np.array([[1, 2], [3, 4]])
        self.viz.parallel_coordinates(X, opts={"title": "My Plot"})

        payload = self._last_payload()
        self.assertEqual(payload["layout"]["title"]["text"], "My Plot")
        self.assertEqual(payload["layout"]["title"]["x"], 0.5)
        trace = payload["data"][0]
        self.assertEqual(trace["domain"], {"y": [0, 0.85]})

    def test_no_title_no_domain(self):
        X = np.array([[1, 2], [3, 4]])
        self.viz.parallel_coordinates(X)

        trace = self._last_payload()["data"][0]
        self.assertNotIn("domain", trace)

    def test_auto_width_without_colorbar(self):
        X = np.array([[1, 2, 3, 4, 5]] * 2)
        self.viz.parallel_coordinates(X)

        opts = self._last_payload()["opts"]
        self.assertEqual(opts["width"], max(600, 5 * 140))
        self.assertEqual(opts["height"], 450)

    def test_auto_width_with_colorbar(self):
        X = np.array([[1, 2]] * 2)
        Y = np.array([0, 1])
        self.viz.parallel_coordinates(X, Y=Y)

        opts = self._last_payload()["opts"]
        self.assertEqual(opts["width"], max(600, 2 * 140 + 100))

    def test_explicit_size_not_overridden(self):
        X = np.array([[1, 2], [3, 4]])
        self.viz.parallel_coordinates(X, opts={"width": 999, "height": 777})

        opts = self._last_payload()["opts"]
        self.assertEqual(opts["width"], 999)
        self.assertEqual(opts["height"], 777)

    def test_win_and_env_passed_through(self):
        X = np.array([[1, 2], [3, 4]])
        self.viz.parallel_coordinates(X, win="mywin", env="myenv")

        payload = self._last_payload()
        self.assertEqual(payload["win"], "mywin")
        self.assertEqual(payload["eid"], "myenv")

    def test_nan_in_x_converted_to_none(self):
        X = np.array([[1, np.nan], [3, 4]])
        self.viz.parallel_coordinates(X)

        dims = self._last_payload()["data"][0]["dimensions"]
        self.assertIsNone(dims[1]["values"][0])
        self.assertEqual(dims[1]["values"][1], 4.0)

    def test_nan_in_y_converted_to_none(self):
        X = np.array([[1, 2], [3, 4]])
        Y = np.array([np.nan, 5.0])
        self.viz.parallel_coordinates(X, Y=Y)

        line = self._last_payload()["data"][0]["line"]
        self.assertIsNone(line["color"][0])
        self.assertEqual(line["color"][1], 5.0)

    def test_layout_bgcolor_defaults(self):
        X = np.array([[1, 2], [3, 4]])
        self.viz.parallel_coordinates(X)

        layout = self._last_payload()["layout"]
        self.assertEqual(layout["paper_bgcolor"], "white")
        self.assertEqual(layout["plot_bgcolor"], "white")

    def test_1d_x_rejected(self):
        with self.assertRaises(AssertionError):
            self.viz.parallel_coordinates(np.array([1, 2, 3]))

    def test_single_column_rejected(self):
        with self.assertRaises(AssertionError):
            self.viz.parallel_coordinates(np.array([[1], [2]]))

    def test_y_length_mismatch_rejected(self):
        with self.assertRaises(AssertionError):
            self.viz.parallel_coordinates(
                np.array([[1, 2], [3, 4]]), Y=np.array([1, 2, 3])
            )

    def test_wrong_dimensions_length_rejected(self):
        with self.assertRaises(AssertionError):
            self.viz.parallel_coordinates(
                np.array([[1, 2], [3, 4]]), opts={"dimensions": ["only_one"]}
            )

    def test_max_experiments_without_y_rejected(self):
        with self.assertRaises(AssertionError):
            self.viz.parallel_coordinates(
                np.array([[1, 2], [3, 4]]), opts={"max_experiments": 1}
            )

    def test_list_input_converted_to_array(self):
        self.viz.parallel_coordinates([[1, 2], [3, 4]])

        dims = self._last_payload()["data"][0]["dimensions"]
        self.assertEqual(dims[0]["values"], [1.0, 3.0])

    def test_y_list_input_converted(self):
        self.viz.parallel_coordinates([[1, 2], [3, 4]], Y=[10, 20])

        line = self._last_payload()["data"][0]["line"]
        self.assertEqual(line["color"], [10.0, 20.0])

    def test_font_sizes_set(self):
        X = np.array([[1, 2], [3, 4]])
        self.viz.parallel_coordinates(X)

        trace = self._last_payload()["data"][0]
        self.assertEqual(trace["labelfont"], {"size": 13})
        self.assertEqual(trace["tickfont"], {"size": 11})
        self.assertEqual(trace["rangefont"], {"size": 11})

    def test_auto_range_padding(self):
        X = np.array([[10, 100], [20, 200]])
        self.viz.parallel_coordinates(X)

        dims = self._last_payload()["data"][0]["dimensions"]
        self.assertAlmostEqual(dims[0]["range"][0], 10 - 0.5)
        self.assertAlmostEqual(dims[0]["range"][1], 20 + 0.5)

    def test_constant_column_padding(self):
        X = np.array([[5, 1], [5, 2]])
        self.viz.parallel_coordinates(X)

        dims = self._last_payload()["data"][0]["dimensions"]
        self.assertAlmostEqual(dims[0]["range"][0], 5 - 0.5)
        self.assertAlmostEqual(dims[0]["range"][1], 5 + 0.5)


if __name__ == "__main__":
    unittest.main()
