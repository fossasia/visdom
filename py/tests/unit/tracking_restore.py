#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Test replay helpers and captured plot calls from tracked runs."""

import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pytest
import visdom

from visdom.tracking import RunTracker
from visdom.tracking.restore import (
    RunRestoreError,
    extract_replayable_calls,
    load_run_events,
    load_run_file,
    replay_calls,
    resolve_under_root,
    restore_run,
    retarget_calls,
    validate_calls_for_replay,
    validate_delay,
)

pytestmark = pytest.mark.unit


def _echo_assigned_win(url, data=None, **kwargs):
    """Echo the window id assigned by the client, as the server would."""
    msg = json.loads(data)
    return msg.get("win")


def _unconnected_visdom():
    with (
        patch.object(visdom.Visdom, "_handle_post", return_value=True),
        patch.object(visdom.Visdom, "_start_session_reaper"),
    ):
        client = visdom.Visdom(use_incoming_socket=False, use_preflight_checks=False)
    client._handle_post = Mock(side_effect=_echo_assigned_win)
    return client


def _read_events_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


class TestRestoreRunEndToEnd(unittest.TestCase):
    """RunTracker(record_data=True) -> TrackedVisdom -> restore_run."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name
        self.vis = _unconnected_visdom()

    def tearDown(self):
        self._tmp.cleanup()

    def _track_a_run(self, eid="mnist_baseline"):
        run = RunTracker("mnist_baseline", out_dir=self.out_dir, record_data=True)
        tvis = run.track(self.vis)
        win = None
        for epoch in range(3):
            win = tvis.line(
                X=np.array([epoch]),
                Y=np.array([1.0 / (epoch + 1)]),
                win=win,
                update="append" if win else None,
                env=eid,
            )
        run.finish()
        return run, win

    def test_restore_run_replays_every_recorded_call(self):
        run, win = self._track_a_run()

        replayed_vis = _unconnected_visdom()
        sent = []
        replayed_vis._handle_post = Mock(
            side_effect=lambda url, data=None, **kw: (
                sent.append(json.loads(data)) or json.loads(data).get("win")
            )
        )
        result = restore_run(run.path, replayed_vis, env="replay_env")

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["replayed"], 3)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["run_id"], run.run_id)
        self.assertEqual(result["eid"], "replay_env")
        # every replayed message was retargeted to the requested env
        self.assertTrue(all(m["eid"] == "replay_env" for m in sent))
        self.assertEqual(sent[0]["win"], win)

    def test_restore_run_via_client_method_delegates(self):
        """Visdom.restore_run is a thin wrapper -- exercise the real public
        entry point once, not just the module function."""
        run, win = self._track_a_run()
        replayed_vis = _unconnected_visdom()
        result = replayed_vis.restore_run(run.path, env="via_client")
        self.assertEqual(result["replayed"], 3)
        self.assertEqual(result["eid"], "via_client")

    def test_restore_run_without_env_uses_the_recorded_eid(self):
        run, win = self._track_a_run(eid="original_env")
        replayed_vis = _unconnected_visdom()
        result = restore_run(run.path, replayed_vis)
        self.assertEqual(result["eid"], "original_env")

    def test_restore_run_paces_replays_with_delay(self):
        run, win = self._track_a_run()
        replayed_vis = _unconnected_visdom()
        with patch("visdom.tracking.restore.time.sleep") as mock_sleep:
            restore_run(run.path, replayed_vis, env="paced", delay=0.5)
        # 3 calls -> 2 gaps between them, never after the last one
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(0.5)

    def test_restore_run_refuses_an_offline_client(self):
        """An offline client's send() never reaches a
        server at all (Visdom._send returns early without posting
        anything), so "replaying" into one would either silently no-op
        every call or (worse) misreport them as successful -- refusing
        outright, with a clear error, is correct instead."""
        run, _ = self._track_a_run()
        offline_vis = _unconnected_visdom()
        offline_vis.offline = True

        with self.assertRaises(RunRestoreError) as ctx:
            restore_run(run.path, offline_vis)
        self.assertIn("offline", str(ctx.exception))

    def test_restore_run_rejects_a_tampered_endpoint_before_sending_anything(self):
        """End-to-end wiring check: restore_run() itself must reject a
        recorded call naming an endpoint outside events/update (e.g. a
        tampered or corrupted run file), not just the standalone
        validate_calls_for_replay() function in isolation."""
        run, _ = self._track_a_run()
        events_path = os.path.join(self.out_dir, run.run_id + ".events.jsonl")
        lines = _read_events_jsonl(events_path)
        # Tamper with the first plot_update's recorded endpoint.
        for event in lines:
            if event["type"] == "plot_update":
                event["data"]["calls"][0]["endpoint"] = "close"
                break
        with open(events_path, "w") as f:
            for event in lines:
                f.write(json.dumps(event) + "\n")

        replayed_vis = _unconnected_visdom()
        sent = []
        replayed_vis._handle_post = Mock(
            side_effect=lambda url, data=None, **kw: sent.append(data)
        )

        with self.assertRaises(RunRestoreError):
            restore_run(run.path, replayed_vis, env="tampered")
        self.assertEqual(sent, [])

    def test_track_records_the_clients_workspace_in_metadata(self):
        """RunTracker.track must capture vis.workspace so a server
        enforcing workspace isolation can later verify a replay request
        against the run's recorded owner (see
        tracking_restore_handler._check_run_workspace_ownership)."""
        self.vis.workspace = "alpha"
        run = RunTracker("exp", out_dir=self.out_dir, record_data=True)
        run.track(self.vis)
        run.finish()

        metadata = json.load(open(run.path))
        self.assertEqual(metadata["workspace"], "alpha")

    def test_track_records_none_for_a_keyless_clients_workspace(self):
        run = RunTracker("exp", out_dir=self.out_dir, record_data=True)
        run.track(self.vis)  # self.vis has no .workspace set -> None
        run.finish()

        metadata = json.load(open(run.path))
        self.assertIsNone(metadata["workspace"])

    def test_restore_run_without_record_data_has_nothing_to_replay(self):
        run = RunTracker("exp", out_dir=self.out_dir, record_data=False)
        tvis = run.track(self.vis)
        tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
        run.finish()

        with self.assertRaises(RunRestoreError) as ctx:
            restore_run(run.path, _unconnected_visdom())
        self.assertIn("record_data=True", str(ctx.exception))

    def test_a_long_run_replays_events_beyond_the_recent_events_cap(self):
        """recent_events is capped; replay must read the full .jsonl log,
        not the capped metadata snapshot, or a long run would silently lose
        its earliest plots."""
        run = RunTracker(
            "long_exp",
            out_dir=self.out_dir,
            record_data=True,
            recent_events_limit=5,
        )
        tvis = run.track(self.vis)
        win = None
        for epoch in range(20):
            win = tvis.line(
                X=np.array([epoch]),
                Y=np.array([float(epoch)]),
                win=win,
                update="append" if win else None,
            )
        run.finish()

        # Metadata keeps only recent events.
        metadata = json.load(open(run.path))
        self.assertLessEqual(len(metadata["recent_events"]), 5)
        # Replay still reads all recorded calls.
        replayed_vis = _unconnected_visdom()
        result = restore_run(run.path, replayed_vis, env="full_history")
        self.assertEqual(result["total"], 20)
        self.assertEqual(result["replayed"], 20)

    def test_metadata_file_does_not_grow_with_captured_payload_size(self):
        """Captured payloads stay in JSONL, not the metadata file."""
        run = RunTracker("exp", out_dir=self.out_dir, record_data=True)
        tvis = run.track(self.vis)
        big_y = np.zeros(20000)  # a plot payload heavy enough to notice
        tvis.line(X=np.arange(20000), Y=big_y, win="big")
        run.finish()

        metadata_size = os.path.getsize(run.path)
        self.assertLess(
            metadata_size,
            200_000,
            "metadata file grew with the plot payload size; the captured "
            "wire message should only live in the .events.jsonl log",
        )
        # the full payload *is* present in the durable event log, though.
        events_path = os.path.join(self.out_dir, run.run_id + ".events.jsonl")
        events = _read_events_jsonl(events_path)
        plot_updates = [e for e in events if e["type"] == "plot_update"]
        self.assertEqual(len(plot_updates), 1)
        self.assertIn("calls", plot_updates[0]["data"])
        recorded_call = plot_updates[0]["data"]["calls"][0]
        self.assertEqual(len(recorded_call["msg"]["data"][0]["y"]), 20000)

        # the compacted copy kept in metadata/recent_events has no payload.
        recent = json.load(open(run.path))["recent_events"]
        compact_update = [e for e in recent if e["type"] == "plot_update"][0]
        self.assertNotIsInstance(compact_update["data"]["calls"], list)
        self.assertEqual(compact_update["data"]["calls"], {"count": 1})


class TestMultiSendCapture(unittest.TestCase):
    """A method that sends more than once per call (e.g.
    learning_curve -> an internal self.line()) must have every one of its
    sent messages captured, not just the last."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name
        self.vis = _unconnected_visdom()

    def tearDown(self):
        self._tmp.cleanup()

    def test_capture_send_accumulates_every_message_in_order(self):
        """Direct check of the fixed mechanism: appending to a list rather
        than overwriting a single slot."""
        run = RunTracker("exp", out_dir=self.out_dir, record_data=True)
        tvis = run.track(self.vis)
        object.__setattr__(tvis, "_captured_calls", [])
        tvis._capture_send({"win": "a"}, "events")
        tvis._capture_send({"win": "a", "data": []}, "update")
        self.assertEqual(
            [c["endpoint"] for c in tvis._captured_calls], ["events", "update"]
        )
        run.finish()

    def test_a_method_that_sends_internally_more_than_once_captures_all_of_it(self):
        """A method like ``learning_curve`` sends through an internal
        ``self.line()`` call in addition to whatever it sends directly --
        i.e. one wrapped Python call can reach ``Visdom._send`` (and
        therefore the capture hook) more than once. Emulate that shape by
        making the wrapped method send an extra message itself before
        delegating to the real one, and confirm every message -- not just
        the last -- survives in the recorded ``calls`` list."""
        run = RunTracker("exp", out_dir=self.out_dir, record_data=True)
        tvis = run.track(self.vis)

        original_line = self.vis.line

        def _line_that_sends_twice(*args, **kwargs):
            # Goes through the real (unmocked) _send(), which is what
            # actually invokes the capture hook -- same path a delegating
            # chart method's internal call would take.
            self.vis._send({"win": "extra", "eid": self.vis.env}, "events")
            return original_line(*args, **kwargs)

        with patch.object(self.vis, "line", side_effect=_line_that_sends_twice):
            tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
        run.finish()

        events_path = os.path.join(self.out_dir, run.run_id + ".events.jsonl")
        events = _read_events_jsonl(events_path)
        plot_update = [e for e in events if e["type"] == "plot_update"][0]
        calls = plot_update["data"]["calls"]
        self.assertEqual([c["endpoint"] for c in calls], ["events", "events"])
        self.assertEqual([c["msg"]["win"] for c in calls], ["extra", "loss"])


