#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the client's layout, marker and option helpers.

Everything here sits between a user's ``opts`` dict and the Plotly payload the
browser receives. Almost every public plot method calls three or four of them,
and none had a direct test, so a change to any one of them would surface as a
subtly wrong plot rather than as a failure.

Several of these functions are unusual enough to trip up a reader:

* ``_title2str`` and ``_assert_opts`` **mutate their argument** and their return
  value is meaningless. ``_title2str`` returns ``None`` outright when ``opts``
  carries no title, so ``opts = _title2str(opts)`` would silently erase the
  caller's options. All 20+ call sites correctly ignore the result; the tests
  below pin that so a future refactor cannot quietly break it.
* ``_axisformat`` is gated: if none of the listed fields are present it returns
  ``None`` and the whole axis is dropped from the layout.
* The four ``*Check`` helpers validate with bare ``assert``, so their tests are
  skipped under ``python -O``.
"""

import base64
import binascii

import numpy as np
import pytest

from visdom import (
    _assert_opts,
    _axisformat,
    _axisformat3d,
    _dashCheck,
    _decode_binary_arrays,
    _lineColorCheck,
    _markerColorCheck,
    _markerSizeCheck,
    _normalize_labels,
    _opts2layout,
    _scrub_dict,
    _title2str,
)

pytestmark = pytest.mark.unit

requires_assertions = pytest.mark.skipif(
    not __debug__, reason="assert-based validation is stripped under python -O"
)


@pytest.mark.parametrize("title", [5, 5.5, np.int64(7), np.float64(1.25)])
def test_title2str_casts_a_numeric_title_in_place(title):
    """A number is stringified on the caller's dict, not on a copy."""
    opts = {"title": title}
    _title2str(opts)
    assert opts["title"] == str(title)
    assert isinstance(opts["title"], str)


def test_title2str_warns_when_it_casts(caplog):
    """The cast is silent otherwise, so it is logged."""
    with caplog.at_level("WARNING", logger="visdom"):
        _title2str({"title": 42})
    assert "Numerical title 42 has been cast to a string" in caplog.text


def test_title2str_leaves_a_string_title_alone():
    """A string title is already valid and must not be touched."""
    opts = {"title": "loss"}
    assert _title2str(opts) is opts
    assert opts["title"] == "loss"


def test_title2str_does_not_cast_a_boolean():
    """isnum excludes bool, so True stays a bool rather than becoming 'True'."""
    opts = {"title": True}
    _title2str(opts)
    assert opts["title"] is True


@pytest.mark.parametrize("opts", [{}, {"title": None}, {"xlabel": "x"}])
def test_title2str_returns_none_without_a_title(opts):
    """The return value is unusable and every caller ignores it.

    Pinned deliberately: rewriting a call site as ``opts = _title2str(opts)``
    would throw the caller's whole options dict away for the common case of a
    plot with no title.
    """
    assert _title2str(opts) is None


def test_scrub_dict_drops_none_values():
    """None is what Plotly treats as 'unset', so it is stripped."""
    assert _scrub_dict({"a": 1, "b": None}) == {"a": 1}


@pytest.mark.parametrize("value", [0, 0.0, False, "", [], {}])
def test_scrub_dict_keeps_falsy_values(value):
    """Only None goes; a zero margin or an empty label is a real setting."""
    assert _scrub_dict({"a": value}) == {"a": value}


def test_scrub_dict_recurses():
    """Nested layouts are scrubbed at every depth."""
    scrubbed = _scrub_dict({"axis": {"title": None, "range": [0, 1]}, "b": None})
    assert scrubbed == {"axis": {"range": [0, 1]}}


def test_scrub_dict_keeps_an_emptied_dict():
    """A sub-dict whose values were all None becomes {}, not None."""
    assert _scrub_dict({"axis": {"title": None}}) == {"axis": {}}


@pytest.mark.parametrize("value", [5, "text", [1, None, 2], None])
def test_scrub_dict_passes_non_dicts_through(value):
    """Lists are not descended into, so a None inside one survives."""
    assert _scrub_dict(value) == value


