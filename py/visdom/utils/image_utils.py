#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Pixel conversion shared by the client's image methods.

Pillow encodes uint8 arrays, so ``image`` and ``image_heatmap`` reduce what
they are given to uint8 through ``image_to_uint8`` first. uint8 passes through
as it is; every other type goes to the converter for its kind, made of one
function per step: find the range, map it onto [0, 255], then saturate
whatever is still outside it.

Integers and floats follow the same rules and come out as the same bytes, but
they are converted apart. A float image has to be scaled in floating point; an
integer one does not, and widening it to float64 first cost eight bytes a pixel
before any work was done, and rounded together 64-bit values past 2**53.

An integer image that the clip changes, such as a 16-bit depth map, issues a
``UserWarning`` that points at ``normalize``.
"""

import os
import warnings

import numpy as np

from visdom.utils.shared_utils import _finite_range

#: The visdom package directory. The clip warning is reported against the first
#: frame outside it, which is the caller's own line however deep the call runs.
_PACKAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "")

#: Value ranges an image is recognised as being in, tried in order. The first
#: one the whole image fits in is stretched onto [0, 255]; an image that fits
#: none of them is left for the clip. [0, 1] is tried first, so an image with no
#: negative values is not read as the upper half of [-1, 1].
KNOWN_RANGES = ((0, 1), (-1, 1))

#: How far past a known range a value may stray and still count as inside it,
#: so a 1.0 that came back as 1.0000001 from a float32 computation is still 1.
#: An integer is either inside a range or a whole unit outside it.
RANGE_TOLERANCE = 1e-5

#: Integer spans up to this wide are stretched through a table holding the byte
#: for every offset in the span, so the image is converted without a float copy
#: of it. Wider spans, which only ``normalize`` reaches, are scaled in float64.
LOOKUP_SPAN = 1 << 16


def image_to_uint8(img, normalize=False):
    """Return ``img`` as the uint8 pixels it should be drawn with.

    uint8 is drawn as it is. Every other drawable type is converted: the first
    of ``KNOWN_RANGES`` the image fits in is stretched onto [0, 255], and
    anything outside them is clipped. Integer and bool images take the same
    rules, so one in [0, 255] draws exactly as its uint8 copy would and a 0/1
    or bool mask draws black and white. ``normalize`` stretches the image's own
    finite range onto [0, 255] instead.
    """
    img = np.asarray(img)
    if img.dtype == np.uint8:
        return img
    convert = _CONVERTERS.get(img.dtype.kind)
    if convert is None:
        raise TypeError(
            "Unsupported image dtype: {}. Images must hold integer, bool or "
            "float values.".format(img.dtype)
        )
    return convert(img, normalize)


def _known_range(low, high):
    """The first of ``KNOWN_RANGES`` that ``[low, high]`` fits in, or ``None``."""
    for range_low, range_high in KNOWN_RANGES:
        if low >= range_low - RANGE_TOLERANCE and high <= range_high + RANGE_TOLERANCE:
            return range_low, range_high
    return None


# ---- floats ---- #


def _float_to_uint8(img, normalize):
    """Scale a float image in floating point, keeping its own precision."""
    # An image with no finite value at all is all NaN or infinity, which the
    # saturation step turns into 0 and 255 whatever the range is said to be.
    low, high = _finite_range(img) or (0.0, 0.0)
    target = (low, high) if normalize else _known_range(low, high)
    if target is not None:
        img = _stretch_to_bytes(img, *target)
    return _saturate(img)


def _stretch_to_bytes(img, low, high):
    """Map ``[low, high]`` linearly onto [0, 255]; a flat image maps to 0."""
    if high <= low:
        # Nothing to stretch, so every finite pixel is 0. NaN and the
        # infinities are left for the saturation step, as in a stretched image.
        return np.where(np.isfinite(img), 0.0, img)
    return (img - low) / (high - low) * 255.0


def _saturate(img):
    """Clip to [0, 255] as uint8; NaN becomes 0 and the infinities saturate."""
    img = np.nan_to_num(img, nan=0.0, posinf=255.0, neginf=0.0)
    return np.uint8(np.clip(img, 0, 255))


# ---- integers and bool ---- #


def _integer_to_uint8(img, normalize):
    """Convert an integer or bool image without widening it to float.

    The bytes are the ones the float path gives the same values, worked out
    from exact integer offsets instead of from a float64 copy of the image.
    """
    low, high = _integer_range(img)
    target = (low, high) if normalize else _known_range(low, high)
    if target is None:
        if low < 0 or high > 255:
            _warn_clipped(img.dtype)
        return _clip_to_bytes(img)
    return _stretch_integers(img, *target)


def _warn_clipped(dtype):
    """Warn that an integer image is losing the values outside [0, 255].

    The message names only the dtype, never the range, so Python's default
    filter shows it once per calling line instead of on every frame of a loop.
    """
    warnings.warn(
        "{} image values outside [0, 255] are clipped to 0 and 255. Pass "
        "opts.normalize=True to stretch the image's own range onto [0, 255] "
        "instead, e.g. for a depth map.".format(dtype),
        UserWarning,
        skip_file_prefixes=(_PACKAGE_DIR,),
    )


def _integer_range(img):
    """The exact smallest and largest value of ``img``; (0, 0) if it is empty."""
    if img.size == 0:
        return 0, 0
    return int(img.min()), int(img.max())


def _clip_to_bytes(img):
    """Clip into [0, 255], writing the bytes out directly with no wider copy."""
    out = np.empty(img.shape, dtype=np.uint8)
    # Bounded by the dtype too, so the bound is never out of range for it: an
    # int8 image has nothing above 127 to clip.
    high = min(255, np.iinfo(img.dtype).max)
    return np.clip(img, 0, high, out=out, casting="unsafe")


def _stretch_integers(img, low, high):
    """``_stretch_to_bytes`` for an integer image, from exact offsets.

    ``img - low`` is taken in integers, so 64-bit values past 2**53, which
    float64 rounds together, keep their differences. A span up to
    ``LOOKUP_SPAN`` is then mapped through a table built by the float formula,
    one entry per offset; a wider one is scaled from the offsets in float64.
    """
    span = high - low
    offsets = _offsets(img, low)
    if span <= LOOKUP_SPAN:
        table = _saturate(_stretch_to_bytes(np.arange(span + 1.0), 0, span))
        return table[offsets]
    scaled = offsets.astype(np.float64)
    scaled /= span
    scaled *= 255.0
    return scaled.astype(np.uint8)


def _offsets(img, low):
    """``img - low`` exactly, as unsigned integers as wide as the image.

    The subtraction can overflow the image's own type -- int8 values -128 and
    127 are 255 apart -- but it wraps modulo 2**bits, and every true offset lies
    in [0, 2**bits), so reading the wrapped result as unsigned gives it back
    exactly. numpy cannot subtract bools, so bool is read as uint8 first.
    """
    if img.dtype == np.bool_:
        img = img.view(np.uint8)
    unsigned = np.dtype("u{}".format(img.dtype.itemsize))
    return (img - img.dtype.type(low)).view(unsigned)


#: The converter for each numpy dtype kind an image may hold: bool, signed and
#: unsigned integers, and floats. Complex, object, string and date arrays have
#: no pixel meaning, so they have no entry.
_CONVERTERS = {
    "b": _integer_to_uint8,
    "i": _integer_to_uint8,
    "u": _integer_to_uint8,
    "f": _float_to_uint8,
}
