#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import threading
import time
import warnings

from visdom.utils import rank_utils

CPU_WIN = "system_cpu"
RAM_WIN = "system_ram"
MB = 2**20
STOP_TIMEOUT = 5


def _lifetime_cpu(proc):
    """CPU percent of one core since ``proc`` started.

    psutil's cpu_percent reports 0.0 on a process's first call, so a worker
    would read idle for its whole first interval. Its total CPU time over
    its age is the best figure available until the second call.
    """
    proc.cpu_percent(None)
    times = proc.cpu_times()
    age = time.time() - proc.create_time()
    return 100 * (times.user + times.system) / age if age > 0 else 0.0


class VisdomSystemMonitor:
    """Plots the CPU and RAM usage of the running script to Visdom.

    A background thread samples the current process and its child
    processes (e.g. DataLoader workers) every ``interval`` seconds and
    appends the values to two line plots in ``env``, or in the client's
    own env when ``env`` is None. The windows have fixed ids, so a second
    run in the same env replaces them instead of adding more.

    The x-axis is seconds since ``start()``. Values come straight from
    the OS through psutil; nothing is computed about the model. psutil is
    optional: without it ``start()`` warns and the monitor does nothing.
    RSS is summed per process, so memory shared between workers is
    counted once per worker. The cores the script may use are those in its
    CPU affinity mask (so a SLURM job pinned to 8 of 64 cores tops out at
    100%), or all cores where the OS has no such mask, e.g. macOS. A
    container CPU quota is not taken into account.

    Sampling and sending happen on the monitor's own daemon thread, so a
    slow server never stalls training. While the server keeps failing the
    monitor waits longer between samples, up to 16 times ``interval``, and
    goes back to ``interval`` once a sample gets through. Every sample
    carries the window options, so a window closed in the browser comes
    back with its title. Under distributed training only
    the main process, global rank 0, is monitored; pass
    ``is_main_process=True`` or ``False`` to choose it yourself, as with
    VisdomLogger.

    Usage::

        from visdom.loggers import VisdomSystemMonitor

        with VisdomSystemMonitor(viz, interval=5):
            train()

        monitor = VisdomSystemMonitor(viz, env="run_1").start()
        train()
        monitor.stop()
    """

    def __init__(self, viz, env=None, interval=5, is_main_process=None):
        if isinstance(interval, bool) or not isinstance(interval, (int, float)):
            raise TypeError("interval must be a number, got {!r}".format(interval))
        if not 0 < interval <= threading.TIMEOUT_MAX:
            raise ValueError(
                "interval must be a positive, finite number, got {}".format(interval)
            )
        if not isinstance(is_main_process, (bool, type(None))):
            raise TypeError(
                "is_main_process must be True, False or None, got {!r}".format(
                    is_main_process
                )
            )
        self.viz = viz
        self.env = env
        self.interval = interval
        self._main_override = is_main_process
        self._psutil = None
        self._root = None
        self._known = {}
        self._created = set()
        self._failures = 0
        self._warned = False
        self._t0 = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def _is_main(self):
        if self._main_override is not None:
            return self._main_override
        return rank_utils.is_main_process()

    def start(self):
        """Start sampling in a background thread. Returns self."""
        if self._thread is not None and self._thread.is_alive():
            if not self._stop.is_set():
                return self
            self._thread.join(timeout=STOP_TIMEOUT)
            if self._thread.is_alive():
                warnings.warn(
                    "The previous VisdomSystemMonitor thread is still shutting "
                    "down, not starting a new one."
                )
                return self
        if not self._is_main:
            return self
        try:
            import psutil
        except ImportError:
            warnings.warn(
                "psutil is required for VisdomSystemMonitor, no system "
                "metrics will be logged. Install with: pip install psutil"
            )
            return self
        self._psutil = psutil
        self._root = psutil.Process()
        self._root.cpu_percent(None)
        self._known = {self._root.pid: self._root}
        self._created = set()
        self._failures = 0
        self._stop.clear()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, name="visdom-system-monitor", daemon=True
        )
        self._thread.start()
        return self

    def stop(self):
        """Stop the thread after one last sample. Safe to call twice.

        Waits at most STOP_TIMEOUT seconds, so a server that has stopped
        answering cannot hold up the end of the script.
        """
        if self._thread is None or self._stop.is_set():
            return
        self._stop.set()
        self._thread.join(timeout=STOP_TIMEOUT)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def _delay(self):
        return self.interval * 2 ** min(self._failures, 4)

    def _run(self):
        while not self._stop.wait(self._delay()):
            self._log()
        self._log()

    def _warn(self, error):
        if not self._warned:
            self._warned = True
            warnings.warn("VisdomSystemMonitor failed to log: {}".format(error))

    def _core_count(self):
        try:
            return len(self._root.cpu_affinity()) or 1
        except Exception:
            return self._psutil.cpu_count() or 1

    def _sample(self):
        known, self._known = self._known, {self._root.pid: self._root}
        for child in self._root.children(recursive=True):
            self._known[child.pid] = known.get(child.pid, child)
        cpu = rss = 0
        for pid, proc in self._known.items():
            try:
                proc_cpu = (
                    proc.cpu_percent(None) if pid in known else _lifetime_cpu(proc)
                )
                proc_rss = proc.memory_info().rss
            except self._psutil.NoSuchProcess:
                continue
            cpu += proc_cpu
            rss += proc_rss
        return cpu / self._core_count(), rss / MB

    def _log(self):
        x = time.monotonic() - self._t0
        try:
            cpu, ram = self._sample()
        except Exception as e:
            self._warn(e)
            self._failures += 1
            return
        sent = [
            self._plot(CPU_WIN, "CPU usage (%)", x, cpu),
            self._plot(RAM_WIN, "RAM usage (MB)", x, ram),
        ]
        self._failures = 0 if all(sent) else self._failures + 1

    def _plot(self, win, title, x, value):
        update = {"update": "append"} if win in self._created else {}
        try:
            reply = self.viz.line(
                X=[x],
                Y=[value],
                win=win,
                env=self.env,
                name="script",
                opts={"title": title, "xlabel": "seconds", "ylabel": title},
                **update
            )
        except Exception as e:
            self._warn(e)
            return False
        if not reply:
            self._warn("the Visdom server did not accept the data")
            return False
        self._created.add(win)
        return True
