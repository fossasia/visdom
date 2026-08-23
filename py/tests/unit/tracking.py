#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for visdom.tracking.RunTracker.

Everything here is hermetic: temp dirs only, no visdom server, no network
(``_capture_environment`` only calls stdlib/local lookups).

Note: RunTracker.finish() is always called *before* the test method returns
(never via addCleanup) since addCleanup callbacks run after tearDown, by
which point the TemporaryDirectory used as out_dir has already been removed.
"""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from visdom.tracking import (
    RunAlreadyFinishedError,
    RunTracker,
)


def _read_events_jsonl(path):
    """Read every line of a run's .events.jsonl file as a list of dicts."""
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


class TestRunTrackerLifecycle(unittest.TestCase):
    """Creation, event logging, and a normal finish()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_file_immediately_as_running(self):
        """The JSON file exists (status=running) before finish() is called."""
        run = RunTracker("exp", params={"lr": 0.01}, out_dir=self.out_dir)
        self.assertTrue(os.path.exists(run.path))
        data = json.load(open(run.path))
        self.assertEqual(data["status"], RunTracker.STATUS_RUNNING)
        self.assertEqual(data["params"], {"lr": 0.01})
        self.assertIsNone(data["end_time"])
        run.finish()

    def test_finish_sets_terminal_state_and_duration(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        time.sleep(0.02)
        run.finish()
        data = json.load(open(run.path))
        self.assertEqual(data["status"], RunTracker.STATUS_FINISHED)
        self.assertIsNotNone(data["end_time"])
        self.assertGreater(data["total_duration"], 0)

    def test_log_event_appends_to_metadata_and_jsonl_with_deltas(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        run.log_event("epoch_end", epoch=1, loss=0.5)
        time.sleep(0.02)
        run.log_event("epoch_end", epoch=2, loss=0.3)
        data = json.load(open(run.path))
        run.finish()

        # metadata file's "recent_events" mirrors what's been logged so far
        self.assertEqual(data["event_count"], 3)  # created + 2 epoch_end
        recent = data["recent_events"]
        self.assertEqual(len(recent), 3)
        ev2, ev3 = recent[1], recent[2]
        self.assertEqual(ev2["data"], {"epoch": 1, "loss": 0.5})
        self.assertIsNotNone(ev3["delta_from_prev"])
        self.assertGreater(ev3["delta_from_prev"], 0)

        # full history lives in the sibling .jsonl file
        events_path = os.path.join(self.out_dir, data["events_file"])
        full_events = _read_events_jsonl(events_path)
        self.assertEqual(len(full_events), 4)  # + status_change from finish()
        self.assertEqual([e["seq"] for e in full_events], [1, 2, 3, 4])

    def test_set_param_updates_params_and_logs_event(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        run.set_param("lr", 0.001)
        data = json.load(open(run.path))
        run.finish()
        self.assertEqual(data["params"]["lr"], 0.001)
        self.assertEqual(data["recent_events"][-1]["type"], "param_set")

    def test_two_runs_same_name_get_distinct_files(self):
        """Multiple experiments/plots in one 'env' must not collide."""
        run_a = RunTracker("exp1", out_dir=self.out_dir)
        run_b = RunTracker("exp1", out_dir=self.out_dir)
        self.assertNotEqual(run_a.path, run_b.path)
        self.assertNotEqual(run_a.run_id, run_b.run_id)
        self.assertNotEqual(run_a.events_path, run_b.events_path)
        run_a.finish()
        run_b.finish()

    def test_cannot_mutate_or_refinish_after_finish(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        run.finish()
        with self.assertRaises(RunAlreadyFinishedError):
            run.finish()
        with self.assertRaises(RunAlreadyFinishedError):
            run.log_event("late")
        with self.assertRaises(RunAlreadyFinishedError):
            run.set_param("lr", 1)

    def test_finish_rejects_unknown_status(self):
        run = RunTracker("exp", out_dir=self.out_dir)
        with self.assertRaises(ValueError):
            run.finish(status="done")
        run.finish()  # clean, known status

    def test_environment_snapshot_has_no_git_fields(self):
        """Explicitly asked to be dropped: no git_commit/branch anywhere."""
        run = RunTracker("exp", out_dir=self.out_dir)
        blob = json.dumps(run.environment).lower()
        run.finish()
        self.assertNotIn("git_commit", blob)
        self.assertNotIn("git_branch", blob)

    def test_capture_environment_false_skips_snapshot(self):
        run = RunTracker("exp", out_dir=self.out_dir, capture_environment=False)
        env = run.environment
        run.finish()
        self.assertEqual(env, {})


class TestRunTrackerUnfinished(unittest.TestCase):
    """The 'closed early' path: status=unfinished with a stop_reason."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_exception_inside_context_manager_marks_unfinished(self):
        run_ref = {}
        with self.assertRaises(RuntimeError):
            with RunTracker("exp", out_dir=self.out_dir) as run:
                run_ref["run"] = run
                run.log_event("epoch_end", epoch=1)
                raise RuntimeError("gpu OOM")
        data = json.load(open(run_ref["run"].path))
        self.assertEqual(data["status"], RunTracker.STATUS_UNFINISHED)
        self.assertIn("gpu OOM", data["stop_reason"])
        self.assertIn("RuntimeError", data["stop_reason"])

    def test_normal_context_manager_exit_marks_finished(self):
        with RunTracker("exp", out_dir=self.out_dir) as run:
            pass
        data = json.load(open(run.path))
        self.assertEqual(data["status"], RunTracker.STATUS_FINISHED)
        self.assertIsNone(data["stop_reason"])

    def test_keyboard_interrupt_inside_context_manager_marks_unfinished(self):
        """KeyboardInterrupt is a BaseException, not an Exception -- make
        sure __exit__ (which receives every exception type) still catches
        it rather than only plain Exceptions."""
        run_ref = {}
        with self.assertRaises(KeyboardInterrupt):
            with RunTracker("exp", out_dir=self.out_dir) as run:
                run_ref["run"] = run
                raise KeyboardInterrupt()
        data = json.load(open(run_ref["run"].path))
        self.assertEqual(data["status"], RunTracker.STATUS_UNFINISHED)
        self.assertIn("KeyboardInterrupt", data["stop_reason"])

    def test_atexit_finalize_marks_unfinished_with_reason(self):
        """Simulates process exit without finish() ever being called."""
        run = RunTracker("exp", out_dir=self.out_dir)
        run._atexit_finalize()
        data = json.load(open(run.path))
        self.assertEqual(data["status"], RunTracker.STATUS_UNFINISHED)
        self.assertEqual(
            data["stop_reason"], "process exited before finish() was called"
        )

    def test_atexit_finalize_is_noop_if_already_finished(self):
        """A clean finish() must not be overwritten by the atexit hook."""
        run = RunTracker("exp", out_dir=self.out_dir)
        run.finish()
        run._atexit_finalize()
        data = json.load(open(run.path))
        self.assertEqual(data["status"], RunTracker.STATUS_FINISHED)
        self.assertIsNone(data["stop_reason"])


