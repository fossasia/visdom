#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the client's image, audio, video and SVG payloads.

These methods encode their input into a base64 data URI, so the assertions
decode the payload back into an array and check the pixels the browser would
receive. That is the only way to catch the failure mode this family actually
has: a wrong scaling branch produces a valid payload holding a black image.

Three behaviours pinned here are current, not desired:

* A float image whose maximum is just over 1.0 (1.0001 from a denormalization
  round trip, say) matches neither the [0, 1] nor the [-1, 1] branch, so it is
  truncated to uint8 and arrives **black**. ``opts.normalize=True`` is the
  workaround. See ``test_image_float_just_over_one_arrives_black``.
* ``images`` fills the gaps between tiles with 1.0, which the float branch
  scales to white but the uint8 branch leaves as near-black, so the padding
  colour depends on the input dtype.
* ``images`` insets each tile one pixel past its ``padding``, so the gap below
  and to the right of a tile is a pixel thinner than the gap above and to its
  left. See ``test_images_insets_each_tile_by_an_extra_pixel``.

Everything runs against an ``offline_client`` through the
``capture_send`` fixture — no server, no sockets. ``update_image_slider``'s
index coercion is covered in ``unit/image_slider.py``; only its routing is
asserted here.
"""

import base64
import io
import sys
import wave
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

pytestmark = pytest.mark.unit

requires_assertions = pytest.mark.skipif(
    not __debug__, reason="assert-based validation is stripped under python -O"
)


def content(sent):
    """The single content block of a captured payload."""
    return sent["payload"]["data"][0]["content"]


def decode(sent):
    """Return (mimetype, pixels) for a captured image payload."""
    header, encoded = content(sent)["src"].split(",", 1)
    pixels = np.asarray(Image.open(io.BytesIO(base64.b64decode(encoded))))
    return header, pixels


# ----------------------------------------------------------------- image ----


def test_image_sends_a_png_data_uri(capture_send):
    sent = capture_send(lambda v: v.image(np.zeros((3, 4, 5), dtype=np.uint8)))
    assert sent["endpoint"] == "events"
    assert sent["payload"]["data"][0]["type"] == "image"
    mimetype, pixels = decode(sent)
    assert mimetype == "data:image/png;base64"
    assert pixels.shape == (4, 5, 3)


def test_image_sizes_the_pane_from_the_array(capture_send):
    """CxHxW, so the width comes from the last axis and the height from the middle."""
    sent = capture_send(lambda v: v.image(np.zeros((3, 4, 5), dtype=np.uint8)))
    assert sent["payload"]["opts"]["width"] == 5
    assert sent["payload"]["opts"]["height"] == 4


def test_image_keeps_an_explicit_pane_size(capture_send):
    sent = capture_send(
        lambda v: v.image(
            np.zeros((3, 4, 5), dtype=np.uint8), opts=dict(width=100, height=200)
        )
    )
    assert sent["payload"]["opts"]["width"] == 100
    assert sent["payload"]["opts"]["height"] == 200


@pytest.mark.parametrize(
    "shape, mode_channels",
    [((4, 5), 1), ((1, 4, 5), 1), ((3, 4, 5), 3), ((4, 4, 5), 4)],
)
def test_image_accepts_every_supported_channel_layout(
    capture_send, shape, mode_channels
):
    sent = capture_send(lambda v: v.image(np.zeros(shape, dtype=np.uint8)))
    _, pixels = decode(sent)
    assert pixels.shape[:2] == (4, 5)
    if mode_channels == 1:
        assert pixels.ndim == 2
    else:
        assert pixels.shape[2] == mode_channels


def test_image_carries_the_caption(capture_send):
    sent = capture_send(
        lambda v: v.image(np.zeros((4, 5), dtype=np.uint8), opts=dict(caption="a cat"))
    )
    assert content(sent)["caption"] == "a cat"


def test_image_caption_is_none_when_unset(capture_send):
    sent = capture_send(lambda v: v.image(np.zeros((4, 5), dtype=np.uint8)))
    assert content(sent)["caption"] is None


def test_image_scales_a_unit_range_float_to_bytes(capture_send):
    """0.5 must arrive as mid grey, not as uint8(0.5) == 0."""
    sent = capture_send(lambda v: v.image(np.full((2, 3), 0.5, dtype=np.float32)))
    _, pixels = decode(sent)
    assert set(np.unique(pixels)) == {127}


def test_image_maps_a_signed_float_range_onto_bytes(capture_send):
    """[-1, 1] is shifted rather than clipped, so -1 is black and 1 is white."""
    sent = capture_send(
        lambda v: v.image(np.array([[-1.0, 1.0], [0.0, 0.0]], dtype=np.float32))
    )
    _, pixels = decode(sent)
    assert pixels.tolist() == [[0, 255], [127, 127]]


def test_image_replaces_non_finite_pixels(capture_send):
    """NaN becomes black and the infinities saturate, rather than wrapping."""
    sent = capture_send(
        lambda v: v.image(
            np.array([[np.nan, np.inf], [-np.inf, 0.5]], dtype=np.float32)
        )
    )
    _, pixels = decode(sent)
    assert pixels.tolist() == [[0, 255], [0, 127]]


def test_image_float_just_over_one_arrives_black(capture_send):
    """Pinned defect: one pixel at 1.0001 costs the whole image its brightness.

    The value misses both float branches by 1e-4, so nothing is scaled and
    ``uint8`` truncates every 0.9 to 0. Reported as issue #602.
    """
    img = np.full((3, 4, 4), 0.9, dtype=np.float32)
    img[0, 0, 0] = 1.0001
    sent = capture_send(lambda v: v.image(img))
    _, pixels = decode(sent)
    assert pixels.max() <= 1


def test_image_normalize_rescues_the_out_of_range_float(capture_send):
    """opts.normalize min-max scales instead of testing the range, so it works."""
    img = np.full((3, 4, 4), 0.9, dtype=np.float32)
    img[0, 0, 0] = 1.0001
    sent = capture_send(lambda v: v.image(img, opts=dict(normalize=True)))
    _, pixels = decode(sent)
    assert pixels.min() == 0
    assert pixels.max() == 255


def test_image_normalize_of_a_flat_image_is_black(capture_send):
    """A zero-width range cannot be stretched, so it collapses rather than dividing."""
    sent = capture_send(
        lambda v: v.image(np.full((4, 4), 7.0), opts=dict(normalize=True))
    )
    _, pixels = decode(sent)
    assert set(np.unique(pixels)) == {0}


def test_image_encodes_as_jpeg_when_a_quality_is_given(capture_send):
    sent = capture_send(
        lambda v: v.image(np.zeros((3, 4, 4), dtype=np.uint8), opts=dict(jpgquality=80))
    )
    assert decode(sent)[0] == "data:image/jpeg;base64"


def test_image_keeps_rgba_as_png_despite_a_jpeg_quality(capture_send):
    """JPEG has no alpha channel, so the request is ignored rather than failing."""
    sent = capture_send(
        lambda v: v.image(np.zeros((4, 2, 2), dtype=np.uint8), opts=dict(jpgquality=80))
    )
    mimetype, pixels = decode(sent)
    assert mimetype == "data:image/png;base64"
    assert pixels.shape[2] == 4


def test_image_store_history_switches_the_pane_type(capture_send):
    sent = capture_send(
        lambda v: v.image(
            np.zeros((4, 4), dtype=np.uint8), opts=dict(store_history=True)
        )
    )
    assert sent["payload"]["data"][0]["type"] == "image_history"


def test_image_store_history_creates_the_window_first(capture_send):
    """With no window yet the frame has to go through /events, not /update."""
    sent = capture_send(
        lambda v: v.image(
            np.zeros((4, 4), dtype=np.uint8), win="w1", opts=dict(store_history=True)
        ),
        win_exists=False,
    )
    assert sent["endpoint"] == "events"


def test_image_store_history_appends_to_an_existing_window(capture_send):
    """Once the pane exists the frame is an update, so the slider grows."""
    sent = capture_send(
        lambda v: v.image(
            np.zeros((4, 4), dtype=np.uint8), win="w1", opts=dict(store_history=True)
        ),
        win_exists=True,
    )
    assert sent["endpoint"] == "update"


def test_image_store_history_without_preflight_always_updates(
    capture_send, offline_client
):
    """The server decides: /update appends the frame, or creates the pane."""
    offline_client.use_preflight_checks = False
    with patch.object(offline_client, "win_exists") as probe:
        sent = capture_send(
            lambda v: v.image(
                np.zeros((4, 4), dtype=np.uint8),
                win="w1",
                opts=dict(store_history=True),
            )
        )
    assert not probe.called
    assert sent["endpoint"] == "update"
    assert sent["payload"]["append"]


def test_image_store_history_without_preflight_still_needs_a_window_id(
    capture_send, offline_client
):
    """There is nothing to update without a window, so it stays an event."""
    offline_client.use_preflight_checks = False
    sent = capture_send(
        lambda v: v.image(
            np.zeros((4, 4), dtype=np.uint8), opts=dict(store_history=True)
        )
    )
    assert sent["endpoint"] == "events"
    assert "append" not in sent["payload"]


def test_image_store_history_without_a_window_id_stays_an_event(capture_send):
    sent = capture_send(
        lambda v: v.image(
            np.zeros((4, 4), dtype=np.uint8), opts=dict(store_history=True)
        ),
        win_exists=True,
    )
    assert sent["endpoint"] == "events"


@pytest.mark.parametrize(
    "img, message",
    [
        (
            np.zeros((5, 2, 2), dtype=np.uint8),
            "Unsupported number of image channels: 5",
        ),
        (np.zeros((2, 2, 2, 2), dtype=np.uint8), "Unsupported image dimensions: 4"),
        (np.zeros(4, dtype=np.uint8), "Unsupported image dimensions: 1"),
    ],
)
def test_image_rejects_unsupported_shapes(offline_client, img, message):
    with pytest.raises(ValueError, match=message):
        offline_client.image(img)


# ---------------------------------------------------------------- images ----


def test_images_tiles_a_batch_into_a_grid(capture_send):
    """Four 8x8 images at the default nrow land on one row, each cell padded by 2."""
    sent = capture_send(lambda v: v.images(np.zeros((4, 3, 8, 8), dtype=np.uint8)))
    _, pixels = decode(sent)
    assert pixels.shape == (8 + 4, (8 + 4) * 4, 3)


def test_images_wraps_onto_further_rows(capture_send):
    sent = capture_send(
        lambda v: v.images(np.zeros((4, 3, 4, 4), dtype=np.uint8), nrow=2)
    )
    _, pixels = decode(sent)
    assert pixels.shape == ((4 + 4) * 2, (4 + 4) * 2, 3)


def test_images_accepts_a_list_of_arrays(capture_send):
    sent = capture_send(
        lambda v: v.images([np.zeros((3, 4, 4), dtype=np.uint8)] * 2, nrow=2)
    )
    _, pixels = decode(sent)
    assert pixels.shape == (4 + 4, (4 + 4) * 2, 3)


def test_images_tiles_without_padding(capture_send):
    """Regression: the cell offset used to overrun the grid and raise on padding=0."""
    sent = capture_send(
        lambda v: v.images(np.ones((2, 3, 4, 4), dtype=np.float32), nrow=2, padding=0)
    )
    _, pixels = decode(sent)
    assert pixels.shape == (4, 8, 3)


def test_images_insets_each_tile_by_an_extra_pixel(capture_send):
    """Pinned quirk: the tile sits one pixel low and right inside its cell.

    ``padding`` is added on all four sides of the cell but the tile starts
    ``padding + 1`` into it, so the gap below and to the right of each tile is
    one pixel thinner than the gap above and to its left.
    """
    sent = capture_send(
        lambda v: v.images(np.zeros((2, 3, 4, 4), dtype=np.float32), nrow=2, padding=1)
    )
    _, pixels = decode(sent)
    assert pixels.shape == (4 + 2, (4 + 2) * 2, 3)
    assert (pixels[:2] == 255).all()  # two rows above, none below
    assert (pixels[2:, 2:6] == 0).all()
    assert (pixels[2:, 8:12] == 0).all()


def test_images_padding_colour_follows_the_input_dtype(capture_send):
    """Pinned quirk: the gaps are filled with 1.0 before the scaling branch runs.

    A float batch is scaled up so the fill becomes white; a uint8 batch takes
    the clipping branch instead, so the same fill stays at 1 — near black.
    """
    float_grid = capture_send(
        lambda v: v.images(np.full((2, 3, 2, 2), 0.8, dtype=np.float32), nrow=2)
    )
    uint8_grid = capture_send(
        lambda v: v.images(np.full((2, 3, 2, 2), 200, dtype=np.uint8), nrow=2)
    )
    assert decode(float_grid)[1][0, 0].tolist() == [255, 255, 255]
    assert decode(uint8_grid)[1][0, 0].tolist() == [1, 1, 1]


def test_images_expands_a_single_channel_batch_to_rgb(capture_send):
    sent = capture_send(lambda v: v.images(np.zeros((4, 1, 4, 4), dtype=np.uint8)))
    _, pixels = decode(sent)
    assert pixels.shape[2] == 3


def test_images_passes_a_single_image_straight_through(capture_send):
    """A 3D input is one image, so no grid is built and no padding is added."""
    sent = capture_send(lambda v: v.images(np.zeros((3, 4, 4), dtype=np.uint8)))
    _, pixels = decode(sent)
    assert pixels.shape == (4, 4, 3)


def test_images_promotes_a_grayscale_image_to_three_channels(capture_send):
    sent = capture_send(lambda v: v.images(np.zeros((4, 4), dtype=np.uint8)))
    _, pixels = decode(sent)
    assert pixels.shape == (4, 4, 3)


def _compressible(channels=3, size=128):
    """A smooth image, so a PNG level really does change the payload size.

    Random pixels are incompressible -- level 0 and level 9 come out within
    bytes of each other -- which makes noise useless for asserting that the
    dial is wired up at all.
    """
    ramp = np.linspace(0, 255, size, dtype=np.uint8)
    plane = np.broadcast_to(ramp, (size, size))
    return np.stack([plane] * channels)


def _grid_dtype(client, batch, **kwargs):
    """The dtype of the grid ``images`` hands to ``image``."""
    seen = []
    with patch.object(
        client, "image", side_effect=lambda g, *a, **k: seen.append(g.dtype)
    ):
        client.images(batch, **kwargs)
    assert len(seen) == 1
    return seen[0]


def test_images_grid_is_byte_identical_across_shapes_and_dtypes(capture_send):
    """The vectorised tile fill must place every tile where the loop did.

    The grid is built by writing one strided block per row of cells rather
    than one block per tile, which is only valid if the slots it addresses are
    exactly the old ``h_start:h_end``/``w_start:w_end`` windows. A partial last
    row, ``padding=0`` (where the extra inset pixel is dropped) and a batch
    smaller than ``nrow`` are the three ways that arithmetic can drift, so each
    is checked against the pixels the reference loop produces.
    """

    def reference(tensor, nrow, padding):
        nmaps = tensor.shape[0]
        xmaps = min(nrow, nmaps)
        ymaps = int(np.ceil(nmaps / xmaps))
        height = tensor.shape[2] + 2 * padding
        width = tensor.shape[3] + 2 * padding
        offset = padding + 1 if padding > 0 else 0
        grid = np.ones([tensor.shape[1], height * ymaps, width * xmaps])
        k = 0
        for y in range(ymaps):
            for x in range(xmaps):
                if k >= nmaps:
                    break
                h_start = y * height + offset
                w_start = x * width + offset
                grid[
                    :,
                    h_start : h_start + tensor.shape[2],
                    w_start : w_start + tensor.shape[3],
                ] = tensor[k]
                k += 1
        return grid

    rng = np.random.default_rng(0)
    batches = [
        rng.integers(0, 256, (4, 3, 6, 6), dtype=np.uint8),  # exactly one row
        rng.integers(0, 256, (10, 3, 5, 5), dtype=np.uint8),  # partial last row
        rng.integers(0, 256, (3, 3, 4, 4), dtype=np.uint8),  # fewer than nrow
        rng.integers(0, 2, (6, 3, 4, 4), dtype=np.uint8),  # uint8 that still scales
        rng.random((5, 3, 4, 4)),  # float keeps the float grid
    ]
    for tensor in batches:
        for nrow, padding in ((8, 2), (4, 1), (2, 0), (3, 3)):
            sent = capture_send(
                lambda v, t=tensor, n=nrow, p=padding: v.images(t, nrow=n, padding=p)
            )
            _, pixels = decode(sent)
            expected = reference(tensor, nrow, padding)
            # `image()` is what turns the grid into pixels, so compare through it
            through_image = capture_send(lambda v, g=expected: v.image(g))
            assert np.array_equal(pixels, decode(through_image)[1]), (
                tensor.dtype,
                tensor.shape,
                nrow,
                padding,
            )


def test_images_keeps_a_uint8_batch_in_uint8(offline_client):
    """A uint8 batch no longer widens to float64 on its way through the grid.

    The grid used to be ``np.ones(...)`` -- float64 -- which cost eight bytes a
    pixel and then took ``image()``'s float branch with its full-size
    temporaries. This is the observable half of that: the pixels are unchanged,
    so the test watches the dtype the grid is actually built with.
    """
    batch = np.full((4, 3, 4, 4), 200, dtype=np.uint8)
    assert _grid_dtype(offline_client, batch) == np.uint8


def test_images_keeps_the_float_grid_for_a_low_valued_uint8_batch(offline_client):
    """The dtype shortcut is only taken where it cannot change a pixel.

    ``image()`` stretches anything whose whole range fits in [0, 1] -- and the
    grid's fill value of 1 means a uint8 batch holding only 0s and 1s is such a
    grid. Keeping that case in float64 preserves the stretch pinned by
    ``test_images_padding_colour_follows_the_input_dtype``.
    """
    batch = np.ones((2, 3, 2, 2), dtype=np.uint8)
    assert _grid_dtype(offline_client, batch) == np.float64


def test_images_keeps_the_float_grid_when_normalize_is_requested(offline_client):
    """``opts.normalize`` is implemented only inside ``image()``'s float branch.

    A uint8 grid never reaches that branch, so taking the dtype shortcut under
    ``normalize=True`` would accept the option and silently do nothing. The
    batch here is uint8 with a maximum above 1, which is exactly what the
    shortcut is for -- so the float grid can only be coming from the option.
    """
    batch = np.full((4, 3, 4, 4), 200, dtype=np.uint8)
    assert _grid_dtype(offline_client, batch, opts={"normalize": True}) == np.float64
    assert _grid_dtype(offline_client, batch, opts={"normalize": False}) == np.uint8


def test_images_normalize_still_stretches_a_uint8_batch(capture_send):
    """And the stretch itself reaches the pixels, not just the grid dtype.

    A batch spanning only part of [0, 255] is min-max scaled onto the whole
    range, so the decoded grid has to reach both ends; without the option it
    keeps the input's own, narrower range.
    """
    batch = np.full((4, 3, 4, 4), 200, dtype=np.uint8)
    batch[:, :, 0, 0] = 40
    stretched = decode(
        capture_send(lambda v: v.images(batch, opts={"normalize": True}))
    )[1]
    plain = decode(capture_send(lambda v: v.images(batch)))[1]
    assert (stretched.min(), stretched.max()) == (0, 255)
    assert (plain.min(), plain.max()) == (1, 200)


def test_images_forwards_the_compress_level(capture_send):
    """``images`` hands its opts to ``image``, so the PNG dial reaches the grid."""
    batch = np.stack([_compressible(size=32)] * 4)
    fast = capture_send(lambda v: v.images(batch, opts=dict(compresslevel=0)))
    small = capture_send(lambda v: v.images(batch, opts=dict(compresslevel=9)))
    assert len(content(fast)["src"]) > len(content(small)["src"])
    assert np.array_equal(decode(fast)[1], decode(small)[1])


def test_image_compress_level_changes_the_payload_not_the_pixels(capture_send):
    """``opts.compresslevel`` is a speed/size dial, so PNG stays lossless.

    Level 0 stores the image uncompressed and level 9 spends the most time on
    it, which is visible as a payload-size ordering; the decoded pixels have to
    be identical either way, since a lossy level would be a silent data change.
    """
    img = _compressible()
    stored = capture_send(lambda v: v.image(img, opts=dict(compresslevel=0)))
    packed = capture_send(lambda v: v.image(img, opts=dict(compresslevel=9)))
    assert len(content(stored)["src"]) > len(content(packed)["src"])
    assert np.array_equal(decode(stored)[1], decode(packed)[1])
    assert decode(stored)[0] == "data:image/png;base64"


def test_image_default_compression_is_unchanged(capture_send):
    """Omitting the opt must encode exactly as before: PIL's default of 6.

    The point of exposing the level is that nobody's payload size moves unless
    they ask, so an unset opt and an explicit 6 have to produce the same bytes.
    """
    img = np.random.default_rng(1).integers(0, 256, (3, 48, 48), dtype=np.uint8)
    default = capture_send(lambda v: v.image(img))
    explicit = capture_send(lambda v: v.image(img, opts=dict(compresslevel=6)))
    assert content(default)["src"] == content(explicit)["src"]


def test_image_jpeg_quality_wins_over_a_compress_level(capture_send):
    """``compress_level`` is a PNG argument, so JPEG must not be handed one.

    Passing both used to be impossible; now it has to pick the JPEG path and
    drop the PNG dial rather than fail inside PIL.
    """
    img = np.random.default_rng(2).integers(0, 256, (3, 16, 16), dtype=np.uint8)
    sent = capture_send(
        lambda v: v.image(img, opts=dict(jpgquality=80, compresslevel=1))
    )
    assert decode(sent)[0] == "data:image/jpeg;base64"


def test_image_rgba_with_a_jpeg_quality_still_takes_the_compress_level(capture_send):
    """An RGBA image stays PNG despite a quality, so the PNG dial still applies."""
    img = _compressible(channels=4)
    stored = capture_send(
        lambda v: v.image(img, opts=dict(jpgquality=80, compresslevel=0))
    )
    packed = capture_send(
        lambda v: v.image(img, opts=dict(jpgquality=80, compresslevel=9))
    )
    assert decode(stored)[0] == "data:image/png;base64"
    assert len(content(stored)["src"]) > len(content(packed)["src"])


def test_image_heatmap_takes_a_compress_level(capture_send):
    img = _compressible()
    heatmap = np.broadcast_to(np.linspace(0, 1, 128), (128, 128))
    stored = capture_send(
        lambda v: v.image_heatmap(img, heatmap, opts=dict(compresslevel=0))
    )
    packed = capture_send(
        lambda v: v.image_heatmap(img, heatmap, opts=dict(compresslevel=9))
    )
    assert len(content(stored)["src"]) > len(content(packed)["src"])
    assert np.array_equal(decode(stored)[1], decode(packed)[1])


# --------------------------------------------------------- image_heatmap ----


def test_image_heatmap_blends_into_a_single_rgb_image(capture_send):
    """The overlay is composited in Python, so the frontend just sees an image."""
    sent = capture_send(
        lambda v: v.image_heatmap(np.zeros((4, 4), dtype=np.uint8), np.ones((4, 4)))
    )
    assert sent["endpoint"] == "events"
    assert sent["payload"]["data"][0]["type"] == "image"
    mimetype, pixels = decode(sent)
    assert mimetype == "data:image/png;base64"
    assert pixels.shape == (4, 4, 3)


def test_image_heatmap_sizes_the_pane_from_the_image(capture_send):
    sent = capture_send(
        lambda v: v.image_heatmap(np.zeros((3, 4, 5), dtype=np.uint8), np.ones((4, 5)))
    )
    assert sent["payload"]["opts"]["width"] == 5
    assert sent["payload"]["opts"]["height"] == 4


def test_image_heatmap_falls_back_to_a_blue_red_ramp_without_matplotlib(capture_send):
    """The colormap import is optional, so a missing matplotlib must not raise."""
    with patch.dict(sys.modules, {"matplotlib": None}):
        sent = capture_send(
            lambda v: v.image_heatmap(
                np.zeros((2, 2), dtype=np.uint8), np.array([[0.0, 1.0], [1.0, 0.0]])
            )
        )
    _, pixels = decode(sent)
    assert pixels.tolist() == [[[0, 0, 0], [127, 0, 0]], [[127, 0, 0], [0, 0, 0]]]


def test_image_heatmap_alpha_controls_the_blend_strength(capture_send):
    """alpha=0 leaves the base image untouched however hot the heatmap is."""
    with patch.dict(sys.modules, {"matplotlib": None}):
        sent = capture_send(
            lambda v: v.image_heatmap(
                np.full((2, 2), 200, dtype=np.uint8),
                np.ones((2, 2)),
                opts=dict(alpha=0),
            )
        )
    _, pixels = decode(sent)
    assert (pixels == 200).all()


def test_image_heatmap_rescales_a_heatmap_outside_the_unit_range(capture_send):
    """Raw activations rarely land in [0, 1], so they are min-max scaled first."""
    with patch.dict(sys.modules, {"matplotlib": None}):
        raw = capture_send(
            lambda v: v.image_heatmap(
                np.zeros((2, 2), dtype=np.uint8), np.array([[0.0, 10.0], [20.0, 30.0]])
            )
        )
        unit = capture_send(
            lambda v: v.image_heatmap(
                np.zeros((2, 2), dtype=np.uint8),
                np.array([[0.0, 1 / 3], [2 / 3, 1.0]]),
            )
        )
    assert decode(raw)[1].tolist() == decode(unit)[1].tolist()


def test_image_heatmap_replaces_non_finite_heatmap_values(capture_send):
    """NaN reads as cold and the infinities clamp, instead of poisoning the blend."""
    with patch.dict(sys.modules, {"matplotlib": None}):
        sent = capture_send(
            lambda v: v.image_heatmap(
                np.zeros((2, 2), dtype=np.uint8),
                np.array([[np.nan, np.inf], [-np.inf, 1.0]]),
            )
        )
    _, pixels = decode(sent)
    assert pixels[0, 0].tolist() == [0, 0, 0]
    assert pixels[0, 1].tolist() == pixels[1, 1].tolist()


def test_image_heatmap_encodes_as_jpeg_when_a_quality_is_given(capture_send):
    sent = capture_send(
        lambda v: v.image_heatmap(
            np.zeros((4, 4), dtype=np.uint8), np.ones((4, 4)), opts=dict(jpgquality=80)
        )
    )
    assert decode(sent)[0] == "data:image/jpeg;base64"


def test_image_heatmap_carries_the_caption(capture_send):
    sent = capture_send(
        lambda v: v.image_heatmap(
            np.zeros((4, 4), dtype=np.uint8), np.ones((4, 4)), opts=dict(caption="cam")
        )
    )
    assert content(sent)["caption"] == "cam"


def test_image_heatmap_does_not_mutate_the_callers_opts(capture_send):
    """Unlike image(), this one copies, so the width is not written back."""
    opts = {"caption": "cam"}
    capture_send(
        lambda v: v.image_heatmap(
            np.zeros((4, 4), dtype=np.uint8), np.ones((4, 4)), opts=opts
        )
    )
    assert opts == {"caption": "cam"}


@pytest.mark.parametrize(
    "args, kwargs, message",
    [
        (
            (np.zeros((2, 2), dtype=np.uint8), np.ones((3, 3))),
            {},
            r"heatmap shape \(3, 3\) does not match image \(2,2\)",
        ),
        (
            (np.zeros((5, 2, 2), dtype=np.uint8), np.ones((2, 2))),
            {},
            "img must have 1, 3, or 4 channels",
        ),
        (
            (np.zeros((2, 2, 2, 2), dtype=np.uint8), np.ones((2, 2))),
            {},
            "img must be 2D",
        ),
        (
            (np.zeros((2, 2), dtype=np.uint8), np.ones((2, 2))),
            {"opts": {"alpha": 2}},
            r"alpha must be in \[0, 1\]",
        ),
    ],
)
def test_image_heatmap_rejects_malformed_input(offline_client, args, kwargs, message):
    with pytest.raises(ValueError, match=message):
        offline_client.image_heatmap(*args, **kwargs)


# ---------------------------------------------- image_select / the slider ----


def test_image_select_updates_the_frame_without_resending_it(capture_send):
    sent = capture_send(lambda v: v.image_select("w1", 3))
    assert sent["endpoint"] == "update"
    assert sent["payload"]["win"] == "w1"
    assert sent["payload"]["data"] == [{"type": "image_update_selected", "selected": 3}]


def test_image_select_passes_the_environment_through(capture_send):
    sent = capture_send(lambda v: v.image_select("w1", 0, env="e1"))
    assert sent["payload"]["eid"] == "e1"


@requires_assertions
@pytest.mark.parametrize(
    "args, message",
    [
        ((None, 1), "Must specify a window"),
        (("w1", 1.5), "selected must be an integer"),
        (("w1", "1"), "selected must be an integer"),
    ],
)
def test_image_select_rejects_malformed_input(offline_client, args, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.image_select(*args)


def test_update_image_slider_passes_the_environment_through(capture_send):
    """Index coercion is covered in unit/image_slider.py; this is the routing."""
    sent = capture_send(lambda v: v.update_image_slider("w1", 2, env="e1"))
    assert sent["endpoint"] == "update"
    assert sent["payload"]["eid"] == "e1"


@requires_assertions
def test_update_image_slider_requires_a_window(offline_client):
    with pytest.raises(AssertionError, match="requires a window id"):
        offline_client.update_image_slider(None, 1)


# ----------------------------------------------------------------- audio ----


def test_audio_is_sent_as_a_text_pane_holding_a_player(capture_send):
    sent = capture_send(lambda v: v.audio(tensor=np.zeros(16)))
    assert sent["endpoint"] == "events"
    assert sent["payload"]["data"][0]["type"] == "text"
    assert "<audio controls>" in content(sent)


def test_audio_encodes_a_tensor_as_wav(capture_send):
    sent = capture_send(lambda v: v.audio(tensor=np.sin(np.linspace(0, 1, 64))))
    assert 'type="audio/wav"' in content(sent)
    assert "data:audio/wav;base64," in content(sent)


def test_audio_defaults_the_sample_frequency_and_pane_size(capture_send):
    sent = capture_send(lambda v: v.audio(tensor=np.zeros(16)))
    assert sent["payload"]["opts"]["sample_frequency"] == 44100
    assert sent["payload"]["opts"]["height"] == 80
    assert sent["payload"]["opts"]["width"] == 330


def test_audio_survives_an_all_zero_waveform(capture_send):
    """Normalizing silence would divide by its zero maximum, so it is skipped."""
    sent = capture_send(lambda v: v.audio(tensor=np.zeros(16)))
    assert "data:audio/wav;base64," in content(sent)


def test_audio_accepts_a_stereo_tensor(capture_send):
    sent = capture_send(lambda v: v.audio(tensor=np.zeros((16, 2))))
    assert "<audio controls>" in content(sent)


def test_audio_accepts_mono_channel_first(capture_send):
    sent = capture_send(lambda v: v.audio(tensor=np.zeros((1, 16))))
    assert "<audio controls>" in content(sent)


def test_audio_accepts_stereo_channel_first(capture_send):
    sent = capture_send(lambda v: v.audio(tensor=np.zeros((2, 16))))
    assert "<audio controls>" in content(sent)


def test_audio_accepts_mono_column(capture_send):
    sent = capture_send(lambda v: v.audio(tensor=np.zeros((16, 1))))
    assert "<audio controls>" in content(sent)


@pytest.mark.parametrize("extension", ["wav", "mp3", "ogg", "flac"])
def test_audio_maps_the_file_extension_to_a_mime_type(
    capture_send, tmp_path, extension
):
    path = tmp_path / ("clip." + extension)
    path.write_bytes(b"not really audio")
    sent = capture_send(lambda v: v.audio(audiofile=str(path)))
    assert 'type="audio/{}"'.format(extension) in content(sent)


def test_audio_escapes_the_caption(capture_send):
    """The caption is interpolated into markup, so it has to be escaped."""
    sent = capture_send(
        lambda v: v.audio(tensor=np.zeros(16), opts=dict(caption="a & <b>"))
    )
    assert "<p>a &amp; &lt;b&gt;</p>" in content(sent)


@requires_assertions
def test_audio_rejects_an_unknown_file_type(offline_client, tmp_path):
    path = tmp_path / "clip.xyz"
    path.write_bytes(b"x")
    with pytest.raises(AssertionError, match="unknown audio type: xyz"):
        offline_client.audio(audiofile=str(path))


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "should specify audio tensor or file"),
        (dict(tensor=np.zeros((3, 3))), "tensor should be 1D vector or 2D matrix"),
        (dict(tensor=np.zeros(0)), "tensor should not be empty"),
        (dict(tensor=np.zeros((0, 2))), "tensor should not be empty"),
    ],
)
def test_audio_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.audio(**kwargs)


# ----------------------------------------------------------------- video ----


def test_video_is_sent_as_a_text_pane_holding_a_player(capture_send, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"not really video")
    sent = capture_send(lambda v: v.video(videofile=str(path)))
    assert sent["payload"]["data"][0]["type"] == "text"
    assert "<video controls" in content(sent)
    assert "data:video/mp4;base64," in content(sent)


@pytest.mark.parametrize(
    "extension, mimetype",
    [("mp4", "mp4"), ("ogv", "ogg"), ("avi", "avi"), ("webm", "webm")],
)
def test_video_maps_the_file_extension_to_a_mime_type(
    capture_send, tmp_path, extension, mimetype
):
    path = tmp_path / ("clip." + extension)
    path.write_bytes(b"x")
    sent = capture_send(lambda v: v.video(videofile=str(path)))
    assert 'type="video/{}"'.format(mimetype) in content(sent)


def test_video_defaults_to_a_passive_player(capture_send, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    sent = capture_send(lambda v: v.video(videofile=str(path)))
    assert "<video controls >" in content(sent)
    assert sent["payload"]["opts"]["fps"] == 25
    assert sent["payload"]["opts"]["loop"] is False
    assert sent["payload"]["opts"]["autoplay"] is False


def test_video_turns_the_playback_opts_into_tag_flags(capture_send, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    sent = capture_send(
        lambda v: v.video(videofile=str(path), opts=dict(autoplay=True, loop=True))
    )
    assert "<video controls autoplay loop>" in content(sent)


def test_video_escapes_the_caption(capture_send, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    sent = capture_send(
        lambda v: v.video(videofile=str(path), opts=dict(caption="a & <b>"))
    )
    assert "<p>a &amp; &lt;b&gt;</p>" in content(sent)


@requires_assertions
def test_video_rejects_an_unknown_file_type(offline_client, tmp_path):
    path = tmp_path / "clip.xyz"
    path.write_bytes(b"x")
    with pytest.raises(AssertionError, match="unknown video type: xyz"):
        offline_client.video(videofile=str(path))


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "should specify video tensor or file"),
        (dict(tensor=np.zeros((2, 2, 2))), "video should be in 4D tensor"),
        (
            dict(tensor=np.zeros((2, 2, 2, 3)), dim="XYZ"),
            "dimension argument should be LxHxWxC or LxCxHxW",
        ),
    ],
)
def test_video_rejects_malformed_input(offline_client, kwargs, message):
    """The shape checks run before the deferred PyAV import, so no encoder is needed."""
    with pytest.raises(AssertionError, match=message):
        offline_client.video(**kwargs)


# ------------------------------------------------------------------- svg ----


def test_svg_is_sent_as_a_text_pane(capture_send):
    sent = capture_send(lambda v: v.svg(svgstr="<svg width='1'><rect/></svg>"))
    assert sent["endpoint"] == "events"
    assert sent["payload"]["data"][0]["type"] == "text"
    assert content(sent) == "<svg width='1'><rect/></svg>"


def test_svg_extracts_the_markup_from_its_surroundings(capture_send):
    """An XML prologue or a trailing newline must not reach the pane."""
    sent = capture_send(
        lambda v: v.svg(svgstr="<?xml version='1.0'?><svg a='1'><g/></svg>\n")
    )
    assert content(sent) == "<svg a='1'><g/></svg>"


def test_svg_reads_a_file(capture_send, tmp_path):
    path = tmp_path / "drawing.svg"
    path.write_text("<svg width='2'><rect/></svg>")
    sent = capture_send(lambda v: v.svg(svgfile=str(path)))
    assert content(sent) == "<svg width='2'><rect/></svg>"


@pytest.mark.parametrize("text", ["line one\nline two", "研究 café", r"literal \n path"])
def test_svg_file_preserves_text(capture_send, tmp_path, text):
    """File input must produce the same SVG text as the string API."""
    markup = "<svg width='2'>\n<text>{}</text>\n</svg>".format(text)
    path = tmp_path / "drawing.svg"
    path.write_bytes((markup + "\n").encode("utf-8"))
    sent = capture_send(lambda v: v.svg(svgfile=str(path)))
    assert content(sent) == markup


def test_svg_passes_opts_through(capture_send):
    sent = capture_send(
        lambda v: v.svg(svgstr="<svg a='1'><g/></svg>", opts=dict(title="diagram"))
    )
    assert sent["payload"]["opts"]["title"] == "diagram"


@requires_assertions
@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "should specify SVG string or filename"),
        (dict(svgstr="no markup here"), "could not parse SVG string"),
    ],
)
def test_svg_rejects_malformed_input(offline_client, kwargs, message):
    with pytest.raises(AssertionError, match=message):
        offline_client.svg(**kwargs)