@pytest.mark.parametrize(
    "field",
    [
        "type",
        "label",
        "tickmin",
        "tickmax",
        "tickvals",
        "ticklabels",
        "tick",
        "tickstep",
        "tickfont",
    ],
)
def test_axisformat_is_produced_by_any_single_field(field):
    """Any one recognised option is enough to build the axis dict."""
    assert _axisformat("x", {"x" + field: 1}) is not None


def test_axisformat_returns_none_for_unrelated_opts():
    """With no axis option at all the axis is left out of the layout."""
    assert _axisformat("x", {"title": "t", "ytickmin": 0}) is None
    assert _axisformat("x", {}) is None


def test_axisformat_applies_a_lone_tick_step():
    """Regression: xtickstep alone used to be dropped.

    ``tickstep`` was missing from the gate list while the body read it into
    ``dtick``, so the documented ``opts.xtickstep`` only took effect when it
    happened to be passed alongside another axis option.
    """
    assert _axisformat("x", {"xtickstep": 0.5})["dtick"] == 0.5


def test_axisformat_maps_options_onto_plotly_names():
    """label becomes title and ticklabels becomes ticktext.

    Plotly dropped the bare-string form of ``title``, so a label arrives
    wrapped as ``{"text": ...}``.
    """
    axis = _axisformat(
        "y",
        {
            "ytype": "log",
            "ylabel": "loss",
            "ytickvals": [1, 2],
            "yticklabels": ["a", "b"],
            "ytick": True,
            "ytickfont": {"size": 9},
        },
    )
    assert axis["type"] == "log"
    assert axis["title"] == {"text": "loss"}
    assert axis["tickvals"] == [1, 2]
    assert axis["ticktext"] == ["a", "b"]
    assert axis["showticklabels"] is True
    assert axis["tickfont"] == {"size": 9}


def test_axisformat_sets_a_range_only_when_both_bounds_are_given():
    """A half-specified range would pin one end of the axis at None."""
    assert _axisformat("x", {"xtickmin": 0, "xtickmax": 10})["range"] == [0, 10]
    assert _axisformat("x", {"xtickmin": 0})["range"] is None
    assert _axisformat("x", {"xtickmax": 10})["range"] is None


def test_axisformat_keeps_the_axes_independent():
    """The xy prefix means a y option never leaks onto the x axis."""
    opts = {"xlabel": "epoch", "ylabel": "loss"}
    assert _axisformat("x", opts)["title"] == {"text": "epoch"}
    assert _axisformat("y", opts)["title"] == {"text": "loss"}


def test_axisformat_enables_automargin_for_a_tight_layout():
    """tight_layout trims the margins, so the axis must size itself."""
    assert _axisformat("x", {"xlabel": "e", "tight_layout": True})["automargin"] is True
    assert _axisformat("x", {"xlabel": "e"})["automargin"] is None


def test_axisformat3d_returns_none_without_a_recognised_field():
    """Same gate as the 2d version."""
    assert _axisformat3d("z", {"title": "t"}) is None


def test_axisformat3d_computes_nticks_from_the_step():
    """nticks is the span divided by the step, and comes back as a float."""
    axis = _axisformat3d("z", {"ztickmin": 0, "ztickmax": 10, "ztickstep": 2})
    assert axis["nticks"] == 5.0
    assert isinstance(axis["nticks"], float)


def test_axisformat3d_needs_bounds_before_it_uses_a_step():
    """Without a range there is nothing to divide, so nticks stays None."""
    assert _axisformat3d("z", {"zlabel": "d", "ztickstep": 2})["nticks"] is None


def test_axisformat3d_applies_a_lone_tick_step():
    """A 3d step alone reaches plotly as ``dtick``.

    It used to feed only ``nticks``, which is gated on both bounds, so a lone
    step built no axis at all. The 3d axis now carries ``dtick`` just like the
    2d one, which is what makes the step meaningful on its own.
    """
    axis = _axisformat3d("z", {"ztickstep": 2})
    assert axis["dtick"] == 2
    assert axis["nticks"] is None


def test_opts2layout_builds_flat_axes_in_2d():
    """A 2d plot carries xaxis and yaxis at the top level."""
    layout = _opts2layout({"xlabel": "e", "ylabel": "l"})
    assert layout["xaxis"]["title"] == {"text": "e"}
    assert layout["yaxis"]["title"] == {"text": "l"}
    assert "scene" not in layout


def test_opts2layout_nests_three_axes_in_a_scene_in_3d():
    """A 3d plot puts all three axes under scene instead."""
    layout = _opts2layout({"xlabel": "a", "ylabel": "b", "zlabel": "c"}, is3d=True)
    assert set(layout["scene"]) == {"xaxis", "yaxis", "zaxis"}
    assert "xaxis" not in layout


@pytest.mark.parametrize(
    "opts, is3d, expected",
    [
        ({}, False, {"l": 60, "r": 60, "t": 60, "b": 60}),
        ({}, True, {"l": 0, "r": 60, "t": 20, "b": 0}),
        ({"tight_layout": True}, False, {"l": 0, "r": 0, "t": 30, "b": 0}),
        ({"tight_layout": True}, True, {"l": 0, "r": 0, "t": 20, "b": 0}),
    ],
)
def test_opts2layout_margin_defaults(opts, is3d, expected):
    """The margins differ on both is3d and tight_layout; top differs on both."""
    assert _opts2layout(opts, is3d=is3d)["margin"] == expected


def test_opts2layout_margins_can_be_overridden_individually():
    """An explicit margin wins over the default for that side only."""
    margin = _opts2layout({"marginleft": 5, "margintop": 7})["margin"]
    assert margin == {"l": 5, "r": 60, "t": 7, "b": 60}


def test_opts2layout_shows_the_legend_when_one_is_supplied():
    """showlegend defaults to whether a legend was given at all."""
    assert _opts2layout({"legend": ["a", "b"]})["showlegend"] is True
    assert _opts2layout({})["showlegend"] is False
    assert _opts2layout({"legend": ["a"], "showlegend": False})["showlegend"] is False


def test_opts2layout_stacks_bars_on_request():
    """A truthy stacked becomes Plotly's barmode."""
    assert _opts2layout({"stacked": True})["barmode"] == "stack"


@pytest.mark.parametrize("stacked", [False, 0, None])
def test_opts2layout_omits_barmode_when_not_stacked(stacked):
    """The 'group' arm of the ternary is unreachable, which is harmless.

    ``barmode`` is only assigned inside ``if opts.get("stacked")``, so the
    ``else "group"`` branch can never run. Omitting the key entirely leaves
    Plotly on its own default, which is already ``group``.
    """
    assert "barmode" not in _opts2layout({"stacked": stacked})


def test_opts2layout_merges_plotly_layoutopts():
    """layoutopts['plotly'] is the escape hatch for raw Plotly settings.

    What comes through it is still normalized: Plotly 3 rejects a bare string
    title, so a hand-written one is wrapped like the rest.
    """
    layout = _opts2layout(
        {"layoutopts": {"plotly": {"hovermode": "x", "title": "raw"}}}
    )
    assert layout["hovermode"] == "x"
    assert layout["title"] == {"text": "raw"}


def test_opts2layout_ignores_layoutopts_for_another_backend():
    """Only the plotly key is read; anything else is left for its own backend."""
    layout = _opts2layout({"layoutopts": {"matplotlib": {"hovermode": "x"}}})
    assert "hovermode" not in layout
    assert "matplotlib" not in layout


def test_opts2layout_scrubs_unset_values_last():
    """A missing title must not reach the payload as an explicit null."""
    layout = _opts2layout({})
    assert "title" not in layout
    assert "xaxis" not in layout


def test_opts2layout_does_not_mutate_the_caller_opts():
    """Unlike _title2str and _assert_opts, this one is pure."""
    opts = {"title": "t", "xlabel": "e"}
    _opts2layout(opts)
    assert opts == {"title": "t", "xlabel": "e"}


def test_normalize_labels_passes_one_based_integers_through():
    """Already-valid labels are used as-is, signalled by label_values None."""
    Y, values, K = _normalize_labels(np.array([1, 2, 2, 3]))
    np.testing.assert_array_equal(Y, [1, 2, 2, 3])
    assert values is None
    assert K == 3


