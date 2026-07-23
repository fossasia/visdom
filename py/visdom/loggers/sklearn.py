#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import functools
import html
import threading
import time

import numpy as np

_TD_KEY = (
    "style='padding:2px 10px 2px 0;" "color:#555;white-space:nowrap;vertical-align:top'"
)
_TD_VAL = "style='padding:2px 0;vertical-align:top'"
_WRAP = "style='font-family:monospace;font-size:12px;" "padding:6px;line-height:1.5'"
_TITLE = (
    "style='font-size:14px;font-weight:bold;"
    "border-bottom:1px solid #ddd;padding-bottom:4px;margin-bottom:6px'"
)
_SECTION = (
    "style='font-size:10px;font-weight:bold;text-transform:uppercase;"
    "color:#888;margin:8px 0 4px'"
)


class VisdomSklearnLogger:
    """Auto-logs sklearn estimator fit() calls to Visdom.

    Call autolog() once at the start of your script. Every subsequent
    fit() call on any sklearn estimator is logged automatically.

    GridSearchCV and RandomizedSearchCV produce a bar chart of
    mean_test_score per parameter combination and a text pane with
    best_params_ and best_score_. All other estimators produce a text
    pane with dataset shape, train score, fit time, and hyperparameters.
    Estimators that expose a per-iteration training history
    (MLPClassifier/MLPRegressor via loss_curve_,
    GradientBoostingClassifier/GradientBoostingRegressor via
    train_score_) additionally produce a line chart of that history.
    MLPClassifier/MLPRegressor fit with early_stopping=True also produce
    a line chart of validation_scores_ per epoch.
    Regressors additionally get rmse/mae rows in the text pane (R2 alone
    can be misleading) and a predicted-vs-residual scatter plot.

    Usage::

        from visdom.loggers import VisdomSklearnLogger

        VisdomSklearnLogger.autolog()

        clf.fit(X_train, y_train)   # logged automatically
        gs.fit(X_train, y_train)    # logged automatically
    """

    active = None

    def __init__(self, viz=None, env=None):
        if viz is None:
            import visdom as _visdom

            viz = _visdom.Visdom()
        self.viz = viz
        self.env = env
        self._local = threading.local()

    @property
    def _depth(self):
        return getattr(self._local, "depth", 0)

    @_depth.setter
    def _depth(self, value):
        self._local.depth = value

    @classmethod
    def autolog(cls, viz=None, env=None):
        """Patch all sklearn estimators to log fit() calls to Visdom."""
        try:
            from sklearn.model_selection import (
                GridSearchCV,
                RandomizedSearchCV,
            )
            from sklearn.utils import all_estimators
        except ImportError:
            raise ImportError(
                "scikit-learn is required for VisdomSklearnLogger. "
                "Install with: pip install scikit-learn"
            )
        instance = cls(viz, env)
        _viz_env = getattr(instance.viz, "env", None)
        instance.env = (
            env
            or (_viz_env if _viz_env and _viz_env != "main" else None)
            or "sklearn_{}".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        )
        cls.active = instance
        for cv_cls in (GridSearchCV, RandomizedSearchCV):
            instance._patch(cv_cls, is_cv=True)
        for _name, est_cls in all_estimators():
            instance._patch(est_cls, is_cv=False)

    def _patch(self, cls, is_cv):
        if not hasattr(cls, "fit"):
            return
        if getattr(cls.fit, "_visdom_patched", False):
            return

        original = cls.fit
        visdom_cls = self.__class__

        if is_cv:

            @functools.wraps(original)
            def patched_fit(self_est, *args, **kwargs):
                logger = visdom_cls.active
                logger._depth += 1
                t0 = time.time()
                try:
                    result = original(self_est, *args, **kwargs)
                finally:
                    logger._depth -= 1
                duration = time.time() - t0
                if logger._depth == 0:
                    logger._log_cv(self_est, duration)
                return result

        else:

            @functools.wraps(original)
            def patched_fit(self_est, *args, **kwargs):
                logger = visdom_cls.active
                logger._depth += 1
                t0 = time.time()
                try:
                    result = original(self_est, *args, **kwargs)
                finally:
                    logger._depth -= 1
                duration = time.time() - t0
                if logger._depth == 0:
                    X = args[0] if args else None
                    y = args[1] if len(args) > 1 else None
                    logger._log_plain(self_est, X, y, duration)
                return result

        patched_fit._visdom_patched = True
        cls.fit = patched_fit

    @staticmethod
    def _row(key, val):
        return "<tr><td {k}>{key}</td><td {v}>{val}</td></tr>".format(
            k=_TD_KEY,
            v=_TD_VAL,
            key=html.escape(str(key)),
            val=html.escape(str(val)),
        )

    def _log_cv(self, est, duration):
        refit = getattr(est, "refit", None)
        score_key = "mean_test_{}".format(refit) if isinstance(refit, str) else None
        if score_key not in est.cv_results_:
            score_key = next(
                (k for k in est.cv_results_ if k.startswith("mean_test_")),
                "mean_test_score",
            )
        scores = est.cv_results_[score_key]
        n = len(scores)
        self.viz.bar(
            X=scores,
            env=self.env,
            opts={
                "title": "{} CV scores".format(type(est).__name__),
                "xlabel": "param combo",
                "ylabel": score_key,
                "rownames": ["combo_{}".format(i) for i in range(n)],
            },
        )
        if hasattr(est, "best_score_"):
            summary_rows = "".join(
                [
                    self._row("best_score", "{:.4f}".format(est.best_score_)),
                    self._row("fit_time", "{:.2f}s".format(duration)),
                ]
            )
            param_rows = "".join(
                self._row(k, v) for k, v in sorted(est.best_params_.items())
            )
        else:
            summary_rows = "".join(
                [
                    self._row("fit_time", "{:.2f}s".format(duration)),
                    self._row(
                        "note",
                        "refit=False: best_score_/best_params_ " "unavailable",
                    ),
                ]
            )
            param_rows = ""
        body = (
            "<div {wrap}>"
            "<div {title}>{name}</div>"
            "<table>{summary}</table>"
            "<div {section}>Best Params</div>"
            "<table>{params}</table>"
            "</div>"
        ).format(
            wrap=_WRAP,
            title=_TITLE,
            name=html.escape(type(est).__name__),
            summary=summary_rows,
            section=_SECTION,
            params=param_rows,
        )
        self.viz.text(body, env=self.env)

    def _plot_history(self, est, curve, attr, xlabel, ylabel):
        self.viz.line(
            X=list(range(1, len(curve) + 1)),
            Y=curve,
            env=self.env,
            opts={
                "title": "{} {}".format(type(est).__name__, attr),
                "xlabel": xlabel,
                "ylabel": ylabel,
            },
        )

    def _log_history(self, est):
        loss_curve = getattr(est, "loss_curve_", None)
        if loss_curve is not None and len(loss_curve) > 0:
            self._plot_history(est, loss_curve, "loss_curve_", "epoch", "loss")
            val_scores = getattr(est, "validation_scores_", None)
            if val_scores is not None and len(val_scores) > 0:
                self._plot_history(
                    est, val_scores, "validation_scores_", "epoch", "val_score"
                )

        train_score = getattr(est, "train_score_", None)
        if train_score is not None and len(train_score) > 0:
            self._plot_history(
                est, train_score, "train_score_", "iteration", "train_score"
            )

    def _log_regression_diagnostics(self, est, X, y, summary_rows):
        from sklearn.base import is_regressor

        if not is_regressor(est) or y is None:
            return
        try:
            y_pred = est.predict(X)
        except Exception:
            return

        y_true = np.asarray(y, dtype=float)
        y_pred = np.asarray(y_pred, dtype=float)
        residuals = y_true - y_pred
        rmse = np.sqrt(np.mean(residuals**2))
        mae = np.mean(np.abs(residuals))
        summary_rows.append(self._row("rmse", "{:.4f}".format(rmse)))
        summary_rows.append(self._row("mae", "{:.4f}".format(mae)))

        self.viz.scatter(
            X=np.column_stack([y_pred, residuals]),
            env=self.env,
            opts={
                "title": "{} residuals".format(type(est).__name__),
                "xlabel": "predicted",
                "ylabel": "residual",
                "markersize": 5,
            },
        )

    def _log_plain(self, est, X, y, duration):
        summary_rows = [self._row("fit_time", "{:.2f}s".format(duration))]

        shape = getattr(X, "shape", None)
        if shape is not None:
            ncols = shape[1] if len(shape) > 1 else 1
            summary_rows.insert(
                0, self._row("dataset", "{} x {}".format(shape[0], ncols))
            )

        try:
            score = est.score(X, y) if y is not None else est.score(X)
            summary_rows.append(self._row("train_score", "{:.4f}".format(score)))
        except Exception:
            pass

        self._log_regression_diagnostics(est, X, y, summary_rows)

        param_rows = "".join(
            self._row(k, v) for k, v in sorted(est.get_params().items())
        )
        body = (
            "<div {wrap}>"
            "<div {title}>{name}</div>"
            "<table>{summary}</table>"
            "<div {section}>Params</div>"
            "<table>{params}</table>"
            "</div>"
        ).format(
            wrap=_WRAP,
            title=_TITLE,
            name=html.escape(type(est).__name__),
            summary="".join(summary_rows),
            section=_SECTION,
            params=param_rows,
        )
        self.viz.text(body, env=self.env)
        self._log_history(est)
