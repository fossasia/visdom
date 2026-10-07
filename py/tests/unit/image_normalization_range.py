#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import base64
from io import BytesIO

import numpy as np
from PIL import Image
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.filterwarnings("error::RuntimeWarning")]


@pytest.mark.parametrize("method", ["image", "image_heatmap"])
@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
@pytest.mark.parametrize("channels", [None, 1, 3, 4])
def test_normalize_extreme_finite_range(capture_send, method, dtype, channels):
    limit = np.finfo(dtype).max
    pixels = np.array([[-limit, 0, limit]], dtype=dtype)
    img = pixels if channels is None else np.broadcast_to(pixels, (channels, 1, 3))
    original = img.copy()

    def plot(viz):
        if method == "image":
            return viz.image(img, opts={"normalize": True})
        return viz.image_heatmap(img, np.zeros((1, 3)), opts={"normalize": True})

    sent = capture_send(plot)
    src = sent["payload"]["data"][0]["content"]["src"]
    with Image.open(BytesIO(base64.b64decode(src.split(",", 1)[1]))) as image:
        actual = np.asarray(image)
    expected = np.array([[0, 127, 255]], dtype=np.uint8)
    if method == "image_heatmap" or channels in (3, 4):
        count = 3 if method == "image_heatmap" else channels
        expected = np.repeat(expected[..., None], count, axis=-1)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(img, original)


@pytest.mark.parametrize("method", ["image", "image_heatmap"])
@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_normalize_large_positive_range(capture_send, method, dtype):
    limit = np.finfo(dtype).max
    img = np.array([[limit / 2, limit * 0.75, limit]], dtype=dtype)

    def plot(viz):
        if method == "image":
            return viz.image(img, opts={"normalize": True})
        return viz.image_heatmap(img, np.zeros((1, 3)), opts={"normalize": True})

    sent = capture_send(plot)
    src = sent["payload"]["data"][0]["content"]["src"]
    with Image.open(BytesIO(base64.b64decode(src.split(",", 1)[1]))) as image:
        expected = np.array([[0, 127, 255]], dtype=np.uint8)
        if method == "image_heatmap":
            expected = np.repeat(expected[..., None], 3, axis=-1)
        np.testing.assert_array_equal(np.asarray(image), expected)
