#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""``POST /update`` for the panes that carry content rather than traces.

``UpdateHandler.update`` dispatches on ``p["type"]`` before it ever looks at
plot data, and the first three branches -- ``text``, ``image_history`` and the
separate ``update_embeddings_packet`` route -- each mutate the pane in a
different shape. Text concatenates, image history appends and moves a cursor,
and embeddings swap ``content["data"]`` while stacking the old value onto
``old_content``. All three are asserted here through a real HTTP round trip.
"""

import unittest

import pytest

from testutils.http import VisdomHTTPTestCase
from testutils.payloads import content_args

pytestmark = pytest.mark.integration


class TestTextUpdate(VisdomHTTPTestCase):
    """Text updates concatenate onto the existing content with ``<br>``."""

    def test_update_appends_after_a_line_break(self):
        win = self.create_text_window(content="hello")
        self.update(win, [{"type": "text", "content": "world"}])
        self.assertEqual(self.get_win_data(win)["content"], "hello<br>world")

    def test_repeated_updates_accumulate(self):
        win = self.create_text_window(content="a")
        self.update(win, [{"content": "b"}])
        self.update(win, [{"content": "c"}])
        self.assertEqual(self.get_win_data(win)["content"], "a<br>b<br>c")

    def test_update_leaves_the_pane_type_alone(self):
        win = self.create_text_window(content="a")
        self.update(win, [{"content": "b"}])
        self.assertEqual(self.get_win_data(win)["type"], "text")


class EmbeddingsTestCase(VisdomHTTPTestCase):
    """Creates a two-point embeddings pane for the selection tests below."""

    def create_embeddings(self, data=None, labels=None):
        content = {
            "data": [[1, 2], [3, 4]] if data is None else data,
            "labels": ["a", "b"] if labels is None else labels,
            "selected": None,
        }
        args = content_args("embeddings", content)
        return self.create_window(args["data"], layout=args["layout"])

    def select_entity(self, win, index):
        return self.update(win, {"update_type": "EntitySelected", "selected": index})

    def select_region(self, win, points):
        return self.update(win, {"update_type": "RegionSelected", "points": points})


class TestEmbeddingsUpdate(EmbeddingsTestCase):
    """``update_embeddings_packet`` handles both selection kinds in place."""

    def test_entity_selection_records_the_index(self):
        win = self.create_embeddings()
        self.select_entity(win, 1)
        self.assertEqual(self.get_win_data(win)["content"]["selected"], 1)

    def test_entity_selection_leaves_the_points_alone(self):
        win = self.create_embeddings()
        self.select_entity(win, 1)
        pane = self.get_win_data(win)
        self.assertEqual(pane["content"]["data"], [[1, 2], [3, 4]])
        self.assertEqual(pane["old_content"], [])

    def test_region_selection_replaces_the_points(self):
        win = self.create_embeddings()
        self.select_region(win, [[5, 6]])
        pane = self.get_win_data(win)
        self.assertEqual(pane["content"]["data"], [[5, 6]])
        self.assertTrue(pane["content"]["has_previous"])

    def test_region_selection_stacks_the_previous_points(self):
        win = self.create_embeddings()
        self.select_region(win, [[5, 6]])
        pane = self.get_win_data(win)
        self.assertEqual(pane["old_content"], [[[1, 2], [3, 4]]])

    def test_region_selection_clears_the_selected_entity(self):
        win = self.create_embeddings()
        self.select_entity(win, 1)
        self.select_region(win, [[5, 6]])
        self.assertIsNone(self.get_win_data(win)["content"]["selected"])

    def test_entity_selection_survives_a_preceding_region_selection(self):
        win = self.create_embeddings()
        self.select_region(win, [[5, 6]])
        self.select_entity(win, 0)
        pane = self.get_win_data(win)
        self.assertEqual(pane["content"]["selected"], 0)
        self.assertTrue(pane["content"]["has_previous"])

    def test_unknown_update_type_is_a_no_op(self):
        win = self.create_embeddings()
        resp = self.update(win, {"update_type": "NothingLikeThis"})
        self.assertEqual(resp.code, 200)
        self.assertEqual(self.get_win_data(win)["content"]["data"], [[1, 2], [3, 4]])


class ImageHistoryTestCase(VisdomHTTPTestCase):
    """Creates a single-frame image history pane and appends frames to it."""

    def create_image_history(self, caption="c0"):
        args = content_args(
            "image_history",
            {"src": "data:image/png;base64,{}".format(caption), "caption": caption},
        )
        return self.create_window(args["data"], layout=args["layout"])

    def append_image(self, win, caption):
        return self.update(
            win,
            [
                {
                    "type": "image_history",
                    "content": {
                        "src": "data:image/png;base64,{}".format(caption),
                        "caption": caption,
                    },
                }
            ],
        )

    def select_image(self, win, index):
        return self.update(win, [{"type": "image_update_selected", "selected": index}])


class TestImageHistoryUpdate(ImageHistoryTestCase):
    """Appends grow ``content`` and drag ``selected`` along with them."""

    def test_append_grows_the_history(self):
        win = self.create_image_history()
        self.append_image(win, "c1")
        pane = self.get_win_data(win)
        self.assertEqual(len(pane["content"]), 2)
        self.assertEqual(pane["content"][1]["caption"], "c1")

    def test_append_selects_the_newest_frame(self):
        win = self.create_image_history()
        self.append_image(win, "c1")
        self.append_image(win, "c2")
        pane = self.get_win_data(win)
        self.assertEqual(len(pane["content"]), 3)
        self.assertEqual(pane["selected"], 2)


class TestImageHistorySelection(ImageHistoryTestCase):
    """``image_update_selected`` clamps the requested index into range.

    The original of this file asserted only that ``selected`` was 0 or 1 after
    an append, which no implementation could fail. The real contract is the
    clamp in ``UpdateHandler.update``.
    """

    def test_selection_moves_the_cursor(self):
        win = self.create_image_history()
        self.append_image(win, "c1")
        self.select_image(win, 0)
        self.assertEqual(self.get_win_data(win)["selected"], 0)

    def test_selection_past_the_end_clamps_to_the_last_frame(self):
        win = self.create_image_history()
        self.append_image(win, "c1")
        self.select_image(win, 99)
        self.assertEqual(self.get_win_data(win)["selected"], 1)

    def test_negative_selection_clamps_to_the_first_frame(self):
        win = self.create_image_history()
        self.append_image(win, "c1")
        self.select_image(win, -5)
        self.assertEqual(self.get_win_data(win)["selected"], 0)

    def test_selection_does_not_change_the_history(self):
        win = self.create_image_history()
        self.append_image(win, "c1")
        self.select_image(win, 0)
        self.assertEqual(len(self.get_win_data(win)["content"]), 2)

    def test_selection_on_a_text_pane_is_rejected(self):
        win = self.create_text_window(content="not an image")
        resp = self.select_image(win, 0)
        self.assertEqual(resp.code, 400)
        self.assertIn(b"win is not image_history", resp.body)


if __name__ == "__main__":
    unittest.main()
