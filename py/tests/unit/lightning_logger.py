#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for VisdomLightningLogger.

VisdomLightningLogger implements Lightning's Logger protocol -- Lightning
calls log_metrics / log_hyperparams / finalize directly, so every test
below drives those methods against a mocked viz, with no LightningModule,
Trainer or training loop. viz.line / viz.properties return a fresh handle
per call so window bookkeeping can be asserted.
"""

import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from visdom.loggers.lightning import VisdomLightningLogger

pytestmark = pytest.mark.unit


def _mock_viz():
    viz = Mock()
    viz.line.side_effect = lambda *a, **kw: Mock()
    viz.properties.side_effect = lambda *a, **kw: Mock()
    return viz


def _logger(**kwargs):
    kwargs.setdefault("env", "lightning_test")
    return VisdomLightningLogger(_mock_viz(), **kwargs)


class TestInit(unittest.TestCase):
    def test_explicit_env_is_kept(self):
        self.assertEqual(_logger(env="my_run").env, "my_run")

    def test_falls_back_to_viz_env(self):
        viz = SimpleNamespace(env="from_viz")
        self.assertEqual(VisdomLightningLogger(viz).env, "from_viz")

    def test_viz_env_main_is_ignored(self):
        viz = SimpleNamespace(env="main")
        self.assertTrue(VisdomLightningLogger(viz).env.startswith("lightning_"))

    def test_default_env_has_lightning_prefix(self):
        viz = SimpleNamespace(env=None)
        self.assertTrue(VisdomLightningLogger(viz).env.startswith("lightning_"))

    def test_initial_state(self):
        logger = _logger()
        self.assertEqual(logger._wins, {})
        self.assertIsNone(logger._hparam_win)
        self.assertEqual(logger._step, 0)


class TestProperties(unittest.TestCase):
    def setUp(self):
        self.logger = _logger(env="run_x")

    def test_name_is_visdom(self):
        self.assertEqual(self.logger.name, "visdom")

    def test_version_is_the_env(self):
        self.assertEqual(self.logger.version, "run_x")

    def test_experiment_is_the_viz_client(self):
        self.assertIs(self.logger.experiment, self.logger.viz)


class TestToFloat(unittest.TestCase):
    def test_int_becomes_float(self):
        self.assertEqual(VisdomLightningLogger._to_float(3), 3.0)

    def test_numeric_string_is_parsed(self):
        self.assertEqual(VisdomLightningLogger._to_float("2.5"), 2.5)

    def test_scalar_tensor_is_unwrapped_via_dunder_float(self):
        class _Scalar:
            def __float__(self):
                return 0.25

        self.assertEqual(VisdomLightningLogger._to_float(_Scalar()), 0.25)

    def test_non_numeric_string_is_none(self):
        self.assertIsNone(VisdomLightningLogger._to_float("high"))

    def test_none_is_none(self):
        self.assertIsNone(VisdomLightningLogger._to_float(None))

    def test_multi_element_sequence_is_none(self):
        self.assertIsNone(VisdomLightningLogger._to_float([1, 2]))


class TestLogMetrics(unittest.TestCase):
    def setUp(self):
        self.logger = _logger(env="run_x")
        self.viz = self.logger.viz

    def test_empty_metrics_is_a_noop(self):
        self.logger.log_metrics({})
        self.viz.line.assert_not_called()

    def test_none_metrics_is_a_noop(self):
        self.logger.log_metrics(None)
        self.viz.line.assert_not_called()

    def test_first_metric_opens_a_window(self):
        self.logger.log_metrics({"loss": 0.5})
        self.viz.line.assert_called_once()
        kwargs = self.viz.line.call_args.kwargs
        self.assertNotIn("win", kwargs)
        self.assertEqual(kwargs["env"], "run_x")
        self.assertEqual(
            kwargs["opts"],
            {"title": "loss", "xlabel": "step", "ylabel": "loss"},
        )
        self.assertIn("loss", self.logger._wins)

    def test_second_call_appends_to_the_same_window(self):
        self.logger.log_metrics({"loss": 0.5})
        handle = self.logger._wins["loss"]
        self.logger.log_metrics({"loss": 0.4})
        kwargs = self.viz.line.call_args.kwargs
        self.assertEqual(kwargs["win"], handle)
        self.assertEqual(kwargs["update"], "append")
        self.assertNotIn("opts", kwargs)

    def test_step_none_auto_increments_from_zero(self):
        self.logger.log_metrics({"loss": 1.0})
        self.assertEqual(self.viz.line.call_args.kwargs["X"], [0])
        self.logger.log_metrics({"loss": 2.0})
        self.assertEqual(self.viz.line.call_args.kwargs["X"], [1])

    def test_explicit_step_is_used(self):
        self.logger.log_metrics({"loss": 1.0}, step=5)
        self.assertEqual(self.viz.line.call_args.kwargs["X"], [5])

    def test_explicit_step_is_coerced_to_int(self):
        self.logger.log_metrics({"loss": 1.0}, step="7")
        self.assertEqual(self.viz.line.call_args.kwargs["X"], [7])
        self.assertEqual(self.logger._step, 0)

    def test_invalid_step_falls_back_to_the_auto_counter(self):
        self.logger.log_metrics({"loss": 1.0}, step="bad")
        self.assertEqual(self.viz.line.call_args.kwargs["X"], [0])
        self.logger.log_metrics({"loss": 2.0}, step="bad")
        self.assertEqual(self.viz.line.call_args.kwargs["X"], [1])

    def test_epoch_key_is_not_plotted(self):
        self.logger.log_metrics({"epoch": 3, "loss": 0.1})
        self.viz.line.assert_called_once()
        self.assertIn("loss", self.logger._wins)
        self.assertNotIn("epoch", self.logger._wins)

    def test_non_numeric_metric_warns_and_is_skipped(self):
        with self.assertWarns(UserWarning):
            self.logger.log_metrics({"loss": "high"})
        self.viz.line.assert_not_called()

    def test_one_bad_metric_does_not_block_the_others(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.logger.log_metrics({"bad": None, "good": 1.0})
        self.assertIn("good", self.logger._wins)
        self.assertNotIn("bad", self.logger._wins)

    def test_plot_failure_warns_instead_of_raising(self):
        self.viz.line.side_effect = RuntimeError("boom")
        with self.assertWarns(UserWarning):
            self.logger.log_metrics({"loss": 0.5})

    def test_one_step_is_shared_across_every_key_in_a_call(self):
        self.logger.log_metrics({"a": 1.0, "b": 2.0})
        for call in self.viz.line.call_args_list:
            self.assertEqual(call.kwargs["X"], [0])
        self.viz.line.reset_mock()
        self.logger.log_metrics({"a": 1.5, "b": 2.5})
        for call in self.viz.line.call_args_list:
            self.assertEqual(call.kwargs["X"], [1])

    def test_distinct_metrics_get_distinct_windows(self):
        self.logger.log_metrics({"loss": 0.5, "acc": 0.9})
        self.assertEqual(sorted(self.logger._wins), ["acc", "loss"])


class TestLogHyperparams(unittest.TestCase):
    def setUp(self):
        self.logger = _logger(env="run_x")
        self.viz = self.logger.viz

    def test_none_is_a_noop(self):
        self.logger.log_hyperparams(None)
        self.viz.properties.assert_not_called()

    def test_empty_dict_is_a_noop(self):
        self.logger.log_hyperparams({})
        self.viz.properties.assert_not_called()

    def test_dict_params_open_a_window(self):
        self.logger.log_hyperparams({"lr": 0.1, "bs": 32})
        self.viz.properties.assert_called_once()
        args, kwargs = self.viz.properties.call_args
        content = args[0]
        self.assertEqual(
            content,
            [
                {"type": "text", "name": "lr", "value": "0.1"},
                {"type": "text", "name": "bs", "value": "32"},
            ],
        )
        self.assertEqual(kwargs["env"], "run_x")
        self.assertEqual(kwargs["opts"], {"title": "hyperparameters"})
        self.assertNotIn("win", kwargs)
        self.assertIsNotNone(self.logger._hparam_win)

    def test_namespace_params_are_converted_via_vars(self):
        self.logger.log_hyperparams(SimpleNamespace(lr=0.1))
        content = self.viz.properties.call_args.args[0]
        self.assertEqual(content, [{"type": "text", "name": "lr", "value": "0.1"}])

    def test_non_dict_mapping_is_converted(self):
        import collections.abc

        class _Mapping(collections.abc.Mapping):
            _data = {"lr": 0.1}

            def __getitem__(self, key):
                return self._data[key]

            def __iter__(self):
                return iter(self._data)

            def __len__(self):
                return len(self._data)

        self.logger.log_hyperparams(_Mapping())
        content = self.viz.properties.call_args.args[0]
        self.assertEqual(content, [{"type": "text", "name": "lr", "value": "0.1"}])

    def test_second_call_reuses_the_hyperparameter_window(self):
        self.logger.log_hyperparams({"lr": 0.1})
        handle = self.logger._hparam_win
        self.logger.log_hyperparams({"lr": 0.2})
        self.assertEqual(self.viz.properties.call_args.kwargs["win"], handle)

    def test_failure_warns_instead_of_raising(self):
        self.viz.properties.side_effect = RuntimeError("boom")
        with self.assertWarns(UserWarning):
            self.logger.log_hyperparams({"lr": 0.1})


class TestFinalize(unittest.TestCase):
    def setUp(self):
        self.logger = _logger(env="run_x")
        self.viz = self.logger.viz

    def test_finalize_saves_the_env(self):
        self.logger.finalize("success")
        self.viz.save.assert_called_once_with(["run_x"])

    def test_finalize_failure_warns_instead_of_raising(self):
        self.viz.save.side_effect = RuntimeError("boom")
        with self.assertWarns(UserWarning):
            self.logger.finalize("failed")


if __name__ == "__main__":
    unittest.main()
