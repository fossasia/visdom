#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""What a subscribed browser actually receives when a pane is updated.

``js/main.js`` applies an incremental ``window_update`` only when its
``version`` is exactly one ahead of the pane the client already holds, and
falls back to re-querying the entire environment otherwise. That makes the
version sequence a wire contract, not an internal counter, so it is asserted
here off a real subscriber socket rather than off the server's own state.

The unit file ``py/tests/unit/pane_versioning.py`` pins the same rule at the
handler; this one exists because the two halves of it -- the version the
server keeps and the version it announces -- used to be able to disagree, and
only the announced one is what the frontend gates on.
"""

import unittest

import pytest

from testutils import open_sub, sent
from testutils.http import VisdomHTTPTestCase
from testutils.payloads import content_args

pytestmark = pytest.mark.integration


class BroadcastTestCase(VisdomHTTPTestCase):
    """Attaches a subscriber to ``main`` and reads the versions it is sent."""

    def subscribe(self, eid="main"):
        sub = open_sub(self._app)
        sub.eid = eid
        return sub

    def update_versions(self, sub, win):
        """Versions of the ``window_update`` packets broadcast for ``win``."""
        return [
            msg["version"]
            for msg in sent(sub)
            if isinstance(msg, dict)
            and msg.get("command") == "window_update"
            and msg.get("win") == win
        ]

    def assert_updates_are_consecutive(self, sub, win, count=3):
        """The client starts at 1, so the run has to be 2, 3, ... with no gaps.

        A repeated or stalled version is the failure this guards: it makes the
        frontend drop the patch and reload the whole environment instead.
        """
        self.assertEqual(
            self.update_versions(sub, win), list(range(2, 2 + count)), self.panes()
        )


class TestContentPaneBroadcasts(BroadcastTestCase):
    """Panes that carry content rather than traces.

    Each of these returns from ``UpdateHandler.update`` before the plot code
    runs, which is how they came to be excluded from the version bump.
    """

    def test_text_updates_announce_consecutive_versions(self):
        sub = self.subscribe()
        win = self.create_text_window(content="line0")
        for line in ("line1", "line2", "line3"):
            self.update(win, [{"type": "text", "content": line}])
        self.assert_updates_are_consecutive(sub, win)

    def test_image_history_appends_announce_consecutive_versions(self):
        sub = self.subscribe()
        args = content_args(
            "image_history",
            {"src": "data:image/png;base64,AAA", "caption": "c0"},
        )
        win = self.create_window(args["data"], layout=args["layout"])
        for caption in ("c1", "c2", "c3"):
            self.update(
                win,
                [
                    {
                        "type": "image_history",
                        "content": {
                            "src": "data:image/png;base64,{}".format(caption),
                            "caption": caption,
                        },
                    }
                ],
            )
        self.assert_updates_are_consecutive(sub, win)

    def test_plot_history_appends_announce_consecutive_versions(self):
        sub = self.subscribe()
        args = content_args(
            "plot_history", {"data": [], "layout": {}, "caption": "frame0"}
        )
        win = self.create_window(args["data"], layout=args["layout"])
        for i in (1, 2, 3):
            self.update(
                win,
                [
                    {
                        "type": "plot_history",
                        "content": {
                            "data": [{"type": "scatter", "x": [i], "y": [i]}],
                            "layout": {},
                            "caption": "frame{}".format(i),
                        },
                    }
                ],
            )
        self.assert_updates_are_consecutive(sub, win)


class TestEmbeddingsBroadcasts(BroadcastTestCase):
    """Embeddings build their patch by hand, bypassing ``update_packet``."""

    def create_embeddings(self):
        args = content_args(
            "embeddings",
            {"data": [[1, 2], [3, 4]], "labels": ["a", "b"], "selected": None},
        )
        return self.create_window(args["data"], layout=args["layout"])

    def test_selections_announce_consecutive_versions(self):
        sub = self.subscribe()
        win = self.create_embeddings()
        self.update(win, {"update_type": "EntitySelected", "selected": 1})
        self.update(win, {"update_type": "RegionSelected", "points": [[5, 6]]})
        self.update(win, {"update_type": "EntitySelected", "selected": 0})
        self.assert_updates_are_consecutive(sub, win)

    def test_the_patch_moves_the_client_to_the_announced_version(self):
        """The packet's ``version`` is useless unless the patch installs it."""
        sub = self.subscribe()
        win = self.create_embeddings()
        self.update(win, {"update_type": "EntitySelected", "selected": 1})
        packet = [
            msg
            for msg in sent(sub)
            if isinstance(msg, dict) and msg.get("command") == "window_update"
        ][-1]
        self.assertIn(
            {"op": "replace", "path": "/version", "value": packet["version"]},
            packet["content"],
        )


class TestPlotBroadcasts(BroadcastTestCase):
    """The one pane type that already worked, kept honest."""

    def test_trace_appends_announce_consecutive_versions(self):
        sub = self.subscribe()
        win = self.create_window(
            [{"type": "scatter", "x": [1], "y": [1], "name": "t1"}]
        )
        for i in (2, 3, 4):
            self.update(
                win,
                [{"type": "scatter", "x": [i], "y": [i], "name": "t1"}],
                name="t1",
                append=True,
            )
        self.assert_updates_are_consecutive(sub, win)


if __name__ == "__main__":
    unittest.main()
