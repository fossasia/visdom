# SPDX-License-Identifier: Apache-2.0
# https://www.apache.org/licenses/LICENSE-2.0
"""Plot methods must not write into the caller's opts dict.

Every public method that takes ``opts`` is called with a dict holding a
numeric title (``_title2str`` casts that one in place) and a nested value, and
the dict must come back equal. ``text``, ``svg`` and ``embeddings`` are not
covered here: they are fixed in their own pull requests.
"""

import copy

import numpy as np
import pytest

pytestmark = pytest.mark.unit

_GRID = np.arange(12, dtype=float).reshape(3, 4)
_LABELS = np.array([0, 1, 0, 1, 1, 0])
_SCORES = np.linspace(0.1, 0.9, 6)

# name -> (call, defaults the method injects into the payload's opts).
# An empty defaults dict means the method only fails the "untouched" check.
_CALLS = {
    "audio": (
        lambda v, o: v.audio(tensor=np.zeros(1000), opts=o),
        {"sample_frequency": 44100, "height": 80, "width": 330},
    ),
    "bar": (lambda v, o: v.bar(X=np.arange(4.0), opts=o), {"stacked": False}),
    "boxplot": (lambda v, o: v.boxplot(X=np.arange(8.0).reshape(4, 2), opts=o), {}),
    "confusion_matrix": (
        lambda v, o: v.confusion_matrix(y_true=_LABELS, y_pred=_LABELS[::-1], opts=o),
        {},
    ),
    "contour": (
        lambda v, o: v.contour(X=_GRID, opts=o),
        {"xmin": 0.0, "xmax": 11.0, "colormap": "Viridis"},
    ),
    "dual_axis_lines": (
        lambda v, o: v.dual_axis_lines(
            X=np.arange(4), Y1=np.arange(4.0), Y2=np.arange(4.0)[::-1], opts=o
        ),
        {"height": 300, "width": 500},
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
    "heatmap": (lambda v, o: v.heatmap(X=_GRID, opts=o), {"colormap": "Viridis"}),
    "histogram": (lambda v, o: v.histogram(X=np.arange(20.0), opts=o), {}),
    "histogram2d": (
        lambda v, o: v.histogram2d(X=np.arange(10.0), Y=np.arange(10.0)[::-1], opts=o),
        {"colormap": "Viridis"},
    ),
    "html_table": (
        lambda v, o: v.html_table([[1, 2]], headers=["a", "b"], opts=o),
        {},
    ),
    "mesh": (lambda v, o: v.mesh(X=np.arange(12.0).reshape(4, 3), opts=o), {}),
    "parallel_coordinates": (
        lambda v, o: v.parallel_coordinates(X=np.arange(15.0).reshape(5, 3), opts=o),
        {"width": 600, "height": 450},
    ),
    "pie": (lambda v, o: v.pie(X=np.array([1.0, 2.0, 3.0]), opts=o), {}),
    "pr_curve": (lambda v, o: v.pr_curve(_LABELS, _SCORES, opts=o), {}),
    "quiver": (
        lambda v, o: v.quiver(X=_GRID, Y=_GRID, opts=o),
        {"mode": "lines", "arrowheads": True},
    ),
    "roc_curve": (lambda v, o: v.roc_curve(_LABELS, _SCORES, opts=o), {}),
    "sankey": (lambda v, o: v.sankey([0, 1], [1, 2], [1, 1], opts=o), {}),
    "stem": (lambda v, o: v.stem(X=np.arange(4.0), opts=o), {"mode": "lines"}),
    "sunburst": (
        lambda v, o: v.sunburst(["a", "b"], ["", "a"], values=[1, 1], opts=o),
        {},
    ),
    "surf": (
        lambda v, o: v.surf(X=_GRID, opts=o),
        {"xmin": 0.0, "xmax": 11.0, "colormap": "Viridis"},
    ),
    "table": (
        lambda v, o: v.table([[1, 2]], headers=["a", "b"], opts=o),
        {"editable": True},
    ),
    "video": (
        lambda v, o: v.video(tensor=np.zeros((2, 16, 16, 3), np.uint8), opts=o),
        {"fps": 25, "loop": False, "autoplay": False},
    ),
    "violin": (lambda v, o: v.violin(X=np.arange(10.0), opts=o), {}),
    "matplot": (
        lambda v, o: v.matplot(pytest.importorskip("matplotlib.pyplot").figure(), o),
        {},
    ),
    "properties": (
        lambda v, o: v.properties(
            [{"type": "text", "name": "a", "value": "b"}], opts=o
        ),
        {},
    ),
}

# Optional dependencies: video() encodes through PyAV, matplot() needs matplotlib.
_NEEDS = {"video": "av", "matplot": "matplotlib"}
# properties() type-checks its title instead of casting it.
_STRING_TITLE = {"properties"}


def _skip_without_dependency(name):
    if name in _NEEDS:
        pytest.importorskip(_NEEDS[name])


def _caller_opts(name):
    title = "t" if name in _STRING_TITLE else 5
    return {"title": title, "layoutopts": {"plotly": {"showlegend": False}}}


@pytest.mark.parametrize("name", sorted(_CALLS))
def test_callers_opts_are_left_untouched(capture_send, name):
    _skip_without_dependency(name)
    call, _ = _CALLS[name]
    opts = _caller_opts(name)
    before = copy.deepcopy(opts)
    capture_send(lambda v: call(v, opts))
    assert opts == before


@pytest.mark.parametrize(
    "name", sorted(name for name, (_, defaults) in _CALLS.items() if defaults)
)
def test_default_opts_reach_the_payload(capture_send, name):
    _skip_without_dependency(name)
    call, defaults = _CALLS[name]
    sent = capture_send(lambda v: call(v, {}))
    payload_opts = sent["payload"]["opts"]
    for key, value in defaults.items():
        assert payload_opts[key] == value, (
            f"{name}: payload opts[{key!r}] = {payload_opts.get(key)!r}, "
            f"want {value!r}"
        )


@pytest.mark.parametrize("name", ["surf", "contour"])
def test_a_reused_dict_does_not_carry_the_first_plots_axis_range(capture_send, name):
    """The data-dependent case: xmin/xmax came from the first call's data."""
    call = _CALLS[name][0]
    shared = {}
    capture_send(lambda v: call(v, shared))
    sent = capture_send(
        lambda v: getattr(v, name)(X=np.arange(48.0).reshape(6, 8), opts=shared)
    )
    assert sent["payload"]["opts"]["xmax"] == 47.0