def test_normalize_labels_counts_up_to_the_maximum_not_the_distinct_count():
    """A gap in the labels still reserves a slot, since K is the max."""
    _, values, K = _normalize_labels(np.array([1, 3]))
    assert values is None
    assert K == 3


@pytest.mark.parametrize(
    "labels, expected, values",
    [
        ([0, 1, 2], [1, 2, 3], [0, 1, 2]),
        ([-1, 5], [1, 2], [-1, 5]),
        ([1.5, 2.5, 1.5], [1, 2, 1], [1.5, 2.5]),
    ],
)
def test_normalize_labels_reindexes_anything_else(labels, expected, values):
    """Zero-based, negative and fractional labels all go through np.unique."""
    Y, label_values, K = _normalize_labels(np.array(labels))
    np.testing.assert_array_equal(Y, expected)
    np.testing.assert_array_equal(label_values, values)
    assert K == len(values)


def test_normalize_labels_orders_strings_by_sorted_value():
    """np.searchsorted ranks by sorted value, not by first appearance."""
    Y, values, K = _normalize_labels(np.array(["b", "a", "b"]))
    np.testing.assert_array_equal(Y, [2, 1, 2])
    np.testing.assert_array_equal(values, ["a", "b"])
    assert K == 2


def test_normalize_labels_handles_an_object_dtype_of_strings():
    """Object arrays skip the numeric check without raising."""
    Y, values, K = _normalize_labels(np.array(["b", "a"], dtype=object))
    np.testing.assert_array_equal(Y, [2, 1])
    assert K == 2


def test_normalize_labels_ravels_a_2d_input():
    """Labels arrive per point, however the caller shaped them."""
    Y, _, _ = _normalize_labels(np.array([[1, 2], [2, 1]]))
    np.testing.assert_array_equal(Y, [1, 2, 2, 1])


def test_normalize_labels_returns_integer_indices():
    """Downstream code uses these to index colour and size palettes."""
    Y, _, _ = _normalize_labels(np.array([1.5, 2.5]))
    assert np.issubdtype(Y.dtype, np.integer)


@requires_assertions
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_normalize_labels_rejects_non_finite_numeric_labels(bad):
    """A NaN label cannot be indexed against, so it is caught early."""
    with pytest.raises(AssertionError, match="labels must be finite"):
        _normalize_labels(np.array([1.0, bad]))


@requires_assertions
@pytest.mark.parametrize("bad", [float("inf"), float("-inf")])
def test_normalize_labels_does_not_warn_on_infinite_input(recwarn, bad):
    """np.mod sees the infinity before the finite check rejects it.

    ``inf % 1`` is an invalid floating-point operation, so this produced an
    'invalid value encountered in remainder' RuntimeWarning pointing at a line
    that is not the problem. (``nan % 1`` merely propagates and never warned.)
    The computation is wrapped in np.errstate, so the AssertionError now
    arrives on its own.
    """
    with pytest.raises(AssertionError, match="labels must be finite"):
        _normalize_labels(np.array([1.0, bad]))
    assert [w for w in recwarn if issubclass(w.category, RuntimeWarning)] == []


def _points(n=3):
    return np.arange(n * 2, dtype=float).reshape(n, 2)


def test_marker_color_check_expands_a_greyscale_palette():
    """A 1d palette becomes rgba strings, one per point, grouped by label."""
    result = _markerColorCheck(np.array([0, 255]), _points(), np.array([1, 2, 1]), 2)
    assert result[1] == ["rgba(0, 0, 255, 0.0)", "rgba(0, 0, 255, 0.0)"]
    assert result[2] == ["rgba(0, 0, 255, 1.0)"]


def test_marker_color_check_expands_an_rgb_palette():
    """A K x 3 palette becomes hex, indexed by label."""
    result = _markerColorCheck(
        np.array([[255, 0, 0], [0, 255, 0]]), _points(), np.array([1, 2, 1]), 2
    )
    assert result[1] == ["#ff0000", "#ff0000"]
    assert result[2] == ["#00ff00"]


