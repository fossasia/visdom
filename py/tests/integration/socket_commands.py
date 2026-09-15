#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Every command ``on_message`` dispatches, driven through a real socket.

``AnySocketHandlerOrWrapper.on_message`` is one long ``elif`` chain and is the
only entry point for pane closing, undo, environment deletion, layout edits,
comments and the embeddings drill-down. None of it needed a WebSocket to test:
``testutils.socket_double`` builds the real handler classes over a real
``Application`` with a recording ``write_message``.

``on_message`` is a coroutine -- its saves and undo writes go to the storage
executor -- so ``send`` drives it through ``asyncio.run``. Every command that
touches disk is finished by the time it returns.

Several commands hand work to ``IOLoop.current().run_in_executor``. The
``inline_executor`` fixture replaces that with a synchronous stand-in, so the
side effect has happened by the time the call returns and the assertions do not
race a thread pool.
"""

import asyncio
import json

import pytest

from visdom.server.defaults import DEFAULT_MAX_UNDO_HISTORY
from visdom.utils.server_utils import count_deleted, push_deleted

from testutils import commands, last, open_source, open_sub, sent

pytestmark = pytest.mark.integration


def send(sock, **msg):
    """Dispatch one command through the real ``on_message``."""
    send_raw(sock, json.dumps(msg))


def send_raw(sock, message):
    """Dispatch an already-encoded message, for the malformed-input cases."""
    asyncio.run(sock.on_message(message))


def pane(win="win_0", ptype="plot", content=None, **extra):
    """A pane as it sits in ``state[eid]["jsons"]``."""
    p = {
        "id": win,
        "i": 0,
        "type": ptype,
        "content": {"data": [], "layout": {}} if content is None else content,
    }
    p.update(extra)
    return p


@pytest.fixture
def env(app):
    """``app`` with an ``expt`` environment holding one pane."""
    app.state["expt"] = {"jsons": {"win_0": pane()}, "reload": {}}
    return app


# -- close -------------------------------------------------------------------


def test_close_removes_the_pane(env):
    sub = open_sub(env)
    send(sub, cmd="close", eid="expt", data="win_0")

    assert env.state["expt"]["jsons"] == {}


def test_close_pushes_the_pane_onto_the_undo_stack(env):
    sub = open_sub(env)
    send(sub, cmd="close", eid="expt", data="win_0")

    assert count_deleted(env.storage, "expt") == 1


def test_close_forwards_the_pane_data_to_sources(env):
    """The close event carries the pane that was removed, not ``None``.

    The pane used to be popped a second time under the unescaped eid, so by the
    time the event was built there was nothing left to attach and every source
    received ``pane_data: None``.
    """
    source = open_source(env)
    sub = open_sub(env)

    send(sub, cmd="close", eid="expt", data="win_0")

    event = sent(source)[-1]
    assert event["event_type"] == "close"
    assert event["target"] == "win_0"
    assert event["eid"] == "expt"
    assert event["pane_data"]["id"] == "win_0"


def test_close_of_an_unknown_pane_reports_no_pane_data(env):
    """Closing something that is not there still tells the sources."""
    source = open_source(env)
    sub = open_sub(env)

    send(sub, cmd="close", eid="expt", data="ghost")

    assert sent(source)[-1]["pane_data"] is None
    assert count_deleted(env.storage, "expt") == 0


def test_close_of_an_unknown_pane_still_reports_the_depth(env):
    """Nothing was pushed, so the count comes from the stack as it stands."""
    push_deleted(env.storage, "expt", "win_9", pane("win_9"))
    sub = open_sub(env)
    sub.eid = "expt"

    send(sub, cmd="close", eid="expt", data="ghost")

    assert last(sub, "undo_state")["count"] == 1


def test_close_broadcasts_the_undo_count(env):
    sub = open_sub(env)
    sub.eid = "expt"

    send(sub, cmd="close", eid="expt", data="win_0")

    undo_state = last(sub, "undo_state")
    assert undo_state["eid"] == "expt"
    assert undo_state["count"] == 1


def test_close_escapes_the_environment_id(app):
    """A slash in the eid is escaped before the state lookup."""
    app.state["a_b"] = {"jsons": {"win_0": pane()}, "reload": {}}
    source = open_source(app)
    sub = open_sub(app)

    send(sub, cmd="close", eid="a/b", data="win_0")

    assert app.state["a_b"]["jsons"] == {}
    assert sent(source)[-1]["eid"] == "a_b"


def test_close_of_an_unknown_environment_is_a_noop(env):
    source = open_source(env)
    sub = open_sub(env)

    send(sub, cmd="close", eid="ghost", data="win_0")

    assert sent(source) == [{"command": "alive", "data": "vis_alive"}]
    assert env.state["expt"]["jsons"] != {}


def test_close_without_a_target_is_ignored(env):
    sub = open_sub(env)

    send(sub, cmd="close", eid="expt")

    assert "win_0" in env.state["expt"]["jsons"]


# -- undo --------------------------------------------------------------------


def test_undo_restores_the_last_closed_pane(env):
    sub = open_sub(env)
    send(sub, cmd="close", eid="expt", data="win_0")

    send(sub, cmd="undo", eid="expt")

    assert "win_0" in env.state["expt"]["jsons"]


def test_undo_puts_the_pane_at_the_end_of_the_order(env):
    """A restored pane gets a fresh index so it cannot collide."""
    env.state["expt"]["jsons"]["win_1"] = pane("win_1")
    env.state["expt"]["jsons"]["win_1"]["i"] = 5
    sub = open_sub(env)
    send(sub, cmd="close", eid="expt", data="win_0")

    send(sub, cmd="undo", eid="expt")

    assert env.state["expt"]["jsons"]["win_0"]["i"] == 6


def test_undo_broadcasts_the_restored_pane(env):
    sub = open_sub(env)
    sub.eid = "expt"
    send(sub, cmd="close", eid="expt", data="win_0")

    send(sub, cmd="undo", eid="expt")

    restored = [m for m in sent(sub) if m.get("id") == "win_0"]
    assert restored
    assert restored[-1]["eid"] == "expt"


def test_undo_on_an_empty_stack_only_reports_the_count(env):
    sub = open_sub(env)
    sub.eid = "expt"

    send(sub, cmd="undo", eid="expt")

    assert last(sub, "undo_state")["count"] == 0
    assert env.state["expt"]["jsons"].keys() == {"win_0"}


def test_undo_stack_is_capped(env):
    """Closing more panes than the cap keeps only the most recent ones."""
    for i in range(DEFAULT_MAX_UNDO_HISTORY + 3):
        push_deleted(env.storage, "expt", f"win_{i}", pane(f"win_{i}"))

    assert count_deleted(env.storage, "expt") == DEFAULT_MAX_UNDO_HISTORY


def test_undo_of_an_unknown_environment_is_a_noop(env):
    sub = open_sub(env)

    send(sub, cmd="undo", eid="ghost")

    assert commands(sub) == ["register", "layout_update", "env_update"]


# -- delete_env --------------------------------------------------------------


def test_delete_env_drops_the_environment(env, inline_executor):
    sub = open_sub(env)

    send(sub, cmd="delete_env", eid="expt")

    assert "expt" not in env.state
    assert not env.storage.env_exists("expt")


def test_delete_env_clears_the_undo_history(env, inline_executor):
    sub = open_sub(env)
    send(sub, cmd="close", eid="expt", data="win_0")

    send(sub, cmd="delete_env", eid="expt")

    assert count_deleted(env.storage, "expt") == 0


def test_delete_env_announces_the_new_environment_list(env, inline_executor):
    sub = open_sub(env)

    send(sub, cmd="delete_env", eid="expt")

    assert last(sub, "env_update")["data"] == ["main"]


def test_delete_env_refuses_to_remove_main(env):
    sub = open_sub(env)

    send(sub, cmd="delete_env", eid="main")

    assert "main" in env.state


def test_delete_env_escapes_the_environment_id(app, inline_executor):
    app.state["a_b"] = {"jsons": {}, "reload": {}}
    sub = open_sub(app)

    send(sub, cmd="delete_env", eid="a/b")

    assert "a_b" not in app.state


# -- save --------------------------------------------------------------------


def test_save_forks_the_previous_environment(env):
    sub = open_sub(env)

    send(sub, cmd="save", eid="copy", prev_eid="expt", data={"win_0": [0, 0, 3, 3]})

    assert "win_0" in env.state["copy"]["jsons"]
    assert env.state["copy"]["reload"] == {"win_0": [0, 0, 3, 3]}


def test_save_leaves_the_source_environment_alone(env):
    sub = open_sub(env)
    send(sub, cmd="save", eid="copy", prev_eid="expt", data={})

    env.state["copy"]["jsons"]["win_1"] = pane("win_1")

    assert "win_1" not in env.state["expt"]["jsons"]


def test_save_persists_the_new_environment(env):
    sub = open_sub(env)

    send(sub, cmd="save", eid="copy", prev_eid="expt", data={})

    assert env.storage.env_exists("copy")


def test_save_repoints_the_socket_at_the_new_environment(env):
    sub = open_sub(env)

    send(sub, cmd="save", eid="copy", prev_eid="expt", data={})

    assert sub.eid == "copy"


def test_save_without_a_known_source_is_a_noop(env):
    sub = open_sub(env)

    send(sub, cmd="save", eid="copy", prev_eid="ghost", data={})

    assert "copy" not in env.state


def test_save_without_a_previous_id_is_a_noop(env):
    sub = open_sub(env)

    send(sub, cmd="save", eid="copy", data={})

    assert "copy" not in env.state


# -- save_all ----------------------------------------------------------------


def test_save_all_persists_every_environment(env, inline_executor):
    sub = open_sub(env)

    send(sub, cmd="save_all")

    assert env.storage.env_exists("expt")
    assert env.storage.env_exists("main")


def test_save_all_is_handed_to_the_executor(env, inline_executor):
    """The write is offloaded rather than blocking the socket loop."""
    sub = open_sub(env)

    send(sub, cmd="save_all")

    func, args = inline_executor[0]
    assert func == env.storage.save_all
    assert list(args[0]) == list(env.state)


def test_save_all_hands_the_worker_a_snapshot(env, inline_executor):
    """The worker must not receive the live state dict."""
    sub = open_sub(env)

    send(sub, cmd="save_all")

    _func, args = inline_executor[0]
    payload = args[0]
    assert payload is not env.state
    assert payload["expt"] is not env.state["expt"]
    assert payload["expt"]["jsons"] is not env.state["expt"]["jsons"]


def test_save_all_snapshot_ignores_later_mutations(env, inline_executor):
    """What reaches disk is the state as it was when the command arrived."""
    sub = open_sub(env)
    captured = {}

    def capture(state):
        captured["eids"] = sorted(state)
        captured["panes"] = sorted(state["expt"]["jsons"])
        env.state["expt"]["jsons"]["win_late"] = pane("win_late")
        return []

    env.storage.save_all = capture
    send(sub, cmd="save_all")

    assert captured["panes"] == ["win_0"]
    assert "win_late" in env.state["expt"]["jsons"]


# -- save_layouts ------------------------------------------------------------


def test_save_layouts_stores_the_payload(env):
    sub = open_sub(env)

    send(sub, cmd="save_layouts", data='[["view A", {}]]')

    assert env.layouts == '[["view A", {}]]'
    assert env.storage.load_layouts() == '[["view A", {}]]'


def test_save_layouts_tells_the_subscribers(env):
    sub = open_sub(env)

    send(sub, cmd="save_layouts", data="[]")

    assert last(sub, "layout_update")["data"] == "[]"


def test_a_source_socket_can_save_layouts(env):
    """A source connection sending ``save_layouts`` used to raise ValueError.

    Only subscriber sockets carried an implementation of ``broadcast_layouts``;
    the base class raised, and the exception escaped the message loop.
    """
    sub = open_sub(env)
    source = open_source(env)

    send(source, cmd="save_layouts", data='[["from a source", {}]]')

    assert env.layouts == '[["from a source", {}]]'
    assert last(sub, "layout_update")["data"] == '[["from a source", {}]]'


def test_save_layouts_without_data_is_a_noop(env):
    sub = open_sub(env)
    before = env.layouts

    send(sub, cmd="save_layouts")

    assert env.layouts == before


# -- layout_item_update ------------------------------------------------------


def test_layout_item_update_records_the_position(env):
    sub = open_sub(env)

    send(sub, cmd="layout_item_update", eid="expt", win="win_0", data=[0, 0, 4, 4])

    assert env.state["expt"]["reload"]["win_0"] == [0, 0, 4, 4]


@pytest.mark.parametrize(
    "msg",
    [
        {"cmd": "layout_item_update", "win": "win_0", "data": []},
        {"cmd": "layout_item_update", "eid": "expt", "data": []},
        {"cmd": "layout_item_update", "eid": "ghost", "win": "win_0", "data": []},
    ],
)
def test_layout_item_update_drops_malformed_messages(env, msg):
    sub = open_sub(env)

    send_raw(sub, json.dumps(msg))

    assert env.state["expt"]["reload"] == {}


# -- update_plot_layout ------------------------------------------------------


def test_update_plot_layout_patches_the_layout(env):
    sub = open_sub(env)

    send(sub, cmd="update_plot_layout", eid="expt", win="win_0", data={"title": "new"})

    assert env.state["expt"]["jsons"]["win_0"]["content"]["layout"]["title"] == "new"


def test_update_plot_layout_merges_into_an_existing_layout(env):
    env.state["expt"]["jsons"]["win_0"]["content"]["layout"] = {"title": "old", "a": 1}
    sub = open_sub(env)

    send(sub, cmd="update_plot_layout", eid="expt", win="win_0", data={"title": "new"})

    layout = env.state["expt"]["jsons"]["win_0"]["content"]["layout"]
    assert layout == {"title": "new", "a": 1}


def test_update_plot_layout_targets_one_history_frame(app):
    """A ``plot_history`` pane holds a list of frames; only ``frame`` changes."""
    frames = [{"data": [], "layout": {}}, {"data": [], "layout": {}}]
    app.state["expt"] = {
        "jsons": {"win_0": pane(ptype="plot_history", content=frames)},
        "reload": {},
    }
    sub = open_sub(app)

    send(
        sub,
        cmd="update_plot_layout",
        eid="expt",
        win="win_0",
        frame=1,
        data={"title": "second"},
    )

    stored = app.state["expt"]["jsons"]["win_0"]["content"]
    assert stored[1]["layout"] == {"title": "second"}
    assert stored[0]["layout"] == {}


@pytest.mark.parametrize("frame", [None, -1, 2, "1", 1.0, True, [1]])
def test_update_plot_layout_rejects_a_bad_history_frame(app, frame):
    """The frame index must be an in-range int, and is checked as one.

    Out-of-range and missing frames were already rejected, but the comparison
    ran before any type check, so a string or list frame from a client raised
    ``TypeError`` out of the socket loop. ``True`` is excluded too: it would
    otherwise sail through as index 1.
    """
    frames = [{"data": [], "layout": {}}, {"data": [], "layout": {}}]
    app.state["expt"] = {
        "jsons": {"win_0": pane(ptype="plot_history", content=frames)},
        "reload": {},
    }
    sub = open_sub(app)

    send(
        sub,
        cmd="update_plot_layout",
        eid="expt",
        win="win_0",
        frame=frame,
        data={"title": "nope"},
    )

    assert all(
        f["layout"] == {} for f in app.state["expt"]["jsons"]["win_0"]["content"]
    )


def test_update_plot_layout_rejects_a_non_dict_patch(env):
    sub = open_sub(env)

    send(sub, cmd="update_plot_layout", eid="expt", win="win_0", data=["title"])

    assert env.state["expt"]["jsons"]["win_0"]["content"]["layout"] == {}


def test_update_plot_layout_rejects_a_pane_without_plot_content(env):
    env.state["expt"]["jsons"]["win_0"]["content"] = "just text"
    sub = open_sub(env)

    send(sub, cmd="update_plot_layout", eid="expt", win="win_0", data={"title": "x"})

    assert env.state["expt"]["jsons"]["win_0"]["content"] == "just text"


def test_update_plot_layout_drops_an_unknown_pane(env):
    sub = open_sub(env)

    send(sub, cmd="update_plot_layout", eid="expt", win="ghost", data={"title": "x"})

    assert env.state["expt"]["jsons"]["win_0"]["content"]["layout"] == {}


# -- update_comment ----------------------------------------------------------


def test_update_comment_stores_the_text(env, inline_executor):
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="expt", win="win_0", data="looks good")

    assert env.state["expt"]["jsons"]["win_0"]["comment"] == "looks good"


def test_update_comment_bumps_the_version(env, inline_executor):
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="expt", win="win_0", data="first")
    send(sub, cmd="update_comment", eid="expt", win="win_0", data="second")

    assert env.state["expt"]["jsons"]["win_0"]["version"] == 3


def test_update_comment_broadcasts_a_json_patch(env, inline_executor):
    sub = open_sub(env)
    sub.eid = "expt"

    send(sub, cmd="update_comment", eid="expt", win="win_0", data="looks good")

    packet = last(sub, "window_update")
    assert packet["win"] == "win_0"
    assert packet["eid"] == "expt"
    assert packet["content"] == [
        {"op": "add", "path": "/comment", "value": "looks good"},
        {"op": "replace", "path": "/version", "value": packet["version"]},
    ]


def test_update_comment_does_not_persist_on_its_own(env, inline_executor):
    """The comment lands in memory only; writing it out is the save flow's job.

    ``update_comment`` used to call ``storage.save_env`` itself. That separate
    path was dropped so the command persists the same way every other one does,
    which means nothing reaches disk until an ordinary save runs.
    """
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="expt", win="win_0", data="looks good")

    assert env.state["expt"]["jsons"]["win_0"]["comment"] == "looks good"
    assert inline_executor == []
    assert not env.storage.env_exists("expt")


def test_flushing_persists_the_comment(env, inline_executor):
    """The mark is what carries it to disk, so a flush is enough to write it."""
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="expt", win="win_0", data="looks good")
    env.flush_dirty()

    saved = env.storage.load_env("expt")
    assert saved["jsons"]["win_0"]["comment"] == "looks good"
    assert "expt" not in env.dirty_envs


@pytest.mark.parametrize("comment", [42, None, ["a"], {"text": "a"}])
def test_update_comment_rejects_a_non_string(env, comment):
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="expt", win="win_0", data=comment)

    assert "comment" not in env.state["expt"]["jsons"]["win_0"]


def test_update_comment_drops_an_unknown_pane(env):
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="expt", win="ghost", data="hi")

    assert "comment" not in env.state["expt"]["jsons"]["win_0"]


def test_update_comment_drops_an_unknown_environment(env):
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="ghost", win="win_0", data="hi")

    assert "comment" not in env.state["expt"]["jsons"]["win_0"]


# -- forward_to_vis ----------------------------------------------------------


def test_forward_to_vis_reaches_the_sources(env):
    source = open_source(env)
    sub = open_sub(env)

    send(
        sub,
        cmd="forward_to_vis",
        data={"eid": "expt", "target": "win_0", "event_type": "Click"},
    )

    assert sent(source)[-1]["event_type"] == "Click"


def test_forward_to_vis_attaches_the_pane(env):
    source = open_source(env)
    sub = open_sub(env)

    send(sub, cmd="forward_to_vis", data={"eid": "expt", "target": "win_0"})

    assert sent(source)[-1]["pane_data"]["id"] == "win_0"


def test_forward_to_vis_honours_an_opt_out(env):
    """``pane_data: False`` means the source does not want the pane inlined."""
    source = open_source(env)
    sub = open_sub(env)

    send(
        sub,
        cmd="forward_to_vis",
        data={"eid": "expt", "target": "win_0", "pane_data": False},
    )

    assert sent(source)[-1]["pane_data"] is False


@pytest.mark.parametrize("packet", ["a string", 42, ["a"], None])
def test_forward_to_vis_rejects_a_non_dict_payload(env, packet):
    source = open_source(env)
    sub = open_sub(env)

    send(sub, cmd="forward_to_vis", data=packet)

    assert commands(source) == ["alive"]


@pytest.mark.parametrize("packet", [{"target": "win_0"}, {"eid": "expt"}, {}])
def test_forward_to_vis_rejects_an_incomplete_packet(env, packet):
    source = open_source(env)
    sub = open_sub(env)

    send(sub, cmd="forward_to_vis", data=packet)

    assert commands(source) == ["alive"]


def test_forward_to_vis_warns_the_sender_about_a_missing_env(env):
    source = open_source(env)
    sub = open_sub(env)

    send(sub, cmd="forward_to_vis", data={"eid": "ghost", "target": "win_0"})

    notification = last(sub, "notification")
    assert notification["data"]["type"] == "warning"
    assert "ghost" in notification["data"]["message"]
    assert commands(source) == ["alive"]


def test_forward_to_vis_warns_the_sender_about_a_missing_pane(env):
    source = open_source(env)
    sub = open_sub(env)

    send(sub, cmd="forward_to_vis", data={"eid": "expt", "target": "ghost"})

    notification = last(sub, "notification")
    assert notification["data"]["type"] == "warning"
    assert "ghost" in notification["data"]["message"]
    assert commands(source) == ["alive"]


def test_forward_to_vis_notifies_only_the_sender(env):
    other = open_sub(env)
    sub = open_sub(env)

    send(sub, cmd="forward_to_vis", data={"eid": "ghost", "target": "win_0"})

    assert last(sub, "notification") is not None
    assert last(other, "notification") is None


# -- pop_embeddings_pane -----------------------------------------------------


def embeddings_pane(history=None):
    """An embeddings pane mid-drilldown, with previous states to pop back to."""
    return pane(
        ptype="embeddings",
        content={"data": [[9, 9]], "selected": 3, "has_previous": True},
        old_content=[[[1, 1]], [[5, 5]]] if history is None else history,
    )


def test_pop_embeddings_restores_the_previous_points(app):
    app.state["expt"] = {"jsons": {"win_0": embeddings_pane()}, "reload": {}}
    sub = open_sub(app)

    send(sub, cmd="pop_embeddings_pane", data={"eid": "expt", "target": "win_0"})

    content = app.state["expt"]["jsons"]["win_0"]["content"]
    assert content["data"] == [[5, 5]]
    assert content["selected"] is None
    assert content["has_previous"] is True


def test_pop_embeddings_clears_has_previous_on_the_last_step(app):
    app.state["expt"] = {
        "jsons": {"win_0": embeddings_pane([[[1, 1]]])},
        "reload": {},
    }
    sub = open_sub(app)

    send(sub, cmd="pop_embeddings_pane", data={"eid": "expt", "target": "win_0"})

    assert app.state["expt"]["jsons"]["win_0"]["content"]["has_previous"] is False


def test_pop_embeddings_issues_a_new_content_id(app):
    app.state["expt"] = {"jsons": {"win_0": embeddings_pane()}, "reload": {}}
    app.state["expt"]["jsons"]["win_0"]["contentID"] = "old"
    sub = open_sub(app)

    send(sub, cmd="pop_embeddings_pane", data={"eid": "expt", "target": "win_0"})

    assert app.state["expt"]["jsons"]["win_0"]["contentID"] != "old"


def test_pop_embeddings_broadcasts_the_pane(app):
    app.state["expt"] = {"jsons": {"win_0": embeddings_pane()}, "reload": {}}
    sub = open_sub(app)
    sub.eid = "expt"

    send(sub, cmd="pop_embeddings_pane", data={"eid": "expt", "target": "win_0"})

    broadcast = [m for m in sent(sub) if m.get("id") == "win_0"][-1]
    assert broadcast["eid"] == "expt"
    assert broadcast["content"]["data"] == [[5, 5]]


@pytest.mark.parametrize("drop_key", [False, True], ids=["empty", "absent"])
def test_pop_embeddings_survives_an_exhausted_history(app, drop_key):
    """Popping with nothing left used to raise out of the message loop.

    The pane is left untouched and the socket stays usable, rather than an
    ``IndexError`` (empty list) or ``KeyError`` (absent key) escaping into
    Tornado's WebSocket callback.
    """
    p = embeddings_pane([])
    if drop_key:
        del p["old_content"]
    app.state["expt"] = {"jsons": {"win_0": p}, "reload": {}}
    sub = open_sub(app)

    send(sub, cmd="pop_embeddings_pane", data={"eid": "expt", "target": "win_0"})

    assert app.state["expt"]["jsons"]["win_0"]["content"]["data"] == [[9, 9]]

    send(sub, cmd="layout_item_update", eid="expt", win="win_0", data=[0, 0, 1, 1])
    assert app.state["expt"]["reload"]["win_0"] == [0, 0, 1, 1]


@pytest.mark.parametrize(
    "packet",
    [
        "a string",
        None,
        {"target": "win_0"},
        {"eid": "expt"},
        {"eid": "ghost", "target": "win_0"},
        {"eid": "expt", "target": "ghost"},
    ],
)
def test_pop_embeddings_drops_malformed_messages(app, packet):
    app.state["expt"] = {"jsons": {"win_0": embeddings_pane()}, "reload": {}}
    sub = open_sub(app)

    send(sub, cmd="pop_embeddings_pane", data=packet)

    assert app.state["expt"]["jsons"]["win_0"]["content"]["data"] == [[9, 9]]


# -- echo, and the source/subscriber split -----------------------------------


def test_echo_returns_the_message_to_the_sources(env):
    source = open_source(env)

    send(source, cmd="echo", data="ping")

    assert sent(source)[-1] == {"cmd": "echo", "data": "ping"}


def test_echo_reaches_every_source(env):
    first = open_source(env)
    second = open_source(env)

    send(first, cmd="echo", data="ping")

    assert sent(second)[-1]["data"] == "ping"


def test_echo_does_not_fall_through_to_the_base_commands(env):
    """``echo`` returns early; it is not also treated as an unknown command."""
    source = open_source(env)
    sub = open_sub(env)

    send(source, cmd="echo", data="ping")

    assert commands(sub) == ["register", "layout_update", "env_update"]


def test_a_source_socket_handles_the_shared_commands_too(env, inline_executor):
    """Anything that is not ``echo`` falls through to the shared dispatch."""
    source = open_source(env)

    send(source, cmd="delete_env", eid="expt")

    assert "expt" not in env.state


def test_echo_from_a_subscriber_is_not_a_command(env):
    """``echo`` only exists on the source socket class."""
    sub = open_sub(env)

    send(sub, cmd="echo", data="ping")

    assert commands(sub) == ["register", "layout_update", "env_update"]


# -- unknown commands --------------------------------------------------------


@pytest.mark.parametrize("cmd", ["not_a_command", "", None])
def test_an_unrecognised_command_is_ignored(env, cmd):
    sub = open_sub(env)

    send(sub, cmd=cmd)

    assert commands(sub) == ["register", "layout_update", "env_update"]
    assert env.state["expt"]["jsons"].keys() == {"win_0"}


# -- autosave bookkeeping ----------------------------------------------------


def test_close_marks_the_environment_dirty(env):
    """Every command below edits state that autosave has to notice.

    Only the HTTP handlers marked their writes, so a pane closed, a comment
    added, a layout dragged or a table edited from the browser -- all of which
    arrive over the socket -- were never written out by the timer, and were
    lost unless something else happened to save the environment.
    """
    sub = open_sub(env)

    send(sub, cmd="close", eid="expt", data="win_0")

    assert env.dirty_envs["expt"] == 1


def test_undo_marks_the_environment_dirty(env):
    sub = open_sub(env)
    send(sub, cmd="close", eid="expt", data="win_0")
    env.dirty_envs.clear()

    send(sub, cmd="undo", eid="expt")

    assert env.dirty_envs["expt"] == 1


def test_layout_item_update_marks_the_environment_dirty(env):
    sub = open_sub(env)

    send(sub, cmd="layout_item_update", eid="expt", win="win_0", data=[0, 0, 4, 4])

    assert env.dirty_envs["expt"] == 1


def test_update_plot_layout_marks_the_environment_dirty(env):
    sub = open_sub(env)

    send(sub, cmd="update_plot_layout", eid="expt", win="win_0", data={"title": "new"})

    assert env.dirty_envs["expt"] == 1


def test_update_comment_marks_the_environment_dirty(env):
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="expt", win="win_0", data="looks good")

    assert env.dirty_envs["expt"] == 1


def test_table_edit_marks_the_environment_dirty(app):
    app.state["expt"] = {
        "jsons": {
            "win_0": pane(ptype="table", content={"headers": ["a"], "rows": [["x"]]})
        },
        "reload": {},
    }
    sub = open_sub(app)

    send(
        sub,
        cmd="table_edit",
        eid="expt",
        win="win_0",
        op="edit_cell",
        data={"row": 0, "col": 0, "value": "y"},
    )

    assert app.state["expt"]["jsons"]["win_0"]["content"]["rows"] == [["y"]]
    assert app.dirty_envs["expt"] == 1


def test_a_dropped_command_leaves_the_environment_clean(env):
    """Nothing changed, so nothing is owed to disk."""
    sub = open_sub(env)

    send(sub, cmd="update_comment", eid="expt", win="ghost", data="hi")

    assert env.dirty_envs == {}
