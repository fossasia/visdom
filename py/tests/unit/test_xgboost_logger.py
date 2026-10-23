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

    def test_continued_training_appends_at_the_models_round(self):
        # xgb_model= restarts epoch at 0, but the model already has 5 rounds.
        self.logger._wins["rmse"] = "existing_win"
        model = Mock(num_boosted_rounds=Mock(return_value=6))
        sent = _capture(
            self.viz,
            lambda: self.logger.after_iteration(model, 0, {"train": {"rmse": [0.3]}}),
        )
        self.assertTrue(sent["payload"]["append"])
        self.assertEqual(sent["payload"]["data"][0]["x"], [5])

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


class TestAutologContinuedTraining(unittest.TestCase):
    """autolog() keeps a continued run in its window and opens new ones otherwise."""

    PARAMS = {"objective": "binary:logistic", "verbosity": 0}

    def setUp(self):
        self.viz = _unconnected_visdom()
        self.addCleanup(lambda: setattr(VisdomXGBLogger, "active", None))
        rng = np.random.RandomState(0)
        self.X, self.y = rng.rand(60, 3), rng.randint(0, 2, 60)
        self.dtrain = xgb.DMatrix(self.X, label=self.y)
        self.created = []
        self.calls = []

        def line(**kwargs):
            self.calls.append(kwargs)
            if kwargs.get("win") is None:
                self.created.append("win%d" % len(self.created))
                return self.created[-1]
            return kwargs["win"]

        self.line = line

    def _train(self, rounds, **kwargs):
        return xgb.train(
            self.PARAMS,
            self.dtrain,
            rounds,
            evals=[(self.dtrain, "eval")],
            verbose_eval=False,
            **kwargs,
        )

    def test_train_with_xgb_model_continues_in_the_same_window(self):
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_test")
        with patch.object(self.viz, "line", side_effect=self.line):
            first = self._train(3)
            self._train(2, xgb_model=first)
        self.assertEqual(self.created, ["win0"])
        self.assertEqual([c["X"][0] for c in self.calls], [0, 1, 2, 3, 4])
        self.assertEqual(
            [c.get("update") for c in self.calls[3:]], ["append", "append"]
        )

    def test_fit_with_xgb_model_continues_in_the_same_window(self):
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_test")
        with patch.object(self.viz, "line", side_effect=self.line):
            first = xgb.XGBClassifier(n_estimators=3).fit(
                self.X, self.y, eval_set=[(self.X, self.y)], verbose=False
            )
            xgb.XGBClassifier(n_estimators=2).fit(
                self.X,
                self.y,
                eval_set=[(self.X, self.y)],
                verbose=False,
                xgb_model=first.get_booster(),
            )
        self.assertEqual(self.created, ["win0"])
        self.assertEqual([c["X"][0] for c in self.calls], [0, 1, 2, 3, 4])

    def test_separate_runs_still_open_their_own_windows(self):
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_test")
        with patch.object(self.viz, "line", side_effect=self.line):
            self._train(3)
            self._train(2)
        self.assertEqual(self.created, ["win0", "win1"])

    def test_continuing_an_unrelated_model_opens_a_new_window(self):
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_test")
        other = xgb.train(self.PARAMS, self.dtrain, 7)
        with patch.object(self.viz, "line", side_effect=self.line):
            self._train(3)
            self._train(2, xgb_model=other)
        self.assertEqual(self.created, ["win0", "win1"])
        self.assertEqual([c["X"][0] for c in self.calls[3:]], [7, 8])

    def test_grid_search_fits_share_one_window(self):
        model_selection = pytest.importorskip("sklearn.model_selection")
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_test")
        search = model_selection.GridSearchCV(
            xgb.XGBClassifier(n_estimators=2), {"max_depth": [2, 3]}, cv=2
        )
        with patch.object(self.viz, "line", side_effect=self.line):
            search.fit(self.X, self.y, eval_set=[(self.X, self.y)], verbose=False)
        self.assertEqual(self.created, ["win0"])


