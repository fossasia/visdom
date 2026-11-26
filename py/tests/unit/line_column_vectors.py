#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests: ``vis.line`` accepts ``(N, 1)`` column vectors.

``X``, ``Y`` and ``Z`` may each be given as a single column. ``X`` and ``Z``
used to be flattened only when ``Y`` was a column too, so a column ``X`` or
``Z`` next to a 1D or multi-line ``Y`` failed the shape assertions.
"""

import numpy as np
import pytest

pytestmark = pytest.mark.unit

N = 5


def _traces(capture_send, **kwargs):
    sent = capture_send(lambda v: v.line(**kwargs))
    return sent["payload"]["data"]


def test_column_x_with_1d_y(capture_send):
    Y = np.arange(N, dtype=float)
    X = np.arange(N, dtype=float) * 2

    expected = _traces(capture_send, Y=Y, X=X)
    actual = _traces(capture_send, Y=Y, X=X.reshape(-1, 1))

    assert actual == expected


def test_column_x_shared_across_multi_line_y(capture_send):
    Y = np.arange(N * 2, dtype=float).reshape(N, 2)
    X = np.arange(N, dtype=float) * 2

    expected = _traces(capture_send, Y=Y, X=X)
    actual = _traces(capture_send, Y=Y, X=X.reshape(-1, 1))

    assert len(actual) == 2
    assert actual == expected


def test_column_z_with_1d_y(capture_send):
    Y = np.arange(N, dtype=float)
    X = np.arange(N, dtype=float)
    Z = np.ones(N)

    expected = _traces(capture_send, Y=Y, X=X, Z=Z, is3d=True)
    actual = _traces(capture_send, Y=Y, X=X, Z=Z.reshape(-1, 1), is3d=True)

    assert actual == expected


def test_column_z_shared_across_multi_line_y(capture_send):
    Y = np.arange(N * 2, dtype=float).reshape(N, 2)
    X = np.arange(N, dtype=float)
    Z = np.ones(N)

    expected = _traces(capture_send, Y=Y, X=X, Z=Z, is3d=True)
    actual = _traces(capture_send, Y=Y, X=X, Z=Z.reshape(-1, 1), is3d=True)

    assert len(actual) == 2
    assert actual == expected


def test_all_column_vectors_still_work(capture_send):
    """The case that worked before the fix: Y, X and Z are all columns."""
    Y = np.arange(N, dtype=float)
    X = np.arange(N, dtype=float)
    Z = np.ones(N)

    expected = _traces(capture_send, Y=Y, X=X, Z=Z, is3d=True)
    actual = _traces(
        capture_send,
        Y=Y.reshape(-1, 1),
        X=X.reshape(-1, 1),
        Z=Z.reshape(-1, 1),
        is3d=True,
    )

    assert actual == expected


@pytest.mark.parametrize(
    "X_shape, message",
    [
        ((N, 2), "X and Y should be the same shape"),
        ((N - 1, 1), "X and Y should be the same shape"),
        ((N, 1, 1), "X should have 1 or 2 dim"),
    ],
)
def test_bad_x_shapes_still_fail(offline_client, X_shape, message):
    """Only a true single column is flattened; other mismatches still fail."""
    Y = np.arange(N, dtype=float)

    with pytest.raises(AssertionError, match=message):
        offline_client.line(Y=Y, X=np.zeros(X_shape))


def test_bad_z_shape_still_fails(offline_client):
    Y = np.arange(N, dtype=float)

    with pytest.raises(AssertionError, match="Z and Y should be the same shape"):
        offline_client.line(Y=Y, X=Y, Z=np.zeros((N, 2)), is3d=True)
