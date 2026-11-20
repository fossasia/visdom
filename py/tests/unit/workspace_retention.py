#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Dropping the environments a workspace's plan no longer keeps.

The gateway decides the window and this end decides what has aged out of it.
Two things matter here: a dry run must touch nothing, since it is what gets
pointed at a deployment holding real work first, and a removal must not leave
the environment behind in memory, because the next autosave would write it
straight back to disk.
"""

import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import pytest

from visdom.server.app import Application
from visdom.utils.server_utils import purge_env as purge

pytestmark = pytest.mark.unit

DAY = 86400


class TestRetention(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = Application(port=8099, env_path=self._tmp.name)
        self.addCleanup(self.app.shutdown_storage)
        self.workspace = "ws-retention"
        self.directory = os.path.join(self._tmp.name, "workspaces", self.workspace)
        os.makedirs(self.directory, exist_ok=True)

    def write_env(self, eid, days_old):
        path = os.path.join(self.directory, "%s.json" % eid)
        with open(path, "w") as handle:
            json.dump({"jsons": {}, "reload": {}}, handle)
        when = time.time() - (days_old * DAY)
        os.utime(path, (when, when))
        return path

    def files(self):
        return sorted(os.listdir(self.directory))

    def settle(self, path, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not os.path.exists(path):
                return True
            time.sleep(0.05)
        return not os.path.exists(path)

    def test_a_dry_run_names_what_would_go_and_removes_nothing(self):
        old = self.write_env("january", days_old=30)
        self.write_env("yesterday", days_old=1)

        answer = self.app.retire_workspace(self.workspace, 7, dry_run=True)

        self.assertEqual(answer["envs"], ["january"])
        self.assertEqual(answer["removed"], 0)
        self.assertTrue(answer["dry_run"])
        self.assertTrue(os.path.exists(old))
        self.assertEqual(self.files(), ["january.json", "yesterday.json"])

    def test_only_what_is_past_the_window_is_removed(self):
        old = self.write_env("january", days_old=30)
        self.write_env("yesterday", days_old=1)

        answer = self.app.retire_workspace(self.workspace, 7, dry_run=False)

        self.assertEqual(answer["removed"], 1)
        self.assertTrue(self.settle(old))
        self.assertEqual(self.files(), ["yesterday.json"])

    def test_a_long_environment_name_is_reported_by_its_real_id(self):
        eid = "run-" + "x" * 300
        path = os.path.join(self.directory, "hash_%s.json" % ("a" * 64))
        with open(path, "w") as handle:
            json.dump({"jsons": {}, "reload": {}, "name": eid}, handle)
        when = time.time() - (30 * DAY)
        os.utime(path, (when, when))

        answer = self.app.retire_workspace(self.workspace, 7, dry_run=True)

        self.assertEqual(answer["envs"], [eid])

    def test_an_env_with_unsaved_writes_is_kept(self):
        path = self.write_env("january", days_old=30)
        space = self.app.workspace_env_manager.space(self.workspace)
        space.state["january"] = {"jsons": {}, "reload": {}}
        space.dirty_envs["january"] += 1

        answer = self.app.retire_workspace(self.workspace, 7, dry_run=False)

        self.assertEqual(answer["envs"], [])
        self.assertEqual(answer["removed"], 0)
        self.assertIn("january", space.state)
        self.assertTrue(os.path.exists(path))

    def test_main_is_kept_however_old_it_is(self):
        main = self.write_env("main", days_old=400)

        answer = self.app.retire_workspace(self.workspace, 7, dry_run=False)

        self.assertEqual(answer["envs"], [])
        self.assertTrue(os.path.exists(main))

    def test_a_removed_env_does_not_come_back_from_memory(self):
        """The failure this guards: deleting the file while the env is still in
        state, so the next autosave writes it out again."""
        old = self.write_env("january", days_old=30)
        space = self.app.workspace_env_manager.space(self.workspace, slug="ws")
        space.state["january"] = {"jsons": {}, "reload": {}}

        self.app.retire_workspace(self.workspace, 7, dry_run=False)

        self.assertNotIn("january", space.state)
        self.assertTrue(self.settle(old))

    def test_the_answer_says_whether_this_instance_holds_the_workspace(self):
        """Instances share a disk, so the caller has to sweep from the holder."""
        self.write_env("january", days_old=30)

        cold = self.app.retire_workspace(self.workspace, 7, dry_run=True)
        self.assertFalse(cold["loaded"])

        self.app.workspace_env_manager.space(self.workspace, slug="ws")
        warm = self.app.retire_workspace(self.workspace, 7, dry_run=True)
        self.assertTrue(warm["loaded"])

    def retire_off_loop(self, dry_run=False):
        manager = self.app.workspace_env_manager
        scanned_on = []
        scan = manager.expired_envs

        def expired_envs(*args):
            scanned_on.append(threading.current_thread().name)
            return scan(*args)

        manager.expired_envs = expired_envs
        answer = asyncio.run(
            self.app.retire_workspace_off_loop(self.workspace, 7, dry_run=dry_run)
        )
        return answer, scanned_on

    def test_the_endpoint_scans_the_disk_off_the_loop(self):
        self.write_env("january", days_old=30)

        answer, scanned_on = self.retire_off_loop(dry_run=True)

        self.assertEqual(answer["envs"], ["january"])
        self.assertEqual(len(scanned_on), 1)
        self.assertNotEqual(scanned_on[0], threading.current_thread().name)

    def test_the_endpoint_removes_a_dormant_workspaces_files_off_the_loop(self):
        old = self.write_env("january", days_old=30)
        self.write_env("yesterday", days_old=1)

        answer, _ = self.retire_off_loop()

        self.assertEqual(answer["removed"], 1)
        self.assertFalse(answer["loaded"])
        self.assertEqual(self.files(), ["yesterday.json"])
        self.assertFalse(os.path.exists(old))

    def test_the_endpoint_removes_a_loaded_env_from_memory_too(self):
        old = self.write_env("january", days_old=30)
        space = self.app.workspace_env_manager.space(self.workspace, slug="ws")
        space.state["january"] = {"jsons": {}, "reload": {}}

        answer, _ = self.retire_off_loop()

        self.assertEqual(answer["removed"], 1)
        self.assertNotIn("january", space.state)
        self.assertTrue(self.settle(old))

    def load_during_purge(self, touch=None):
        manager = self.app.workspace_env_manager
        loaded = {}

        def purge_env(storage, eid):
            if not loaded:
                loaded["first"] = eid
                space = manager.space(self.workspace, slug="ws")
                if touch is not None:
                    space.state[eid] = touch
            purge(storage, eid)

        with mock.patch("visdom.server.app.purge_env", purge_env):
            answer, _ = self.retire_off_loop()
        return answer, loaded["first"], manager.loaded_space(self.workspace)

    def test_a_load_during_the_purge_stops_it(self):
        self.write_env("january", days_old=30)
        self.write_env("february", days_old=30)

        answer, first, _ = self.load_during_purge()

        self.assertEqual(answer["removed"], 1)
        self.assertNotIn("%s.json" % first, self.files())
        self.assertEqual(len([f for f in self.files() if f != "main.json"]), 1)

    def test_an_env_written_after_a_late_load_is_kept_and_saved_again(self):
        self.write_env("january", days_old=30)
        fresh = {"jsons": {"w": {}}, "reload": {}}

        _, first, space = self.load_during_purge(touch=fresh)

        self.assertIs(space.state[first], fresh)
        self.assertTrue(space.dirty_envs[first])

    def test_an_untouched_env_left_by_a_late_load_is_dropped(self):
        self.write_env("january", days_old=30)

        _, first, space = self.load_during_purge()

        self.assertNotIn(first, space.state)
        self.assertFalse(space.dirty_envs.get(first))

    def test_a_workspace_with_no_directory_is_not_an_error(self):
        answer = self.app.retire_workspace("never-seen", 7, dry_run=False)
        self.assertEqual(answer["envs"], [])
        self.assertEqual(answer["removed"], 0)

    def test_a_workspace_id_cannot_reach_outside_the_workspaces_folder(self):
        outside = os.path.join(self._tmp.name, "outside")
        os.makedirs(outside)
        stray = os.path.join(outside, "january.json")
        with open(stray, "w") as handle:
            json.dump({"jsons": {}, "reload": {}}, handle)
        when = time.time() - (30 * DAY)
        os.utime(stray, (when, when))

        for workspace_id in ["../outside", "..", "a/b", ""]:
            with self.subTest(workspace_id=workspace_id):
                with self.assertRaises(ValueError):
                    self.app.retire_workspace(workspace_id, 7, dry_run=False)
        self.assertTrue(os.path.exists(stray))

    def test_no_window_means_keep_everything(self):
        """An unlimited plan passes no window, and nothing should age out."""
        old = self.write_env("january", days_old=400)

        answer = self.app.retire_workspace(self.workspace, None, dry_run=False)

        self.assertEqual(answer["envs"], [])
        self.assertTrue(os.path.exists(old))