class TestReviewRegressions(unittest.TestCase):
    """One test per bug found in code review -- each fails on the old code."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_unstringable_event_data_does_not_poison_future_writes(self):
        """Previously: a value whose __str__ raised made every future
        write for the run fail forever (including finish()), because the
        bad value stayed in the in-memory history and got re-encountered
        on every subsequent json.dump. Now it's sanitized at insertion
        time instead."""

        class Unstringable:
            def __str__(self):
                raise RuntimeError("boom, cannot even str() me")

        run = RunTracker("exp", out_dir=self.out_dir)
        run.log_event("bad", obj=Unstringable())  # must not raise
        run.log_event("good", epoch=1)  # must still succeed afterwards
        run.finish()  # must still succeed afterwards

        data = json.load(open(run.path))
        self.assertEqual(data["status"], RunTracker.STATUS_FINISHED)
        bad_event = data["recent_events"][1]
        self.assertIn("unrepresentable", bad_event["data"]["obj"])

    def test_metadata_file_size_does_not_grow_with_event_count(self):
        """Previously: every log_event() rewrote the *entire* accumulated
        event history, making per-call cost (and file size) grow linearly
        with how many events had already been logged -- O(n^2) total for
        n events. The metadata file must now stay roughly constant size
        past recent_events_limit, with full history in the .jsonl file."""
        run = RunTracker("exp", out_dir=self.out_dir, recent_events_limit=10)

        for i in range(30):
            run.log_event("step", i=i)
        size_at_30 = os.path.getsize(run.path)

        for i in range(30, 300):
            run.log_event("step", i=i)
        size_at_300 = os.path.getsize(run.path)

        run.finish()

        # Comfortably bounded, not 10x-ing alongside the event count.
        self.assertLess(size_at_300, size_at_30 * 2)

        data = json.load(open(run.path))
        self.assertEqual(data["event_count"], 302)  # created + 300 steps + finish
        self.assertLessEqual(len(data["recent_events"]), 10)

        events_path = os.path.join(self.out_dir, data["events_file"])
        full_events = _read_events_jsonl(events_path)
        self.assertEqual(len(full_events), 302)

    def test_duration_uses_monotonic_clock_not_wall_clock(self):
        """Previously: total_duration/deltas were computed from time.time(),
        which can jump backward on an NTP sync or manual clock change,
        producing a negative duration. time.monotonic() is immune to that,
        so patching time.time() to jump backward must not affect it."""
        run = RunTracker("exp", out_dir=self.out_dir)
        real_time = time.time

        with patch(
            "visdom.tracking.core.time.time",
            side_effect=lambda: real_time() - 10_000,
        ):
            run.finish()

        self.assertIsNotNone(run.total_duration)
        self.assertGreaterEqual(run.total_duration, 0)

    def test_overly_long_name_is_truncated_not_a_crash(self):
        """Previously: a long `name` could push the filename past the OS
        limit (e.g. 255 bytes on Linux/macOS), raising OSError out of the
        constructor itself."""
        run = RunTracker("x" * 300, out_dir=self.out_dir)
        self.assertTrue(os.path.exists(run.path))
        run.finish()

    def test_invalid_name_type_raises_value_error(self):
        with self.assertRaises(ValueError):
            RunTracker(None, out_dir=self.out_dir)
        with self.assertRaises(ValueError):
            RunTracker(123, out_dir=self.out_dir)
        with self.assertRaises(ValueError):
            RunTracker("   ", out_dir=self.out_dir)

    def test_params_are_not_aliased_to_caller_mutable_objects(self):
        """Previously: params/tags were only shallow-copied, so a caller
        mutating a nested dict/list *after* construction (without going
        through set_param) would silently change what got serialized on
        the next write, with no corresponding event recording the change."""
        mutable_params = {"layers": [1, 2, 3]}
        run = RunTracker("exp", params=mutable_params, out_dir=self.out_dir)

        mutable_params["layers"].append(999)  # mutate the caller's copy
        mutable_params["new_key"] = "sneaky"

        run.log_event("checkpoint")  # triggers another write
        run.finish()

        data = json.load(open(run.path))
        self.assertEqual(data["params"], {"layers": [1, 2, 3]})
        self.assertNotIn("new_key", data["params"])

    def test_failed_finish_write_rolls_back_status_and_allows_retry(self):
        """Previously: self.status flipped to a terminal value in memory
        *before* the write that was supposed to persist it. If that write
        failed, the object permanently lied about its own state: retrying
        finish() raised RunAlreadyFinishedError (since status already
        looked terminal), and the atexit safety net silently no-op'd for
        the same reason -- the on-disk file was stuck at "running" forever
        with no path to ever correct it."""
        run = RunTracker("exp", out_dir=self.out_dir)

        with patch("visdom.tracking.core.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run.finish()

        # In-memory state must reflect what's actually durable on disk,
        # not what we merely attempted.
        self.assertEqual(run.status, RunTracker.STATUS_RUNNING)
        on_disk = json.load(open(run.path))
        self.assertEqual(on_disk["status"], RunTracker.STATUS_RUNNING)

        run.finish()
        self.assertEqual(run.status, RunTracker.STATUS_FINISHED)
        on_disk_after = json.load(open(run.path))
        self.assertEqual(on_disk_after["status"], RunTracker.STATUS_FINISHED)

    def test_atexit_still_recovers_after_a_failed_finish_attempt(self):
        """Companion to the above: if a failed finish() is never retried,
        the atexit safety net must still be able to mark the run
        unfinished, rather than seeing an incorrectly-terminal in-memory
        status and skipping it."""
        run = RunTracker("exp", out_dir=self.out_dir)

        with patch("visdom.tracking.core.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run.finish()

        run._atexit_finalize()
        data = json.load(open(run.path))
        self.assertEqual(data["status"], RunTracker.STATUS_UNFINISHED)

    def test_failed_set_param_write_rolls_back_the_param(self):
        """Same class of bug as finish(): self.params must not claim a
        value that was never actually persisted."""
        run = RunTracker("exp", params={"lr": 0.01}, out_dir=self.out_dir)

        with patch("visdom.tracking.core.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run.set_param("lr", 0.999)

        self.assertEqual(run.params["lr"], 0.01)  # rolled back, not 0.999
        run.finish()
        data = json.load(open(run.path))
        self.assertEqual(data["params"]["lr"], 0.01)

    def test_failed_log_event_write_does_not_advance_event_count(self):
        """The event-counter analogue: if the durable .jsonl append itself
        fails, event_count/recent_events must not advance either -- they'd
        otherwise claim an event exists that was never actually written
        anywhere."""
        run = RunTracker("exp", out_dir=self.out_dir)
        count_before = run.event_count

        with patch("visdom.tracking.core.open", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run.log_event("will_not_persist")

        self.assertEqual(run.event_count, count_before)
        run.finish()

    def test_failed_log_plot_update_write_does_not_advance_window_counters(self):
        """Same write-then-commit contract as log_event/set_param, for the
        per-window bookkeeping log_plot_update maintains: a failed write
        must leave _window_update_count/_window_last_update_monotonic
        exactly as they were, not claiming a window update happened that
        was never actually persisted anywhere."""
        run = RunTracker("exp", out_dir=self.out_dir)

        with patch("visdom.tracking.core.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run.log_plot_update("line", "loss")

        self.assertEqual(run._window_update_count, {})
        self.assertEqual(run._window_last_update_monotonic, {})

        event = run.log_plot_update("line", "loss")
        self.assertEqual(event["data"]["window_update_seq"], 1)
        self.assertIsNone(event["data"]["seconds_since_prev_update_to_window"])
        run.finish()

    def test_failed_finish_write_leaves_no_phantom_event_in_jsonl(self):
        """Follow-up to the two tests above: a failed finish() must not
        leave a status_change line in the .jsonl log that doesn't match
        the (correctly rolled-back-to-running) status. This used to
        happen because the old _add_event() durably appended to .jsonl as
        a side effect of just building the event, before the metadata
        write was even attempted -- so a failed metadata write still left
        that append committed. The write-then-commit design (build the
        event, attempt the metadata write with it included, only append
        to .jsonl after that succeeds) closes this gap: if the metadata
        write fails, the event was never appended anywhere at all."""
        run = RunTracker("exp", out_dir=self.out_dir)

        with patch("visdom.tracking.core.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run.finish()

        events_after_failure = [json.loads(l) for l in open(run.events_path)]
        self.assertEqual([e["type"] for e in events_after_failure], ["created"])
        self.assertEqual(run.event_count, 1)  # not 2 -- the attempt didn't count

        run.finish()

        events_after_retry = [json.loads(l) for l in open(run.events_path)]
        self.assertEqual(
            [e["type"] for e in events_after_retry], ["created", "status_change"]
        )  # exactly one status_change, not two

    def test_failed_init_write_leaves_no_orphaned_jsonl_file(self):
        """Companion for __init__ specifically: if the very first metadata
        write fails, the constructor raises and no RunTracker is ever
        returned -- but the old design still durably appended the
        "created" event to .jsonl as a side effect of _add_event() before
        _write() was attempted, leaving an orphaned .events.jsonl file
        with no matching .json and no object anyone holds a reference to.
        The write-then-commit ordering means nothing is appended until
        after the metadata write succeeds, so a failure here should leave
        the output directory completely empty."""
        with patch("visdom.tracking.core.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                RunTracker("exp", out_dir=self.out_dir)

        self.assertEqual(os.listdir(self.out_dir), [])

    def test_jsonl_append_failure_after_committed_metadata_does_not_corrupt_state(
        self,
    ):
        """The one gap the write-then-commit design does NOT close (and
        documents rather than hides): if the metadata write succeeds but
        the subsequent .jsonl append then fails, self.status/self.params
        are already correctly committed (metadata -- the source of truth
        -- says so too), so finish() still "worked" from a correctness
        standpoint even though this call raises. Confirms that outcome is
        self-consistent rather than silently wrong: status is genuinely
        terminal, a further finish() call is correctly rejected (not
        because of a bug, but because the run really did finish), and the
        metadata file matches self.status exactly."""
        run = RunTracker("exp", out_dir=self.out_dir)

        with patch.object(
            RunTracker, "_append_event_line", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                run.finish()

        # The metadata write (source of truth) already succeeded before
        # the patched call, so status really is terminal now.
        self.assertEqual(run.status, RunTracker.STATUS_FINISHED)
        on_disk = json.load(open(run.path))
        self.assertEqual(on_disk["status"], RunTracker.STATUS_FINISHED)

        # A further finish() call is correctly rejected -- the run
        # genuinely did finish, this isn't the bug from before.
        with self.assertRaises(RunAlreadyFinishedError):
            run.finish()

    def test_tmp_file_is_cleaned_up_if_write_fails(self):
        """Previously: if json.dump/os.replace failed partway through
        _write(), the .tmp file could be left behind on disk."""
        run = RunTracker("exp", out_dir=self.out_dir)
        tmp_path = run.path + ".tmp"

        with patch("visdom.tracking.core.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run.log_event("will_fail_to_persist")

        self.assertFalse(os.path.exists(tmp_path))
        # status flips back to running-but-unpersisted in memory; a
        # subsequent successful write still works.
        run.finish()
        data = json.load(open(run.path))
        self.assertEqual(data["status"], RunTracker.STATUS_FINISHED)


class TestSlugify(unittest.TestCase):
    def test_path_separators_and_junk_are_sanitized(self):
        from visdom.tracking.core import _slugify

        self.assertEqual(_slugify("../../etc/passwd"), ".._.._etc_passwd")
        self.assertNotIn("/", _slugify("weird name/with:chars*"))

    def test_empty_name_falls_back(self):
        from visdom.tracking.core import _slugify

        self.assertEqual(_slugify(""), "run")

    def test_long_name_is_truncated(self):
        from visdom.tracking.core import _slugify, _MAX_SLUG_LEN

        self.assertEqual(len(_slugify("x" * 500)), _MAX_SLUG_LEN)


class TestJsonSafe(unittest.TestCase):
    def test_primitives_pass_through_unchanged(self):
        from visdom.tracking.core import _json_safe

        self.assertEqual(_json_safe(1), 1)
        self.assertEqual(_json_safe(1.5), 1.5)
        self.assertEqual(_json_safe("s"), "s")
        self.assertEqual(_json_safe(True), True)
        self.assertIsNone(_json_safe(None))

    def test_nested_dict_and_list_are_rebuilt_not_aliased(self):
        from visdom.tracking.core import _json_safe

        original = {"a": [1, {"b": 2}]}
        safe = _json_safe(original)
        self.assertEqual(safe, original)
        self.assertIsNot(safe, original)
        self.assertIsNot(safe["a"], original["a"])
        self.assertIsNot(safe["a"][1], original["a"][1])

    def test_unstringable_object_becomes_placeholder_not_a_crash(self):
        from visdom.tracking.core import _json_safe

        class Bad:
            def __str__(self):
                raise RuntimeError("nope")

        result = _json_safe(Bad())
        self.assertIsInstance(result, str)
        self.assertIn("unrepresentable", result)

    def test_excessive_nesting_does_not_recurse_forever(self):
        from visdom.tracking.core import _json_safe

        nested = {}
        cursor = nested
        for _ in range(50):
            cursor["next"] = {}
            cursor = cursor["next"]
        result = _json_safe(nested)  # must return, not raise/hang
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
