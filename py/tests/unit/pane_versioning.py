#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""``version`` rises once per accepted ``/update``, for every pane type.

The frontend applies a broadcast patch only when ``cmd.version`` is exactly one
ahead of the pane it already holds (``js/main.js``, ``updateWindow``); anything
else makes it drop the patch and re-query the whole environment. That contract
held for plot panes alone, because the bump lived in ``update_window()`` and
``UpdateHandler.update`` returns before reaching it for text, image history,
plot history and tables -- and embeddings never reach it at all, having their
own packet builder. Those five types sat at version 1 update after update, so
the comparison was permanently ``1 == 2`` and the incremental protocol was
dead for the most common panes in the library.

So the assertions here are per pane type rather than per branch: the bump now
sits in ``update_packet``, and what needs pinning is that no dispatch arm can
skip it. Each type is also checked for the ``/version`` op in the patch it
broadcasts, since a server-side bump the patch does not carry desynchronises
the frontend exactly as badly as no bump at all.
"""

import copy

import pytest

from visdom.server.defaults import (
    DEFAULT_MAX_IMAGE_HISTORY,
    DEFAULT_MAX_OLD_CONTENT,
    DEFAULT_MAX_PLOT_HISTORY,
    DEFAULT_MAX_TEXT_LINES,
)
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


def _update_packet(p, args):
    """One ``/update`` through the handler, with the production caps."""
    return UpdateHandler.update_packet(
        p,
        copy.deepcopy(args),
        DEFAULT_MAX_TEXT_LINES,
        DEFAULT_MAX_OLD_CONTENT,
        DEFAULT_MAX_IMAGE_HISTORY,
        DEFAULT_MAX_PLOT_HISTORY,
    )


def _text():
    return _pane("text", content="line0"), {"data": [{"content": "line1"}]}


def _image_history():
    pane = _pane(
        "image_history",
        content=[{"src": "data:image/png;base64,AAA", "caption": "img0"}],
        selected=0,
        show_slider=True,
    )
    args = {
        "data": [
            {
                "type": "image_history",
                "content": {
                    "src": "data:image/png;base64,BBB",
                    "caption": "img1",
                },
            }
        ]
    }
    return pane, args


def _plot_history():
    pane = _pane(
        "plot_history",
        content=[{"data": [], "layout": {}, "caption": "frame0"}],
        selected=0,
        show_slider=True,
    )
    args = {
        "data": [
            {
                "type": "plot_history",
                "content": {
                    "data": [{"type": "scatter", "x": [1], "y": [1]}],
                    "layout": {},
                    "caption": "frame1",
                },
            }
        ]
    }
    return pane, args


def _table():
    pane = _pane("table", content=[["a"]], editable=True)
    return pane, {"data": [{"type": "table", "content": [["b"]]}]}


def _scatter():
    pane = _pane(
        "plot",
        content={
            "data": [{"type": "scatter", "x": [1], "y": [1], "name": "t1"}],
            "layout": {},
        },
    )
    args = {
        "data": [{"type": "scatter", "x": [2], "y": [2], "name": "t1"}],
        "name": "t1",
        "append": True,
    }
    return pane, args


def _heatmap():
    pane = _pane(
        "plot",
        content={
            "data": [
                {
                    "type": "heatmap",
                    "z": [[1, 2]],
                    "x": ["a", "b"],
                    "y": ["c"],
                    "name": "hm",
                }
            ],
            "layout": {},
        },
    )
    args = {
        "data": [{"type": "heatmap", "z": [[3, 4]], "x": None, "y": ["d"]}],
        "updateDir": "appendRow",
        "append": True,
    }
    return pane, args


# The types ``UpdateHandler.wrap_func`` accepts, one builder each. Embeddings
# are absent on purpose: they take the ``update_embeddings_packet`` route and
# are covered separately below.
BUILDERS = {
    "text": _text,
    "image_history": _image_history,
    "plot_history": _plot_history,
    "table": _table,
    "scatter": _scatter,
    "heatmap": _heatmap,
}


def _embeddings_pane():
    return _pane(
        "embeddings",
        content={
            "data": [[1, 2], [3, 4]],
            "labels": ["a", "b"],
            "selected": None,
            "has_previous": False,
        },
        old_content=[],
    )


def _versions_in(patch):
    return [op["value"] for op in patch if op.get("path") == "/version"]


# -- Every pane type bumps ---------------------------------------------------


@pytest.mark.parametrize("ptype", sorted(BUILDERS))
def test_one_update_bumps_the_version(ptype):
    pane, args = BUILDERS[ptype]()
    pane, _ = _update_packet(pane, args)
    assert pane["version"] == 2


@pytest.mark.parametrize("ptype", sorted(BUILDERS))
def test_repeated_updates_bump_once_each(ptype):
    """Four updates, four bumps -- the frontend's check allows no gaps."""
    pane, args = BUILDERS[ptype]()
    for expected in (2, 3, 4, 5):
        pane, _ = _update_packet(pane, args)
        assert pane["version"] == expected


@pytest.mark.parametrize("ptype", sorted(BUILDERS))
def test_the_patch_carries_the_new_version(ptype):
    """The broadcast patch has to move the frontend's copy along with it.

    A bump the patch leaves out desynchronises the two sides on the very next
    update, which is the same full reload the bump exists to avoid.
    """
    pane, args = BUILDERS[ptype]()
    pane, patch = _update_packet(pane, args)
    assert _versions_in(patch) == [pane["version"]]


@pytest.mark.parametrize("ptype", sorted(BUILDERS))
def test_a_pane_without_a_version_is_given_one(ptype):
    """Envs saved before panes carried a version must not raise ``KeyError``."""
    pane, args = BUILDERS[ptype]()
    del pane["version"]
    pane, _ = _update_packet(pane, args)
    assert pane["version"] == 2


# -- Embeddings --------------------------------------------------------------


def test_entity_selection_bumps_the_version():
    pane = _embeddings_pane()
    UpdateHandler.update_embeddings_packet(
        pane,
        {"data": {"update_type": "EntitySelected", "selected": 1}},
        DEFAULT_MAX_OLD_CONTENT,
    )
    assert pane["version"] == 2


def test_region_selection_bumps_the_version():
    pane = _embeddings_pane()
    UpdateHandler.update_embeddings_packet(
        pane,
        {"data": {"update_type": "RegionSelected", "points": [[5, 6]]}},
        DEFAULT_MAX_OLD_CONTENT,
    )
    assert pane["version"] == 2


@pytest.mark.parametrize(
    "args",
    [
        {"data": {"update_type": "EntitySelected", "selected": 1}},
        {"data": {"update_type": "RegionSelected", "points": [[5, 6]]}},
    ],
    ids=["entity", "region"],
)
def test_the_embeddings_patch_carries_the_new_version(args):
    pane = _embeddings_pane()
    patch = UpdateHandler.update_embeddings_packet(pane, args, DEFAULT_MAX_OLD_CONTENT)
    assert _versions_in(patch) == [pane["version"]]


def test_an_unknown_embeddings_update_leaves_the_version_alone():
    """Nothing was applied, so there is no revision to announce."""
    pane = _embeddings_pane()
    patch = UpdateHandler.update_embeddings_packet(
        pane, {"data": {"update_type": "Nonsense"}}, DEFAULT_MAX_OLD_CONTENT
    )
    assert patch == []
    assert pane["version"] == 1
