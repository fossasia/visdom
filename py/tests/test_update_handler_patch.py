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


def test_update_packet_plot_history_append_fast_patch_roundtrip():
    pane = {
        "id": "w3",
        "type": "plot_history",
        "content": [{"x": [1], "y": [2]}],
        "selected": 0,
        "contentID": "old",
    }
    original = copy.deepcopy(pane)
    args = {"data": [{"type": "plot_history", "content": {"x": [2], "y": [3]}}]}

    updated, patch_ops = UpdateHandler.update_packet(
        pane, args, max_text_lines=50, max_old_content=20, max_image_history=20
    )

    patched = _apply_patch(original, patch_ops)
    assert patched == updated
