#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Reconstructs a tracked run's plots from the files it recorded.

``tracking.core.RunTracker(..., record_data=True)`` plus
``tracking.graphs.TrackedVisdom`` capture the exact wire message(s) every
tracked chart call produced, writing them to the run's full
``<run_id>.events.jsonl`` timeline (see ``tracking.core``'s module docstring
for why that file exists separately from the small, capped ``<run_id>.json``
metadata file -- replay always reads from the ``.jsonl`` file so a run longer
than ``recent_events_limit`` doesn't silently lose its earliest plots).

This module reads that pair of files back and replays the captured messages
against a live ``Visdom`` client: the ``Visdom`` -> JSON direction
``RunTracker`` already provides, run the other way. ``Visdom.restore_run`` is
the public entry point; the server's ``POST /restore_run`` endpoint (see
``visdom.server.handlers.tracking_restore_handler``) reuses the pieces here
directly rather than round-tripping through a client.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Callable, Iterable, Optional


class RunRestoreError(Exception):
    """Raised when a run's recorded files can't be read back or replayed."""


def resolve_under_root(root_dir: str, rel_path: str) -> str:
    """Resolve ``rel_path`` against ``root_dir``, refusing any path that
    would escape it.

    Mirrors the traversal protection the rest of the server applies to
    caller-supplied paths: a NUL byte, a ``..`` segment, an absolute path, or
    a symlink that resolves outside ``root_dir`` are all rejected rather than
    silently followed. ``root_dir`` itself is resolved first so a symlinked
    root doesn't make every legitimate path look like it "escapes".
    """
    if not isinstance(rel_path, str) or "\x00" in rel_path:
        raise RunRestoreError("path must be a string with no NUL bytes")
    root_real = os.path.realpath(root_dir)
    candidate = (
        rel_path if os.path.isabs(rel_path) else os.path.join(root_dir, rel_path)
    )
    candidate_real = os.path.realpath(candidate)
    if candidate_real != root_real and not candidate_real.startswith(
        root_real + os.sep
    ):
        raise RunRestoreError(
            "path {0!r} resolves outside the allowed directory".format(rel_path)
        )
    return candidate_real


def load_run_file(json_path: str) -> dict:
    """Read and parse a run's ``<run_id>.json`` metadata file."""
    try:
        with open(json_path, "r") as f:
            metadata = json.load(f)
    except FileNotFoundError:
        raise RunRestoreError("no run file found at {0!r}".format(json_path))
    except (OSError, ValueError) as e:
        raise RunRestoreError("could not read run file {0!r}: {1}".format(json_path, e))
    if not isinstance(metadata, dict) or "run_id" not in metadata:
        raise RunRestoreError(
            "{0!r} does not look like a visdom.tracking run file".format(json_path)
        )
    return metadata


