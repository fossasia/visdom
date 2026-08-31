#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the client's content panes and its env/window management.

Everything here runs against the ``offline_client`` fixture, so no server and
no sockets are involved. The methods split in two on how they treat what
``_send`` hands back, and the tests follow that split:

* **Payload builders** return ``_send``'s value untouched, so the
  ``capture_send`` fixture can intercept the message. ``text``, ``properties``,
  ``table``, ``html_table``, ``embeddings``, ``learning_curve``,
  ``update_window_opts`` and the window/env writes are asserted this way.
* **Reply parsers** feed the response through ``json.loads`` or compare it
  against a literal, so ``capture_send`` cannot be used — it would hand them a
  ``(msg, endpoint)`` tuple and ``json.loads`` would choke on it. ``win_exists``,
  ``get_env_list``, ``get_env_state`` and ``delete_envs`` patch ``_send`` with a
  canned reply instead.

Two behaviours pinned here are current, not desired:

* ``properties`` documents five property types and validates none of them. A
  malformed entry reaches the browser unchallenged.
* ``register_event_handler`` asserts on ``use_socket``, so ``embeddings`` raises
  on a client that has no incoming socket unless
  ``opts.register_embedding_events`` is False. The default is True, which makes
  the common offline case the failing one.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
import pytest

pytestmark = pytest.mark.unit

requires_assertions = pytest.mark.skipif(
    not __debug__, reason="assert-based validation is stripped under python -O"
)


def block(sent):
    """The single content block of a captured payload."""
    return sent["payload"]["data"][0]


def replies(client, value):
    """Patch ``_send`` to answer with ``value`` and record the calls."""
    return patch.object(client, "_send", return_value=value)


def echoes(client):
    """Patch ``_send`` to hand back the ``(msg, endpoint)`` it would have posted."""
    return patch.object(
        client, "_send", side_effect=lambda msg, endpoint="events", **_: (msg, endpoint)
    )


@contextmanager
def posted(client):
    """Yield the message the transport under ``_send`` actually received.

    Only ``_handle_post`` is replaced, so ``_send`` itself still runs and its own
    ``eid`` handling is exercised rather than mocked away.
    """
    captured = {}

    def capture(url, data=None):
        captured.update(json.loads(data))
        return True

    with patch.object(client, "_handle_post", side_effect=capture):
        yield captured


def sends_to(send, endpoint):
    """Messages a patched ``_send`` received for one endpoint.

    An update through ``line`` also probes ``win_exists``, so the raw call list
    holds more than the sends under test.
    """
    return [
        call[0][0]
        for call in send.call_args_list
        if call[1].get("endpoint", "events") == endpoint
    ]


# ------------------------------------------------------------------ text ----


def test_text_sends_a_text_block_to_events(capture_send):
    sent = capture_send(lambda v: v.text("hello"))
    assert sent["endpoint"] == "events"
    assert block(sent) == {"content": "hello", "type": "text"}


def test_text_append_switches_endpoint_to_update(capture_send):
    sent = capture_send(lambda v: v.text("more", win="w1", append=True))
    assert sent["endpoint"] == "update"
    assert sent["payload"]["win"] == "w1"


def test_text_routes_win_env_and_opts(capture_send):
    sent = capture_send(lambda v: v.text("hi", win="w1", env="e1", opts={"title": "T"}))
    assert sent["payload"]["win"] == "w1"
    assert sent["payload"]["eid"] == "e1"
    assert sent["payload"]["opts"] == {"title": "T"}


def test_text_defaults_opts_to_an_empty_dict(capture_send):
    sent = capture_send(lambda v: v.text("hi"))
    assert sent["payload"]["opts"] == {}
    assert sent["payload"]["win"] is None
    assert sent["payload"]["eid"] is None


def test_text_passes_an_unrecognized_opt_through(capture_send):
    """``_assert_opts`` type-checks the opts it knows; it does not gate keys."""
    sent = capture_send(lambda v: v.text("hi", opts={"not_an_opt": 1}))
    assert sent["payload"]["opts"]["not_an_opt"] == 1


