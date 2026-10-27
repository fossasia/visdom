#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
``POST /restore_run`` -- the server-side counterpart to ``Visdom.restore_run``
(see ``visdom.tracking.restore``). Reads a tracked run's recorded files and
replays its plots directly into this server's own state, without needing a
Python client in between.
"""

import asyncio
import json
import os
from typing import Optional

import tornado.escape
import tornado.web

from visdom.server.handlers.base_handlers import BaseHandler
from visdom.tracking.core import DEFAULT_OUT_DIR
from visdom.tracking.restore import (
    SUPPORTED_REPLAY_ENDPOINTS,
    RunRestoreError,
    _iter_calls_from_event,
    _replay_one,
    default_target_eid,
    iter_run_events,
    load_run_file,
    resolve_run_events_path,
    resolve_under_root,
    retarget_calls,
    run_event_consistency_warning,
    validate_calls_for_replay,
    validate_delay,
)
from visdom.utils.server_utils import (
    broadcast_envs,
    check_auth,
    check_readonly_message,
    ensure_env_loaded,
    register_window,
    run_on_storage_executor,
    save_env_off_loop,
    window,
)

#: Root directory for run files. Override with ``VISDOM_TRACKING_DIR``.
TRACKING_ROOT = os.environ.get("VISDOM_TRACKING_DIR", os.path.abspath(DEFAULT_OUT_DIR))

#: Maximum delay between calls. Override with
#: ``VISDOM_MAX_RESTORE_DELAY_SECONDS``.
MAX_DELAY_SECONDS = float(os.environ.get("VISDOM_MAX_RESTORE_DELAY_SECONDS", "60"))

#: Maximum calls per request. Override with ``VISDOM_MAX_RESTORE_CALLS``.
MAX_RESTORE_CALLS = int(os.environ.get("VISDOM_MAX_RESTORE_CALLS", "20000"))

#: Maximum size of each run file. Override with
#: ``VISDOM_MAX_RESTORE_FILE_BYTES``.
MAX_RESTORE_FILE_BYTES = int(
    os.environ.get("VISDOM_MAX_RESTORE_FILE_BYTES", str(256 * 1024 * 1024))
)

#: Maximum total pacing time per request. Override with
#: ``VISDOM_MAX_RESTORE_TOTAL_SECONDS``.
MAX_TOTAL_REPLAY_SECONDS = float(
    os.environ.get("VISDOM_MAX_RESTORE_TOTAL_SECONDS", str(15 * 60))
)


class _CaptureHandler:
    """Absorb dispatch responses while forwarding state to the real handler.

    Restore dispatches many calls in one request, so each call's response
    must not finish the HTTP response.
    """

    def __init__(self, handler):
        self._handler = handler
        self.status_code = 200
        self.written = []

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def write(self, chunk):
        self.written.append(chunk)

    def write_text(self, body):
        self.written.append(body)

    def write_json(self, payload):
        self.written.append(payload)

    def set_status(self, status_code, reason=None):
        self.status_code = status_code

    def get_status(self):
        return self.status_code


async def _replay_calls_paced(calls, send, delay=None):
    """Replay calls with async delays so the Tornado loop stays responsive."""
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
            await asyncio.sleep(delay)
    return {
        "total": len(calls),
        "replayed": replayed,
        "failed": len(errors),
        "errors": errors,
    }


class _RunTooLargeError(RunRestoreError):
    """Raised when a run exceeds the endpoint's size or call limit."""


class _RunWorkspaceMismatchError(RunRestoreError):
    """Raised when a run belongs to a different workspace."""


def _check_run_workspace_ownership(
    metadata: dict, workspace_slug: Optional[str]
) -> None:
    """Reject runs owned by another workspace before reading event data.

    Unscoped requests skip this check. Scoped requests require a recorded
    workspace match; runs without one are refused.
    """
    if workspace_slug is None:
        return
    if metadata.get("workspace") != workspace_slug:
        raise _RunWorkspaceMismatchError("run does not belong to the current workspace")