def test_marker_color_check_accepts_a_per_point_array():
    """One colour per point is used directly rather than indexed by label."""
    result = _markerColorCheck(
        np.array([0, 128, 255]), _points(), np.array([1, 1, 1]), 1
    )
    assert len(result[1]) == 3
    assert result[1][1] == "rgba(0, 0, 255, %s)" % (128 / 255.0)


def test_marker_color_check_groups_every_point_under_its_label():
    """The returned dict maps each label to that label's colours, in order."""
    result = _markerColorCheck(
        np.array([[1, 1, 1], [2, 2, 2], [3, 3, 3]]),
        _points(),
        np.array([2, 1, 2]),
        2,
    )
    assert sorted(result) == [1, 2]
    assert len(result[2]) == 2 and len(result[1]) == 1


@requires_assertions
@pytest.mark.parametrize(
    "mc, message",
    [
        ([0, 255], "mc should be a numpy ndarray"),
        (np.array([0]), "marker colors have to be of size"),
        (np.array([[0, 0], [1, 1]]), "marker colors have to be of size"),
        (np.zeros((2, 2, 2)), "marker colors have to be of size"),
        (np.array([-1, 255]), "marker colors have to be >= 0"),
        (np.array([0, 256]), "marker colors have to be <= 255"),
        (np.array([0.5, 255.0]), "marker colors are assumed to be ints"),
    ],
)
def test_marker_color_check_rejects_bad_input(mc, message):
    """Type, shape, range and integrality are each asserted separately."""
    with pytest.raises(AssertionError, match=message):
        _markerColorCheck(mc, _points(), np.array([1, 2, 1]), 2)


@pytest.mark.parametrize("sizes", [[5.0, 10.0, 15.0], (5.0, 10.0, 15.0)])
def test_marker_size_check_coerces_sequences(sizes):
    """Lists and tuples are accepted, so callers need not build an array."""
    result = _markerSizeCheck(sizes, _points(), np.array([1, 2, 1]))
    np.testing.assert_array_equal(result, [5.0, 10.0, 15.0])


def test_marker_size_check_expands_a_per_label_array():
    """Fewer sizes than points means one size per label, indexed by Y."""
    result = _markerSizeCheck(np.array([5.0, 10.0]), _points(), np.array([1, 2, 1]))
    np.testing.assert_array_equal(result, [5.0, 10.0, 5.0])


def test_marker_size_check_prefers_per_point_when_the_counts_collide():
    """With as many sizes as points the array is taken point-wise.

    Three points and three labels is ambiguous; the per-point branch is
    checked first, so the sizes are not reindexed through Y.
    """
    result = _markerSizeCheck(
        np.array([5.0, 10.0, 15.0]), _points(), np.array([3, 3, 3])
    )
    np.testing.assert_array_equal(result, [5.0, 10.0, 15.0])


def test_marker_size_check_returns_floats():
    """Integer sizes are cast, so Plotly never sees a numpy int."""
    result = _markerSizeCheck(np.array([5, 10]), _points(), np.array([1, 2, 1]))
    assert result.dtype == float


def test_marker_size_check_accepts_an_empty_label_vector():
    """With no labels K is 0 and every palette is long enough."""
    result = _markerSizeCheck(np.array([5.0]), _points(0), np.array([]))
    assert result.shape == (0,)


@requires_assertions
@pytest.mark.parametrize(
    "ms, message",
    [
        (5.0, "markersize array should be a numpy ndarray"),
        (np.array([[5.0, 10.0]]), "markersize array should be 1-dimensional"),
        (np.array([5.0, 0.0]), "all marker sizes must be positive"),
        (np.array([-1.0, 5.0]), "all marker sizes must be positive"),
        (np.array([5.0]), "markersize should be of size"),
    ],
)
def test_marker_size_check_rejects_bad_input(ms, message):
    """Type, dimensionality, positivity and length are each asserted."""
    with pytest.raises(AssertionError, match=message):
        _markerSizeCheck(ms, _points(), np.array([1, 2, 2]))