@requires_assertions
def test_text_rejects_a_mistyped_known_opt(capture_send):
    with pytest.raises(AssertionError):
        capture_send(lambda v: v.text("hi", opts={"colormap": 7}))


# ------------------------------------------------------------ properties ----


def test_properties_wraps_the_rows_verbatim(capture_send):
    rows = [
        {"type": "text", "name": "Text input", "value": "initial"},
        {"type": "number", "name": "Number input", "value": "12"},
        {"type": "button", "name": "Button", "value": "Start"},
        {"type": "checkbox", "name": "Checkbox", "value": True},
        {"type": "select", "name": "Select", "value": 1, "values": ["R", "G", "B"]},
    ]
    sent = capture_send(lambda v: v.properties(rows))
    assert sent["endpoint"] == "events"
    assert block(sent)["type"] == "properties"
    assert block(sent)["content"] == rows


def test_properties_does_not_validate_the_rows(capture_send):
    """Pinned: no type checking, so a malformed row reaches the browser."""
    sent = capture_send(lambda v: v.properties([{"type": "bogus", "value": object}]))
    assert block(sent)["content"][0]["type"] == "bogus"


def test_properties_routes_win_and_env(capture_send):
    sent = capture_send(lambda v: v.properties([], win="w1", env="e1"))
    assert sent["payload"]["win"] == "w1"
    assert sent["payload"]["eid"] == "e1"


# ----------------------------------------------------------------- table ----


def test_table_sends_headers_and_rows_as_a_native_pane(capture_send):
    """The pane carries structured data, not a rendered HTML string."""
    sent = capture_send(lambda v: v.table([[1, 2], [3, 4]], headers=["a", "b"]))
    assert block(sent)["type"] == "table"
    assert block(sent)["content"] == {
        "headers": ["a", "b"],
        "rows": [[1, 2], [3, 4]],
    }


def test_table_passes_markup_through_as_data(capture_send):
    """Cells are data, so markup is carried verbatim rather than escaped.

    The old HTML table escaped on the way out because it built the markup
    itself. Escaping now belongs to the frontend that renders the pane, and
    doing it here as well would double-escape every angle bracket.
    """
    sent = capture_send(
        lambda v: v.table([["<script>x</script>"]], headers=["<b>h</b>"])
    )
    assert block(sent)["content"] == {
        "headers": ["<b>h</b>"],
        "rows": [["<script>x</script>"]],
    }


def test_table_accepts_an_empty_body(capture_send):
    """Headers alone build a table with no rows."""
    sent = capture_send(lambda v: v.table([], headers=["a"]))
    assert block(sent)["content"] == {"headers": ["a"], "rows": []}


def test_table_normalizes_tuple_rows_to_lists(capture_send):
    sent = capture_send(lambda v: v.table([("x", "y")], headers=["a", "b"]))
    assert block(sent)["content"]["rows"] == [["x", "y"]]


def test_table_derives_headers_from_dict_rows(capture_send):
    """A list of dicts needs no headers -- the first row's keys supply them."""
    sent = capture_send(lambda v: v.table([{"a": 1, "b": 2}, {"a": 3, "b": 4}]))
    assert block(sent)["content"] == {
        "headers": ["a", "b"],
        "rows": [[1, 2], [3, 4]],
    }


def test_table_headers_select_and_order_dict_columns(capture_send):
    """Explicit headers reorder the dict columns and drop the rest."""
    sent = capture_send(
        lambda v: v.table([{"a": 1, "b": 2, "c": 3}], headers=["c", "a"])
    )
    assert block(sent)["content"]["rows"] == [[3, 1]]


def test_table_fills_missing_dict_keys_with_blanks(capture_send):
    sent = capture_send(lambda v: v.table([{"a": 1}, {"b": 2}], headers=["a", "b"]))
    assert block(sent)["content"]["rows"] == [[1, ""], ["", 2]]


