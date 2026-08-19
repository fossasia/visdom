#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""In-memory growth caps on the panes that append rather than replace.

A long-running job appending to the same pane used to grow the server's state
without bound (#1320). Four pane fields are capped -- text content, embedding
undo history, image history and plot history -- and each keeps the *newest*
entries, since those are what the frontend shows. The caps are passed in rather
than read from ``defaults``, so these drive ``UpdateHandler`` directly with
small limits instead of appending five hundred times.
"""

from unittest.mock import MagicMock

import pytest

from visdom.server.defaults import (
    DEFAULT_MAX_IMAGE_HISTORY,
    DEFAULT_MAX_OLD_CONTENT,
    DEFAULT_MAX_PLOT_HISTORY,
    DEFAULT_MAX_TEXT_LINES,
)
from visdom.server.handlers.base_handlers import BaseHandler
from visdom.server.handlers.web_handlers import UpdateHandler
from visdom.utils.shared_utils import get_rand_id

pytestmark = pytest.mark.unit


def _pane(ptype, **extra):
    pane = {
        "command": "window",
        "version": 1,
        "id": "win_{}".format(ptype),
        "title": ptype,
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": get_rand_id(),
        "type": ptype,
        "i": 0,
    }
    pane.update(extra)
    return pane


def _text_pane(content="line0"):
    return _pane("text", content=content)


def _embeddings_pane(old_content=None):
    return _pane(
        "embeddings",
        content={
            "data": [[1, 2], [3, 4]],
            "labels": ["a", "b"],
            "selected": None,
            "has_previous": False,
        },
        old_content=[] if old_content is None else old_content,
    )


def _image_history_pane(images=None):
    if images is None:
        images = [{"src": "data:image/png;base64,AAA", "caption": "img0"}]
    return _pane(
        "image_history",
        content=list(images),
        selected=0,
        show_slider=True,
    )


def _update(
    p,
    args,
    max_text=DEFAULT_MAX_TEXT_LINES,
    max_old=DEFAULT_MAX_OLD_CONTENT,
    max_img=DEFAULT_MAX_IMAGE_HISTORY,
    max_plot=DEFAULT_MAX_PLOT_HISTORY,
):
    """Call ``UpdateHandler.update`` with explicit caps."""
    return UpdateHandler.update(p, args, max_text, max_old, max_img, max_plot)


def _update_embeddings(p, args, max_old=DEFAULT_MAX_OLD_CONTENT):
    """Call the embeddings update path with an explicit ``old_content`` cap.

    Embeddings never reach ``UpdateHandler.update``: the handler routes them to
    ``update_embeddings_packet`` first, which mutates the window in place and
    returns a JSON patch rather than the window.
    """
    UpdateHandler.update_embeddings_packet(p, args, max_old)
    return p


def _append_lines(count, cap, start="line0"):
    """Append ``count`` numbered lines to a text pane held at ``cap`` lines."""
    p = _text_pane(start)
    for i in range(1, count + 1):
        p = _update(p, {"data": [{"content": "line{}".format(i)}]}, max_text=cap)
    return p["content"].split("<br>")


def _append_images(count, cap):
    """Append ``count`` numbered frames to a history pane held at ``cap``."""
    p = _image_history_pane()
    for i in range(1, count + 1):
        args = {
            "data": [
                {
                    "type": "image_history",
                    "content": {
                        "src": "data:image/png;base64,img{}".format(i),
                        "caption": "img{}".format(i),
                    },
                }
            ]
        }
        p = _update(p, args, max_img=cap)
    return p


def _plot_history_pane(frames=None):
    if frames is None:
        frames = [{"data": [], "layout": {}, "caption": "frame0"}]
    return _pane(
        "plot_history",
        content=list(frames),
        selected=0,
        show_slider=True,
    )


def _append_frames(count, cap):
    """Append ``count`` numbered frames to a plot history held at ``cap``."""
    p = _plot_history_pane()
    for i in range(1, count + 1):
        args = {
            "data": [
                {
                    "type": "plot_history",
                    "content": {
                        "data": [{"type": "scatter", "x": [i], "y": [i]}],
                        "layout": {},
                        "caption": "frame{}".format(i),
                    },
                }
            ]
        }
        p = _update(p, args, max_plot=cap)
    return p


def _region_select(points):
    return {"data": {"update_type": "RegionSelected", "points": points}}


# -- Text -------------------------------------------------------------------


@pytest.mark.parametrize(
    "appends, cap, expected",
    [(1, 5, 2), (5, 6, 6), (4, 3, 3), (199, 10, 10)],
    ids=["under-cap", "at-cap", "over-cap", "long-run"],
)
def test_text_content_is_capped(appends, cap, expected):
    assert len(_append_lines(appends, cap)) == expected


def test_text_appends_join_with_a_line_break():
    assert _append_lines(1, 5, start="hello") == ["hello", "line1"]


def test_text_truncation_keeps_the_newest_line():
    assert _append_lines(4, 3)[-1] == "line4"


def test_text_truncation_drops_the_oldest_lines():
    lines = _append_lines(4, 3)
    assert "line0" not in lines
    assert "line1" not in lines


def test_default_text_cap():
    assert DEFAULT_MAX_TEXT_LINES == 500


# -- Embeddings undo history -------------------------------------------------


def test_region_select_stacks_the_replaced_points():
    p = _embeddings_pane()
    original = p["content"]["data"]
    p = _update_embeddings(p, _region_select([[10, 20]]), max_old=5)
    assert p["old_content"] == [original]
    assert p["content"]["has_previous"]


def test_old_content_under_the_cap_is_kept_whole():
    p = _embeddings_pane(old_content=[[[1, 2]], [[3, 4]]])
    p = _update_embeddings(p, _region_select([[5, 6]]), max_old=5)
    assert len(p["old_content"]) == 3


def test_old_content_truncation_keeps_the_newest_entry():
    p = _embeddings_pane(old_content=[[[i, i]] for i in range(3)])
    p = _update_embeddings(p, _region_select([[99, 99]]), max_old=3)
    assert len(p["old_content"]) == 3
    assert p["old_content"][-1] == [[1, 2], [3, 4]]


def test_repeated_region_selects_stay_bounded():
    p = _embeddings_pane()
    for i in range(50):
        p = _update_embeddings(p, _region_select([[i, i]]), max_old=5)
    assert len(p["old_content"]) == 5


def test_entity_select_does_not_grow_old_content():
    p = _embeddings_pane()
    args = {"data": {"update_type": "EntitySelected", "selected": 0}}
    p = _update_embeddings(p, args, max_old=5)
    assert p["old_content"] == []


def test_default_old_content_cap():
    assert DEFAULT_MAX_OLD_CONTENT == 50


# -- Image history -----------------------------------------------------------


@pytest.mark.parametrize(
    "appends, cap, expected",
    [(1, 4, 2), (2, 4, 3), (5, 3, 3), (199, 4, 4)],
    ids=["under-cap", "still-under-cap", "over-cap", "long-run"],
)
def test_image_history_is_capped(appends, cap, expected):
    assert len(_append_images(appends, cap)["content"]) == expected


def test_image_history_truncation_keeps_the_newest_frame():
    assert _append_images(5, 3)["content"][-1]["caption"] == "img5"


def test_image_history_truncation_drops_the_oldest_frames():
    captions = [img["caption"] for img in _append_images(5, 3)["content"]]
    assert "img0" not in captions
    assert "img1" not in captions


@pytest.mark.parametrize("cap", [1, 2, 4])
def test_selected_stays_a_valid_index_after_truncation(cap):
    p = _append_images(9, cap)
    assert 0 <= p["selected"] < len(p["content"])


def test_explicit_selection_is_unaffected_by_the_cap():
    images = [
        {"src": "data:image/png;base64,A", "caption": "img{}".format(i)}
        for i in range(3)
    ]
    p = _image_history_pane(images)
    p["selected"] = 2
    args = {"data": [{"type": "image_update_selected", "selected": 0}]}
    p = _update(p, args, max_img=4)
    assert p["selected"] == 0
    assert len(p["content"]) == 3


def test_default_image_history_cap():
    assert DEFAULT_MAX_IMAGE_HISTORY == 4


# -- Plot history ------------------------------------------------------------


@pytest.mark.parametrize(
    "appends, cap, expected",
    [(1, 4, 2), (2, 4, 3), (5, 3, 3), (999, 4, 4)],
    ids=["under-cap", "still-under-cap", "over-cap", "long-run"],
)
def test_plot_history_is_capped(appends, cap, expected):
    assert len(_append_frames(appends, cap)["content"]) == expected


def test_plot_history_truncation_keeps_the_newest_frame():
    assert _append_frames(5, 3)["content"][-1]["caption"] == "frame5"


def test_plot_history_truncation_drops_the_oldest_frames():
    captions = [frame["caption"] for frame in _append_frames(5, 3)["content"]]
    assert "frame0" not in captions
    assert "frame1" not in captions


@pytest.mark.parametrize("cap", [1, 2, 4])
def test_plot_selected_stays_a_valid_index_after_truncation(cap):
    p = _append_frames(9, cap)
    assert 0 <= p["selected"] < len(p["content"])


def test_explicit_frame_selection_is_unaffected_by_the_cap():
    frames = [
        {"data": [], "layout": {}, "caption": "frame{}".format(i)} for i in range(3)
    ]
    p = _plot_history_pane(frames)
    p["selected"] = 2
    args = {"data": [{"type": "plot_update_selected", "selected": 0}]}
    p = _update(p, args, max_plot=4)
    assert p["selected"] == 0
    assert len(p["content"]) == 3


def test_default_plot_history_cap():
    assert DEFAULT_MAX_PLOT_HISTORY == 4


# -- Handler wiring ----------------------------------------------------------


def test_handler_copies_the_caps_off_the_application():
    app = MagicMock()
    app.max_text_lines = 100
    app.max_old_content = 20
    app.max_image_history = 8
    app.max_plot_history = 6

    handler = MagicMock(spec=BaseHandler)
    BaseHandler.initialize(handler, app=app)

    assert handler.max_text_lines == 100
    assert handler.max_old_content == 20
    assert handler.max_image_history == 8
    assert handler.max_plot_history == 6