class TestHookLockSerialization(unittest.TestCase):
    """Two TrackedVisdom proxies (or threads driving one)
    sharing the same underlying Visdom client must not have their captured
    calls cross-contaminate."""

    def test_concurrent_tracked_calls_on_a_shared_client_do_not_cross_capture(self):
        self._tmp = tempfile.TemporaryDirectory()
        out_dir = self._tmp.name
        vis = _unconnected_visdom()

        # Slow the transport down so the two threads' wrapped calls actually
        # overlap in time, which is what would expose a hook race.
        real_handle_post = vis._handle_post

        def _slow_echo(url, data=None, **kw):
            time.sleep(0.05)
            return real_handle_post(url, data=data, **kw)

        vis._handle_post = _slow_echo

        run_a = RunTracker("run_a", out_dir=out_dir, record_data=True)
        run_b = RunTracker("run_b", out_dir=out_dir, record_data=True)
        tvis_a = run_a.track(vis)
        tvis_b = run_b.track(vis)

        def _plot(tvis, win):
            tvis.line(X=np.array([0]), Y=np.array([1.0]), win=win)

        t_a = threading.Thread(target=_plot, args=(tvis_a, "a_win"))
        t_b = threading.Thread(target=_plot, args=(tvis_b, "b_win"))
        t_a.start()
        t_b.start()
        t_a.join(timeout=5)
        t_b.join(timeout=5)
        run_a.finish()
        run_b.finish()

        events_a = _read_events_jsonl(
            os.path.join(out_dir, run_a.run_id + ".events.jsonl")
        )
        events_b = _read_events_jsonl(
            os.path.join(out_dir, run_b.run_id + ".events.jsonl")
        )
        update_a = [e for e in events_a if e["type"] == "plot_update"][0]
        update_b = [e for e in events_b if e["type"] == "plot_update"][0]
        self.assertEqual(update_a["data"]["calls"][0]["msg"]["win"], "a_win")
        self.assertEqual(update_b["data"]["calls"][0]["msg"]["win"], "b_win")
        self._tmp.cleanup()


