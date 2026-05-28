#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from visdom.utils.server_utils import atomic_write_json, serialize_env, LazyEnvData


class TestAtomicWriteJson(unittest.TestCase):
    def test_writes_correct_data(self):
        with tempfile.TemporaryDirectory() as env_path:
            path = os.path.join(env_path, "env.json")
            atomic_write_json(path, {"jsons": {}, "reload": {}})
            with open(path) as fn:
                self.assertEqual(json.load(fn), {"jsons": {}, "reload": {}})

    def test_no_tmp_file_left_after_success(self):
        with tempfile.TemporaryDirectory() as env_path:
            path = os.path.join(env_path, "env.json")
            atomic_write_json(path, {"jsons": {}, "reload": {}})
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_existing_file_preserved_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as env_path:
            path = os.path.join(env_path, "env.json")
            atomic_write_json(path, {"original": True})

            with patch("visdom.utils.server_utils.os.replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    atomic_write_json(path, {"replacement": True})

            with open(path) as fn:
                self.assertEqual(json.load(fn), {"original": True})

    def test_tmp_file_cleaned_up_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as env_path:
            path = os.path.join(env_path, "env.json")
            atomic_write_json(path, {"original": True})

            with patch("visdom.utils.server_utils.os.replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    atomic_write_json(path, {"replacement": True})

            self.assertFalse(os.path.exists(path + ".tmp"))


class TestSerializeEnv(unittest.TestCase):
    def _make_state(self):
        return {
            "main": {
                "jsons": {"win1": {"id": "win1", "type": "text", "content": "hello"}},
                "reload": {"win1": {"x": 0, "y": 0}},
            }
        }

    def test_keeps_legacy_json_format(self):
        state = self._make_state()
        with tempfile.TemporaryDirectory() as env_path:
            saved = serialize_env(state, ["main"], env_path=env_path)

            self.assertEqual(saved, ["main"])
            with open(os.path.join(env_path, "main.json")) as fn:
                on_disk = json.load(fn)
            self.assertEqual(on_disk, state["main"])

    def test_skips_unloaded_lazy_env(self):
        with tempfile.TemporaryDirectory() as env_path:
            env_file = os.path.join(env_path, "main.json")
            with open(env_file, "w") as fn:
                fn.write(json.dumps({"jsons": {}, "reload": {}}))

            state = {"main": LazyEnvData(env_file)}
            # LazyEnvData that has never been loaded should be skipped
            saved = serialize_env(state, ["main"], env_path=env_path)
            self.assertEqual(saved, ["main"])

    def test_writes_atomically(self):
        """serialize_env must not leave a .tmp file behind on success."""
        state = self._make_state()
        with tempfile.TemporaryDirectory() as env_path:
            serialize_env(state, ["main"], env_path=env_path)
            self.assertFalse(
                os.path.exists(os.path.join(env_path, "main.json.tmp"))
            )

    def test_tmp_file_on_disk_does_not_prevent_normal_load(self):
        """A leftover .tmp file from a previous crash must not shadow the good env."""
        state = self._make_state()
        with tempfile.TemporaryDirectory() as env_path:
            serialize_env(state, ["main"], env_path=env_path)

            # Simulate a .tmp file left by a previous interrupted write
            tmp_path = os.path.join(env_path, "main.json.tmp")
            with open(tmp_path, "w") as fn:
                fn.write('{"jsons": "corrupt"}')

            env_file = os.path.join(env_path, "main.json")
            with open(env_file) as fn:
                recovered = json.load(fn)
            self.assertEqual(recovered, state["main"])

    def test_only_requested_envs_are_saved(self):
        state = {
            "main": {"jsons": {}, "reload": {}},
            "other": {"jsons": {}, "reload": {}},
        }
        with tempfile.TemporaryDirectory() as env_path:
            saved = serialize_env(state, ["main"], env_path=env_path)

            self.assertIn("main", saved)
            self.assertNotIn("other", saved)
            self.assertTrue(os.path.exists(os.path.join(env_path, "main.json")))
            self.assertFalse(os.path.exists(os.path.join(env_path, "other.json")))


class TestAutosaveInterval(unittest.TestCase):
    def test_start_server_accepts_autosave_interval_kwarg(self):
        """start_server signature must accept autosave_interval without error."""
        import inspect
        from visdom.server.run_server import start_server

        params = inspect.signature(start_server).parameters
        self.assertIn("autosave_interval", params)
        self.assertEqual(params["autosave_interval"].default, 0)


if __name__ == "__main__":
    unittest.main()
