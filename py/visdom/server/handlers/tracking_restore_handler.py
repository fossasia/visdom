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

import tornado.escape
import tornado.web

from visdom.server.handlers.base_handlers import BaseHandler
from visdom.tracking.core import DEFAULT_OUT_DIR
from visdom.tracking.restore import (
    RunRestoreError,
    default_target_eid,
    extract_replayable_calls,
    load_run_events,
    load_run_file,
    resolve_under_root,
    retarget_calls,
    run_event_consistency_warning,
    validate_delay,
    _replay_one,
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

#: Directory JSON paths passed to ``/restore_run`` are resolved under.
#: Overridable via ``VISDOM_TRACKING_DIR`` for the same reason the client
#: side's ``out_dir``/``DEFAULT_OUT_DIR`` is a parameter, not a constant: a
#: deployment that runs ``RunTracker`` with a non-default ``out_dir`` needs
#: the server to look in the same place.
TRACKING_ROOT = os.environ.get("VISDOM_TRACKING_DIR", os.path.abspath(DEFAULT_OUT_DIR))

#: Upper bound on a single request's `delay`, in seconds. `validate_delay`
#: only rules out nonsensical values (negative, NaN, infinite); this bounds
#: how long one HTTP request may legitimately pace itself for on this
#: specific path. A standalone client script replaying `delay=3600` is the
#: caller's own process to leave running as long as they like, but the same
#: value here would hold this request (and the asyncio task driving it)
#: open for an hour, which is a server resource/availability concern this
#: path alone needs to guard against. Overridable via
#: `VISDOM_MAX_RESTORE_DELAY_SECONDS` for a deployment that genuinely wants
#: slower-than-default replays.
MAX_DELAY_SECONDS = float(os.environ.get("VISDOM_MAX_RESTORE_DELAY_SECONDS", "60"))

#: Upper bound on how many recorded calls one `/restore_run` request will
#: replay. `load_run_events`/`extract_replayable_calls` materialize the
#: whole timeline (and then the call list) in memory before anything is
#: dispatched, so an enormous recorded run -- submitted by an authenticated
#: caller either deliberately or by accident -- otherwise has no bound on
#: the memory, latency, or wall-clock time one request can demand.
#: Overridable via `VISDOM_MAX_RESTORE_CALLS`.
MAX_RESTORE_CALLS = int(os.environ.get("VISDOM_MAX_RESTORE_CALLS", "20000"))


class _CaptureHandler:
    """A stand-in handler that absorbs one dispatched call's response instead
    of writing it to the network.

    ``register_window``/``UpdateHandler.wrap_func`` are the server's own
    code for turning one parsed request into a pane -- reusing them (via
    ``RestoreRunHandler._dispatch_call``) means a replayed call is handled
    by exactly the same logic a live client's call would be, rather than a
    second, drifting implementation. The catch: both of those end by
    writing the real HTTP response (``handler.write(...)``, or
    ``handler.write_text(...)`` which calls ``self.finish()``), and
    ``RestoreRunHandler.post`` dispatches *many* calls in one request, so
    letting the first one reach the real handler's ``finish()`` would end
    the response before the rest ever run (and the real handler would then
    raise ``finish() called twice`` on the summary ``post()`` tries to send
    at the end).

    So this wraps the real handler and intercepts exactly the methods that
    write: a call through this never touches the network. Everything else
    (``state``, ``mark_dirty``, ``subs``, ``storage_executor``, ...) is
    forwarded straight through to the real handler via ``__getattr__``, so
    ``register_window``/``wrap_func`` can't tell the difference.
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
    """Like ``tracking.restore.replay_calls``, but paced with ``await
    asyncio.sleep`` instead of ``time.sleep``.

    A server handler runs on the one shared Tornado IO loop: a blocking
    ``time.sleep(delay)`` between each replayed call -- fine for a
    standalone client script -- would freeze every other request the
    server is handling (other clients' plots, page loads, websocket
    traffic) for the full duration of the replay. ``await asyncio.sleep``
    yields control back to the loop instead, so other requests are served
    normally in between paced steps.
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
            await asyncio.sleep(delay)
    return {
        "total": len(calls),
        "replayed": replayed,
        "failed": len(errors),
        "errors": errors,
    }


def _load_calls(json_path):
    """Off-loop: read a run's metadata + full event timeline and extract its
    replayable calls. Raises ``RunRestoreError`` (via the functions it
    calls) on anything from a missing file to a run tracked without
    ``record_data=True``. Returns ``(metadata, events, calls)`` -- ``events``
    is kept around (not just ``calls``) so the caller can also check
    ``run_event_consistency_warning`` against it.
    """
    metadata = load_run_file(json_path)
    events = load_run_events(json_path, metadata)
    return metadata, events, extract_replayable_calls(events)


#: Endpoints _dispatch_call actually knows how to replay. The client path
#: (Visdom.restore_run) is endpoint-agnostic -- it just re-sends whatever
#: was recorded through _send() -- but the server only ever reconstructs
#: panes through `events`/`update`, so a recorded call naming anything else
#: can never be dispatched here.
_SUPPORTED_SERVER_ENDPOINTS = frozenset({"events", "update"})


def _validate_calls_for_server_replay(calls):
    """Structurally validate every call *before* any of them are dispatched.

    ``extract_replayable_calls`` only guarantees ``msg`` is a dict; it
    can't know this server only replays ``events``/``update``, or that
    ``_dispatch_call``/``window()`` need a non-empty ``win`` and (for a
    create) a typed ``data[0]``. Without this upfront pass, a file whose
    Nth call is malformed or names an endpoint the server can't replay
    would only fail once dispatch actually reaches that call -- after
    every call before it has already mutated the target environment, for
    what is supposed to read as one atomic "restore this run" request.
    """
    for index, call in enumerate(calls):
        endpoint = call.get("endpoint")
        msg = call.get("msg")
        if endpoint not in _SUPPORTED_SERVER_ENDPOINTS:
            raise RunRestoreError(
                "recorded call {0} has an unsupported endpoint {1!r}; this "
                "server can only replay {2} calls".format(
                    index, endpoint, sorted(_SUPPORTED_SERVER_ENDPOINTS)
                )
            )
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


class RestoreRunHandler(BaseHandler):
    """``POST /restore_run`` -- body: ``{"path": <run json, relative to the
    tracking root>, "eid": <optional target env>, "delay": <optional
    seconds between updates>}``.
    """

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
            metadata, events, calls = await run_on_storage_executor(
                self, _load_calls, json_path
            )
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

        if len(calls) > MAX_RESTORE_CALLS:
            self.set_status(413)
            self.write_json(
                {
                    "error": (
                        "{0!r} has {1} recorded calls, over this server's "
                        "limit of {2}; set VISDOM_MAX_RESTORE_CALLS to "
                        "raise it".format(rel_path, len(calls), MAX_RESTORE_CALLS)
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
                "warning": run_event_consistency_warning(metadata, events),
            }
        )
        self.write_json(summary)

    def _dispatch_call(self, capture, msg, endpoint, eid):
        """Run one captured ``(msg, endpoint)`` pair through the same
        request-handling code a live client's call would take, but against
        ``capture`` (a ``_CaptureHandler`` wrapping this handler) rather
        than a real client connection -- see ``_CaptureHandler``.
        """
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
