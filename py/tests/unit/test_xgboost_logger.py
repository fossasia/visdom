#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import unittest
from unittest.mock import Mock, patch

import numpy as np
import pytest
import visdom

xgb = pytest.importorskip("xgboost")

from visdom.loggers.xgboost import VisdomXGBLogger

pytestmark = pytest.mark.unit


def _unconnected_visdom():
    with (
        patch.object(visdom.Visdom, "_handle_post", return_value=True),
        patch.object(visdom.Visdom, "_start_session_reaper"),
        patch.object(visdom.logger, "warning"),
    ):
        client = visdom.Visdom(use_incoming_socket=False)
    client._handle_post = Mock(
        side_effect=AssertionError("unexpected transport call in unit test")
    )
    return client


def _capture(viz, call, win_exists=True):
    """Run call() against viz with _send captured instead of transmitted.

    win_exists is patched too: line(update="append") checks it when the
    client isn't in offline mode, and would otherwise reach for a real
    connection.
    """
    sent = {}

    def capture(msg, endpoint="events", **_):
        sent["payload"] = msg
        sent["endpoint"] = endpoint
        return "win1"

    with (
        patch.object(viz, "_send", side_effect=capture),
        patch.object(viz, "win_exists", return_value=win_exists),
    ):
        call()
    return sent


class TestAfterIteration(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()
        self.logger = VisdomXGBLogger(self.viz, env="xgb_test")

    def test_first_round_opens_a_window(self):
        sent = _capture(
            self.viz,
            lambda: self.logger.after_iteration(None, 0, {"train": {"rmse": [0.5]}}),
        )
        self.assertEqual(sent["endpoint"], "events")
        self.assertEqual(sent["payload"]["eid"], "xgb_test")
        self.assertEqual(sent["payload"]["data"][0]["name"], "train")
        self.assertEqual(self.logger._wins["rmse"], "win1")

    def test_later_round_appends_to_the_existing_window(self):
        self.logger._wins["rmse"] = "existing_win"
        sent = _capture(
            self.viz,
            lambda: self.logger.after_iteration(None, 1, {"train": {"rmse": [0.4]}}),
        )
        self.assertEqual(sent["endpoint"], "update")
        self.assertTrue(sent["payload"]["append"])
        self.assertEqual(sent["payload"]["win"], "existing_win")

    def test_epoch_zero_reusing_a_window_replaces_instead_of_appending(self):
        # A nested fit (or a manually reused callback) starts a new run at
        # epoch 0 while the previous run's window is still tracked.
        self.logger._wins["rmse"] = "existing_win"
        sent = _capture(
            self.viz,
            lambda: self.logger.after_iteration(None, 0, {"train": {"rmse": [0.5]}}),
        )
        self.assertEqual(sent["endpoint"], "update")
        self.assertFalse(sent["payload"]["append"])

    def test_tuple_valued_metric_unwraps_to_its_first_element(self):
        sent = _capture(
            self.viz,
            lambda: self.logger.after_iteration(
                None, 0, {"train": {"rmse": [(0.5, 0.01)]}}
            ),
        )
        self.assertEqual(sent["payload"]["data"][0]["y"], [0.5])

    def test_different_eval_sets_share_one_window_per_metric(self):
        self.logger._wins["rmse"] = "shared_win"
        sent = _capture(
            self.viz,
            lambda: self.logger.after_iteration(None, 1, {"eval": {"rmse": [0.6]}}),
        )
        self.assertEqual(sent["payload"]["data"][0]["name"], "eval")
        self.assertEqual(sent["payload"]["win"], "shared_win")

    def test_logging_failure_warns_instead_of_raising(self):
        with patch.object(self.viz, "line", side_effect=RuntimeError("boom")):
            with self.assertWarns(UserWarning):
                self.logger.after_iteration(None, 0, {"train": {"rmse": [0.5]}})


class TestAfterTraining(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()
        self.logger = VisdomXGBLogger(self.viz, env="xgb_test")

    def test_logs_best_iteration_and_score_as_text(self):
        model = Mock(best_iteration=7, best_score=0.123)
        sent = _capture(self.viz, lambda: self.logger.after_training(model))
        self.assertEqual(sent["payload"]["data"][0]["type"], "text")
        content = sent["payload"]["data"][0]["content"]
        self.assertIn("best_iteration: 7", content)
        self.assertIn("best_score: 0.123", content)

    def test_second_call_reuses_the_summary_window(self):
        model = Mock(best_iteration=1, best_score=0.5)
        _capture(self.viz, lambda: self.logger.after_training(model))
        sent = _capture(self.viz, lambda: self.logger.after_training(model))
        self.assertEqual(sent["payload"]["win"], "win1")

    def test_missing_best_iteration_is_a_no_op(self):
        model = Mock(spec=[])
        with patch.object(self.viz, "text") as text_mock:
            self.logger.after_training(model)
        text_mock.assert_not_called()

    def test_returns_the_model_unchanged(self):
        model = Mock(best_iteration=None, best_score=None)
        result = self.logger.after_training(model)
        self.assertIs(result, model)


class TestAutolog(unittest.TestCase):
    def setUp(self):
        self.viz = _unconnected_visdom()
        self.addCleanup(lambda: setattr(VisdomXGBLogger, "active", None))

    def _dtrain(self):
        X = np.array([[0.0], [1.0], [2.0], [3.0]])
        y = np.array([0.0, 1.0, 2.0, 3.0])
        return xgb.DMatrix(X, label=y)

    def test_train_is_logged_without_passing_callbacks_explicitly(self):
        logger = VisdomXGBLogger.autolog(viz=self.viz, env="xgb_autolog")
        dtrain = self._dtrain()
        with (
            patch.object(self.viz, "_send", return_value="win1") as send,
            patch.object(self.viz, "win_exists", return_value=True),
        ):
            xgb.train(
                {"objective": "reg:squarederror", "verbosity": 0},
                dtrain,
                num_boost_round=3,
                evals=[(dtrain, "train")],
                verbose_eval=False,
            )
        self.assertEqual(send.call_count, 3)
        self.assertIn("rmse", logger._wins)

    def test_autolog_called_twice_does_not_double_wrap_train(self):
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_autolog")
        first_train = xgb.train
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_autolog")
        self.assertIs(xgb.train, first_train)

    def test_switching_env_warns_and_makes_the_new_logger_active(self):
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_env_a")
        with self.assertWarns(UserWarning):
            logger_b = VisdomXGBLogger.autolog(viz=self.viz, env="xgb_env_b")
        self.assertIs(VisdomXGBLogger.active, logger_b)

    def test_xgbmodel_fit_is_logged_via_autolog(self):
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_estimator")
        X = np.array([[0.0], [1.0], [2.0], [3.0]])
        y = np.array([0.0, 1.0, 2.0, 3.0])
        model = xgb.XGBRegressor(n_estimators=3, verbosity=0)
        with (
            patch.object(self.viz, "_send", return_value="win1") as send,
            patch.object(self.viz, "win_exists", return_value=True),
        ):
            model.fit(X, y, eval_set=[(X, y)], verbose=False)
        self.assertTrue(send.called)


if __name__ == "__main__":
    unittest.main()
