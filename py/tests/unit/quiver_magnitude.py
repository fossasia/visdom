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


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("small,large", [(1e-30, 1.0), (1e-20, 1e20)])
@pytest.mark.parametrize("components", [(1, 0), (0, -1), (1, -1)])
def test_normalization_warns_when_nonzero_vector_underflows(
    capture_send, dtype, small, large, components
):
    x = np.array([[components[0] * small, large, 0]], dtype=dtype)
    y = np.array([[components[1] * small, 0, 0]], dtype=dtype)
    original_x, original_y = x.copy(), y.copy()
    with pytest.warns(RuntimeWarning, match="nonzero vectors became zero") as caught:
        sent = capture_send(
            lambda client: client.quiver(
                x,
                y,
                gridX=np.zeros_like(x),
                gridY=np.zeros_like(y),
                opts={"normalize": 1e-300, "arrowheads": False},
            )
        )
    assert len(caught) == 1
    trace = sent["payload"]["data"][0]
    assert trace["x"][1] == trace["y"][1] == 0
    np.testing.assert_allclose(trace["x"][4], 1e-300, rtol=1e-12, atol=0)
    np.testing.assert_array_equal(x, original_x)
    np.testing.assert_array_equal(y, original_y)


@pytest.mark.parametrize("normalize", [None, 0, 1])
def test_normalization_does_not_warn_for_original_zero_vectors(capture_send, normalize):
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        capture_send(
            lambda client: client.quiver(
                np.array([[0.0, 1.0]]),
                np.zeros((1, 2)),
                opts={"normalize": normalize, "arrowheads": False},
            )
        )


def test_normalization_does_not_warn_when_only_one_component_underflows(capture_send):
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        sent = capture_send(
            lambda client: client.quiver(
                np.array([[1e-30, 1.0]]),
                np.array([[1.0, 0.0]]),
                gridX=np.zeros((1, 2)),
                gridY=np.zeros((1, 2)),
                opts={"normalize": 1e-300, "arrowheads": False},
            )
        )
    trace = sent["payload"]["data"][0]
    assert trace["x"][1] == 0
    assert trace["y"][1] == 1e-300


def test_normalization_does_not_warn_for_nonfinite_vectors(capture_send):
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        capture_send(
            lambda client: client.quiver(
                np.array([[np.inf, np.nan, 1.0]]),
                np.zeros((1, 3)),
                opts={"normalize": 1e-300, "arrowheads": False},
            )
        )
