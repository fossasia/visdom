#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""``/update`` requests that carry ``opts``/``layout`` but no ``data``.

This is the shape ``Visdom.update_window_opts()`` sends. Only plot panes ever
handled it; text, image_history, plot_history, table and embeddings panes
indexed ``args["data"]`` unconditionally and answered HTTP 500.
"""

import copy

import pytest
import tornado.web

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


def _image_pane():
    return _pane("image", content={"src": "img0", "caption": None})


PANE_CASES = [
    ("plot", _plot_pane),
    ("text", _text_pane),
    ("image_history", _image_history_pane),
    ("plot_history", _plot_history_pane),
    ("table", _table_pane),
    ("embeddings", _embeddings_pane),
]

CONTENT_PRESERVING_CASES = [case for case in PANE_CASES if case[0] != "plot"]

OPTS = {"title": "renamed", "width": 400}
LAYOUT = {"title": {"text": "renamed"}, "margin": {"l": 60, "r": 60}}


def _opts_only(pane, **extra):
    handler = FakeHandler(state={"main": {"jsons": {pane["id"]: pane}, "reload": {}}})
    sub = handler.add_sub(eid="main")
    args = {"win": pane["id"], "eid": "main"}
    args.update(extra)
    UpdateHandler.wrap_func(handler, args)
    return handler, sub


@pytest.mark.parametrize("name, build", PANE_CASES, ids=[c[0] for c in PANE_CASES])
def test_opts_reach_the_pane(name, build):
    pane = build()
    _opts_only(pane, layout=copy.deepcopy(LAYOUT), opts=dict(OPTS))
    assert pane["title"] == "renamed"
    assert pane["width"] == 400


@pytest.mark.parametrize("name, build", PANE_CASES, ids=[c[0] for c in PANE_CASES])
def test_the_update_is_broadcast_with_the_next_version(name, build):
    pane = build()
    handler, sub = _opts_only(pane, layout=copy.deepcopy(LAYOUT), opts=dict(OPTS))
    assert pane["version"] == 2
    assert [msg["version"] for msg in sub.sent] == [2]
    assert handler.dirtied == ["main"]


@pytest.mark.parametrize(
    "name, build",
    CONTENT_PRESERVING_CASES,
    ids=[c[0] for c in CONTENT_PRESERVING_CASES],
)
def test_the_content_is_left_alone(name, build):
    pane = build()
    before = copy.deepcopy(pane["content"])
    _opts_only(pane, layout=copy.deepcopy(LAYOUT), opts=dict(OPTS))
    assert pane["content"] == before


def test_a_plot_pane_still_takes_the_layout():
    pane = _plot_pane()
    _opts_only(pane, layout=copy.deepcopy(LAYOUT), opts=dict(OPTS))
    assert pane["content"]["layout"]["title"] == {"text": "renamed"}
    assert pane["content"]["data"] == [
        {"type": "scatter", "x": [1], "y": [1], "name": "a"}
    ]


def test_a_legend_opt_does_not_reach_a_pane_without_traces():
    pane = _text_pane()
    _opts_only(pane, opts={"title": "renamed", "legend": ["a", "b"]})
    assert pane["title"] == "renamed"
    assert pane["content"] == "line0"


def test_a_legend_opt_still_renames_plot_traces():
    pane = _plot_pane()
    _opts_only(pane, opts={"legend": ["b"]})
    assert pane["content"]["data"][0]["name"] == "b"


def test_an_empty_data_list_is_treated_as_opts_only():
    pane = _text_pane()
    _opts_only(pane, data=[], opts=dict(OPTS))
    assert pane["title"] == "renamed"
    assert pane["content"] == "line0"


def test_a_pane_type_that_cannot_be_updated_is_reported():
    pane = _image_pane()
    handler, sub = _opts_only(pane, layout=copy.deepcopy(LAYOUT), opts=dict(OPTS))
    assert "win is not scatter" in handler.body
    assert "was image" in handler.body
    assert sub.sent == []
    assert handler.dirtied == []


def test_a_bar_pane_still_reports_its_trace_type():
    pane = _pane(
        "plot",
        content={"data": [{"type": "bar", "x": ["a"], "y": [1]}], "layout": {}},
    )
    handler, _ = _opts_only(pane, opts=dict(OPTS))
    assert "was bar" in handler.body


def test_a_named_update_without_data_is_a_client_error():
    pane = _plot_pane()
    with pytest.raises(tornado.web.HTTPError) as excinfo:
        _opts_only(pane, name="a", opts=dict(OPTS))
    assert excinfo.value.status_code == 400
