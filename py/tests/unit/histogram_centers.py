# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Histogram bars use the centers of the intervals that were counted."""

import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "values,numbins",
    [
        ([0.0, 0.2, 1.9, 2.0, 3.9, 4.0], 2),
        ([4.0, 4.0, 4.0], 3),
        ([0.0, 4.0], 1),
        ([], 2),
        ([np.nan, np.inf, -np.inf], 2),
    ],
)
def test_bar_positions_match_counted_bin_intervals(capture_send, values, numbins):
    x = np.array(values)
    finite = x[np.isfinite(x)]
    bounds = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    counts, edges = np.histogram(x, bins=numbins, range=bounds)
    sent = capture_send(lambda client: client.histogram(x, opts={"numbins": numbins}))
    trace = sent["payload"]["data"][0]
    np.testing.assert_allclose(trace["x"], edges[:-1] + np.diff(edges) / 2)
    assert trace["y"] == counts.tolist()
    assert len(trace["x"]) == numbins
    np.testing.assert_array_equal(x, values)
