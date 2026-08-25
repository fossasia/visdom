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

# Terminal states: once set, a run's record is frozen.
_TERMINAL_STATUSES = (STATUS_FINISHED, STATUS_FAILED, STATUS_UNFINISHED)

DEFAULT_OUT_DIR = "visdom_runs"


DEFAULT_RECENT_EVENTS_LIMIT = 50


_MAX_SLUG_LEN = 100


_UNSET = object()


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

    This exists to fix several related problems with just passing arbitrary
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
    3. NumPy scalars (``np.float32``, ``np.int64``, ``np.bool_``, ...)
       aren't Python ``int``/``float``/``bool`` (only ``np.float64``
       happens to subclass ``float`` on most platforms -- everything else
       doesn't) and would otherwise fall through to the ``str()``
       fallback, silently turning e.g. a logged loss value into the
       *string* ``"0.4523"`` instead of the number ``0.4523``. Converted
       via ``.item()`` to the equivalent native Python type instead, since
       this is an extremely common case: numpy arrays/scalars are what
       most training loops actually produce.
    4. NumPy arrays would otherwise stringify via ``str(array)``, which
       truncates large arrays with ``...`` and isn't valid JSON or even
       reparseable Python (``"[1 2 3]"`` has no commas). Converted via
       ``.tolist()`` instead, which recursively yields plain nested
       Python lists/numbers.
    5. ``NaN``/``Infinity``/``-Infinity`` are not valid JSON (RFC 8259).
       Python's ``json`` module writes them anyway by default as bare
       ``NaN``/``Infinity``/``-Infinity`` tokens, which round-trips inside
       Python but breaks any stricter parser (e.g. JavaScript's
       ``JSON.parse``, most other languages' JSON libraries). This is also
       a very real case for this tool specifically, not just a
       theoretical one: "loss became NaN" is one of the most common
       training failure modes there is, and a reproducibility record
       should capture that cleanly rather than emit a file that then
       fails to parse elsewhere. Converted to the strings ``"NaN"``/
       ``"Infinity"``/``"-Infinity"`` instead.

    ``_max_depth`` guards against pathological self-referential or very
    deeply nested structures turning one bad call into a stack overflow.
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

        # Per-window bookkeeping for log_plot_update (see tracking.graphs):
        # reports "this is the Nth update to window 'loss', arriving
        # M seconds after the (N-1)th" without the caller having to track
        # any of that themselves.
        self._window_update_count: dict = {}
        self._window_last_update_monotonic: dict = {}

        ensure_dir_exists(out_dir)
        # Write-then-commit: build the "created" event but don't touch
        # jsonl or any counters yet. Attempt the metadata write first; only
        # if THAT succeeds do we commit anything, so a failure here leaves
        # zero files behind instead of an orphaned .events.jsonl with no
        # matching .json (see _build_event/_commit_event below).
        event, now_mono = self._build_event(
            "created", {"params": self.params, "tags": self.tags}
        )
        self._write(self.to_dict(pending_event=event))
        self._commit_event(event, now_mono)
        self._append_event_line(event)

        # Belt-and-braces: if the process ends without finish() ever being
        # called (crash, uncaught signal, forgotten call), leave the record
        # as "unfinished" rather than a permanently-stale "running". This
        # keeps a reference to self alive until finish()/atexit fires -- see
        # the module docstring's note on always finishing runs explicitly.
        atexit.register(self._atexit_finalize)

    # recording

    def _build_event(self, event_type: str, data: Optional[dict] = None):
        """Build a candidate event, deliberately without touching any of
        self's state yet.

        Returns ``(event, now_monotonic)``. Callers persist ``event`` via
        ``to_dict(pending_event=event)`` / ``_write()`` *first*; only once
        that succeeds do they call :meth:`_commit_event` to make it count
        in memory, then append it to the durable ``.jsonl`` log. This
        write-then-commit ordering is what makes the rollback logic this
        module used to need (snapshot fields, restore them in an
        ``except``) unnecessary: if the write never happens, self was
        never mutated in the first place, so there's nothing to undo.
        """
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
        """Record an event in memory. Only ever call this *after* the
        metadata write that included it (via ``pending_event``) has
        already succeeded -- see :meth:`_build_event`.
        """
        self.event_count = event["seq"]
        self._last_event_monotonic = now_mono
        self._recent_events.append(event)

    def _append_event_line(self, event: dict) -> None:
        """Append one event as a JSON line to the full on-disk timeline.

        O(1) in the number of events logged so far -- this is what keeps
        ``log_event`` cheap across very long runs, unlike rewriting the
        whole file (which the metadata file intentionally avoids doing
        with the full event history -- see ``to_dict``).

        Always called *after* the metadata write already succeeded (see
        ``log_event``/``set_param``/``_finish_locked``), so the metadata
        file -- the source of truth for ``status``/``params``/
        ``event_count`` -- is never left inconsistent by a failure here.
        The narrow remaining gap: if this specific call fails, the
        ``.jsonl`` full history can be missing the line for an event the
        metadata file already confirms happened. That's a real but minor
        limitation (documented in the module docstring) rather than
        something silently swept under the rug.
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

        Note: in the rare case where the metadata write succeeds but the
        subsequent ``.jsonl`` append then fails, this can raise even
        though the event was already durably recorded in the metadata
        file's ``event_count``/``recent_events``. The full ``.jsonl``
        history may be missing this one line in that specific case.
        """
        with self._lock:
            self._reject_if_terminal("log an event on")
            event, now_mono = self._build_event(event_type, data)
            # Attempt the durable write with this event included *before*
            # touching self.event_count/_recent_events. If this raises,
            # self is untouched -- no rollback needed, log_event can just
            # be called again.
            self._write(self.to_dict(pending_event=event))
            self._commit_event(event, now_mono)
            self._append_event_line(event)
        return event

    def set_param(self, key: str, value: Any) -> None:
        """Record/replace a parameter value, timestamped as an event too.

        Note: as with :meth:`log_event`, this can raise in the rare case
        where the metadata write succeeded but the trailing ``.jsonl``
        append then failed -- ``self.params`` will already reflect the
        new value.
        """
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
        """Log one graph/plot update, with per-window sequence and timing.

        Meant to be called by :mod:`visdom.tracking.graphs` (or anything
        else wrapping a Visdom instance), not typically by hand: it answers
        "is this the first update to this window, and if not, how long
        since the last one" so a plotted metric's own cadence shows up in
        the record, not just the run's global event timeline.

        Note: as with :meth:`log_event`, this can raise in the rare case
        where the metadata write succeeded but the trailing ``.jsonl``
        append then failed -- the per-window counters will already
        reflect this update.
        """
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
            # Same write-then-commit ordering as log_event/set_param: the
            # per-window counters below are only committed after the
            # metadata write (including this event) has actually
            # succeeded, so a failure can't leave self._window_update_count
            # claiming an update was recorded when it wasn't.
            self._write(self.to_dict(pending_event=event))
            self._window_update_count[win] = seq
            self._window_last_update_monotonic[win] = now
            self._commit_event(event, now_mono)
            self._append_event_line(event)
        return event

    def track(self, vis):
        """Wrap a ``Visdom`` instance so its graph calls auto-log here.

        Returns a thin proxy -- see :class:`visdom.tracking.graphs.TrackedVisdom`
        -- that behaves exactly like ``vis`` except that calls to chart
        methods (``line``, ``scatter``, ``bar``, ...) also call
        :meth:`log_plot_update` for you. Everything else (``vis.image()``,
        ``vis.close()``, attribute access, ...) passes straight through.

            run = RunTracker("exp1", params={...})
            tvis = run.track(vis)
            tvis.line(X=..., Y=..., win="loss")  # auto-logged

        Imported lazily to avoid a circular import (``graphs`` depends on
        this module for type hints, not the other way around).
        """
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
        self, status: str = STATUS_FINISHED, reason: Optional[str] = None
    ) -> None:
        """Mark the run terminal (``finished`` or ``failed``) and persist it.

        ``reason`` is optional here since a deliberate ``finish()`` call
        doesn't need explaining -- it's ``unfinished`` runs (see
        :meth:`_atexit_finalize` / the context-manager path) where a reason
        actually earns its place in the record.

        Note: in the rare case where the metadata write succeeds but the
        subsequent (best-effort) full-history ``.jsonl`` append then
        fails, this can raise even though ``self.status``/the metadata
        file already correctly show the run as terminal. Check
        ``self.status`` in an ``except`` block before assuming the run
        didn't finish -- a second ``finish()`` call in that situation
        correctly raises ``RunAlreadyFinishedError``, not because it
        failed, but because it already succeeded.
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
        system clock adjustment mid-run (see ``_build_event``).
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
        """Build the metadata payload.

        With no arguments, reflects the currently *committed* state --
        this is what plain introspection and ``_write()``'s default use.

        The keyword-only overrides exist for the write-then-commit pattern
        used throughout this class (see ``log_event``/``set_param``/
        ``_finish_locked``): a caller about to change ``status``,
        ``stop_reason``, ``end_time``, ``params``, and/or add a new event
        can render the *candidate* resulting payload here -- without
        mutating ``self`` at all -- attempt to persist it, and only touch
        ``self`` afterwards, once persisting has actually succeeded. That
        ordering is what lets a failed write be handled by simply not
        committing anything, rather than needing to mutate first and roll
        back on failure.
        """
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
            "start_time": self.start_time,
            "end_time": resolved_end_time,
            "total_duration": resolved_total_duration,
            "stop_reason": resolved_stop_reason,
            "event_count": event_count,
            "events_file": os.path.basename(self.events_path),
            "recent_events": recent_events,
        }

    def _write(self, payload: Optional[dict] = None) -> None:
        """Persist ``payload`` (or the current committed state if omitted),
        atomically (write to tmp, then rename).

        Deliberately does *not* include the full event history -- see
        ``to_dict``/``_append_event_line`` -- so this file's write cost
        stays roughly constant no matter how many events a run has logged.
        Every mutation calls this, so a crash between two events still
        leaves a readable, complete-up-to-that-point metadata file on disk.
        """
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
