"""
Tests for JSON patch generation via update_packet().
Verifies that window updates produce valid, applicable JSON patches.
"""

import copy
import unittest

import jsonpatch

from visdom.server.handlers.web_handlers import UpdateHandler
from visdom.server.defaults import (
    DEFAULT_MAX_IMAGE_HISTORY,
    DEFAULT_MAX_OLD_CONTENT,
    DEFAULT_MAX_TEXT_LINES,
)
from visdom.utils.shared_utils import get_rand_id

# Shorthand for the three cap arguments required by update_packet/update
_CAPS = (DEFAULT_MAX_TEXT_LINES, DEFAULT_MAX_OLD_CONTENT, DEFAULT_MAX_IMAGE_HISTORY)


def update_packet(p, args):
    """Wrapper that supplies the default cap arguments."""
    return UpdateHandler.update_packet(p, args, *_CAPS)


def make_text_window(content="hello"):
    return {
        "command": "window",
        "version": 1,
        "id": "win_text",
        "title": "text win",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": get_rand_id(),
        "content": content,
        "type": "text",
        "i": 0,
    }


def make_plot_window(traces=None):
    if traces is None:
        traces = [{"type": "scatter", "x": [1, 2], "y": [3, 4], "name": "t1"}]
    return {
        "command": "window",
        "version": 1,
        "id": "win_plot",
        "title": "plot win",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": get_rand_id(),
        "content": {
            "data": traces,
            "layout": {"title": "test"},
        },
        "type": "plot",
        "i": 0,
    }


def make_heatmap_window():
    return {
        "command": "window",
        "version": 1,
        "id": "win_heatmap",
        "title": "heatmap win",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": get_rand_id(),
        "content": {
            "data": [
                {
                    "type": "heatmap",
                    "z": [[1, 2], [3, 4]],
                    "x": ["a", "b"],
                    "y": ["c", "d"],
                }
            ],
            "layout": {"title": "heatmap"},
        },
        "type": "plot",
        "i": 0,
    }


def make_embeddings_window():
    return {
        "command": "window",
        "version": 1,
        "id": "win_emb",
        "title": "embeddings",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": get_rand_id(),
        "content": {
            "data": [[1, 2], [3, 4], [5, 6]],
            "labels": ["a", "b", "c"],
            "selected": None,
            "has_previous": False,
        },
        "type": "embeddings",
        "old_content": [],
        "i": 0,
    }


def make_image_history_window():
    return {
        "command": "window",
        "version": 1,
        "id": "win_imghist",
        "title": "image history",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": get_rand_id(),
        "content": [{"src": "data:image/png;base64,AAA", "caption": "img1"}],
        "selected": 0,
        "type": "image_history",
        "show_slider": True,
        "i": 0,
    }


class TestTextPatch(unittest.TestCase):
    def test_text_append_produces_content_replace(self):
        p = make_text_window("hello")
        old_p = copy.deepcopy(p)
        new_p, patch = update_packet(p, {"data": [{"content": "world"}]})
        self.assertEqual(new_p["content"], "hello<br>world")
        # Patch should contain a replace on /content
        content_ops = [op for op in patch if op["path"] == "/content"]
        self.assertTrue(len(content_ops) > 0)

    def test_text_capped_at_max_lines(self):
        p = make_text_window("line0")
        for i in range(1, 600):
            p, _ = update_packet(p, {"data": [{"content": f"line{i}"}]})
        lines = p["content"].split("<br>")
        self.assertEqual(len(lines), DEFAULT_MAX_TEXT_LINES)

    def test_text_patch_is_applicable(self):
        p = make_text_window("hello")
        old_p = copy.deepcopy(p)
        new_p, patch = update_packet(p, {"data": [{"content": "world"}]})
        # Apply patch to old state → should match new state
        patched = jsonpatch.apply_patch(old_p, patch)
        self.assertEqual(patched["content"], new_p["content"])


