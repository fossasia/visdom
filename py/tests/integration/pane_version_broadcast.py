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
        """Versions ``win`` was announced at, in the order they were sent.

        An update reaches the browser as whichever of the patch and the whole
        pane is smaller, so both encodings count. ``main.js`` takes the
        version from either -- a ``window`` packet replaces the pane it names
        and carries its version forward -- and it is the sequence across the
        two that has to have no gaps, not the sequence within one of them.
        """
        versions = []
        for msg in sent(sub):
            if not isinstance(msg, dict):
                continue
            if msg.get("command") == "window_update" and msg.get("win") == win:
                versions.append(msg["version"])
            elif msg.get("command") == "window" and msg.get("id") == win:
                versions.append(msg["version"])
        return versions

    def assert_updates_are_consecutive(self, sub, win, count=3):
        """The run has to be 1, 2, ... with no gaps.

        The subscriber is attached before the pane is created, so the packet
        that creates it opens the run at 1 and the updates continue it. A
        repeated or stalled version is the failure this guards: it makes the
        frontend drop the patch and reload the whole environment instead.
        """
        self.assertEqual(
            self.update_versions(sub, win), list(range(1, 2 + count)), self.panes()
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
        # "replace" lands even on a pane saved before panes carried a version:
        # main.js applies the patch with validation off, so the member is set.
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


class TestRejectedUpdates(BroadcastTestCase):
    """An update the server declines announces nothing.

    A ``window_update`` whose version the client already holds fails the same
    "exactly one ahead" check a stale one does, so a refusal that broadcast --
    or that bumped without having changed anything -- sent the browser back for
    the entire environment.
    """

    def update_packets(self, sub, win):
        return [
            msg
            for msg in sent(sub)
            if isinstance(msg, dict)
            and msg.get("command") == "window_update"
            and msg.get("win") == win
        ]

    def test_a_table_update_is_not_broadcast(self):
        """``/update`` on a table is ignored; ``vis.table()`` replaces it."""
        sub = self.subscribe()
        args = content_args("table", [["a"]])
        win = self.create_window(args["data"], layout=args["layout"])

        self.update(win, [{"type": "table", "content": [["b"]]}])

        self.assertEqual(self.update_packets(sub, win), [])
        self.assertEqual(self.panes()[win]["version"], 1)

    def test_an_unknown_embeddings_update_is_not_broadcast(self):
        sub = self.subscribe()
        args = content_args(
            "embeddings",
            {"data": [[1, 2], [3, 4]], "labels": ["a", "b"], "selected": None},
        )
        win = self.create_window(args["data"], layout=args["layout"])

        self.update(win, {"update_type": "Nonsense"})

        self.assertEqual(self.update_packets(sub, win), [])
        self.assertEqual(self.panes()[win]["version"], 1)

    def test_a_refusal_leaves_no_gap_in_the_announced_versions(self):
        sub = self.subscribe()
        args = content_args(
            "embeddings",
            {"data": [[1, 2], [3, 4]], "labels": ["a", "b"], "selected": None},
        )
        win = self.create_window(args["data"], layout=args["layout"])

        self.update(win, {"update_type": "EntitySelected", "selected": 1})
        self.update(win, {"update_type": "Nonsense"})
        self.update(win, {"update_type": "RegionSelected", "points": [[5, 6]]})

        self.assertEqual(self.update_versions(sub, win), [1, 2, 3], self.panes())


if __name__ == "__main__":
    unittest.main()
