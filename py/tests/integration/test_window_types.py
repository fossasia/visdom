#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Every pane type created through ``POST /events``.

``window()`` dispatches on ``data[0]["type"]``: anything it does not recognise
as a visdom-native pane becomes a generic ``plot`` carrying the traces
untouched. Both halves of that split are asserted here -- the native panes for
the extra keys the server synthesises (``selected``, ``old_content``,
``showEdgeLabels``, ...), and the plot panes for the traces surviving the round
trip intact.
"""

import pytest

from testutils.payloads import content_args, window_args

pytestmark = pytest.mark.integration


def create(server, args, eid="main"):
    """POST an args dict built by ``testutils.payloads`` and read the pane back."""
    resp = server.post_json("/events", dict(args, eid=eid))
    assert resp.status_code == 200, resp.text
    pane = server.get_win_data(resp.text, eid=eid)
    assert pane["id"] == resp.text
    return pane


# -- Plot panes ---------------------------------------------------------------

PLOT_TRACES = {
    "scatter": {"type": "scatter", "x": [1, 2, 3], "y": [4, 5, 6], "name": "t1"},
    "scatter3d": {"type": "scatter3d", "x": [1], "y": [2], "z": [3], "name": "3d"},
    "heatmap": {
        "type": "heatmap",
        "z": [[1, 2], [3, 4]],
        "x": ["a", "b"],
        "y": ["c", "d"],
    },
    "bar": {"type": "bar", "x": ["a", "b"], "y": [10, 20], "name": "bars"},
}


@pytest.mark.parametrize("trace_type", sorted(PLOT_TRACES))
def test_plot_traces_survive_the_round_trip(visdom_server, trace_type):
    trace = PLOT_TRACES[trace_type]
    pane = create(
        visdom_server, window_args(data=[trace], layout={"title": trace_type})
    )
    assert pane["type"] == "plot"
    assert pane["content"]["data"] == [trace]
    assert pane["content"]["layout"]["title"] == trace_type


def test_parcoords_dimensions_are_preserved(visdom_server):
    trace = {
        "type": "parcoords",
        "dimensions": [
            {"label": "Learning Rate", "values": [0.01, 0.05, 0.1]},
            {"label": "Batch Size", "values": [16, 32, 64]},
            {"label": "Accuracy", "values": [85.0, 90.5, 78.2]},
        ],
        "line": {
            "color": [85.0, 90.5, 78.2],
            "colorscale": "Viridis",
            "showscale": True,
        },
    }
    pane = create(
        visdom_server, window_args(data=[trace], layout={"title": "parallel coords"})
    )
    assert pane["type"] == "plot"
    dimensions = pane["content"]["data"][0]["dimensions"]
    assert [d["label"] for d in dimensions] == [
        "Learning Rate",
        "Batch Size",
        "Accuracy",
    ]
    assert pane["content"]["layout"]["title"] == "parallel coords"


# -- Text ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    ["hello", "<b>bold</b> & <i>italic</i>"],
    ids=["plain", "html"],
)
def test_text_pane_stores_its_content_verbatim(visdom_server, content):
    pane = create(visdom_server, content_args("text", content))
    assert pane["type"] == "text"
    assert pane["content"] == content
    assert pane["command"] == "window"


# -- Media --------------------------------------------------------------------


def test_image_pane_stores_the_data_uri(visdom_server):
    pane = create(visdom_server, content_args("image", "data:image/png;base64,AAAA"))
    assert pane["type"] == "image"
    assert pane["content"] == "data:image/png;base64,AAAA"


def test_image_history_pane_starts_a_one_entry_history(visdom_server):
    frame = {"src": "data:image/png;base64,BBB", "caption": "img1"}
    pane = create(visdom_server, content_args("image_history", frame))
    assert pane["type"] == "image_history"
    assert pane["content"] == [frame]
    assert pane["selected"] == 0
    assert pane["show_slider"] is True


# -- Embeddings ---------------------------------------------------------------


def test_embeddings_pane_starts_with_no_previous_state(visdom_server):
    content = {
        "data": [[1, 2], [3, 4], [5, 6]],
        "labels": ["a", "b", "c"],
        "selected": None,
    }
    pane = create(visdom_server, content_args("embeddings", content))
    assert pane["type"] == "embeddings"
    assert pane["content"]["data"] == content["data"]
    assert pane["content"]["labels"] == content["labels"]
    assert pane["content"]["has_previous"] is False
    assert pane["old_content"] == []


# -- Network ------------------------------------------------------------------


def test_network_pane_takes_its_flags_from_opts(visdom_server):
    content = {
        "nodes": [{"id": 1, "label": "A"}, {"id": 2, "label": "B"}],
        "links": [{"source": 1, "target": 2}],
    }
    pane = create(
        visdom_server, content_args("network", content, opts={"directed": True})
    )
    assert pane["type"] == "network"
    assert pane["directed"] is True
    assert pane["showEdgeLabels"] == "hover"
    assert pane["showVertexLabels"] == "hover"
    assert pane["content"] == content


# -- Properties ---------------------------------------------------------------


def test_properties_pane_keeps_the_row_order(visdom_server):
    rows = [
        {"type": "text", "name": "prop1", "value": "val1"},
        {"type": "number", "name": "prop2", "value": 42},
        {"type": "button", "name": "prop3", "value": "click"},
    ]
    pane = create(visdom_server, content_args("properties", rows))
    assert pane["type"] == "properties"
    assert pane["content"] == rows


# -- Opts and environment placement -------------------------------------------


@pytest.mark.parametrize(
    "key,value", [("title", "My Title"), ("width", 400), ("height", 300)]
)
def test_opts_are_flattened_onto_the_pane(visdom_server, key, value):
    pane = create(visdom_server, content_args("text", "opts", opts={key: value}))
    assert pane[key] == value


def test_pane_is_created_in_the_named_env(visdom_server):
    pane = create(visdom_server, content_args("text", "new env"), eid="brand_new_env")
    assert pane["content"] == "new env"
    assert "brand_new_env" in visdom_server.get_envs()
