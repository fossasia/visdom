# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Decode encoded videos to check pixel conversion at the client boundary."""

import base64
import fractions
import io
import re

import av
import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "dtype,value,expected",
    [
        (np.float32, -0.2, 0),
        (np.float32, 1.2, 255),
        (np.int16, -1, 0),
        (np.int16, 300, 255),
        (np.float32, 0.5, 127),
        (np.uint8, 127, 127),
    ],
)
def test_video_clips_pixels_before_converting_to_bytes(
    capture_send, dtype, value, expected
):
    tensor = np.full((1, 16, 16, 3), value, dtype=dtype)
    original = tensor.copy()
    sent = capture_send(lambda client: client.video(tensor=tensor))
    html = sent["payload"]["data"][0]["content"]
    encoded = re.search(r"data:video/mp4;base64,([^\"]+)", html).group(1)
    with av.open(io.BytesIO(base64.b64decode(encoded))) as container:
        pixels = next(container.decode(video=0)).to_ndarray(format="rgb24")
    # H.264 is lossy; wrapped pixels differ by hundreds rather than a few levels.
    assert np.max(np.abs(pixels.astype(int) - expected)) <= 8
    np.testing.assert_array_equal(tensor, original)


def _encoded_video_rate(sent):
    html = sent["payload"]["data"][0]["content"]
    encoded = re.search(r"data:video/mp4;base64,([^\"]+)", html).group(1)
    with av.open(io.BytesIO(base64.b64decode(encoded))) as container:
        return container.streams.video[0].average_rate


@pytest.mark.parametrize(
    "fps,expected",
    [
        (29.97, fractions.Fraction(2997, 100)),
        (np.float64(29.97), fractions.Fraction(2997, 100)),
        (fractions.Fraction(30000, 1001), fractions.Fraction(30000, 1001)),
        (0.5, fractions.Fraction(1, 2)),
    ],
)
def test_video_fps_preserves_fractional_rate(capture_send, fps, expected):
    tensor = np.full((2, 16, 16, 3), 0.5, dtype=np.float32)
    opts = {"fps": fps}
    sent = capture_send(lambda client: client.video(tensor=tensor, opts=opts))
    assert _encoded_video_rate(sent) == expected
    assert opts == {"fps": fps}
    assert sent["payload"]["opts"]["fps"] == float(expected)


def test_video_fps_int_works(capture_send):
    """Integer FPS values should work as before."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    sent = capture_send(lambda client: client.video(tensor=tensor, opts={"fps": 30}))
    assert _encoded_video_rate(sent) == 30


def test_video_fps_numpy_float64_works(capture_send):
    """NumPy float64 FPS values should work."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    sent = capture_send(lambda client: client.video(tensor=tensor, opts={"fps": np.float64(29.97)}))
    assert _encoded_video_rate(sent) == fractions.Fraction(2997, 100)


def test_video_fps_numpy_int32_works(capture_send):
    """NumPy int32 FPS values should work."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    sent = capture_send(lambda client: client.video(tensor=tensor, opts={"fps": np.int32(30)}))
    assert _encoded_video_rate(sent) == 30


def test_video_fps_bool_raises(capture_send):
    """Boolean FPS values should raise AssertionError."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    with pytest.raises(AssertionError, match="fps should be a number"):
        capture_send(lambda client: client.video(tensor=tensor, opts={"fps": True}))


def test_video_fps_negative_raises(capture_send):
    """Negative FPS values should raise AssertionError."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    with pytest.raises(AssertionError, match="fps must be greater than 0"):
        capture_send(lambda client: client.video(tensor=tensor, opts={"fps": -5}))


def test_video_fps_zero_raises(capture_send):
    """Zero FPS should raise AssertionError."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    with pytest.raises(AssertionError, match="fps must be greater than 0"):
        capture_send(lambda client: client.video(tensor=tensor, opts={"fps": 0}))


def test_video_fps_nan_raises(capture_send):
    """NaN FPS should raise AssertionError."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    with pytest.raises(AssertionError, match="fps must be greater than 0"):
        capture_send(lambda client: client.video(tensor=tensor, opts={"fps": float("nan")}))


def test_video_fps_inf_raises(capture_send):
    """Infinite FPS should raise AssertionError."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    with pytest.raises(AssertionError, match="fps must be greater than 0"):
        capture_send(lambda client: client.video(tensor=tensor, opts={"fps": float("inf")}))


def test_video_fps_string_raises(capture_send):
    """String FPS should raise AssertionError."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    with pytest.raises(AssertionError, match="fps should be a number"):
        capture_send(lambda client: client.video(tensor=tensor, opts={"fps": "30"}))


def test_video_fps_default_when_none(capture_send):
    """Default FPS of 25 should be used when not specified."""
    tensor = np.full((1, 16, 16, 3), 0.5, dtype=np.float32)
    sent = capture_send(lambda client: client.video(tensor=tensor))
    assert _encoded_video_rate(sent) == 25
