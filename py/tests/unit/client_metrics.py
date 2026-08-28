#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the client's metric and curve helpers.

``roc_curve``, ``pr_curve`` and ``confusion_matrix`` are built on ten private
numpy helpers near the top of ``visdom/__init__.py``. Nothing in the suite
touched any of them, which matters more here than elsewhere: these are the only
functions in the client that compute a *number* the user reads off the plot, so
a silent off-by-one in a threshold index shows up as a wrong AUC rather than as
a crash.

Two conventions worth knowing before editing this file:

* ``_compute_pr_curve`` returns ``(precision, recall)`` while its caller
  ``pr_curve`` immediately re-orders them into ``(recall, precision)`` for the
  x/y of the plot. The argument order is easy to swap; the tests name them.
* ``_compute_confusion_matrix`` indexes ``cm[actual, predicted]``. That
  orientation is invisible on a symmetric example, so the tests use a
  deliberately asymmetric one.
"""

import warnings
from unittest.mock import patch

import numpy as np
import pytest

from visdom import (
    _average_precision,
    _binary_clf_curve,
    _coerce_curve_xy,
    _compute_confusion_matrix,
    _compute_pr_curve,
    _compute_roc_curve,
    _curve_legend,
    _trapz_area,
    _validate_curve_range,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "y_true, y_score, message",
    [
        ([[0, 1], [1, 0]], [0.1, 0.2, 0.3, 0.4], "y_true should have 1 dim"),
        ([0, 1], [[0.1, 0.2]], "y_score should have 1 dim"),
        ([0, 1, 1], [0.1, 0.2], "y_true and y_score should match"),
        ([], [], "y_true and y_score should be non-empty"),
        ([0, 1], [0.1, float("nan")], "y_score should only contain finite values"),
        ([0, 1], [0.1, float("inf")], "y_score should only contain finite values"),
    ],
)
def test_binary_clf_curve_rejects_bad_input(y_true, y_score, message):
    """Each guard raises ValueError with its own message."""
    with pytest.raises(ValueError, match=message):
        _binary_clf_curve(np.asarray(y_true), np.asarray(y_score))


def test_binary_clf_curve_counts_at_each_threshold():
    """Scores descend, and each entry is the running count at that threshold."""
    fps, tps = _binary_clf_curve(
        np.array([0, 0, 1, 1]), np.array([0.1, 0.4, 0.35, 0.8])
    )
    np.testing.assert_array_equal(tps, [1.0, 1.0, 2.0, 2.0])
    np.testing.assert_array_equal(fps, [0.0, 1.0, 1.0, 2.0])


def test_binary_clf_curve_totals_are_the_class_sizes():
    """The last entry of each array is the total count of that class."""
    y_true = np.array([1, 0, 1, 1, 0])
    fps, tps = _binary_clf_curve(y_true, np.array([0.9, 0.8, 0.7, 0.6, 0.5]))
    assert tps[-1] == float((y_true == 1).sum())
    assert fps[-1] == float((y_true == 0).sum())


def test_binary_clf_curve_collapses_tied_scores():
    """Equal scores share one threshold, so four samples give two rows."""
    fps, tps = _binary_clf_curve(np.array([1, 0, 1, 0]), np.array([0.5, 0.5, 0.2, 0.2]))
    assert tps.shape == (2,)
    np.testing.assert_array_equal(tps, [1.0, 2.0])
    np.testing.assert_array_equal(fps, [1.0, 2.0])


def test_binary_clf_curve_keeps_the_fps_identity():
    """fps is defined as 1 + threshold_idx - tps; the sum is the sample count."""
    fps, tps = _binary_clf_curve(
        np.array([1, 0, 1, 0, 1]), np.array([0.9, 0.7, 0.5, 0.3, 0.1])
    )
    np.testing.assert_array_equal(fps + tps, [1.0, 2.0, 3.0, 4.0, 5.0])


def test_binary_clf_curve_honours_pos_label():
    """pos_label selects which class counts as positive."""
    y_true = np.array([2, 3, 2, 3])
    y_score = np.array([0.9, 0.8, 0.7, 0.6])
    _, tps_two = _binary_clf_curve(y_true, y_score, pos_label=2)
    _, tps_three = _binary_clf_curve(y_true, y_score, pos_label=3)
    assert tps_two[-1] == 2.0
    assert tps_three[-1] == 2.0
    np.testing.assert_array_equal(tps_two, [1.0, 1.0, 2.0, 2.0])
    np.testing.assert_array_equal(tps_three, [0.0, 1.0, 1.0, 2.0])


def test_binary_clf_curve_accepts_string_labels_via_pos_label():
    """y_true need not be numeric; it is compared against pos_label."""
    fps, tps = _binary_clf_curve(
        np.array(["spam", "ham", "spam"]),
        np.array([0.9, 0.5, 0.4]),
        pos_label="spam",
    )
    np.testing.assert_array_equal(tps, [1.0, 1.0, 2.0])
    np.testing.assert_array_equal(fps, [0.0, 1.0, 1.0])


def test_roc_curve_starts_at_origin_and_ends_at_one():
    """np.r_ prepends the origin, and both rates reach 1 at the last point."""
    fpr, tpr = _compute_roc_curve(
        np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])
    )
    assert fpr[0] == 0.0 and tpr[0] == 0.0
    assert fpr[-1] == 1.0 and tpr[-1] == 1.0


def test_roc_curve_of_a_perfect_classifier_hugs_the_corner():
    """Perfect separation reaches tpr 1 while fpr is still 0."""
    fpr, tpr = _compute_roc_curve(
        np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])
    )
    assert _trapz_area(tpr, fpr) == pytest.approx(1.0)
    assert tpr[np.argmax(fpr > 0) - 1] == 1.0


def test_roc_curve_of_a_scoreless_classifier_is_the_diagonal():
    """All scores tied means no discrimination, so the area is one half."""
    fpr, tpr = _compute_roc_curve(
        np.array([0, 1, 0, 1]), np.array([0.5, 0.5, 0.5, 0.5])
    )
    np.testing.assert_array_equal(fpr, [0.0, 1.0])
    np.testing.assert_array_equal(tpr, [0.0, 1.0])
    assert _trapz_area(tpr, fpr) == pytest.approx(0.5)


def test_roc_curve_of_an_inverted_classifier_falls_below_the_diagonal():
    """Ranking positives last gives an area under one half."""
    fpr, tpr = _compute_roc_curve(
        np.array([0, 1, 0, 1]), np.array([0.4, 0.3, 0.2, 0.1])
    )
    assert _trapz_area(tpr, fpr) == pytest.approx(0.25)


def test_roc_curve_is_monotone():
    """Both rates are non-decreasing, which is what makes the area meaningful."""
    rng = np.random.RandomState(0)
    y_true = rng.randint(0, 2, size=40)
    fpr, tpr = _compute_roc_curve(y_true, rng.rand(40))
    assert (np.diff(fpr) >= 0).all()
    assert (np.diff(tpr) >= 0).all()


@pytest.mark.parametrize(
    "y_true, message",
    [
        ([0, 0, 0], "y_true has no positive samples"),
        ([1, 1, 1], "y_true has no negative samples"),
    ],
)
def test_roc_curve_needs_both_classes(y_true, message):
    """A single-class y_true cannot produce a rate, so it raises."""
    with pytest.raises(ValueError, match=message):
        _compute_roc_curve(np.asarray(y_true), np.array([0.1, 0.2, 0.3]))


def test_pr_curve_starts_at_precision_one_and_recall_zero():
    """np.r_ prepends the (0 recall, 1 precision) anchor point."""
    precision, recall = _compute_pr_curve(
        np.array([0, 1, 1, 0]), np.array([0.1, 0.9, 0.8, 0.2])
    )
    assert precision[0] == 1.0
    assert recall[0] == 0.0


def test_pr_curve_recall_is_monotone_and_reaches_one():
    """Recall never decreases and ends at every positive being retrieved."""
    precision, recall = _compute_pr_curve(
        np.array([1, 0, 1, 0, 1]), np.array([0.9, 0.8, 0.7, 0.6, 0.5])
    )
    assert (np.diff(recall) >= 0).all()
    assert recall[-1] == pytest.approx(1.0)


def test_pr_curve_precision_stays_in_range():
    """Precision is tps/(tps+fps), so it can never leave [0, 1]."""
    rng = np.random.RandomState(7)
    y_true = np.concatenate([np.ones(10), np.zeros(10)]).astype(int)
    precision, _ = _compute_pr_curve(y_true, rng.rand(20))
    assert ((precision >= 0.0) & (precision <= 1.0)).all()


def test_pr_curve_of_a_perfect_classifier_holds_precision_at_one():
    """With perfect separation precision stays 1 until recall is exhausted."""
    precision, recall = _compute_pr_curve(
        np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])
    )
    assert precision[recall <= 1.0][: int((recall == 1.0).argmax()) + 1].min() == 1.0


def test_pr_curve_needs_a_positive_sample():
    """Recall is undefined with no positives, so it raises rather than divide."""
    with pytest.raises(ValueError, match="y_true has no positive samples"):
        _compute_pr_curve(np.array([0, 0, 0]), np.array([0.1, 0.2, 0.3]))


@pytest.mark.parametrize(
    "x, y, message",
    [
        ([[0.0, 1.0]], [0.0, 1.0], "fpr should have 1 dim"),
        ([0.0, 1.0], [[0.0, 1.0]], "tpr should have 1 dim"),
        ([0.0, 0.5, 1.0], [0.0, 1.0], "fpr and tpr should match"),
        ([0.0], [1.0], "fpr and tpr should have at least 2 points"),
        ([], [], "fpr and tpr should have at least 2 points"),
    ],
)
def test_coerce_curve_xy_rejects_bad_input(x, y, message):
    """The guards raise ValueError, quoting the caller's names for the axes."""
    with pytest.raises(ValueError, match=message):
        _coerce_curve_xy(x, y, "fpr", "tpr")


