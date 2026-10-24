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


class VisdomSystemMonitor:
    """Plots the CPU and RAM usage of the running script to Visdom.

    A background thread samples the current process and its child
    processes (e.g. DataLoader workers) every ``interval`` seconds and
    appends the values to two line plots in ``env``, or in the client's
    own env when ``env`` is None. The windows have fixed ids, so a second
    run in the same env replaces them instead of adding more:

    ===========  ====================  =================================
    window id    title                 value
    ===========  ====================  =================================
    system_cpu   CPU usage (%)         process CPU time over all cores,
                                       as a percentage of the machine
    system_ram   RAM usage (MB)        resident memory (RSS) of the
                                       process and its children
    ===========  ====================  =================================

    The x-axis is seconds since ``start()``. Values come straight from
    the OS through psutil; nothing is computed about the model. psutil is
    optional: without it ``start()`` warns and the monitor does nothing.
    RSS is summed per process, so memory shared between workers is
    counted once per worker.

    Sampling and sending happen on the monitor's own daemon thread, so a
    slow server never stalls training. Under distributed training only
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
        self._known = {}
        self._created = set()
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

    def _run(self):
        while not self._stop.wait(self.interval):
            self._log()
        self._log()

    def _warn(self, error):
        if not self._warned:
            self._warned = True
            warnings.warn("VisdomSystemMonitor failed to log: {}".format(error))

    def _sample(self):
        tracked = {self._root.pid: self._root}
        for child in self._root.children(recursive=True):
            tracked[child.pid] = self._known.get(child.pid, child)
        self._known = tracked
        cpu = rss = 0
        for proc in tracked.values():
            try:
                proc_cpu = proc.cpu_percent(None)
                proc_rss = proc.memory_info().rss
            except self._psutil.NoSuchProcess:
                continue
            cpu += proc_cpu
            rss += proc_rss
        return cpu / (self._psutil.cpu_count() or 1), rss / MB

    def _log(self):
        x = time.monotonic() - self._t0
        try:
            cpu, ram = self._sample()
        except Exception as e:
            self._warn(e)
            return
        self._plot(CPU_WIN, "CPU usage (%)", x, cpu)
        self._plot(RAM_WIN, "RAM usage (MB)", x, ram)

    def _plot(self, win, title, x, value):
        try:
            if win in self._created:
                self.viz.line(
                    X=[x],
                    Y=[value],
                    win=win,
                    env=self.env,
                    update="append",
                    name="script",
                )
            elif self.viz.line(
                X=[x],
                Y=[value],
                win=win,
                env=self.env,
                name="script",
                opts={"title": title, "xlabel": "seconds", "ylabel": title},
            ):
                self._created.add(win)
        except Exception as e:
            self._warn(e)
