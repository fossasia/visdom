# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Unknown scores must not displace the best parallel-coordinate runs."""

import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "scores,cap,expected",
    [
        ([np.nan, 0.9, 0.8, 0.1], 2, [1, 2]),
        ([0.5, np.nan, 0.3, 0.1], 3, [0, 2, 3]),
        ([np.nan, np.nan, 0.8, 0.7], 1, [2]),
    ],
)
def test_missing_scores_rank_after_known_scores(capture_send, scores, cap, expected):
    x = np.column_stack([np.arange(4), np.arange(4) + 10])
    y = np.array(scores)
    sent = capture_send(
        lambda client: client.parallel_coordinates(
            x, Y=y, opts={"max_experiments": cap}
        )
    )
    trace = sent["payload"]["data"][0]
    assert trace["dimensions"][0]["values"] == expected
    assert trace["dimensions"][1]["values"] == [i + 10 for i in expected]
    assert trace["line"]["color"] == [scores[i] for i in expected]
    np.testing.assert_array_equal(y, scores)
    np.testing.assert_array_equal(x[:, 0], np.arange(4))


@pytest.mark.skipif(
    not __debug__, reason="assert-based validation is stripped under python -O"
)
@pytest.mark.parametrize("cap", [0, -1, True, 1.5, "2"])
def test_invalid_experiment_cap_is_rejected_before_sending(offline_client, cap):
    with pytest.raises(
        AssertionError, match="max_experiments must be a positive integer"
    ):
        offline_client.parallel_coordinates(
            np.array([[1.0, 2.0], [3.0, 4.0]]),
            Y=np.array([0.1, 0.2]),
            opts={"max_experiments": cap},
        )


@pytest.mark.parametrize("cap", [None, np.int64(4), 5])
def test_uncapped_or_short_matrix_preserves_input_order(capture_send, cap):
    scores = np.array([np.nan, 0.9, 0.8, 0.1])
    x = np.column_stack([np.arange(4), np.arange(4) + 10])
    opts = {} if cap is None else {"max_experiments": cap}
    sent = capture_send(
        lambda client: client.parallel_coordinates(x, Y=scores, opts=opts)
    )
    trace = sent["payload"]["data"][0]
    assert trace["dimensions"][0]["values"] == list(range(4))
    np.testing.assert_array_equal(trace["line"]["color"], scores)