class TestFinishWaitsForInFlightCalls(unittest.TestCase):
    """A tracked call already underway when finish() is called
    from another thread must still get recorded, not silently dropped."""

    def test_finish_waits_for_a_call_that_started_before_it(self):
        self._tmp = tempfile.TemporaryDirectory()
        out_dir = self._tmp.name
        vis = _unconnected_visdom()
        real_handle_post = vis._handle_post

        call_started = threading.Event()

        def _slow_echo(url, data=None, **kw):
            call_started.set()
            time.sleep(0.2)
            return real_handle_post(url, data=data, **kw)

        vis._handle_post = _slow_echo

        run = RunTracker("exp", out_dir=out_dir)
        tvis = run.track(vis)

        plot_thread = threading.Thread(
            target=lambda: tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
        )
        plot_thread.start()
        call_started.wait(timeout=5)
        # finish() is requested while the plot call above is still inside
        # its (slow) send -- it has not reached log_plot_update yet.
        run.finish()
        plot_thread.join(timeout=5)

        events = _read_events_jsonl(os.path.join(out_dir, run.run_id + ".events.jsonl"))
        updates = [e for e in events if e["type"] == "plot_update"]
        self.assertEqual(
            len(updates),
            1,
            "the in-flight plot call's update was dropped by finish() "
            "instead of being waited for",
        )
        self._tmp.cleanup()

    def test_finish_does_not_go_terminal_while_a_call_is_still_being_logged(self):
        """Deterministic reproduction of the exact race: the network/plot
        call itself can be fast -- the gap that matters is between the
        wrapped method returning and log_plot_update actually committing.
        Forces that gap open with explicit synchronization (not timing),
        so this fails reliably if _end_call() ever moves back to firing
        before logging, rather than only occasionally under GIL scheduling
        luck."""
        self._tmp = tempfile.TemporaryDirectory()
        out_dir = self._tmp.name
        vis = _unconnected_visdom()
        run = RunTracker("exp", out_dir=out_dir)
        tvis = run.track(vis)

        entered_logging = threading.Event()
        release_logging = threading.Event()
        original_log_plot_update = run.log_plot_update

        def _blocked_log_plot_update(*args, **kwargs):
            entered_logging.set()
            release_logging.wait(timeout=5)
            return original_log_plot_update(*args, **kwargs)

        with patch.object(run, "log_plot_update", side_effect=_blocked_log_plot_update):
            plot_thread = threading.Thread(
                target=lambda: tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
            )
            plot_thread.start()
            self.assertTrue(
                entered_logging.wait(timeout=5),
                "plot call never reached log_plot_update",
            )
            # The plot method itself has already returned at this point --
            # under the old, buggy ordering _end_call() would already have
            # fired here, and finish() below would complete immediately.

            finish_thread = threading.Thread(target=run.finish)
            finish_thread.start()
            finish_thread.join(timeout=0.3)
            self.assertTrue(
                finish_thread.is_alive(),
                "finish() returned while the in-flight call was still "
                "being logged -- _end_call() is firing too early again",
            )
            self.assertEqual(run.status, RunTracker.STATUS_RUNNING)

            release_logging.set()
            plot_thread.join(timeout=5)
            finish_thread.join(timeout=5)

        events = _read_events_jsonl(os.path.join(out_dir, run.run_id + ".events.jsonl"))
        updates = [e for e in events if e["type"] == "plot_update"]
        self.assertEqual(len(updates), 1)
        self._tmp.cleanup()

    def test_finish_timeout_zero_does_not_wait(self):
        """timeout=0 opts back into the old, non-waiting behavior."""
        tmp = tempfile.TemporaryDirectory()
        run = RunTracker("exp", out_dir=tmp.name)
        began = run._begin_call()
        self.assertTrue(began)
        start = time.monotonic()
        run.finish(timeout=0)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.5)
        run._end_call()
        tmp.cleanup()

    def test_context_manager_exit_does_not_go_terminal_while_a_call_is_still_being_logged(
        self,
    ):
        """``finish()`` waits for in-flight calls, but
        ``with RunTracker(...) as run:`` -- the usage pattern the feature's
        own docs lead with -- exits through ``__exit__``, not ``finish()``.
        Before this fix, ``__exit__`` called ``_finish_locked`` directly, so
        the exact race ``finish()`` closes was still wide open on this path.
        Same deterministic-interleaving reproduction as
        ``test_finish_does_not_go_terminal_while_a_call_is_still_being_logged``
        (forcing the exact gap open with ``threading.Event`` rather than
        relying on timing), just exercised through ``__exit__`` -- called
        directly, as the ``with`` statement itself would, rather than
        through ``finish()`` -- instead of through ``finish()``."""
        self._tmp = tempfile.TemporaryDirectory()
        out_dir = self._tmp.name
        vis = _unconnected_visdom()
        run = RunTracker("exp", out_dir=out_dir)
        tvis = run.track(vis)

        entered_logging = threading.Event()
        release_logging = threading.Event()
        original_log_plot_update = run.log_plot_update

        def _blocked_log_plot_update(*args, **kwargs):
            entered_logging.set()
            release_logging.wait(timeout=5)
            return original_log_plot_update(*args, **kwargs)

        with patch.object(run, "log_plot_update", side_effect=_blocked_log_plot_update):
            run.__enter__()
            plot_thread = threading.Thread(
                target=lambda: tvis.line(X=np.array([0]), Y=np.array([1.0]), win="loss")
            )
            plot_thread.start()
            self.assertTrue(
                entered_logging.wait(timeout=5),
                "plot call never reached log_plot_update",
            )
            # The wrapped plot method has already returned at this point --
            # under the old, buggy __exit__ (calling _finish_locked
            # directly) the block below would have gone terminal
            # immediately instead of blocking here.

            exit_thread = threading.Thread(
                target=lambda: run.__exit__(None, None, None)
            )
            exit_thread.start()
            exit_thread.join(timeout=0.3)
            self.assertTrue(
                exit_thread.is_alive(),
                "__exit__ returned while the in-flight call was still "
                "being logged -- it is not waiting for active calls the "
                "way finish() does",
            )
            self.assertEqual(run.status, RunTracker.STATUS_RUNNING)

            release_logging.set()
            plot_thread.join(timeout=5)
            exit_thread.join(timeout=5)

        events = _read_events_jsonl(os.path.join(out_dir, run.run_id + ".events.jsonl"))
        updates = [e for e in events if e["type"] == "plot_update"]
        self.assertEqual(
            len(updates),
            1,
            "the in-flight plot call's update was dropped by __exit__ "
            "instead of being waited for",
        )
        self.assertEqual(run.status, RunTracker.STATUS_FINISHED)
        self._tmp.cleanup()


class TestLoadRunFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_raises_run_restore_error(self):
        with self.assertRaises(RunRestoreError):
            load_run_file(os.path.join(self.out_dir, "nope.json"))

    def test_malformed_json_raises_run_restore_error(self):
        path = os.path.join(self.out_dir, "bad.json")
        with open(path, "w") as f:
            f.write("{not json")
        with self.assertRaises(RunRestoreError):
            load_run_file(path)

    def test_json_without_run_id_is_rejected(self):
        path = os.path.join(self.out_dir, "not_a_run.json")
        with open(path, "w") as f:
            json.dump({"hello": "world"}, f)
        with self.assertRaises(RunRestoreError):
            load_run_file(path)

    def test_valid_run_file_loads(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        run.finish()
        metadata = load_run_file(run.path)
        self.assertEqual(metadata["run_id"], run.run_id)


class TestLoadRunEvents(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_reads_full_jsonl_history(self):
        run = RunTracker("exp", out_dir=self.out_dir, recent_events_limit=1)
        run.log_event("a")
        run.log_event("b")
        run.finish()
        events = load_run_events(run.path)
        types = [e["type"] for e in events]
        self.assertEqual(types, ["created", "a", "b", "status_change"])

    def test_falls_back_to_recent_events_if_jsonl_missing(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        run.log_event("a")
        run.finish()
        os.remove(run.events_path)
        events = load_run_events(run.path)
        self.assertTrue(any(e["type"] == "a" for e in events))

    def test_skips_unparseable_lines(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        run.finish()
        with open(run.events_path, "a") as f:
            f.write("not json at all\n")
        events = load_run_events(run.path)
        self.assertTrue(all(isinstance(e, dict) for e in events))

    def _write_metadata(self, run_id, events_file):
        path = os.path.join(self.out_dir, run_id + ".json")
        with open(path, "w") as f:
            json.dump({"run_id": run_id, "name": "exp", "events_file": events_file}, f)
        return path

    def test_an_events_file_pointing_outside_the_run_directory_is_rejected(self):
        """The events_file comes from metadata, so
        untrusted the same way the request path is -- a tampered metadata
        file naming an events_file outside json_path's own directory must
        be refused, not silently followed."""
        path = self._write_metadata("tampered", "../outside.jsonl")
        with self.assertRaises(RunRestoreError):
            load_run_events(path)

    def test_an_absolute_events_file_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as secret:
            secret.write(b'{"type": "created", "data": {}}\n')
            secret.flush()
            path = self._write_metadata("tampered_abs", secret.name)
            with self.assertRaises(RunRestoreError):
                load_run_events(path)

    def test_a_non_string_events_file_is_rejected(self):
        path = os.path.join(self.out_dir, "tampered_type.json")
        with open(path, "w") as f:
            json.dump(
                {"run_id": "tampered_type", "name": "exp", "events_file": ["x"]}, f
            )
        with self.assertRaises(RunRestoreError):
            load_run_events(path)

    def test_a_plain_sibling_events_file_still_works(self):
        """The containment check must not break the ordinary, legitimate
        case: events_file as RunTracker actually writes it -- a bare
        basename alongside json_path."""
        run = RunTracker("exp", out_dir=self.out_dir)
        run.log_event("a")
        run.finish()
        events = load_run_events(run.path)
        self.assertTrue(any(e["type"] == "a" for e in events))


class TestExtractReplayableCalls(unittest.TestCase):
    def test_ignores_non_plot_update_events(self):
        events = [{"type": "created", "data": {}}, {"type": "status_change"}]
        self.assertEqual(extract_replayable_calls(events), [])

    def test_ignores_plot_update_without_captured_call(self):
        events = [{"type": "plot_update", "data": {"method": "line"}}]
        self.assertEqual(extract_replayable_calls(events), [])

    def test_extracts_single_call_shape(self):
        events = [
            {
                "type": "plot_update",
                "data": {"call": {"endpoint": "events", "msg": {"win": "a"}}},
            }
        ]
        calls = extract_replayable_calls(events)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["endpoint"], "events")

    def test_extracts_multi_call_shape_in_order(self):
        events = [
            {
                "type": "plot_update",
                "data": {
                    "calls": [
                        {"endpoint": "events", "msg": {"win": "a"}},
                        {"endpoint": "update", "msg": {"win": "a"}},
                    ]
                },
            }
        ]
        calls = extract_replayable_calls(events)
        self.assertEqual([c["endpoint"] for c in calls], ["events", "update"])


class TestRetargetCalls(unittest.TestCase):
    def test_overwrites_eid_on_every_call(self):
        calls = [
            {"endpoint": "events", "msg": {"win": "a", "eid": "orig"}},
            {"endpoint": "update", "msg": {"win": "a", "eid": "other"}},
        ]
        retargeted = retarget_calls(calls, "new_env")
        self.assertTrue(all(c["msg"]["eid"] == "new_env" for c in retargeted))

    def test_does_not_mutate_the_input(self):
        calls = [{"endpoint": "events", "msg": {"win": "a", "eid": "orig"}}]
        retarget_calls(calls, "new_env")
        self.assertEqual(calls[0]["msg"]["eid"], "orig")


class TestValidateDelay(unittest.TestCase):
    def test_none_passes_through(self):
        self.assertIsNone(validate_delay(None))

    def test_zero_is_valid(self):
        self.assertEqual(validate_delay(0), 0.0)

    def test_positive_number_is_valid(self):
        self.assertEqual(validate_delay(1.5), 1.5)
        self.assertEqual(validate_delay(2), 2.0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            validate_delay(-1)

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            validate_delay(True)

    def test_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            validate_delay("1")

    def test_positive_infinity_raises(self):
        with self.assertRaises(ValueError):
            validate_delay(float("inf"))

    def test_negative_infinity_raises(self):
        with self.assertRaises(ValueError):
            validate_delay(float("-inf"))

    def test_nan_raises(self):
        """NaN compares false against every ordering comparison (including
        `< 0`), so the negative-value check alone would let it through."""
        with self.assertRaises(ValueError):
            validate_delay(float("nan"))

    def test_json_decoded_infinity_and_nan_tokens_are_rejected(self):
        """Python's json module accepts the bare Infinity/-Infinity/NaN
        tokens by default (the same tokens NanSafeEncoder writes for a
        non-finite float), so a request body containing one for "delay"
        decodes straight to the float it names -- this must still be
        caught here, not assumed impossible upstream."""
        for token in ("Infinity", "-Infinity", "NaN"):
            with self.subTest(token=token):
                decoded = json.loads('{"delay": %s}' % token)["delay"]
                with self.assertRaises(ValueError):
                    validate_delay(decoded)


class TestResolveUnderRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_simple_relative_path_resolves(self):
        open(os.path.join(self.root, "run.json"), "w").close()
        resolved = resolve_under_root(self.root, "run.json")
        self.assertTrue(resolved.startswith(os.path.realpath(self.root)))

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(RunRestoreError):
            resolve_under_root(self.root, "../outside.json")

    def test_absolute_path_outside_root_is_rejected(self):
        with self.assertRaises(RunRestoreError):
            resolve_under_root(self.root, "/etc/passwd")

    def test_an_absolute_path_that_would_resolve_inside_root_is_still_rejected(self):
        """An absolute path must be rejected,
        full stop, but the old implementation only rejected one that also
        failed the containment check -- an absolute path that happened to
        resolve inside root_dir slipped through. No legitimate caller ever
        has an absolute path to offer (a request body's `path`, or a bare
        basename RunTracker itself wrote into `events_file`), so this
        tightens the check to match what's documented."""
        open(os.path.join(self.root, "run.json"), "w").close()
        absolute_but_contained = os.path.join(self.root, "run.json")
        self.assertTrue(os.path.isabs(absolute_but_contained))

        with self.assertRaises(RunRestoreError):
            resolve_under_root(self.root, absolute_but_contained)

    def test_nul_byte_is_rejected(self):
        with self.assertRaises(RunRestoreError):
            resolve_under_root(self.root, "run\x00.json")


class TestReplayCalls(unittest.TestCase):
    def test_replays_in_order_and_counts_results(self):
        sent = []

        def send(msg, endpoint):
            sent.append((endpoint, msg["win"]))

        calls = [
            {"endpoint": "events", "msg": {"win": "a"}},
            {"endpoint": "update", "msg": {"win": "b"}},
        ]
        result = replay_calls(calls, send)
        self.assertEqual(result, {"total": 2, "replayed": 2, "failed": 0, "errors": []})
        self.assertEqual(sent, [("events", "a"), ("update", "b")])

    def test_a_failing_call_is_recorded_but_does_not_stop_the_rest(self):
        def send(msg, endpoint):
            if msg["win"] == "bad":
                raise RuntimeError("boom")

        calls = [
            {"endpoint": "events", "msg": {"win": "bad"}},
            {"endpoint": "events", "msg": {"win": "good"}},
        ]
        result = replay_calls(calls, send)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["replayed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertIn("boom", result["errors"][0])

    def test_delay_sleeps_between_but_not_after_the_last_call(self):
        calls = [
            {"endpoint": "events", "msg": {"win": "a"}},
            {"endpoint": "events", "msg": {"win": "b"}},
            {"endpoint": "events", "msg": {"win": "c"}},
        ]
        with patch("visdom.tracking.restore.time.sleep") as mock_sleep:
            replay_calls(calls, lambda msg, endpoint: None, delay=0.25)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(0.25)

    def test_zero_delay_does_not_sleep(self):
        calls = [{"endpoint": "events", "msg": {"win": "a"}}]
        with patch("visdom.tracking.restore.time.sleep") as mock_sleep:
            replay_calls(calls, lambda msg, endpoint: None, delay=0)
        mock_sleep.assert_not_called()

    def test_invalid_delay_raises_before_replaying_anything(self):
        sent = []
        calls = [{"endpoint": "events", "msg": {"win": "a"}}]
        with self.assertRaises(ValueError):
            replay_calls(calls, lambda msg, endpoint: sent.append(msg), delay=-1)
        self.assertEqual(sent, [])

    def test_a_send_returning_false_is_counted_as_failed_not_replayed(self):
        """Visdom._send returns False (rather
        than raising) for a connection/SSL failure whenever
        raise_exceptions isn't True -- the common/default case. Treating
        "didn't raise" as "succeeded" would silently count that failure as
        replayed."""
        calls = [
            {"endpoint": "events", "msg": {"win": "a"}},
            {"endpoint": "events", "msg": {"win": "b"}},
        ]
        result = replay_calls(calls, lambda msg, endpoint: msg["win"] != "a")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["replayed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertIn("False", result["errors"][0])

    def test_a_send_returning_none_or_other_falsy_values_still_counts_as_replayed(
        self,
    ):
        """Only the exact sentinel False is a failure -- a legitimate
        result can itself be None, 0, or "" (e.g. offline mode, or a
        window id of "0"), and none of those should be misread as a
        failure the way a bare `if not result` check would."""
        for value in (None, 0, "", "0"):
            with self.subTest(value=value):
                result = replay_calls(
                    [{"endpoint": "events", "msg": {"win": "a"}}],
                    lambda msg, endpoint, v=value: v,
                )
                self.assertEqual(result["replayed"], 1)
                self.assertEqual(result["failed"], 0)


class TestValidateCallsForReplay(unittest.TestCase):
    def test_events_and_update_calls_are_accepted(self):
        calls = [
            {"endpoint": "events", "msg": {"win": "a"}},
            {"endpoint": "update", "msg": {"win": "a"}},
        ]
        validate_calls_for_replay(calls)  # must not raise

    def test_an_unsupported_endpoint_is_rejected(self):
        """The client path (Visdom.restore_run) must replay
        whatever endpoint a recorded call named, with no allowlist at all
        -- unlike the server path. A crafted/tampered run file naming an
        endpoint like "close" or "delete_env" would otherwise be resent to
        the live server verbatim."""
        calls = [{"endpoint": "close", "msg": {"win": "a"}}]
        with self.assertRaises(RunRestoreError):
            validate_calls_for_replay(calls)

    def test_rejects_before_any_call_is_sent(self):
        sent = []
        calls = [
            {"endpoint": "events", "msg": {"win": "a"}},
            {"endpoint": "delete_env", "msg": {"win": "b"}},
        ]
        with self.assertRaises(RunRestoreError):
            validate_calls_for_replay(calls)
        self.assertEqual(sent, [])
