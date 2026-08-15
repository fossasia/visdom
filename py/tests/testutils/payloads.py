#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Builders for the request and storage payloads the server consumes.

Keeping these in one place stops each test file from reinventing a slightly
different pane shape, which is how the previous copies drifted apart.
"""


def env_payload(win_id="win_0", jsons=None, reload=None):
    """Environment as persisted by the DataStore: ``jsons`` plus ``reload``."""
    if jsons is None:
        jsons = {win_id: {"id": win_id}}
    return {"jsons": jsons, "reload": {} if reload is None else reload}


def plot_data(trace_type="scatter", x=None, y=None, name=None):
    """A single plotly trace as the client sends it."""
    trace = {
        "type": trace_type,
        "x": [1, 2, 3] if x is None else x,
        "y": [4, 5, 6] if y is None else y,
        "mode": "lines",
    }
    if name is not None:
        trace["name"] = name
    return trace


def window_args(
    data=None,
    layout=None,
    opts=None,
    win=None,
    eid=None,
    version=None,
):
    """Args dict accepted by ``server_utils.window`` and the ``/events`` route.

    ``data`` defaults to a single scatter trace, producing a generic ``plot``
    pane. Pass ``[{"type": "text", "content": "..."}]`` for a visdom-native
    pane type instead.
    """
    args = {
        "data": [plot_data()] if data is None else data,
        "layout": {} if layout is None else layout,
    }
    if opts is not None:
        args["opts"] = opts
    if win is not None:
        args["win"] = win
    if eid is not None:
        args["eid"] = eid
    if version is not None:
        args["version"] = version
    return args


def content_args(ptype, content, opts=None, win=None, eid=None):
    """Args for a visdom-native pane (``text``, ``image``, ``embeddings``, ...).

    These are distinguished from generic plots by carrying a ``content`` key
    inside ``data[0]``.
    """
    return window_args(
        data=[{"type": ptype, "content": content}],
        opts=opts,
        win=win,
        eid=eid,
    )


def embeddings_pane(win_id="win_0"):
    """A stored embeddings pane, as ``state[eid]["jsons"][win]`` holds it.

    ``old_content`` is the region-selection history the pane pops back through.
    """
    return {
        "id": win_id,
        "type": "embeddings",
        "content": {"data": [], "selected": None, "has_previous": False},
        "old_content": [],
        "contentID": "content_0",
    }


def table_pane(win_id="win_0"):
    """A stored, editable table pane."""
    return {
        "id": win_id,
        "type": "table",
        "editable": True,
        "content": {"headers": ["a", "b"], "rows": [["1", "2"]]},
        "contentID": "content_0",
    }
