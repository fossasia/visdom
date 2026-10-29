#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for ``visdom.utils.image_utils``, the conversion behind
``image`` and ``image_heatmap``.

``client_payloads_media.py`` decodes the PNG a call would send. These pin what
a decoded image cannot show: that an integer image comes out as the bytes the
float path gives the same values, that it gets there without a float copy of
the image, that 64-bit values float64 cannot hold apart stay apart, and that
only an integer image the clip changes warns.
"""

import tracemalloc
import warnings

import numpy as np
import pytest

from visdom.utils.image_utils import image_to_uint8

pytestmark = pytest.mark.unit


def _peak_bytes(call):
    """Peak allocation during ``call``, numpy's own buffers included."""
    call()  # first call pays for any one-off import or cache
    tracemalloc.start()
    try:
        call()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


INTEGER_IMAGES = {
    "bool_mask": np.array([[True, False], [False, True]]),
    "int64_mask": np.array([[0, 1], [1, 0]], dtype=np.int64),
    "signed_unit_range": np.array([[-1, 0], [1, 0]], dtype=np.int16),
    "byte_range": np.array([[0, 17], [128, 255]], dtype=np.int64),
    "out_of_range": np.array([[-300, -1], [256, 70000]], dtype=np.int32),
    "int8_extremes": np.array([[-128, 0], [5, 127]], dtype=np.int8),
    "uint16_depth": np.array([[1000, 2000], [2500, 3000]], dtype=np.uint16),
    "flat": np.full((2, 2), 9, dtype=np.uint32),
    "span_past_the_table": np.array(
        [[-(2**31), 0], [7, 2**31 - 1]], dtype=np.int64
    ),
}


@pytest.mark.filterwarnings("ignore:.*are clipped to 0 and 255")
@pytest.mark.parametrize("normalize", [False, True], ids=["rules", "normalize"])
@pytest.mark.parametrize("name", INTEGER_IMAGES)
def test_integers_draw_as_the_float_path_draws_the_same_values(name, normalize):
    """The integer path may only be cheaper, never draw differently."""
    img = INTEGER_IMAGES[name]
    expected = image_to_uint8(img.astype(np.float64), normalize)
    np.testing.assert_array_equal(image_to_uint8(img, normalize), expected)


CLIPPED = ["out_of_range", "int8_extremes", "uint16_depth", "span_past_the_table"]


@pytest.mark.parametrize("name", CLIPPED)
def test_an_integer_image_the_clip_changes_warns(name):
    img = INTEGER_IMAGES[name]
    match = r"{} image values outside \[0, 255\] are clipped".format(img.dtype)
    with pytest.warns(UserWarning, match=match):
        image_to_uint8(img)


@pytest.mark.parametrize(
    "name, normalize",
    [(name, False) for name in INTEGER_IMAGES if name not in CLIPPED]
    + [(name, True) for name in CLIPPED],
)
def test_an_integer_image_that_loses_nothing_does_not_warn(name, normalize):
    """Masks, [-1, 1], [0, 255] and anything ``normalize`` stretches draw whole."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        image_to_uint8(INTEGER_IMAGES[name], normalize)


@pytest.mark.parametrize(
    "dtype, low",
    [
        (np.int64, 2**53),
        (np.int64, np.iinfo(np.int64).max - 1),
        (np.uint64, np.iinfo(np.uint64).max - 1),
    ],
)
def test_normalize_keeps_apart_64_bit_values_float64_rounds_together(dtype, low):
    """float64 holds 53 bits, so these two used to stretch to one flat black."""
    img = np.array([[low, low + 1]], dtype=dtype)
    assert image_to_uint8(img, normalize=True).tolist() == [[0, 255]]


def test_normalize_stretches_the_whole_64_bit_range():
    """A span too wide for a table is scaled from the exact offsets instead."""
    info = np.iinfo(np.int64)
    img = np.array([[info.min, 0, info.max]], dtype=np.int64)
    assert image_to_uint8(img, normalize=True).tolist() == [[0, 127, 255]]


@pytest.mark.parametrize(
    "img",
    [
        np.arange(1 << 20, dtype=np.int64).reshape(1024, 1024) % 256,
        np.arange(1 << 20).reshape(1024, 1024) % 3 == 0,
    ],
    ids=["clipped_int64", "bool_mask_through_the_table"],
)
def test_integers_convert_without_a_float_copy(img):
    """A float64 copy alone is eight bytes a pixel; what is drawn is one.

    The float path is run against the same budget, which is what shows the
    budget is tight enough to catch a conversion that widens the image.
    """
    budget = img.size * np.dtype(np.float64).itemsize // 2
    assert _peak_bytes(lambda: image_to_uint8(img)) < budget
    assert _peak_bytes(lambda: image_to_uint8(img.astype(np.float64))) > budget


def test_uint8_is_returned_untouched():
    img = np.arange(6, dtype=np.uint8).reshape(2, 3)
    assert image_to_uint8(img) is img


def test_an_empty_integer_image_converts_to_an_empty_one():
    out = image_to_uint8(np.zeros((0, 4), dtype=np.int64))
    assert out.dtype == np.uint8 and out.shape == (0, 4)
