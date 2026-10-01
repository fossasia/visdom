#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for VisdomSklearnLogger.

These exercise the logger's pane-building logic directly (``_log_plain``,
``_log_cv``, ``_log_history``, ``_log_regression_diagnostics``, ``_win``)
against a mocked viz. ``autolog()`` is deliberately never called here: it
monkeypatches every real sklearn estimator class for the life of the
process, which would leak across the rest of the suite. The nested-fit
depth bookkeeping that ``autolog()`` relies on is instead exercised through
``_patch`` against small local classes defined per test.
"""

import unittest
from unittest.mock import Mock, patch

import numpy as np
import pytest
from sklearn.ensemble import (
    GradientBoostingRegressor,
    HistGradientBoostingClassifier,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.model_selection import GridSearchCV
from sklearn.neural_network import MLPClassifier

from visdom.loggers.sklearn import VisdomSklearnLogger

pytestmark = pytest.mark.unit


def _logger():
    return VisdomSklearnLogger(viz=Mock(), env="test_env")


class TestWin(unittest.TestCase):
    def test_same_estimator_reuses_tag(self):
        """Two panes for one estimator share the same base tag."""
        logger = _logger()
        est = LinearRegression()
        summary = logger._win(est, "summary")
        residuals = logger._win(est, "residuals")
        self.assertEqual(summary.rsplit("_", 1)[0], residuals.rsplit("_", 1)[0])

    def test_distinct_estimators_get_distinct_tags(self):
        """Two separate instances of the same class get separate tags."""
        logger = _logger()
        a, b = LinearRegression(), LinearRegression()
        self.assertNotEqual(logger._win(a, "summary"), logger._win(b, "summary"))

    def test_win_name_includes_class_and_pane(self):
        """The window id embeds the estimator class name and pane name."""
        logger = _logger()
        win = logger._win(LinearRegression(), "summary")
        self.assertTrue(win.startswith("LinearRegression_"))
        self.assertTrue(win.endswith("_summary"))


class TestRow(unittest.TestCase):
    def test_escapes_html(self):
        """Key and value are HTML-escaped before landing in the table row."""
        row = VisdomSklearnLogger._row("<b>k</b>", "<i>v</i>")
        self.assertIn("&lt;b&gt;k&lt;/b&gt;", row)
        self.assertIn("&lt;i&gt;v&lt;/i&gt;", row)


class TestLogPlainClassifier(unittest.TestCase):
    def setUp(self):
        self.logger = _logger()
        self.X = np.array([[0.0], [1.0], [2.0], [3.0]])
        self.y = np.array([0, 0, 1, 1])
        self.est = LogisticRegression().fit(self.X, self.y)

    def test_text_pane_written_once(self):
        self.logger._log_plain(self.est, self.X, self.y, 0.5)
        self.logger.viz.text.assert_called_once()

    def test_no_residual_scatter_for_classifier(self):
        """Classifiers skip the regression-only residual scatter."""
        self.logger._log_plain(self.est, self.X, self.y, 0.5)
        self.logger.viz.scatter.assert_not_called()

    def test_summary_includes_dataset_shape(self):
        self.logger._log_plain(self.est, self.X, self.y, 0.5)
        body = self.logger.viz.text.call_args[0][0]
        self.assertIn("4 x 1", body)

    def test_summary_includes_train_score(self):
        self.logger._log_plain(self.est, self.X, self.y, 0.5)
        body = self.logger.viz.text.call_args[0][0]
        self.assertIn("train_score", body)

    def test_refit_reuses_same_win(self):
        """Refitting the same estimator replaces its pane, not a new one."""
        self.logger._log_plain(self.est, self.X, self.y, 0.5)
        win1 = self.logger.viz.text.call_args.kwargs["win"]
        self.logger._log_plain(self.est, self.X, self.y, 0.7)
        win2 = self.logger.viz.text.call_args.kwargs["win"]
        self.assertEqual(win1, win2)


class TestLogPlainRegressor(unittest.TestCase):
    def setUp(self):
        self.logger = _logger()
        self.X = np.array([[0.0], [1.0], [2.0], [3.0]])
        self.y = np.array([0.0, 1.0, 2.0, 3.0])
        self.est = LinearRegression().fit(self.X, self.y)

    def test_residual_scatter_written(self):
        self.logger._log_plain(self.est, self.X, self.y, 0.1)
        self.logger.viz.scatter.assert_called_once()

    def test_summary_includes_rmse_and_mae(self):
        self.logger._log_plain(self.est, self.X, self.y, 0.1)
        body = self.logger.viz.text.call_args[0][0]
        self.assertIn("train_rmse", body)
        self.assertIn("train_mae", body)

    def test_residual_points_shape(self):
        """Residual scatter is Nx2: predicted value, residual."""
        self.logger._log_plain(self.est, self.X, self.y, 0.1)
        points = self.logger.viz.scatter.call_args.kwargs["X"]
        self.assertEqual(points.shape, (4, 2))


class TestRegressionDiagnostics(unittest.TestCase):
    def setUp(self):
        self.logger = _logger()
        self.X = np.array([[0.0], [1.0], [2.0]])
        self.y = np.array([1.0, 2.0, 3.0])
        self.est = LinearRegression().fit(self.X, self.y)

    def test_rmse_and_mae_values(self):
        """rmse/mae are computed from actual residuals, not train_score."""
        self.est.predict = Mock(return_value=np.array([1.0, 2.0, 4.0]))
        rows = []
        points = self.logger._log_regression_diagnostics(self.est, self.X, self.y, rows)
        # residuals = y - pred = [0, 0, -1]
        self.assertAlmostEqual(points[2, 1], -1.0)
        joined = "".join(rows)
        self.assertIn("0.5774", joined)  # rmse = sqrt(1/3)
        self.assertIn("0.3333", joined)  # mae = 1/3

    def test_column_y_is_raveled(self):
        """An (n, 1) y is flattened before diffing against predictions."""
        self.est.predict = Mock(return_value=np.array([1.0, 2.0, 3.0]))
        y_col = self.y.reshape(-1, 1)
        rows = []
        points = self.logger._log_regression_diagnostics(self.est, self.X, y_col, rows)
        self.assertEqual(points.shape, (3, 2))

    def test_classifier_returns_none(self):
        """Classifiers are skipped entirely; no rows are appended."""
        clf = LogisticRegression().fit(self.X, np.array([0, 0, 1]))
        rows = []
        result = self.logger._log_regression_diagnostics(clf, self.X, self.y, rows)
        self.assertIsNone(result)
        self.assertEqual(rows, [])

    def test_y_none_returns_none(self):
        rows = []
        result = self.logger._log_regression_diagnostics(self.est, self.X, None, rows)
        self.assertIsNone(result)

    def test_predict_exception_returns_none(self):
        self.est.predict = Mock(side_effect=ValueError("boom"))
        rows = []
        result = self.logger._log_regression_diagnostics(self.est, self.X, self.y, rows)
        self.assertIsNone(result)
        self.assertEqual(rows, [])

    def test_shape_mismatch_returns_none(self):
        """A wider multioutput prediction than y is dropped, not scattered."""
        self.est.predict = Mock(return_value=np.array([[1.0, 1.0], [2.0, 2.0]]))
        rows = []
        result = self.logger._log_regression_diagnostics(self.est, self.X, self.y, rows)
        self.assertIsNone(result)


class TestLogHistory(unittest.TestCase):
    def test_gradient_boosting_logs_train_score_line(self):
        logger = _logger()
        X = np.arange(20).reshape(-1, 1).astype(float)
        y = X.ravel() * 2
        est = GradientBoostingRegressor(n_estimators=3, random_state=0).fit(X, y)
        logger._log_history(est)
        logger.viz.line.assert_called_once()
        self.assertEqual(len(logger.viz.line.call_args.kwargs["Y"]), 3)

    def test_mlp_without_early_stopping_logs_loss_only(self):
        logger = _logger()
        X = np.array([[0.0, 0.0], [1.0, 1.0], [0.0, 1.0], [1.0, 0.0]])
        y = np.array([0, 1, 1, 0])
        est = MLPClassifier(hidden_layer_sizes=(2,), max_iter=5, random_state=0).fit(
            X, y
        )
        logger._log_history(est)
        self.assertEqual(logger.viz.line.call_count, 1)

    def test_mlp_with_early_stopping_logs_loss_and_validation(self):
        logger = _logger()
        rng = np.random.RandomState(0)
        X = rng.rand(20, 2)
        y = np.array([0, 1] * 10)
        est = MLPClassifier(
            hidden_layer_sizes=(2,),
            max_iter=20,
            early_stopping=True,
            n_iter_no_change=2,
            random_state=0,
        ).fit(X, y)
        logger._log_history(est)
        self.assertEqual(logger.viz.line.call_count, 2)

    def test_estimator_without_history_logs_nothing(self):
        logger = _logger()
        est = LinearRegression().fit(np.array([[0.0], [1.0]]), np.array([0.0, 1.0]))
        logger._log_history(est)
        logger.viz.line.assert_not_called()

    def _hist_gb(self, max_iter=15):
        rng = np.random.RandomState(0)
        X = rng.rand(300, 4)
        y = (X[:, 0] > 0.5).astype(int)
        return HistGradientBoostingClassifier(
            early_stopping=True, max_iter=max_iter, random_state=0
        ).fit(X, y)

    def _plot(self, logger, attr):
        for call in logger.viz.line.call_args_list:
            if attr in call.kwargs["opts"]["title"]:
                return call.kwargs
        return None

    def test_hist_gradient_boosting_train_score_starts_at_zero(self):
        # train_score_ is (n_iter_ + 1) long: its first entry is the score
        # before the first iteration, so the curve starts at 0, not 1.
        logger = _logger()
        est = self._hist_gb()
        logger._log_history(est)
        plot = self._plot(logger, "train_score_")
        self.assertIsNotNone(plot)
        self.assertEqual(len(est.train_score_), est.n_iter_ + 1)
        self.assertEqual(plot["X"][0], 0)
        self.assertEqual(plot["X"][-1], est.n_iter_)

    def test_validation_curve_starts_at_zero_when_it_has_a_baseline_entry(self):
        # validation_scores_ runs through the same x_start helper, so an
        # (n_iter_ + 1) curve has to start at 0 there too.
        logger = _logger()
        est = MLPClassifier(
            hidden_layer_sizes=(2,),
            max_iter=20,
            early_stopping=True,
            n_iter_no_change=2,
            random_state=0,
        ).fit(np.random.RandomState(0).rand(40, 2), np.array([0, 1] * 20))
        est.n_iter_ = len(est.validation_scores_) - 1
        logger._log_history(est)
        plot = self._plot(logger, "validation_scores_")
        self.assertIsNotNone(plot)
        self.assertEqual(plot["X"][0], 0)
        self.assertEqual(plot["X"][-1], est.n_iter_)

    def test_validation_curve_starts_at_one_without_a_baseline_entry(self):
        # MLP* normally report one score per epoch and no pre-training entry,
        # so that curve must keep starting at 1.
        logger = _logger()
        est = MLPClassifier(
            hidden_layer_sizes=(2,),
            max_iter=20,
            early_stopping=True,
            n_iter_no_change=2,
            random_state=0,
        ).fit(np.random.RandomState(0).rand(40, 2), np.array([0, 1] * 20))
        self.assertEqual(len(est.validation_scores_), est.n_iter_)
        logger._log_history(est)
        plot = self._plot(logger, "validation_scores_")
        self.assertEqual(plot["X"][0], 1)
        self.assertEqual(plot["X"][-1], len(est.validation_scores_))

    def test_gradient_boosting_train_score_still_starts_at_one(self):
        # The older family records only the iterations themselves, so its
        # curve must keep starting at 1.
        logger = _logger()
        X = np.arange(20).reshape(-1, 1).astype(float)
        est = GradientBoostingRegressor(n_estimators=3, random_state=0).fit(
            X, X.ravel() * 2
        )
        logger._log_history(est)
        plot = self._plot(logger, "train_score_")
        self.assertEqual(plot["X"], [1, 2, 3])


class TestValidationCurveDiscovery(unittest.TestCase):
    """The boosting estimators report a validation history under a different
    name than MLP*, and without reporting a loss curve at all."""

    def _hist_gb(self):
        rng = np.random.RandomState(0)
        X = rng.rand(300, 4)
        y = (X[:, 0] > 0.5).astype(int)
        return HistGradientBoostingClassifier(
            early_stopping=True, max_iter=15, random_state=0
        ).fit(X, y)

    def _titles(self, logger):
        return [c.kwargs["opts"]["title"] for c in logger.viz.line.call_args_list]

    def test_singular_attribute_is_found(self):
        logger = _logger()
        est = self._hist_gb()
        self.assertFalse(hasattr(est, "validation_scores_"))
        self.assertTrue(hasattr(est, "validation_score_"))
        logger._log_history(est)
        self.assertTrue(any("validation_score_" in t for t in self._titles(logger)))

    def test_found_without_a_loss_curve(self):
        # The lookup used to sit inside the loss_curve_ branch, which these
        # estimators never enter.
        logger = _logger()
        est = self._hist_gb()
        self.assertFalse(hasattr(est, "loss_curve_"))
        logger._log_history(est)
        self.assertEqual(logger.viz.line.call_count, 2)

    def test_plural_attribute_still_wins_for_mlp(self):
        logger = _logger()
        rng = np.random.RandomState(0)
        est = MLPClassifier(
            hidden_layer_sizes=(2,),
            max_iter=20,
            early_stopping=True,
            n_iter_no_change=2,
            random_state=0,
        ).fit(rng.rand(40, 2), np.array([0, 1] * 20))
        logger._log_history(est)
        titles = self._titles(logger)
        self.assertTrue(any("validation_scores_" in t for t in titles))
        self.assertEqual(logger.viz.line.call_count, 2)

    def test_only_one_validation_curve_when_both_names_exist(self):
        # A future sklearn exposing both aliases must not produce two panes
        # for the same history.
        logger = _logger()
        est = self._hist_gb()
        est.validation_scores_ = list(est.validation_score_)
        logger._log_history(est)
        titles = self._titles(logger)
        self.assertEqual(sum(1 for t in titles if "validation" in t), 1, titles)


class TestLogCv(unittest.TestCase):
    def setUp(self):
        self.logger = _logger()
        self.X = np.array([[0.0], [1.0], [2.0], [3.0]])
        self.y = np.array([0, 1, 0, 1])

    def test_bar_and_text_written(self):
        gs = GridSearchCV(LogisticRegression(), {"C": [0.1, 1.0]}, cv=2).fit(
            self.X, self.y
        )
        self.logger._log_cv(gs, 1.2)
        self.logger.viz.bar.assert_called_once()
        self.logger.viz.text.assert_called_once()

    def test_summary_includes_best_score_and_params(self):
        gs = GridSearchCV(LogisticRegression(), {"C": [0.1, 1.0]}, cv=2).fit(
            self.X, self.y
        )
        self.logger._log_cv(gs, 1.2)
        body = self.logger.viz.text.call_args[0][0]
        self.assertIn("best_score", body)
        self.assertIn("C", body)

    def test_refit_false_skips_best_score_without_crashing(self):
        """Multi-metric scoring with refit=False leaves best_score_ and
        best_params_ undefined on the estimator, unlike single-metric
        scoring where they remain available even with refit=False."""
        gs = GridSearchCV(
            LogisticRegression(),
            {"C": [0.1, 1.0]},
            cv=2,
            scoring=["accuracy", "f1_macro"],
            refit=False,
        ).fit(self.X, self.y)
        self.logger._log_cv(gs, 1.2)
        body = self.logger.viz.text.call_args[0][0]
        self.assertIn("refit=False", body)
        self.assertNotIn(">best_score<", body)

    def test_multi_metric_uses_refit_metric_score_key(self):
        gs = GridSearchCV(
            LogisticRegression(),
            {"C": [0.1, 1.0]},
            cv=2,
            scoring=["accuracy", "f1_macro"],
            refit="accuracy",
        ).fit(self.X, self.y)
        self.logger._log_cv(gs, 1.2)
        opts = self.logger.viz.bar.call_args.kwargs["opts"]
        self.assertEqual(opts["ylabel"], "mean_test_accuracy")


class TestPatchDepth(unittest.TestCase):
    """Covers the nested-fit dedup logic ``_patch`` builds for autolog()."""

    def setUp(self):
        self.logger = _logger()
        VisdomSklearnLogger.active = self.logger

    def tearDown(self):
        VisdomSklearnLogger.active = None

    def test_single_fit_logs_once(self):
        class Est:
            def fit(self, X, y=None):
                return self

        self.logger._patch(Est, is_cv=False)
        with patch.object(self.logger, "_log_plain") as mock_log:
            Est().fit(np.zeros((2, 1)), np.zeros(2))
        mock_log.assert_called_once()

    def test_double_patch_is_noop(self):
        class Est:
            def fit(self, X, y=None):
                return self

        self.logger._patch(Est, is_cv=False)
        patched_once = Est.fit
        self.logger._patch(Est, is_cv=False)
        self.assertIs(Est.fit, patched_once)

    def test_nested_fit_logs_only_outer(self):
        """A CV-style outer fit that calls an inner fit logs once, for the
        outer estimator, not the inner one it drives per fold."""

        class Inner:
            def fit(self, X, y=None):
                return self

        class Outer:
            def __init__(self):
                self.inner = Inner()

            def fit(self, X, y=None):
                self.inner.fit(X, y)
                return self

        self.logger._patch(Inner, is_cv=False)
        self.logger._patch(Outer, is_cv=False)
        with patch.object(self.logger, "_log_plain") as mock_log:
            outer = Outer().fit(np.zeros((2, 1)), np.zeros(2))
        mock_log.assert_called_once()
        self.assertIs(mock_log.call_args[0][0], outer)

    def test_logging_exception_is_swallowed_and_warned(self):
        """A failure while building panes must not break the user's fit()."""

        class Est:
            def fit(self, X, y=None):
                return self

        self.logger._patch(Est, is_cv=False)
        with patch.object(self.logger, "_log_plain", side_effect=RuntimeError("boom")):
            with self.assertWarns(UserWarning):
                result = Est().fit(np.zeros((2, 1)), np.zeros(2))
        self.assertIsInstance(result, Est)


if __name__ == "__main__":
    unittest.main()
