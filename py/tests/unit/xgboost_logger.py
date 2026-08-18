#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for VisdomXGBLogger.

``after_iteration``/``after_training`` are tested directly against a mocked
viz, since they only need the plain evals_log dict xgboost's callback
protocol documents. The patching helpers (``_patch_fit``, ``_patch_function``,
``_patch_depth``, ``_patch_depth_function``) are exercised against small
local classes/functions rather than real xgboost/sklearn entry points:
``autolog()`` monkeypatches every XGBModel subclass and, if sklearn is
installed, GridSearchCV/RandomizedSearchCV/cross_val_score/cross_validate,
globally for the life of the process, which would leak across the rest of
the suite.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from visdom.loggers.xgboost import VisdomXGBLogger


def _logger():
    viz = Mock()
    viz.line.side_effect = lambda *a, **kw: Mock()
    return VisdomXGBLogger(viz, env="test_env")


class TestAfterIteration(unittest.TestCase):
    def setUp(self):
        self.logger = _logger()

    def test_first_call_creates_window(self):
        """A brand-new metric opens a window with no win= kwarg."""
        self.logger.after_iteration(None, 0, {"train": {"logloss": [0.5]}})
        self.logger.viz.line.assert_called_once()
        self.assertNotIn("win", self.logger.viz.line.call_args.kwargs)
        self.assertIn("logloss", self.logger._wins)

    def test_second_call_appends(self):
        """A later round for the same metric appends to its window."""
        self.logger.after_iteration(None, 0, {"train": {"logloss": [0.5]}})
        win = self.logger._wins["logloss"]
        self.logger.after_iteration(None, 1, {"train": {"logloss": [0.4]}})
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["win"], win)
        self.assertEqual(kwargs["update"], "append")

    def test_epoch_zero_on_existing_window_replaces(self):
        """A second run reusing the same window (nested fit) replaces
        rather than appends when it starts back at epoch 0."""
        self.logger.after_iteration(None, 0, {"train": {"logloss": [0.5]}})
        win = self.logger._wins["logloss"]
        self.logger.after_iteration(None, 0, {"train": {"logloss": [0.5]}})
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["win"], win)
        self.assertEqual(kwargs["update"], "replace")

    def test_tuple_metric_value_uses_first_element(self):
        """xgb.cv's evals_log carries (mean, std) tuples per round."""
        self.logger.after_iteration(None, 0, {"train": {"logloss": [(0.5, 0.1)]}})
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["Y"], [0.5])

    def test_multiple_metrics_get_separate_windows(self):
        self.logger.after_iteration(
            None,
            0,
            {"train": {"logloss": [0.5], "auc": [0.9]}},
        )
        self.assertEqual(set(self.logger._wins), {"logloss", "auc"})
        self.assertEqual(self.logger.viz.line.call_count, 2)

    def test_multiple_eval_sets_share_one_window_by_metric(self):
        """train/eval curves for the same metric land in one window,
        distinguished by trace name, not one window per eval set."""
        self.logger.after_iteration(
            None,
            0,
            {"train": {"logloss": [0.5]}, "eval": {"logloss": [0.6]}},
        )
        self.assertEqual(list(self.logger._wins), ["logloss"])
        names = [c.kwargs["name"] for c in self.logger.viz.line.call_args_list]
        self.assertEqual(names, ["train", "eval"])

    def test_always_returns_false(self):
        """The callback never triggers xgboost's early stopping."""
        result = self.logger.after_iteration(None, 0, {"train": {"logloss": [0.5]}})
        self.assertFalse(result)

    def test_logging_exception_is_swallowed_and_warned(self):
        self.logger.viz.line.side_effect = RuntimeError("boom")
        with self.assertWarns(UserWarning):
            result = self.logger.after_iteration(None, 0, {"train": {"logloss": [0.5]}})
        self.assertFalse(result)


class TestAfterTraining(unittest.TestCase):
    def setUp(self):
        self.logger = _logger()

    def _model(self, best_iteration=5, best_score=0.1):
        return SimpleNamespace(best_iteration=best_iteration, best_score=best_score)

    def test_creates_summary_pane_on_first_call(self):
        self.logger.after_training(self._model())
        self.logger.viz.text.assert_called_once()
        self.assertNotIn("win", self.logger.viz.text.call_args.kwargs)
        self.assertIn("__summary__", self.logger._wins)

    def test_reuses_summary_window_on_second_call(self):
        self.logger.after_training(self._model())
        win = self.logger._wins["__summary__"]
        self.logger.after_training(self._model(best_iteration=6, best_score=0.05))
        kwargs = self.logger.viz.text.call_args.kwargs
        self.assertEqual(kwargs["win"], win)
        self.assertEqual(self.logger.viz.text.call_count, 2)

    def test_missing_best_iteration_skips_text(self):
        """A model without best_iteration/best_score (no early stopping
        configured) is a normal case, not an error, and logs nothing."""
        self.logger.after_training(SimpleNamespace())
        self.logger.viz.text.assert_not_called()

    def test_exception_is_swallowed_and_warned(self):
        self.logger.viz.text.side_effect = RuntimeError("boom")
        with self.assertWarns(UserWarning):
            self.logger.after_training(self._model())

    def test_returns_model_unchanged(self):
        model = self._model()
        self.assertIs(self.logger.after_training(model), model)


