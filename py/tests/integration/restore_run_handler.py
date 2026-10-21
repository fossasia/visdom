#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""``POST /restore_run`` over real HTTP, against a real ``Application``.

Run files are written directly (not generated through a live ``Visdom``
client) so these tests stay focused on the handler's own behavior --
resolving/validating the request, dispatching each captured call through
the same code a live client's call would take, and pacing. The capture
format itself (what ``RunTracker``/``TrackedVisdom`` actually produce) is
covered in ``unit/tracking_restore.py``.
"""

import json
import os
import tempfile
import time
from unittest.mock import patch

import pytest

from visdom.server.handlers import tracking_restore_handler

from testutils.http import VisdomHTTPTestCase
from testutils.payloads import content_args

pytestmark = pytest.mark.integration


def _write_tracked_run(tracking_dir, run_id, calls, name="exp", status="finished"):
    """Write a minimal ``<run_id>.json`` + ``<run_id>.events.jsonl`` pair in
    the shape ``RunTracker(record_data=True)`` produces -- one
    ``plot_update`` event per call, each carrying the exact wire message
    under ``data["call"]``.
    """
    events_file = run_id + ".events.jsonl"
    metadata = {
        "run_id": run_id,
        "name": name,
        "status": status,
        "params": {},
        "tags": {},
        "environment": {},
        "start_time": 0,
        "end_time": 1,
        "total_duration": 1,
        "stop_reason": None,
        "event_count": len(calls) + 1,
        "events_file": events_file,
        "recent_events": [],
    }
    with open(os.path.join(tracking_dir, run_id + ".json"), "w") as f:
        json.dump(metadata, f)
    with open(os.path.join(tracking_dir, events_file), "w") as f:
        f.write(json.dumps({"type": "created", "data": {}}) + "\n")
        for call in calls:
            f.write(json.dumps({"type": "plot_update", "data": {"call": call}}) + "\n")
    return run_id + ".json"


class RestoreRunCase(VisdomHTTPTestCase):
    def setUp(self):
        self._tracking_dir = tempfile.mkdtemp(prefix="visdom_tracking_test_")
        self._tracking_patch = patch.object(
            tracking_restore_handler, "TRACKING_ROOT", self._tracking_dir
        )
        self._tracking_patch.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._tracking_patch.stop()
        import shutil

        shutil.rmtree(self._tracking_dir, ignore_errors=True)

    def write_run(self, run_id, calls, **kwargs):
        return _write_tracked_run(self._tracking_dir, run_id, calls, **kwargs)


class TestRestoreRunReplaysIntoTheApplication(RestoreRunCase):
    def test_a_create_and_an_append_replay_into_a_fresh_env(self):
        calls = [
            {
                "endpoint": "events",
                "msg": content_args("text", "epoch 0", win="w1", eid="orig"),
            },
            {
                "endpoint": "update",
                "msg": {
                    "win": "w1",
                    "eid": "orig",
                    "data": [{"type": "text", "content": "epoch 1"}],
                },
            },
        ]
        rel_path = self.write_run("run_a", calls)

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "replayed"})

        self.assertEqual(resp.code, 200, resp.body)
        body = json.loads(resp.body)
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["replayed"], 2)
        self.assertEqual(body["failed"], 0)
        self.assertEqual(body["eid"], "replayed")
        self.assertEqual(body["run_id"], "run_a")

        panes = self.panes("replayed")
        self.assertEqual(len(panes), 1)
        pane = next(iter(panes.values()))
        self.assertEqual(pane["content"], "epoch 0<br>epoch 1")
        # the original env (every call's recorded eid) was never touched --
        # the handler always retargets to the requested eid.
        self.assertNotIn("orig", self._app.state)

    def test_omitting_eid_defaults_to_the_calls_own_recorded_env(self):
        calls = [
            {
                "endpoint": "events",
                "msg": content_args("text", "hi", win="w1", eid="original_env"),
            }
        ]
        rel_path = self.write_run("run_b", calls)

        resp = self.post_json("/restore_run", {"path": rel_path})

        self.assertEqual(resp.code, 200, resp.body)
        self.assertEqual(json.loads(resp.body)["eid"], "original_env")
        self.assertEqual(len(self.panes("original_env")), 1)

    def test_broadcasts_the_new_environment_to_env_state(self):
        calls = [
            {
                "endpoint": "events",
                "msg": content_args("text", "hi", win="w1", eid="x"),
            }
        ]
        rel_path = self.write_run("run_c", calls)

        self.post_json("/restore_run", {"path": rel_path, "eid": "brand_new_env"})

        self.assertIn("brand_new_env", self.get_envs())


class TestRestoreRunDelay(RestoreRunCase):
    def _calls(self, n):
        return [
            {
                "endpoint": "events",
                "msg": content_args("text", "v{0}".format(i), win="w{0}".format(i)),
            }
            for i in range(n)
        ]

    def test_a_delay_paces_the_replay_over_real_wall_clock_time(self):
        rel_path = self.write_run("run_delay", self._calls(3))

        start = time.monotonic()
        resp = self.post_json(
            "/restore_run", {"path": rel_path, "eid": "paced", "delay": 0.15}
        )
        elapsed = time.monotonic() - start

        self.assertEqual(resp.code, 200, resp.body)
        self.assertEqual(json.loads(resp.body)["replayed"], 3)
        # 3 calls -> 2 gaps of >= 0.15s each; generous headroom either side.
        self.assertGreaterEqual(elapsed, 0.25)
        self.assertLess(elapsed, 5.0)

    def test_no_delay_replays_immediately(self):
        rel_path = self.write_run("run_fast", self._calls(3))

        start = time.monotonic()
        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "fast"})
        elapsed = time.monotonic() - start

        self.assertEqual(resp.code, 200, resp.body)
        self.assertLess(elapsed, 1.0)

    def test_a_negative_delay_is_rejected_before_replaying_anything(self):
        rel_path = self.write_run("run_bad_delay", self._calls(1))

        resp = self.post_json(
            "/restore_run", {"path": rel_path, "eid": "x", "delay": -1}
        )

        self.assertEqual(resp.code, 400)
        self.assertNotIn("x", self._app.state)


class TestRestoreRunRejectsBadInput(RestoreRunCase):
    def test_missing_path_is_400(self):
        resp = self.post_json("/restore_run", {})
        self.assertEqual(resp.code, 400)

    def test_nonexistent_run_is_404(self):
        resp = self.post_json("/restore_run", {"path": "does_not_exist.json"})
        self.assertEqual(resp.code, 404)

    def test_path_traversal_is_rejected(self):
        resp = self.post_json("/restore_run", {"path": "../../etc/passwd"})
        self.assertEqual(resp.code, 400)

    def test_a_run_tracked_without_record_data_has_nothing_to_replay(self):
        run_id = "run_no_data"
        metadata = {
            "run_id": run_id,
            "name": "exp",
            "status": "finished",
            "params": {},
            "tags": {},
            "environment": {},
            "start_time": 0,
            "end_time": 1,
            "total_duration": 1,
            "stop_reason": None,
            "event_count": 1,
            "events_file": run_id + ".events.jsonl",
            "recent_events": [],
        }
        with open(os.path.join(self._tracking_dir, run_id + ".json"), "w") as f:
            json.dump(metadata, f)
        with open(os.path.join(self._tracking_dir, run_id + ".events.jsonl"), "w") as f:
            f.write(json.dumps({"type": "created", "data": {}}) + "\n")
            f.write(
                json.dumps(
                    {
                        "type": "plot_update",
                        "data": {"method": "line", "win": "w1"},
                    }
                )
                + "\n"
            )

        resp = self.post_json("/restore_run", {"path": run_id + ".json"})

        self.assertEqual(resp.code, 422)
        self.assertIn("record_data=True", json.loads(resp.body)["error"])

    def test_malformed_json_body_is_400(self):
        resp = self.fetch(
            "/restore_run",
            method="POST",
            body="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)


class TestRestoreRunReadonly(VisdomHTTPTestCase):
    app_kwargs = {"readonly": True}

    def test_restoring_a_run_is_refused(self):
        resp = self.post_json("/restore_run", {"path": "whatever.json"})
        self.assertEqual(resp.code, 403)
        body = json.loads(resp.body)
        self.assertFalse(body["success"])
        self.assertIn("readonly", body["error"])