def test_table_coerces_numpy_cells_to_native_types(capture_send):
    """numpy scalars are not JSON-serializable, so they are unwrapped here."""
    sent = capture_send(
        lambda v: v.table([[np.int64(1), np.float32(2.5)]], headers=["a", "b"])
    )
    rows = block(sent)["content"]["rows"]
    assert rows == [[1, 2.5]]
    assert [type(cell) for cell in rows[0]] == [int, float]


# ------------------------------------------------------------ html_table ----


def test_html_table_renders_headers_and_rows_as_html(capture_send):
    sent = capture_send(lambda v: v.html_table([[1, 2], [3, 4]], ["a", "b"]))
    html = block(sent)["content"]
    assert block(sent)["type"] == "text"
    assert "<th>a</th><th>b</th>" in html
    assert "<tr><td>1</td><td>2</td></tr>" in html
    assert "<tr><td>3</td><td>4</td></tr>" in html
    assert "class='visdom-table'" in html


def test_html_table_escapes_markup_in_cells_and_headers(capture_send):
    """This one builds the markup itself, so it must escape on the way out."""
    sent = capture_send(lambda v: v.html_table([["<script>x</script>"]], ["<b>h</b>"]))
    html = block(sent)["content"]
    assert "&lt;b&gt;h&lt;/b&gt;" in html
    assert "<script>" not in html


def test_html_table_accepts_an_empty_body(capture_send):
    sent = capture_send(lambda v: v.html_table([], ["a"]))
    assert "<tbody></tbody>" in block(sent)["content"]


def test_html_table_accepts_tuple_rows(capture_send):
    sent = capture_send(lambda v: v.html_table([("x", "y")], ["a", "b"]))
    assert "<td>x</td><td>y</td>" in block(sent)["content"]


@requires_assertions
@pytest.mark.parametrize(
    "data,headers",
    [
        ([["x"]], "a"),
        ("x", ["a"]),
        (["x"], ["a"]),
        ([["x"]], ["a", "b"]),
        ([["x"]], None),
        ([], None),
        ([{"a": 1}, ["b"]], None),
    ],
    ids=[
        "headers_not_list",
        "data_not_list",
        "row_not_sequence",
        "width_mismatch",
        "list_rows_without_headers",
        "neither_data_nor_headers",
        "mixed_dict_and_list_rows",
    ],
)
def test_table_rejects_malformed_input(capture_send, data, headers):
    with pytest.raises(AssertionError):
        capture_send(lambda v: v.table(data, headers=headers))


@pytest.mark.parametrize(
    "headers,data",
    [
        ("a", [["x"]]),
        (["a"], "x"),
        (["a"], ["x"]),
        (["a", "b"], [["x"]]),
    ],
    ids=["headers_not_list", "data_not_list", "row_not_sequence", "width_mismatch"],
)
def test_html_table_rejects_malformed_input(capture_send, headers, data):
    with pytest.raises(AssertionError):
        capture_send(lambda v: v.html_table(data, headers))


# -------------------------------------------------------- learning_curve ----


def test_learning_curve_stacks_metrics_into_one_plot(capture_send):
    sent = capture_send(
        lambda v: v.learning_curve({"train": [1.0, 0.8], "val": [1.1, 0.9]})
    )
    traces = sent["payload"]["data"]
    assert len(traces) == 2
    assert [t["name"] for t in traces] == ["train", "val"]
    assert traces[0]["y"] == [1.0, 0.8]
    assert traces[0]["x"] == [0, 1]


def test_learning_curve_defaults_its_labels(capture_send):
    sent = capture_send(lambda v: v.learning_curve({"loss": [1.0]}))
    layout = sent["payload"]["layout"]
    assert layout["title"] == {"text": "Learning Curve"}
    assert layout["xaxis"]["title"] == {"text": "step"}
    assert layout["yaxis"]["title"] == {"text": "metric"}


def test_learning_curve_honours_a_supplied_step(capture_send):
    sent = capture_send(lambda v: v.learning_curve({"loss": [1.0, 0.5]}, step=[10, 20]))
    assert sent["payload"]["data"][0]["x"] == [10, 20]


