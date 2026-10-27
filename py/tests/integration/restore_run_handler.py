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
from visdom.server.workspace_manager import WorkspaceAuthError

from testutils.http import VisdomHTTPTestCase
from testutils.payloads import content_args

pytestmark = pytest.mark.integration


def _write_tracked_run(
    tracking_dir, run_id, calls, name="exp", status="finished", workspace=None
):
    """Write a minimal ``<run_id>.json`` + ``<run_id>.events.jsonl`` pair in
    the shape ``RunTracker(record_data=True)`` produces -- one
    ``plot_update`` event per call, each carrying the exact wire message
    under ``data["call"]``. ``workspace`` matches ``RunTracker.workspace``
    (``None`` for an untagged/pre-fix run, see ``RunTracker.track``).
    """
    events_file = run_id + ".events.jsonl"
    metadata = {
        "run_id": run_id,
        "name": name,
        "status": status,
        "params": {},
        "tags": {},
        "environment": {},
        "workspace": workspace,
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
        # Replay uses the requested env, not the recorded one.
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
        # Check both inter-call delays with some timing margin.
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

    def test_an_infinite_delay_is_rejected_before_replaying_anything(self):
        rel_path = self.write_run("run_inf_delay", self._calls(1))

        resp = self.post_json(
            "/restore_run", {"path": rel_path, "eid": "x", "delay": float("inf")}
        )

        self.assertEqual(resp.code, 400)
        self.assertNotIn("x", self._app.state)

    def test_a_nan_delay_is_rejected_before_replaying_anything(self):
        rel_path = self.write_run("run_nan_delay", self._calls(1))

        resp = self.fetch(
            "/restore_run",
            method="POST",
            body='{"path": %s, "eid": "x", "delay": NaN}' % json.dumps(rel_path),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(resp.code, 400)
        self.assertNotIn("x", self._app.state)

    def test_a_delay_over_the_servers_cap_is_rejected(self):
        rel_path = self.write_run("run_huge_delay", self._calls(1))

        resp = self.post_json(
            "/restore_run",
            {
                "path": rel_path,
                "eid": "x",
                "delay": tracking_restore_handler.MAX_DELAY_SECONDS + 1,
            },
        )

        self.assertEqual(resp.code, 400)
        self.assertNotIn("x", self._app.state)

    def test_a_small_per_delay_is_rejected_once_the_total_replay_budget_is_exceeded(
        self,
    ):
        """MAX_DELAY_SECONDS only bounds the gap *between*
        calls, not the request's total pacing time -- a small, individually
        legal delay across enough calls can still add up to far more than
        this server is willing to hold one request open for."""
        rel_path = self.write_run("run_long_total", self._calls(5))

        with patch.object(tracking_restore_handler, "MAX_TOTAL_REPLAY_SECONDS", 1.0):
            resp = self.post_json(
                "/restore_run",
                # Four half-second gaps exceed the one-second limit.
                {"path": rel_path, "eid": "x", "delay": 0.5},
            )

        self.assertEqual(resp.code, 400, resp.body)
        self.assertIn("total", json.loads(resp.body)["error"])
        self.assertNotIn("x", self._app.state)

    def test_a_delay_within_the_total_replay_budget_still_replays(self):
        rel_path = self.write_run("run_short_total", self._calls(3))

        with patch.object(tracking_restore_handler, "MAX_TOTAL_REPLAY_SECONDS", 10.0):
            # Two short gaps stay under the limit.
            resp = self.post_json(
                "/restore_run", {"path": rel_path, "eid": "ok", "delay": 0.05}
            )

        self.assertEqual(resp.code, 200, resp.body)
        self.assertEqual(json.loads(resp.body)["replayed"], 3)


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

    def test_a_non_string_eid_is_rejected(self):
        rel_path = self.write_run(
            "run_bad_eid",
            [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}],
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": {}})

        self.assertEqual(resp.code, 400)
        self.assertEqual(self.panes(), {})

    def test_an_unsupported_endpoint_is_rejected_before_any_call_is_dispatched(self):
        """A structurally bad call later in the file must not let
        earlier, valid calls partially mutate the target environment first
        -- the whole file is validated before any of it is dispatched."""
        rel_path = self.write_run(
            "run_bad_endpoint",
            [
                {
                    "endpoint": "events",
                    "msg": content_args("text", "first", win="w1"),
                },
                {"endpoint": "close", "msg": {"win": "w1"}},
            ],
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "untouched"})

        self.assertEqual(resp.code, 422)
        self.assertNotIn("untouched", self._app.state)

    def test_a_call_missing_a_window_id_is_rejected_before_any_dispatch(self):
        rel_path = self.write_run(
            "run_missing_win",
            [{"endpoint": "events", "msg": {"data": [{"type": "text"}]}}],
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "untouched"})

        self.assertEqual(resp.code, 422)
        self.assertNotIn("untouched", self._app.state)

    def test_too_many_recorded_calls_is_rejected(self):
        rel_path = self.write_run(
            "run_too_big",
            [
                {
                    "endpoint": "events",
                    "msg": content_args("text", "v{0}".format(i), win="w{0}".format(i)),
                }
                for i in range(5)
            ],
        )

        with patch.object(tracking_restore_handler, "MAX_RESTORE_CALLS", 3):
            resp = self.post_json(
                "/restore_run", {"path": rel_path, "eid": "untouched"}
            )

        self.assertEqual(resp.code, 413)
        self.assertNotIn("untouched", self._app.state)

    def test_too_many_calls_is_rejected_without_reading_the_whole_run(self):
        """Enforce MAX_RESTORE_CALLS while streaming the event log."""

        def _infinite_events():
            call = {
                "endpoint": "events",
                "msg": {"win": "w", "data": [{"type": "text", "content": "x"}]},
            }
            while True:
                yield {"type": "plot_update", "data": {"call": call}}

        with (
            patch.object(
                tracking_restore_handler,
                "iter_run_events",
                return_value=_infinite_events(),
            ),
            patch.object(
                tracking_restore_handler,
                "load_run_file",
                return_value={"run_id": "r"},
            ),
        ):
            start = time.monotonic()
            with self.assertRaises(tracking_restore_handler._RunTooLargeError):
                tracking_restore_handler._load_calls_bounded(
                    "unused.json", 10, 10**9, None
                )
            elapsed = time.monotonic() - start
        # The unbounded source catches implementations that read everything
        # before enforcing the call limit.
        self.assertLess(elapsed, 2.0)

    def test_a_run_file_over_the_byte_size_cap_is_rejected(self):
        rel_path = self.write_run(
            "run_big_file",
            [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}],
        )

        with patch.object(tracking_restore_handler, "MAX_RESTORE_FILE_BYTES", 10):
            resp = self.post_json(
                "/restore_run", {"path": rel_path, "eid": "untouched"}
            )

        self.assertEqual(resp.code, 413, resp.body)
        self.assertNotIn("untouched", self._app.state)

    def test_an_oversized_metadata_file_is_rejected_without_being_parsed(self):
        """Check the metadata file size before parsing it."""
        rel_path = self.write_run(
            "run_big_metadata",
            [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}],
        )

        def _boom(*args, **kwargs):
            raise AssertionError(
                "load_run_file() was called before the metadata file's "
                "size was checked"
            )

        with (
            patch.object(tracking_restore_handler, "MAX_RESTORE_FILE_BYTES", 10),
            patch.object(tracking_restore_handler, "load_run_file", side_effect=_boom),
        ):
            resp = self.post_json(
                "/restore_run", {"path": rel_path, "eid": "untouched"}
            )

        self.assertEqual(resp.code, 413, resp.body)
        self.assertNotIn("untouched", self._app.state)

    def test_an_update_call_with_no_data_layout_or_opts_is_rejected_before_dispatch(
        self,
    ):
        rel_path = self.write_run(
            "run_empty_update", [{"endpoint": "update", "msg": {"win": "w1"}}]
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "untouched"})

        self.assertEqual(resp.code, 422)
        self.assertNotIn("untouched", self._app.state)

    def test_an_update_call_with_append_but_no_data_is_rejected_before_dispatch(self):
        rel_path = self.write_run(
            "run_append_no_data",
            [{"endpoint": "update", "msg": {"win": "w1", "append": True, "opts": {}}}],
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "untouched"})

        self.assertEqual(resp.code, 422)
        self.assertNotIn("untouched", self._app.state)

    def test_an_update_call_with_a_non_object_layout_create_is_rejected_before_dispatch(
        self,
    ):
        rel_path = self.write_run(
            "run_bad_layout_create",
            [
                {
                    "endpoint": "update",
                    "msg": {"win": "w1", "opts": {}, "layout_create": "nope"},
                }
            ],
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "untouched"})

        self.assertEqual(resp.code, 422)
        self.assertNotIn("untouched", self._app.state)

    def test_a_structurally_valid_update_call_still_replays(self):
        """The stricter update validation must not
        reject the ordinary, already-working case."""
        rel_path = self.write_run(
            "run_ok_update",
            [
                {
                    "endpoint": "events",
                    "msg": content_args("text", "epoch 0", win="w1"),
                },
                {
                    "endpoint": "update",
                    "msg": {
                        "win": "w1",
                        "data": [{"type": "text", "content": "epoch 1"}],
                    },
                },
            ],
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "ok"})

        self.assertEqual(resp.code, 200, resp.body)
        self.assertEqual(json.loads(resp.body)["replayed"], 2)


