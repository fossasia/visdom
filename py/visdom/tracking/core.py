#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
A run produces two files under ``out_dir``:

- ``<run_id>.json`` -- small, roughly constant-size metadata: params, tags,
  environment snapshot, status, timing, and only the most recent events (see
  ``recent_events_limit``). Safe to read at any time, including while the
  run is still in progress.
- ``<run_id>.events.jsonl`` -- the *complete* event timeline, one JSON
  object per line, appended to (never rewritten). This is what keeps
  ``log_event`` cheap even across a run with hundreds of thousands of calls:
  each call appends one line instead of re-serializing everything logged so
  far.
"""

from __future__ import annotations

import atexit
import collections
import json
import math
import os
import platform
import socket
import threading
import time
import uuid
from typing import Any, Optional

import numpy as np

from visdom.utils.shared_utils import ensure_dir_exists

STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
STATUS_UNFINISHED = "unfinished"

_TERMINAL_STATUSES = (STATUS_FINISHED, STATUS_FAILED, STATUS_UNFINISHED)

DEFAULT_OUT_DIR = "visdom_runs"

#: How long ``finish()`` and ``__exit__`` wait for tracked calls to finish.
DEFAULT_FINISH_WAIT_TIMEOUT = 5.0


DEFAULT_RECENT_EVENTS_LIMIT = 50


_MAX_SLUG_LEN = 100


_UNSET = object()


class RunAlreadyFinishedError(Exception):
    """Raised when trying to modify a run that already reached a terminal state."""


def _slugify(name: str) -> str:
    """Make ``name`` safe and short enough for a filename."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    safe = safe.encode("utf-8")[:_MAX_SLUG_LEN].decode("utf-8", errors="ignore")
    return safe or "run"


def _json_safe(value: Any, _depth: int = 0, _max_depth: int = 20) -> Any:
    """Convert values to JSON-safe copies, including NumPy values.

    Mutable inputs are copied so later changes do not alter logged events.
    Non-finite floats become strings, and ``_max_depth`` limits recursion.
    """
    if _depth > _max_depth:
        return "<max nesting depth exceeded>"

    if isinstance(value, (np.floating, np.integer, np.bool_)):
        try:
            return _json_safe(value.item(), _depth, _max_depth)
        except Exception:
            pass  # fall through to the str() fallback below

    if isinstance(value, np.ndarray):
        try:
            return _json_safe(value.tolist(), _depth, _max_depth)
        except Exception:
            pass  # fall through to the str() fallback below

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v, _depth + 1, _max_depth) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v, _depth + 1, _max_depth) for v in value]
    try:
        return str(value)
    except Exception as e:
        return "<unrepresentable {0}: {1}>".format(type(value).__name__, e)


def _safe_exc_str(exc: BaseException) -> str:
    """``str(exc)``, but never raises even if the exception's __str__ does."""
    try:
        return str(exc)
    except Exception:
        return "<exception message unavailable>"


def _capture_environment() -> dict:
    """Best-effort snapshot of the machine/interpreter a run executed under.

    Every field is wrapped so one missing/failing lookup (e.g. no network for
    ``gethostname`` in a sandboxed container) can't take down the rest of the
    snapshot -- a partial environment block is far more useful than none.
    """
    env: dict[str, Any] = {}

    def _safe(key, fn):
        try:
            env[key] = fn()
        except Exception:
            env[key] = None

    _safe("python_version", platform.python_version)
    _safe("python_implementation", platform.python_implementation)
    _safe("platform", platform.platform)
    _safe("processor", platform.processor)
    _safe("hostname", socket.gethostname)
    _safe("cpu_count", os.cpu_count)
    _safe("pid", os.getpid)
    _safe("cwd", os.getcwd)
    env["packages"] = _capture_packages()
    env["gpus"] = _capture_gpus()
    return env


def _capture_packages() -> dict:
    """Return ``{distribution_name: version}`` for every installed package.

    Uses the standard library only (``importlib.metadata``), so recording an
    environment never requires a new dependency.
    """
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:
        return {}
    packages = {}
    try:
        for dist in importlib_metadata.distributions():
            try:
                name = dist.metadata["Name"]
            except Exception:
                name = None
            if name:
                packages[name] = dist.version
    except Exception:
        return {}
    return packages


def _capture_gpus() -> list:
    """Return a best-effort list of visible GPU names, or ``[]`` if unknown.

    Tries ``torch`` first (most common in this ecosystem), then falls back to
    ``nvidia-smi`` if it's on ``PATH``. Neither is required -- both failures
    are silent since most environments will have neither.
    """
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return [
                torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
            ]
        return []
    except Exception:
        pass
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []


class RunTracker:
    """Records one experiment run's parameters, timeline and outcome to disk.

    One tracker == one run. Create as many as you need, even for the same
    Visdom env -- each gets its own ``run_id`` and its own files under
    ``out_dir``, so nothing here assumes an env maps to a single experiment.
    """

    STATUS_RUNNING = STATUS_RUNNING
    STATUS_FINISHED = STATUS_FINISHED
    STATUS_FAILED = STATUS_FAILED
    STATUS_UNFINISHED = STATUS_UNFINISHED

    def __init__(
        self,
        name: str,
        params: Optional[dict] = None,
        out_dir: str = DEFAULT_OUT_DIR,
        tags: Optional[dict] = None,
        capture_environment: bool = True,
        recent_events_limit: int = DEFAULT_RECENT_EVENTS_LIMIT,
        record_data: bool = False,
    ):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        self.name = name
        self.run_id = "{0}_{1}_{2}".format(
            _slugify(name), time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:8]
        )
        self.out_dir = out_dir
        self.path = os.path.join(out_dir, self.run_id + ".json")
        self.events_path = os.path.join(out_dir, self.run_id + ".events.jsonl")
        # Capture plot messages for replay when enabled; this can increase
        # event log size, so it is off by default.
        self.record_data = bool(record_data)

        self._lock = threading.Lock()
        # finish() waits for active calls to record their events.
        self._active_calls = 0
        self._active_calls_cv = threading.Condition(self._lock)
        self.status = STATUS_RUNNING
        # _json_safe rebuilds params/tags into fresh, guaranteed-serializable
        # objects, which also means later caller-side mutation of whatever
        # they originally passed in can no longer change what's on disk.
        self.params = _json_safe(dict(params or {}))
        self.tags = _json_safe(dict(tags or {}))
        self.start_time = time.time()
        self._start_monotonic = time.monotonic()
        self.end_time: Optional[float] = None
        self._end_monotonic: Optional[float] = None
        self.stop_reason: Optional[str] = None
        self.environment = _capture_environment() if capture_environment else {}
        # Stored with the run so workspace-scoped restores can verify its
        # owner. Keyless clients leave this unset.
        self.workspace: Optional[str] = None

        self._recent_events: "collections.deque[dict]" = collections.deque(
            maxlen=max(1, recent_events_limit)
        )
        self.event_count = 0
        self._last_event_monotonic = self._start_monotonic

        # Track update counts and timing for each window.
        self._window_update_count: dict = {}
        self._window_last_update_monotonic: dict = {}

        ensure_dir_exists(out_dir)
        # Write metadata before committing the event so a failed write does
        # not leave an orphaned event log.
        event, now_mono = self._build_event(
            "created", {"params": self.params, "tags": self.tags}
        )
        self._write(self.to_dict(pending_event=event))
        self._commit_event(event, now_mono)
        self._append_event_line(event)

        # Mark the run unfinished at exit if finish() was never called.
        atexit.register(self._atexit_finalize)

    # recording

    def _build_event(self, event_type: str, data: Optional[dict] = None):
        """Build an event without changing tracker state."""
        now_wall = time.time()
        now_mono = time.monotonic()
        event = {
            "seq": self.event_count + 1,
            "type": event_type,
            "time": now_wall,
            # Deltas are computed from a monotonic clock, not wall time, so
            # a system clock adjustment (NTP sync, DST, manual change)
            # during a long run can't produce a negative duration here.
            "delta_from_start": round(now_mono - self._start_monotonic, 6),
            "delta_from_prev": round(now_mono - self._last_event_monotonic, 6),
        }
        if data:
            event["data"] = _json_safe(data)
        return event, now_mono

    def _commit_event(self, event: dict, now_mono: float) -> None:
        """Commit a successfully written event to memory."""
        self.event_count = event["seq"]
        self._last_event_monotonic = now_mono
        self._recent_events.append(event)

    def _append_event_line(self, event: dict) -> None:
        """Append one event to the full JSONL timeline."""
        line = json.dumps(event, default=str, allow_nan=False) + "\n"
        with open(self.events_path, "a") as f:
            f.write(line)

    # in-flight call bookkeeping (see finish())

    def _begin_call(self) -> bool:
        """Register an active plot call, or return ``False`` if finished."""
        with self._lock:
            if self.status in _TERMINAL_STATUSES:
                return False
            self._active_calls += 1
            return True

    def _end_call(self) -> None:
        """Unregister a call and wake ``finish()`` when none remain."""
        with self._active_calls_cv:
            self._active_calls = max(0, self._active_calls - 1)
            if self._active_calls == 0:
                self._active_calls_cv.notify_all()

    # compact recent_events/metadata representation

    _HEAVY_PAYLOAD_KEYS = ("call", "calls")

    @classmethod
    def _compact_event(cls, event: dict) -> dict:
        """Drop replay payloads from the capped metadata event copy."""
        data = event.get("data")
        if not isinstance(data, dict) or not any(
            key in data for key in cls._HEAVY_PAYLOAD_KEYS
        ):
            return event
        compact = dict(event)
        data = dict(data)
        call = data.get("call")
        if isinstance(call, dict):
            data["call"] = {"endpoint": call.get("endpoint")}
        calls = data.get("calls")
        if isinstance(calls, list):
            data["calls"] = {"count": len(calls)}
        compact["data"] = data
        return compact

    def log_event(self, event_type: str, **data) -> dict:
        """Append a timestamped event, such as an epoch milestone."""
        with self._lock:
            self._reject_if_terminal("log an event on")
            event, now_mono = self._build_event(event_type, data)
            compact = self._compact_event(event)
            # Attempt the durable write with this event included *before*
            # touching self.event_count/_recent_events. If this raises,
            # self is untouched -- no rollback needed, log_event can just
            # be called again.
            self._write(self.to_dict(pending_event=compact))
            self._commit_event(compact, now_mono)
            self._append_event_line(event)
        return event

    def set_param(self, key: str, value: Any) -> None:
        """Set a parameter and record the change as an event."""
        with self._lock:
            self._reject_if_terminal("set a param on")
            key = str(key)
            safe_value = _json_safe(value)
            candidate_params = dict(self.params)
            candidate_params[key] = safe_value
            event, now_mono = self._build_event(
                "param_set", {"key": key, "value": safe_value}
            )
            # Same write-then-commit ordering as log_event: attempt the
            # write with the *candidate* params dict, without touching
            # self.params yet. A failure here leaves self.params exactly
            # as it was
            self._write(self.to_dict(pending_event=event, params=candidate_params))
            self.params = candidate_params
            self._commit_event(event, now_mono)
            self._append_event_line(event)

    def log_plot_update(self, method: str, win: Optional[str], **extra) -> dict:
        """Record a plot update with its window sequence and timing."""
        with self._lock:
            self._reject_if_terminal("log a plot update on")
            now = time.monotonic()
            prev = self._window_last_update_monotonic.get(win)
            seq = self._window_update_count.get(win, 0) + 1
            data = {
                "method": method,
                "win": win,
                "window_update_seq": seq,
                "seconds_since_prev_update_to_window": (
                    None if prev is None else round(now - prev, 6)
                ),
            }
            data.update(extra)
            event, now_mono = self._build_event("plot_update", data)
            # Keep full replay data in the event log, not metadata.
            compact = self._compact_event(event)
            # Same write-then-commit ordering as log_event/set_param: the
            # per-window counters below are only committed after the
            # metadata write (including this event) has actually
            # succeeded, so a failure can't leave self._window_update_count
            # claiming an update was recorded when it wasn't.
            self._write(self.to_dict(pending_event=compact))
            self._window_update_count[win] = seq
            self._window_last_update_monotonic[win] = now
            self._commit_event(compact, now_mono)
            self._append_event_line(event)
        return event

    def track(self, vis):
        """Wrap ``vis`` so chart calls are logged with this run."""
        self.workspace = getattr(vis, "workspace", None)

        from visdom.tracking.graphs import TrackedVisdom

        return TrackedVisdom(vis, self)

    # lifecycle

    def _reject_if_terminal(self, action: str) -> None:
        if self.status in _TERMINAL_STATUSES:
            raise RunAlreadyFinishedError(
                "run {0!r} is {1!r}; cannot {2} a finished run".format(
                    self.run_id, self.status, action
                )
            )

    def finish(
        self,
        status: str = STATUS_FINISHED,
        reason: Optional[str] = None,
        timeout: Optional[float] = DEFAULT_FINISH_WAIT_TIMEOUT,
    ) -> None:
        """Mark the run finished or failed and save it.

        Wait up to ``timeout`` seconds for active plot calls to finish.
        Pass ``None`` to wait indefinitely or ``0`` to skip the wait.
        """
        if status not in (STATUS_FINISHED, STATUS_FAILED):
            raise ValueError(
                "finish status must be {0!r} or {1!r}, got {2!r}".format(
                    STATUS_FINISHED, STATUS_FAILED, status
                )
            )
        with self._active_calls_cv:
            self._reject_if_terminal("finish")
            self._wait_for_active_calls_locked(timeout)
            self._finish_locked(status, reason)

    def _wait_for_active_calls_locked(self, timeout: Optional[float]) -> None:
        """Wait for active calls to finish. The condition lock must be held."""
        if timeout is not None and timeout <= 0:
            return
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._active_calls > 0:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                break
            self._active_calls_cv.wait(remaining)

    def _finish_locked(self, status: str, reason: Optional[str]) -> None:
        end_time = time.time()
        end_monotonic = time.monotonic()
        event, now_mono = self._build_event(
            "status_change", {"status": status, "reason": reason}
        )
        self._write(
            self.to_dict(
                pending_event=event,
                status=status,
                stop_reason=reason,
                end_time=end_time,
                end_monotonic=end_monotonic,
            )
        )
        self.status = status
        self.stop_reason = reason
        self.end_time = end_time
        self._end_monotonic = end_monotonic
        self._commit_event(event, now_mono)
        try:
            self._append_event_line(event)
        finally:
            # The metadata write above already succeeded and is the
            # source of truth for `status`, so unregister regardless of
            # whether this last (best-effort, supplementary) full-history
            # append succeeds -- a correctly-finished run shouldn't keep
            # the atexit reference alive just because this line failed.
            try:
                atexit.unregister(self._atexit_finalize)
            except Exception:
                pass

    def _atexit_finalize(self) -> None:
        """Mark the run unfinished if the process exits before ``finish()``."""
        with self._lock:
            if self.status not in _TERMINAL_STATUSES:
                self._finish_locked(
                    STATUS_UNFINISHED,
                    "process exited before finish() was called",
                )

    @property
    def total_duration(self) -> Optional[float]:
        """Elapsed seconds, or ``None`` while the run is active."""
        if self._end_monotonic is None:
            return None
        return self._end_monotonic - self._start_monotonic

    # context manager

    def __enter__(self) -> "RunTracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Finish the run when leaving a context and wait for active calls."""
        with self._active_calls_cv:
            if self.status in _TERMINAL_STATUSES:
                return False
            self._wait_for_active_calls_locked(DEFAULT_FINISH_WAIT_TIMEOUT)
            if exc_type is None:
                self._finish_locked(STATUS_FINISHED, None)
            else:
                reason = "{0}: {1}".format(exc_type.__name__, _safe_exc_str(exc))
                self._finish_locked(STATUS_UNFINISHED, reason)
        return False

    # persistence

    def to_dict(
        self,
        *,
        pending_event: Optional[dict] = None,
        status: Any = _UNSET,
        stop_reason: Any = _UNSET,
        end_time: Any = _UNSET,
        end_monotonic: Any = _UNSET,
        params: Any = _UNSET,
    ) -> dict:
        """Build metadata for the current state or pending changes."""
        resolved_status = self.status if status is _UNSET else status
        resolved_stop_reason = (
            self.stop_reason if stop_reason is _UNSET else stop_reason
        )
        resolved_end_time = self.end_time if end_time is _UNSET else end_time
        resolved_end_monotonic = (
            self._end_monotonic if end_monotonic is _UNSET else end_monotonic
        )
        resolved_params = self.params if params is _UNSET else params

        resolved_total_duration = None
        if resolved_end_monotonic is not None:
            resolved_total_duration = resolved_end_monotonic - self._start_monotonic

        recent_events = list(self._recent_events)
        event_count = self.event_count
        if pending_event is not None:
            recent_events.append(pending_event)
            limit = self._recent_events.maxlen
            if limit is not None and len(recent_events) > limit:
                recent_events = recent_events[-limit:]
            event_count = pending_event["seq"]

        return {
            "run_id": self.run_id,
            "name": self.name,
            "status": resolved_status,
            "params": resolved_params,
            "tags": self.tags,
            "environment": self.environment,
            "workspace": self.workspace,
            "start_time": self.start_time,
            "end_time": resolved_end_time,
            "total_duration": resolved_total_duration,
            "stop_reason": resolved_stop_reason,
            "event_count": event_count,
            "events_file": os.path.basename(self.events_path),
            "recent_events": recent_events,
        }

    def _write(self, payload: Optional[dict] = None) -> None:
        """Atomically save metadata without rewriting the full event log."""
        if payload is None:
            payload = self.to_dict()
        tmp_path = self.path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(payload, f, indent=2, default=str, allow_nan=False)
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise
