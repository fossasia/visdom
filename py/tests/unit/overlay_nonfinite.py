# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Rescaling finite activations must preserve non-finite overlay semantics."""

import base64
from io import BytesIO
import sys
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw,normalized",
    [
        ([-5.0, -1.0, np.nan, np.inf, -np.inf], [0.0, 1.0, 0.0, 1.0, 0.0]),
        ([2.0, 6.0, np.nan, np.inf, -np.inf], [0.0, 1.0, 0.0, 1.0, 0.0]),
        ([-2.0, -2.0, np.nan, np.inf, -np.inf], [0.0, 0.0, 0.0, 1.0, 0.0]),
        ([2.0, 2.0, np.nan, np.inf, -np.inf], [0.0, 0.0, 0.0, 1.0, 0.0]),
        ([0.2, 0.8, np.nan, np.inf, -np.inf], [0.2, 0.8, 0.0, 1.0, 0.0]),
        ([np.nan, np.inf, -np.inf], [0.0, 1.0, 0.0]),
    ],
)
def test_overlay_rescaling_preserves_missing_and_infinite_values(
    capture_send, raw, normalized
):
    image = np.full((1, len(raw)), 100, dtype=np.uint8)
    heatmap = np.array([raw], dtype=np.float32)
    original = heatmap.copy()

    def render(values):
        sent = capture_send(lambda client: client.image_heatmap(image, values))
        source = sent["payload"]["data"][0]["content"]["src"]
        encoded = source.split(",", 1)[1]
        with Image.open(BytesIO(base64.b64decode(encoded))) as png:
            return np.asarray(png).copy()

    with patch.dict(sys.modules, {"matplotlib": None}):
        actual = render(heatmap)
        expected = render(np.array([normalized], dtype=np.float32))
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(heatmap, original)
    np.testing.assert_array_equal(image, 100)
