# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Decode encoded videos to check pixel conversion at the client boundary."""

import base64
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
