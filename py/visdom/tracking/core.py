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
import os
import platform
import socket
import threading
import time
import uuid
from typing import Any, Optional

from visdom.utils.shared_utils import ensure_dir_exists

STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
STATUS_UNFINISHED = "unfinished"


_TERMINAL_STATUSES = (STATUS_FINISHED, STATUS_FAILED, STATUS_UNFINISHED)

DEFAULT_OUT_DIR = "visdom_runs"


DEFAULT_RECENT_EVENTS_LIMIT = 50


_MAX_SLUG_LEN = 100


class RunAlreadyFinishedError(Exception):
    """Raised when trying to modify a run that already reached a terminal state."""


def _slugify(name: str) -> str:
    """Return ``name`` made safe (and short enough) for use in a filename.

    Keeps things simple and dependency-free: alnum/dash/underscore/dot
    survive, everything else (path separators included) becomes ``_`` so a
    run name can never escape ``out_dir`` or collide with OS-reserved
    characters. Truncated to ``_MAX_SLUG_LEN`` so an overly long name can't
    push the final filename past OS limits.
    """
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    safe = safe[:_MAX_SLUG_LEN]
    return safe or "run"


def _json_safe(value: Any, _depth: int = 0, _max_depth: int = 20) -> Any:
    """Recursively rebuild ``value`` into something guaranteed JSON-safe.

    This exists to fix two related problems with just passing arbitrary
    caller data straight to ``json.dump(..., default=str)``:

    1. A single value whose ``__str__`` itself raises would otherwise make
       *every* future write for the run fail (the bad value never leaves
       the in-memory history, so every subsequent write re-encounters it).
       Here, a failing ``str()`` is caught and replaced with a placeholder
       instead of propagating.
    2. Passing a mutable object (e.g. a dict) straight through means a
       caller mutating it later silently changes what a *previous* log
       entry would re-serialize as. Rebuilding dicts/lists into new
       objects here breaks that aliasing at the point of logging, not at
       write time.

    ``_max_depth`` guards against pathological self-referential or very
    deeply nested structures turning one bad call into a stack overflow.
    """
    if _depth > _max_depth:
        return "<max nesting depth exceeded>"
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
    except ImportError:  # pragma: no cover - py < 3.8, unsupported by visdom
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

        self._lock = threading.Lock()
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

        self._recent_events: "collections.deque[dict]" = collections.deque(
            maxlen=max(1, recent_events_limit)
        )
        self.event_count = 0
        self._last_event_monotonic = self._start_monotonic

        ensure_dir_exists(out_dir)
        self._add_event("created", {"params": self.params, "tags": self.tags})
        self._write()

        atexit.register(self._atexit_finalize)

    # recording

    def _add_event(self, event_type: str, data: Optional[dict] = None) -> dict:
        now_wall = time.time()
        now_mono = time.monotonic()
        seq = self.event_count + 1
        event = {
            "seq": seq,
            "type": event_type,
            "time": now_wall,
            "delta_from_start": round(now_mono - self._start_monotonic, 6),
            "delta_from_prev": round(now_mono - self._last_event_monotonic, 6),
        }
        if data:
            event["data"] = _json_safe(data)

        self._append_event_line(event)
        self.event_count = seq
        self._last_event_monotonic = now_mono
        self._recent_events.append(event)
        return event

    def _append_event_line(self, event: dict) -> None:
        """Append one event as a JSON line to the full on-disk timeline.

        O(1) in the number of events logged so far -- this is what keeps
        ``log_event`` cheap across very long runs, unlike rewriting the
        whole file (which the metadata file below intentionally avoids
        doing with the full event history).
        """
        line = json.dumps(event, default=str) + "\n"
        with open(self.events_path, "a") as f:
            f.write(line)

    def log_event(self, event_type: str, **data) -> dict:
        """Append a timestamped event to this run's timeline and persist it.

        Free-form: use it for milestones the graph-level hooks in a later
        part won't catch on their own, e.g. ``run.log_event("epoch_end",
        epoch=3, loss=0.21)``. Every call records how long it's been since
        the run started and since the previous event.
        """
        with self._lock:
            self._reject_if_terminal("log an event on")
            event = self._add_event(event_type, data)
            self._write()
        return event

    def set_param(self, key: str, value: Any) -> None:
        """Record/replace a parameter value, timestamped as an event too."""
        with self._lock:
            self._reject_if_terminal("set a param on")
            key = str(key)
            had_key = key in self.params
            prev_value = self.params.get(key)
            safe_value = _json_safe(value)
            self.params[key] = safe_value
            try:
                self._add_event("param_set", {"key": key, "value": safe_value})
                self._write()
            except Exception:
                # Same reasoning as _finish_locked: don't let self.params
                # claim a value that was never actually persisted.
                if had_key:
                    self.params[key] = prev_value
                else:
                    self.params.pop(key, None)
                raise

    # lifecycle

    def _reject_if_terminal(self, action: str) -> None:
        if self.status in _TERMINAL_STATUSES:
            raise RunAlreadyFinishedError(
                "run {0!r} is {1!r}; cannot {2} a finished run".format(
                    self.run_id, self.status, action
                )
            )

    def finish(
        self, status: str = STATUS_FINISHED, reason: Optional[str] = None
    ) -> None:
        """Mark the run terminal (``finished`` or ``failed``) and persist it.

        ``reason`` is optional here since a deliberate ``finish()`` call
        doesn't need explaining -- it's ``unfinished`` runs (see
        :meth:`_atexit_finalize` / the context-manager path) where a reason
        actually earns its place in the record.
        """
        if status not in (STATUS_FINISHED, STATUS_FAILED):
            raise ValueError(
                "finish status must be {0!r} or {1!r}, got {2!r}".format(
                    STATUS_FINISHED, STATUS_FAILED, status
                )
            )
        with self._lock:
            self._reject_if_terminal("finish")
            self._finish_locked(status, reason)

    def _finish_locked(self, status: str, reason: Optional[str]) -> None:
        prev_status = self.status
        prev_reason = self.stop_reason
        prev_end_time = self.end_time
        prev_end_monotonic = self._end_monotonic

        self.status = status
        self.stop_reason = reason
        self.end_time = time.time()
        self._end_monotonic = time.monotonic()
        try:
            self._add_event("status_change", {"status": status, "reason": reason})
            self._write()
        except Exception:
            self.status = prev_status
            self.stop_reason = prev_reason
            self.end_time = prev_end_time
            self._end_monotonic = prev_end_monotonic
            raise
        try:
            atexit.unregister(self._atexit_finalize)
        except Exception:
            pass

    def _atexit_finalize(self) -> None:
        """Catch the process ending without an explicit finish() call.

        Fires on normal interpreter shutdown, ``sys.exit()``, and most
        uncaught exceptions/``KeyboardInterrupt`` -- not on ``os._exit()``,
        ``SIGKILL``, or a hard crash, which no in-process hook can observe.
        """
        with self._lock:
            if self.status not in _TERMINAL_STATUSES:
                self._finish_locked(
                    STATUS_UNFINISHED,
                    "process exited before finish() was called",
                )

    @property
    def total_duration(self) -> Optional[float]:
        """Seconds between start and end, or ``None`` while still running.

        Computed from a monotonic clock so it can't go negative from a
        system clock adjustment mid-run (see ``_add_event``).
        """
        if self._end_monotonic is None:
            return None
        return self._end_monotonic - self._start_monotonic

    # context manager

    def __enter__(self) -> "RunTracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        with self._lock:
            if self.status in _TERMINAL_STATUSES:
                return False
            if exc_type is None:
                self._finish_locked(STATUS_FINISHED, None)
            else:
                reason = "{0}: {1}".format(exc_type.__name__, _safe_exc_str(exc))
                self._finish_locked(STATUS_UNFINISHED, reason)
        return False  # never swallow the exception

    # persistence

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "params": self.params,
            "tags": self.tags,
            "environment": self.environment,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration": self.total_duration,
            "stop_reason": self.stop_reason,
            "event_count": self.event_count,
            "events_file": os.path.basename(self.events_path),
            "recent_events": list(self._recent_events),
        }

    def _write(self) -> None:
        """Persist current metadata, atomically (write to tmp, then rename).

        Deliberately does *not* include the full event history -- see
        ``to_dict``/``_append_event_line`` -- so this file's write cost
        stays roughly constant no matter how many events a run has logged.
        Every mutation calls this, so a crash between two events still
        leaves a readable, complete-up-to-that-point metadata file on disk.
        """
        tmp_path = self.path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(self.to_dict(), f, indent=2, default=str)
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise
