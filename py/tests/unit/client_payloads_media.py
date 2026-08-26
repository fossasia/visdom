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

Four behaviours pinned here are current, not desired:

* A float image whose maximum is just over 1.0 (1.0001 from a denormalization
  round trip, say) matches neither the [0, 1] nor the [-1, 1] branch, so it is
  truncated to uint8 and arrives **black**. ``opts.normalize=True`` is the
  workaround. See ``test_image_float_just_over_one_arrives_black``.
* ``images`` fills the gaps between tiles with 1.0, which the float branch
  scales to white but the uint8 branch leaves as near-black, so the padding
  colour depends on the input dtype.
* ``images`` writes each tile one pixel into its cell, so the gap is a pixel
  wider above and to the left of a tile than below and to the right of it, and
  ``padding=0`` raises because the last row and column no longer fit.
* ``svg(svgfile=...)`` stringifies the raw bytes, so newlines in the file reach
  the browser as literal backslash-n.

Everything runs against a ``Visdom(send=False)`` client through the
``capture_send`` fixture — no server, no sockets. ``update_image_slider``'s
index coercion is covered in ``unit/image_slider.py``; only its routing is
asserted here.
"""

import base64
import io
import sys
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


def test_images_rejects_zero_padding(capture_send):
    """Pinned quirk: `padding=0` raises instead of tiling the batch edge to edge.

    Each tile is written at a one-pixel offset into its cell, so the last row
    and column fall outside a cell that has no padding to absorb them and the
    assignment into the grid fails to broadcast.
    """
    with pytest.raises(ValueError, match="broadcast"):
        capture_send(
            lambda v: v.images(
                np.ones((2, 3, 4, 4), dtype=np.float32), nrow=2, padding=0
            )
        )


def test_images_offsets_each_tile_by_one_pixel(capture_send):
    """Pinned quirk: a tile sits one pixel low and right inside its own cell.

    With `padding=1` the cell is six pixels square, but the gap ends up two
    pixels wide above and to the left of the image and zero wide below and to
    the right of it, rather than one pixel on every side.
    """
    sent = capture_send(
        lambda v: v.images(np.zeros((2, 3, 4, 4), dtype=np.float32), nrow=2, padding=1)
    )
    _, pixels = decode(sent)
    assert pixels.shape == (4 + 2, (4 + 2) * 2, 3)

    white_rows = [bool((row == 255).all()) for row in pixels]
    assert white_rows == [True, True, False, False, False, False]

    white_cols = [bool((pixels[:, c] == 255).all()) for c in range(pixels.shape[1])]
    assert white_cols == [True, True] + [False] * 4 + [True, True] + [False] * 4


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


def test_svg_file_newlines_arrive_escaped(capture_send, tmp_path):
    """Pinned defect: the file is read as bytes and stringified, not decoded.

    ``str(b"...")`` renders every newline as a literal backslash-n, so a
    pretty-printed SVG reaches the browser with escapes in its markup.
    """
    path = tmp_path / "drawing.svg"
    path.write_text("<svg width='2'>\n  <rect/>\n</svg>\n")
    sent = capture_send(lambda v: v.svg(svgfile=str(path)))
    assert "\\n" in content(sent)
    assert "\n" not in content(sent)


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
