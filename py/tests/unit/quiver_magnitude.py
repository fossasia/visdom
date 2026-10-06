# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Quiver normalization remains stable across representable vector sizes."""

import warnings

import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "size,dtype",
    [
        (1.0, np.float64),
        (1e200, np.float64),
        (1e-200, np.float64),
        (100, np.int16),
        (10**9, np.int64),
    ],
)
def test_normalization_avoids_intermediate_square_overflow(capture_send, size, dtype):
    x = np.array([[3 * size]], dtype=dtype)
    y = np.array([[4 * size]], dtype=dtype)
    original_x, original_y = x.copy(), y.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        sent = capture_send(
            lambda client: client.quiver(
                x,
                y,
                gridX=np.zeros((1, 1)),
                gridY=np.zeros((1, 1)),
                opts={"normalize": 1, "arrowheads": False},
            )
        )
    trace = sent["payload"]["data"][0]
    assert trace["x"][1] == pytest.approx(0.6)
    assert trace["y"][1] == pytest.approx(0.8)
    np.testing.assert_array_equal(x, original_x)
    np.testing.assert_array_equal(y, original_y)