def _check_file_size(path: str, max_bytes: int, label: str) -> None:
    """Reject files larger than ``max_bytes`` before reading them."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size > max_bytes:
        raise _RunTooLargeError(
            "{0} {1!r} is {2} bytes, over this server's limit of {3}; "
            "set VISDOM_MAX_RESTORE_FILE_BYTES to raise it".format(
                label, path, size, max_bytes
            )
        )


def _load_calls_bounded(json_path, max_calls, max_bytes, workspace_slug):
    """Load replay calls off-loop while enforcing size, count, and ownership limits.

    Check metadata size and ownership before reading the events file, then
    stream events and stop when the call limit is exceeded. Return metadata,
    event count, and calls.
    """
    _check_file_size(json_path, max_bytes, "run file")
    metadata = load_run_file(json_path)
    _check_run_workspace_ownership(metadata, workspace_slug)
    events_path = resolve_run_events_path(json_path, metadata)
    if events_path is not None:
        _check_file_size(events_path, max_bytes, "events file")
    calls = []
    event_count = 0
    for event in iter_run_events(json_path, metadata):
        event_count += 1
        for call in _iter_calls_from_event(event):
            calls.append(call)
            if len(calls) > max_calls:
                raise _RunTooLargeError(
                    "{0!r} has more than {1} recorded calls, over this "
                    "server's limit; set VISDOM_MAX_RESTORE_CALLS to raise "
                    "it".format(json_path, max_calls)
                )
    return metadata, event_count, calls


def _validate_calls_for_server_replay(calls):
    """Validate call endpoints and required fields before dispatch.

    This prevents a malformed later call from being discovered only after
    earlier calls have already changed the target environment. Semantic
    errors that pass these structural checks are reported during dispatch.
    """
    validate_calls_for_replay(calls)
    for index, call in enumerate(calls):
        endpoint = call.get("endpoint")
        msg = call.get("msg")
        if (
            not isinstance(msg, dict)
            or not isinstance(msg.get("win"), str)
            or not msg.get("win")
        ):
            raise RunRestoreError(
                "recorded call {0} is missing a valid window id".format(index)
            )
        if endpoint == "events":
            data = msg.get("data")
            if (
                not isinstance(data, list)
                or not data
                or not isinstance(data[0], dict)
                or "type" not in data[0]
            ):
                raise RunRestoreError(
                    "recorded call {0} is missing valid plot data".format(index)
                )
        elif endpoint == "update":
            # Match UpdateHandler's checks before any calls are dispatched.
            if "data" not in msg and "layout" not in msg and "opts" not in msg:
                raise RunRestoreError(
                    "recorded call {0} (update) has none of data, layout, "
                    "or opts".format(index)
                )
            if "data" not in msg and msg.get("append"):
                raise RunRestoreError(
                    "recorded call {0} (update) has append set but no "
                    "data".format(index)
                )
            layout_create = msg.get("layout_create", {})
            if not isinstance(layout_create, dict):
                raise RunRestoreError(
                    "recorded call {0} (update) has a non-object "
                    "layout_create".format(index)
                )


class RestoreRunHandler(BaseHandler):
    """Replay recorded plots from a run file."""

    @check_auth
    @check_readonly_message(
        "Restoring a run is disabled while the server is in readonly mode"
    )
    async def post(self):
        try:
            args = tornado.escape.json_decode(
                tornado.escape.to_basestring(self.request.body)
            )
        except (ValueError, UnicodeDecodeError):
            self.set_status(400)
            self.write_json({"error": "request body must be JSON"})
            return
        if not isinstance(args, dict):
            self.set_status(400)
            self.write_json({"error": "request body must be a JSON object"})
            return

        rel_path = args.get("path")
        if not rel_path or not isinstance(rel_path, str):
            self.set_status(400)
            self.write_json({"error": "missing required field: path"})
            return

        try:
            delay = validate_delay(args.get("delay"))
        except ValueError as e:
            self.set_status(400)
            self.write_json({"error": str(e)})
            return
        if delay is not None and delay > MAX_DELAY_SECONDS:
            self.set_status(400)
            self.write_json(
                {
                    "error": (
                        "delay must be <= {0!r} seconds on this endpoint, "
                        "got {1!r}".format(MAX_DELAY_SECONDS, delay)
                    )
                }
            )
            return

        eid = args.get("eid")
        if eid is not None and not isinstance(eid, str):
            self.set_status(400)
            self.write_json({"error": "eid must be a string, got {0!r}".format(eid)})
            return

        try:
            json_path = resolve_under_root(TRACKING_ROOT, rel_path)
        except RunRestoreError as e:
            self.set_status(400)
            self.write_json({"error": str(e)})
            return

        if not os.path.isfile(json_path):
            self.set_status(404)
            self.write_json({"error": "no run file found at {0!r}".format(rel_path)})
            return

        try:
            metadata, event_count, calls = await run_on_storage_executor(
                self,
                _load_calls_bounded,
                json_path,
                MAX_RESTORE_CALLS,
                MAX_RESTORE_FILE_BYTES,
                self.workspace_slug,
            )
        except _RunWorkspaceMismatchError:
            # Do not reveal whether another workspace owns this run.
            self.set_status(404)
            self.write_json({"error": "no run file found at {0!r}".format(rel_path)})
            return
        except _RunTooLargeError as e:
            self.set_status(413)
            self.write_json({"error": str(e)})
            return
        except RunRestoreError as e:
            self.set_status(400)
            self.write_json({"error": str(e)})
            return

        if not calls:
            self.set_status(422)
            self.write_json(
                {
                    "error": (
                        "{0!r} has no replayable plot data recorded. Only "
                        "runs tracked with RunTracker(..., record_data=True) "
                        "capture what restore_run needs.".format(rel_path)
                    )
                }
            )
            return

        if delay and len(calls) > 1:
            total_replay_seconds = (len(calls) - 1) * delay
            if total_replay_seconds > MAX_TOTAL_REPLAY_SECONDS:
                self.set_status(400)
                self.write_json(
                    {
                        "error": (
                            "replaying {0} calls with delay={1!r} would take "
                            "about {2:.0f}s total, over this server's limit "
                            "of {3:.0f}s; set VISDOM_MAX_RESTORE_TOTAL_SECONDS "
                            "to raise it, or request fewer calls/a shorter "
                            "delay".format(
                                len(calls),
                                delay,
                                total_replay_seconds,
                                MAX_TOTAL_REPLAY_SECONDS,
                            )
                        )
                    }
                )
                return

        try:
            _validate_calls_for_server_replay(calls)
        except RunRestoreError as e:
            self.set_status(422)
            self.write_json({"error": str(e)})
            return

        eid = eid or default_target_eid(calls, metadata, None)
        calls = retarget_calls(calls, eid)

        await ensure_env_loaded(self, eid)
        capture = _CaptureHandler(self)
        summary = await _replay_calls_paced(
            calls,
            lambda msg, endpoint: self._dispatch_call(capture, msg, endpoint, eid),
            delay=delay,
        )

        await save_env_off_loop(self, eid)
        broadcast_envs(self)

        summary.update(
            {
                "run_id": metadata.get("run_id"),
                "name": metadata.get("name"),
                "status": metadata.get("status"),
                "eid": eid,
                "warning": run_event_consistency_warning(metadata, event_count),
            }
        )
        self.write_json(summary)

    def _dispatch_call(self, capture, msg, endpoint, eid):
        """Dispatch one captured call through the normal server handlers."""
        msg = dict(msg)
        msg["eid"] = eid
        if endpoint == "events":
            p = window(msg)
            register_window(capture, p, eid)
            return
        if endpoint == "update":
            from visdom.server.handlers.web_handlers import UpdateHandler

            UpdateHandler.wrap_func(capture, msg)
            if capture.status_code >= 400:
                raise RuntimeError(
                    "replayed update for window {0!r} was rejected ({1}): "
                    "{2}".format(msg.get("win"), capture.status_code, capture.written)
                )
            return
        raise RuntimeError("cannot replay a recorded {0!r} call".format(endpoint))