class TestPlotPatch(unittest.TestCase):
    def test_plot_append_produces_data_patch(self):
        p = make_plot_window()
        old_p = copy.deepcopy(p)
        new_p, patch = update_packet(
            p,
            {
                "data": [{"type": "scatter", "x": [5], "y": [6], "name": "t1"}],
                "name": "t1",
                "append": True,
            },
        )
        # x should be concatenated
        self.assertEqual(new_p["content"]["data"][0]["x"], [1, 2, 5])
        self.assertTrue(len(patch) > 0)

    def test_delete_trace_patch(self):
        traces = [
            {"type": "scatter", "x": [1], "y": [2], "name": "t1"},
            {"type": "scatter", "x": [3], "y": [4], "name": "t2"},
        ]
        p = make_plot_window(traces)
        old_p = copy.deepcopy(p)
        new_p, patch = update_packet(
            p,
            {"data": [{}], "name": "t1", "delete": True},
        )
        self.assertEqual(len(new_p["content"]["data"]), 1)
        self.assertEqual(new_p["content"]["data"][0]["name"], "t2")

    def test_inject_new_trace_patch(self):
        p = make_plot_window()
        new_p, patch = update_packet(
            p,
            {
                "data": [
                    {"type": "scatter", "x": [10], "y": [20], "name": "new_trace"}
                ],
                "name": "new_trace",
            },
        )
        self.assertEqual(len(new_p["content"]["data"]), 2)
        self.assertEqual(new_p["content"]["data"][1]["name"], "new_trace")


class TestHeatmapPatch(unittest.TestCase):
    def test_heatmap_append_row_patch(self):
        p = make_heatmap_window()
        old_p = copy.deepcopy(p)
        new_p, patch = update_packet(
            p,
            {
                "data": [{"type": "heatmap", "z": [[5, 6]], "x": None, "y": ["e"]}],
                "name": None,
                "updateDir": "appendRow",
            },
        )
        self.assertEqual(len(new_p["content"]["data"][0]["z"]), 3)
        self.assertTrue(len(patch) > 0)


class TestEmbeddingsPatch(unittest.TestCase):
    def test_entity_selected_patch(self):
        p = make_embeddings_window()
        old_p = copy.deepcopy(p)
        new_p, patch = update_packet(
            p,
            {"data": {"update_type": "EntitySelected", "selected": 2}},
        )
        self.assertEqual(new_p["content"]["selected"], 2)
        # Patch should be minimal — only selected and contentID changed
        paths_changed = {op["path"] for op in patch}
        self.assertIn("/content/selected", paths_changed)

    def test_old_content_capped(self):
        p = make_embeddings_window()
        for i in range(60):
            p, _ = update_packet(
                p, {"data": {"update_type": "RegionSelected", "points": [[i, i + 1]]}}
            )
        self.assertEqual(len(p["old_content"]), DEFAULT_MAX_OLD_CONTENT)

    def test_region_selected_patch(self):
        p = make_embeddings_window()
        new_p, patch = update_packet(
            p,
            {"data": {"update_type": "RegionSelected", "points": [[7, 8], [9, 10]]}},
        )
        self.assertTrue(new_p["content"]["has_previous"])
        self.assertEqual(new_p["content"]["data"], [[7, 8], [9, 10]])
        self.assertEqual(len(new_p["old_content"]), 1)


class TestImageHistoryPatch(unittest.TestCase):
    def test_image_history_append_patch(self):
        p = make_image_history_window()
        old_p = copy.deepcopy(p)
        new_p, patch = update_packet(
            p,
            {
                "data": [
                    {
                        "type": "image_history",
                        "content": {
                            "src": "data:image/png;base64,BBB",
                            "caption": "img2",
                        },
                    }
                ]
            },
        )
        self.assertEqual(len(new_p["content"]), 2)
        self.assertEqual(new_p["selected"], 1)

    def test_image_history_capped(self):
        p = make_image_history_window()
        for i in range(10):
            p, _ = update_packet(
                p,
                {
                    "data": [
                        {
                            "type": "image_history",
                            "content": {
                                "src": f"data:image/png;base64,IMG{i}",
                                "caption": f"img{i}",
                            },
                        }
                    ]
                },
            )
        self.assertEqual(len(p["content"]), DEFAULT_MAX_IMAGE_HISTORY)


class TestPatchGeneral(unittest.TestCase):
    def test_patch_always_updates_contentID(self):
        p = make_text_window("hello")
        old_id = p["contentID"]
        new_p, patch = update_packet(p, {"data": [{"content": "world"}]})
        self.assertNotEqual(new_p["contentID"], old_id)

    def test_patch_is_valid_jsonpatch_format(self):
        p = make_plot_window()
        old_p = copy.deepcopy(p)
        new_p, patch = update_packet(
            p,
            {
                "data": [{"type": "scatter", "x": [5], "y": [6], "name": "t1"}],
                "name": "t1",
                "append": True,
            },
        )
        # Every op should have "op" and "path" fields
        for op in patch:
            self.assertIn("op", op)
            self.assertIn("path", op)
            self.assertIn(
                op["op"], ["add", "remove", "replace", "move", "copy", "test"]
            )


if __name__ == "__main__":
    unittest.main()