class TestRunsWithoutEvals(unittest.TestCase):
    """A run that logs no eval data leaves the plotted curve as it was."""

    PARAMS = {"objective": "binary:logistic", "verbosity": 0}

    def setUp(self):
        self.viz = _unconnected_visdom()
        self.addCleanup(lambda: setattr(VisdomXGBLogger, "active", None))
        rng = np.random.RandomState(0)
        self.dtrain = xgb.DMatrix(rng.rand(60, 3), label=rng.randint(0, 2, 60))
        self.calls = []

    def line(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs.get("win") or "win%d" % len(self.calls)

    def _train(self, rounds, evals=True, **kwargs):
        evals = [(self.dtrain, "eval")] if evals else []
        return xgb.train(
            self.PARAMS, self.dtrain, rounds, evals=evals, verbose_eval=False, **kwargs
        )

    def _continue_after_a_run_without_evals(self, **callbacks):
        with patch.object(self.viz, "line", side_effect=self.line):
            first = self._train(3, **callbacks)
            self._train(2, evals=False, **callbacks)
            self._train(2, xgb_model=first, **callbacks)
        later = self.calls[3:]
        self.assertEqual([c["X"][0] for c in later], [3, 4])
        self.assertEqual([c.get("update") for c in later], ["append", "append"])
        self.assertEqual({c["win"] for c in later}, {"win1"})

    def test_manual_callback_keeps_the_curve(self):
        logger = VisdomXGBLogger(self.viz, env="xgb_test")
        self._continue_after_a_run_without_evals(callbacks=[logger])

    def test_autolog_keeps_the_curve(self):
        VisdomXGBLogger.autolog(viz=self.viz, env="xgb_test")
        self._continue_after_a_run_without_evals()

    def test_a_run_without_evals_plots_nothing(self):
        logger = VisdomXGBLogger(self.viz, env="xgb_test")
        with patch.object(self.viz, "line", side_effect=self.line):
            self._train(3, evals=False, callbacks=[logger])
        self.assertEqual(self.calls, [])
        self.assertEqual(logger._next_round, 0)


class TestContinuationIsMatchedByRoundCount(unittest.TestCase):
    """Only the round count is compared, as before_training documents."""

    def test_an_unrelated_model_with_the_same_rounds_is_appended(self):
        rng = np.random.RandomState(0)
        dtrain = xgb.DMatrix(rng.rand(60, 3), label=rng.randint(0, 2, 60))
        params = {"objective": "binary:logistic", "verbosity": 0}
        unrelated = xgb.train(params, dtrain, 3)
        viz = _unconnected_visdom()
        logger = VisdomXGBLogger(viz, env="xgb_test")
        with patch.object(viz, "line", return_value="win1") as line:
            xgb.train(params, dtrain, 3, evals=[(dtrain, "eval")], callbacks=[logger])
            xgb.train(
                params,
                dtrain,
                2,
                evals=[(dtrain, "eval")],
                callbacks=[logger],
                xgb_model=unrelated,
            )
        later = line.call_args_list[3:]
        self.assertEqual([c.kwargs["X"][0] for c in later], [3, 4])
        self.assertEqual([c.kwargs.get("update") for c in later], ["append"] * 2)


class TestContinuedTraining(unittest.TestCase):
    """Training on from xgb_model extends the curve instead of wiping it."""

    def _rounds(self, line, name):
        return [
            (c.kwargs["X"][0], c.kwargs.get("update"))
            for c in line.call_args_list
            if c.kwargs["name"] == name
        ]

    def test_curve_continues_across_xgb_model(self):
        rng = np.random.RandomState(0)
        dtrain = xgb.DMatrix(rng.rand(60, 3), label=rng.randint(0, 2, 60))
        params = {"objective": "binary:logistic", "verbosity": 0}
        viz = _unconnected_visdom()
        logger = VisdomXGBLogger(viz, env="xgb_test")
        with patch.object(viz, "line", return_value="win1") as line:
            first = xgb.train(
                params, dtrain, 3, evals=[(dtrain, "eval")], callbacks=[logger]
            )
            xgb.train(
                params,
                dtrain,
                3,
                evals=[(dtrain, "eval")],
                callbacks=[logger],
                xgb_model=first,
            )
        rounds = self._rounds(line, "eval")
        self.assertEqual([x for x, _ in rounds], [0, 1, 2, 3, 4, 5])
        self.assertNotIn("replace", [u for _, u in rounds])

    def test_a_separate_pretrained_model_starts_a_new_curve(self):
        """xgb_model= from another training is not a continuation of this curve."""
        rng = np.random.RandomState(0)
        dtrain = xgb.DMatrix(rng.rand(60, 3), label=rng.randint(0, 2, 60))
        params = {"objective": "binary:logistic", "verbosity": 0}
        other = xgb.train(params, dtrain, 7)
        viz = _unconnected_visdom()
        logger = VisdomXGBLogger(viz, env="xgb_test")
        with patch.object(viz, "line", return_value="win1") as line:
            xgb.train(params, dtrain, 3, evals=[(dtrain, "eval")], callbacks=[logger])
            xgb.train(
                params,
                dtrain,
                2,
                evals=[(dtrain, "eval")],
                callbacks=[logger],
                xgb_model=other,
            )
        rounds = self._rounds(line, "eval")
        self.assertEqual(rounds[3:], [(7, "replace"), (8, "append")])

    def test_a_failure_warns_with_the_plotted_round(self):
        viz = _unconnected_visdom()
        logger = VisdomXGBLogger(viz, env="xgb_test")
        model = Mock(num_boosted_rounds=Mock(return_value=6))
        with patch.object(viz, "line", side_effect=RuntimeError("boom")):
            with self.assertWarnsRegex(UserWarning, "round 5"):
                logger.after_iteration(model, 0, {"train": {"rmse": [0.5]}})

    def test_a_fresh_model_still_replaces_the_old_run(self):
        rng = np.random.RandomState(0)
        dtrain = xgb.DMatrix(rng.rand(60, 3), label=rng.randint(0, 2, 60))
        params = {"objective": "binary:logistic", "verbosity": 0}
        viz = _unconnected_visdom()
        logger = VisdomXGBLogger(viz, env="xgb_test")
        with patch.object(viz, "line", return_value="win1") as line:
            for _ in range(2):
                xgb.train(
                    params, dtrain, 2, evals=[(dtrain, "eval")], callbacks=[logger]
                )
        rounds = self._rounds(line, "eval")
        self.assertEqual(
            rounds, [(0, None), (1, "append"), (0, "replace"), (1, "append")]
        )


if __name__ == "__main__":
    unittest.main()
