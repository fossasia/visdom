#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Labels outside native integer range must keep their trace identities."""

import warnings

import numpy as np
import pytest

from visdom import _normalize_labels

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "labels",
    [
        np.array([2**63, 1, 2**63 + 1, 2**63], dtype=np.uint64),
        np.array([2**64 - 1, 1, 2**64 - 2, 2**64 - 1], dtype=np.uint64),
        np.array([2**63, 1, 2**64, 2**63], dtype=np.float64),
        np.array([1e100, 1, 2e100, 1e100]),
    ],
)
def test_scatter_remaps_large_labels_without_corrupting_trace_names(
    capture_send, labels
):
    points = np.arange(8, dtype=float).reshape(4, 2)
    original = labels.copy()
    values = np.unique(labels)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        sent = capture_send(lambda v: v.scatter(points, Y=labels))

    traces = sent["payload"]["data"]
    assert len(traces) == len(values)
    for trace, label in zip(traces, values):
        assert trace["name"] == str(label)
        np.testing.assert_array_equal(trace["x"], points[labels == label, 0])
        np.testing.assert_array_equal(trace["y"], points[labels == label, 1])
    assert sum(len(trace["x"]) for trace in traces) == len(points)
    np.testing.assert_array_equal(labels, original)


def test_remapped_large_labels_support_legends_and_color_palettes(capture_send):
    labels = np.array([2**64 - 1, 1, 2**64 - 1, 1], dtype=np.uint64)
    sent = capture_send(
        lambda v: v.scatter(
            np.arange(8, dtype=float).reshape(4, 2),
            Y=labels,
            opts={
                "legend": ["small", "large"],
                "markercolor": np.array([[255, 0, 0], [0, 255, 0]]),
            },
        )
    )
    small, large = sent["payload"]["data"]
    assert small["name"] == "small"
    assert small["marker"]["color"] == ["#ff0000", "#ff0000"]
    assert large["name"] == "large"
    assert large["marker"]["color"] == ["#00ff00", "#00ff00"]


@pytest.mark.parametrize("dtype", [np.int64, np.uint64])
def test_representable_integer_labels_keep_their_original_indices(dtype):
    labels = np.array([1, np.iinfo(int).max], dtype=dtype)
    normalized, values, count = _normalize_labels(labels)
    np.testing.assert_array_equal(normalized, labels)
    assert values is None
    assert count == int(labels[-1])
