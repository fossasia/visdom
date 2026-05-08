import json
import tempfile
import unittest
from pathlib import Path

from visdom.utils.server_utils import compare_envs, load_env


class DummySocket:
    def __init__(self):
        self.messages = []
        self.eid = None

    def write_message(self, message):
        self.messages.append(message)


class ServerUtilsLazyEnvPathTests(unittest.TestCase):
    def make_env(self, title):
        return {
            "jsons": {
                "win1": {
                    "command": "window",
                    "id": "win1",
                    "title": title,
                    "type": "plot",
                    "content": {
                        "data": [{"name": "series", "y": [1], "x": [1]}],
                        "layout": {},
                    },
                    "i": 1,
                }
            },
            "reload": {"foo": "bar"},
        }

    def test_load_env_reads_eid_json_file(self):
        state = {}
        socket = DummySocket()

        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "demo.json").write_text(json.dumps(self.make_env("demo")))

            load_env(state, " demo ", socket, env_path=tmpdir)

        self.assertIn(" demo ", state)
        self.assertEqual(socket.eid, " demo ")
        self.assertTrue(any("layout" in str(message) for message in socket.messages))

    def test_compare_envs_reads_each_env_from_json_files(self):
        state = {}
        socket = DummySocket()

        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "envA.json").write_text(json.dumps(self.make_env("shared")))
            Path(tmpdir, "envB.json").write_text(json.dumps(self.make_env("shared")))

            compare_envs(state, ["envA", "envB"], socket, env_path=tmpdir)

        self.assertEqual(set(state), {"envA", "envB"})
        self.assertEqual(socket.eid, ["envA", "envB"])
        self.assertTrue(any("window_compare_legend" in str(message) for message in socket.messages))


if __name__ == "__main__":
    unittest.main()
