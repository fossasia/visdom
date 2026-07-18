import unittest

import numpy as np
import visdom

from visdom.server.handlers.web_handlers import UpdateHandler


class TestImageUpdateSelected(unittest.TestCase):
    def _pane(self, n=5):
        return {
            "type": "image_history",
            "content": [{"src": "img_{}".format(i)} for i in range(n)],
            "selected": 0,
        }

    def _args(self, index):
        return {"data": [{"type": "image_update_selected", "selected": index}]}

    def _plot_pane(self):
        return {
            "type": "plot",
            "content": {
                "data": [{"type": "scatter", "x": [1], "y": [2]}],
                "layout": {},
            },
        }

    def _update(self, pane, args):
        return UpdateHandler.update(pane, args, 500, 50, 4)

    def test_sets_index(self):
        p = self._update(self._pane(), self._args(3))
        self.assertEqual(p["selected"], 3)

    def test_empty_content_returns_unchanged(self):
        p = {"type": "image_history", "content": [], "selected": 0}
        result = self._update(p, self._args(2))
        self.assertEqual(result["selected"], 0)

    def test_clamps_negative(self):
        p = self._update(self._pane(), self._args(-5))
        self.assertEqual(p["selected"], 0)

    def test_clamps_over_bound(self):
        p = self._update(self._pane(n=3), self._args(99))
        self.assertEqual(p["selected"], 2)

    def test_rejects_fractional_index(self):
        with self.assertRaises(ValueError):
            self._update(self._pane(), self._args(1.5))

    def test_rejects_non_numeric_index(self):
        for bad_value in ["2", None]:
            with self.subTest(bad_value=bad_value):
                with self.assertRaises(TypeError):
                    self._update(self._pane(), self._args(bad_value))

    def test_server_rejects_bool_index(self):
        with self.assertRaises(TypeError):
            self._update(self._pane(), self._args(True))

    def test_client_rejects_bool_index(self):
        viz = visdom.Visdom(send=False, use_incoming_socket=False)
        with self.assertRaises(TypeError):
            viz.update_image_slider("win_a", True)

    def test_client_rejects_non_finite_float(self):
        viz = visdom.Visdom(send=False, use_incoming_socket=False)
        for bad_value in [float("inf"), float("-inf"), float("nan")]:
            with self.subTest(bad_value=bad_value):
                with self.assertRaises(ValueError):
                    viz.update_image_slider("win_a", bad_value)

    def test_client_payload_coerces_numpy_scalars(self):
        viz = visdom.Visdom(send=False, use_incoming_socket=False)
        msg, endpoint = viz.update_image_slider("win_a", np.int64(2))
        self.assertEqual(endpoint, "update")
        self.assertEqual(msg["win"], "win_a")
        self.assertEqual(msg["data"][0]["type"], "image_update_selected")
        self.assertEqual(msg["data"][0]["selected"], 2)
        self.assertIsInstance(msg["data"][0]["selected"], int)

    def test_client_payload_accepts_integral_float_scalars(self):
        viz = visdom.Visdom(send=False, use_incoming_socket=False)
        msg, endpoint = viz.update_image_slider("win_a", np.float32(2.0))
        self.assertEqual(endpoint, "update")
        self.assertEqual(msg["data"][0]["selected"], 2)

    def test_client_payload_rejects_fractional_float(self):
        viz = visdom.Visdom(send=False, use_incoming_socket=False)
        with self.assertRaises(ValueError):
            viz.update_image_slider("win_a", np.float32(2.5))

    def test_client_payload_rejects_non_numeric_values(self):
        viz = visdom.Visdom(send=False, use_incoming_socket=False)
        for bad_value in ["2", None]:
            with self.subTest(bad_value=bad_value):
                with self.assertRaises(TypeError):
                    viz.update_image_slider("win_a", bad_value)

    def test_wrap_func_rejects_non_image_history_windows(self):
        class DummyHandler:
            def __init__(self, pane):
                self.state = {"main": {"jsons": {"plot_win": pane}}}
                self.messages = []
                self.status = None

            def set_status(self, code):
                self.status = code

            def write(self, message):
                self.messages.append(message)

        handler = DummyHandler(self._plot_pane())
        UpdateHandler.wrap_func(
            handler,
            {
                "win": "plot_win",
                "eid": "main",
                "data": [{"type": "image_update_selected", "selected": 2}],
            },
        )
        self.assertEqual(handler.status, 400)
        self.assertEqual(handler.messages, ["win is not image_history; was plot"])

    def test_wrap_func_reports_invalid_slider_indices(self):
        class DummyHandler:
            def __init__(self, pane):
                self.state = {"main": {"jsons": {"image_win": pane}}}
                self.messages = []
                self.status = None
                self.max_text_lines = 500
                self.max_old_content = 50
                self.max_image_history = 4

            def set_status(self, code):
                self.status = code

            def write(self, message):
                self.messages.append(message)

        handler = DummyHandler(self._pane())
        UpdateHandler.wrap_func(
            handler,
            {
                "win": "image_win",
                "eid": "main",
                "data": [{"type": "image_update_selected", "selected": 1.5}],
            },
        )
        self.assertEqual(handler.status, 400)
        self.assertEqual(
            handler.messages,
            ["image slider index must be an integer, got 1.5"],
        )

    def test_client_payload_coerces_numpy_array_scalar(self):
        viz = visdom.Visdom(send=False, use_incoming_socket=False)
        msg, endpoint = viz.update_image_slider("win_a", np.array(2, dtype=np.int64))
        self.assertEqual(msg["data"][0]["selected"], 2)
        self.assertIsInstance(msg["data"][0]["selected"], int)

    def test_client_payload_rejects_numpy_array_multielement(self):
        viz = visdom.Visdom(send=False, use_incoming_socket=False)
        with self.assertRaises(TypeError):
            viz.update_image_slider("win_a", np.array([1, 2], dtype=np.int64))


if __name__ == "__main__":
    unittest.main()