def test_learning_curve_promotes_scalars_to_one_point(capture_send):
    sent = capture_send(lambda v: v.learning_curve({"loss": 0.5}, step=3))
    assert sent["payload"]["data"][0]["y"] == [0.5]
    assert sent["payload"]["data"][0]["x"] == [3]


def test_learning_curve_legend_defaults_to_the_metric_names(capture_send):
    sent = capture_send(lambda v: v.learning_curve({"a": [1], "b": [2]}))
    assert [t["name"] for t in sent["payload"]["data"]] == ["a", "b"]


def test_learning_curve_sends_one_named_update_per_metric(offline_client):
    """An update fans out so mapping order cannot swap traces."""
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve(
            {"a": [1.0], "b": [2.0]}, step=[1], win="w1", update="append"
        )

    updates = sends_to(send, "update")
    assert len(updates) == 2
    assert [m["name"] for m in updates] == ["a", "b"]
    assert all(m["win"] == "w1" for m in updates)


def test_learning_curve_remove_deletes_the_named_trace(offline_client):
    with patch.object(offline_client, "_send", return_value="w1") as send:
        offline_client.learning_curve({"a": [1.0]}, win="w1", update="remove")

    (removal,) = sends_to(send, "update")
    assert removal["name"] == "a"
    assert removal["delete"] is True
    assert removal["data"] == []


@requires_assertions
@pytest.mark.parametrize(
    "kwargs",
    [
        {"metrics": {}},
        {"metrics": {"a": []}},
        {"metrics": {"a": [1, 2], "b": [1]}},
        {"metrics": {"a": [1, 2]}, "step": [1]},
        {"metrics": {"a": [1]}, "update": "append"},
        {"metrics": {"a": [1]}, "opts": {"legend": "notalist"}},
    ],
    ids=[
        "empty",
        "empty_series",
        "ragged",
        "step_mismatch",
        "append_no_step",
        "legend",
    ],
)
def test_learning_curve_rejects_malformed_input(capture_send, kwargs):
    with pytest.raises(AssertionError):
        capture_send(lambda v: v.learning_curve(**kwargs))


# ----------------------------------------------------- update_window_opts ----


def test_update_window_opts_sends_layout_without_content(capture_send):
    sent = capture_send(
        lambda v: v.update_window_opts("w1", {"title": "T", "xlabel": "x"})
    )
    assert sent["endpoint"] == "update"
    assert "data" not in sent["payload"]
    assert sent["payload"]["win"] == "w1"
    assert sent["payload"]["opts"]["title"] == "T"
    assert sent["payload"]["layout"]["title"] == {"text": "T"}
    assert sent["payload"]["layout"]["xaxis"]["title"] == {"text": "x"}


def test_update_window_opts_routes_env(capture_send):
    sent = capture_send(lambda v: v.update_window_opts("w1", {}, env="e1"))
    assert sent["payload"]["eid"] == "e1"


# ------------------------------------------------------------ embeddings ----

FEATURES = np.array([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]])
LABELS = [1, 2, 1]
TSNE_XY = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])


def test_embeddings_sends_a_loading_pane_then_the_points(offline_client):
    calls = []
    with patch("visdom.do_tsne", return_value=TSNE_XY), patch.object(
        offline_client, "_send", side_effect=lambda m, **k: calls.append((m, k)) or "w"
    ):
        offline_client.embeddings(
            FEATURES, LABELS, opts={"register_embedding_events": False}
        )

    assert len(calls) == 2
    loading, points = calls[0][0], calls[1][0]
    assert loading["data"][0] == {"content": {"isLoading": True}, "type": "embeddings"}
    assert points["data"][0]["type"] == "embeddings"
    assert len(points["data"][0]["content"]["data"]) == 3


