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
    _iter_calls_from_event,
    _replay_one,
    default_target_eid,
    iter_run_events,
    load_run_file,
    resolve_run_events_path,
    resolve_under_root,
    retarget_calls,
    run_event_consistency_warning,
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
#: replay. Enforced *while* `_load_calls_bounded` streams a run's event
#: timeline (see its docstring) -- an enormous recorded run, submitted by
#: an authenticated caller either deliberately or by accident, stops being
#: read the moment this is exceeded, rather than only being checked after
#: its whole timeline (and then its whole call list) has already been
#: materialized in memory. Overridable via `VISDOM_MAX_RESTORE_CALLS`.
MAX_RESTORE_CALLS = int(os.environ.get("VISDOM_MAX_RESTORE_CALLS", "20000"))

#: Upper bound, in bytes, on the recorded-run files one `/restore_run`
#: request will read. Checked with a cheap `os.path.getsize()` against both
#: the run's `<run_id>.json` and `<run_id>.events.jsonl`, before either is
#: opened. `MAX_RESTORE_CALLS` already bounds memory regardless of file
#: size, since `_load_calls_bounded` streams rather than materializing the
#: whole timeline -- but a file dominated by lines that never produce a
#: replayable call (and so never trip that limit) could still cost
#: unbounded time to simply read and parse line by line; this bounds that
#: cost up front instead. Overridable via `VISDOM_MAX_RESTORE_FILE_BYTES`.
MAX_RESTORE_FILE_BYTES = int(
    os.environ.get("VISDOM_MAX_RESTORE_FILE_BYTES", str(256 * 1024 * 1024))
)

#: Upper bound, in seconds, on the *total* time one `/restore_run` request
#: will spend pacing its replay -- i.e. on `(len(calls) - 1) * delay`, not
#: on `delay` alone. `MAX_DELAY_SECONDS` only bounds the gap *between*
#: consecutive calls; paired with `MAX_RESTORE_CALLS`, a request can still
#: legally ask for up to roughly `(MAX_RESTORE_CALLS - 1) *
#: MAX_DELAY_SECONDS` seconds of total pacing (with their current
#: defaults, nearly two weeks) without this second, independent bound.
#: Checked once the actual call count is known, before replay starts.
#: Overridable via `VISDOM_MAX_RESTORE_TOTAL_SECONDS`.
MAX_TOTAL_REPLAY_SECONDS = float(
    os.environ.get("VISDOM_MAX_RESTORE_TOTAL_SECONDS", str(15 * 60))
)


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


class _RunTooLargeError(RunRestoreError):
    """A recorded run exceeded this endpoint's resource bounds -- too many
    bytes to read, or too many replayable calls -- mapped to HTTP 413.

    A dedicated subclass (rather than a plain ``RunRestoreError``, which
    the handler maps to 400) so ``post()`` can tell "this run is too big"
    apart from "this run's files are missing or malformed" without
    inspecting the message text.
    """


def _check_run_file_sizes(json_path: str, metadata: dict, max_bytes: int) -> None:
    """Reject a run up front, via a cheap ``os.path.getsize()``, if either
    of its files is implausibly large -- see ``MAX_RESTORE_FILE_BYTES``.

    Checked before either file is opened for reading. A metadata file this
    large would already be surprising (``RunTracker`` keeps it small/capped
    by design), but it's checked alongside the events file for the same
    reason: a cheap check is worth having even where it's expected to never
    trigger, since "expected to never happen" is exactly the condition an
    adversarial or corrupted input is free to violate.
    """
    candidates = [("run file", json_path)]
    events_path = resolve_run_events_path(json_path, metadata)
    if events_path is not None:
        candidates.append(("events file", events_path))
    for label, path in candidates:
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > max_bytes:
            raise _RunTooLargeError(
                "{0} {1!r} is {2} bytes, over this server's limit of {3}; "
                "set VISDOM_MAX_RESTORE_FILE_BYTES to raise it".format(
                    label, path, size, max_bytes
                )
            )


