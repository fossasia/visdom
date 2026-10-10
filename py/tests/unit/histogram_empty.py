# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Histogram bin selection when a filtered dataset has no observations."""

import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("dtype", [float, int])
def test_empty_histogram_has_a_zero_count_bin(capture_send, dtype):
    sent = capture_send(lambda client: client.histogram(np.array([], dtype=dtype)))
    trace = sent["payload"]["data"][0]
    assert trace["type"] == "bar"
    assert trace["y"] == [0]
    assert len(trace["x"]) == 1
    assert np.isfinite(trace["x"]).all()


def test_empty_histogram_respects_explicit_bin_count(capture_send):
    sent = capture_send(
        lambda client: client.histogram(np.array([]), opts={"numbins": 3})
    )
    trace = sent["payload"]["data"][0]
    assert trace["y"] == [0, 0, 0]
    assert len(trace["x"]) == 3


@pytest.mark.parametrize("count,bins", [(1, 1), (40, 30)])
def test_nonempty_histogram_retains_default_bins(capture_send, count, bins):
    sent = capture_send(lambda client: client.histogram(np.arange(count)))
    values = sent["payload"]["data"][0]["y"]
    assert len(values) == bins
    assert sum(values) == count


def test_explicit_zero_bins_is_still_rejected(offline_client):
    with pytest.raises(ValueError, match="positive"):
        offline_client.histogram(np.array([]), opts={"numbins": 0})


@pytest.mark.parametrize("numbins", [None, 3])
def test_reused_histogram_options_do_not_freeze_automatic_bins(capture_send, numbins):
    opts = {"title": "Filtered metrics"}
    if numbins is not None:
        opts["numbins"] = numbins
    original = opts.copy()
    capture_send(lambda client: client.histogram(np.array([]), opts=opts))
    sent = capture_send(lambda client: client.histogram(np.arange(40), opts=opts))
    assert len(sent["payload"]["data"][0]["y"]) == (30 if numbins is None else numbins)
    assert opts == original