def test_coerce_curve_xy_sorts_y_alongside_x():
    """Points are paired: reordering x must carry each y with it."""
    x, y = _coerce_curve_xy([0.9, 0.1, 0.5], [3.0, 1.0, 2.0], "fpr", "tpr")
    np.testing.assert_array_equal(x, [0.1, 0.5, 0.9])
    np.testing.assert_array_equal(y, [1.0, 2.0, 3.0])


def test_coerce_curve_xy_is_stable_on_ties():
    """Equal x keep their input order, so a flat segment is not shuffled."""
    x, y = _coerce_curve_xy([0.5, 0.5, 0.1], [1.0, 2.0, 0.0], "fpr", "tpr")
    np.testing.assert_array_equal(x, [0.1, 0.5, 0.5])
    np.testing.assert_array_equal(y, [0.0, 1.0, 2.0])


def test_coerce_curve_xy_accepts_lists_and_returns_arrays():
    """Plain Python sequences are coerced, so callers need not import numpy."""
    x, y = _coerce_curve_xy([0.0, 1.0], (2.0, 3.0), "recall", "precision")
    assert isinstance(x, np.ndarray) and isinstance(y, np.ndarray)


def test_coerce_curve_xy_uses_the_given_names_in_messages():
    """The names are parameters, not hardcoded, so pr_curve reads correctly."""
    with pytest.raises(ValueError, match="recall and precision should match"):
        _coerce_curve_xy([0.0, 0.5, 1.0], [0.0, 1.0], "recall", "precision")


