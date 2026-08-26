#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for VisdomKerasLogger.

VisdomKerasLogger is used manually (passed via callbacks=[...] to fit()),
with no autolog()/monkeypatching involved, so every test below drives its
Callback hooks directly against a mocked viz -- no real model or training
loop needed.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from visdom.loggers.keras import VisdomKerasLogger

pytestmark = pytest.mark.unit


def _logger(**kwargs):
    viz = Mock()
    viz.line.side_effect = lambda *a, **kw: Mock()
    return VisdomKerasLogger(viz, env="test_env", **kwargs)


class TestInit(unittest.TestCase):
    def test_log_every_none_is_allowed(self):
        self.assertIsNone(_logger().log_every)

    def test_log_every_coerced_to_int(self):
        self.assertEqual(_logger(log_every="5").log_every, 5)

    def test_log_every_below_one_raises(self):
        with self.assertRaises(ValueError):
            _logger(log_every=0)


class TestOnEpochEnd(unittest.TestCase):
    def setUp(self):
        self.logger = _logger()

    def test_no_logs_is_noop(self):
        self.logger.on_epoch_end(0, logs=None)
        self.logger.on_epoch_end(0, logs={})
        self.logger.viz.line.assert_not_called()

    def test_first_call_creates_window(self):
        self.logger.on_epoch_end(0, logs={"loss": 0.9})
        self.logger.viz.line.assert_called_once()
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertNotIn("win", kwargs)
        self.assertEqual(kwargs["name"], "train")
        self.assertIn("loss", self.logger._wins)

    def test_val_prefixed_key_shares_window_with_train(self):
        """val_loss and loss land in one 'loss' window as separate
        traces, matching how Keras pairs train/val metrics."""
        self.logger.on_epoch_end(0, logs={"loss": 0.9, "val_loss": 1.1})
        self.assertEqual(list(self.logger._wins), ["loss"])
        names = [c.kwargs["name"] for c in self.logger.viz.line.call_args_list]
        self.assertEqual(names, ["train", "val"])

    def test_later_epoch_appends(self):
        self.logger.on_epoch_end(0, logs={"loss": 0.9})
        win = self.logger._wins["loss"]
        self.logger.on_epoch_end(1, logs={"loss": 0.8})
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["win"], win)
        self.assertEqual(kwargs["update"], "append")

    def test_epoch_zero_on_existing_window_replaces(self):
        """A logger instance reused for a second fit() call starts back
        at epoch 0 while the previous run's window is still tracked."""
        self.logger.on_epoch_end(0, logs={"loss": 0.9})
        win = self.logger._wins["loss"]
        self.logger.on_epoch_end(0, logs={"loss": 0.9})
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["win"], win)
        self.assertEqual(kwargs["update"], "replace")

    def test_logging_exception_is_swallowed_and_warned(self):
        self.logger.viz.line.side_effect = RuntimeError("boom")
        with self.assertWarns(UserWarning):
            self.logger.on_epoch_end(0, logs={"loss": 0.9})


class TestOnTrainBegin(unittest.TestCase):
    def test_resets_step_counter(self):
        logger = _logger(log_every=1)
        logger._step = 5
        logger.on_train_begin()
        self.assertEqual(logger._step, 0)


