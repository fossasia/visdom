#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Every pane type created through ``POST /events``.

``window()`` dispatches on ``data[0]["type"]``: anything it does not recognise
as a visdom-native pane becomes a generic ``plot`` carrying the traces
untouched. Both halves of that split are asserted here -- the native panes for
the extra keys the server synthesises (``selected``, ``old_content``,
``showEdgeLabels``, ...), and the plot panes for the traces surviving the round
trip intact.
"""

import unittest

import pytest

from testutils.http import VisdomHTTPTestCase
from testutils.payloads import content_args, window_args

pytestmark = pytest.mark.integration


class WindowTypeTestCase(VisdomHTTPTestCase):
    """Adds a create-and-read-back helper shared by every case below."""

    def create(self, args, eid="main"):
        """POST an args dict built by ``testutils.payloads``, return the pane."""
        resp = self.post_json("/events", dict(args, eid=eid))
        self.assertEqual(resp.code, 200, resp.body)
        win_id = resp.body.decode()
        pane = self.get_win_data(win_id, eid=eid)
        self.assertEqual(pane["id"], win_id)
        return pane

    def assert_plot_round_trip(self, trace, title):
        pane = self.create(window_args(data=[trace], layout={"title": title}))
        self.assertEqual(pane["type"], "plot")
        self.assertEqual(pane["content"]["data"], [trace])
        self.assertEqual(pane["content"]["layout"]["title"], title)
        return pane


class TestPlotPanes(WindowTypeTestCase):
    def test_scatter_survives_the_round_trip(self):
        self.assert_plot_round_trip(
            {"type": "scatter", "x": [1, 2, 3], "y": [4, 5, 6], "name": "t1"}, "scatter"
        )

    def test_scatter3d_survives_the_round_trip(self):
        self.assert_plot_round_trip(
            {"type": "scatter3d", "x": [1], "y": [2], "z": [3], "name": "3d"},
            "scatter3d",
        )

    def test_heatmap_survives_the_round_trip(self):
        self.assert_plot_round_trip(
            {
                "type": "heatmap",
                "z": [[1, 2], [3, 4]],
                "x": ["a", "b"],
                "y": ["c", "d"],
            },
            "heatmap",
        )

    def test_bar_survives_the_round_trip(self):
        self.assert_plot_round_trip(
            {"type": "bar", "x": ["a", "b"], "y": [10, 20], "name": "bars"}, "bar"
        )

    def test_parcoords_dimensions_are_preserved(self):
        trace = {
            "type": "parcoords",
            "dimensions": [
                {"label": "Learning Rate", "values": [0.01, 0.05, 0.1]},
                {"label": "Batch Size", "values": [16, 32, 64]},
                {"label": "Accuracy", "values": [85.0, 90.5, 78.2]},
            ],
            "line": {
                "color": [85.0, 90.5, 78.2],
                "colorscale": "Viridis",
                "showscale": True,
            },
        }
        pane = self.assert_plot_round_trip(trace, "parallel coords")
        dimensions = pane["content"]["data"][0]["dimensions"]
        self.assertEqual(
            [d["label"] for d in dimensions],
            ["Learning Rate", "Batch Size", "Accuracy"],
        )


class TestTextPane(WindowTypeTestCase):
    def _assert_text_round_trip(self, content):
        pane = self.create(content_args("text", content))
        self.assertEqual(pane["type"], "text")
        self.assertEqual(pane["content"], content)
        self.assertEqual(pane["command"], "window")

    def test_plain_text_is_stored_verbatim(self):
        self._assert_text_round_trip("hello")

    def test_html_in_text_is_stored_verbatim(self):
        self._assert_text_round_trip("<b>bold</b> & <i>italic</i>")


class TestMediaPanes(WindowTypeTestCase):
    def test_image_pane_stores_the_data_uri(self):
        pane = self.create(content_args("image", "data:image/png;base64,AAAA"))
        self.assertEqual(pane["type"], "image")
        self.assertEqual(pane["content"], "data:image/png;base64,AAAA")

    def test_image_history_pane_starts_a_one_entry_history(self):
        frame = {"src": "data:image/png;base64,BBB", "caption": "img1"}
        pane = self.create(content_args("image_history", frame))
        self.assertEqual(pane["type"], "image_history")
        self.assertEqual(pane["content"], [frame])
        self.assertEqual(pane["selected"], 0)
        self.assertTrue(pane["show_slider"])


class TestEmbeddingsPane(WindowTypeTestCase):
    def test_embeddings_pane_starts_with_no_previous_state(self):
        content = {
            "data": [[1, 2], [3, 4], [5, 6]],
            "labels": ["a", "b", "c"],
            "selected": None,
        }
        pane = self.create(content_args("embeddings", content))
        self.assertEqual(pane["type"], "embeddings")
        self.assertEqual(pane["content"]["data"], content["data"])
        self.assertEqual(pane["content"]["labels"], content["labels"])
        self.assertFalse(pane["content"]["has_previous"])
        self.assertEqual(pane["old_content"], [])


class TestNetworkPane(WindowTypeTestCase):
    def test_network_pane_takes_its_flags_from_opts(self):
        content = {
            "nodes": [{"id": 1, "label": "A"}, {"id": 2, "label": "B"}],
            "links": [{"source": 1, "target": 2}],
        }
        pane = self.create(content_args("network", content, opts={"directed": True}))
        self.assertEqual(pane["type"], "network")
        self.assertTrue(pane["directed"])
        self.assertEqual(pane["showEdgeLabels"], "hover")
        self.assertEqual(pane["showVertexLabels"], "hover")
        self.assertEqual(pane["content"], content)


class TestPropertiesPane(WindowTypeTestCase):
    def test_properties_pane_keeps_the_row_order(self):
        rows = [
            {"type": "text", "name": "prop1", "value": "val1"},
            {"type": "number", "name": "prop2", "value": 42},
            {"type": "button", "name": "prop3", "value": "click"},
        ]
        pane = self.create(content_args("properties", rows))
        self.assertEqual(pane["type"], "properties")
        self.assertEqual(pane["content"], rows)


class TestOptsAndPlacement(WindowTypeTestCase):
    def _assert_opt_flattened(self, key, value):
        pane = self.create(content_args("text", "opts", opts={key: value}))
        self.assertEqual(pane[key], value)

    def test_title_opt_is_flattened_onto_the_pane(self):
        self._assert_opt_flattened("title", "My Title")

    def test_width_opt_is_flattened_onto_the_pane(self):
        self._assert_opt_flattened("width", 400)

    def test_height_opt_is_flattened_onto_the_pane(self):
        self._assert_opt_flattened("height", 300)

    def test_pane_is_created_in_the_named_env(self):
        pane = self.create(content_args("text", "new env"), eid="brand_new_env")
        self.assertEqual(pane["content"], "new env")
        self.assertIn("brand_new_env", self.get_envs())


if __name__ == "__main__":
    unittest.main()