@pytest.mark.parametrize(
    "values",
    [
        [0.0, float("nan")],
        [0.0, float("inf")],
        [0.0, float("-inf")],
        [-0.1, 0.5],
        [0.5, 1.1],
    ],
)
def test_validate_curve_range_rejects_out_of_range(values):
    """Non-finite or outside [0, 1] is rejected, naming the offending array."""
    with pytest.raises(ValueError, match="fpr"):
        _validate_curve_range(values, "fpr")


@pytest.mark.parametrize("values", [[0.0, 1.0], [0.0], [1.0], [0.5, 0.5], []])
def test_validate_curve_range_accepts_the_boundaries(values):
    """Both endpoints are inclusive, and an empty array is vacuously valid."""
    assert _validate_curve_range(values, "tpr") is None


def test_validate_curve_range_reports_non_finite_before_range():
    """NaN fails the finite check, whose message is the more useful one."""
    with pytest.raises(ValueError, match="should only contain finite values"):
        _validate_curve_range([float("nan")], "tpr")


def test_curve_legend_returns_a_copy_of_the_default():
    """The default list must not be handed out for a caller to mutate."""
    default = ["ROC", "Chance"]
    result = _curve_legend(None, default)
    assert result == default
    result.append("extra")
    assert default == ["ROC", "Chance"]


