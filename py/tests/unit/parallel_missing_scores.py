# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Unknown scores must not displace the best parallel-coordinate runs."""

import subprocess
import sys
from pathlib import Path

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


@pytest.mark.parametrize("cap", [2.0, np.float32(2), np.float64(2), 10.0])
def test_integral_float_caps_keep_feature_and_score_alignment(capture_send, cap):
    x = np.column_stack([np.arange(4), np.arange(4) + 10])
    scores = np.array([np.nan, 0.9, 0.8, 0.1])
    sent = capture_send(
        lambda client: client.parallel_coordinates(
            x, Y=scores, opts={"max_experiments": cap}
        )
    )
    trace = sent["payload"]["data"][0]
    expected = [1, 2] if cap == 2 else list(range(4))
    assert trace["dimensions"][0]["values"] == expected
    assert trace["dimensions"][1]["values"] == [i + 10 for i in expected]
    np.testing.assert_array_equal(trace["line"]["color"], scores[expected])
    np.testing.assert_array_equal(x[:, 0], np.arange(4))
    np.testing.assert_array_equal(scores, [np.nan, 0.9, 0.8, 0.1])


@pytest.mark.parametrize(
    "cap", [0, -1, True, np.bool_(True), 1.5, np.nan, np.inf, -np.inf, "2"]
)
def test_invalid_experiment_cap_is_rejected_before_sending(offline_client, cap):
    with pytest.raises(ValueError, match="max_experiments must be a positive integer"):
        offline_client.parallel_coordinates(
            np.array([[1.0, 2.0], [3.0, 4.0]]),
            Y=np.array([0.1, 0.2]),
            opts={"max_experiments": cap},
        )


def test_invalid_experiment_caps_are_rejected_under_optimized_python():
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            """
from unittest.mock import Mock
import numpy as np
from visdom import Visdom

client = Visdom.__new__(Visdom)
client._send = Mock()
for cap in (0, -1, True, np.bool_(True), 1.5, np.nan, np.inf, -np.inf, "2"):
    try:
        client.parallel_coordinates(
            np.array([[1., 2.], [3., 4.]]),
            Y=np.array([.1, .2]),
            opts={"max_experiments": cap},
        )
    except ValueError as error:
        if str(error) != "opts.max_experiments must be a positive integer":
            raise
    else:
        raise RuntimeError("Invalid cap accepted: %r" % (cap,))
client._send.assert_not_called()
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


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


@pytest.mark.parametrize("cap", [1, 2, 3])
@pytest.mark.parametrize("optimized", [False, True])
def test_capped_coordinates_require_scores_before_sending(cap, optimized):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(
        [
            "-c",
            """
from unittest.mock import Mock
import numpy as np
from visdom import Visdom

client = Visdom.__new__(Visdom)
client._send = Mock()
try:
    client.parallel_coordinates(
        np.array([[1., 2.], [3., 4.]]),
        opts={"max_experiments": %d},
    )
except ValueError as error:
    if str(error) != "opts.max_experiments requires Y to be provided":
        raise
else:
    raise RuntimeError("Missing scores accepted")
client._send.assert_not_called()
"""
            % cap,
        ]
    )
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


INVALID_SHAPES = [
    (dict(X=[1.0, 2.0]), "X must be a 2D matrix"),
    (dict(X=np.empty((0, 2))), "X must have at least 1 experiment"),
    (dict(X=np.empty((2, 0))), "X must have at least 2 dimensions"),
    (dict(X=[[1.0], [2.0]]), "X must have at least 2 dimensions"),
    (dict(X=np.ones((2, 2)), Y=np.ones((2, 2))), "Y must be a 1D vector"),
    (dict(X=np.ones((2, 2)), opts={"dimensions": "ab"}), "should be a list/tuple"),
    (
        dict(X=np.ones((2, 2)), opts={"dimensions": ["one"]}),
        "must match number of columns",
    ),
    (
        dict(X=np.ones((2, 2)), opts={"dimensions": ["one", "two", "three"]}),
        "must match number of columns",
    ),
]
for score_count in (0, 1, 3):
    for cap in (None, 1, 2, 3):
        INVALID_SHAPES.append(
            (
                dict(
                    X=np.ones((2, 2)),
                    Y=np.arange(score_count),
                    opts={} if cap is None else {"max_experiments": cap},
                ),
                "must match number of rows in X",
            )
        )


@pytest.mark.parametrize("kwargs,message", INVALID_SHAPES)
def test_invalid_coordinate_shapes_fail_before_sending(offline_client, kwargs, message):
    from unittest.mock import Mock

    offline_client._send = Mock()
    with pytest.raises(ValueError, match=message):
        offline_client.parallel_coordinates(**kwargs)
    offline_client._send.assert_not_called()


@pytest.mark.parametrize("optimized", [False, True])
def test_coordinate_shape_validation_survives_optimization(optimized):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(
        [
            "-c",
            """