def test_line_color_check_returns_hex_strings():
    """One hex colour per line, in the order given."""
    assert _lineColorCheck(np.array([[255, 0, 0], [0, 0, 255]]), 2) == [
        "#ff0000",
        "#0000ff",
    ]


@requires_assertions
@pytest.mark.parametrize(
    "lc, K, message",
    [
        ([[255, 0, 0]], 1, "lc should be a numpy ndarray"),
        (np.array([[255, 0, 0]]), 2, "lc should be same shape as K"),
        (np.array([[-1, 0, 0]]), 1, "line colors have to be >= 0"),
        (np.array([[256, 0, 0]]), 1, "line colors have to be <= 255"),
        (np.array([[0.5, 0.0, 0.0]]), 1, "line colors are assumed to be ints"),
    ],
)
def test_line_color_check_rejects_bad_input(lc, K, message):
    """Same four checks as the marker colours, minus the palette expansion."""
    with pytest.raises(AssertionError, match=message):
        _lineColorCheck(lc, K)


def test_dash_check_returns_the_array_unchanged():
    """The dash styles are only length-checked, then passed straight through."""
    dash = np.array(["solid", "dash"])
    assert _dashCheck(dash, 2) is dash


@requires_assertions
@pytest.mark.parametrize(
    "dash, K, message",
    [
        (["solid"], 1, "dash should be a numpy ndarray"),
        (np.array(["solid"]), 2, "dash should be same shape as K"),
    ],
)
def test_dash_check_rejects_bad_input(dash, K, message):
    """Type and length only; the style strings themselves are not validated."""
    with pytest.raises(AssertionError, match=message):
        _dashCheck(dash, K)


def test_assert_opts_drops_a_none_title_with_a_warning(caplog):
    """title=None would crash the frontend, so it is removed and reported."""
    opts = {"title": None, "color": None}
    with caplog.at_level("WARNING", logger="visdom"):
        _assert_opts(opts)
    assert "title" not in opts
    assert "None-incompatible opt title" in caplog.text


def test_assert_opts_leaves_other_none_values_alone():
    """Only title is in the remove_nones list."""
    opts = {"color": None, "colormap": None}
    _assert_opts(opts)
    assert opts == {"color": None, "colormap": None}


def test_assert_opts_accepts_a_fully_populated_opts():
    """A realistic opts dict passes every branch at once."""
    _assert_opts(
        {
            "title": "loss",
            "color": "red",
            "colormap": "Viridis",
            "mode": "lines",
            "markersymbol": "dot",
            "markersize": 10,
            "markerborderwidth": 0,
            "columnnames": ["a"],
            "rownames": ["b"],
            "jpgquality": 100,
            "opacity": 1,
            "fps": 30,
        }
    )


@pytest.mark.parametrize("markersize", [1, 2.5, [1, 2], (1, 2), np.array([1.0, 2.0])])
def test_assert_opts_accepts_scalar_and_sequence_marker_sizes(markersize):
    """markersize may be one number or one per point."""
    _assert_opts({"markersize": markersize})


@requires_assertions
@pytest.mark.parametrize(
    "opts, message",
    [
        ({"color": 5}, "color should be a string"),
        ({"colormap": 5}, "colormap should be string"),
        ({"mode": 5}, "mode should be a string"),
        ({"markersymbol": 5}, "marker symbol should be string"),
        ({"title": 5}, "title should be a string"),
        ({"markersize": 0}, "marker size should be a positive number"),
        ({"markersize": -1}, "marker size should be a positive number"),
        ({"markersize": "big"}, "marker size should be a positive number"),
        ({"markersize": [1, 0]}, "all marker sizes must be positive"),
        ({"markerborderwidth": -1}, "marker border width should be a nonnegative"),
        ({"markerborderwidth": "x"}, "marker border width should be a nonnegative"),
        ({"columnnames": "abc"}, "columnnames should be a list"),
        ({"rownames": "abc"}, "rownames should be a list"),
        ({"jpgquality": "high"}, "JPG quality should be a number"),
        ({"jpgquality": 101}, "JPG quality should be number between 0 and 100"),
        ({"opacity": "half"}, "opacity should be a number"),
        ({"opacity": 1.5}, "opacity should be a number between 0 and 1"),
        ({"fps": "fast"}, "fps should be a number"),
        ({"fps": -1}, "fps must be greater than 0"),
    ],
)
def test_assert_opts_rejects_bad_input(opts, message):
    """Every type and range assertion, one case each."""
    with pytest.raises(AssertionError, match=message):
        _assert_opts(opts)