class TestPatchMechanics(unittest.TestCase):
    """Covers the callback-injection and depth/window-reset bookkeeping
    autolog() relies on, without patching real xgboost/sklearn classes."""

    def setUp(self):
        self.logger = _logger()
        VisdomXGBLogger.active = self.logger

    def tearDown(self):
        VisdomXGBLogger.active = None

    def test_patch_fit_injects_and_restores_callbacks(self):
        class Est:
            def __init__(self):
                self.callbacks = None
                self.seen_callbacks = None

            def fit(self, X, y=None):
                self.seen_callbacks = list(self.callbacks or [])
                return self

        self.logger._patch_fit(Est)
        est = Est()
        est.fit(None)
        self.assertIn(self.logger, est.seen_callbacks)
        self.assertIsNone(est.callbacks)

    def test_double_patch_fit_is_noop(self):
        class Est:
            def fit(self, X, y=None):
                return self

        self.logger._patch_fit(Est)
        patched_once = Est.fit
        self.logger._patch_fit(Est)
        self.assertIs(Est.fit, patched_once)

    def test_active_none_falls_through_without_touching_callbacks(self):
        class Est:
            def __init__(self):
                self.callbacks = None

            def fit(self, X, y=None):
                return self

        self.logger._patch_fit(Est)
        VisdomXGBLogger.active = None
        est = Est()
        result = est.fit(None)
        self.assertIsInstance(result, Est)
        self.assertIsNone(est.callbacks)

    def test_wins_reset_only_at_true_top_level_boundary(self):
        """A standalone run followed by a nested (CV-style) run must not
        have its first inner fold silently overwrite the standalone run's
        window -- the reset has to key off the true depth-0 boundary."""

        class Est:
            def __init__(self):
                self.callbacks = None

            def fit(self, X, y=None):
                for cb in self.callbacks or []:
                    cb.after_iteration(None, 0, {"train": {"logloss": [0.5]}})
                return self

        class Outer:
            def __init__(self, inner):
                self.inner = inner

            def fit(self, X, y=None):
                self.inner.fit(X, y)
                return self

        self.logger._patch_fit(Est)
        self.logger._patch_depth(Outer)

        Est().fit(None)
        standalone_win = self.logger._wins["logloss"]

        Outer(Est()).fit(None)
        nested_win = self.logger._wins["logloss"]

        self.assertNotEqual(standalone_win, nested_win)

    def test_nested_fit_shares_one_window_across_folds(self):
        """A CV-style outer fit driving several inner fits (folds) must
        reuse one window per metric, not open one per fold."""

        class Est:
            def __init__(self):
                self.callbacks = None

            def fit(self, X, y=None):
                for cb in self.callbacks or []:
                    cb.after_iteration(None, 0, {"train": {"logloss": [0.5]}})
                return self

        class Outer:
            def fit(self, X, y=None):
                for _ in range(3):
                    Est().fit(X, y)
                return self

        self.logger._patch_fit(Est)
        self.logger._patch_depth(Outer)

        Outer().fit(None)
        new_window_calls = [
            c for c in self.logger.viz.line.call_args_list if "win" not in c.kwargs
        ]
        self.assertEqual(len(new_window_calls), 1)

    def test_patch_function_injects_callback_into_kwargs(self):
        calls = []

        def fake_train(*, callbacks=None, **kwargs):
            calls.append(list(callbacks or []))
            return "trained"

        mod = SimpleNamespace(train=fake_train)
        self.logger._patch_function(mod, "train")
        result = mod.train()
        self.assertEqual(result, "trained")
        self.assertIn(self.logger, calls[0])

    def test_patch_function_active_none_passthrough(self):
        def fake_train(*, callbacks=None, **kwargs):
            return callbacks

        mod = SimpleNamespace(train=fake_train)
        self.logger._patch_function(mod, "train")
        VisdomXGBLogger.active = None
        self.assertIsNone(mod.train(callbacks=None))

    def test_patch_depth_function_does_not_inject_callbacks(self):
        """cross_val_score-style functions have no callbacks= of their
        own; depth tracking must not invent one."""
        calls = []

        def fake_cross_val_score(*args, **kwargs):
            calls.append(kwargs)
            return "scores"

        mod = SimpleNamespace(cross_val_score=fake_cross_val_score)
        self.logger._patch_depth_function(mod, "cross_val_score")
        result = mod.cross_val_score()
        self.assertEqual(result, "scores")
        self.assertNotIn("callbacks", calls[0])


if __name__ == "__main__":
    unittest.main()
