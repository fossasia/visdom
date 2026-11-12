# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Plot methods must not write their defaults into the caller's opts dict."""

import copy

import numpy as np
import pytest

pytestmark = pytest.mark.unit

_GRID = np.arange(12, dtype=float).reshape(3, 4)

# (call, {key: default}) pairs. The defaults are what each method is known to
# inject -- so a check for an injected key doubles as a regression for the
# default value itself, instead of only asserting payload["opts"] is truthy.
_CALLS = {
    "bar": (
        lambda v, o: v.bar(X=np.arange(4.0), opts=o),
        {"stacked": False},
    ),
    "graph": (
        lambda v, o: v.graph(np.array([[0, 1], [1, 2]]), opts=o),
        {
            "directed": False,
            "scheme": "same",
            "showEdgeLabels": False,
            "showVertexLabels": False,
            "width": 500,
            "height": 500,
        },
    ),
    "heatmap": (
        lambda v, o: v.heatmap(X=_GRID, opts=o),
        {"colormap": "Viridis"},
    ),
    "histogram2d": (
        lambda v, o: v.histogram2d(X=np.arange(10.0), Y=np.arange(10.0)[::-1], opts=o),
        {"colormap": "Viridis"},
    ),
    "quiver": (
        lambda v, o: v.quiver(X=_GRID, Y=_GRID, opts=o),
        {"mode": "lines", "arrowheads": True},
    ),
    "video": (
        lambda v, o: v.video(tensor=np.zeros((2, 16, 16, 3), np.uint8), opts=o),
        {"fps": 25, "loop": False, "autoplay": False},
    ),
}

# video() encodes its tensor through PyAV; skip it where PyAV is not installed.
_NEEDS_AV = {"video"}


def _maybe_skip(name):
    if name in _NEEDS_AV:
        pytest.importorskip("av")


@pytest.mark.parametrize("name", sorted(_CALLS))
def test_callers_opts_are_left_untouched(capture_send, name):
    _maybe_skip(name)
    call, _ = _CALLS[name]
    opts = {"title": "t", "layoutopts": {"plotly": {"showlegend": False}}}
    before = copy.deepcopy(opts)
    capture_send(lambda v: call(v, opts))
    assert opts == before


@pytest.mark.parametrize("name", sorted(_CALLS))
def test_default_opts_reach_the_payload(capture_send, name):
    _maybe_skip(name)
    call, defaults = _CALLS[name]
    sent = capture_send(lambda v: call(v, {}))
    payload_opts = sent["payload"]["opts"]
    for key, value in defaults.items():
        assert payload_opts[key] == value, (
            f"{name}: payload opts[{key!r}] = {payload_opts.get(key)!r}, "
            f"want {value!r}"
        )