@pytest.mark.parametrize(
    "opts",
    [
        {"jpgquality": 100},
        {"jpgquality": 0},
        {"opacity": 0},
        {"opacity": 1},
        {"fps": 1},
    ],
)
def test_assert_opts_accepts_the_boundaries(opts):
    """The inclusive ends of each range are valid.

    ``opacity=0`` and ``jpgquality=0`` reach no assertion at all, since the
    guards are ``if opts.get(...)`` and zero is falsy.
    """
    _assert_opts(opts)


def _encoded(values, dtype="float64"):
    array = np.asarray(values, dtype=dtype)
    return {
        "dtype": dtype,
        "bdata": base64.b64encode(array.tobytes()).decode("ascii"),
    }


def test_decode_binary_arrays_decodes_a_leaf():
    """A dtype/bdata pair becomes a plain list."""
    assert _decode_binary_arrays(_encoded([1.0, 2.0, 3.0])) == [1.0, 2.0, 3.0]


def test_decode_binary_arrays_honours_a_shape():
    """A 2d array is restored rather than flattened."""
    encoded = _encoded([1.0, 2.0, 3.0, 4.0])
    encoded["shape"] = (2, 2)
    assert _decode_binary_arrays(encoded) == [[1.0, 2.0], [3.0, 4.0]]


@pytest.mark.parametrize("dtype", ["int32", "int64", "float32", "uint8"])
def test_decode_binary_arrays_supports_several_dtypes(dtype):
    """Plotly picks the narrowest dtype that fits, so all of them turn up."""
    assert _decode_binary_arrays(_encoded([1, 2, 3], dtype=dtype)) == [1, 2, 3]


def test_decode_binary_arrays_recurses_into_a_figure():
    """The encoded arrays sit inside the traces of a whole figure dict."""
    figure = {"data": [{"x": _encoded([1.0, 2.0]), "type": "scatter"}]}
    assert _decode_binary_arrays(figure) == {
        "data": [{"x": [1.0, 2.0], "type": "scatter"}]
    }


@pytest.mark.parametrize(
    "value",
    [{"a": 1}, [1, 2], "text", 5, None, {"dtype": "float64"}, {"bdata": "AA=="}],
)
def test_decode_binary_arrays_passes_everything_else_through(value):
    """Only a dict carrying both keys is treated as an encoded array."""
    assert _decode_binary_arrays(value) == value


@pytest.mark.parametrize(
    "encoded",
    [
        {"dtype": "float64", "bdata": "AAAAA"},
        {"dtype": "notadtype", "bdata": "AAAAAAAA8D8="},
        {"dtype": "float64", "bdata": "AAAAAAAA8D8=", "shape": (3, 3)},
    ],
)
def test_decode_binary_arrays_returns_the_original_on_failure(encoded):
    """Bad padding, an unknown dtype and an impossible shape are all survivable.

    ``plotlyplot`` runs this over whatever the installed Plotly produced, so an
    encoding it does not understand must leave the figure intact rather than
    raise out of the client.
    """
    assert _decode_binary_arrays(encoded) is encoded


def test_decode_binary_arrays_yields_an_empty_list_for_junk_base64():
    """A wart worth knowing about: junk decodes to nothing rather than failing.

    ``base64.b64decode`` ignores characters outside its alphabet unless
    ``validate=True``, so ``binascii.Error`` is only raised for bad padding.
    Everything else decodes to an empty buffer and the trace silently empties.
    """
    with pytest.raises(binascii.Error):
        base64.b64decode("!!!", validate=True)
    assert _decode_binary_arrays({"dtype": "float64", "bdata": "!!!"}) == []
