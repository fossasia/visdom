#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the hyper-parameter pane client method.

``Visdom.hparams`` is a thin wrapper: it validates ``opts`` like the other
plotting methods and posts the selection (``query``/``env_ids``/``mode``) to the
``experiments/hparams`` endpoint, which does the selecting, flattening and
window creation. These tests pin the request it builds with a mocked transport
(no server); the selection rules and flattening are tested against the endpoint
in ``test_experiment_hparams``.
"""

import unittest
from unittest.mock import Mock, patch

from visdom import Visdom


class TestHparamsClientMessage(unittest.TestCase):
    """Visdom.hparams posts the selection to the experiments/hparams endpoint.

    The transport is mocked to return the ``(msg, endpoint)`` it would have
    posted, so we can assert on it directly.
    """

    def setUp(self):
        with (
            patch.object(Visdom, "_handle_post", return_value=True),
            patch.object(Visdom, "_start_session_reaper"),
        ):
            self.vis = Visdom(raise_exceptions=True, use_incoming_socket=False)

        self.vis._send = Mock(
            side_effect=lambda msg, endpoint="events", **_: (msg, endpoint)
        )

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


if __name__ == "__main__":
    unittest.main()
