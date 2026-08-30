#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import numpy as np
import pytest

from visdom.server.handlers.web_handlers import UpdateHandler

pytestmark = pytest.mark.unit


def image_pane(n=5):
    return {
        "type": "image_history",
        "content": [{"src": "img_{}".format(i)} for i in range(n)],
        "selected": 0,
    }


def plot_pane():
    return {
        "type": "plot",
        "content": {
            "data": [{"type": "scatter", "x": [1], "y": [2]}],
            "layout": {},
        },
    }


def select(index):
    return {"data": [{"type": "image_update_selected", "selected": index}]}


def update(pane, args):
    return UpdateHandler.update(pane, args, 500, 50, 4, 4)


# ------------------------------------------------------- server-side update ----


def test_sets_index():
    assert update(image_pane(), select(3))["selected"] == 3


def test_empty_content_returns_unchanged():
    pane = {"type": "image_history", "content": [], "selected": 0}
    assert update(pane, select(2))["selected"] == 0


def test_clamps_negative():
    assert update(image_pane(), select(-5))["selected"] == 0


def test_clamps_over_bound():
    assert update(image_pane(n=3), select(99))["selected"] == 2


def test_rejects_fractional_index():
    with pytest.raises(ValueError):
        update(image_pane(), select(1.5))


@pytest.mark.parametrize("bad_value", ["2", None, True], ids=["string", "none", "bool"])
def test_rejects_non_numeric_index(bad_value):
    with pytest.raises(TypeError):
        update(image_pane(), select(bad_value))


# ------------------------------------------------------- client-side checks ----


def test_client_rejects_bool_index(offline_client):
    with pytest.raises(TypeError):
        offline_client.update_image_slider("win_a", True)


@pytest.mark.parametrize(
    "bad_value",
    [float("inf"), float("-inf"), float("nan")],
    ids=["inf", "-inf", "nan"],
)
def test_client_rejects_non_finite_float(offline_client, bad_value):
    with pytest.raises(ValueError):
        offline_client.update_image_slider("win_a", bad_value)


@pytest.mark.parametrize("bad_value", ["2", None], ids=["string", "none"])
def test_client_payload_rejects_non_numeric_values(offline_client, bad_value):
    with pytest.raises(TypeError):
        offline_client.update_image_slider("win_a", bad_value)


def test_client_payload_rejects_fractional_float(offline_client):
    with pytest.raises(ValueError):
        offline_client.update_image_slider("win_a", np.float32(2.5))


def test_client_payload_rejects_numpy_array_multielement(offline_client):
    with pytest.raises(TypeError):
        offline_client.update_image_slider("win_a", np.array([1, 2], dtype=np.int64))


def test_client_payload_coerces_numpy_scalars(capture_send):
    sent = capture_send(lambda v: v.update_image_slider("win_a", np.int64(2)))
    assert sent["endpoint"] == "update"
    assert sent["payload"]["win"] == "win_a"
    block = sent["payload"]["data"][0]
    assert block["type"] == "image_update_selected"
    assert block["selected"] == 2
    assert isinstance(block["selected"], int)


def test_client_payload_accepts_integral_float_scalars(capture_send):
    sent = capture_send(lambda v: v.update_image_slider("win_a", np.float32(2.0)))
    assert sent["endpoint"] == "update"
    assert sent["payload"]["data"][0]["selected"] == 2


def test_client_payload_coerces_numpy_array_scalar(capture_send):
    sent = capture_send(
        lambda v: v.update_image_slider("win_a", np.array(2, dtype=np.int64))
    )
    block = sent["payload"]["data"][0]
    assert block["selected"] == 2
    assert isinstance(block["selected"], int)


# ------------------------------------------------------------- wrap_func ----


def test_wrap_func_rejects_non_image_history_windows(handler):
    handler.state = {"main": {"jsons": {"plot_win": plot_pane()}}}
    UpdateHandler.wrap_func(
        handler,
        {"win": "plot_win", "eid": "main", **select(2)},
    )
    assert handler.status == 400
    assert handler.written == ["win is not image_history; was plot"]


def test_wrap_func_reports_invalid_slider_indices(handler):
    handler.state = {"main": {"jsons": {"image_win": image_pane()}}}
    UpdateHandler.wrap_func(
        handler,
        {"win": "image_win", "eid": "main", **select(1.5)},
    )
    assert handler.status == 400
    assert handler.written == ["image slider index must be an integer, got 1.5"]