def test_embeddings_point_carries_group_label_and_index(offline_client):
    calls = []
    with patch("visdom.do_tsne", return_value=TSNE_XY), patch.object(
        offline_client, "_send", side_effect=lambda m, **k: calls.append(m) or "w"
    ):
        offline_client.embeddings(
            FEATURES, LABELS, opts={"register_embedding_events": False}
        )

    first = calls[1]["data"][0]["content"]["data"][0]
    assert first["idx"] == 0
    assert first["label"] == 1
    assert first["name"] == "Entity 0"
    assert first["group"] == 0


def test_embeddings_reuses_the_win_id_from_the_loading_send(offline_client):
    with patch("visdom.do_tsne", return_value=TSNE_XY), patch.object(
        offline_client, "_send", return_value="assigned"
    ) as send:
        result = offline_client.embeddings(
            FEATURES, LABELS, opts={"register_embedding_events": False}
        )

    assert result == "assigned"
    assert send.call_args_list[1][0][0]["win"] == "assigned"


@requires_assertions
def test_embeddings_registers_events_by_default_and_needs_a_socket(offline_client):
    """Pinned: the default opt makes the offline case the failing one."""
    with patch("visdom.do_tsne", return_value=TSNE_XY), patch.object(
        offline_client, "_send", return_value="w"
    ):
        with pytest.raises(AssertionError):
            offline_client.embeddings(FEATURES, LABELS)


def test_register_embeddings_stores_the_window_state(offline_client):
    offline_client.use_socket = True
    offline_client._register_embeddings(
        FEATURES, LABELS, [], None, None, "w1", "e1", {}
    )

    state = offline_client.win_data["w1"]
    assert state["labels"] == LABELS
    assert state["env"] == "e1"
    assert offline_client.event_handlers[("e1", "w1")]


def test_register_embeddings_entity_selected_serves_the_preview(offline_client):
    offline_client.use_socket = True
    offline_client._register_embeddings(
        FEATURES, LABELS, [], lambda i: "<p>%d</p>" % i, "html", "w1", "e1", {}
    )
    handler = offline_client.event_handlers[("e1", "w1")][0]

    with patch.object(offline_client, "_send") as send:
        handler(
            {
                "target": "w1",
                "event_type": "EntitySelected",
                "entityId": "e7",
                "idx": 2,
            }
        )

    msg = send.call_args[0][0]
    assert send.call_args[1]["endpoint"] == "update"
    assert msg["data"]["update_type"] == "EntitySelected"
    assert msg["data"]["selected"] == {"html": "<p>2</p>", "entityId": "e7"}


def test_register_embeddings_entity_selected_without_a_getter(offline_client):
    offline_client.use_socket = True
    offline_client._register_embeddings(
        FEATURES, LABELS, [], None, None, "w1", None, {}
    )
    handler = offline_client.event_handlers[(None, "w1")][0]

    with patch.object(offline_client, "_send") as send:
        handler(
            {"target": "w1", "event_type": "EntitySelected", "entityId": "e", "idx": 0}
        )

    assert send.call_args[0][0]["data"]["selected"]["html"] == (
        "<div>No preview available</div>"
    )


def test_register_embeddings_region_selected_reruns_tsne_on_the_subset(offline_client):
    offline_client.use_socket = True
    offline_client._register_embeddings(
        FEATURES, LABELS, [], None, None, "w1", None, {}
    )
    handler = offline_client.event_handlers[(None, "w1")][0]

    with patch("visdom.do_tsne", return_value=TSNE_XY[:2]) as tsne, patch.object(
        offline_client, "_send"
    ) as send:
        handler(
            {"target": "w1", "event_type": "RegionSelected", "selectedIdxs": [0, 2]}
        )

    assert tsne.call_args[0][0].shape == (2, 2)
    points = send.call_args[0][0]["data"]["points"]
    assert [p["idx"] for p in points] == [0, 2]


def test_register_embeddings_ignores_an_unsupported_event(offline_client):
    offline_client.use_socket = True
    offline_client._register_embeddings(
        FEATURES, LABELS, [], None, None, "w1", None, {}
    )
    handler = offline_client.event_handlers[(None, "w1")][0]

    with patch.object(offline_client, "_send") as send:
        handler({"target": "w1", "event_type": "Whatever"})

    send.assert_not_called()


