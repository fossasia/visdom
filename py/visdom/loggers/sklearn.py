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
    """Patches sklearn estimator fit() calls to log results to Visdom.

    GridSearchCV and RandomizedSearchCV produce a bar chart of
    mean_test_score per parameter combination and a text pane with
    best_params_ and best_score_. All other estimators produce a text
    pane with the estimator name, parameter count, and fit duration.

    Usage::

        from visdom.logger import VisdomSklearnLogger

        logger = VisdomSklearnLogger(viz, env="sklearn_run")
        logger.enable()

        clf.fit(X_train, y_train)
        gs.fit(X_train, y_train)

        logger.disable()

        # or as a context manager:
        with VisdomSklearnLogger(viz, env="sklearn_run"):
            clf.fit(X_train, y_train)
    """

    def __init__(self, viz, env=None):
        self.viz = viz
        self.env = env or "sklearn_{}".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        self._patches = {}
        self._cv_depth = 0

    def __enter__(self):
        self.enable()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disable()
        return False

    def enable(self):
        """Patch sklearn estimator fit() methods to log to Visdom."""
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

        for cls in (GridSearchCV, RandomizedSearchCV):
            self._patch(cls, is_cv=True)

        for _name, cls in all_estimators():
            self._patch(cls, is_cv=False)

    def disable(self):
        """Restore all patched fit() methods to their originals."""
        for cls, (original, had_own_fit) in self._patches.items():
            if had_own_fit:
                cls.fit = original
            else:
                try:
                    delattr(cls, "fit")
                except AttributeError:
                    pass
        self._patches.clear()

    def _patch(self, cls, is_cv):
        if cls in self._patches or not hasattr(cls, "fit"):
            return

        had_own_fit = "fit" in cls.__dict__
        original = cls.fit
        self._patches[cls] = (original, had_own_fit)
        visdom_logger = self

        if is_cv:

            @functools.wraps(original)
            def patched_fit(self_est, *args, **kwargs):
                visdom_logger._cv_depth += 1
                t0 = time.time()
                try:
                    result = original(self_est, *args, **kwargs)
                finally:
                    visdom_logger._cv_depth -= 1
                duration = time.time() - t0
                visdom_logger._log_cv(self_est, duration)
                return result

        else:

            @functools.wraps(original)
            def patched_fit(self_est, *args, **kwargs):
                t0 = time.time()
                result = original(self_est, *args, **kwargs)
                duration = time.time() - t0
                if visdom_logger._cv_depth == 0:
                    X = args[0] if args else None
                    y = args[1] if len(args) > 1 else None
                    visdom_logger._log_plain(self_est, X, y, duration)
                return result

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