def test_curve_legend_falls_back_silently_on_none():
    """No legend at all is the normal case and must not warn."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _curve_legend(None, ["PR", "Baseline"]) == ["PR", "Baseline"]


@pytest.mark.parametrize("legend", [["only"], "ROC", 5, {}, ()])
def test_curve_legend_warns_when_a_legend_is_unusable(legend):
    """A supplied but unusable legend is a mistake worth telling the user about."""
    with pytest.warns(UserWarning, match="at least 2 elements"):
        assert _curve_legend(legend, ["ROC", "Chance"]) == ["ROC", "Chance"]


def test_curve_legend_passes_a_valid_legend_through():
    """Two or more elements are accepted verbatim, as a list."""
    assert _curve_legend(("a", "b"), ["ROC", "Chance"]) == ["a", "b"]
    assert _curve_legend(["a", "b", "c"], ["ROC", "Chance"]) == ["a", "b", "c"]


@pytest.mark.parametrize(
    "y, x, expected",
    [
        ([0.0, 1.0], [0.0, 1.0], 0.5),
        ([1.0, 1.0], [0.0, 1.0], 1.0),
        ([0.0, 0.0], [0.0, 1.0], 0.0),
        ([0.0, 1.0, 1.0], [0.0, 0.5, 1.0], 0.75),
    ],
)
def test_trapz_area(y, x, expected):
    """The trapezoid rule over a few shapes with an obvious area."""
    assert _trapz_area(np.asarray(y), np.asarray(x)) == pytest.approx(expected)


def test_trapz_area_returns_a_plain_float():
    """The result is formatted into a title, so it must not be a numpy scalar."""
    assert type(_trapz_area(np.array([0.0, 1.0]), np.array([0.0, 1.0]))) is float


def test_trapz_area_falls_back_when_numpy_has_no_trapezoid():
    """numpy < 2.0 has only np.trapz, and np.trapezoid is what 2.0 renamed it to.

    np.trapz was removed outright in numpy 2.0, so on the version this suite
    runs against the fallback branch is unreachable without standing both
    attributes up by hand.
    """
    with patch.object(np, "trapezoid", None):
        with patch.object(np, "trapz", lambda y, x: 42.0, create=True):
            assert _trapz_area(np.array([0.0, 1.0]), np.array([0.0, 1.0])) == 42.0


@pytest.mark.parametrize(
    "precision, recall, expected",
    [
        ([1.0, 1.0], [0.0, 1.0], 1.0),
        ([1.0, 0.5], [0.0, 1.0], 0.5),
        ([1.0, 1.0, 0.5], [0.0, 0.5, 1.0], 0.75),
        ([1.0, 1.0], [0.0, 0.0], 0.0),
    ],
)
def test_average_precision(precision, recall, expected):
    """AP weights each precision by the recall gained at that step."""
    assert _average_precision(precision, recall) == pytest.approx(expected)


def test_average_precision_ignores_the_first_precision():
    """The anchor point contributes nothing, since diff(recall) is one shorter."""
    assert _average_precision([0.0, 1.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_average_precision_returns_a_plain_float():
    """Like the ROC area, it is formatted into the default title."""
    assert type(_average_precision([1.0, 1.0], [0.0, 1.0])) is float


def test_confusion_matrix_of_a_perfect_prediction_is_diagonal():
    """Every sample lands on the diagonal when the prediction is right."""
    cm = _compute_confusion_matrix(
        np.array([0, 1, 2, 1]), np.array([0, 1, 2, 1]), [0, 1, 2]
    )
    np.testing.assert_array_equal(cm, np.diag([1, 2, 1]))


def test_confusion_matrix_is_indexed_actual_then_predicted():
    """One sample, actual 0 predicted 1, sits at cm[0][1] and not cm[1][0]."""
    cm = _compute_confusion_matrix(np.array([0]), np.array([1]), [0, 1])
    assert cm[0][1] == 1
    assert cm[1][0] == 0


def test_confusion_matrix_counts_repeated_pairs():
    """Repeats accumulate in the same cell."""
    cm = _compute_confusion_matrix(np.array([1, 1, 1]), np.array([0, 0, 1]), [0, 1])
    assert cm[1][0] == 2
    assert cm[1][1] == 1


def test_confusion_matrix_has_integer_dtype():
    """Counts are ints; normalization in the caller casts to float afterwards."""
    cm = _compute_confusion_matrix(np.array([0]), np.array([0]), [0])
    assert np.issubdtype(cm.dtype, np.integer)


def test_confusion_matrix_supports_string_labels():
    """Labels are dict keys, so any hashable works."""
    cm = _compute_confusion_matrix(
        np.array(["cat", "dog"]), np.array(["dog", "dog"]), ["cat", "dog"]
    )
    np.testing.assert_array_equal(cm, [[0, 1], [0, 1]])


def test_confusion_matrix_keeps_an_unused_label_as_an_empty_row_and_column():
    """A label present only in `labels` still gets its slot in the matrix."""
    cm = _compute_confusion_matrix(np.array([0, 0]), np.array([0, 0]), [0, 1, 2])
    assert cm.shape == (3, 3)
    assert cm[1].sum() == 0 and cm[:, 1].sum() == 0


def test_confusion_matrix_skips_unknown_labels_with_a_warning():
    """Samples outside `labels` are dropped, and the count is reported."""
    with pytest.warns(UserWarning, match="2 samples had labels not in"):
        cm = _compute_confusion_matrix(np.array([0, 1, 9]), np.array([0, 9, 1]), [0, 1])
    assert cm.sum() == 1
    assert cm[0][0] == 1


def test_confusion_matrix_does_not_warn_when_everything_is_known():
    """The warning is conditional on skipped > 0."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _compute_confusion_matrix(np.array([0, 1]), np.array([1, 0]), [0, 1])


