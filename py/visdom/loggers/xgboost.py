#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import functools

try:
    from xgboost.callback import TrainingCallback
except ImportError:
    raise ImportError(
        "xgboost is required for VisdomXGBLogger. Install with: pip install xgboost"
    )


class VisdomXGBLogger(TrainingCallback):
    """Plots XGBoost train/eval metrics to Visdom as boosting progresses.

    Implements xgboost's TrainingCallback protocol. after_iteration()
    receives evals_log directly from xgboost after every boosting round,
    so there is no separate evals_result dict to pass or read.

    Call autolog() once at the start of your script to patch xgb.train
    and every XGBModel subclass's fit() to log automatically. Or pass an
    instance directly via callbacks= for manual control.

    Usage::

        from visdom.loggers import VisdomXGBLogger

        VisdomXGBLogger.autolog()

        booster = xgb.train(params, dtrain, evals=[...])   # logged automatically
        clf.fit(X_train, y_train)                          # logged automatically

    Or manually::

        callback = VisdomXGBLogger(viz)
        booster = xgb.train(
            params, dtrain,
            evals=[(dtrain, "train"), (dval, "eval")],
            callbacks=[callback],
        )
    """

    active = None

    def __init__(self, viz, env=None):
        super().__init__()
        self.viz = viz
        self.env = env or "xgboost_{}".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        self._wins = {}
        self._depth = 0

    @classmethod
    def autolog(cls, viz=None, env=None):
        """Patch xgb.train and every XGBModel subclass's fit() to log
        boosting rounds to Visdom."""
        if viz is None:
            import visdom as _visdom

            viz = _visdom.Visdom()
        try:
            import xgboost as xgb
        except ImportError:
            raise ImportError(
                "xgboost is required for VisdomXGBLogger. "
                "Install with: pip install xgboost"
            )

        _viz_env = getattr(viz, "env", None)
        env = (
            env
            or (_viz_env if _viz_env and _viz_env != "main" else None)
            or "xgboost_{}".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        )
        instance = cls(viz, env)
        cls.active = instance
        instance._patch_train(xgb)
        for est_cls in cls._all_estimators(xgb.XGBModel):
            instance._patch_fit(est_cls)

    @staticmethod
    def _all_estimators(base_cls):
        """Recursively collect base_cls and every (sub)subclass of it, so
        third-party or future XGBModel subclasses are covered too."""
        estimators = {base_cls}
        frontier = [base_cls]
        while frontier:
            cls = frontier.pop()
            for sub in cls.__subclasses__():
                if sub not in estimators:
                    estimators.add(sub)
                    frontier.append(sub)
        return estimators

    def _patch_train(self, xgb):
        if getattr(xgb.train, "_visdom_patched", False):
            return

        original = xgb.train
        visdom_cls = self.__class__

        @functools.wraps(original)
        def patched_train(*args, **kwargs):
            logger = visdom_cls.active
            if logger is None:
                return original(*args, **kwargs)
            callbacks = list(kwargs.get("callbacks") or [])
            if logger not in callbacks:
                callbacks.append(logger)
            kwargs["callbacks"] = callbacks
            logger._depth += 1
            try:
                return original(*args, **kwargs)
            finally:
                logger._depth -= 1

        patched_train._visdom_patched = True
        xgb.train = patched_train

    def _patch_fit(self, cls):
        if not hasattr(cls, "fit"):
            return
        if getattr(cls.fit, "_visdom_patched", False):
            return

        original = cls.fit
        visdom_cls = self.__class__

        @functools.wraps(original)
        def patched_fit(self_est, *args, **kwargs):
            logger = visdom_cls.active
            if logger is None:
                return original(self_est, *args, **kwargs)
            original_callbacks = self_est.callbacks
            callbacks = list(original_callbacks or [])
            if logger not in callbacks:
                callbacks.append(logger)
            self_est.callbacks = callbacks
            logger._depth += 1
            try:
                return original(self_est, *args, **kwargs)
            finally:
                logger._depth -= 1
                self_est.callbacks = original_callbacks

        patched_fit._visdom_patched = True
        cls.fit = patched_fit

    def before_training(self, model):
        self._wins = {}
        return model

    def after_iteration(self, model, epoch, evals_log):
        for data_name, metrics in evals_log.items():
            for metric_name, log in metrics.items():
                value = log[-1]
                if isinstance(value, tuple):
                    value = value[0]
                win_name = metric_name
                trace_name = data_name
                if win_name not in self._wins:
                    self._wins[win_name] = self.viz.line(
                        X=[epoch],
                        Y=[value],
                        env=self.env,
                        name=trace_name,
                        opts={
                            "title": win_name,
                            "xlabel": "round",
                            "ylabel": win_name,
                            "showlegend": True,
                        },
                    )
                else:
                    self.viz.line(
                        X=[epoch],
                        Y=[value],
                        win=self._wins[win_name],
                        env=self.env,
                        name=trace_name,
                        update="append",
                    )
        return False

    def after_training(self, model):
        try:
            best_iteration = model.best_iteration
            best_score = model.best_score
        except (AttributeError, TypeError):
            best_iteration = None
            best_score = None
        if best_iteration is not None and best_score is not None:
            self.viz.text(
                "best_iteration: {}<br>best_score: {}".format(
                    best_iteration, best_score
                ),
                env=self.env,
            )
        return model
