#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Pixel conversion shared by the client's image methods.

Pillow encodes uint8 arrays, so ``image`` and ``image_heatmap`` reduce what
they are given to uint8 through ``image_to_uint8`` first. Each step of that
is its own function: check the dtype, find the range of the finite values, map
that range onto [0, 255], then saturate whatever is still outside it.
"""

import numpy as np

from visdom.utils.shared_utils import _finite_range

#: numpy dtype kinds an image may hold: bool, signed and unsigned integers, and
#: floats. Complex, object, string and date arrays have no pixel meaning.
DRAWABLE_DTYPE_KINDS = "biuf"

#: Value ranges an image is recognised as being in, tried in order. The first
#: one the whole image fits in is stretched onto [0, 255]; an image that fits
#: none of them is left for the clip. [0, 1] is tried first, so an image with no
#: negative values is not read as the upper half of [-1, 1].
KNOWN_RANGES = ((0.0, 1.0), (-1.0, 1.0))

#: How far past a known range a value may stray and still count as inside it,
#: so a 1.0 that came back as 1.0000001 from a float32 computation is still 1.
RANGE_TOLERANCE = 1e-5


def image_to_uint8(img, normalize=False):
    """Return ``img`` as the uint8 pixels it should be drawn with.

    uint8 is drawn as it is. Every other drawable type is converted: the first
    of ``KNOWN_RANGES`` the image fits in is stretched onto [0, 255], and
    anything outside them is clipped. Integer and bool images take the same
    path, so one in [0, 255] draws exactly as its uint8 copy would and a 0/1
    or bool mask draws black and white. ``normalize`` stretches the image's own
    finite range onto [0, 255] instead.
    """
    img = np.asarray(img)
    if img.dtype == np.uint8:
        return img
    img = _as_float(img)
    # An image with no finite value at all is all NaN or infinity, which the
    # saturation step turns into 0 and 255 whatever the range is said to be.
    low, high = _finite_range(img) or (0.0, 0.0)
    rescale = _stretch_to_bytes if normalize else _scale_known_range
    return _saturate(rescale(img, low, high))


def _as_float(img):
    """``img`` as floats, cast from bool or integers; raise for anything else.

    Floats keep their own precision, so a float32 image is scaled in float32.
    """
    if img.dtype.kind not in DRAWABLE_DTYPE_KINDS:
        raise TypeError(
            "Unsupported image dtype: {}. Images must hold integer, bool or "
            "float values.".format(img.dtype)
        )
    if img.dtype.kind == "f":
        return img
    return img.astype(np.float64)


def _stretch_to_bytes(img, low, high):
    """Map ``[low, high]`` linearly onto [0, 255]; a flat image maps to 0."""
    if high <= low:
        return np.zeros_like(img)
    return (img - low) / (high - low) * 255.0


def _scale_known_range(img, low, high):
    """Stretch the first of ``KNOWN_RANGES`` that ``[low, high]`` fits in.

    An image that fits none of them comes back unchanged, to be clipped.
    """
    for range_low, range_high in KNOWN_RANGES:
        if low >= range_low - RANGE_TOLERANCE and high <= range_high + RANGE_TOLERANCE:
            return _stretch_to_bytes(img, range_low, range_high)
    return img


def _saturate(img):
    """Clip to [0, 255] as uint8; NaN becomes 0 and the infinities saturate."""
    img = np.nan_to_num(img, nan=0.0, posinf=255.0, neginf=0.0)
    return np.uint8(np.clip(img, 0, 255))
