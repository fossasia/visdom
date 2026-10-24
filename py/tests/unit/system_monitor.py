#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for VisdomSystemMonitor.

psutil is replaced by a fake module so no real process is measured, and
viz is a Mock. Sampling is driven through ``_log`` directly; only the
thread tests start the background thread, with a tiny interval.
"""

import sys
import threading
import time
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from visdom.loggers.system_monitor import CPU_WIN, RAM_WIN, VisdomSystemMonitor

pytestmark = pytest.mark.unit

MB = 2**20


def _proc(pid=1, cpu=50.0, rss=100 * MB, children=(), cpu_time=0.0, age=10.0):
    proc = Mock(pid=pid)
    proc.cpu_percent.return_value = cpu
    proc.memory_info.return_value = SimpleNamespace(rss=rss)
    proc.children.return_value = list(children)
    proc.cpu_times.return_value = SimpleNamespace(user=cpu_time, system=0.0)
    proc.create_time.return_value = time.time() - age
    del proc.cpu_affinity
    return proc


def _fake_psutil(root=None, cores=4):
    ps = MagicMock()
    ps.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    ps.cpu_count.return_value = cores
    ps.Process.return_value = root or _proc()
    return ps


def _monitor(psutil_module=None, **kwargs):
    viz = Mock()
    viz.line.side_effect = lambda *a, **kw: kw.get("win")
    monitor = VisdomSystemMonitor(viz, **kwargs)
    monitor._psutil = psutil_module or _fake_psutil()
    monitor._root = monitor._psutil.Process()
    monitor._known = {monitor._root.pid: monitor._root}
    monitor._t0 = time.monotonic()
    return monitor


def _y(monitor, call_index):
    return monitor.viz.line.call_args_list[call_index].kwargs["Y"]


def _wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False


class TestInit(unittest.TestCase):
    def test_non_positive_interval_raises(self):
        with self.assertRaises(ValueError):
            VisdomSystemMonitor(Mock(), interval=0)
        with self.assertRaises(ValueError):
            VisdomSystemMonitor(Mock(), interval=-1)

    def test_nan_inf_and_huge_intervals_raise(self):
        for interval in (float("nan"), float("inf"), 1e12):
            with self.assertRaises(ValueError):
                VisdomSystemMonitor(Mock(), interval=interval)

    def test_non_numeric_interval_raises(self):
        with self.assertRaises(TypeError):
            VisdomSystemMonitor(Mock(), interval="fast")

    def test_non_bool_is_main_process_raises(self):
        with self.assertRaises(TypeError):
            VisdomSystemMonitor(Mock(), is_main_process="yes")

    def test_default_main_process_comes_from_rank_utils(self):
        monitor = VisdomSystemMonitor(Mock())
        target = "visdom.loggers.system_monitor.rank_utils.is_main_process"
        with patch(target, return_value=False):
            self.assertFalse(monitor._is_main)
        with patch(target, return_value=True):
            self.assertTrue(monitor._is_main)

    def test_explicit_main_process_overrides_rank_utils(self):
        target = "visdom.loggers.system_monitor.rank_utils.is_main_process"
        with patch(target, return_value=False):
            monitor = VisdomSystemMonitor(Mock(), is_main_process=True)
            self.assertTrue(monitor._is_main)

    def test_window_ids_are_fixed(self):
        self.assertEqual(CPU_WIN, "system_cpu")
        self.assertEqual(RAM_WIN, "system_ram")


class TestPlotting(unittest.TestCase):
    def test_first_sample_creates_both_windows(self):
        monitor = _monitor(env="my_env")
        monitor._log()
        calls = monitor.viz.line.call_args_list
        self.assertEqual([c.kwargs["win"] for c in calls], [CPU_WIN, RAM_WIN])
        for call in calls:
            self.assertEqual(call.kwargs["env"], "my_env")
            self.assertNotIn("update", call.kwargs)
        self.assertEqual(calls[0].kwargs["opts"]["title"], "CPU usage (%)")
        self.assertEqual(calls[1].kwargs["opts"]["title"], "RAM usage (MB)")

    def test_default_env_is_left_to_the_client(self):
        monitor = _monitor()
        monitor._log()
        for call in monitor.viz.line.call_args_list:
            self.assertIsNone(call.kwargs["env"])

    def test_later_samples_append_to_the_same_windows(self):
        monitor = _monitor()
        monitor._log()
        monitor.viz.line.reset_mock()
        monitor._log()
        calls = monitor.viz.line.call_args_list
        self.assertEqual([c.kwargs["win"] for c in calls], [CPU_WIN, RAM_WIN])
        for call in calls:
            self.assertEqual(call.kwargs["update"], "append")

    def test_every_sample_carries_the_window_options(self):
        monitor = _monitor()
        monitor._log()
        monitor._log()
        titles = [c.kwargs["opts"]["title"] for c in monitor.viz.line.call_args_list]
        self.assertEqual(titles, ["CPU usage (%)", "RAM usage (MB)"] * 2)

    def test_x_axis_is_elapsed_seconds(self):
        monitor = _monitor()
        monitor._log()
        call = monitor.viz.line.call_args_list[0]
        self.assertEqual(call.kwargs["opts"]["xlabel"], "seconds")
        self.assertGreaterEqual(call.kwargs["X"][0], 0)

    def test_failed_create_is_retried_as_create(self):
        monitor = _monitor()
        monitor.viz.line.side_effect = [False, False, "w", "w"]
        monitor._log()
        monitor._log()
        for call in monitor.viz.line.call_args_list[2:]:
            self.assertNotIn("update", call.kwargs)


class TestSampling(unittest.TestCase):
    def test_cpu_is_normalized_by_core_count(self):
        monitor = _monitor(_fake_psutil(_proc(cpu=200.0), cores=4))
        monitor._log()
        self.assertEqual(monitor.viz.line.call_args_list[0].kwargs["Y"], [50.0])

    def test_ram_is_reported_in_megabytes(self):
        monitor = _monitor(_fake_psutil(_proc(rss=256 * MB)))
        monitor._log()
        self.assertEqual(_y(monitor, 1), [256.0])

    def test_children_are_summed_in(self):
        children = [_proc(pid=2, cpu=80.0, rss=50 * MB)]
        root = _proc(cpu=100.0, rss=100 * MB, children=children)
        monitor = _monitor(_fake_psutil(root, cores=4))
        monitor._log()
        monitor._log()
        calls = monitor.viz.line.call_args_list
        self.assertEqual(calls[2].kwargs["Y"], [45.0])
        self.assertEqual(calls[3].kwargs["Y"], [150.0])

    def test_new_child_cpu_comes_from_its_lifetime_not_zero(self):
        child = _proc(pid=2, cpu=999.0, cpu_time=5.0, age=10.0)
        root = _proc(cpu=0.0, children=[child])
        monitor = _monitor(_fake_psutil(root, cores=4))
        monitor._log()
        self.assertAlmostEqual(_y(monitor, 0)[0], 12.5, delta=0.5)
        child.cpu_percent.assert_called_once_with(None)

    def test_child_with_no_age_reads_zero(self):
        child = _proc(pid=2, cpu_time=5.0, age=0.0)
        child.create_time.return_value = time.time() + 60
        root = _proc(cpu=0.0, children=[child])
        monitor = _monitor(_fake_psutil(root))
        monitor._log()
        self.assertEqual(_y(monitor, 0), [0.0])

    def test_cpu_is_normalized_by_the_cores_the_script_may_use(self):
        root = _proc(cpu=200.0)
        root.cpu_affinity = Mock(return_value=[0, 1])
        monitor = _monitor(_fake_psutil(root, cores=64))
        monitor._log()
        self.assertEqual(_y(monitor, 0), [100.0])

    def test_failing_affinity_falls_back_to_the_core_count(self):
        root = _proc(cpu=200.0)
        root.cpu_affinity = Mock(side_effect=OSError("denied"))
        monitor = _monitor(_fake_psutil(root, cores=4))
        monitor._log()
        self.assertEqual(_y(monitor, 0), [50.0])

    def test_empty_affinity_does_not_divide_by_zero(self):
        root = _proc(cpu=30.0)
        root.cpu_affinity = Mock(return_value=[])
        monitor = _monitor(_fake_psutil(root, cores=4))
        monitor._log()
        self.assertEqual(_y(monitor, 0), [30.0])

    def test_child_objects_are_reused_between_samples(self):
        first = _proc(pid=2)
        root = _proc(children=[first])
        monitor = _monitor(_fake_psutil(root))
        monitor._log()
        root.children.return_value = [_proc(pid=2)]
        monitor._log()
        self.assertEqual(first.cpu_percent.call_count, 2)

    def test_vanished_child_is_skipped(self):
        ps = _fake_psutil()
        gone = _proc(pid=2)
        gone.cpu_percent.side_effect = ps.NoSuchProcess()
        ps.Process.return_value = _proc(rss=100 * MB, children=[gone])
        monitor = _monitor(ps)
        monitor._log()
        self.assertEqual(_y(monitor, 1), [100.0])

    def test_unknown_core_count_does_not_divide_by_none(self):
        monitor = _monitor(_fake_psutil(_proc(cpu=30.0), cores=None))
        monitor._log()
        self.assertEqual(monitor.viz.line.call_args_list[0].kwargs["Y"], [30.0])


class TestFailures(unittest.TestCase):
    def test_viz_failure_warns_once_and_continues(self):
        monitor = _monitor()
        monitor.viz.line.side_effect = ConnectionError("down")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            monitor._log()
            monitor._log()
        self.assertEqual(len(caught), 1)
        self.assertIn("down", str(caught[0].message))
        self.assertEqual(monitor.viz.line.call_count, 4)

    def test_refused_post_counts_as_a_failure_and_warns_once(self):
        monitor = _monitor()
        monitor.viz.line.side_effect = lambda *a, **kw: False
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            monitor._log()
            monitor._log()
        self.assertEqual(len(caught), 1)
        self.assertIn("did not accept", str(caught[0].message))
        self.assertEqual(monitor._failures, 2)

    def test_failed_append_keeps_appending(self):
        monitor = _monitor()
        monitor._log()
        monitor.viz.line.side_effect = lambda *a, **kw: False
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            monitor._log()
        monitor.viz.line.side_effect = lambda *a, **kw: kw.get("win")
        monitor._log()
        self.assertEqual(monitor.viz.line.call_args_list[-1].kwargs["update"], "append")

    def test_wait_backs_off_while_the_server_is_failing(self):
        monitor = _monitor(interval=5)
        self.assertEqual(monitor._delay(), 5)
        monitor._failures = 1
        self.assertEqual(monitor._delay(), 10)
        monitor._failures = 3
        self.assertEqual(monitor._delay(), 40)

    def test_backoff_is_capped(self):
        monitor = _monitor(interval=5)
        monitor._failures = 4
        capped = monitor._delay()
        monitor._failures = 10_000
        self.assertEqual(monitor._delay(), capped)
        self.assertEqual(capped, 80)

    def test_a_good_sample_ends_the_backoff(self):
        monitor = _monitor(interval=5)
        monitor.viz.line.side_effect = lambda *a, **kw: False
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            monitor._log()
        self.assertEqual(monitor._delay(), 10)
        monitor.viz.line.side_effect = lambda *a, **kw: kw.get("win")
        monitor._log()
        self.assertEqual(monitor._delay(), 5)

    def test_sampling_error_counts_as_a_failure(self):
        monitor = _monitor()
        monitor._root.children.side_effect = RuntimeError("gone")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            monitor._log()
        self.assertEqual(monitor._failures, 1)

    def test_missing_psutil_warns_and_starts_nothing(self):
        viz = Mock()
        monitor = VisdomSystemMonitor(viz, interval=0.01, is_main_process=True)
        with patch.dict(sys.modules, {"psutil": None}):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self.assertIs(monitor.start(), monitor)
        self.assertEqual(len(caught), 1)
        self.assertIn("psutil", str(caught[0].message))
        self.assertIsNone(monitor._thread)
        viz.line.assert_not_called()

    def test_non_main_process_starts_nothing(self):
        monitor = VisdomSystemMonitor(Mock(), is_main_process=False)
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            monitor.start()
        self.assertIsNone(monitor._thread)


class TestThread(unittest.TestCase):
    def _started(self, **kwargs):
        viz = Mock()
        viz.line.side_effect = lambda *a, **kw: kw.get("win")
        monitor = VisdomSystemMonitor(
            viz, interval=0.01, is_main_process=True, **kwargs
        )
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            monitor.start()
        return monitor

    def test_thread_samples_until_stopped(self):
        monitor = self._started()
        self.assertTrue(_wait_for(lambda: monitor.viz.line.call_count >= 4))
        monitor.stop()
        self.assertFalse(monitor._thread.is_alive())
        count = monitor.viz.line.call_count
        time.sleep(0.05)
        self.assertEqual(monitor.viz.line.call_count, count)

    def test_thread_is_a_daemon(self):
        monitor = self._started()
        self.assertTrue(monitor._thread.daemon)
        monitor.stop()

    def test_stop_sends_a_final_sample(self):
        viz = Mock()
        viz.line.side_effect = lambda *a, **kw: kw.get("win")
        monitor = VisdomSystemMonitor(viz, interval=60, is_main_process=True)
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            monitor.start()
        monitor.stop()
        self.assertEqual(viz.line.call_count, 2)

    def test_final_sample_is_sent_from_the_monitor_thread(self):
        names = []
        viz = Mock()
        viz.line.side_effect = lambda *a, **kw: (
            names.append(threading.current_thread().name) or kw.get("win")
        )
        monitor = VisdomSystemMonitor(viz, interval=60, is_main_process=True)
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            monitor.start()
        monitor.stop()
        self.assertEqual(set(names), {"visdom-system-monitor"})

    def test_stop_does_not_wait_for_a_hung_server(self):
        release = threading.Event()
        viz = Mock()
        viz.line.side_effect = lambda *a, **kw: release.wait(5)
        monitor = VisdomSystemMonitor(viz, interval=0.01, is_main_process=True)
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            monitor.start()
        self.assertTrue(_wait_for(lambda: viz.line.called))
        with patch("visdom.loggers.system_monitor.STOP_TIMEOUT", 0.1):
            started = time.monotonic()
            monitor.stop()
        self.assertLess(time.monotonic() - started, 2)
        release.set()
        monitor._thread.join(timeout=2)

    def _stuck(self, release):
        viz = Mock()
        viz.line.side_effect = lambda *a, **kw: release.wait(5) and kw.get("win")
        monitor = VisdomSystemMonitor(viz, interval=0.01, is_main_process=True)
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            monitor.start()
        self.assertTrue(_wait_for(lambda: viz.line.called))
        with patch("visdom.loggers.system_monitor.STOP_TIMEOUT", 0.05):
            monitor.stop()
        return monitor

    def test_restart_waits_for_a_thread_that_is_still_stopping(self):
        release = threading.Event()
        monitor = self._stuck(release)
        old = monitor._thread
        self.assertTrue(old.is_alive())
        threading.Timer(0.1, release.set).start()
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            monitor.start()
        self.assertIsNot(monitor._thread, old)
        self.assertFalse(old.is_alive())
        self.assertTrue(monitor._thread.is_alive())
        monitor.stop()

    def test_restart_warns_when_the_old_thread_never_finishes(self):
        release = threading.Event()
        monitor = self._stuck(release)
        old = monitor._thread
        with patch("visdom.loggers.system_monitor.STOP_TIMEOUT", 0.05):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
                    self.assertIs(monitor.start(), monitor)
        self.assertEqual(len(caught), 1)
        self.assertIn("still shutting down", str(caught[0].message))
        self.assertIs(monitor._thread, old)
        release.set()
        old.join(timeout=2)

    def test_start_twice_keeps_one_thread(self):
        monitor = self._started()
        thread = monitor._thread
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            monitor.start()
        self.assertIs(monitor._thread, thread)
        monitor.stop()

    def test_stop_is_idempotent_and_safe_before_start(self):
        VisdomSystemMonitor(Mock()).stop()
        monitor = self._started()
        monitor.stop()
        monitor.stop()

    def test_context_manager_starts_and_stops(self):
        viz = Mock()
        viz.line.side_effect = lambda *a, **kw: kw.get("win")
        monitor = VisdomSystemMonitor(viz, interval=0.01, is_main_process=True)
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            with monitor as entered:
                self.assertIs(entered, monitor)
                self.assertTrue(monitor._thread.is_alive())
        self.assertFalse(monitor._thread.is_alive())

    def test_context_manager_does_not_swallow_exceptions(self):
        monitor = VisdomSystemMonitor(Mock(), interval=0.01, is_main_process=True)
        with patch.dict(sys.modules, {"psutil": _fake_psutil()}):
            with self.assertRaises(RuntimeError):
                with monitor:
                    raise RuntimeError("boom")
        self.assertFalse(monitor._thread.is_alive())
