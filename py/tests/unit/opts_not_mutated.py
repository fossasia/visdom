# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Plot methods must not write their defaults into the caller's opts dict."""

import copy

import numpy as np
import pytest

pytestmark = pytest.mark.unit

_GRID = np.arange(12, dtype=float).reshape(3, 4)
_CALLS = {
    "bar": lambda v, o: v.bar(X=np.arange(4.0), opts=o),
    "graph": lambda v, o: v.graph(np.array([[0, 1], [1, 2]]), opts=o),
    "heatmap": lambda v, o: v.heatmap(X=_GRID, opts=o),
    "histogram2d": lambda v, o: v.histogram2d(
        X=np.arange(10.0), Y=np.arange(10.0)[::-1], opts=o
    ),
    "quiver": lambda v, o: v.quiver(X=_GRID, Y=_GRID, opts=o),
    "video": lambda v, o: v.video(tensor=np.zeros((2, 16, 16, 3), np.uint8), opts=o),
}


@pytest.mark.parametrize("name", sorted(_CALLS))
def test_callers_opts_are_left_untouched(capture_send, name):
    opts = {"title": "t", "layoutopts": {"plotly": {"showlegend": False}}}
    before = copy.deepcopy(opts)
    capture_send(lambda v: _CALLS[name](v, opts))
    assert opts == before


@pytest.mark.parametrize("name", sorted(_CALLS))
def test_defaults_still_reach_the_payload(capture_send, name):
    sent = capture_send(lambda v: _CALLS[name](v, {}))
    assert sent["payload"]["opts"]
