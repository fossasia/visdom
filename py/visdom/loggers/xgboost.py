#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import functools
import warnings

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

    Call autolog() once at the start of your script to patch xgb.train,
    xgb.cv, every XGBModel subclass's fit(), and (if scikit-learn is
    installed) GridSearchCV/RandomizedSearchCV.fit() and
    cross_val_score/cross_validate, to log automatically. When an
    XGBModel is fit inside one of these, the per-fold and refit calls
    share a single window per metric instead of each opening its own —
    only the most recent run's curve is shown, rather than one window
    per inner fit. Or pass an instance directly via callbacks= for
    manual control.

    cross_validate is patched both on sklearn.model_selection and on the
    module that defines it, so cross_val_score is depth-tracked no matter
    when it was imported. Importing cross_validate itself before autolog()
    runs still binds the original, unpatched function.

    One logger is active at a time. Calling autolog() again replaces it, and
    every patched entry point then targets the new env; the previous env
    keeps the windows it already has but receives nothing further. Switching
    env this way is supported and warns, so the change is not silent.
    autolog() returns the active logger.

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

    Not thread-safe: active/_depth/_wins have no locking, so concurrent
    fits in the same process can race.
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
        """Patch xgb.train, xgb.cv, every XGBModel subclass's fit(), and
        (if scikit-learn is installed) GridSearchCV/RandomizedSearchCV.fit()
        and cross_val_score/cross_validate to log boosting rounds to
        Visdom. Replaces any previously active logger and returns the new
        one."""
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
        previous = cls.active
        if previous is not None and previous.env != env:
            warnings.warn(
                "VisdomXGBLogger.autolog() was already active for env "
                "'{}'; logging moves to '{}' and '{}' receives nothing "
                "further.".format(previous.env, env, previous.env)
            )
        instance = cls(viz, env)
        cls.active = instance
        instance._patch_function(xgb, "train")
        instance._patch_function(xgb, "cv")
        for est_cls in cls._all_estimators(xgb.XGBModel):
            instance._patch_fit(est_cls)
        try:
            import sklearn.model_selection as sklearn_ms
        except ImportError:
            pass
        else:
            for cv_cls in (sklearn_ms.GridSearchCV, sklearn_ms.RandomizedSearchCV):
                instance._patch_depth(cv_cls)
            for fn_name in ("cross_val_score", "cross_validate"):
                instance._patch_depth_function(sklearn_ms, fn_name)
            # cross_val_score() calls cross_validate() as a global of
            # _validation, so patching it here also covers callers that
            # imported cross_val_score before autolog() ran.
            try:
                from sklearn.model_selection import _validation
            except ImportError:
                pass
            else:
                if hasattr(_validation, "cross_validate"):
                    instance._patch_depth_function(_validation, "cross_validate")
        return instance

    @staticmethod
    def _all_estimators(base_cls):
        """Recursively collect base_cls and every (sub)subclass of it.
        __subclasses__() is a call-time snapshot, so subclasses imported
        later (e.g. xgboost.dask) are missed."""
        estimators = {base_cls}
        frontier = [base_cls]
        while frontier:
            cls = frontier.pop()
            for sub in cls.__subclasses__():
                if sub not in estimators:
                    estimators.add(sub)
                    frontier.append(sub)
        return estimators

    def _patch_function(self, xgb, name):
        """Patch a top-level xgboost function (train or cv) that accepts
        a keyword-only callbacks= argument."""
        original = getattr(xgb, name)
        if getattr(original, "_visdom_patched", False):
            return

        visdom_cls = self.__class__

        @functools.wraps(original)
        def patched(*args, **kwargs):
            logger = visdom_cls.active
            if logger is None:
                return original(*args, **kwargs)
            if logger._depth == 0:
                logger._wins = {}
            callbacks = list(kwargs.get("callbacks") or [])
            if logger not in callbacks:
                callbacks.append(logger)
            kwargs["callbacks"] = callbacks
            logger._depth += 1
            try:
                return original(*args, **kwargs)
            finally:
                logger._depth -= 1

        patched._visdom_patched = True
        setattr(xgb, name, patched)

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
            if logger._depth == 0:
                logger._wins = {}
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

    def _patch_depth(self, cls):
        """Track depth around a meta-estimator's fit() (e.g. GridSearchCV)
        that has no callbacks= of its own but calls into a patched
        XGBModel.fit() internally."""
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
            if logger._depth == 0:
                logger._wins = {}
            logger._depth += 1
            try:
                return original(self_est, *args, **kwargs)
            finally:
                logger._depth -= 1

        patched_fit._visdom_patched = True
        cls.fit = patched_fit

    def _patch_depth_function(self, module, name):
        """Track depth around a plain function (e.g. cross_val_score)
        that has no callbacks= of its own but calls into a patched
        estimator's fit() internally."""
        original = getattr(module, name)
        if getattr(original, "_visdom_patched", False):
            return

        visdom_cls = self.__class__

        @functools.wraps(original)
        def patched(*args, **kwargs):
            logger = visdom_cls.active
            if logger is None:
                return original(*args, **kwargs)
            if logger._depth == 0:
                logger._wins = {}
            logger._depth += 1
            try:
                return original(*args, **kwargs)
            finally:
                logger._depth -= 1

        patched._visdom_patched = True
        setattr(module, name, patched)

    def after_iteration(self, model, epoch, evals_log):
        try:
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
                    elif epoch == 0:
                        # New run reusing an old window (nested fit, or a
                        # manually reused callback) — replace, don't append.
                        self.viz.line(
                            X=[epoch],
                            Y=[value],
                            win=self._wins[win_name],
                            env=self.env,
                            name=trace_name,
                            update="replace",
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
        except Exception as e:
            warnings.warn("VisdomXGBLogger failed to log round {}: {}".format(epoch, e))
        return False

    def after_training(self, model):
        try:
            best_iteration = model.best_iteration
            best_score = model.best_score
        except (AttributeError, TypeError):
            best_iteration = None
            best_score = None
        if best_iteration is not None and best_score is not None:
            text = "best_iteration: {}<br>best_score: {}".format(
                best_iteration, best_score
            )
            try:
                summary_win = self._wins.get("__summary__")
                if summary_win is None:
                    self._wins["__summary__"] = self.viz.text(text, env=self.env)
                else:
                    self.viz.text(text, win=summary_win, env=self.env)
            except Exception as e:
                warnings.warn(
                    "VisdomXGBLogger failed to log training summary: {}".format(e)
                )
        return model