class TestRestoreRunConsistencyWarning(RestoreRunCase):
    def test_a_run_claiming_more_events_than_it_has_warns_but_still_replays(self):
        run_id = "run_truncated_history"
        calls = [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}]
        rel_path = self.write_run(run_id, calls)
        # Simulate failed appends by reporting more events than the log has.
        json_path = os.path.join(self._tracking_dir, rel_path)
        with open(json_path) as f:
            metadata = json.load(f)
        metadata["event_count"] = 999
        with open(json_path, "w") as f:
            json.dump(metadata, f)

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "warned"})

        self.assertEqual(resp.code, 200, resp.body)
        body = json.loads(resp.body)
        self.assertEqual(body["replayed"], 1)
        self.assertIsNotNone(body["warning"])
        self.assertIn("999", body["warning"])

    def test_a_consistent_run_has_no_warning(self):
        rel_path = self.write_run(
            "run_consistent",
            [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}],
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "clean"})

        self.assertEqual(resp.code, 200, resp.body)
        self.assertIsNone(json.loads(resp.body)["warning"])


class TestRestoreRunReadonly(VisdomHTTPTestCase):
    app_kwargs = {"readonly": True}

    def test_restoring_a_run_is_refused(self):
        resp = self.post_json("/restore_run", {"path": "whatever.json"})
        self.assertEqual(resp.code, 403)
        body = json.loads(resp.body)
        self.assertFalse(body["success"])
        self.assertIn("readonly", body["error"])


