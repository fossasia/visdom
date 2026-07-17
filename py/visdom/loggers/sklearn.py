#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import functools
import html
import time

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

    Usage::

        from visdom.loggers import VisdomSklearnLogger

        VisdomSklearnLogger.autolog()

        clf.fit(X_train, y_train)   # logged automatically
        gs.fit(X_train, y_train)    # logged automatically
    """

    _active = None

    def __init__(self, viz, env):
        self.viz = viz
        self.env = env
        self._cv_depth = 0

    @classmethod
    def autolog(cls, viz=None, env=None):
        """Patch all sklearn estimators to log fit() calls to Visdom."""
        if viz is None:
            import visdom as _visdom

            viz = _visdom.Visdom()
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
        _viz_env = getattr(viz, "env", None)
        env = (
            env
            or (_viz_env if _viz_env and _viz_env != "main" else None)
            or "sklearn_{}".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        )
        instance = cls(viz, env)
        cls._active = instance
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
                logger = visdom_cls._active
                logger._cv_depth += 1
                t0 = time.time()
                try:
                    result = original(self_est, *args, **kwargs)
                finally:
                    logger._cv_depth -= 1
                duration = time.time() - t0
                logger._log_cv(self_est, duration)
                return result

        else:

            @functools.wraps(original)
            def patched_fit(self_est, *args, **kwargs):
                t0 = time.time()
                result = original(self_est, *args, **kwargs)
                duration = time.time() - t0
                logger = visdom_cls._active
                if logger._cv_depth == 0:
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
        scores = est.cv_results_["mean_test_score"]
        n = len(scores)
        self.viz.bar(
            X=scores,
            env=self.env,
            opts={
                "title": "{} CV scores".format(type(est).__name__),
                "xlabel": "param combo",
                "ylabel": "mean_test_score",
                "rownames": ["combo_{}".format(i) for i in range(n)],
            },
        )
        summary_rows = "".join(
            [
                self._row("best_score", "{:.4f}".format(est.best_score_)),
                self._row("fit_time", "{:.2f}s".format(duration)),
            ]
        )
        param_rows = "".join(
            self._row(k, v) for k, v in sorted(est.best_params_.items())
        )
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
