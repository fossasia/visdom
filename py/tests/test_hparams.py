"""Tests for the hyper-parameter pane client method (Layer 3, PR A1).

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


class TestHparamsClientMessage(unittest.TestCase):
    """Visdom.hparams posts the selection to the experiments/hparams endpoint.

    The transport is captured at ``_handle_post``, so what is asserted on is
    the message the client would have put on the wire.
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


if __name__ == "__main__":
    unittest.main()
