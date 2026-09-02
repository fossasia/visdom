#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for VisdomLogger (raw PyTorch training-loop logger).

VisdomLogger is driven entirely by the user calling ``log(name, value)``
inside a ``with`` block, so every test below calls ``log`` directly against
a mocked viz -- no model, optimizer or training loop is needed. ``viz.line``
returns a fresh handle per call so window bookkeeping can be asserted.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from visdom.pytorch import VisdomLogger

pytestmark = pytest.mark.unit


def _logger(**kwargs):
    kwargs.setdefault("env", "test_env")
    viz = Mock()
    viz.line.side_effect = lambda *a, **kw: Mock()
    return VisdomLogger(viz, **kwargs)


class TestInit(unittest.TestCase):
    def test_default_env_has_run_prefix(self):
        self.assertTrue(VisdomLogger(Mock()).env.startswith("run_"))

    def test_explicit_env_is_kept(self):
        self.assertEqual(VisdomLogger(Mock(), env="my_run").env, "my_run")

    def test_log_every_coerced_to_int(self):
        self.assertEqual(VisdomLogger(Mock(), log_every="3").log_every, 3)

    def test_log_every_below_one_raises(self):
        with self.assertRaises(ValueError):
            VisdomLogger(Mock(), log_every=0)
        with self.assertRaises(ValueError):
            VisdomLogger(Mock(), log_every=-2)


class TestLogValidation(unittest.TestCase):
    def setUp(self):
        self.logger = _logger()

    def test_empty_name_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.logger.log("", 1.0)

    def test_non_string_name_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.logger.log(123, 1.0)

    def test_non_numeric_value_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.logger.log("loss", "high")

    def test_none_value_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.logger.log("loss", None)

    def test_tensor_like_value_is_unwrapped_via_item(self):
        self.logger.log("loss", SimpleNamespace(item=lambda: 0.25))
        self.assertEqual(self.logger.viz.line.call_args.kwargs["Y"], [0.25])

    def test_int_value_accepted(self):
        self.logger.log("acc", 1)
        self.assertEqual(self.logger.viz.line.call_args.kwargs["Y"], [1])


class TestPlotting(unittest.TestCase):
    def setUp(self):
        self.logger = _logger(env="run_x")

    def test_first_log_creates_window_without_win_kwarg(self):
        self.logger.log("Train Loss", 0.9)
        self.logger.viz.line.assert_called_once()
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertNotIn("win", kwargs)
        self.assertEqual(kwargs["env"], "run_x")
        self.assertEqual(
            kwargs["opts"],
            {"title": "Train Loss", "xlabel": "epoch", "ylabel": "Train Loss"},
        )
        self.assertIn("Train Loss", self.logger._wins)

    def test_window_handle_is_taken_from_viz_line_return(self):
        self.logger.log("loss", 0.9)
        handle = self.logger._wins["loss"]
        self.logger.log("loss", 0.8)
        self.assertEqual(self.logger.viz.line.call_args.kwargs["win"], handle)

    def test_second_log_appends_to_same_window(self):
        self.logger.log("loss", 0.9)
        self.logger.log("loss", 0.8)
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["update"], "append")
        self.assertNotIn("opts", kwargs)

    def test_x_axis_auto_increments_from_one(self):
        self.logger.log("loss", 0.9)
        self.assertEqual(self.logger.viz.line.call_args.kwargs["X"], [1])
        self.logger.log("loss", 0.8)
        self.assertEqual(self.logger.viz.line.call_args.kwargs["X"], [2])

    def test_explicit_x_is_used_and_does_not_advance_auto_step(self):
        self.logger.log("loss", 0.9)  # X=[1]
        self.logger.log("loss", 0.8, x=99)
        self.assertEqual(self.logger.viz.line.call_args.kwargs["X"], [99])
        self.logger.log("loss", 0.7)  # back on the auto axis
        self.assertEqual(self.logger.viz.line.call_args.kwargs["X"], [2])

    def test_xlabel_passed_into_opts(self):
        self.logger.log("loss", 0.9, xlabel="step")
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["opts"]["xlabel"], "step")

    def test_distinct_metrics_get_distinct_windows(self):
        self.logger.log("loss", 0.9)
        self.logger.log("acc", 0.1)
        self.assertEqual(sorted(self.logger._wins), ["acc", "loss"])
        for call in self.logger.viz.line.call_args_list:
            self.assertNotIn("win", call.kwargs)


class TestContextManager(unittest.TestCase):
    def test_enter_returns_the_logger(self):
        logger = _logger()
        with logger as tracker:
            self.assertIs(tracker, logger)

    def test_exit_does_not_suppress_exceptions(self):
        with self.assertRaises(RuntimeError):
            with _logger():
                raise RuntimeError("boom")

    def test_nothing_pending_means_no_flush_on_exit(self):
        logger = _logger(log_every=1)
        with logger as tracker:
            tracker.log("loss", 1.0)
            logger.viz.line.reset_mock()
        logger.viz.line.assert_not_called()

    def test_pending_value_flushed_on_exit(self):
        logger = _logger(log_every=2)
        with logger as tracker:
            tracker.log("loss", 1.0)  # first call -> plotted
            tracker.log("loss", 2.0)  # counter 2, on interval -> plotted
            tracker.log("loss", 3.0)  # counter 3, off interval -> buffered
            logger.viz.line.reset_mock()
        logger.viz.line.assert_called_once()
        kwargs = logger.viz.line.call_args.kwargs
        self.assertEqual(kwargs["update"], "append")
        self.assertEqual(kwargs["X"], [3])
        self.assertEqual(kwargs["Y"], [3.0])


class TestLogEvery(unittest.TestCase):
    def test_first_call_plotted_even_with_large_log_every(self):
        logger = _logger(log_every=100)
        logger.log("loss", 0.5)
        logger.viz.line.assert_called_once()

    def test_off_interval_call_is_buffered_not_plotted(self):
        logger = _logger(log_every=5)
        logger.log("loss", 1.0)
        logger.viz.line.reset_mock()
        logger.log("loss", 2.0)
        logger.viz.line.assert_not_called()
        self.assertIn("loss", logger._pending)

    def test_on_interval_call_is_plotted(self):
        logger = _logger(log_every=2)
        logger.log("loss", 1.0)
        logger.viz.line.reset_mock()
        logger.log("loss", 2.0)
        logger.viz.line.assert_called_once()
        self.assertNotIn("loss", logger._pending)

    def test_plotted_value_after_buffered_one_drops_the_buffer(self):
        logger = _logger(log_every=2)
        logger.log("loss", 1.0)  # plotted
        logger.log("loss", 2.0)  # plotted
        logger.log("loss", 3.0)  # buffered
        self.assertIn("loss", logger._pending)
        logger.log("loss", 4.0)  # on interval -> plotted, buffer cleared
        self.assertNotIn("loss", logger._pending)
        self.assertEqual(logger.viz.line.call_args.kwargs["Y"], [4.0])


if __name__ == "__main__":
    unittest.main()
