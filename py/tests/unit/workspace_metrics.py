#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""What a scrape of one instance says about its workspaces."""

import tempfile
import types
import unittest

from visdom.server import metrics
from visdom.server.app import Application
from visdom.utils.server_utils import broadcast


class TestRendering(unittest.TestCase):
    """The exposition format, which a scraper will reject if it is wrong."""

    def test_a_family_is_declared_once_and_then_valued(self):
        text = metrics.render(
            [
                {
                    "workspace_id": "a",
                    "slug": "one",
                    "visdom_workspace_writes_total": 3,
                },
                {
                    "workspace_id": "b",
                    "slug": "two",
                    "visdom_workspace_writes_total": 5,
                },
            ]
        )
        lines = text.strip().split("\n")

        self.assertEqual(lines.count("# TYPE visdom_workspace_writes_total counter"), 1)
        self.assertIn(
            'visdom_workspace_writes_total{workspace="a",slug="one"} 3', lines
        )
        self.assertIn(
            'visdom_workspace_writes_total{workspace="b",slug="two"} 5', lines
        )

    def test_a_missing_value_is_left_out_rather_than_called_zero(self):
        """A size nobody measured and a size of zero are different answers."""
        text = metrics.render([{"workspace_id": "a", "slug": "one"}])

        self.assertIn("# TYPE visdom_workspace_stored_bytes gauge", text)
        self.assertNotIn("visdom_workspace_stored_bytes{", text)

    def test_a_slug_cannot_break_out_of_its_label(self):
        """Slugs come from whoever made the workspace, not from this server."""
        text = metrics.render(
            [
                {
                    "workspace_id": "a",
                    "slug": 'evil"} malicious{x="',
                    "visdom_workspace_writes_total": 1,
                }
            ]
        )
        value = [
            line
            for line in text.split("\n")
            if line.startswith("visdom_workspace_writes_total{")
        ]

        self.assertEqual(len(value), 1)
        # The injected text survives inside the label, which is fine. What must
        # not survive is its quote, since an unescaped one would close the label
        # early and turn the rest into a second metric.
        self.assertIn('slug="evil\\"}', value[0])
        self.assertTrue(value[0].endswith("} 1"))

    def test_every_family_is_declared_even_with_nothing_to_report(self):
        text = metrics.render([])

        for name, _kind, _help in metrics._FAMILIES:
            self.assertIn(f"# TYPE {name} ", text)


class TestCounting(unittest.TestCase):
    """The numbers themselves, counted where the work happens."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = Application(port=8097, env_path=self._tmp.name)
        self.addCleanup(self.app.shutdown_storage)

    def space(self, workspace_id):
        return self.app.workspace_env_manager.space(workspace_id)

    def test_a_write_is_attributed_to_the_workspace_that_made_it(self):
        self.space("ws-a").mark_dirty("main")
        self.space("ws-a").mark_dirty("main")
        self.space("ws-b").mark_dirty("main")

        self.assertEqual(self.space("ws-a").activity()["writes"], 2)
        self.assertEqual(self.space("ws-b").activity()["writes"], 1)

    def test_a_broadcast_counts_once_per_viewer_it_reached(self):
        """It is work the instance did, and with three viewers it did it three
        times."""
        space = self.space("ws-a")
        handler = types.SimpleNamespace(server_state=space, subs=space.subs)
        for name in ("one", "two", "three"):
            space.subs[name] = types.SimpleNamespace(
                eid="main", write_message=lambda msg: None
            )

        broadcast(handler, "12345", "main")

        activity = space.activity()
        self.assertEqual(activity["broadcasts"], 3)
        self.assertEqual(activity["broadcast_bytes"], 15)

    def test_a_broadcast_nobody_is_watching_counts_nothing(self):
        space = self.space("ws-a")
        handler = types.SimpleNamespace(server_state=space, subs=space.subs)
        space.subs["elsewhere"] = types.SimpleNamespace(
            eid="another", write_message=lambda msg: None
        )

        broadcast(handler, "12345", "main")

        self.assertEqual(space.activity()["broadcasts"], 0)

    def test_broadcasting_without_a_workspace_state_still_delivers(self):
        """The same path serves a plain single-tenant server, where there is no
        workspace to attribute anything to."""
        delivered = []
        handler = types.SimpleNamespace(
            subs={
                "one": types.SimpleNamespace(eid="main", write_message=delivered.append)
            }
        )

        broadcast(handler, "hello", "main")

        self.assertEqual(delivered, ["hello"])

    def test_a_scrape_reports_every_workspace_the_instance_holds(self):
        for workspace in ("ws-a", "ws-b"):
            self.space(workspace).mark_dirty("main")

        from visdom.server.handlers.web_handlers import ActivityHandler

        handler = types.SimpleNamespace(_manager=self.app.workspace_env_manager)
        gathered = ActivityHandler.gather(handler)
        text = metrics.render([metrics.sample_from_activity(e) for e in gathered])

        self.assertEqual(text.count("visdom_workspace_writes_total{"), 2)
        self.assertIn("visdom_workspace_stored_bytes{", text)


if __name__ == "__main__":
    unittest.main()


class TestWorkspacesOnlyOnDisk(unittest.TestCase):
    """A workspace nobody has touched since the instance started.

    The common case just after a restart, and the one the counters were
    invisible in: every workspace came back from the disk pass alone, which
    carried no counters, so the console reported them all as unavailable.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = Application(port=8097, env_path=self._tmp.name)
        self.addCleanup(self.app.shutdown_storage)

    def gather(self):
        from visdom.server.handlers.web_handlers import ActivityHandler

        return ActivityHandler.gather(
            types.SimpleNamespace(_manager=self.app.workspace_env_manager)
        )

    def stored_only(self):
        """One workspace written to disk, then forgotten, as a restart would."""
        space = self.app.workspace_env_manager.space("ws-a", slug="a")
        space.state["expt"] = {"jsons": {}, "reload": {}}
        space.mark_dirty("expt")
        space.flush_dirty()
        # Drop the in-memory state, leaving only what is on disk, which is what
        # a restarted instance sees. The disk scan is lazy and has not run yet,
        # so nothing has to be invalidated.
        self.app.workspace_env_manager._states.pop("ws-a")

    def test_an_untouched_workspace_reports_no_work_rather_than_no_answer(self):
        self.stored_only()

        entry = next(e for e in self.gather() if e["workspace_id"] == "ws-a")

        self.assertEqual(entry["writes"], 0)
        self.assertEqual(entry["broadcasts"], 0)
        self.assertEqual(entry["broadcast_bytes"], 0)

    def test_a_scrape_gives_it_a_value_too(self):
        self.stored_only()

        text = metrics.render([metrics.sample_from_activity(e) for e in self.gather()])

        self.assertIn('visdom_workspace_writes_total{workspace="ws-a",slug=""} 0', text)

    def test_a_workspace_still_held_keeps_its_real_count(self):
        """The disk pass must not overwrite what the socket pass counted."""
        space = self.app.workspace_env_manager.space("ws-b", slug="b")
        space.state["expt"] = {"jsons": {}, "reload": {}}
        for _ in range(4):
            space.mark_dirty("expt")
        space.flush_dirty()

        entry = next(e for e in self.gather() if e["workspace_id"] == "ws-b")

        self.assertEqual(entry["writes"], 4)
