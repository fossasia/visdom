#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""``POST /update`` for plot panes -- heatmaps, traces, layout and opts.

Once ``UpdateHandler.update`` is past the content panes it works on
``p["content"]["data"]``, and which branch runs depends on how many traces the
``name`` argument selects: none injects a trace, exactly one heatmap takes the
``updateDir`` path, and anything else falls through to the positional trace
update. Every one of those branches is driven here over HTTP.
"""

import unittest

import pytest

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


class PlotUpdateTestCase(VisdomHTTPTestCase):
    """Creates the two plot shapes the update paths distinguish between."""

    def create_heatmap(self, z=None, x=None, y=None):
        return self.create_window(
            [
                {
                    "type": "heatmap",
                    "z": [[1, 2], [3, 4]] if z is None else z,
                    "x": ["a", "b"] if x is None else x,
                    "y": ["c", "d"] if y is None else y,
                }
            ],
            layout={"title": "hm"},
        )

    def create_scatter(self, name="t1", x=None, y=None):
        return self.create_window(
            [
                {
                    "type": "scatter",
                    "x": [1, 2] if x is None else x,
                    "y": [3, 4] if y is None else y,
                    "name": name,
                }
            ],
            layout={"title": "scatter"},
        )

    def update_heatmap(self, win, z, update_dir, x=None, y=None):
        """Mirror the client: ``append`` is set for every directional update.

        ``Visdom.heatmap`` derives it from ``updateDir`` (``__init__.py:3006``)
        and it is load-bearing -- without it the opts loop at the end of the
        heatmap branch overwrites the labels it just extended.
        """
        return self.update(
            win,
            [{"type": "heatmap", "z": z, "x": x, "y": y}],
            name=None,
            updateDir=update_dir,
            append=update_dir != "replace",
        )

    def traces(self, win):
        return self.get_win_data(win)["content"]["data"]

    def heatmap_z(self, win):
        return self.traces(win)[0]["z"]


class TestHeatmapRowUpdates(PlotUpdateTestCase):
    """``appendRow`` and ``prependRow`` grow ``z`` along the y axis."""

    def test_append_row_adds_to_the_bottom(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[5, 6]], "appendRow", y=["e"])
        z = self.heatmap_z(win)
        self.assertEqual(len(z), 3)
        self.assertEqual(z[2], [5, 6])

    def test_append_row_extends_the_row_labels(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[5, 6]], "appendRow", y=["e"])
        self.assertEqual(self.traces(win)[0]["y"], ["c", "d", "e"])

    def test_prepend_row_adds_to_the_top(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[5, 6]], "prependRow", y=["e"])
        z = self.heatmap_z(win)
        self.assertEqual(len(z), 3)
        self.assertEqual(z[0], [5, 6])

    def test_prepend_row_extends_the_row_labels(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[5, 6]], "prependRow", y=["e"])
        self.assertEqual(self.traces(win)[0]["y"], ["e", "c", "d"])


class TestHeatmapColumnUpdates(PlotUpdateTestCase):
    """``appendColumn`` and ``prependColumn`` grow every row of ``z``."""

    def test_append_column_adds_to_the_right(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[7], [8]], "appendColumn", x=["e"])
        z = self.heatmap_z(win)
        self.assertEqual(len(z[0]), 3)
        self.assertEqual([row[2] for row in z], [7, 8])

    def test_prepend_column_adds_to_the_left(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[7], [8]], "prependColumn", x=["e"])
        z = self.heatmap_z(win)
        self.assertEqual(len(z[0]), 3)
        self.assertEqual([row[0] for row in z], [7, 8])

    def test_column_update_extends_the_column_labels(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[7], [8]], "appendColumn", x=["e"])
        self.assertEqual(self.traces(win)[0]["x"], ["a", "b", "e"])


class TestHeatmapReplace(PlotUpdateTestCase):
    """``replace`` swaps the matrix outright, dimensions and all."""

    def test_replace_swaps_the_matrix(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[9]], "replace", x=["only"], y=["one"])
        self.assertEqual(self.heatmap_z(win), [[9]])

    def test_replace_swaps_the_labels(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[9]], "replace", x=["only"], y=["one"])
        trace = self.traces(win)[0]
        self.assertEqual(trace["x"], ["only"])
        self.assertEqual(trace["y"], ["one"])


class TestHeatmapMismatch(PlotUpdateTestCase):
    """A shape or label conflict logs and leaves the plot untouched."""

    def test_wrong_column_count_is_a_no_op(self):
        win = self.create_heatmap()
        resp = self.update_heatmap(win, [[5, 6, 7]], "appendRow", y=["e"])
        self.assertEqual(resp.code, 200)
        self.assertEqual(self.heatmap_z(win), [[1, 2], [3, 4]])

    def test_wrong_row_count_is_a_no_op(self):
        win = self.create_heatmap()
        resp = self.update_heatmap(win, [[7]], "appendColumn", x=["e"])
        self.assertEqual(resp.code, 200)
        self.assertEqual(self.heatmap_z(win), [[1, 2], [3, 4]])

    def test_duplicate_labels_are_a_no_op(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[5, 6]], "appendRow", y=["c"])
        self.assertEqual(self.heatmap_z(win), [[1, 2], [3, 4]])

    def test_missing_labels_are_a_no_op(self):
        win = self.create_heatmap()
        self.update_heatmap(win, [[5, 6]], "appendRow", y=None)
        self.assertEqual(self.heatmap_z(win), [[1, 2], [3, 4]])


class TestTraceUpdates(PlotUpdateTestCase):
    """A ``name`` selects which traces the update applies to."""

    def create_two_traces(self):
        return self.create_window(
            [
                {"type": "scatter", "x": [1], "y": [2], "name": "t1"},
                {"type": "scatter", "x": [3], "y": [4], "name": "t2"},
            ],
            layout={"title": "multi"},
        )

    def test_named_update_replaces_the_trace(self):
        win = self.create_scatter()
        self.update(
            win,
            [{"type": "scatter", "x": [10, 20], "y": [30, 40], "name": "t1"}],
            name="t1",
            append=False,
        )
        self.assertEqual(self.traces(win)[0]["x"], [10, 20])

    def test_named_update_appends_to_the_trace(self):
        win = self.create_scatter()
        self.update(
            win,
            [{"type": "scatter", "x": [5], "y": [6], "name": "t1"}],
            name="t1",
            append=True,
        )
        trace = self.traces(win)[0]
        self.assertEqual(trace["x"], [1, 2, 5])
        self.assertEqual(trace["y"], [3, 4, 6])

    def test_delete_removes_only_the_named_trace(self):
        win = self.create_two_traces()
        self.update(win, [{}], name="t1", delete=True)
        remaining = self.traces(win)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["name"], "t2")

    def test_an_unknown_name_injects_a_new_trace(self):
        win = self.create_scatter()
        self.update(
            win,
            [{"type": "scatter", "x": [10], "y": [20], "name": "new_trace"}],
            name="new_trace",
        )
        traces = self.traces(win)
        self.assertEqual(len(traces), 2)
        self.assertEqual(traces[1]["name"], "new_trace")
        self.assertEqual(traces[1]["x"], [10])

    def test_a_named_update_carrying_several_entries_is_rejected(self):
        win = self.create_scatter()
        resp = self.update(
            win,
            [
                {"type": "scatter", "x": [5], "y": [6], "name": "t1"},
                {"type": "scatter", "x": [7], "y": [8], "name": "t1"},
            ],
            name="t1",
        )
        self.assertEqual(resp.code, 400)


class TestMarkerUpdates(PlotUpdateTestCase):
    """Marker colours concatenate alongside the points they belong to."""

    def create_coloured_scatter(self, colors):
        return self.create_window(
            [
                {
                    "type": "scatter",
                    "x": [1],
                    "y": [2],
                    "name": "t1",
                    "marker": {"color": colors},
                }
            ],
            layout={"title": "markers"},
        )

    def append_colour(self, win, color, append=True):
        return self.update(
            win,
            [
                {
                    "type": "scatter",
                    "x": [3],
                    "y": [4],
                    "name": "t1",
                    "marker": {"color": [color]},
                }
            ],
            name="t1",
            append=append,
        )

    def test_append_concatenates_the_colours(self):
        win = self.create_coloured_scatter(["red"])
        self.append_colour(win, "blue")
        self.assertEqual(self.traces(win)[0]["marker"]["color"], ["red", "blue"])

    def test_replace_swaps_the_colours(self):
        win = self.create_coloured_scatter(["red"])
        self.append_colour(win, "blue", append=False)
        self.assertEqual(self.traces(win)[0]["marker"]["color"], ["blue"])


class TestLayoutAndOptsUpdates(PlotUpdateTestCase):
    """An update with no ``data`` still applies the layout and opts."""

    def test_layout_only_update_changes_the_title(self):
        win = self.create_scatter()
        self.update(win, None, layout={"title": "new title"})
        pane = self.get_win_data(win)
        self.assertEqual(pane["content"]["layout"]["title"], "new title")

    def test_layout_only_update_bumps_the_version(self):
        win = self.create_scatter()
        self.assertEqual(self.get_win_data(win)["version"], 1)
        self.update(win, None, layout={"title": "new title"})
        self.assertEqual(self.get_win_data(win)["version"], 2)

    def test_opts_legend_renames_the_trace(self):
        win = self.create_scatter()
        self.update(win, None, opts={"legend": ["renamed_trace"]})
        self.assertEqual(self.traces(win)[0]["name"], "renamed_trace")


class TestCategoricalXUpdate(PlotUpdateTestCase):
    """A categorical x axis must survive the all-missing-points check.

    That check exists to skip a trace whose points are all None/NaN/Inf. Only
    numbers can be either, so handing a label to ``math.isnan`` used to raise
    ``TypeError`` and answer 500.
    """

    def create_categorical(self):
        return self.create_scatter(x=["a", "b"], y=[1, 2])

    def test_appending_to_a_categorical_axis_succeeds(self):
        win = self.create_categorical()
        resp = self.update(
            win,
            [{"type": "scatter", "x": ["c"], "y": [3], "name": "t1"}],
            name="t1",
            append=True,
        )
        self.assertEqual(resp.code, 200, resp.body)

    def test_appending_to_a_categorical_axis_keeps_the_labels(self):
        win = self.create_categorical()
        self.update(
            win,
            [{"type": "scatter", "x": ["c"], "y": [3], "name": "t1"}],
            name="t1",
            append=True,
        )
        trace = self.traces(win)[0]
        self.assertEqual(trace["x"], ["a", "b", "c"])
        self.assertEqual(trace["y"], [1, 2, 3])

    def test_a_wholly_missing_numeric_update_is_still_skipped(self):
        win = self.create_scatter()
        self.update(
            win,
            [{"type": "scatter", "x": [None, None], "y": [9, 9], "name": "t1"}],
            name="t1",
            append=False,
        )
        self.assertEqual(self.traces(win)[0]["x"], [1, 2])


class TestEmptyDataUpdate(PlotUpdateTestCase):
    """Updates carrying fewer data entries than the plot has traces.

    Each of these indexed into ``data`` without checking its length first and
    answered 500 with an ``IndexError``.
    """

    def test_an_empty_data_list_applies_the_layout(self):
        win = self.create_scatter()
        resp = self.update(win, [], layout={"title": "new title"})
        self.assertEqual(resp.code, 200, resp.body)
        pane = self.get_win_data(win)
        self.assertEqual(pane["content"]["layout"]["title"], "new title")

    def test_an_empty_data_list_leaves_the_traces_alone(self):
        win = self.create_scatter()
        self.update(win, [], layout={"title": "new title"})
        self.assertEqual(self.traces(win)[0]["x"], [1, 2])

    def test_a_trace_can_be_injected_into_an_emptied_plot(self):
        win = self.create_scatter()
        self.update(win, [{}], name="t1", delete=True)
        self.assertEqual(self.traces(win), [])

        resp = self.update(
            win,
            [{"type": "scatter", "x": [7], "y": [8], "name": "t2"}],
            name="t2",
        )
        self.assertEqual(resp.code, 200, resp.body)
        traces = self.traces(win)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["name"], "t2")
        self.assertEqual(traces[0]["x"], [7])

    def test_an_unnamed_delete_still_empties_the_plot(self):
        """``Visdom.heatmap(update="remove")`` names no trace.

        It posts ``data: []`` with ``delete`` set (``__init__.py:3008``), which
        the empty-data shortcut above must not mistake for an opts-only update.
        """
        win = self.create_heatmap()
        resp = self.update(win, [], name=None, delete=True)
        self.assertEqual(resp.code, 200, resp.body)
        self.assertEqual(self.traces(win), [])

    def test_an_unnamed_update_may_cover_only_the_first_traces(self):
        win = self.create_window(
            [
                {"type": "scatter", "x": [1], "y": [2], "name": "t1"},
                {"type": "scatter", "x": [3], "y": [4], "name": "t2"},
            ],
            layout={"title": "multi"},
        )
        resp = self.update(
            win,
            [{"type": "scatter", "x": [9], "y": [9]}],
            append=True,
        )
        self.assertEqual(resp.code, 200, resp.body)
        traces = self.traces(win)
        self.assertEqual(traces[0]["x"], [1, 9])
        self.assertEqual(traces[1]["x"], [3])


class TestUnsupportedUpdate(PlotUpdateTestCase):
    """Only a handful of pane types accept ``/update`` at all."""

    def test_a_bar_pane_reports_the_type_it_is(self):
        win = self.create_window(
            [{"type": "bar", "x": ["a"], "y": [1], "name": "b1"}],
            layout={"title": "bar"},
        )
        resp = self.update(
            win,
            [{"type": "bar", "x": ["b"], "y": [2], "name": "b1"}],
            name="b1",
        )
        self.assertIn(b"win is not scatter", resp.body)
        self.assertIn(b"was bar", resp.body)

    def test_an_update_to_a_missing_window_is_reported(self):
        resp = self.update("no_such_win", [{"type": "scatter", "x": [1], "y": [2]}])
        self.assertEqual(resp.body, b"win does not exist")


if __name__ == "__main__":
    unittest.main()
