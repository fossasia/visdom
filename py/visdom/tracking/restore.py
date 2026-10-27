#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Read tracked-run files and replay their plots through a Visdom client.

Runs recorded with ``record_data=True`` store full plot calls in an
append-only ``.events.jsonl`` file. ``Visdom.restore_run`` is the public
entry point; the server's ``POST /restore_run`` endpoint reuses these helpers.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Callable, Iterable, Iterator, Optional


class RunRestoreError(Exception):
    """Raised when a run's recorded files can't be read back or replayed."""


def resolve_under_root(root_dir: str, rel_path: str) -> str:
    """Resolve a relative path under ``root_dir`` and reject traversal.

    Absolute paths, NUL bytes, and symlinks that leave the root are refused.
    """
    if not isinstance(rel_path, str) or "\x00" in rel_path:
        raise RunRestoreError("path must be a string with no NUL bytes")
    if os.path.isabs(rel_path):
        raise RunRestoreError(
            "path {0!r} must be relative to the allowed directory, not "
            "absolute".format(rel_path)
        )
    root_real = os.path.realpath(root_dir)
    candidate_real = os.path.realpath(os.path.join(root_dir, rel_path))
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


def resolve_run_events_path(json_path: str, metadata: dict) -> Optional[str]:
    """Return the validated events path, or ``None`` if it is missing.

    Resolve the metadata filename under the run directory to prevent a
    crafted file from pointing outside that directory.
    """
    events_name = metadata.get("events_file")
    if not events_name:
        return None
    run_dir = os.path.dirname(json_path) or "."
    events_path = resolve_under_root(run_dir, events_name)
    if not os.path.exists(events_path):
        return None
    return events_path


def iter_run_events(json_path: str, metadata: Optional[dict] = None) -> Iterator[dict]:
    """Yield events from the full log, falling back to ``recent_events``.

    Events are streamed one at a time. Invalid JSON lines are skipped so a
    partial write does not prevent reading the rest of the log.
    """
    if metadata is None:
        metadata = load_run_file(json_path)
    events_path = resolve_run_events_path(json_path, metadata)
    if events_path is None:
        for event in metadata.get("recent_events") or []:
            yield event
        return
    with open(events_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def load_run_events(json_path: str, metadata: Optional[dict] = None) -> list:
    """Return all events as a list. Use ``iter_run_events`` to stream them."""
    return list(iter_run_events(json_path, metadata))


def _iter_calls_from_event(event: dict) -> Iterator[dict]:
    """Yield captured calls from a ``plot_update`` event."""
    if not isinstance(event, dict) or event.get("type") != "plot_update":
        return
    data = event.get("data")
    if not isinstance(data, dict):
        return
    call = data.get("call")
    if isinstance(call, dict) and isinstance(call.get("msg"), dict):
        yield call
    raw_calls = data.get("calls")
    if isinstance(raw_calls, list):
        for one in raw_calls:
            if isinstance(one, dict) and isinstance(one.get("msg"), dict):
                yield one


def extract_replayable_calls(events: Iterable[dict]) -> list:
    """Collect captured plot calls from ``events`` in order."""
    calls = []
    for event in events:
        calls.extend(_iter_calls_from_event(event))
    return calls


#: Only plot creation and update calls can be replayed. Recorded endpoints
#: are untrusted, so this allowlist blocks calls to other server routes.
SUPPORTED_REPLAY_ENDPOINTS = frozenset({"events", "update"})


def validate_calls_for_replay(calls: Iterable[dict]) -> None:
    """Reject calls that target an unsupported endpoint."""
    for index, call in enumerate(calls):
        endpoint = call.get("endpoint")
        if endpoint not in SUPPORTED_REPLAY_ENDPOINTS:
            raise RunRestoreError(
                "recorded call {0} has an unsupported endpoint {1!r}; only "
                "{2} calls can be replayed".format(
                    index, endpoint, sorted(SUPPORTED_REPLAY_ENDPOINTS)
                )
            )


def retarget_calls(calls: Iterable[dict], eid: str) -> list:
    """Return call copies with each message pointed at ``eid``."""
    retargeted = []
    for call in calls:
        msg = dict(call.get("msg") or {})
        msg["eid"] = eid
        retargeted.append({"endpoint": call.get("endpoint"), "msg": msg})
    return retargeted


def validate_delay(delay: Optional[float]) -> Optional[float]:
    """Validate a replay delay before replay starts."""
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
    """Send one call and return an error string instead of raising.

    ``Visdom._send`` can return ``False`` on connection errors without
    raising, so treat that exact value as a failure too.
    """
    endpoint = call.get("endpoint")
    msg = call.get("msg")
    if not endpoint or not isinstance(msg, dict):
        return "skipped malformed call: {0!r}".format(call)
    try:
        result = send(msg, endpoint)
        if result is False:
            return (
                "{0} (win={1!r}) failed: send() returned False -- typically "
                "a connection/SSL failure that this client's "
                "`raise_exceptions` setting swallowed instead of "
                "raising".format(endpoint, msg.get("win"))
            )
        return None
    except Exception as e:
        return "{0} (win={1!r}) failed: {2}: {3}".format(
            endpoint, msg.get("win"), type(e).__name__, e
        )


def replay_calls(
    calls: list, send: Callable[[dict, str], Any], delay: Optional[float] = None
) -> dict:
    """Replay calls in order, optionally waiting between them."""
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
    """Choose the first recorded env, then the run name or client env."""
    for call in calls:
        msg = call.get("msg") or {}
        eid = msg.get("eid")
        if eid:
            return eid
    return metadata.get("name") or fallback_eid or "main"


def run_event_consistency_warning(metadata: dict, event_count: int) -> Optional[str]:
    """Warn if fewer events were read than the run metadata reports."""
    declared = metadata.get("event_count")
    if isinstance(declared, int) and declared > event_count:
        return (
            "run metadata reports {0} event(s) but only {1} could be read "
            "back -- the full .events.jsonl history may be missing, "
            "truncated, or unavailable, so this replay may be "
            "incomplete.".format(declared, event_count)
        )
    return None


def restore_run(
    json_path: str, vis, env: Optional[str] = None, delay: Optional[float] = None
) -> dict:
    """Load and replay a run through ``vis``. Used by ``Visdom.restore_run``."""
    if getattr(vis, "offline", False):
        raise RunRestoreError(
            "cannot restore_run with an offline Visdom client -- nothing it "
            "sends reaches a server, so there is nothing to meaningfully "
            "replay"
        )
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
    validate_calls_for_replay(calls)
    target_eid = env or default_target_eid(calls, metadata, getattr(vis, "env", None))
    calls = retarget_calls(calls, target_eid)

    def _send(msg, endpoint):
        return vis._send(msg, endpoint, from_log=True)

    summary = replay_calls(calls, _send, delay=delay)
    summary.update(
        {
            "run_id": metadata.get("run_id"),
            "name": metadata.get("name"),
            "status": metadata.get("status"),
            "eid": target_eid,
            "warning": run_event_consistency_warning(metadata, len(events)),
        }
    )
    return summary
