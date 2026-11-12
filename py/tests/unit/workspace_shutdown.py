#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The final save on the way down, across every workspace.

The graceful stop saves once and the ``atexit`` hook asks again. A pass that
failed must be run again by that second call, or a workspace's last changes
stay in memory and go with the process; a pass that succeeded must not be.
"""

import tempfile
import unittest

import pytest

from visdom.server.app import Application

pytestmark = pytest.mark.unit


class TestWorkspaceShutdown(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = Application(port=8096, env_path=self._tmp.name)
        self.space = self.app.workspace_env_manager.space("ws-a")
        self.saves = []

    def flaky(self, fail_first):
        def save_all(state):
            self.saves.append(state)
            if fail_first and len(self.saves) == 1:
                raise OSError("disk full")

        self.space.storage.save_all = save_all

    def test_a_failed_workspace_save_is_retried_by_the_next_shutdown(self):
        self.flaky(fail_first=True)

        with self.assertRaises(OSError):
            self.app.shutdown_storage()
        self.app.shutdown_storage()

        self.assertEqual(len(self.saves), 2)

    def test_a_shutdown_that_worked_is_not_run_again(self):
        self.flaky(fail_first=False)

        self.app.shutdown_storage()
        self.app.shutdown_storage()

        self.assertEqual(len(self.saves), 1)

    def test_one_workspace_failing_does_not_stop_the_others_saving(self):
        self.flaky(fail_first=True)
        self.space.dirty_envs["main"] = 1
        other = self.app.workspace_env_manager.space("ws-b")
        other.dirty_envs["main"] = 1
        other_saves = []
        other.storage.save_all = other_saves.append

        with self.assertRaises(OSError):
            self.app.shutdown_storage()

        self.assertEqual(len(other_saves), 1)
        self.assertFalse(other.dirty_envs)
        self.assertIn("main", self.space.dirty_envs)

    def test_a_failed_server_save_still_saves_every_workspace(self):
        self.flaky(fail_first=False)

        def broken_save_all(state):
            raise OSError("disk full")

        self.app.server_state.storage.save_all = broken_save_all

        with self.assertRaises(OSError):
            self.app.shutdown_storage()

        self.assertEqual(len(self.saves), 1)


if __name__ == "__main__":
    unittest.main()