def _load_calls_bounded(json_path, max_calls, max_bytes):
    """Off-loop: read a run's metadata and extract its replayable calls,
    enforcing ``max_calls``/``max_bytes`` while doing so rather than after
    the fact.

    Replaces materializing the whole event timeline (``load_run_events``)
    and then the whole call list (``extract_replayable_calls``) before
    checking anything: ``_check_run_file_sizes`` rejects an implausibly
    large run file before either file is opened, and the loop below streams
    ``iter_run_events`` one event at a time, extracting calls as it goes
    and bailing out via ``_RunTooLargeError`` (mapped to HTTP 413) the
    moment ``max_calls`` is exceeded -- so an enormous recorded run, whether
    submitted by an authenticated caller deliberately or by accident, is
    never fully read into memory (or, past the size cap, read at all)
    before this endpoint's resource bounds are enforced.

    Raises ``RunRestoreError`` (via ``load_run_file``) for a missing or
    malformed metadata file, or ``_RunTooLargeError`` once either bound is
    exceeded. Returns ``(metadata, event_count, calls)`` -- ``event_count``
    (how many events were read, not the events themselves) is kept around
    so the caller can still compute ``run_event_consistency_warning``
    without this function retaining every event's full payload for the
    whole read.
    """
    metadata = load_run_file(json_path)
    _check_run_file_sizes(json_path, metadata, max_bytes)
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


#: Endpoints _dispatch_call actually knows how to replay. The client path
#: (Visdom.restore_run) is endpoint-agnostic -- it just re-sends whatever
#: was recorded through _send() -- but the server only ever reconstructs
#: panes through `events`/`update`, so a recorded call naming anything else
#: can never be dispatched here.
_SUPPORTED_SERVER_ENDPOINTS = frozenset({"events", "update"})


def _validate_calls_for_server_replay(calls):
    """Structurally validate every call *before* any of them are dispatched.

    ``extract_replayable_calls``/``_iter_calls_from_event`` only guarantee
    ``msg`` is a dict; they can't know this server only replays
    ``events``/``update``, or what each of those two needs structurally to
    avoid being rejected by the real dispatch code
    (``register_window``/``window()`` for ``events``,
    ``UpdateHandler.wrap_func`` for ``update``) before it ever gets the
    chance to apply anything. Without this upfront pass, a file whose Nth
    call is malformed or names an endpoint the server can't replay would
    only fail once dispatch actually reaches that call -- after every call
    before it has already mutated the target environment, for what is
    supposed to read as one atomic "restore this run" request.

    This guarantees every call is free of the specific structural defects
    checked for here -- not that every call will apply cleanly. Deeper,
    semantic validity (e.g. an ``update`` whose trace count or shape
    doesn't match the window it targets) is still the dispatch layer's own
    job: ``_dispatch_call``/``_replay_one`` already treat each call's
    replay as independent and best-effort, catching whatever it raises and
    recording it in the result's ``errors`` list rather than aborting the
    rest of the replay. That's a different, and fundamentally weaker,
    guarantee than "validated before dispatch" -- a malformed-but-plausible
    ``update`` can still fail at dispatch time -- but it does mean a
    structurally-bad call, including a malformed ``update``, can never
    itself mutate the target environment; it either gets dispatched and
    applies, or it doesn't apply at all.
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
        elif endpoint == "update":
            # Mirrors UpdateHandler.wrap_func's own upfront checks (see
            # web_handlers.py) -- the exact conditions under which it
            # raises HTTPError(400) before touching any state -- so a call
            # that would fail there fails here first, before anything has
            # been dispatched.
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
            metadata, event_count, calls = await run_on_storage_executor(
                self,
                _load_calls_bounded,
                json_path,
                MAX_RESTORE_CALLS,
                MAX_RESTORE_FILE_BYTES,
            )
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
