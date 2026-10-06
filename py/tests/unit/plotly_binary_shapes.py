# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Restore the multidimensional binary shape format emitted by Plotly 6."""

import base64
import copy

import numpy as np
import pytest

from visdom import _decode_binary_arrays

pytestmark = pytest.mark.unit


def encoded(array, shape):
    return {
        "dtype": array.dtype.str,
        "bdata": base64.b64encode(array.tobytes()).decode("ascii"),
        "shape": shape,
    }


@pytest.mark.parametrize("shape", [(2, 3), (1, 3), (2, 1), (2, 2, 2), (0, 3)])
def test_decode_comma_separated_shape(shape):
    array = np.arange(np.prod(shape), dtype=np.float64).reshape(shape)
    payload = encoded(array, ", ".join(map(str, shape)))
    original = copy.deepcopy(payload)
    assert _decode_binary_arrays(payload) == array.tolist()
    assert payload == original


@pytest.mark.parametrize(
    "shape", ["2,x", "", "2,4", "-1,-1", "999999999999999999999,1"]
)
def test_invalid_string_shape_keeps_original_encoding(shape):
    payload = encoded(np.arange(6, dtype=np.float64), shape)
    assert _decode_binary_arrays(payload) is payload


@pytest.mark.parametrize("dtype", [np.float32, np.float64, np.int32, np.uint8])
def test_plotly_figure_heatmap_uses_nested_lists(capture_send, dtype):
    go = pytest.importorskip("plotly.graph_objects")
    array = np.arange(6, dtype=dtype).reshape(2, 3)
    figure = go.Figure(go.Heatmap(z=array))
    sent = capture_send(lambda client: client.plotlyplot(figure))
    assert sent["payload"]["data"][0]["z"] == array.tolist()
    np.testing.assert_array_equal(figure.data[0].z, array)
