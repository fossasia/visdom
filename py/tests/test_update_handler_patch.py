import copy

import jsonpatch

from visdom.server.handlers.web_handlers import UpdateHandler


def _apply_patch(doc, patch_ops):
    return jsonpatch.apply_patch(copy.deepcopy(doc), patch_ops, in_place=False)


def test_update_packet_text_fast_patch_roundtrip():
    pane = {"id": "w1", "type": "text", "content": "line1", "contentID": "old"}
    original = copy.deepcopy(pane)
    args = {"data": [{"content": "line2"}]}

    updated, patch_ops = UpdateHandler.update_packet(
        pane, args, max_text_lines=50, max_old_content=20, max_image_history=20
    )

    patched = _apply_patch(original, patch_ops)
    assert patched == updated
    assert {
        "op": "replace",
        "path": "/content",
        "value": updated["content"],
    } in patch_ops
    assert any(op["path"] == "/contentID" for op in patch_ops)


def test_update_packet_image_history_select_fast_patch_roundtrip():
    pane = {
        "id": "w2",
        "type": "image_history",
        "content": [{"foo": 1}, {"foo": 2}],
        "selected": 0,
        "contentID": "old",
    }
    original = copy.deepcopy(pane)
    args = {"data": [{"type": "image_update_selected", "selected": 1}]}

    updated, patch_ops = UpdateHandler.update_packet(
        pane, args, max_text_lines=50, max_old_content=20, max_image_history=20
    )

    patched = _apply_patch(original, patch_ops)
    assert patched == updated
    assert {"op": "add", "path": "/selected", "value": 1} in patch_ops
    assert not any(
        op["path"] == "/content" or op["path"] == "/content/-" for op in patch_ops
    )


def test_update_packet_plot_history_append_fast_patch_roundtrip():
    pane = {
        "id": "w3",
        "type": "plot_history",
        "content": [{"x": [1], "y": [2]}],
        "selected": 0,
        "contentID": "old",
    }
    original = copy.deepcopy(pane)
    new_item = {"x": [2], "y": [3]}
    args = {"data": [{"type": "plot_history", "content": new_item}]}

    updated, patch_ops = UpdateHandler.update_packet(
        pane, args, max_text_lines=50, max_old_content=20, max_image_history=20
    )

    patched = _apply_patch(original, patch_ops)
    assert patched == updated
    assert {"op": "add", "path": "/content/-", "value": new_item} in patch_ops
    assert {"op": "add", "path": "/selected", "value": 1} in patch_ops


def test_update_packet_image_history_append_uses_content_add():
    pane = {
        "id": "w4",
        "type": "image_history",
        "content": [{"foo": 1}],
        "selected": 0,
        "contentID": "old",
    }
    original = copy.deepcopy(pane)
    new_item = {"foo": 2}
    args = {"data": [{"type": "image_history", "content": new_item}]}

    updated, patch_ops = UpdateHandler.update_packet(
        pane, args, max_text_lines=50, max_old_content=20, max_image_history=20
    )

    patched = _apply_patch(original, patch_ops)
    assert patched == updated
    assert {"op": "add", "path": "/content/-", "value": new_item} in patch_ops
    assert not any(
        op["path"] == "/content" and op["op"] == "replace" for op in patch_ops
    )


def test_update_packet_selected_guard_omits_missing_selected():
    pane = {
        "id": "w5",
        "type": "image_history",
        "content": [],
        "contentID": "old",
    }
    args = {"data": [{"type": "image_update_selected", "selected": 0}]}

    updated, patch_ops = UpdateHandler.update_packet(
        pane, args, max_text_lines=50, max_old_content=20, max_image_history=20
    )

    # Empty content causes update() to return early without setting selected.
    assert "selected" not in updated
    assert not any(op["path"] == "/selected" for op in patch_ops)
    assert any(op["path"] == "/contentID" for op in patch_ops)