@pytest.mark.parametrize(
    "y_true, y_pred, message",
    [
        ([0, 1, 1], [0, 1], "must have the same length"),
        ([], [], "must be non-empty"),
    ],
)
def test_confusion_matrix_rejects_bad_input(y_true, y_pred, message):
    """Length mismatch and an empty pair raise before the counting loop."""
    with pytest.raises(ValueError, match=message):
        _compute_confusion_matrix(np.asarray(y_true), np.asarray(y_pred), [0, 1])


def test_roc_curve_from_raw_labels_sends_two_traces(capture_send):
    """The curve itself plus the dashed chance baseline."""
    sent = capture_send(
        lambda v: v.roc_curve(y_true=[0, 0, 1, 1], y_score=[0.1, 0.2, 0.8, 0.9])
    )
    data = sent["payload"]["data"]
    assert len(data) == 2
    assert data[0]["mode"] == "lines"
    assert data[1]["x"] == [0.0, 1.0] and data[1]["y"] == [0.0, 1.0]
    assert data[1]["line"]["dash"] == "dash"


def test_roc_curve_default_title_carries_the_area(capture_send):
    """A perfect classifier is reported as AUC 1.0000."""
    sent = capture_send(
        lambda v: v.roc_curve(y_true=[0, 0, 1, 1], y_score=[0.1, 0.2, 0.8, 0.9])
    )
    assert sent["payload"]["opts"]["title"] == "ROC Curve (AUC=1.0000)"


def test_roc_curve_default_axis_labels_and_legend(capture_send):
    """The rate names are filled in when the caller supplies no opts."""
    sent = capture_send(lambda v: v.roc_curve(y_true=[0, 1], y_score=[0.2, 0.8]))
    opts = sent["payload"]["opts"]
    assert opts["xlabel"] == "False Positive Rate"
    assert opts["ylabel"] == "True Positive Rate"
    assert opts["legend"] == ["ROC", "Chance"]


def test_roc_curve_respects_supplied_opts(capture_send):
    """User values win over every default, including the title."""
    sent = capture_send(
        lambda v: v.roc_curve(
            y_true=[0, 1],
            y_score=[0.2, 0.8],
            opts={"title": "mine", "xlabel": "x", "legend": ["a", "b"]},
        )
    )
    opts = sent["payload"]["opts"]
    assert opts["title"] == "mine"
    assert opts["xlabel"] == "x"
    assert sent["payload"]["data"][0]["name"] == "a"


