"""Tests for the hyper-parameter pane client method (Layer 3, PR A1).

``Visdom.hparams`` is a thin wrapper: it validates ``opts`` like the other
plotting methods and posts the selection (``query``/``env_ids``/``mode``) to the
``experiments/hparams`` endpoint, which does the selecting, flattening and
window creation. These tests pin the request it builds with ``send=False`` (no
server); the selection rules and flattening are tested against the endpoint in
``test_experiment_hparams``.
"""

import unittest

from visdom import Visdom


class TestHparamsClientMessage(unittest.TestCase):
    """Visdom.hparams posts the selection to the experiments/hparams endpoint."""

    def setUp(self):
        self.vis = Visdom(send=False, raise_exceptions=True)

    def test_posts_to_hparams_endpoint(self):
        """The selection goes to the experiments/hparams endpoint."""
        msg, endpoint = self.vis.hparams("acc > 0.9")
        self.assertEqual(endpoint, "experiments/hparams")
        self.assertEqual(msg["query"], "acc > 0.9")
        self.assertIsNone(msg["mode"])
        self.assertIsNone(msg["env_ids"])

    def test_env_ids_and_mode_pass_through(self):
        """env_ids and an explicit mode ride along untouched for the server."""
        msg, _ = self.vis.hparams(env_ids=["run-a", "run-b"], mode="env_ids")
        self.assertEqual(msg["env_ids"], ["run-a", "run-b"])
        self.assertEqual(msg["mode"], "env_ids")

    def test_win_and_env_pass_through(self):
        """win/env target a specific pane like the other plotting methods."""
        msg, _ = self.vis.hparams("acc > 0.9", win="hp1", env="run-x")
        self.assertEqual(msg["win"], "hp1")
        self.assertEqual(msg["eid"], "run-x")

    def test_opts_are_validated_client_side(self):
        """opts are asserted before the request, like the other methods."""
        with self.assertRaises(AssertionError):
            self.vis.hparams("acc > 0.9", opts={"opacity": 5})


class TestUpdateHparamsClientMessage(unittest.TestCase):
    """Visdom.update_hparams posts to the experiments/hparams/update endpoint."""

    def setUp(self):
        self.vis = Visdom(send=False, raise_exceptions=True)

    def test_posts_to_update_endpoint(self):
        """The target window and new selection go to the update endpoint."""
        msg, endpoint = self.vis.update_hparams("hp1", "acc > 0.9")
        self.assertEqual(endpoint, "experiments/hparams/update")
        self.assertEqual(msg["win"], "hp1")
        self.assertEqual(msg["query"], "acc > 0.9")

    def test_bare_refresh_sends_only_the_window(self):
        """A bare refresh carries no selection for the server to replace."""
        msg, _ = self.vis.update_hparams("hp1")
        self.assertIsNone(msg["query"])
        self.assertIsNone(msg["env_ids"])
        self.assertIsNone(msg["mode"])
        self.assertIsNone(msg["opts"])

    def test_env_passes_through_as_eid(self):
        msg, _ = self.vis.update_hparams("hp1", env="run-x")
        self.assertEqual(msg["eid"], "run-x")

    def test_win_is_required(self):
        """The update targets an existing pane, so win cannot be omitted."""
        with self.assertRaises(ValueError):
            self.vis.update_hparams(None)
        with self.assertRaises(ValueError):
            self.vis.update_hparams("")

    def test_opts_are_validated_client_side(self):
        with self.assertRaises(AssertionError):
            self.vis.update_hparams("hp1", opts={"opacity": 5})


if __name__ == "__main__":
    unittest.main()
