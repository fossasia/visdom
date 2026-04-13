import os
import json
import threading
import shutil
import tempfile
import unittest
from visdom.utils.server_utils import atomic_save, serialize_env, LazyEnvData


class TestInfrastructure(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_atomic_save(self):
        test_file = os.path.join(self.test_dir, "test.json")
        data = json.dumps({"test": "data"})
        atomic_save(test_file, data)

        with open(test_file, "r") as f:
            self.assertEqual(f.read(), data)

    def test_lazy_env_data_tags(self):
        # Create a file with tags
        test_file = os.path.join(self.test_dir, "with_tags.json")
        data = {"jsons": {}, "reload": {}, "tags": ["tag1", "tag2"]}
        with open(test_file, "w") as f:
            json.dump(data, f)

        lazy_data = LazyEnvData(test_file)
        self.assertEqual(lazy_data["tags"], ["tag1", "tag2"])

        # Create a file without tags (backward compatibility)
        test_file_no_tags = os.path.join(self.test_dir, "no_tags.json")
        data_no_tags = {"jsons": {}, "reload": {}}
        with open(test_file_no_tags, "w") as f:
            json.dump(data_no_tags, f)

        lazy_data_no_tags = LazyEnvData(test_file_no_tags)
        self.assertEqual(lazy_data_no_tags["tags"], [])

    def test_concurrent_serialization(self):
        # Stress test for concurrency
        eid = "stress_test"
        state = {eid: {"jsons": {"win1": "content"}, "reload": {}, "tags": []}}

        def runner(i):
            # Each thread tries to update tags and serialize
            state[eid]["tags"] = [f"tag_{i}"]
            serialize_env(state, [eid], env_path=self.test_dir)

        threads = []
        for i in range(50):
            t = threading.Thread(target=runner, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Verify the file is still a valid JSON
        test_file = os.path.join(self.test_dir, f"{eid}.json")
        with open(test_file, "r") as f:
            try:
                result = json.load(f)
                self.assertIn("jsons", result)
                self.assertIn("tags", result)
                # The exact tag depends on the last thread that ran,
                # but it must be a list with one tag.
                self.assertEqual(len(result["tags"]), 1)
            except json.JSONDecodeError:
                self.fail("JSON file corrupted during concurrent writes!")


if __name__ == "__main__":
    unittest.main()
