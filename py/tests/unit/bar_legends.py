# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Named bar series retain their explicit matrix rows and columns."""

import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "values,legend,rownames,expected",
    [
        ([[1, 2]], ["first", "second"], ["row"], [[1], [2]]),
        ([[1], [2]], ["series"], ["first", "second"], [[1, 2]]),
        ([[1]], ["series"], ["row"], [[1]]),
        ([[1], [2]], ["series"], None, [[1, 2]]),
    ],
)
def test_named_matrix_keeps_its_series(
    capture_send, values, legend, rownames, expected
):
    array = np.array(values)
    original = array.copy()
    opts = {"legend": legend}
    if rownames is not None:
        opts["rownames"] = rownames
    sent = capture_send(lambda client: client.bar(array, opts=opts))
    traces = sent["payload"]["data"]
    assert [trace["y"] for trace in traces] == expected
    assert [trace["name"] for trace in traces] == legend
    expected_x = rownames if rownames is not None else list(range(1, len(values) + 1))
    assert all(trace["x"] == expected_x for trace in traces)
    np.testing.assert_array_equal(array, original)


def test_unnamed_row_vector_keeps_legacy_single_trace(capture_send):
    sent = capture_send(lambda client: client.bar(np.array([[1, 2]])))
    assert [trace["y"] for trace in sent["payload"]["data"]] == [[1, 2]]


def test_one_dimensional_legend_keeps_legacy_series_mode(capture_send):
    sent = capture_send(
        lambda client: client.bar(
            np.array([1, 2]), opts={"legend": ["first", "second"]}
        )
    )
    assert [trace["y"] for trace in sent["payload"]["data"]] == [[1], [2]]


def test_regular_named_matrix_keeps_both_axes(capture_send):
    sent = capture_send(
        lambda client: client.bar(
            np.array([[1, 2], [3, 4]]),
            opts={"legend": ["first", "second"], "rownames": ["row1", "row2"]},
        )
    )
    assert [trace["y"] for trace in sent["payload"]["data"]] == [[1, 3], [2, 4]]


def test_one_dimensional_legend_and_rownames_remain_ambiguous(offline_client):
    with pytest.raises(AssertionError, match="both rownames and legend"):
        offline_client.bar(
            np.array([1, 2]), opts={"legend": ["first", "second"], "rownames": ["row"]}
        )