class _Gateway:
    """Minimal double for the workspace resolver -- just enough to
    authenticate a request into one of two workspaces, mirroring (a
    trimmed-down subset of) the one ``integration/workspace_routing.py``
    uses for the same purpose, kept local here rather than imported so this
    file stays self-contained like every other integration test module."""

    KEYS = {
        ("key-a", "alpha"): ("ws-a", "member"),
        ("key-b", "beta"): ("ws-b", "member"),
    }

    def resolve(self, api_key, slug):
        if (api_key, slug) not in self.KEYS:
            raise WorkspaceAuthError(403, "Not a member of this workspace")
        return self.KEYS[(api_key, slug)]

    def resolve_session(self, token, slug):
        raise WorkspaceAuthError(401, "Sign in to use this workspace.")

    async def resolve_off_loop(self, method, credential, slug):
        return getattr(self, method)(credential, slug)

    def storage_refusal(self, workspace_id):
        return None


class TestRestoreRunEnforcesWorkspaceOwnership(RestoreRunCase):
    """The destination env (``eid``) is already retargeted
    into the authenticated workspace, but the *source* run file was
    resolved only under the global TRACKING_ROOT with no check that it
    belongs to that workspace at all -- so a workspace that knows or
    guesses another workspace's run filename could have this endpoint read
    and replay that other workspace's recorded plot data."""

    def get_app(self):
        self.gateway = _Gateway()
        app = super().get_app()
        app.workspace_manager = self.gateway
        app.server_state.workspace_manager = self.gateway
        return app

    def post_as(self, workspace, api_key, body):
        return self.fetch(
            "/restore_run",
            method="POST",
            body=json.dumps(body),
            headers={
                "Content-Type": "application/json",
                "X-Visdom-Workspace": workspace,
                "X-API-KEY": api_key,
            },
        )

    def space(self, workspace_id):
        return self._app.workspace_env_manager.space(workspace_id)

    def test_a_workspace_can_restore_its_own_run(self):
        rel_path = self.write_run(
            "run_owned",
            [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}],
            workspace="alpha",
        )

        resp = self.post_as("alpha", "key-a", {"path": rel_path, "eid": "dest"})

        self.assertEqual(resp.code, 200, resp.body)
        self.assertEqual(json.loads(resp.body)["replayed"], 1)
        self.assertIn("dest", self.space("ws-a").state)

    def test_a_workspace_cannot_restore_another_workspaces_run(self):
        rel_path = self.write_run(
            "run_owned_by_alpha",
            [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}],
            workspace="alpha",
        )

        resp = self.post_as("beta", "key-b", {"path": rel_path, "eid": "dest"})

        # A mismatched run looks the same as a missing file.
        self.assertEqual(resp.code, 404, resp.body)
        self.assertEqual(
            json.loads(resp.body),
            {"error": "no run file found at {0!r}".format(rel_path)},
        )
        self.assertNotIn("dest", self.space("ws-b").state)

    def test_an_untagged_run_is_refused_inside_a_workspace(self):
        """Runs without workspace metadata have no owner to verify."""
        rel_path = self.write_run(
            "run_untagged",
            [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}],
        )

        resp = self.post_as("alpha", "key-a", {"path": rel_path, "eid": "dest"})

        self.assertEqual(resp.code, 404, resp.body)
        self.assertNotIn("dest", self.space("ws-a").state)

    def test_a_keyless_request_is_unaffected_by_workspace_ownership(self):
        """Unscoped deployments skip workspace ownership checks."""
        rel_path = self.write_run(
            "run_tagged_but_keyless_request",
            [{"endpoint": "events", "msg": content_args("text", "hi", win="w1")}],
            workspace="alpha",
        )

        resp = self.post_json("/restore_run", {"path": rel_path, "eid": "dest"})

        self.assertEqual(resp.code, 200, resp.body)
        self.assertEqual(json.loads(resp.body)["replayed"], 1)