class TestReadLr(unittest.TestCase):
    def setUp(self):
        self.logger = _logger(log_every=1)

    def test_no_model_returns_none(self):
        """model defaults to None until Keras calls set_model()."""
        self.assertIsNone(self.logger._read_lr())

    def test_optimizer_missing_returns_none(self):
        self.logger.set_model(SimpleNamespace())
        self.assertIsNone(self.logger._read_lr())

    def test_learning_rate_missing_returns_none(self):
        self.logger.set_model(SimpleNamespace(optimizer=SimpleNamespace()))
        self.assertIsNone(self.logger._read_lr())

    def test_plain_float_lr(self):
        optimizer = SimpleNamespace(learning_rate=0.01)
        self.logger.set_model(SimpleNamespace(optimizer=optimizer))
        self.assertEqual(self.logger._read_lr(), 0.01)

    def test_callable_schedule_evaluated_at_optimizer_iterations(self):
        """A LearningRateSchedule is called, not read as a value, using
        the optimizer's own step counter."""
        schedule = Mock(return_value=0.02)
        optimizer = SimpleNamespace(learning_rate=schedule, iterations=42)
        self.logger.set_model(SimpleNamespace(optimizer=optimizer))
        result = self.logger._read_lr()
        schedule.assert_called_once_with(42)
        self.assertEqual(result, 0.02)

    def test_tensor_valued_lr_converted_via_numpy(self):
        lr = SimpleNamespace(numpy=lambda: 0.03)
        optimizer = SimpleNamespace(learning_rate=lr)
        self.logger.set_model(SimpleNamespace(optimizer=optimizer))
        result = self.logger._read_lr()
        self.assertEqual(result, 0.03)
        self.assertIsInstance(result, float)


class TestOnTrainBatchEnd(unittest.TestCase):
    def test_log_every_none_is_noop(self):
        logger = _logger()
        logger.on_train_batch_end(0, logs={"loss": 0.9})
        logger.viz.line.assert_not_called()

    def test_no_logs_is_noop(self):
        logger = _logger(log_every=1)
        logger.on_train_batch_end(0, logs=None)
        logger.viz.line.assert_not_called()

    def test_first_batch_always_logs_regardless_of_log_every(self):
        logger = _logger(log_every=100)
        logger.on_train_batch_end(0, logs={"loss": 0.9})
        logger.viz.line.assert_called_once()

    def test_batch_between_intervals_is_skipped_but_step_still_advances(self):
        logger = _logger(log_every=5)
        logger.on_train_batch_end(0, logs={"loss": 0.9})  # step 0: new run, logs
        logger.viz.line.reset_mock()
        logger._step = 3
        logger.on_train_batch_end(0, logs={"loss": 0.8})  # 3 % 5 != 0: skip
        logger.viz.line.assert_not_called()
        self.assertEqual(logger._step, 4)

    def test_new_run_replaces_existing_step_window(self):
        """Reusing a logger for a second fit() call resets _step to 0,
        which must replace the earlier run's curve, not append to it."""
        logger = _logger(log_every=1)
        logger.on_train_batch_end(0, logs={"loss": 0.9})
        win = logger._step_wins["loss"]
        logger._step = 0
        logger.on_train_batch_end(0, logs={"loss": 0.9})
        kwargs = logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["win"], win)
        self.assertEqual(kwargs["update"], "replace")

    def test_mid_run_appends(self):
        logger = _logger(log_every=1)
        logger.on_train_batch_end(0, logs={"loss": 0.9})
        win = logger._step_wins["loss"]
        logger.on_train_batch_end(0, logs={"loss": 0.8})
        kwargs = logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["win"], win)
        self.assertEqual(kwargs["update"], "append")

    def test_lr_plotted_alongside_metrics_when_available(self):
        logger = _logger(log_every=1)
        logger.set_model(SimpleNamespace(optimizer=SimpleNamespace(learning_rate=0.01)))
        logger.on_train_batch_end(0, logs={"loss": 0.9})
        titles = [c.kwargs["opts"]["title"] for c in logger.viz.line.call_args_list]
        self.assertIn("lr (step)", titles)

    def test_no_lr_window_when_optimizer_missing(self):
        """model defaults to None until Keras calls set_model()."""
        logger = _logger(log_every=1)
        logger.on_train_batch_end(0, logs={"loss": 0.9})
        titles = [c.kwargs["opts"]["title"] for c in logger.viz.line.call_args_list]
        self.assertNotIn("lr (step)", titles)

    def test_logging_exception_is_swallowed_and_warned(self):
        logger = _logger(log_every=1)
        logger.viz.line.side_effect = RuntimeError("boom")
        with self.assertWarns(UserWarning):
            logger.on_train_batch_end(0, logs={"loss": 0.9})
        self.assertEqual(logger._step, 1)


if __name__ == "__main__":
    unittest.main()