def load_run_events(json_path: str, metadata: Optional[dict] = None) -> list:
    """Return every event in a run's full timeline, oldest first.

    Reads the run's ``<run_id>.events.jsonl`` file (named by
    ``metadata["events_file"]``, alongside ``json_path``) rather than the
    capped ``recent_events`` embedded in the metadata file itself -- a run
    with more events than ``recent_events_limit`` would otherwise silently
    lose its earliest plots on replay. Falls back to ``recent_events``,
    best-effort, if the ``.jsonl`` file is missing. Skips any line that
    fails to parse as JSON rather than failing the whole read over one
    corrupt line (e.g. a process that crashed mid-write).

    ``events_file`` is untrusted the same way ``json_path`` itself is: it
    comes straight out of the metadata file, which ``resolve_under_root``
    constrains for the *request's* path but says nothing about what's
    written inside it. ``RunTracker`` only ever writes a bare basename
    there, so anything else (an absolute path, a ``..`` segment, a symlink
    that resolves elsewhere) is refused via ``resolve_under_root`` again,
    this time scoped to ``json_path``'s own directory -- without this, a
    tampered or maliciously crafted metadata file could point this read at
    an arbitrary file on disk, entirely outside the boundary the request's
    own path was checked against.
    """
    if metadata is None:
        metadata = load_run_file(json_path)
    events_name = metadata.get("events_file")
    events_path = None
    if events_name:
        run_dir = os.path.dirname(json_path) or "."
        events_path = resolve_under_root(run_dir, events_name)
        if not os.path.exists(events_path):
            events_path = None
    if events_path is None:
        return list(metadata.get("recent_events") or [])
    events = []
    with open(events_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events


def extract_replayable_calls(events: Iterable[dict]) -> list:
    """Pull out, in order, every captured wire message from ``events``.

    A ``plot_update`` event optionally carries the message(s)
    ``tracking.graphs._capture_send`` recorded, under ``data["call"]`` (one
    message -- legacy/compact shape) or ``data["calls"]`` (a list -- see
    ``tracking.graphs.TrackedVisdom``, which can produce more than one wire
    message for a single Python-level call, e.g. ``learning_curve`` sending
    through an internal ``self.line()``). Only present when the run was
    tracked with ``record_data=True``; events from a run tracked without it
    are silently skipped, which is how ``restore_run`` ends up raising one
    clear "no replayable plot data recorded" error rather than a confusing
    per-event one.
    """
    calls = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "plot_update":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        call = data.get("call")
        if isinstance(call, dict) and isinstance(call.get("msg"), dict):
            calls.append(call)
        raw_calls = data.get("calls")
        if isinstance(raw_calls, list):
            for one in raw_calls:
                if isinstance(one, dict) and isinstance(one.get("msg"), dict):
                    calls.append(one)
    return calls


def retarget_calls(calls: Iterable[dict], eid: str) -> list:
    """Return copies of ``calls`` with every message's ``eid`` pointed at
    ``eid``.

    Always applied (never a no-op) so every replayed message ends up in the
    same, single environment regardless of which env(s) the original run
    happened to plot into -- see ``restore_run`` for how that target is
    chosen by default.
    """
    retargeted = []
    for call in calls:
        msg = dict(call.get("msg") or {})
        msg["eid"] = eid
        retargeted.append({"endpoint": call.get("endpoint"), "msg": msg})
    return retargeted


def validate_delay(delay: Optional[float]) -> Optional[float]:
    """Normalize/validate a replay pacing ``delay``.

    Raises ``ValueError`` up front -- before anything is replayed -- for a
    negative, boolean, non-finite, or otherwise non-numeric ``delay``,
    rather than failing partway through a replay or silently treating a bad
    value as "no delay".

    ``NaN``/``inf`` are rejected explicitly (not just "negative"): both
    compare false against ``< 0``, so without this check they would
    otherwise pass straight through as "valid". JSON itself has no
    literal for either, but Python's own decoder accepts the bare tokens
    ``NaN``/``Infinity``/``-Infinity`` (matching what it *writes* for a
    non-finite float -- see ``shared_utils.NanSafeEncoder`` -- so a request
    body containing one of those tokens for ``delay`` decodes straight to
    the float it names), so this still needs to be checked explicitly
    rather than assumed impossible by the time it gets here. A ``nan``
    reaching ``asyncio.sleep``/``time.sleep`` raises there instead -- after
    some calls may already have been replayed -- and an ``inf`` simply
    never returns.
    """
    if delay is None:
        return None
    if isinstance(delay, bool) or not isinstance(delay, (int, float)):
        raise ValueError("delay must be a number of seconds, got {0!r}".format(delay))
    value = float(delay)
    if not math.isfinite(value):
        raise ValueError(
            "delay must be a finite number of seconds, got {0!r}".format(delay)
        )
    if value < 0:
        raise ValueError("delay must be >= 0 seconds, got {0!r}".format(delay))
    return value


def _replay_one(call: dict, send: Callable[[dict, str], Any]) -> Optional[str]:
    """Resend one captured call via ``send(msg, endpoint)``.

    Returns ``None`` on success, or an error message on failure -- this
    never raises, so a replay of many calls can collect failures into a
    summary (see ``replay_calls``/``restore_run``) rather than aborting
    partway through over one bad call.
    """
    endpoint = call.get("endpoint")
    msg = call.get("msg")
    if not endpoint or not isinstance(msg, dict):
        return "skipped malformed call: {0!r}".format(call)
    try:
        send(msg, endpoint)
        return None
    except Exception as e:
        return "{0} (win={1!r}) failed: {2}: {3}".format(
            endpoint, msg.get("win"), type(e).__name__, e
        )


def replay_calls(
    calls: list, send: Callable[[dict, str], Any], delay: Optional[float] = None
) -> dict:
    """Resend ``calls`` in order via ``send(msg, endpoint)``, optionally
    paced ``delay`` seconds apart.

    Used by the synchronous client path (``Visdom.restore_run``, via
    ``time.sleep``). The server's ``POST /restore_run`` handler (see
    ``visdom.server.handlers.tracking_restore_handler``) does not call this
    directly -- blocking the server's single IO loop with ``time.sleep``
    for the whole replay would freeze every other request for its duration
    -- and instead reuses ``_replay_one`` itself in an ``async`` loop paced
    with ``await asyncio.sleep``.
    """
    delay = validate_delay(delay)
    errors = []
    replayed = 0
    last_index = len(calls) - 1
    for index, call in enumerate(calls):
        error = _replay_one(call, send)
        if error is None:
            replayed += 1
        else:
            errors.append(error)
        if delay and index < last_index:
            time.sleep(delay)
    return {
        "total": len(calls),
        "replayed": replayed,
        "failed": len(errors),
        "errors": errors,
    }


def default_target_eid(calls: list, metadata: dict, fallback_eid: Optional[str]) -> str:
    """Pick a target env when the caller didn't name one explicitly.

    Prefers the ``eid`` the run's own calls were originally sent to (the
    first captured call's, for a single, predictable choice even if -- in
    principle -- a run's calls touched more than one env), falling back to
    the run's ``name`` and finally to the client's own current env.
    """
    for call in calls:
        msg = call.get("msg") or {}
        eid = msg.get("eid")
        if eid:
            return eid
    return metadata.get("name") or fallback_eid or "main"


def run_event_consistency_warning(metadata: dict, events: list) -> Optional[str]:
    """Best-effort check between a run's declared event count and what
    could actually be read back for it.

    ``RunTracker`` documents a narrow gap of its own: the metadata write
    (which bumps ``event_count``) can succeed while the following
    ``.events.jsonl`` append then fails (see ``core.py``'s module
    docstring). ``load_run_events`` separately falls back to the capped
    ``recent_events`` entirely if the ``.jsonl`` file is missing outright.
    Either way, a replay built from fewer events than the run claims to
    have logged can be silently incomplete; this makes that visible in the
    result instead, rather than leaving "missing/corrupt history"
    indistinguishable from "nothing went wrong".
    """
    declared = metadata.get("event_count")
    if isinstance(declared, int) and declared > len(events):
        return (
            "run metadata reports {0} event(s) but only {1} could be read "
            "back -- the full .events.jsonl history may be missing, "
            "truncated, or unavailable, so this replay may be "
            "incomplete.".format(declared, len(events))
        )
    return None


def restore_run(
    json_path: str, vis, env: Optional[str] = None, delay: Optional[float] = None
) -> dict:
    """Implementation behind ``Visdom.restore_run`` -- see its docstring."""
    delay = validate_delay(delay)
    metadata = load_run_file(json_path)
    events = load_run_events(json_path, metadata)
    calls = extract_replayable_calls(events)
    if not calls:
        raise RunRestoreError(
            "{0!r} has no replayable plot data recorded. Only runs tracked "
            "with RunTracker(..., record_data=True) (or "
            "run.track(vis, record_data=True)) capture the wire messages "
            "restore_run needs; a run tracked without it only has enough "
            "to describe what happened, not to replay it.".format(json_path)
        )
    target_eid = env or default_target_eid(calls, metadata, getattr(vis, "env", None))
    calls = retarget_calls(calls, target_eid)

    def _send(msg, endpoint):
        vis._send(msg, endpoint, from_log=True)

    summary = replay_calls(calls, _send, delay=delay)
    summary.update(
        {
            "run_id": metadata.get("run_id"),
            "name": metadata.get("name"),
            "status": metadata.get("status"),
            "eid": target_eid,
            "warning": run_event_consistency_warning(metadata, events),
        }
    )
    return summary
