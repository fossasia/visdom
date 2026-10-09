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

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

    def test_failed_window_creation_is_not_tracked(self):
        """A send that fails returns False instead of raising."""
        self.logger.viz.line.side_effect = lambda *a, **kw: False
        self.logger.log("loss", 0.9)
        self.assertNotIn("loss", self.logger._wins)

    def test_window_is_created_again_once_the_server_recovers(self):
        self.logger.viz.line.side_effect = lambda *a, **kw: False
        self.logger.log("loss", 0.9)
        self.logger.viz.line.side_effect = lambda *a, **kw: Mock()
        self.logger.log("loss", 0.8)
        kwargs = self.logger.viz.line.call_args.kwargs
        self.assertNotIn("win", kwargs)
        self.assertIn("loss", self.logger._wins)

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

    def test_failed_interval_send_is_kept_for_the_exit_flush(self):
        """A failed send must not clear the buffer, or the value is lost
        even when the server is back by the time the block exits."""
        logger = _logger(log_every=5)
        logger.viz.line.side_effect = lambda *a, **kw: False
        with logger as tracker:
            for i in range(1, 6):
                tracker.log("loss", float(i))
            self.assertEqual(tracker._pending["loss"], (5, 5.0, "epoch"))
            logger.viz.line.side_effect = lambda *a, **kw: Mock()
            logger.viz.line.reset_mock()
        logger.viz.line.assert_called_once()
        self.assertEqual(logger.viz.line.call_args.kwargs["Y"], [5.0])


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

    def test_failed_append_keeps_the_value_pending(self):
        logger = _logger(log_every=1)
        logger.log("loss", 1.0)
        logger.viz.line.side_effect = lambda *a, **kw: False
        logger.log("loss", 2.0)
        self.assertEqual(logger._pending["loss"], (2, 2.0, "epoch"))

    def test_throttling_holds_when_the_window_was_never_created(self):
        """A failed send leaves the metric out of _wins, which must not
        turn every later call into a send attempt."""
        logger = _logger(log_every=5)
        logger.viz.line.side_effect = lambda *a, **kw: False
        logger.log("loss", 1.0)
        logger.viz.line.reset_mock()
        logger.log("loss", 2.0)
        logger.log("loss", 3.0)
        logger.viz.line.assert_not_called()
        self.assertIn("loss", logger._pending)

    def test_plotted_value_after_buffered_one_drops_the_buffer(self):
        logger = _logger(log_every=2)
        logger.log("loss", 1.0)  # plotted
        logger.log("loss", 2.0)  # plotted
        logger.log("loss", 3.0)  # buffered
        self.assertIn("loss", logger._pending)
        logger.log("loss", 4.0)  # on interval -> plotted, buffer cleared
        self.assertNotIn("loss", logger._pending)
        self.assertEqual(logger.viz.line.call_args.kwargs["Y"], [4.0])