from unittest.mock import Mock
import numpy as np
from visdom import Visdom

client = Visdom.__new__(Visdom)
client._send = Mock()
cases = [
    dict(X=[1., 2.]),
    dict(X=np.empty((0, 2))),
    dict(X=np.empty((2, 0))),
    dict(X=[[1.], [2.]]),
    dict(X=np.ones((2, 2)), Y=np.ones((2, 2))),
    dict(X=np.ones((2, 2)), opts={"dimensions": "ab"}),
    dict(X=np.ones((2, 2)), opts={"dimensions": ["one"]}),
    dict(X=np.ones((2, 2)), opts={"dimensions": ["one", "two", "three"]}),
]
for score_count in (0, 1, 3):
    for cap in (None, 1, 2, 3):
        cases.append(dict(X=np.ones((2, 2)), Y=np.arange(score_count),
                          opts={} if cap is None else {"max_experiments": cap}))
messages = [
    "X must be a 2D matrix", "X must have at least 1 experiment",
    "X must have at least 2 dimensions", "X must have at least 2 dimensions",
    "Y must be a 1D vector", "opts.dimensions should be a list/tuple",
    "Length of opts.dimensions", "Length of opts.dimensions",
] + ["Length of Y"] * 12
failures = []
for kwargs, message in zip(cases, messages):
    try:
        client.parallel_coordinates(**kwargs)
    except ValueError as error:
        if not str(error).startswith(message):
            failures.append("Wrong validation error: %s" % error)
    except Exception as error:
        failures.append("Wrong exception: %r" % error)
    else:
        failures.append("Invalid shape accepted: %r" % (kwargs,))
client._send.assert_not_called()
if failures:
    raise RuntimeError("; ".join(failures))
""",
        ]
    )
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("scores", [0.5, [0.5], [[0.5]]])
def test_single_experiment_accepts_scalar_or_singleton_scores(capture_send, scores):
    sent = capture_send(
        lambda client: client.parallel_coordinates([[1.0, 2.0]], Y=scores)
    )
    assert sent["payload"]["data"][0]["line"]["color"] == [0.5]


@pytest.mark.parametrize("scores", [[[0.1, 0.2]], [[0.1], [0.2]]])
def test_scores_keep_existing_singleton_axis_support(capture_send, scores):
    sent = capture_send(
        lambda client: client.parallel_coordinates([[1.0, 2.0], [3.0, 4.0]], Y=scores)
    )
    trace = sent["payload"]["data"][0]
    assert trace["line"]["color"] == [0.1, 0.2]
    assert trace["dimensions"][0]["values"] == [1.0, 3.0]


@pytest.mark.parametrize("optimized", [False, True])
def test_tick_label_validation_survives_optimization(optimized):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(
        [
            "-c",
            """
from unittest.mock import Mock
from visdom import Visdom

client = Visdom.__new__(Visdom)
client._send = Mock()
for axis in (0, 1):
    cases = [
        ({"ticktext": {axis: ["a"]}}, "requires matching opts.tickvals"),
        ({"ticktext": {axis: ["a", "b"]}, "tickvals": {axis: [1]}},
         "must have the same length"),
    ]
    for opts, message in cases:
        try:
            client.parallel_coordinates([[1., 2.], [3., 4.]], opts=opts)
        except ValueError as error:
            if message not in str(error):
                raise RuntimeError("Unexpected validation message: %s" % error)
        else:
            raise RuntimeError("Invalid ticks accepted: %r" % opts)
client._send.assert_not_called()
client.parallel_coordinates(
    [[1., 2.], [3., 4.]],
    opts={"ticktext": {0: ["a", "b"], 1: ["c", "d"]},
          "tickvals": {0: [1., 3.], 1: [2., 4.]}},
)
dimensions = client._send.call_args.args[0]["data"][0]["dimensions"]
if dimensions[0]["ticktext"] != ["a", "b"] or dimensions[1]["tickvals"] != [2., 4.]:
    raise RuntimeError("Valid tick values or labels changed")
""",
        ]
    )
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
