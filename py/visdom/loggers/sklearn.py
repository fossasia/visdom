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
import warnings
import weakref

import numpy as np

from visdom.tracking.core import RunAlreadyFinishedError

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
    Regressors additionally get train_rmse/train_mae rows in the text
    pane (R2 alone can be misleading) and a predicted-vs-residual
    scatter plot. Like train_score, these are computed on the data
    passed to fit(), so they are in-sample and not held-out estimates.
    A multioutput fit pools its targets into one residual plot.

    Every pane is keyed on the estimator instance, so refitting the same
    estimator replaces its panes instead of opening new ones. Distinct
    estimator objects always get their own panes.

    Pass a :class:`visdom.tracking.RunTracker` via ``run=`` to additionally
    record each fit's outcome to that run's local reproducibility record:
    one structured event with the estimator class, hyperparameters, score,
    and fit time as real typed values (not the HTML-escaped strings the
    Visdom text pane uses), plus a plot_update entry for every chart drawn
    (CV-scores bar, loss/score history line, residual scatter). As with
    :class:`visdom.tracking.graphs.TrackedVisdom`, a failure while
    recording to ``run`` never affects the Visdom panes themselves — those
    have already been drawn by the time recording is attempted.

    Usage::

        from visdom.loggers import VisdomSklearnLogger

        VisdomSklearnLogger.autolog()

        clf.fit(X_train, y_train)   # logged automatically
        gs.fit(X_train, y_train)    # logged automatically

    Or with reproducibility tracking::

        from visdom.tracking import RunTracker
        from visdom.loggers import VisdomSklearnLogger

        with RunTracker("exp1", params={"C": 1.0}) as run:
            VisdomSklearnLogger.autolog(run=run)
            clf.fit(X_train, y_train)   # plotted AND tracked
    """

    active = None

    def __init__(self, viz=None, env=None, run=None):
        if viz is None:
            import visdom as _visdom

            viz = _visdom.Visdom()
        self.viz = viz
        self.env = env
        self.run = run
        self._local = threading.local()
        self._wins = weakref.WeakKeyDictionary()
        self._seq = 0

    @property
    def _depth(self):
        return getattr(self._local, "depth", 0)

    @_depth.setter
    def _depth(self, value):
        self._local.depth = value

    @classmethod
    def autolog(cls, viz=None, env=None, run=None):
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
        instance = cls(viz, env, run=run)
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
                    try:
                        logger._log_cv(self_est, duration)
                    except Exception as e:
                        warnings.warn(
                            "VisdomSklearnLogger failed to log {}: {}".format(
                                type(self_est).__name__, e
                            )
                        )
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
                    try:
                        logger._log_plain(self_est, X, y, duration)
                    except Exception as e:
                        warnings.warn(
                            "VisdomSklearnLogger failed to log {}: {}".format(
                                type(self_est).__name__, e
                            )
                        )
                return result

        patched_fit._visdom_patched = True
        cls.fit = patched_fit

    def _win(self, est, name):
        """Window id for one of est's panes, stable across refits.

        Keyed on the estimator instance so refitting replaces the panes
        that estimator already owns, while a different estimator object
        of the same class still gets its own. The mapping holds weak
        references, so it never keeps a fitted model alive.
        """
        tag = self._wins.get(est)
        if tag is None:
            self._seq += 1
            tag = "{}_{}".format(type(est).__name__, self._seq)
            self._wins[est] = tag
        return "{}_{}".format(tag, name)

    def _log_plot_to_run(self, method, win, **extra):
        """Best-effort record an already-drawn chart update on self.run.

        Same shape as visdom.tracking.graphs.TrackedVisdom._log_best_effort
        and visdom.pytorch.VisdomLogger._log_to_run: a tracking failure
        here must never affect a pane that's already been drawn.

        Deliberately uses only stacklevel=2 (points at the immediate
        caller -- _log_cv/_log_plain/_plot_history/_plot_residuals --
        not further). Unlike visdom.pytorch.VisdomLogger, where a fixed
        call depth back to the user's log() call made a precise
        stacklevel meaningful, this method is reached from several
        different depths depending on which chart triggered it (_log_cv
        calls it directly; _log_plain reaches it by way of
        _log_history/_plot_history for the history charts, one frame
        deeper than for the CV bar chart) -- there is no single correct
        "user's call site" stacklevel across all of them, and the
        estimator class name already included in the warning message is
        more useful here than an approximately-right line number would
        be.
        """
        if self.run is None:
            return
        try:
            self.run.log_plot_update(method, win, **extra)
        except RunAlreadyFinishedError:
            pass
        except Exception as e:
            warnings.warn(
                "VisdomSklearnLogger: failed to record a {0!r} update "
                "for {1!r} on run {2!r} ({3}: {4}) -- the plot itself "
                "still succeeded normally, only the tracking record is "
                "affected.".format(
                    method,
                    win,
                    self.run.run_id,
                    type(e).__name__,
                    e,
                ),
                RuntimeWarning,
                stacklevel=2,
            )

    def _log_event_to_run(self, event_type, **data):
        """Best-effort record a structured fit-outcome event on self.run:
        params/score/timing as real typed values (ints/floats/dicts),
        not the HTML-escaped display strings the Visdom text pane uses.
        This is the actual reproducibility record, not just a mirror of
        what got plotted -- see _log_plot_to_run for that half.
        """
        if self.run is None:
            return
        try:
            self.run.log_event(event_type, **data)
        except RunAlreadyFinishedError:
            pass
        except Exception as e:
            warnings.warn(
                "VisdomSklearnLogger: failed to record a {0!r} event on "
                "run {1!r} ({2}: {3}) -- the plot itself still "
                "succeeded normally, only the tracking record is "
                "affected.".format(event_type, self.run.run_id, type(e).__name__, e),
                RuntimeWarning,
                stacklevel=2,
            )

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
        bar_win = self._win(est, "cv_scores")
        self.viz.bar(
            X=scores,
            win=bar_win,
            env=self.env,
            opts={
                "title": "{} CV scores".format(type(est).__name__),
                "xlabel": "param combo",
                "ylabel": score_key,
                "rownames": ["combo_{}".format(i) for i in range(n)],
            },
        )
        self._log_plot_to_run("bar", bar_win, score_key=score_key, n_candidates=n)

        has_best = hasattr(est, "best_score_")
        if has_best:
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
        text_win = self._win(est, "summary")
        self.viz.text(body, win=text_win, env=self.env)
        self._log_plot_to_run("text", text_win)
        self._log_event_to_run(
            "cv_fit",
            estimator=type(est).__name__,
            fit_time=duration,
            n_candidates=n,
            score_key=score_key,
            best_score=est.best_score_ if has_best else None,
            best_params=est.best_params_ if has_best else None,
            refit=refit,
        )

    def _plot_history(self, est, curve, attr, xlabel, ylabel):
        win = self._win(est, attr)
        self.viz.line(
            X=list(range(1, len(curve) + 1)),
            Y=curve,
            win=win,
            env=self.env,
            opts={
                "title": "{} {}".format(type(est).__name__, attr),
                "xlabel": xlabel,
                "ylabel": ylabel,
            },
        )
        self._log_plot_to_run(
            "line", win, attr=attr, n_points=len(curve), final_value=curve[-1]
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
        """Add train_rmse/train_mae rows for est, return residual points.

        X and y are the arrays fit() was called with, so every value here
        is in-sample and optimistically biased; the train_ prefix and the
        plot title say so rather than implying a held-out estimate.

        Both arrays are flattened first. sklearn ravels a single-column
        target, so an (n, 1) y would otherwise broadcast against an (n,)
        prediction into an n x n matrix, and a multioutput y would widen
        the points past the two columns scatter() accepts.
        """
        from sklearn.base import is_regressor

        if not is_regressor(est) or y is None:
            return None
        try:
            y_pred = est.predict(X)
        except Exception:
            return None

        y_true = np.asarray(y, dtype=float).ravel()
        y_pred = np.asarray(y_pred, dtype=float).ravel()
        if y_true.shape != y_pred.shape:
            return None
        residuals = y_true - y_pred
        rmse = np.sqrt(np.mean(residuals**2))
        mae = np.mean(np.abs(residuals))
        summary_rows.append(self._row("train_rmse", "{:.4f}".format(rmse)))
        summary_rows.append(self._row("train_mae", "{:.4f}".format(mae)))
        return np.column_stack([y_pred, residuals])

    def _plot_residuals(self, est, points):
        win = self._win(est, "residuals")
        self.viz.scatter(
            X=points,
            win=win,
            env=self.env,
            opts={
                "title": "{} training residuals".format(type(est).__name__),
                "xlabel": "predicted",
                "ylabel": "residual",
                "markersize": 5,
            },
        )
        self._log_plot_to_run("scatter", win, n_points=len(points))

    def _log_plain(self, est, X, y, duration):
        summary_rows = [self._row("fit_time", "{:.2f}s".format(duration))]

        shape = getattr(X, "shape", None)
        dataset_shape = None
        if shape is not None:
            ncols = shape[1] if len(shape) > 1 else 1
            dataset_shape = [shape[0], ncols]
            summary_rows.insert(
                0, self._row("dataset", "{} x {}".format(shape[0], ncols))
            )

        score = None
        try:
            score = est.score(X, y) if y is not None else est.score(X)
            summary_rows.append(self._row("train_score", "{:.4f}".format(score)))
        except Exception:
            pass

        residuals = self._log_regression_diagnostics(est, X, y, summary_rows)

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
        text_win = self._win(est, "summary")
        self.viz.text(body, win=text_win, env=self.env)
        self._log_plot_to_run("text", text_win)
        # Params come from get_params(), which for a Pipeline/meta-
        # estimator can include nested estimator objects, not just
        # plain scalars -- safe to pass straight through here, since
        # RunTracker.log_event already runs everything through
        # _json_safe (falls back to a str() representation for
        # anything that isn't JSON-native, never raises).
        self._log_event_to_run(
            "fit",
            estimator=type(est).__name__,
            fit_time=duration,
            dataset_shape=dataset_shape,
            train_score=score,
            params=est.get_params(),
        )
        if residuals is not None:
            self._plot_residuals(est, residuals)
        self._log_history(est)