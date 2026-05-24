# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the visdom.logging bridge.

All tests use ``send=False`` or mock the Visdom instance so no running
server is required.
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np


# ---------------------------------------------------------------------------
# Auto-versioning tests
# ---------------------------------------------------------------------------


class TestGetNextVersion(unittest.TestCase):
    """Tests for :func:`visdom.logging._version.get_next_version`."""

    def _call(self, env_list, base_env="run"):
        from visdom.logging._version import get_next_version

        viz = MagicMock()
        viz.get_env_list.return_value = env_list
        return get_next_version(viz, base_env)

    def test_empty_env_list(self):
        env, ver = self._call([])
        self.assertEqual(env, "run_000")
        self.assertEqual(ver, 0)

    def test_sequential(self):
        env, ver = self._call(["run_000", "run_001", "run_002"])
        self.assertEqual(env, "run_003")
        self.assertEqual(ver, 3)

    def test_gap_ignored(self):
        """Should use max+1, not fill gaps."""
        env, ver = self._call(["run_000", "run_005"])
        self.assertEqual(env, "run_006")
        self.assertEqual(ver, 6)

    def test_non_matching_envs_ignored(self):
        env, ver = self._call(["main", "other_001", "run_002"])
        self.assertEqual(env, "run_003")
        self.assertEqual(ver, 3)

    def test_custom_base(self):
        env, ver = self._call(["exp_000", "exp_001"], base_env="exp")
        self.assertEqual(env, "exp_002")
        self.assertEqual(ver, 2)

    def test_server_unreachable(self):
        """When the server is down, start from 0."""
        from visdom.logging._version import get_next_version

        viz = MagicMock()
        viz.get_env_list.side_effect = Exception("connection refused")
        env, ver = get_next_version(viz, "run")
        self.assertEqual(env, "run_000")
        self.assertEqual(ver, 0)


# ---------------------------------------------------------------------------
# VisdomLoggingHandler tests
# ---------------------------------------------------------------------------


class TestVisdomLoggingHandler(unittest.TestCase):
    """Tests for :class:`visdom.logging.handler.VisdomLoggingHandler`."""

    def _make_handler(self, **kwargs):
        from visdom.logging.handler import VisdomLoggingHandler

        mock_viz = MagicMock()
        mock_viz.line.return_value = "win_id_1"
        mock_viz.text.return_value = "text_win_1"
        mock_viz.image.return_value = "img_win_1"

        handler = VisdomLoggingHandler(viz=mock_viz, **kwargs)
        return handler, mock_viz

    def test_log_routes_to_line(self):
        handler, viz = self._make_handler()
        handler.log({"loss": 0.5}, step=1)

        viz.line.assert_called_once()
        call_kwargs = viz.line.call_args
        np.testing.assert_array_equal(call_kwargs[1]["Y"], np.array([0.5]))
        np.testing.assert_array_equal(call_kwargs[1]["X"], np.array([1.0]))
        self.assertEqual(call_kwargs[1]["opts"]["title"], "loss")

    def test_creates_window_once(self):
        handler, viz = self._make_handler()
        viz.line.return_value = "win_loss"

        handler.log({"loss": 0.5}, step=0)
        handler.log({"loss": 0.3}, step=1)

        self.assertEqual(viz.line.call_count, 2)
        # Second call should use update='append' with the stored window.
        second_call = viz.line.call_args_list[1]
        self.assertEqual(second_call[1]["win"], "win_loss")
        self.assertEqual(second_call[1]["update"], "append")

    def test_multiple_metrics_get_separate_windows(self):
        handler, viz = self._make_handler()
        win_counter = {"n": 0}

        def mock_line(**kwargs):
            win_counter["n"] += 1
            return "win_{}".format(win_counter["n"])

        viz.line.side_effect = mock_line

        handler.log({"loss": 0.5, "accuracy": 0.8}, step=0)
        self.assertEqual(viz.line.call_count, 2)
        self.assertIn("loss", handler.windows)
        self.assertIn("accuracy", handler.windows)

    def test_context_manager(self):
        from visdom.logging.handler import VisdomLoggingHandler

        mock_viz = MagicMock()
        mock_viz.line.return_value = "w"

        with VisdomLoggingHandler(viz=mock_viz) as h:
            h.log({"loss": 1.0}, step=0)

        mock_viz.line.assert_called_once()

    def test_decorator(self):
        from visdom.logging.handler import VisdomLoggingHandler

        mock_viz = MagicMock()
        mock_viz.line.return_value = "w"

        @VisdomLoggingHandler(viz=mock_viz)
        def train(logger):
            logger.log({"loss": 1.0}, step=0)
            return "done"

        result = train()
        self.assertEqual(result, "done")
        mock_viz.line.assert_called_once()

    def test_include_filter(self):
        handler, viz = self._make_handler(include_metrics=["loss", "acc*"])
        handler.log({"loss": 0.5, "accuracy": 0.8, "lr": 0.001}, step=0)

        # loss → exact match, accuracy → matches acc*, lr → excluded
        call_titles = [c[1]["opts"]["title"] for c in viz.line.call_args_list]
        self.assertIn("loss", call_titles)
        self.assertIn("accuracy", call_titles)
        self.assertNotIn("lr", call_titles)

    def test_exclude_filter(self):
        handler, viz = self._make_handler(exclude_metrics=["debug_*"])
        handler.log({"loss": 0.5, "debug_grad_norm": 1.2, "accuracy": 0.9}, step=0)

        call_titles = [c[1]["opts"]["title"] for c in viz.line.call_args_list]
        self.assertIn("loss", call_titles)
        self.assertIn("accuracy", call_titles)
        self.assertNotIn("debug_grad_norm", call_titles)

    def test_log_text(self):
        handler, viz = self._make_handler()
        handler.log_text("hello world")
        viz.text.assert_called_once_with(
            "hello world", win=None, env="main", append=False
        )

    def test_log_image(self):
        handler, viz = self._make_handler()
        img = np.random.rand(3, 64, 64)
        handler.log_image(img)
        viz.image.assert_called_once()

    def test_step_none(self):
        handler, viz = self._make_handler()
        handler.log({"loss": 0.5})  # step=None

        call_kwargs = viz.line.call_args[1]
        self.assertIsNone(call_kwargs["X"])

    def test_env_property(self):
        handler, _ = self._make_handler(env="my_env")
        self.assertEqual(handler.env, "my_env")


