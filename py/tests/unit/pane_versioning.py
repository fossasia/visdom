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

The other half of the rule is that a version is only spent on an update that
was actually applied. ``update()`` declines several of them -- a ``/update``
aimed at a table pane, a slider move on a pane holding no frames, a heatmap
append whose shape or column names do not fit the plot -- and an unrecognised
embeddings ``update_type`` applies nothing either. Bumping for one of those
announces a revision that carries no change, so the second half of this file
pins the refusals: no bump, no patch, and nothing put on the wire.
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


def _heatmap(labels=False):
    """An unlabelled heatmap appends rows indefinitely.

    Passing ``labels`` gives the plot column names, which puts ``update()``
    into the branch that checks an append's names against the plot's -- the
    one that turns duplicates and mismatches away.
    """
    pane = _pane(
        "plot",
        content={
            "data": [
                {
                    "type": "heatmap",
                    "z": [[1, 2]],
                    "x": ["a", "b"] if labels else None,
                    "y": ["c"] if labels else None,
                    "name": "hm",
                }
            ],
            "layout": {},
        },
    )
    args = {
        "data": [
            {
                "type": "heatmap",
                "z": [[3, 4]],
                "x": None,
                "y": ["d"] if labels else None,
            }
        ],
        "updateDir": "appendRow",
        "append": True,
    }
    return pane, args


# The types ``UpdateHandler.wrap_func`` accepts and applies, one builder each.
# Embeddings are absent on purpose: they take the ``update_embeddings_packet``
# route and are covered separately below. So is ``table``, whose builder feeds
# the rejected-update cases instead -- ``update()`` refuses a ``/update`` on a
# table outright, so there is never a revision for it to announce.
BUILDERS = {
    "text": _text,
    "image_history": _image_history,
    "plot_history": _plot_history,
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


# -- Rejected updates --------------------------------------------------------


def _table_update():
    """``/update`` on a table: ``update()`` logs it and applies nothing."""
    return _table()


def _empty_image_slider():
    """A slider move on a pane holding no frames -- nothing to select."""
    pane = _pane("image_history", content=[], selected=0, show_slider=True)
    return pane, {"data": [{"type": "image_update_selected", "selected": 2}]}


def _duplicate_heatmap_labels():
    """An append carrying a column name the plot already has."""
    pane, args = _heatmap(labels=True)
    args["data"][0]["y"] = ["c"]
    return pane, args


def _mismatched_heatmap_row():
    """An append whose rows are wider than the plot's."""
    pane, args = _heatmap(labels=True)
    args["data"][0]["z"] = [[3, 4, 5]]
    return pane, args


def _unnamed_heatmap_append():
    """An append with no column names for a plot that has them."""
    pane, args = _heatmap(labels=True)
    args["data"][0]["y"] = None
    return pane, args


REJECTED = {
    "table": _table_update,
    "empty_image_slider": _empty_image_slider,
    "duplicate_heatmap_labels": _duplicate_heatmap_labels,
    "mismatched_heatmap_row": _mismatched_heatmap_row,
    "unnamed_heatmap_append": _unnamed_heatmap_append,
}


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_a_rejected_update_is_not_a_revision(case):
    """Nothing was applied, so there is no new state to number or to send."""
    pane, args = REJECTED[case]()
    before = copy.deepcopy(pane)
    pane, patch = _update_packet(pane, args)
    assert patch == []
    assert pane == before


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_repeated_rejections_never_advance_the_version(case):
    pane, args = REJECTED[case]()
    for _ in range(4):
        pane, _ = _update_packet(pane, args)
    assert pane["version"] == 1


def test_a_rejection_leaves_no_gap_in_the_sequence():
    """The accepted update after a refusal is the client's next number.

    A refusal that bumped would put the pane two ahead of the browser, and the
    frontend takes a patch only when it is exactly one ahead -- so the next
    real update would be dropped and the whole environment re-queried, which is
    the reload the bump exists to prevent.
    """
    pane, accepted = _heatmap()
    pane, _ = _update_packet(pane, accepted)
    assert pane["version"] == 2

    too_wide = copy.deepcopy(accepted)
    too_wide["data"][0]["z"] = [[1, 2, 3]]
    pane, patch = _update_packet(pane, too_wide)
    assert patch == []

    pane, patch = _update_packet(pane, accepted)
    assert pane["version"] == 3
    assert _versions_in(patch) == [3]


# -- What the subscriber is sent ---------------------------------------------
#
# ``wrap_func`` is driven directly here rather than ``update_packet``, because
# the empty patch is only half the fix: the handler also has to decline to
# broadcast it. A ``window_update`` carrying the version the client already
# holds fails the frontend's check just as a stale one does.


def _serve(handler, pane, win="win_0", eid="main"):
    """Put ``pane`` in the handler's state and return its window id."""
    pane["id"] = win
    handler.state[eid] = {"jsons": {win: pane}, "reload": {}}
    return win


def _update(handler, win, data, eid="main"):
    UpdateHandler.wrap_func(handler, {"win": win, "eid": eid, "data": data})


def test_a_rejected_update_is_not_broadcast(handler):
    sub = handler.add_sub()
    pane, args = _table()
    win = _serve(handler, pane)

    _update(handler, win, args["data"])

    assert sub.sent == []
    assert handler.dirtied == []
    assert handler.written == [win]


def test_an_unknown_embeddings_update_is_not_broadcast(handler):
    """The empty patch used to go out anyway, announcing an unmoved version."""
    sub = handler.add_sub()
    win = _serve(handler, _embeddings_pane())

    _update(handler, win, {"update_type": "Nonsense"})

    assert sub.sent == []
    assert handler.dirtied == []
    assert handler.written == [win]


def test_an_applied_embeddings_update_is_still_broadcast(handler):
    sub = handler.add_sub()
    win = _serve(handler, _embeddings_pane())

    _update(handler, win, {"update_type": "EntitySelected", "selected": 1})

    packet = sub.last("window_update")
    assert packet["version"] == 2
    assert {"op": "add", "path": "/version", "value": 2} in packet["content"]
    assert handler.dirtied == ["main"]


def test_a_refused_embeddings_update_leaves_no_gap(handler):
    """The versions a subscriber sees stay dense across a refusal."""
    sub = handler.add_sub()
    win = _serve(handler, _embeddings_pane())

    _update(handler, win, {"update_type": "EntitySelected", "selected": 1})
    _update(handler, win, {"update_type": "Nonsense"})
    _update(handler, win, {"update_type": "RegionSelected", "points": [[5, 6]]})

    versions = [
        msg["version"] for msg in sub.sent if msg.get("command") == "window_update"
    ]
    assert versions == [2, 3]
