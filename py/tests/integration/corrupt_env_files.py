#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""An env whose file no longer parses can be written to again.

A file cut short by a full disk or a crash used to make every write to its env
answer 500 for as long as the file stayed there. The server now moves the file
aside, untouched, and starts the env empty, so logging carries on.
"""

import json
import os

import pytest

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration

ENV = {"jsons": {"loss": {"id": "loss", "content": "old run"}}, "reload": {}}


class TestCorruptEnvFiles(VisdomHTTPTestCase):
    def get_app(self):
        # The file has to be damaged before the server starts and lists it.
        payload = json.dumps(ENV).encode("utf-8")
        self.damaged = payload[:-10]
        self.path = os.path.join(self.env_path, "run.json")
        with open(self.path, "wb") as fn:
            fn.write(self.damaged)
        return super().get_app()

    def test_writing_to_an_env_with_a_corrupt_file_works(self):
        resp = self.post_json(
            "/events",
            {
                "eid": "run",
                "win": "notes",
                "data": [{"type": "text", "content": "new run"}],
                "layout": {},
            },
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(list(self.panes("run")), ["notes"])

        # The damaged file was moved aside untouched, so saving the new env
        # does not overwrite what was in it.
        self.assertEqual(self.save(["run"]).code, 200)
        (moved,) = [
            n for n in os.listdir(self.env_path) if n.startswith("run.json.corrupt-")
        ]
        with open(os.path.join(self.env_path, moved), "rb") as fn:
            self.assertEqual(fn.read(), self.damaged)
        with open(self.path) as fn:
            self.assertEqual(list(json.load(fn)["jsons"]), ["notes"])