def test_roc_curve_from_precomputed_points(capture_send):
    """The (fpr, tpr) mode skips the metric helpers and plots what it is given."""
    sent = capture_send(lambda v: v.roc_curve(fpr=[0.0, 0.5, 1.0], tpr=[0.0, 0.9, 1.0]))
    assert sent["payload"]["data"][0]["x"] == [0.0, 0.5, 1.0]
    assert sent["payload"]["data"][0]["y"] == [0.0, 0.9, 1.0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"y_true": [0, 1], "y_score": [0.2, 0.8], "fpr": [0.0, 1.0]},
        {"y_true": [0, 1], "tpr": [0.0, 1.0]},
    ],
)
def test_roc_curve_requires_exactly_one_input_mode(offline_client, kwargs):
    """Neither mode, or both at once, is ambiguous and refused."""
    with pytest.raises(ValueError, match="exactly one input mode"):
        offline_client.roc_curve(**kwargs)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"y_true": [0, 1]}, "both y_true and y_score are required"),
        ({"y_score": [0.2, 0.8]}, "both y_true and y_score are required"),
        ({"fpr": [0.0, 1.0]}, "both fpr and tpr are required"),
        ({"tpr": [0.0, 1.0]}, "both fpr and tpr are required"),
    ],
)
def test_roc_curve_requires_both_halves_of_a_mode(offline_client, kwargs, message):
    """Half a pair picks a mode but cannot satisfy it."""
    with pytest.raises(ValueError, match=message):
        offline_client.roc_curve(**kwargs)


def test_roc_curve_rejects_points_outside_the_unit_square(offline_client):
    """Precomputed rates are validated, since nothing else would catch them."""
    with pytest.raises(ValueError, match="fpr should be within"):
        offline_client.roc_curve(fpr=[0.0, 1.5], tpr=[0.0, 1.0])


def test_pr_curve_plots_recall_against_precision(capture_send):
    """Recall is x and precision is y, the opposite order to the helper."""
    sent = capture_send(
        lambda v: v.pr_curve(y_true=[0, 1, 1, 0], y_score=[0.1, 0.9, 0.8, 0.2])
    )
    trace = sent["payload"]["data"][0]
    assert trace["x"][0] == 0.0
    assert trace["y"][0] == 1.0
    assert (np.diff(trace["x"]) >= 0).all()


def test_pr_curve_baseline_is_the_positive_rate(capture_send):
    """The dashed line sits at the share of positives in y_true."""
    sent = capture_send(
        lambda v: v.pr_curve(y_true=[0, 0, 0, 1], y_score=[0.1, 0.2, 0.3, 0.9])
    )
    baseline = sent["payload"]["data"][1]
    assert baseline["y"] == [0.25, 0.25]
    assert baseline["line"]["dash"] == "dash"


def test_pr_curve_default_title_carries_the_average_precision(capture_send):
    """A perfect ranking gives AP 1.0000."""
    sent = capture_send(
        lambda v: v.pr_curve(y_true=[0, 0, 1, 1], y_score=[0.1, 0.2, 0.8, 0.9])
    )
    assert sent["payload"]["opts"]["title"] == "PR Curve (AUC=1.0000)"
    assert sent["payload"]["opts"]["xlabel"] == "Recall"
    assert sent["payload"]["opts"]["ylabel"] == "Precision"


def test_pr_curve_from_precomputed_points_infers_the_baseline(capture_send):
    """With recall starting at 0, precision[0] stands in for the positive rate."""
    sent = capture_send(
        lambda v: v.pr_curve(recall=[0.0, 0.5, 1.0], precision=[0.4, 0.4, 0.4])
    )
    assert sent["payload"]["data"][1]["y"] == [0.4, 0.4]


def test_pr_curve_omits_the_baseline_when_it_cannot_be_inferred(capture_send):
    """Precomputed points that do not start at recall 0 get the curve only."""
    sent = capture_send(
        lambda v: v.pr_curve(recall=[0.2, 0.6, 1.0], precision=[0.4, 0.4, 0.4])
    )
    assert len(sent["payload"]["data"]) == 1


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "exactly one input mode"),
        (
            {"y_true": [0, 1], "y_score": [0.2, 0.8], "recall": [0.0, 1.0]},
            "exactly one input mode",
        ),
        ({"recall": [0.0, 1.0]}, "both precision and recall are required"),
        ({"precision": [1.0, 1.0]}, "both precision and recall are required"),
    ],
)
def test_pr_curve_input_mode_errors(offline_client, kwargs, message):
    """Same two-mode contract as roc_curve, with its own message."""
    with pytest.raises(ValueError, match=message):
        offline_client.pr_curve(**kwargs)


def test_confusion_matrix_sends_a_heatmap_with_string_tick_labels(capture_send):
    """Labels become strings so plotly treats the axes as categorical."""
    sent = capture_send(
        lambda v: v.confusion_matrix(y_true=[0, 1, 1], y_pred=[0, 1, 0])
    )
    trace = sent["payload"]["data"][0]
    assert trace["type"] == "heatmap"
    assert trace["x"] == ["0", "1"] and trace["y"] == ["0", "1"]
    assert trace["z"] == [[1, 0], [1, 1]]


