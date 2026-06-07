"""
Tests for plot_history (store_history support for scatter/line plots).

Covers the server-side update logic, window creation, and the
store_history + update mutual exclusion in the client.
"""

import unittest

from visdom.server.handlers.web_handlers import UpdateHandler
from visdom.utils.server_utils import window as make_window
from visdom.utils.shared_utils import get_rand_id


def _make_plot_history_window(frames=None):
    """Create a plot_history window with optional pre-existing frames."""
    if frames is None:
        frames = [{"data": [{"type": "scatter", "x": [1], "y": [1]}], "layout": {}}]
    return {
        "command": "window",
        "version": 1,
        "id": "win_phist",
        "title": "plot history",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": get_rand_id(),
        "content": list(frames),
        "selected": 0,
        "type": "plot_history",
        "show_slider": True,
        "i": 0,
    }


def _plot_history_append_args(frame=None):
    """Build args that append a new frame to plot_history."""
    if frame is None:
        frame = {"data": [{"type": "scatter", "x": [2], "y": [2]}], "layout": {}}
    return {"data": [{"type": "plot_history", "content": frame}]}


def _plot_update_selected_args(selected):
    """Build args that change the selected frame index."""
    return {"data": [{"type": "plot_update_selected", "selected": selected}]}


class TestPlotHistoryAppend(unittest.TestCase):
    """Appending frames to a plot_history window."""

    def test_append_single_frame(self):
        p = _make_plot_history_window()
        p = UpdateHandler.update(p, _plot_history_append_args())
        self.assertEqual(len(p["content"]), 2)
        self.assertEqual(p["selected"], 1)

    def test_append_multiple_frames(self):
        p = _make_plot_history_window()
        for i in range(5):
            frame = {"data": [{"type": "scatter", "x": [i], "y": [i]}], "layout": {}}
            p = UpdateHandler.update(p, _plot_history_append_args(frame))
        self.assertEqual(len(p["content"]), 6)
        self.assertEqual(p["selected"], 5)

    def test_selected_always_points_to_latest(self):
        p = _make_plot_history_window()
        for i in range(3):
            p = UpdateHandler.update(p, _plot_history_append_args())
        self.assertEqual(p["selected"], len(p["content"]) - 1)

    def test_appended_frame_content_preserved(self):
        p = _make_plot_history_window()
        frame = {
            "data": [{"type": "scatter", "x": [10, 20], "y": [30, 40]}],
            "layout": {"title": "frame2"},
            "caption": "second frame",
        }
        p = UpdateHandler.update(p, _plot_history_append_args(frame))
        self.assertEqual(p["content"][-1], frame)


class TestPlotHistoryUpdateSelected(unittest.TestCase):
    """Changing the selected frame via plot_update_selected."""

    def test_select_valid_index(self):
        frames = [
            {"data": [], "layout": {}},
            {"data": [], "layout": {}},
            {"data": [], "layout": {}},
        ]
        p = _make_plot_history_window(frames)
        p = UpdateHandler.update(p, _plot_update_selected_args(1))
        self.assertEqual(p["selected"], 1)

    def test_select_first_frame(self):
        frames = [{"data": [], "layout": {}} for _ in range(3)]
        p = _make_plot_history_window(frames)
        p["selected"] = 2
        p = UpdateHandler.update(p, _plot_update_selected_args(0))
        self.assertEqual(p["selected"], 0)

    def test_negative_index_clamped_to_zero(self):
        frames = [{"data": [], "layout": {}} for _ in range(3)]
        p = _make_plot_history_window(frames)
        p = UpdateHandler.update(p, _plot_update_selected_args(-5))
        self.assertEqual(p["selected"], 0)

    def test_overflow_index_clamped_to_last(self):
        frames = [{"data": [], "layout": {}} for _ in range(3)]
        p = _make_plot_history_window(frames)
        p = UpdateHandler.update(p, _plot_update_selected_args(100))
        self.assertEqual(p["selected"], 2)


class TestPlotHistoryWindowCreation(unittest.TestCase):
    """The server_utils.window() function should handle plot_history type."""

    def test_window_creates_plot_history_pane(self):
        frame = {"data": [{"type": "scatter", "x": [1], "y": [2]}], "layout": {}}
        args = {
            "data": [{"type": "plot_history", "content": frame}],
            "win": "test_win",
            "eid": "main",
            "opts": {"title": "Plot History", "show_slider": True},
        }
        p = make_window(args)
        self.assertEqual(p["type"], "plot_history")
        self.assertEqual(len(p["content"]), 1)
        self.assertEqual(p["content"][0], frame)
        self.assertEqual(p["selected"], 0)
        self.assertTrue(p["show_slider"])

    def test_window_show_slider_defaults_true(self):
        args = {
            "data": [{"type": "plot_history", "content": {"data": [], "layout": {}}}],
            "win": "w",
            "eid": "main",
            "opts": {"title": "t"},
        }
        p = make_window(args)
        self.assertTrue(p["show_slider"])


class TestStoreHistoryUpdateMutualExclusion(unittest.TestCase):
    """store_history=True and update parameter should not be used together."""

    def test_raises_with_store_history_and_update(self):
        from unittest.mock import patch, MagicMock
        from visdom import Visdom

        with patch.object(Visdom, "__init__", lambda self, **kw: None):
            vis = Visdom.__new__(Visdom)

        vis.win_exists = MagicMock(return_value=False)
        vis._send = MagicMock(return_value="win_id")

        with self.assertRaises(ValueError) as ctx:
            vis.scatter(
                X=[[1, 2], [3, 4]],
                opts={"store_history": True},
                update="append",
            )
        self.assertIn("store_history", str(ctx.exception))


class TestPlotHistoryDoesNotAffectOtherTypes(unittest.TestCase):
    """Existing types like image_history should still work correctly."""

    def test_image_history_unaffected(self):
        p = {
            "type": "image_history",
            "content": [{"src": "img1"}],
            "selected": 0,
            "contentID": get_rand_id(),
        }
        args = {"data": [{"type": "image_history", "content": {"src": "img2"}}]}
        p = UpdateHandler.update(p, args)
        self.assertEqual(len(p["content"]), 2)
        self.assertEqual(p["selected"], 1)


if __name__ == "__main__":
    unittest.main()
