#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Environment lifecycle over real HTTP: create, fork, save, delete, reload.

An environment is never created explicitly -- it appears the moment a pane is
addressed to it. From there ``/fork_env`` deep-copies it, ``/save`` writes it
through the storage backend, ``/delete_env`` removes both the state and the
file, and a fresh ``Application`` over the same directory picks it back up.
That the writes go through the backend rather than around it is asserted
separately in ``storage_wiring``.
"""

import json
import os
import unittest

import pytest

from visdom.server import app as app_module
from visdom.server.app import Application

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


class TestStartupState(VisdomHTTPTestCase):
    def test_main_env_exists_and_is_empty_on_startup(self):
        self.assertIn("main", self.get_envs())
        self.assertEqual(self.get_win_data(), {})

    def test_env_state_returns_a_list(self):
        self.assertIsInstance(self.get_envs(), list)


class TestImplicitCreation(VisdomHTTPTestCase):
    def test_addressing_an_unknown_env_creates_it(self):
        self.create_text_window(eid="new_env", content="hello")
        self.assertIn("new_env", self.get_envs())

    def test_env_state_lists_every_env_created(self):
        self.create_text_window(eid="x_env")
        self.create_text_window(eid="y_env")
        self.assertTrue({"main", "x_env", "y_env"} <= set(self.get_envs()))


class TestForkEnv(VisdomHTTPTestCase):
    def test_fork_copies_the_panes_across(self):
        self.create_text_window(eid="main", content="original", win="w1")
        resp = self.post_json("/fork_env", {"prev_eid": "main", "eid": "fork1"})
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body.decode(), "fork1")
        self.assertEqual(self.get_win_data("w1", eid="fork1")["content"], "original")

    def test_fork_is_independent_of_its_source(self):
        self.create_text_window(eid="main", content="original", win="w1")
        self.post_json("/fork_env", {"prev_eid": "main", "eid": "fork2"})

        self.update("w1", [{"content": "modified"}], eid="fork2")

        self.assertEqual(self.get_win_data("w1", eid="main")["content"], "original")

    def test_forking_an_unknown_env_is_a_bad_request(self):
        resp = self.post_json("/fork_env", {"prev_eid": "no_exist", "eid": "new"})
        self.assertEqual(resp.code, 400)
        self.assertIn("env to be forked doesn't exist", resp.reason)
        self.assertNotIn("new", self.get_envs())


class TestSaveEnv(VisdomHTTPTestCase):
    def test_save_writes_a_file_named_for_the_env(self):
        self.create_text_window(eid="main", content="save me")
        self.save(["main"])
        self.assertTrue(os.path.exists(os.path.join(self.env_path, "main.json")))

    def test_saved_file_carries_jsons_and_reload(self):
        self.create_text_window(eid="main", content="save me")
        self.save(["main"])
        with open(os.path.join(self.env_path, "main.json")) as handle:
            saved = json.load(handle)
        self.assertIn("jsons", saved)
        self.assertIn("reload", saved)

    def test_save_handles_several_envs_at_once(self):
        self.create_text_window(eid="env_a", content="a")
        self.create_text_window(eid="env_b", content="b")
        self.save(["env_a", "env_b"])
        for eid in ("env_a", "env_b"):
            self.assertTrue(os.path.exists(os.path.join(self.env_path, eid + ".json")))

    def test_save_reports_only_the_envs_that_existed(self):
        self.create_text_window(eid="main", content="x")
        saved = json.loads(self.save(["main", "nonexistent"]).body)
        self.assertIn("main", saved)
        self.assertNotIn("nonexistent", saved)


class TestDeleteEnv(VisdomHTTPTestCase):
    def test_delete_removes_the_env_from_state(self):
        self.create_text_window(eid="del_me", content="bye")
        self.post_json("/delete_env", {"eid": "del_me"})
        self.assertNotIn("del_me", self.get_envs())

    def test_delete_removes_the_saved_file_too(self):
        self.create_text_window(eid="del_file", content="bye")
        self.save(["del_file"])
        path = os.path.join(self.env_path, "del_file.json")
        self.assertTrue(os.path.exists(path))

        self.post_json("/delete_env", {"eid": "del_file"})

        self.assertFalse(os.path.exists(path))

    def test_main_env_cannot_be_deleted(self):
        self.post_json("/delete_env", {"eid": "main"})
        self.assertIn("main", self.get_envs())


class TestReload(VisdomHTTPTestCase):
    def test_a_saved_env_is_reloaded_by_a_fresh_application(self):
        self.create_text_window(eid="persist", content="I survive", win="w1")
        self.save(["persist"])

        restarted = Application(port=8097, env_path=self.env_path)

        self.assertIn("persist", restarted.state)
        self.assertEqual(
            restarted.state["persist"]["jsons"]["w1"]["content"], "I survive"
        )


class TestApplicationSettings(VisdomHTTPTestCase):
    def test_building_an_application_leaves_the_settings_template_alone(self):
        """``__init__`` used to write derived values back into the module dict,
        so a second server inherited the first one's cookie secret."""
        before = dict(app_module.tornado_settings)

        built = Application(port=8097, env_path=self.env_path, base_url="/sub")

        self.assertEqual(app_module.tornado_settings, before)
        self.assertEqual(built.settings["static_url_prefix"], "/sub/static/")


if __name__ == "__main__":
    unittest.main()
