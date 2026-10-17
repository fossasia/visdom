#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Removing a whole workspace, files and all.

The gateway calls this once a workspace's rows are gone for good. What matters
is that nothing is left behind: not the directory, not the state in memory that
an autosave would write straight back, and not a tab still open on it. And the
id it is given must never reach outside the workspaces directory.
"""

import json
import os
import tempfile
import unittest
import uuid

import pytest

from visdom.server.app import DROPPED_REASON, Application
from visdom.server.ownership import WS_POLICY_VIOLATION

pytestmark = pytest.mark.unit


class FakeSocket:
    def __init__(self):
        self.closed_with = None

    def close(self, code, reason):
        self.closed_with = (code, reason)


class TestDrop(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = Application(port=8098, env_path=self._tmp.name)
        self.addCleanup(self.app.shutdown_storage)
        self.manager = self.app.workspace_env_manager
        self.workspace = str(uuid.uuid4())
        self.directory = os.path.join(self._tmp.name, "workspaces", self.workspace)

    def write_env(self, eid, size=100):
        os.makedirs(self.directory, exist_ok=True)
        path = os.path.join(self.directory, "%s.json" % eid)
        with open(path, "w") as handle:
            json.dump({"jsons": {}, "reload": {}, "pad": "x" * size}, handle)
        return path

    def drop(self, workspace_id=None):
        answer, pending = self.app.drop_workspace(workspace_id or self.workspace)
        return answer, pending.result(timeout=5)

    def test_the_directory_and_everything_in_it_goes(self):
        self.write_env("main")
        self.write_env("run-1")
        os.makedirs(os.path.join(self.directory, "undo"))
        with open(os.path.join(self.directory, "undo", "run-1.json"), "w") as handle:
            handle.write("[]")

        answer, freed = self.drop()

        self.assertFalse(os.path.exists(self.directory))
        self.assertGreater(freed, 0)
        self.assertEqual(answer["workspace_id"], self.workspace)
        self.assertFalse(answer["loaded"])

    def test_a_loaded_workspace_is_forgotten_so_nothing_writes_it_back(self):
        space = self.manager.space(self.workspace, slug="alpha")
        self.assertTrue(os.path.isdir(self.directory))
        space.dirty_envs["main"] += 1

        answer, _freed = self.drop()

        self.assertTrue(answer["loaded"])
        self.assertIsNone(self.manager.loaded_space(self.workspace))
        self.assertNotIn(
            self.workspace, [wid for wid, _ in self.manager.workspace_spaces()]
        )
        self.app.flush_dirty()
        self.assertFalse(os.path.exists(self.directory))

    def test_open_tabs_and_writers_are_closed(self):
        space = self.manager.space(self.workspace, slug="alpha")
        viewer, writer = FakeSocket(), FakeSocket()
        space.subs["v1"] = viewer
        space.sources["w1"] = writer

        answer, _freed = self.drop()

        self.assertEqual(answer["closed"], 2)
        self.assertEqual(viewer.closed_with, (WS_POLICY_VIOLATION, DROPPED_REASON))
        self.assertEqual(writer.closed_with, (WS_POLICY_VIOLATION, DROPPED_REASON))

    def test_a_second_instance_finds_nothing_left(self):
        self.write_env("main")
        self.drop()

        answer, freed = self.drop()

        self.assertIsNone(freed)
        self.assertFalse(answer["loaded"])

    def test_other_workspaces_are_untouched(self):
        other = os.path.join(self._tmp.name, "workspaces", str(uuid.uuid4()))
        os.makedirs(other)
        kept = os.path.join(other, "main.json")
        with open(kept, "w") as handle:
            handle.write("{}")
        self.write_env("main")

        self.drop()

        self.assertTrue(os.path.exists(kept))

    def test_an_id_that_is_not_a_workspace_id_is_refused(self):
        for bad in ("../..", "..", "", None, "not-a-uuid", "/etc"):
            with self.assertRaises(ValueError):
                self.app.drop_workspace(bad)
        self.assertTrue(os.path.isdir(self._tmp.name))

    def test_the_id_is_matched_however_it_is_written(self):
        self.write_env("main")

        answer, freed = self.drop(self.workspace.upper())

        self.assertEqual(answer["workspace_id"], self.workspace)
        self.assertIsNotNone(freed)
        self.assertFalse(os.path.exists(self.directory))


if __name__ == "__main__":
    unittest.main()
