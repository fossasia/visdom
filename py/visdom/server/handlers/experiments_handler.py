#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Handler that builds the hyper-parameter pane.

``/experiments/hparams`` selects experiments, flattens them into the records
matrix the pane renders from, and registers an ``hparams`` window with that
content — so the ``Visdom.hparams`` client is a thin call to this endpoint
rather than gathering, flattening and creating the window itself. It reads
through the server's ``DataStore`` (:class:`ExperimentStore` over
``handler.storage``), so it stays backend-agnostic.

The window is registered like any other pane (:func:`register_window`): written
into the env state and broadcast to connected clients, and the environment is
saved as soon as the pane exists, so a pane survives a server crash without
waiting for an explicit save. ``/experiments/hparams/update`` is the matching
write path for an existing pane — replace its selection or re-run the stored
one — since the generic ``/update`` endpoint only understands plot-shaped
windows.

That update path is also how a pane refreshes itself: :func:`make_live_queue`
builds the queue that logging a run feeds, and drains it back into this module's
own update handler, so a live refresh and a hand-written one are the same code.
"""

import logging

import tornado.escape
import tornado.ioloop
import tornado.web

from visdom.experiments import (
    DEFAULT_DEBOUNCE_SECONDS,
    ExperimentStore,
    LiveUpdateQueue,
    QueryParseError,
    flatten_experiments,
    resolve_targets,
)
from visdom.server.handlers.base_handlers import BaseHandler
from visdom.utils.server_utils import (
    check_auth,
    extract_eid,
    register_window,
    reject_readonly,
    window,
)

READONLY_MESSAGE = "Experiment writes are disabled while the server is in readonly mode"

VALID_MODES = ("query", "env_ids", "both")


class ExperimentHparamsHandler(BaseHandler):
    """POST ``/experiments/hparams`` — select experiments and open the pane.

    The JSON body selects which runs to show and how:

    * ``query`` — filter with the syntax of :mod:`~visdom.experiments.query`
      (``"lr < 0.01 AND acc > 90"``).
    * ``env_ids`` — an explicit list of environments, kept in the order given.
    * ``mode`` — ``"query"``, ``"env_ids"`` or ``"both"``; when omitted it is
      inferred from which of ``query``/``env_ids`` were supplied. Each mode
      rejects the argument it does not accept, and with neither supplied there is
      nothing to select (400). A blank query counts as no query.

    ``win``/``eid``/``opts`` behave as for any other window. The selected runs
    are flattened (:func:`~visdom.experiments.flatten_experiments`) into the
    window content and registered as a window (env state + broadcast); the reply
    is the created window id.

    Creating the pane writes a window into the env, so the endpoint is rejected
    with 403 while the server runs in readonly mode.
    """

    @staticmethod
    def _resolve_spec(query, env_ids, mode):
        """Validate a selection and return it as the spec stored on the window.

        The spec — ``{"query", "env_ids", "mode"}`` with the mode resolved and
        ``env_ids`` de-duplicated in caller order — is plain JSON data: it is
        written onto the window dict, persists with the environment, and is what
        a later bare ``/experiments/hparams/update`` replays. Invalid argument
        combinations raise ``HTTPError(400)``.
        """
        if mode is not None and mode not in VALID_MODES:
            raise tornado.web.HTTPError(
                400, reason="mode must be one of {0}".format(VALID_MODES)
            )
        if query is not None and not isinstance(query, str):
            raise tornado.web.HTTPError(400, reason="'query' must be a string")
        if env_ids is not None:
            if not isinstance(env_ids, list):
                raise tornado.web.HTTPError(
                    400, reason="'env_ids' must be a list of ids"
                )
            if not all(isinstance(env_id, str) for env_id in env_ids):
                raise tornado.web.HTTPError(
                    400, reason="'env_ids' must contain strings"
                )

        has_query = isinstance(query, str) and query.strip() != ""
        has_env_ids = env_ids is not None and len(env_ids) > 0

        if mode is None:
            if has_query and has_env_ids:
                mode = "both"
            elif has_query:
                mode = "query"
            elif has_env_ids:
                mode = "env_ids"
            else:
                raise tornado.web.HTTPError(
                    400, reason="a query, env_ids, or both is required"
                )
        elif mode == "query":
            if not has_query:
                raise tornado.web.HTTPError(
                    400, reason="mode='query' requires a non-empty query"
                )
            if env_ids is not None:
                raise tornado.web.HTTPError(
                    400, reason="mode='query' does not accept env_ids"
                )
        elif mode == "env_ids":
            if query is not None:
                raise tornado.web.HTTPError(
                    400, reason="mode='env_ids' does not accept a query"
                )
            if not has_env_ids:
                raise tornado.web.HTTPError(
                    400, reason="mode='env_ids' requires a non-empty env_ids"
                )
        else:
            if not has_query:
                raise tornado.web.HTTPError(
                    400, reason="mode='both' requires a non-empty query"
                )
            if not has_env_ids:
                raise tornado.web.HTTPError(
                    400, reason="mode='both' requires a non-empty env_ids"
                )

        return {
            "query": query if has_query else None,
            "env_ids": (
                list(dict.fromkeys(env_ids)) if mode in ("env_ids", "both") else None
            ),
            "mode": mode,
        }

    @staticmethod
    def _select(store, spec):
        """Fetch the experiments a resolved spec names.

        Mirrors the selection the ``Visdom.hparams`` client used to do: a query
        goes through search, an ``env_ids`` selection reads only those
        environments, and ``both`` searches then narrows by ``env_ids``. A
        malformed query raises ``HTTPError(400)``.
        """
        wanted = spec.get("env_ids")

        if spec.get("mode") == "env_ids":
            experiments = []
            for env_id in wanted or []:
                experiment = store.get_experiment(env_id)
                if experiment is not None:
                    experiments.append(experiment)
            return experiments

        try:
            experiments = store.search(query=spec.get("query"))
        except QueryParseError as e:
            raise tornado.web.HTTPError(400, reason=str(e))
        if wanted is not None:
            by_id = {experiment.env_id: experiment for experiment in experiments}
            experiments = [by_id[eid] for eid in wanted if eid in by_id]
        return experiments

    @staticmethod
    def _build_content(handler, spec):
        """Select the runs ``spec`` names and flatten them into pane content."""
        store = ExperimentStore(handler.storage, env_provider=handler.state.get)
        experiments = ExperimentHparamsHandler._select(store, spec)
        return flatten_experiments([experiment.to_dict() for experiment in experiments])

    @staticmethod
    def wrap_func(handler, args):
        spec = ExperimentHparamsHandler._resolve_spec(
            args.get("query"), args.get("env_ids"), args.get("mode")
        )
        content = ExperimentHparamsHandler._build_content(handler, spec)

        eid = extract_eid(args)
        opts = dict(args.get("opts") or {})
        opts.setdefault("title", "Hyperparameters")
        p = window(
            {
                "data": [{"content": content, "type": "hparams"}],
                "win": args.get("win"),
                "opts": opts,
            }
        )
        p["hparams"] = spec
        register_window(handler, p, eid)
        handler.storage.save_env(eid, handler.state[eid])

    @check_auth
    @reject_readonly(READONLY_MESSAGE)
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class ExperimentHparamsUpdateHandler(BaseHandler):
    """POST ``/experiments/hparams/update`` — change or refresh an hparams pane.

    ``/update`` cannot touch an hparams window: it is gated on plot-shaped
    content, and an hparams window holds a records matrix instead. This is the
    dedicated write path for those panes, and it is *only* that — the target
    ``win`` must name an existing window of type ``hparams`` (404 when the env
    or window is unknown, 400 for any other window type).

    With ``query``/``env_ids``/``mode`` in the body the pane's selection is
    replaced, under exactly the rules of ``/experiments/hparams``. With none of
    them the selection stored on the window is re-run — a manual refresh that
    picks up runs logged since the pane was built (400 if the window predates
    stored selections). ``opts`` may override title/size; absent opts keep the
    window's current ones.

    The rebuilt window keeps its id (and so its position) but carries a fresh
    ``contentID``, which is what the client re-renders on; it is written into
    the env state, broadcast to that env's subscribers, and the env is saved so
    disk reflects the update immediately.

    The refresh case is what a live update is, so :func:`make_live_queue` drives
    :meth:`wrap_func` directly rather than growing a second rebuild path.

    That write reaches disk, so the endpoint is rejected with 403 while the
    server runs in readonly mode.
    """

    @staticmethod
    def wrap_func(handler, args):
        win = args.get("win")
        if not isinstance(win, str) or not win:
            raise tornado.web.HTTPError(400, reason="'win' is required")

        eid = extract_eid(args)
        if eid not in handler.state:
            raise tornado.web.HTTPError(404, reason="unknown env {0!r}".format(eid))
        existing = handler.state[eid]["jsons"].get(win)
        if existing is None:
            raise tornado.web.HTTPError(
                404, reason="no window {0!r} in env {1!r}".format(win, eid)
            )
        if existing.get("type") != "hparams":
            raise tornado.web.HTTPError(
                400, reason="window {0!r} is not an hparams window".format(win)
            )

        has_selection = any(
            args.get(key) is not None for key in ("query", "env_ids", "mode")
        )
        if has_selection:
            spec = ExperimentHparamsHandler._resolve_spec(
                args.get("query"), args.get("env_ids"), args.get("mode")
            )
        else:
            spec = existing.get("hparams")
            if not isinstance(spec, dict):
                raise tornado.web.HTTPError(
                    400,
                    reason="window {0!r} has no stored selection; "
                    "pass a query and/or env_ids".format(win),
                )

        content = ExperimentHparamsHandler._build_content(handler, spec)

        opts = {
            "title": existing.get("title", ""),
            "inflate": existing.get("inflate", True),
            "width": existing.get("width"),
            "height": existing.get("height"),
            "comment": existing.get("comment", ""),
        }
        opts.update(args.get("opts") or {})
        p = window(
            {
                "data": [{"content": content, "type": "hparams"}],
                "win": win,
                "version": existing.get("version", 1),
                "opts": opts,
            }
        )
        p["hparams"] = spec
        register_window(handler, p, eid)
        handler.storage.save_env(eid, handler.state[eid])

    @check_auth
    @reject_readonly(READONLY_MESSAGE)
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)


class LivePaneWriter:
    """The application, shaped like the handler the window helpers expect.

    ``wrap_func`` was written to run without a live request — it takes the
    handler and a plain args dict, and every ``post`` in the server is a decode
    followed by a call to it. The one thing it still assumes is a response:
    :func:`register_window` finishes by writing the window id back to the
    client. A live rebuild has nobody to answer, so that write is dropped here
    and everything else the rebuild touches — ``state``, ``subs``, ``storage`` —
    is the application's own.
    """

    def __init__(self, app):
        self._app = app

    def __getattr__(self, name):
        return getattr(self._app, name)

    def write(self, chunk):
        """Swallow the window id ``register_window`` writes to the response."""


def _schedule_on_ioloop(delay, callback):
    """Run ``callback`` on the event loop after ``delay`` seconds.

    Without a running loop — an application built outside a server, as tests
    and embedders do — there is nothing to defer onto, so the drain runs inline
    rather than being lost.
    """
    try:
        tornado.ioloop.IOLoop.current().call_later(delay, callback)
    except RuntimeError:
        callback()


def make_live_queue(app, delay=DEFAULT_DEBOUNCE_SECONDS):
    """Build the queue that keeps ``app``'s hparams panes in step with its runs.

    Logging a run marks its environment on this queue; a drain asks
    :func:`~visdom.experiments.live.resolve_targets` which panes that could
    affect, and refreshes each through
    :meth:`ExperimentHparamsUpdateHandler.wrap_func` with args naming only the
    window — the endpoint's "re-run the stored selection" case. Going through
    the handler rather than around it means a live refresh is validated exactly
    like a requested one, and cannot drift from it.

    Those checks reject what a detached rebuild is bound to meet eventually: a
    pane closed or retyped between the mark and the drain. That is an ordinary
    race rather than a fault, so an ``HTTPError`` is logged at debug and the
    remaining panes still update.

    The decorators on ``post`` are deliberately not re-run here. Authorisation
    and the readonly refusal belong to the ``experiments/log`` request that
    triggered this, and it passed both before anything was marked.
    """
    writer = LivePaneWriter(app)

    def rebuild(eid, win_id):
        try:
            ExperimentHparamsUpdateHandler.wrap_func(
                writer, {"win": win_id, "eid": eid}
            )
        except tornado.web.HTTPError as e:
            logging.debug(
                "skipped live update of hparams window %r in env %r: %s",
                win_id,
                eid,
                e,
            )

    return LiveUpdateQueue(
        resolve=lambda changed: resolve_targets(app.state, changed),
        rebuild=rebuild,
        delay=delay,
        schedule=_schedule_on_ioloop,
    )
