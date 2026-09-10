#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Every accepted ``/update`` advances the pane's broadcast sequence number.

``version`` is the handshake behind incremental updates: the server broadcasts
``window_update`` carrying the pane's new version, and the frontend applies the
patch only when it reads ``pane.version + 1`` (``updateWindow`` in
``js/main.js``). A version that fails to move is not a cosmetic problem -- the
client discards the patch and re-requests the entire environment instead.

The bump used to live in ``update_window()``, which ``UpdateHandler.update()``
reaches for plot panes but returns before for text, image_history, plot_history
and table panes, and which the embeddings route never calls at all. Those four
types stayed at version 1 for the life of the pane while the server kept
broadcasting updates against them, so every ``vis.text()`` append cost a full
environment reload. These tests pin the counter to ``update_packet()`` -- the
one place an accepted update becomes a broadcast -- and assert it for every
pane type rather than for the single type that happened to work.
"""

import json

import pytest

from visdom.server.defaults import (
    DEFAULT_MAX_IMAGE_HISTORY,
    DEFAULT_MAX_OLD_CONTENT,
    DEFAULT_MAX_PLOT_HISTORY,
    DEFAULT_MAX_TEXT_LINES,
)
from visdom.server.handlers.web_handlers import UpdateHandler
from visdom.utils.shared_utils import get_rand_id

from testutils.fakes import FakeHandler

pytestmark = pytest.mark.unit


def _pane(ptype, **extra):
    pane = {
        "command": "window",
        "version": 1,
        "id": "win_{}".format(ptype),
        "title": ptype,
        "contentID": get_rand_id(),
        "type": ptype,
    }
    pane.update(extra)
    return pane


def _plot_pane():
    return _pane(
        "plot",
        content={
            "data": [{"type": "scatter", "x": [1], "y": [1], "name": "a"}],
            "layout": {},
        },
    )


def _text_pane():
    return _pane("text", content="line0")


def _image_history_pane():
    return _pane("image_history", content=[{"src": "img0"}], selected=0)


def _plot_history_pane():
    return _pane("plot_history", content=[{"data": [], "layout": {}}], selected=0)


def _table_pane():
    return _pane("table", content=[["a", "b"]], editable=True)


def _embeddings_pane():
    return _pane(
        "embeddings",
        content={"data": [[1, 2]], "selected": None, "has_previous": False},
        old_content=[],
    )


#: ``(id, pane factory, update args)`` for every type ``/update`` accepts.
#: ``table`` is here because the handler broadcasts for it even though the
#: update itself is refused -- a broadcast the client cannot reconcile is the
#: bug under test, whether or not the content changed.
PANE_CASES = [
    ("plot", _plot_pane, {"data": [{"type": "scatter", "x": [2], "y": [2]}]}),
    ("text", _text_pane, {"data": [{"content": "line1"}]}),
    (
        "image_history",
        _image_history_pane,
        {"data": [{"type": "image_history", "content": {"src": "img1"}}]},
    ),
    (
        "plot_history",
        _plot_history_pane,
        {"data": [{"type": "plot_history", "content": {"data": [], "layout": {}}}]},
    ),
    ("table", _table_pane, {"data": [{"content": [["c"]]}]}),
]


def _update_packet(pane, args):
    return UpdateHandler.update_packet(
        pane,
        args,
        DEFAULT_MAX_TEXT_LINES,
        DEFAULT_MAX_OLD_CONTENT,
        DEFAULT_MAX_IMAGE_HISTORY,
        DEFAULT_MAX_PLOT_HISTORY,
    )


@pytest.mark.parametrize(
    "name, build, args", PANE_CASES, ids=[c[0] for c in PANE_CASES]
)
def test_update_bumps_the_version(name, build, args):
    pane = build()
    updated, _ = _update_packet(pane, args)
    assert updated["version"] == 2


@pytest.mark.parametrize(
    "name, build, args", PANE_CASES, ids=[c[0] for c in PANE_CASES]
)
def test_repeated_updates_advance_by_one_each(name, build, args):
    pane = build()
    for expected in (2, 3, 4):
        pane, _ = _update_packet(pane, args)
        assert pane["version"] == expected


@pytest.mark.parametrize(
    "name, build, args", PANE_CASES, ids=[c[0] for c in PANE_CASES]
)
def test_the_patch_carries_the_new_version(name, build, args):
    """The client applies the diff, so the diff has to move its copy too.

    Without a ``/version`` op the browser's pane keeps the old number and the
    *next* update fails the ``version + 1`` check instead of this one.
    """
    pane = build()
    _, patch = _update_packet(pane, args)
    versions = [op for op in patch if op["path"] == "/version"]
    assert versions == [{"op": "replace", "path": "/version", "value": 2}]


def test_a_pane_without_a_version_is_not_a_crash():
    """Environments persisted before panes carried a version still update."""
    pane = _text_pane()
    del pane["version"]
    updated, _ = _update_packet(pane, {"data": [{"content": "line1"}]})
    assert updated["version"] == 2


# -- embeddings -------------------------------------------------------------
# Embeddings bypass ``update_packet`` for a hand-built patch, so they need the
# same assertions made against their own route.


ENTITY_SELECTED = {"data": {"update_type": "EntitySelected", "selected": 0}}
REGION_SELECTED = {"data": {"update_type": "RegionSelected", "points": [[3, 4]]}}


@pytest.mark.parametrize("args", [ENTITY_SELECTED, REGION_SELECTED])
def test_embeddings_update_bumps_the_version(args):
    pane = _embeddings_pane()
    UpdateHandler.update_embeddings_packet(pane, args, DEFAULT_MAX_OLD_CONTENT)
    assert pane["version"] == 2


@pytest.mark.parametrize("args", [ENTITY_SELECTED, REGION_SELECTED])
def test_embeddings_patch_carries_the_new_version(args):
    pane = _embeddings_pane()
    patch = UpdateHandler.update_embeddings_packet(pane, args, DEFAULT_MAX_OLD_CONTENT)
    assert {"op": "replace", "path": "/version", "value": 2} in patch


def test_an_unknown_embeddings_update_type_changes_nothing():
    """No patch, so no version to announce -- and nothing to broadcast."""
    pane = _embeddings_pane()
    patch = UpdateHandler.update_embeddings_packet(
        pane, {"data": {"update_type": "Nonsense"}}, DEFAULT_MAX_OLD_CONTENT
    )
    assert patch == []
    assert pane["version"] == 1


# -- what the subscriber actually receives ----------------------------------


def _broadcast(build, args, count=3):
    """Drive ``wrap_func`` ``count`` times; return the pane and what a sub saw.

    ``wrap_func`` sends the whole pane instead of a patch whenever the pane
    serialises smaller than its diff, so a given type may produce ``window`` or
    ``window_update`` messages. Both carry a version and both are returned.
    """
    pane = build()
    handler = FakeHandler(state={"main": {"jsons": {pane["id"]: pane}, "reload": {}}})
    sub = handler.add_sub(eid="main")
    for _ in range(count):
        UpdateHandler.wrap_func(handler, dict(args, win=pane["id"], eid="main"))
    return handler.state["main"]["jsons"][pane["id"]], sub.sent


@pytest.mark.parametrize(
    "name, build, args", PANE_CASES, ids=[c[0] for c in PANE_CASES]
)
def test_every_broadcast_carries_the_next_version(name, build, args):
    """The sequence the frontend checks against, asserted end to end.

    Whichever shape the broadcast takes, the versions it announces have to be
    the consecutive run starting one past where the pane began -- that is
    precisely the ``cmd.version == pane.version + 1`` ladder the client walks.
    """
    pane, sent = _broadcast(build, args)
    assert pane["version"] == 4
    assert [msg["version"] for msg in sent] == [2, 3, 4]


def test_an_unknown_embeddings_update_broadcasts_nothing():
    pane = _embeddings_pane()
    handler = FakeHandler(state={"main": {"jsons": {pane["id"]: pane}, "reload": {}}})
    sub = handler.add_sub(eid="main")
    UpdateHandler.wrap_func(
        handler,
        {"win": pane["id"], "eid": "main", "data": {"update_type": "Nonsense"}},
    )
    assert sub.messages == []
    assert handler.dirtied == []


def test_embeddings_broadcast_versions_are_consecutive():
    pane = _embeddings_pane()
    handler = FakeHandler(state={"main": {"jsons": {pane["id"]: pane}, "reload": {}}})
    sub = handler.add_sub(eid="main")
    for i in range(3):
        UpdateHandler.wrap_func(
            handler,
            {
                "win": pane["id"],
                "eid": "main",
                "data": {"update_type": "EntitySelected", "selected": i},
            },
        )
    assert [json.loads(m)["version"] for m in sub.messages] == [2, 3, 4]