class TestRank(unittest.TestCase):
    """Only the main process of a distributed job plots and tracks."""

    @staticmethod
    def _rank(value):
        return patch.dict(os.environ, {"RANK": str(value)})

    @staticmethod
    def _tracked_logger(**kwargs):
        logger = _logger(params={"lr": 0.1}, **kwargs)
        logger.viz.experiment.return_value = {"env_id": "test_env"}
        logger.viz.finish_experiment.return_value = {"env_id": "test_env"}
        logger.viz.log_metrics.return_value = {"env_id": "test_env"}
        return logger

    def test_nonzero_rank_plots_nothing(self):
        logger = _logger()
        with self._rank(1):
            logger.log("loss", 1.0)
        logger.viz.line.assert_not_called()

    def test_rank_zero_plots(self):
        logger = _logger()
        with self._rank(0):
            logger.log("loss", 1.0)
        logger.viz.line.assert_called_once()

    def test_nonzero_rank_still_validates_input(self):
        logger = _logger()
        with self._rank(2):
            with self.assertRaises(TypeError):
                logger.log("loss", "high")
            with self.assertRaises(TypeError):
                logger.log("", 1.0)

    def test_nonzero_rank_buffers_nothing_for_the_exit_flush(self):
        logger = _logger(log_every=3)
        with self._rank(1):
            with logger as tracker:
                tracker.log("loss", 1.0)
                tracker.log("loss", 2.0)
        self.assertEqual(logger._pending, {})
        logger.viz.line.assert_not_called()

    def test_pending_points_are_not_flushed_once_the_rank_is_nonzero(self):
        logger = _logger(log_every=3)
        with self._rank(0):
            logger.log("loss", 1.0)
            logger.log("loss", 2.0)
        logger.viz.line.assert_called_once()
        with self._rank(1):
            logger.__exit__(None, None, None)
        logger.viz.line.assert_called_once()

    def test_nonzero_rank_skips_experiment_tracking(self):
        logger = self._tracked_logger()
        with self._rank(1):
            with logger as tracker:
                tracker.log("loss", 1.0)
        logger.viz.experiment.assert_not_called()
        logger.viz.log_metrics.assert_not_called()
        logger.viz.finish_experiment.assert_not_called()

    def test_experiment_started_as_main_is_finished_if_rank_turns_nonzero(self):
        logger = self._tracked_logger()
        with self._rank(0):
            logger.__enter__()
        with self._rank(1):
            logger.__exit__(None, None, None)
        logger.viz.finish_experiment.assert_called_once()

    def test_experiment_never_started_is_not_finished_or_fed_metrics(self):
        logger = self._tracked_logger()
        with self._rank(1):
            logger.__enter__()
        with self._rank(0):
            logger.log("loss", 1.0)
            logger.__exit__(None, None, None)
        logger.viz.experiment.assert_not_called()
        logger.viz.log_metrics.assert_not_called()
        logger.viz.finish_experiment.assert_not_called()

    def test_explicit_false_skips_tracking_without_any_rank_information(self):
        logger = self._tracked_logger(is_main_process=False)
        env = {k: v for k, v in os.environ.items() if k not in ("RANK", "SLURM_PROCID")}
        with patch.dict(os.environ, env, clear=True):
            with logger as tracker:
                tracker.log("loss", 1.0)
        logger.viz.line.assert_not_called()
        logger.viz.experiment.assert_not_called()
        logger.viz.finish_experiment.assert_not_called()

    def test_override_must_be_a_bool_or_none(self):
        for bad in ("False", "false", 0, 1, 0.0):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    _logger(is_main_process=bad)
        for good in (True, False, None):
            with self.subTest(good=good):
                _logger(is_main_process=good)

    def test_rank_zero_runs_experiment_tracking(self):
        logger = self._tracked_logger()
        with self._rank(0):
            with logger as tracker:
                tracker.log("loss", 1.0)
        logger.viz.experiment.assert_called_once()
        logger.viz.log_metrics.assert_called_once()
        logger.viz.finish_experiment.assert_called_once()

    def test_nonzero_rank_exit_still_propagates_exceptions(self):
        with self._rank(1):
            with self.assertRaises(RuntimeError):
                with _logger():
                    raise RuntimeError("boom")

    def test_rank_is_read_at_call_time_not_at_construction(self):
        logger = _logger()
        with self._rank(1):
            logger.log("loss", 1.0)
        logger.viz.line.assert_not_called()
        with self._rank(0):
            logger.log("loss", 2.0)
        logger.viz.line.assert_called_once()

    def test_explicit_false_overrides_rank_zero(self):
        logger = _logger(is_main_process=False)
        with self._rank(0):
            logger.log("loss", 1.0)
        logger.viz.line.assert_not_called()

    def test_explicit_true_overrides_nonzero_rank(self):
        logger = _logger(is_main_process=True)
        with self._rank(3):
            logger.log("loss", 1.0)
        logger.viz.line.assert_called_once()

    def test_slurm_procid_is_used_when_rank_is_unset(self):
        logger = _logger()
        env = {k: v for k, v in os.environ.items() if k != "RANK"}
        env["SLURM_PROCID"] = "2"
        with patch.dict(os.environ, env, clear=True):
            logger.log("loss", 1.0)
        logger.viz.line.assert_not_called()

    def test_negative_rank_means_not_distributed(self):
        logger = _logger()
        with self._rank(-1):
            logger.log("loss", 1.0)
        logger.viz.line.assert_called_once()

    def test_local_rank_alone_does_not_silence_the_logger(self):
        logger = _logger()
        env = {k: v for k, v in os.environ.items() if k not in ("RANK", "SLURM_PROCID")}
        env["LOCAL_RANK"] = "1"
        with patch.dict(os.environ, env, clear=True):
            logger.log("loss", 1.0)
        logger.viz.line.assert_called_once()

    def test_initialized_process_group_decides_over_environment(self):
        dist = Mock()
        dist.is_available.return_value = True
        dist.is_initialized.return_value = True
        dist.get_rank.return_value = 2
        logger = _logger()
        with self._rank(0), patch.dict(sys.modules, {"torch.distributed": dist}):
            logger.log("loss", 1.0)
        logger.viz.line.assert_not_called()

    def test_uninitialized_process_group_falls_back_to_environment(self):
        dist = Mock()
        dist.is_available.return_value = True
        dist.is_initialized.return_value = False
        logger = _logger()
        with self._rank(1), patch.dict(sys.modules, {"torch.distributed": dist}):
            logger.log("loss", 1.0)
        logger.viz.line.assert_not_called()
        dist.get_rank.assert_not_called()


if __name__ == "__main__":
    unittest.main()