# ---------------------------------------------------------------------------
# VisdomLogger tests (only if pytorch_lightning is installed)
# ---------------------------------------------------------------------------

try:
    import pytorch_lightning  # noqa: F401

    _HAS_LIGHTNING = True
except ImportError:
    _HAS_LIGHTNING = False


@unittest.skipUnless(_HAS_LIGHTNING, "pytorch_lightning not installed")
class TestVisdomLogger(unittest.TestCase):
    """Tests for :class:`visdom.logging.logger.VisdomLogger`."""

    def _make_logger(self, **kwargs):
        from visdom.logging.logger import VisdomLogger

        with patch.object(
            VisdomLogger,
            "_resolved_env",
            new_callable=PropertyMock,
            return_value="test_000",
        ):
            logger = VisdomLogger(env="test_000", **kwargs)

        # Inject a mock Visdom.
        mock_viz = MagicMock()
        mock_viz.line.return_value = "win_1"
        mock_viz.text.return_value = "text_1"
        logger._viz = mock_viz
        logger._env = "test_000"
        logger._version = 0
        return logger, mock_viz

    def test_implements_interface(self):
        from visdom.logging.logger import VisdomLogger

        # Should have the required properties / methods.
        self.assertTrue(hasattr(VisdomLogger, "name"))
        self.assertTrue(hasattr(VisdomLogger, "version"))
        self.assertTrue(hasattr(VisdomLogger, "log_metrics"))
        self.assertTrue(hasattr(VisdomLogger, "log_hyperparams"))
        self.assertTrue(hasattr(VisdomLogger, "finalize"))
        self.assertTrue(hasattr(VisdomLogger, "experiment"))

    def test_name_and_version(self):
        logger, _ = self._make_logger(base_env="experiment")
        self.assertEqual(logger.name, "experiment")
        self.assertEqual(logger.version, 0)

    def test_log_metrics(self):
        logger, viz = self._make_logger()
        logger.log_metrics({"loss": 0.42}, step=10)

        viz.line.assert_called_once()
        kw = viz.line.call_args[1]
        np.testing.assert_array_equal(kw["Y"], np.array([0.42]))
        np.testing.assert_array_equal(kw["X"], np.array([10.0]))
        self.assertEqual(kw["opts"]["title"], "loss")

    def test_log_metrics_with_global_step_key(self):
        logger, viz = self._make_logger()
        logger.log_metrics({"loss": 0.3, "global_step": 5}, step=999)

        kw = viz.line.call_args[1]
        # global_step should be used as X, not step=999
        np.testing.assert_array_equal(kw["X"], np.array([5.0]))

    def test_log_hyperparams(self):
        logger, viz = self._make_logger()
        logger.log_hyperparams({"lr": 0.001, "batch_size": 32})

        viz.text.assert_called_once()
        html = viz.text.call_args[0][0]
        self.assertIn("lr", html)
        self.assertIn("0.001", html)
        self.assertIn("batch_size", html)
        self.assertIn("32", html)

    def test_log_hyperparams_namespace(self):
        from argparse import Namespace

        logger, viz = self._make_logger()
        logger.log_hyperparams(Namespace(lr=0.01, epochs=10))

        viz.text.assert_called_once()
        html = viz.text.call_args[0][0]
        self.assertIn("lr", html)
        self.assertIn("epochs", html)

    def test_finalize(self):
        logger, viz = self._make_logger()
        logger.finalize("success")

        viz.text.assert_called_once()
        html = viz.text.call_args[0][0]
        self.assertIn("success", html)

    def test_include_filter(self):
        logger, viz = self._make_logger(include_metrics=["loss"])
        logger.log_metrics({"loss": 0.5, "accuracy": 0.9}, step=0)

        call_titles = [c[1]["opts"]["title"] for c in viz.line.call_args_list]
        self.assertIn("loss", call_titles)
        self.assertNotIn("accuracy", call_titles)

    def test_exclude_filter(self):
        logger, viz = self._make_logger(exclude_metrics=["debug_*"])
        logger.log_metrics({"loss": 0.5, "debug_info": 1.0}, step=0)

        call_titles = [c[1]["opts"]["title"] for c in viz.line.call_args_list]
        self.assertIn("loss", call_titles)
        self.assertNotIn("debug_info", call_titles)

    def test_experiment_property(self):
        logger, viz = self._make_logger()
        self.assertIs(logger.experiment, viz)


if __name__ == "__main__":
    unittest.main()
