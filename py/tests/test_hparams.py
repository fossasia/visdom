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
window creation. These tests pin the request it builds against a captured
transport (no server); the selection rules and flattening are tested against
the endpoint in ``test_experiment_hparams``.
"""

import json
import unittest
from unittest.mock import Mock, patch

from visdom import Visdom


class CapturedTransport(unittest.TestCase):
    """A client whose transport is captured at ``_handle_post``.

    What is asserted on is the message the client would have put on the wire,
    so no server is involved.
    """

    def setUp(self):
        with (
            patch.object(Visdom, "_handle_post", return_value=True),
            patch.object(Visdom, "_start_session_reaper"),
        ):
            self.vis = Visdom(raise_exceptions=True, use_incoming_socket=False)

        self.posted = []
        self.vis._handle_post = Mock(side_effect=self._capture)

    def _capture(self, url, data=None):
        self.posted.append((url, json.loads(data)))
        return "{}"

    def sent(self):
        """The last message posted, as ``(msg, endpoint)``."""
        url, msg = self.posted[-1]
        prefix = "{}:{}{}/".format(self.vis.server, self.vis.port, self.vis.base_url)
        return msg, url[len(prefix) :]


class TestHparamsClientMessage(CapturedTransport):
    """Visdom.hparams posts the selection to the experiments/hparams endpoint."""

    def test_posts_to_hparams_endpoint(self):
        """The selection goes to the experiments/hparams endpoint."""
        self.vis.hparams("acc > 0.9")

        msg, endpoint = self.sent()
        self.assertEqual(endpoint, "experiments/hparams")
        self.assertEqual(msg["query"], "acc > 0.9")
        self.assertIsNone(msg["mode"])
        self.assertIsNone(msg["env_ids"])

    def test_env_ids_and_mode_pass_through(self):
        """env_ids and an explicit mode ride along untouched for the server."""
        self.vis.hparams(env_ids=["run-a", "run-b"], mode="env_ids")

        msg, _ = self.sent()
        self.assertEqual(msg["env_ids"], ["run-a", "run-b"])
        self.assertEqual(msg["mode"], "env_ids")

    def test_win_and_env_pass_through(self):
        """win/env target a specific pane like the other plotting methods."""
        self.vis.hparams("acc > 0.9", win="hp1", env="run-x")

        msg, _ = self.sent()
        self.assertEqual(msg["win"], "hp1")
        self.assertEqual(msg["eid"], "run-x")

    def test_opts_are_validated_client_side(self):
        """opts are asserted before the request, like the other methods."""
        with self.assertRaises(AssertionError):
            self.vis.hparams("acc > 0.9", opts={"opacity": 5})


class TestUpdateHparamsClientMessage(CapturedTransport):
    """Visdom.update_hparams posts to the experiments/hparams/update endpoint."""

    def test_posts_to_update_endpoint(self):
        """The target window and new selection go to the update endpoint."""
        self.vis.update_hparams("hp1", "acc > 0.9")

        msg, endpoint = self.sent()
        self.assertEqual(endpoint, "experiments/hparams/update")
        self.assertEqual(msg["win"], "hp1")
        self.assertEqual(msg["query"], "acc > 0.9")

    def test_bare_refresh_sends_only_the_window(self):
        """A bare refresh carries no selection for the server to replace."""
        self.vis.update_hparams("hp1")

        msg, _ = self.sent()
        self.assertIsNone(msg["query"])
        self.assertIsNone(msg["env_ids"])
        self.assertIsNone(msg["mode"])
        self.assertIsNone(msg["opts"])

    def test_env_passes_through_as_eid(self):
        self.vis.update_hparams("hp1", env="run-x")

        msg, _ = self.sent()
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
