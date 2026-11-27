#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the pane construction helpers in ``server_utils``.

``window()`` is the single dispatch point that turns an ``/events`` payload into
the pane dict the frontend renders, and ``update_window()`` is how every
subsequent ``/update`` mutates it. Both are pure, and both were previously
covered only indirectly through HTTP tests.
"""

from copy import deepcopy

import pytest

from visdom.utils.server_utils import update_window, window

from testutils.payloads import content_args, plot_data, window_args

pytestmark = pytest.mark.unit


def test_command_is_window():
    assert window(window_args())["command"] == "window"


def test_version_defaults_to_one():
    assert window(window_args())["version"] == 1


def test_version_is_taken_from_args():
    assert window(window_args(version=7))["version"] == 7


def test_supplied_win_is_used_as_id():
    assert window(window_args(win="my_win"))["id"] == "my_win"


def test_id_is_stringified():
    assert window(window_args(win=42))["id"] == "42"


@pytest.mark.parametrize(
    "set_win_to_none", [False, True], ids=["absent", "explicit-none"]
)
def test_missing_win_generates_an_id(set_win_to_none):
    args = window_args()
    if set_win_to_none:
        args["win"] = None
    assert window(args)["id"].startswith("window_")


def test_generated_ids_are_unique():
    assert window(window_args())["id"] != window(window_args())["id"]


def test_content_id_distinguishes_rebuilds():
    args = window_args(win="stable")
    assert window(args)["contentID"] != window(args)["contentID"]


def test_opts_populate_presentation_fields():
    p = window(
        window_args(
            opts={
                "title": "Loss",
                "width": 300,
                "height": 200,
                "comment": "run 3",
                "inflate": False,
            }
        )
    )
    assert p["title"] == "Loss"
    assert p["width"] == 300
    assert p["height"] == 200
    assert p["comment"] == "run 3"
    assert p["inflate"] is False


@pytest.mark.parametrize(
    "field,expected",
    [
        ("title", ""),
        ("comment", ""),
        ("inflate", True),
        ("width", None),
        ("height", None),
    ],
)
def test_presentation_defaults(field, expected):
    assert window(window_args())[field] == expected


def test_type_is_plot():
    assert window(window_args())["type"] == "plot"


def test_data_and_layout_are_nested_under_content():
    traces = [plot_data(), plot_data(trace_type="bar")]
    layout = {"title": "t", "showlegend": True}
    p = window(window_args(data=traces, layout=layout))
    assert p["content"]["data"] == traces
    assert p["content"]["layout"] == layout


def test_caption_defaults_to_none():
    assert window(window_args())["content"]["caption"] is None


def test_caption_comes_from_opts():
    assert (
        window(window_args(opts={"caption": "fig 1"}))["content"]["caption"] == "fig 1"
    )


def test_unknown_trace_type_is_still_a_plot():
    assert window(window_args(data=[{"type": "sunburst"}]))["type"] == "plot"


def test_named_type_without_content_is_not_special_cased():
    """``is_visdom_type`` keys off ``content``, not off the type name."""
    p = window(window_args(data=[{"type": "text"}]))
    assert p["type"] == "plot"
    assert p["content"]["data"] == [{"type": "text"}]


@pytest.mark.parametrize(
    "ptype,content",
    [
        ("image_history", "img_0"),
        ("plot_history", {"data": [plot_data()], "layout": {}}),
    ],
)
def test_history_content_is_wrapped_in_a_slider_list(ptype, content):
    p = window(content_args(ptype, content))
    assert p["type"] == ptype
    assert p["content"] == [content]
    assert p["selected"] == 0


def test_slider_shown_by_default():
    assert window(content_args("image_history", "i"))["show_slider"] is True


def test_slider_can_be_hidden():
    p = window(content_args("image_history", "i", opts={"show_slider": False}))
    assert p["show_slider"] is False


@pytest.mark.parametrize(
    "ptype,content",
    [
        ("text", "hello"),
        ("text", "<b>bold</b> & <i>italic</i>"),
        ("image", "data:image/png;base64,AAA"),
        ("properties", [{"type": "number", "name": "lr", "value": "0.1"}]),
    ],
)
def test_simple_content_is_stored_verbatim(ptype, content):
    p = window(content_args(ptype, content))
    assert p["type"] == ptype
    assert p["content"] == content


def test_no_slider_keys_on_simple_panes():
    p = window(content_args("text", "hello"))
    assert "selected" not in p
    assert "show_slider" not in p


@pytest.fixture
def network_content():
    return {"nodes": [{"id": 0}], "edges": []}


def test_network_type_and_content(network_content):
    p = window(content_args("network", network_content))
    assert p["type"] == "network"
    assert p["content"] == network_content


def test_network_label_and_direction_defaults(network_content):
    p = window(content_args("network", network_content))
    assert p["directed"] is False
    assert p["showEdgeLabels"] == "hover"
    assert p["showVertexLabels"] == "hover"


def test_network_opts_override_defaults(network_content):
    p = window(
        content_args(
            "network",
            network_content,
            opts={
                "directed": True,
                "showEdgeLabels": True,
                "showVertexLabels": False,
            },
        )
    )
    assert p["directed"] is True
    assert p["showEdgeLabels"] is True
    assert p["showVertexLabels"] is False


@pytest.fixture
def embeddings_content():
    return {"data": [[0.0, 1.0]], "labels": ["a"]}


def test_embeddings_type_and_content(embeddings_content):
    p = window(content_args("embeddings", embeddings_content))
    assert p["type"] == "embeddings"
    assert p["content"]["data"] == [[0.0, 1.0]]


def test_embeddings_history_starts_empty(embeddings_content):
    assert window(content_args("embeddings", embeddings_content))["old_content"] == []


@pytest.mark.parametrize("stale_flag", [False, True])
def test_embeddings_has_previous_is_always_reset(embeddings_content, stale_flag):
    """A stale flag from the client must not survive pane construction."""
    content = dict(embeddings_content, has_previous=stale_flag)
    assert (
        window(content_args("embeddings", content))["content"]["has_previous"] is False
    )


@pytest.fixture
def plot_pane():
    return window(window_args(layout={"title": "old", "showlegend": False}))


def test_layout_keys_are_merged(plot_pane):
    update_window(plot_pane, {"layout": {"title": "new"}})
    assert plot_pane["content"]["layout"]["title"] == "new"


def test_unmentioned_layout_keys_survive(plot_pane):
    update_window(plot_pane, {"layout": {"title": "new"}})
    assert plot_pane["content"]["layout"]["showlegend"] is False


def test_new_layout_keys_are_added(plot_pane):
    update_window(plot_pane, {"layout": {"xaxis": {"type": "log"}}})
    assert plot_pane["content"]["layout"]["xaxis"] == {"type": "log"}


def test_options_only_layout_update_preserves_nested_fields(plot_pane):
    layout = plot_pane["content"]["layout"]
    layout.update(
        xaxis={"range": [0, 5], "title": {"text": "old", "font": {"size": 18}}},
        margin={"l": 5, "r": 10, "t": 15, "b": 20},
    )
    update_window(
        plot_pane,
        {"layout": {"xaxis": {"title": {"text": "epoch"}}, "margin": {"l": 7}}},
    )
    assert layout["xaxis"] == {
        "range": [0, 5],
        "title": {"text": "epoch", "font": {"size": 18}},
    }
    assert layout["margin"] == {"l": 7, "r": 10, "t": 15, "b": 20}


def test_options_only_layout_update_replaces_range_array(plot_pane):
    layout = plot_pane["content"]["layout"]
    layout["xaxis"] = {"range": [0, 5], "title": {"text": "epoch"}}
    update_window(plot_pane, {"layout": {"xaxis": {"range": [2, 8]}}})
    assert layout["xaxis"] == {"range": [2, 8], "title": {"text": "epoch"}}


def test_none_window_options_preserve_existing_plot(capture_send, plot_pane):
    layout = plot_pane["content"]["layout"]
    layout.update(
        showlegend=True,
        xaxis={"range": [0, 5]},
        margin={"l": 5, "r": 10, "t": 15, "b": 20},
    )
    sent = capture_send(
        lambda v: v.update_window_opts(
            "w1", {"title": "new", "legend": None, "tight_layout": None}
        )
    )
    update_window(plot_pane, sent["payload"])
    assert layout == {
        "title": {"text": "new"},
        "showlegend": True,
        "xaxis": {"range": [0, 5]},
        "margin": {"l": 5, "r": 10, "t": 15, "b": 20},
    }


def test_content_update_keeps_layout_replacement_semantics(plot_pane):
    layout = plot_pane["content"]["layout"]
    layout["xaxis"] = {"range": [0, 5]}
    update_window(
        plot_pane,
        {"data": [plot_data()], "layout": {"xaxis": {"title": {"text": "new"}}}},
    )
    assert layout["xaxis"] == {"title": {"text": "new"}}


@pytest.mark.parametrize(
    "reset,expected",
    [
        ({"xaxis": {}}, {"xaxis": {}, "margin": {"l": 5}}),
        (
            {"xaxis": {"title": {}}},
            {"xaxis": {"range": [0, 5], "title": {}}, "margin": {"l": 5}},
        ),
        (
            {"margin": {}},
            {"xaxis": {"range": [0, 5], "title": {"text": "epoch"}}, "margin": {}},
        ),
    ],
)
def test_empty_layout_dict_explicitly_resets_object(
    capture_send, plot_pane, reset, expected
):
    plot_pane["content"]["layout"] = {
        "xaxis": {"range": [0, 5], "title": {"text": "epoch"}},
        "margin": {"l": 5},
    }
    sent = capture_send(
        lambda v: v.update_window_opts("w1", {"layoutopts": {"plotly": reset}})
    )
    update_window(plot_pane, sent["payload"])
    assert plot_pane["content"]["layout"] == expected


def test_none_nested_layout_fields_do_not_clear_axis(capture_send, plot_pane):
    plot_pane["content"]["layout"] = {"xaxis": {"range": [0, 5]}}
    sent = capture_send(
        lambda v: v.update_window_opts(
            "w1", {"layoutopts": {"plotly": {"xaxis": {"range": None}}}}
        )
    )
    update_window(plot_pane, sent["payload"])
    assert plot_pane["content"]["layout"] == {"xaxis": {"range": [0, 5]}}


@pytest.mark.parametrize(
    "initial",
    [{}, {"title": "old"}, {"title": {"text": "old", "font": {"size": 18}}}],
)
@pytest.mark.parametrize("title_update", [{"text": None}, {"font": {"size": None}}])
def test_raw_none_only_layout_dict_is_omitted(plot_pane, initial, title_update):
    plot_pane["content"]["layout"] = deepcopy(initial)
    update_window(plot_pane, {"layout": {"title": title_update}})
    assert plot_pane["content"]["layout"] == initial


def test_raw_layout_replacements_omit_none_and_keep_explicit_values(plot_pane):
    updates = {
        "title": {"text": None, "font": {"size": 18, "color": None}},
        "xaxis": {"range": None, "autorange": False},
        "margin": {"l": 0},
    }
    original = deepcopy(updates)
    update_window(plot_pane, {"layout": updates})
    assert plot_pane["content"]["layout"] == {
        "title": {"font": {"size": 18}},
        "showlegend": False,
        "xaxis": {"autorange": False},
        "margin": {"l": 0},
    }
    assert updates == original


@pytest.mark.parametrize("title_update", [{}, {"font": {}}, {"text": None, "font": {}}])
def test_raw_empty_dict_resets_survive_normalization(plot_pane, title_update):
    update_window(plot_pane, {"layout": {"title": title_update}})
    assert plot_pane["content"]["layout"]["title"] == (
        {} if not title_update else {"font": {}}
    )


@pytest.mark.parametrize("args", [{"layout": {"title": None}}, {}])
def test_layout_is_left_alone(plot_pane, args):
    update_window(plot_pane, args)
    assert plot_pane["content"]["layout"]["title"] == "old"


@pytest.fixture
def titled_pane():
    return window(window_args(opts={"title": "old"}))


def test_opts_are_written_to_the_pane_root(titled_pane):
    update_window(titled_pane, {"opts": {"title": "new", "width": 500}})
    assert titled_pane["title"] == "new"
    assert titled_pane["width"] == 500


def test_none_opt_values_are_ignored(titled_pane):
    update_window(titled_pane, {"opts": {"title": None}})
    assert titled_pane["title"] == "old"


def test_caption_is_routed_into_content(titled_pane):
    """``caption`` lives beside the plot data, not at the pane root."""
    update_window(titled_pane, {"opts": {"caption": "fig 2"}})
    assert titled_pane["content"]["caption"] == "fig 2"
    assert "caption" not in {k: v for k, v in titled_pane.items() if k != "content"}


def test_caption_is_skipped_when_content_is_not_a_dict():
    text_pane = window(content_args("text", "hello"))
    update_window(text_pane, {"opts": {"caption": "ignored"}})
    assert text_pane["content"] == "hello"


@pytest.mark.parametrize("args", [{"opts": {"title": "a"}}, {}])
def test_version_is_left_to_the_caller(titled_pane, args):
    """``update_window`` merges fields; it does not sequence the broadcast.

    Only some updates reach this helper -- ``UpdateHandler.update()`` returns
    before it for text, image_history, plot_history and table panes -- so
    bumping here left those types stuck at version 1 and made the frontend
    reload the whole environment on every update. The counter now moves in
    ``UpdateHandler.update_packet()``; see ``unit/pane_versions.py``.
    """
    update_window(titled_pane, args)
    assert titled_pane["version"] == 1


def test_returns_the_same_pane_object(titled_pane):
    assert update_window(titled_pane, {}) is titled_pane


@pytest.fixture
def two_trace_pane():
    return window(window_args(data=[plot_data(name="train"), plot_data(name="val")]))


def trace_names(pane):
    return [d.get("name") for d in pane["content"]["data"]]


@pytest.mark.parametrize(
    "legend,expected",
    [
        (["a", "b"], ["a", "b"]),
        (["a"], ["a", "val"]),
        (["a", "b", "c"], ["a", "b"]),
    ],
)
def test_legend_renames_traces_positionally(two_trace_pane, legend, expected):
    update_window(two_trace_pane, {"opts": {"legend": legend}})
    assert trace_names(two_trace_pane) == expected


@pytest.mark.parametrize(
    "name,legend,expected",
    [
        ("val", ["renamed"], ["train", "renamed"]),
        ("val", [], ["train", "val"]),
        ("missing", ["x"], ["train", "val"]),
    ],
)
def test_named_update_targets_one_trace(two_trace_pane, name, legend, expected):
    update_window(two_trace_pane, {"name": name, "opts": {"legend": legend}})
    assert trace_names(two_trace_pane) == expected
