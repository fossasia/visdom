# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Decode encoded videos to check pixel conversion at the client boundary."""

import base64
import io
import re
from fractions import Fraction

import av
import numpy as np
import pytest
from visdom import _frame_rate

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


def _stream(sent):
    html = sent["payload"]["data"][0]["content"]
    encoded = re.search(r"data:video/mp4;base64,([^\"]+)", html).group(1)
    with av.open(io.BytesIO(base64.b64decode(encoded))) as container:
        stream = container.streams.video[0]
        frames = sum(1 for _ in container.decode(stream))
        return stream.average_rate, frames


@pytest.mark.parametrize(
    "fps,expected",
    [
        (30, Fraction(30)),
        (30.0, Fraction(30)),
        (np.float64(25.0), Fraction(25)),
        (np.float32(30), Fraction(30)),
        (np.int64(24), Fraction(24)),
        (12.5, Fraction(25, 2)),
        (29.97, Fraction(2997, 100)),
        (30000 / 1001, Fraction(30000, 1001)),
        (Fraction(24000, 1001), Fraction(24000, 1001)),
    ],
    ids=str,
)
def test_video_encodes_at_a_float_fps(capture_send, fps, expected):
    """OpenCV's CAP_PROP_FPS and most video readers give fps as a float."""
    tensor = np.zeros((10, 16, 16, 3), dtype=np.uint8)
    sent = capture_send(lambda client: client.video(tensor=tensor, opts={"fps": fps}))
    assert _stream(sent) == (expected, 10)


@pytest.mark.parametrize(
    "fps,message",
    [(float("inf"), "finite"), (1e-4, "too small")],
    ids=["inf", "tiny"],
)
def test_frame_rate_rejects_what_cannot_be_encoded(fps, message):
    with pytest.raises(ValueError, match=message):
        _frame_rate(fps)