# ----------------------------------------------- window and env management ----


@pytest.mark.parametrize(
    "call,endpoint,expected",
    [
        (lambda v: v.close(win="w1", env="e1"), "close", {"win": "w1", "eid": "e1"}),
        (lambda v: v.close(), "close", {"win": None, "eid": None}),
        (lambda v: v.delete_env("e1"), "delete_env", {"eid": "e1"}),
        (
            lambda v: v.get_window_data(win="w1", env="e1"),
            "win_data",
            {"win": "w1", "eid": "e1"},
        ),
        (lambda v: v.save(["a", "b"]), "save", {"data": ["a", "b"]}),
        (
            lambda v: v.fork_env("old", "new"),
            "fork_env",
            {"prev_eid": "old", "eid": "new"},
        ),
    ],
    ids=["close_one", "close_all", "delete_env", "win_data", "save", "fork_env"],
)
def test_management_routes(capture_send, call, endpoint, expected):
    sent = capture_send(call)
    assert sent["endpoint"] == endpoint
    assert sent["payload"] == expected


def test_set_window_data_carries_the_payload(capture_send):
    sent = capture_send(lambda v: v.set_window_data({"jsons": {}}, win="w1", env="e1"))
    assert sent["endpoint"] == "win_data"
    assert sent["payload"]["data"] == {"jsons": {}}


def test_save_accepts_an_empty_list(capture_send):
    sent = capture_send(lambda v: v.save([]))
    assert sent["payload"]["data"] == []


@requires_assertions
@pytest.mark.parametrize(
    "call",
    [
        lambda v: v.save("main"),
        lambda v: v.save([1]),
        lambda v: v.fork_env(1, "new"),
        lambda v: v.fork_env("old", 1),
    ],
    ids=["save_not_list", "save_not_str", "fork_prev_not_str", "fork_eid_not_str"],
)
def test_management_rejects_malformed_input(capture_send, call):
    with pytest.raises(AssertionError):
        capture_send(call)


# ------------------------------------------------------- reply parsers ----


@pytest.mark.parametrize(
    "reply,expected",
    [("true", True), ("false", False), ("", None), ("garbage", None)],
)
def test_win_exists_maps_the_reply(offline_client, reply, expected):
    with patch.object(offline_client, "_win_exists_wrap", return_value=reply):
        assert offline_client.win_exists("w1") is expected


def test_win_exists_survives_a_dead_server(offline_client):
    with patch.object(offline_client, "_win_exists_wrap", side_effect=ConnectionError):
        assert offline_client.win_exists("w1") is None


def test_get_env_list_parses_the_server_reply(offline_client):
    with replies(offline_client, json.dumps(["main", "other"])):
        assert offline_client.get_env_list() == ["main", "other"]


def test_get_env_list_asks_for_every_env_not_just_this_one(offline_client):
    """Regression: ``/env_state`` returns one env's windows when given an eid.

    ``_send`` defaults a missing ``eid`` to the client's env, so before
    ``default_eid=False`` this method asked for ``self.env`` and got that env's
    pane dict back where the caller expects a list of env names.
    """
    with patch.object(
        offline_client, "_send", return_value=json.dumps(["main", "other"])
    ) as send:
        offline_client.get_env_list()

    msg, kwargs = send.call_args[0][0], send.call_args[1]
    assert kwargs["endpoint"] == "env_state"
    assert kwargs["default_eid"] is False
    assert "eid" not in msg


def test_send_defaults_the_eid_to_the_client_env(offline_client):
    offline_client.env = "myenv"
    with posted(offline_client) as msg:
        offline_client._send({"data": []})
    assert msg["eid"] == "myenv"


def test_send_leaves_the_eid_out_when_asked(offline_client):
    offline_client.env = "myenv"
    with posted(offline_client) as msg:
        offline_client._send({"data": []}, default_eid=False)
    assert "eid" not in msg


