import os
import sys
import time
import json
import shutil
import tempfile
import threading
import subprocess
import unittest
from visdom import Visdom


class TestIntegrationTags(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.port = 8098  # Use a different port than default

        # Start visdom server in a background process with correct PYTHONPATH
        env = os.environ.copy()
        env["PYTHONPATH"] = "py"
        self.server_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "visdom.server",
                "-env_path",
                self.test_dir,
                "-port",
                str(self.port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        time.sleep(3)  # Wait for server to start
        self.viz = Visdom(port=self.port)

    def tearDown(self):
        self.server_process.terminate()
        stdout, stderr = self.server_process.communicate()
        print("--- SERVER STDOUT ---")
        print(stdout.decode(errors="replace"))
        print("--- SERVER STDERR ---")
        print(stderr.decode(errors="replace"))
        shutil.rmtree(self.test_dir)

    def test_set_get_tags(self):
        env = "test_env"
        tags = ["tag_a", "tag_b"]

        # 1. Set tags (returns decoded list)
        res = self.viz.set_tags(tags, env=env)
        self.assertCountEqual(res, tags)

        # 2. Get tags (returns decoded list)
        get_res = self.viz.get_tags(env=env)
        self.assertCountEqual(get_res, tags)

        # 3. Append tags
        append_tags = ["tag_c"]
        res_append = self.viz.set_tags(append_tags, env=env, append=True)
        self.assertCountEqual(res_append, ["tag_a", "tag_b", "tag_c"])

        # 4. Check disk persistence
        index_path = os.path.join(self.test_dir, "tags_index.json")
        self.assertTrue(os.path.exists(index_path))
        with open(index_path, "r") as f:
            index_data = json.load(f)
            self.assertIn(env, index_data)
            self.assertCountEqual(index_data[env], ["tag_a", "tag_b", "tag_c"])

    def test_global_index_concurrency(self):
        # Stress test for the global index lock
        envs = [f"env_{i}" for i in range(5)]

        def runner(eid):
            viz = Visdom(port=self.port)
            viz.set_tags([f"tag_{eid}"], env=eid)

        threads = []
        for env in envs:
            t = threading.Thread(target=runner, args=(env,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Verify the global index contains all environments
        index_path = os.path.join(self.test_dir, "tags_index.json")
        with open(index_path, "r") as f:
            index_data = json.load(f)
            for env in envs:
                self.assertIn(env, index_data)
                self.assertEqual(index_data[env], [f"tag_{env}"])

        # Verify per-env JSON also persisted correctly for each environment
        for env in envs:
            env_json_path = os.path.join(self.test_dir, f"{env}.json")
            self.assertTrue(os.path.exists(env_json_path))
            with open(env_json_path, "r") as f:
                env_data = json.load(f)
                self.assertIn("tags", env_data)
                self.assertCountEqual(env_data["tags"], [f"tag_{env}"])

    def test_env_list_excludes_tags_index(self):
        # Fix 6: Ensure tags_index.json is not exposed as a real environment
        envs = self.viz.get_env_list()
        self.assertNotIn("tags_index", envs)

    def test_sdk_return_types(self):
        # Fix 5: Ensure set_tags returns a list (consistent with get_tags)
        res = self.viz.set_tags(["test"], env="type_env")
        self.assertIsInstance(res, list)
        self.assertEqual(res, ["test"])

    def test_persistence_after_restart(self):
        # Fix 9 & 13: Ensure data reloads correctly after server restart
        env = "persistent_env"
        initial_tags = ["old_tag"]
        self.viz.set_tags(initial_tags, env=env)

        # Shutdown server
        self.server_process.terminate()
        self.server_process.communicate()

        # Start new server on same port and directory
        env_vars = os.environ.copy()
        env_vars["PYTHONPATH"] = "py"
        self.server_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "visdom.server",
                "-env_path",
                self.test_dir,
                "-port",
                str(self.port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env_vars,
        )
        time.sleep(3)

        # Re-connect
        new_viz = Visdom(port=self.port)

        # 1. Verify reload from global index
        self.assertEqual(new_viz.get_tags(env=env), initial_tags)

        # 2. Verify backfill on new update (Fix 9)
        # Even if persistent_env isn't in 'state' yet, it should recover tags from app.tags
        appended = new_viz.set_tags(["new_tag"], env=env, append=True)
        self.assertCountEqual(appended, ["old_tag", "new_tag"])


if __name__ == "__main__":
    unittest.main()
