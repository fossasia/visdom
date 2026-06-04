"""
Tests for tight_layout support in _opts2layout and _axisformat.

Verifies that tight_layout=True reduces margins, enables automargin
on axes, and that explicit margin overrides still take priority.
"""

import unittest

from visdom import _opts2layout, _axisformat, _axisformat3d


class TestOpts2LayoutDefaultMargins(unittest.TestCase):
    """Default margins (no tight_layout) should remain unchanged."""

    def test_default_2d_margins(self):
        layout = _opts2layout({}, is3d=False)
        self.assertEqual(layout["margin"]["l"], 60)
        self.assertEqual(layout["margin"]["r"], 60)
        self.assertEqual(layout["margin"]["t"], 60)
        self.assertEqual(layout["margin"]["b"], 60)

    def test_default_3d_margins(self):
        layout = _opts2layout({}, is3d=True)
        self.assertEqual(layout["margin"]["l"], 0)
        self.assertEqual(layout["margin"]["r"], 60)
        self.assertEqual(layout["margin"]["t"], 20)
        self.assertEqual(layout["margin"]["b"], 0)


class TestOpts2LayoutTightMargins(unittest.TestCase):
    """tight_layout=True should reduce margins to minimal values."""

    def test_tight_2d_margins(self):
        layout = _opts2layout({"tight_layout": True}, is3d=False)
        self.assertEqual(layout["margin"]["l"], 0)
        self.assertEqual(layout["margin"]["r"], 0)
        self.assertEqual(layout["margin"]["t"], 30)
        self.assertEqual(layout["margin"]["b"], 0)

    def test_tight_3d_left_and_bottom_already_zero(self):
        layout = _opts2layout({"tight_layout": True}, is3d=True)
        self.assertEqual(layout["margin"]["l"], 0)
        self.assertEqual(layout["margin"]["b"], 0)

    def test_tight_3d_top_stays_20(self):
        layout = _opts2layout({"tight_layout": True}, is3d=True)
        self.assertEqual(layout["margin"]["t"], 20)

    def test_tight_3d_right_becomes_zero(self):
        layout = _opts2layout({"tight_layout": True}, is3d=True)
        self.assertEqual(layout["margin"]["r"], 0)


class TestOpts2LayoutExplicitOverrides(unittest.TestCase):
    """Explicit margin opts should override both default and tight values."""

    def test_explicit_margins_override_defaults(self):
        opts = {
            "marginleft": 100,
            "marginright": 80,
            "margintop": 40,
            "marginbottom": 90,
        }
        layout = _opts2layout(opts, is3d=False)
        self.assertEqual(layout["margin"]["l"], 100)
        self.assertEqual(layout["margin"]["r"], 80)
        self.assertEqual(layout["margin"]["t"], 40)
        self.assertEqual(layout["margin"]["b"], 90)

    def test_explicit_margins_override_tight(self):
        opts = {
            "tight_layout": True,
            "marginleft": 50,
            "marginright": 25,
            "margintop": 10,
            "marginbottom": 15,
        }
        layout = _opts2layout(opts, is3d=False)
        self.assertEqual(layout["margin"]["l"], 50)
        self.assertEqual(layout["margin"]["r"], 25)
        self.assertEqual(layout["margin"]["t"], 10)
        self.assertEqual(layout["margin"]["b"], 15)

    def test_partial_override_with_tight(self):
        opts = {"tight_layout": True, "marginleft": 40}
        layout = _opts2layout(opts, is3d=False)
        self.assertEqual(layout["margin"]["l"], 40)
        self.assertEqual(layout["margin"]["r"], 0)
        self.assertEqual(layout["margin"]["t"], 30)
        self.assertEqual(layout["margin"]["b"], 0)


class TestOpts2LayoutFalseTight(unittest.TestCase):
    """tight_layout=False should behave same as not passing it."""

    def test_false_same_as_default(self):
        layout_default = _opts2layout({}, is3d=False)
        layout_false = _opts2layout({"tight_layout": False}, is3d=False)
        self.assertEqual(layout_default["margin"], layout_false["margin"])


class TestAxisFormatAutomargin(unittest.TestCase):
    """_axisformat should set automargin=True when tight_layout is enabled."""

    def test_automargin_enabled_with_tight(self):
        opts = {"tight_layout": True, "xlabel": "X Axis"}
        axis = _axisformat("x", opts)
        self.assertTrue(axis["automargin"])

    def test_automargin_enabled_on_y_axis(self):
        opts = {"tight_layout": True, "ylabel": "Y Axis"}
        axis = _axisformat("y", opts)
        self.assertTrue(axis["automargin"])

    def test_automargin_none_without_tight(self):
        opts = {"xlabel": "X Axis"}
        axis = _axisformat("x", opts)
        self.assertIsNone(axis["automargin"])

    def test_automargin_none_with_false_tight(self):
        opts = {"tight_layout": False, "xlabel": "X Axis"}
        axis = _axisformat("x", opts)
        self.assertIsNone(axis["automargin"])


class TestAxisFormat3dUnaffected(unittest.TestCase):
    """3D axes should not have automargin regardless of tight_layout."""

    def test_3d_axis_no_automargin_key(self):
        opts = {"tight_layout": True, "xlabel": "X"}
        axis = _axisformat3d("x", opts)
        self.assertNotIn("automargin", axis)

    def test_3d_axis_without_tight(self):
        opts = {"xlabel": "X"}
        axis = _axisformat3d("x", opts)
        self.assertNotIn("automargin", axis)


class TestAxisFormatReturnsNone(unittest.TestCase):
    """_axisformat returns None when no axis fields are set."""

    def test_no_axis_opts_returns_none(self):
        result = _axisformat("x", {})
        self.assertIsNone(result)

    def test_tight_alone_no_axis_returns_none(self):
        result = _axisformat("x", {"tight_layout": True})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