def test_get_env_list_reads_local_state_when_offline(offline_client):
    offline_client.offline = True
    offline_client.env_list = {"cached"}
    assert offline_client.get_env_list() == ["cached"]


def test_get_env_state_returns_the_parsed_env(offline_client):
    with replies(offline_client, json.dumps({"jsons": {"w1": {}}})):
        assert offline_client.get_env_state("e1") == {"jsons": {"w1": {}}}


@pytest.mark.parametrize("reply", [False, json.dumps({"error": "no such env"})])
def test_get_env_state_returns_none_when_the_env_is_missing(offline_client, reply):
    with replies(offline_client, reply):
        assert offline_client.get_env_state("ghost") is None


def test_get_env_state_returns_none_when_offline(offline_client):
    offline_client.offline = True
    assert offline_client.get_env_state("e1") is None


def test_delete_envs_fans_out_one_call_per_env(offline_client):
    with patch.object(offline_client, "delete_env", return_value="ok") as delete:
        assert offline_client.delete_envs(["a", "b"]) == ["ok", "ok"]
    assert [c[0][0] for c in delete.call_args_list] == ["a", "b"]


@pytest.mark.parametrize("bad", ["main", {"a": 1}, None])
def test_delete_envs_rejects_a_non_list(offline_client, bad):
    with pytest.raises(TypeError):
        offline_client.delete_envs(bad)


def test_delete_envs_rejects_a_non_string_entry(offline_client):
    with patch.object(offline_client, "delete_env"):
        with pytest.raises(TypeError):
            offline_client.delete_envs(["ok", 7])


# -------------------------------------------------- experiment messages ----


def test_experiment_message(offline_client):
    offline_client.env = "expenv"
    with echoes(offline_client):
        msg, endpoint = offline_client.experiment(
            name="r1", params={"lr": 0.01}, tags={"ds": "mnist"}, description="d"
        )
    assert endpoint == "experiments/log"
    assert msg["action"] == "log"
    assert msg["eid"] == "expenv"
    assert msg["params"] == {"lr": 0.01}
    assert msg["tags"] == {"ds": "mnist"}
    assert msg["description"] == "d"


def test_experiment_env_override(offline_client):
    offline_client.env = "expenv"
    with echoes(offline_client):
        msg, _ = offline_client.experiment(params={"lr": 0.01}, env="other")
    assert msg["eid"] == "other"


def test_log_metrics_message(offline_client):
    with echoes(offline_client):
        msg, endpoint = offline_client.log_metrics({"acc": 0.9}, step=5)
    assert endpoint == "experiments/log"
    assert msg["action"] == "metrics"
    assert msg["metrics"] == {"acc": 0.9}
    assert msg["step"] == 5


def test_finish_experiment_message(offline_client):
    with echoes(offline_client):
        msg, _ = offline_client.finish_experiment(status="failed")
    assert msg["action"] == "finish"
    assert msg["status"] == "failed"


def test_finish_experiment_defaults_to_finished(offline_client):
    with echoes(offline_client):
        msg, _ = offline_client.finish_experiment()
    assert msg["status"] == "finished"


@pytest.mark.parametrize(
    "call",
    [
        lambda v: v.experiment(params=[1, 2, 3]),
        lambda v: v.experiment(tags=[1, 2, 3]),
        lambda v: v.log_metrics({}),
        lambda v: v.log_metrics("acc"),
    ],
    ids=["params", "tags", "empty_metrics", "metrics_not_dict"],
)
def test_experiment_methods_reject_malformed_input(offline_client, call):
    with pytest.raises(TypeError):
        call(offline_client)


def test_experiment_decodes_a_json_reply(offline_client):
    with replies(offline_client, json.dumps({"name": "r1", "status": "running"})):
        assert offline_client.experiment(name="r1") == {
            "name": "r1",
            "status": "running",
        }


def test_experiment_passes_through_a_non_json_reply(offline_client):
    with replies(offline_client, "server exploded"):
        assert offline_client.experiment(name="r1") == "server exploded"
