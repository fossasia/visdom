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


@pytest.mark.parametrize(
    "size,requested,dtype",
    [
        (1e200, 1e-200, np.float64),
        (1e-200, 1e200, np.float64),
        (1, 1e200, np.float32),
        (100, 1e200, np.int16),
        (1e-300, 1e20, np.float64),
    ],
)
def test_normalization_handles_extreme_scale(capture_send, size, requested, dtype):
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        sent = capture_send(
            lambda client: client.quiver(
                np.array([[3 * size]], dtype=dtype),
                np.array([[4 * size]], dtype=dtype),
                gridX=np.zeros((1, 1)),
                gridY=np.zeros((1, 1)),
                opts={"normalize": requested, "arrowheads": False},
            )
        )
    trace = sent["payload"]["data"][0]
    np.testing.assert_allclose(
        [trace["x"][1], trace["y"][1]],
        [0.6 * requested, 0.8 * requested],
        rtol=1e-12,
        atol=0,
    )


def test_normalization_preserves_small_components_with_finite_scale(capture_send):
    sent = capture_send(
        lambda client: client.quiver(
            np.array([[1e-100, 3e300]]),
            np.array([[0.0, 4e300]]),
            gridX=np.zeros((1, 2)),
            gridY=np.zeros((1, 2)),
            opts={"normalize": 1e200, "arrowheads": False},
        )
    )
    trace = sent["payload"]["data"][0]
    np.testing.assert_allclose(trace["x"][1], 2e-201, rtol=1e-12, atol=0)
