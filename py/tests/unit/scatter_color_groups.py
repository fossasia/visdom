#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Color grouping keeps each trace's point order for both color formats."""

import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("palette", [False, True])
@pytest.mark.parametrize("rgb", [False, True])
def test_interleaved_labels_keep_color_order(capture_send, palette, rgb):
    labels = np.array([2, 1, 2, 1, 2])
    points = np.arange(10, dtype=float).reshape(5, 2)
    colors = (
        np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255], [128, 128, 128], [0, 0, 0]])
        if rgb
        else np.array([0, 64, 128, 192, 255])
    )
    if palette:
        colors = colors[:2]
    original = colors.copy()
    sent = capture_send(
        lambda v: v.scatter(points, Y=labels, opts={"markercolor": colors})
    )

    for trace, label in zip(sent["payload"]["data"], [1, 2]):
        selected = (
            colors[labels - 1][labels == label] if palette else colors[labels == label]
        )
        expected = (
            ["#%02x%02x%02x" % tuple(color) for color in selected]
            if rgb
            else ["rgba(0, 0, 255, %s)" % (color / 255.0) for color in selected]
        )
        assert trace["marker"]["color"] == expected
        np.testing.assert_array_equal(trace["x"], points[labels == label, 0])
    np.testing.assert_array_equal(colors, original)


def test_large_single_trace_keeps_all_per_point_colors(capture_send):
    count = 20000
    colors = np.arange(count, dtype=np.uint8)
    sent = capture_send(
        lambda v: v.scatter(np.zeros((count, 2)), opts={"markercolor": colors})
    )
    trace = sent["payload"]["data"][0]
    assert trace["marker"]["color"] == [
        "rgba(0, 0, 255, %s)" % (color / 255.0) for color in colors
    ]
    assert len(trace["x"]) == count
