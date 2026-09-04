#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Environment comparison -- ``server_utils.compare_envs``.

Comparing environments merges several envs into one synthetic env and pushes it
down a subscriber socket. The merge is driven entirely by pane ``title``: panes
sharing a title across envs are combined into a single pane, everything else is
dropped, and a legend maps each env to the label its traces were renamed with.

The function writes to a socket instead of returning, so every assertion here
reads ``FakeSocket.sent``. Two rules are easy to break and are pinned
deliberately: the base env is deep-copied before it is rewritten (a shallow
merge would corrupt live server state), and an image pane only enters the
comparison when the *first* env carries it.
"""

import copy

import pytest

from visdom.utils.server_utils import MAX_ENV_NAME_LEN, compare_envs

from testutils.payloads import env_payload

pytestmark = pytest.mark.unit


def _plot_pane(wid, title, names=("loss",), i=0):
    """Plot pane whose traces carry ``names`` (a ``None`` name means unnamed)."""
    data = []
    for name in names:
        trace = {"type": "scatter", "x": [1, 2], "y": [3, 4]}
        if name is not None:
            trace["name"] = name
        data.append(trace)
    return {
        "command": "window",
        "id": wid,
        "title": title,
        "type": "plot",
        "i": i,
        "content": {"data": data, "layout": {"title": title}},
    }


def _image_pane(wid, title, caption=None, i=0):
    return {
        "command": "window",
        "id": wid,
        "title": title,
        "type": "image",
        "i": i,
        "content": {"src": "data:image/png;base64,iVBOR", "caption": caption},
    }


def _text_pane(wid, title, i=0):
    return {
        "command": "window",
        "id": wid,
        "title": title,
        "type": "text",
        "i": i,
        "content": "hello",
    }


def _env(*panes):
    return env_payload(jsons={pane["id"]: pane for pane in panes})


def _windows(socket):
    """Pane messages only -- the reload/layout commands filtered out."""
    return [
        msg
        for msg in socket.sent
        if isinstance(msg, dict) and msg.get("command") == "window"
    ]


def _titles(socket):
    return [win.get("title") for win in _windows(socket)]


def _by_title(socket, title):
    for win in _windows(socket):
        if win.get("title") == title:
            return win
    return None


def _legend(socket):
    return _by_title(socket, "compare_legend")


def _trace_names(win):
    return [trace.get("name") for trace in win["content"]["data"]]


# -- Envs that cannot be compared --------------------------------------------


def test_no_known_env_sends_only_a_layout(fake_socket, store):
    """Nothing to compare is a layout refresh, not an error or a legend."""
    compare_envs({}, ["ghost-a", "ghost-b"], fake_socket, store)
    assert fake_socket.commands() == ["layout"]
    assert fake_socket.eid == ["ghost-a", "ghost-b"]


def test_unknown_envs_are_dropped_and_the_rest_compared(fake_socket, store):
    """A missing env is skipped; the envs that do exist still compare."""
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss")),
    }
    compare_envs(state, ["a", "ghost", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is not None


def test_an_env_only_on_disk_is_loaded_and_cached(fake_socket, store):
    """A comparison reaches through the store, and keeps what it read."""
    store.save_env("saved", _env(_plot_pane("w1", "loss")))
    state = {"live": _env(_plot_pane("w2", "loss"))}
    compare_envs(state, ["live", "saved"], fake_socket, store)
    assert "saved" in state
    assert _trace_names(_by_title(fake_socket, "loss")) == ["live_loss", "saved_loss"]


# -- Env numbering ------------------------------------------------------------


def test_short_env_ids_are_used_verbatim(fake_socket, store):
    state = {"alpha": _env(_plot_pane("w1", "loss"))}
    compare_envs(state, ["alpha"], fake_socket, store)
    assert "alpha" in _legend(fake_socket)["content"]


def test_an_id_at_the_length_limit_still_reads_as_a_name(fake_socket, store):
    """The switch is ``<=`` -- exactly ``MAX_ENV_NAME_LEN`` keeps the name."""
    eid = "e" * MAX_ENV_NAME_LEN
    state = {eid: _env(_plot_pane("w1", "loss")), "b": _env(_plot_pane("w2", "loss"))}
    compare_envs(state, [eid, "b"], fake_socket, store)
    assert _trace_names(_by_title(fake_socket, "loss")) == [
        "{}_loss".format(eid),
        "b_loss",
    ]


def test_one_long_id_switches_every_env_to_an_index(fake_socket, store):
    """Numbering is all-or-nothing: one long id renames every trace to an index."""
    long_eid = "e" * (MAX_ENV_NAME_LEN + 1)
    state = {
        long_eid: _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss")),
    }
    compare_envs(state, [long_eid, "b"], fake_socket, store)
    assert _trace_names(_by_title(fake_socket, "loss")) == ["0_loss", "1_loss"]


def test_indices_follow_the_requested_order_not_the_sorted_one(fake_socket, store):
    long_eid = "z" * (MAX_ENV_NAME_LEN + 1)
    state = {
        long_eid: _env(_plot_pane("w1", "loss")),
        "a": _env(_plot_pane("w2", "loss")),
    }
    compare_envs(state, ["a", long_eid], fake_socket, store)
    assert _trace_names(_by_title(fake_socket, "loss")) == ["0_loss", "1_loss"]


# -- The base env is not mutated ---------------------------------------------


def test_the_source_env_survives_the_comparison(fake_socket, store):
    """The merge rewrites a deep copy; live server state must be untouched."""
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss")),
    }
    before = copy.deepcopy(state)
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert state == before


def test_comparing_an_env_with_itself_does_not_alias_its_panes(fake_socket, store):
    state = {"a": _env(_plot_pane("w1", "loss"))}
    compare_envs(state, ["a", "a"], fake_socket, store)
    assert _trace_names(state["a"]["jsons"]["w1"]) == ["loss"]


# -- Plot merging -------------------------------------------------------------


def test_matching_titles_merge_into_one_pane(fake_socket, store):
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    merged = _by_title(fake_socket, "loss")
    assert _trace_names(merged) == ["a_loss", "b_loss"]
    assert merged["has_compare"] is True
    assert merged["content"]["layout"]["showlegend"] is True


def test_the_merged_pane_keeps_its_id_and_gets_a_fresh_content_id(fake_socket, store):
    """The frontend redraws off ``contentID``, so the merge has to restamp it."""
    original = _plot_pane("w1", "loss")
    state = {"a": _env(original), "b": _env(_plot_pane("w1", "loss"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    merged = _by_title(fake_socket, "loss")
    assert merged["id"] == "w1"
    assert merged["contentID"] != original.get("contentID")


def test_every_trace_of_a_multi_trace_plot_is_renamed(fake_socket, store):
    state = {
        "a": _env(_plot_pane("w1", "loss", names=("train", "val"))),
        "b": _env(_plot_pane("w2", "loss", names=("train", "val"))),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _trace_names(_by_title(fake_socket, "loss")) == [
        "a_train",
        "a_val",
        "b_train",
        "b_val",
    ]


def test_a_pane_only_one_env_has_is_dropped(fake_socket, store):
    """``has_compare`` prunes anything that is not shared by two envs."""
    state = {
        "a": _env(_plot_pane("w1", "loss"), _plot_pane("w2", "solo")),
        "b": _env(_plot_pane("w3", "loss")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "solo") is None
    assert _by_title(fake_socket, "loss") is not None


def test_a_title_only_a_later_env_has_is_dropped(fake_socket, store):
    """Titles are collected from the base env, so a newcomer has nothing to join."""
    state = {"a": _env(_plot_pane("w1", "loss")), "b": _env(_plot_pane("w2", "extra"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "extra") is None


def test_unnamed_traces_keep_a_plot_out_of_the_comparison(fake_socket, store):
    """Without a legend name there is nothing to prefix, so the pane is skipped."""
    state = {
        "a": _env(_plot_pane("w1", "loss", names=(None,))),
        "b": _env(_plot_pane("w2", "loss", names=(None,))),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_later_env_with_an_unnamed_trace_clears_has_compare(fake_socket, store):
    """One malformed contributor withdraws the whole pane, rather than half-merging."""
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss", names=(None,))),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_later_env_with_no_traces_clears_has_compare(fake_socket, store):
    """An empty contributor withdraws the pane instead of half-merging it."""
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss", names=())),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_later_env_without_a_data_key_is_skipped(fake_socket, store):
    """A contributor whose content carries no data at all is not a crash."""
    pane = _plot_pane("w2", "loss")
    del pane["content"]["data"]
    state = {"a": _env(_plot_pane("w1", "loss")), "b": _env(pane)}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_an_empty_contributor_does_not_undo_an_earlier_valid_one(fake_socket, store):
    """A comparison already established survives a later empty contributor."""
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss")),
        "c": _env(_plot_pane("w3", "loss", names=())),
    }
    compare_envs(state, ["a", "b", "c"], fake_socket, store)
    win = _by_title(fake_socket, "loss")
    assert win is not None
    assert _trace_names(win) == ["a_loss", "b_loss"]


def test_an_empty_contributor_does_not_block_a_later_valid_one(fake_socket, store):
    """A pane still compares when a good contributor follows an empty one."""
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss", names=())),
        "c": _env(_plot_pane("w3", "loss")),
    }
    compare_envs(state, ["a", "b", "c"], fake_socket, store)
    win = _by_title(fake_socket, "loss")
    assert win is not None
    assert _trace_names(win) == ["a_loss", "c_loss"]


def test_a_malformed_contributor_does_not_undo_an_earlier_valid_one(fake_socket, store):
    """An unnamed trace withdraws its own env, not comparisons already made."""
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss")),
        "c": _env(_plot_pane("w3", "loss", names=(None,))),
    }
    compare_envs(state, ["a", "b", "c"], fake_socket, store)
    win = _by_title(fake_socket, "loss")
    assert win is not None
    assert _trace_names(win) == ["a_loss", "b_loss"]


def test_a_partly_named_contributor_merges_none_of_its_traces(fake_socket, store):
    """A contributor is all-or-nothing: one unnamed trace drops the whole env."""
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss", names=("good", None))),
        "c": _env(_plot_pane("w3", "loss")),
    }
    compare_envs(state, ["a", "b", "c"], fake_socket, store)
    win = _by_title(fake_socket, "loss")
    assert win is not None
    assert _trace_names(win) == ["a_loss", "c_loss"]


def test_a_contributor_with_a_none_trace_is_skipped(fake_socket, store):
    """A trace list holding None is malformed input, not a crash."""
    pane = _plot_pane("w2", "loss")
    pane["content"]["data"] = [None]
    state = {"a": _env(_plot_pane("w1", "loss")), "b": _env(pane)}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_base_pane_with_a_none_trace_is_skipped(fake_socket, store):
    """The same malformed trace list in the base env is also survivable."""
    pane = _plot_pane("w1", "loss")
    pane["content"]["data"] = [None]
    state = {"a": _env(pane), "b": _env(_plot_pane("w2", "loss"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_contributor_whose_data_is_not_a_list_is_skipped(fake_socket, store):
    """Content that is not a trace list at all is skipped rather than iterated."""
    pane = _plot_pane("w2", "loss")
    pane["content"]["data"] = {"name": "loss"}
    state = {"a": _env(_plot_pane("w1", "loss")), "b": _env(pane)}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_base_pane_with_a_none_trace_after_a_valid_one_is_skipped(fake_socket, store):
    """Validation covers every base trace, not just the first."""
    pane = _plot_pane("w1", "loss")
    pane["content"]["data"] = [{"type": "scatter", "name": "loss"}, None]
    state = {"a": _env(pane), "b": _env(_plot_pane("w2", "loss"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_partly_named_base_pane_is_never_half_renamed(fake_socket, store):
    """A base pane with one unnamed trace withdraws instead of leaking it."""
    pane = _plot_pane("w1", "loss")
    pane["content"]["data"] = [
        {"type": "scatter", "name": "loss"},
        {"type": "scatter"},
    ]
    state = {"a": _env(pane), "b": _env(_plot_pane("w2", "loss"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_an_empty_title_is_never_merged(fake_socket, store):
    state = {"a": _env(_plot_pane("w1", "")), "b": _env(_plot_pane("w2", ""))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _titles(fake_socket) == ["compare_legend"]


def test_panes_without_a_title_are_never_merged(fake_socket, store):
    pane_a = _plot_pane("w1", "loss")
    pane_b = _plot_pane("w2", "loss")
    del pane_a["title"]
    del pane_b["title"]
    state = {"a": _env(pane_a), "b": _env(pane_b)}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _titles(fake_socket) == ["compare_legend"]


def test_a_shared_title_with_different_types_is_not_merged(fake_socket, store):
    """A plot and an image are not comparable even under one title."""
    state = {
        "a": _env(_plot_pane("w1", "shared")),
        "b": _env(_image_pane("w2", "shared")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "shared") is None


def test_unsupported_pane_types_are_dropped(fake_socket, store):
    """Only plot and image compare; text and friends never gain ``has_compare``."""
    state = {"a": _env(_text_pane("w1", "notes")), "b": _env(_text_pane("w2", "notes"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "notes") is None


def test_a_contributing_pane_without_content_is_skipped(fake_socket, store):
    pane = _plot_pane("w2", "loss")
    del pane["content"]
    state = {"a": _env(_plot_pane("w1", "loss")), "b": _env(pane)}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_base_pane_without_content_is_skipped(fake_socket, store):
    """A pane the merge writes *into* is checked too, not only the ones read.

    Panes built by ``window()`` always carry content, but an uploaded env file
    or a ``/win_data`` write can put anything in state, and reaching a
    content-less base pane used to raise ``KeyError`` inside the compare route.
    """
    pane = _plot_pane("w1", "loss")
    del pane["content"]
    state = {"a": _env(pane), "b": _env(_plot_pane("w2", "loss"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_a_base_plot_with_no_traces_is_skipped(fake_socket, store):
    """Same shape of hazard: the first trace was indexed without a length check."""
    pane = _plot_pane("w1", "loss")
    pane["content"]["data"] = []
    state = {"a": _env(pane), "b": _env(_plot_pane("w2", "loss"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "loss") is None


def test_three_envs_stack_onto_one_pane(fake_socket, store):
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss")),
        "c": _env(_plot_pane("w3", "loss")),
    }
    compare_envs(state, ["a", "b", "c"], fake_socket, store)
    assert _trace_names(_by_title(fake_socket, "loss")) == [
        "a_loss",
        "b_loss",
        "c_loss",
    ]


# -- Image comparison ---------------------------------------------------------


def test_images_become_an_image_compare_strip(fake_socket, store):
    state = {
        "a": _env(_image_pane("w1", "sample")),
        "b": _env(_image_pane("w2", "sample")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    merged = _by_title(fake_socket, "sample")
    assert merged["type"] == "image_compare"
    assert len(merged["content"]) == 2


def test_image_captions_are_prefixed_with_the_env(fake_socket, store):
    state = {
        "a": _env(_image_pane("w1", "sample", caption="epoch1")),
        "b": _env(_image_pane("w2", "sample", caption="epoch2")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    captions = [img["caption"] for img in _by_title(fake_socket, "sample")["content"]]
    assert captions == ["a_epoch1", "b_epoch2"]


def test_a_missing_caption_falls_back_to_the_word_image(fake_socket, store):
    state = {
        "a": _env(_image_pane("w1", "sample")),
        "b": _env(_image_pane("w2", "sample")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    captions = [img["caption"] for img in _by_title(fake_socket, "sample")["content"]]
    assert captions == ["a_image", "b_image"]


def test_an_image_the_first_env_lacks_is_skipped_entirely(fake_socket, store):
    """The strip is only ever seeded at ``ix == 0``.

    The base env supplies the pane ids, so a title it does not carry as an image
    has no strip to append to. Later envs then find no initialised base and skip,
    rather than appending onto the untouched single-image pane.
    """
    state = {
        "a": _env(_plot_pane("w1", "shared"), _image_pane("w2", "pics")),
        "b": _env(_image_pane("w3", "shared"), _image_pane("w4", "pics")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "shared") is None
    assert _by_title(fake_socket, "pics") is not None


def test_a_lone_image_is_pruned_like_a_lone_plot(fake_socket, store):
    """Seeding the strip sets ``has_compare`` False; only a second env flips it."""
    state = {"a": _env(_image_pane("w1", "sample")), "b": _env()}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _by_title(fake_socket, "sample") is None


def test_three_envs_extend_the_same_strip(fake_socket, store):
    state = {
        "a": _env(_image_pane("w1", "sample")),
        "b": _env(_image_pane("w2", "sample")),
        "c": _env(_image_pane("w3", "sample")),
    }
    compare_envs(state, ["a", "b", "c"], fake_socket, store)
    assert len(_by_title(fake_socket, "sample")["content"]) == 3


# -- show_all -----------------------------------------------------------------


def test_show_all_keeps_the_panes_the_merge_dropped(fake_socket, store):
    state = {
        "a": _env(_plot_pane("w1", "loss"), _text_pane("w2", "notes")),
        "b": _env(_plot_pane("w3", "loss")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store, show_all=True)
    assert "[a] notes" in _titles(fake_socket)


def test_show_all_labels_every_pane_with_its_env(fake_socket, store):
    state = {"a": _env(_text_pane("w1", "notes")), "b": _env(_text_pane("w2", "notes"))}
    compare_envs(state, ["a", "b"], fake_socket, store, show_all=True)
    assert sorted(_titles(fake_socket)) == ["[a] notes", "[b] notes", "compare_legend"]


def test_show_all_escapes_the_pane_title(fake_socket, store):
    state = {"a": _env(_text_pane("w1", "<script>"))}
    compare_envs(state, ["a"], fake_socket, store, show_all=True)
    assert "[a] &lt;script&gt;" in _titles(fake_socket)


def test_show_all_labels_an_untitled_pane_with_the_env_alone(fake_socket, store):
    pane = _text_pane("w1", "")
    state = {"a": _env(pane)}
    compare_envs(state, ["a"], fake_socket, store, show_all=True)
    assert "[a]" in _titles(fake_socket)


def test_show_all_relabels_the_nested_plot_layout_too(fake_socket, store):
    """The pane title and the plotly layout title are shown in different places."""
    state = {"a": _env(_plot_pane("w1", "loss"))}
    compare_envs(state, ["a"], fake_socket, store, show_all=True)
    duplicated = _by_title(fake_socket, "[a] loss")
    assert duplicated["content"]["layout"]["title"] == {"text": "[a] loss"}


def test_show_all_ids_are_namespaced_by_env(fake_socket, store):
    state = {"a": _env(_text_pane("w1", "notes")), "b": _env(_text_pane("w1", "notes"))}
    compare_envs(state, ["a", "b"], fake_socket, store, show_all=True)
    ids = {
        win["id"]
        for win in _windows(fake_socket)
        if win["id"] != "window_compare_legend"
    }
    assert ids == {"a_env_w1", "b_env_w1"}


def test_show_all_leaves_the_merged_panes_alone(fake_socket, store):
    state = {
        "a": _env(_plot_pane("w1", "loss")),
        "b": _env(_plot_pane("w2", "loss")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store, show_all=True)
    assert _trace_names(_by_title(fake_socket, "loss")) == ["a_loss", "b_loss"]


def test_show_all_does_not_mutate_the_source_env(fake_socket, store):
    state = {"a": _env(_text_pane("w1", "notes"))}
    before = copy.deepcopy(state)
    compare_envs(state, ["a"], fake_socket, store, show_all=True)
    assert state == before


# -- The legend pane ----------------------------------------------------------


def test_the_legend_maps_every_env_to_its_label(fake_socket, store):
    long_eid = "e" * (MAX_ENV_NAME_LEN + 1)
    state = {long_eid: _env(), "b": _env()}
    compare_envs(state, [long_eid, "b"], fake_socket, store)
    legend = _legend(fake_socket)["content"]
    assert "<td> {} </td> <td> 0 </td>".format(long_eid) in legend
    assert "<td> b </td> <td> 1 </td>" in legend


def test_the_legend_escapes_env_names(fake_socket, store):
    """Env ids reach the browser as HTML, so they are escaped, not interpolated."""
    state = {"<script>": _env()}
    compare_envs(state, ["<script>"], fake_socket, store)
    legend = _legend(fake_socket)["content"]
    assert "<script>" not in legend
    assert "&lt;script&gt;" in legend


def test_the_legend_is_a_text_pane_with_comments_disabled(fake_socket, store):
    state = {"a": _env()}
    compare_envs(state, ["a"], fake_socket, store)
    legend = _legend(fake_socket)
    assert legend["type"] == "text"
    assert legend["commentsDisabled"] is True
    assert legend["has_compare"] is True


def test_the_legend_survives_the_pruning_pass(fake_socket, store):
    """Even when nothing merged, the comparison still explains its numbering."""
    state = {"a": _env(_text_pane("w1", "notes"))}
    compare_envs(state, ["a"], fake_socket, store)
    assert _titles(fake_socket) == ["compare_legend"]


# -- What reaches the socket --------------------------------------------------


def test_the_reload_settings_are_sent_before_the_panes(fake_socket, store):
    state = {"a": env_payload(jsons={}, reload={"width": 200})}
    compare_envs(state, ["a"], fake_socket, store)
    assert fake_socket.commands()[0] == "reload"
    assert fake_socket.sent[0]["data"] == {"width": 200}


def test_a_layout_command_closes_the_stream(fake_socket, store):
    state = {"a": _env(_plot_pane("w1", "loss")), "b": _env(_plot_pane("w2", "loss"))}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert fake_socket.commands()[-1] == "layout"


def test_panes_are_ordered_by_their_grid_index(fake_socket, store):
    state = {
        "a": _env(_plot_pane("w1", "second", i=5), _plot_pane("w2", "first", i=1)),
        "b": _env(_plot_pane("w3", "second"), _plot_pane("w4", "first")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _titles(fake_socket)[:2] == ["first", "compare_legend"]


def test_a_pane_without_an_index_sorts_last(fake_socket, store):
    pane = _plot_pane("w1", "unplaced")
    del pane["i"]
    state = {
        "a": _env(pane, _plot_pane("w2", "placed", i=3)),
        "b": _env(_plot_pane("w3", "unplaced"), _plot_pane("w4", "placed")),
    }
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert _titles(fake_socket)[-1] == "unplaced"


def test_the_socket_records_the_compared_ids(fake_socket, store):
    """The socket remembers the comparison, so later broadcasts can target it."""
    state = {"a": _env(), "b": _env()}
    compare_envs(state, ["a", "b"], fake_socket, store)
    assert fake_socket.eid == ["a", "b"]