def test_confusion_matrix_defaults(capture_send):
    """Title, axis labels and colormap all have defaults."""
    sent = capture_send(lambda v: v.confusion_matrix(y_true=[0, 1], y_pred=[0, 1]))
    opts = sent["payload"]["opts"]
    assert opts["title"] == "Confusion Matrix"
    assert opts["xlabel"] == "Predicted" and opts["ylabel"] == "Actual"
    assert sent["payload"]["data"][0]["colorscale"] == "Blues"


def test_confusion_matrix_reverses_the_y_axis(capture_send):
    """Actual classes read top to bottom, which needs an explicit autorange."""
    sent = capture_send(lambda v: v.confusion_matrix(y_true=[0, 1], y_pred=[0, 1]))
    layout = sent["payload"]["layout"]
    assert layout["yaxis"]["autorange"] == "reversed"
    assert layout["xaxis"]["side"] == "bottom"


def test_confusion_matrix_annotates_every_cell(capture_send):
    """One annotation per cell, carrying the raw count."""
    sent = capture_send(
        lambda v: v.confusion_matrix(y_true=[0, 1, 1], y_pred=[0, 1, 0])
    )
    annotations = sent["payload"]["layout"]["annotations"]
    assert len(annotations) == 4
    assert [a["text"].split("<br>")[0] for a in annotations] == ["1", "0", "1", "1"]


def test_confusion_matrix_from_a_precomputed_matrix(capture_send):
    """The cm mode numbers its own labels when none are given."""
    sent = capture_send(lambda v: v.confusion_matrix(cm=[[5, 1], [2, 4]]))
    assert sent["payload"]["data"][0]["z"] == [[5, 1], [2, 4]]
    assert sent["payload"]["data"][0]["x"] == ["0", "1"]


def test_confusion_matrix_normalizes_by_row(capture_send):
    """normalize='true' turns each actual row into a distribution."""
    sent = capture_send(
        lambda v: v.confusion_matrix(cm=[[3, 1], [0, 4]], normalize="true")
    )
    assert sent["payload"]["data"][0]["z"] == [[0.75, 0.25], [0.0, 1.0]]


def test_confusion_matrix_normalized_cells_show_a_percentage(capture_send):
    """Normalizing switches showPercent on, keeping the raw count alongside."""
    sent = capture_send(
        lambda v: v.confusion_matrix(cm=[[3, 1], [0, 4]], normalize="all")
    )
    assert sent["payload"]["layout"]["annotations"][0]["text"] == "3<br>37.5%"


def test_confusion_matrix_remove_deletes_through_the_update_endpoint(capture_send):
    """update='remove' short-circuits before any matrix is built."""
    sent = capture_send(lambda v: v.confusion_matrix(win="cm1", update="remove"))
    assert sent["endpoint"] == "update"
    assert sent["payload"]["delete"] is True
    assert sent["payload"]["win"] == "cm1"
    assert sent["payload"]["data"] == []


def test_confusion_matrix_replace_marks_the_update_direction(capture_send):
    """update='replace' redraws in place rather than opening a new pane."""
    sent = capture_send(
        lambda v: v.confusion_matrix(cm=[[1, 0], [0, 1]], win="cm1", update="replace")
    )
    assert sent["endpoint"] == "update"
    assert sent["payload"]["updateDir"] == "replace"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "exactly one input mode"),
        ({"y_true": [0], "y_pred": [0], "cm": [[1]]}, "exactly one input mode"),
        ({"y_true": [0, 1]}, "both y_true and y_pred are required"),
        ({"cm": [[1, 2, 3], [4, 5, 6]]}, "cm must be a square 2D array"),
        ({"cm": [1, 2]}, "cm must be a square 2D array"),
        ({"cm": [[1, 0], [0, 1]], "labels": ["a"]}, "number of labels must match"),
        ({"cm": [[1, 0], [0, 1]], "labels": ["a", "a"]}, "labels must be unique"),
        ({"cm": [[1]], "normalize": "rows"}, "normalize must be one of"),
    ],
)
def test_confusion_matrix_input_errors(offline_client, kwargs, message):
    """Every ValueError guard on the public method."""
    with pytest.raises(ValueError, match=message):
        offline_client.confusion_matrix(**kwargs)
