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
into the env state and broadcast to connected clients, so it appears live and is
also served on the next env load.
"""

import tornado.escape
import tornado.web

from visdom.experiments import (
    ExperimentStore,
    QueryParseError,
    flatten_experiments,
)
from visdom.server.handlers.base_handlers import BaseHandler
from visdom.utils.server_utils import (
    check_auth,
    extract_eid,
    register_window,
    window,
)

VALID_MODES = ("query", "env_ids", "both")

#: How many unknown ids a 404 names before it summarizes the rest.
UNKNOWN_IDS_SHOWN = 5


def _reason(text):
    """Return ``text`` as a reason phrase that is safe to put on the status line.

    Reason phrases are latin-1 encoded by Tornado and cannot span lines, so
    anything built from the request body — an env id, a query — is escaped to
    ASCII and flattened onto one line first. A run named with an emoji should
    come back as the 404 it is rather than a 500 from the error path itself.
    """
    return " ".join(text.split()).encode("ascii", "backslashreplace").decode("ascii")


def _unknown_env_ids(unknown):
    """Return the 404 naming the ``env_ids`` that have no experiment."""
    named = ", ".join("'{0}'".format(env_id) for env_id in unknown[:UNKNOWN_IDS_SHOWN])
    if len(unknown) > UNKNOWN_IDS_SHOWN:
        named += " (and {0} more)".format(len(unknown) - UNKNOWN_IDS_SHOWN)
    return tornado.web.HTTPError(
        404, reason=_reason("no experiment for env_ids: {0}".format(named))
    )


class ExperimentHparamsHandler(BaseHandler):
    """POST ``/experiments/hparams`` — select experiments and open the pane.

    The JSON body selects which runs to show and how:

    * ``query`` — filter with the syntax of :mod:`~visdom.experiments.query`
      (``"lr < 0.01 AND acc > 90"``).
    * ``env_ids`` — an explicit list of environments, kept in the order given.
      Every id must have an experiment; one that does not is a 404 naming it,
      like ``/experiments/compare``, since a mistyped id dropped from the
      selection would open a pane quietly missing a run that was asked for.
    * ``mode`` — ``"query"``, ``"env_ids"`` or ``"both"``; when omitted it is
      inferred from which of ``query``/``env_ids`` were supplied. Each mode
      rejects the argument it does not accept, and with neither supplied there is
      nothing to select (400). A blank query counts as no query.

    ``win``/``eid``/``opts`` behave as for any other window. The selected runs
    are flattened (:func:`~visdom.experiments.flatten_experiments`) into the
    window content and registered as a window (env state + broadcast); the reply
    is the created window id.
    """

    @staticmethod
    def _select(store, query, env_ids, mode):
        """Resolve the mode, fetch the runs, and return them as experiments.

        Mirrors the selection the ``Visdom.hparams`` client used to do: a query
        goes through search, an ``env_ids`` selection reads only those
        environments, and ``both`` searches then narrows by ``env_ids``. Invalid
        argument combinations raise ``HTTPError(400)``; ids that name no
        experiment at all raise ``HTTPError(404)``. Under ``both`` that is only
        the ids with no experiment behind them — one that exists but does not
        match the query is filtered out as the query asked.
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

        wanted = list(dict.fromkeys(env_ids)) if mode in ("env_ids", "both") else None

        if mode == "env_ids":
            experiments = []
            unknown = []
            for env_id in wanted:
                experiment = store.get_experiment(env_id)
                if experiment is None:
                    unknown.append(env_id)
                else:
                    experiments.append(experiment)
            if unknown:
                raise _unknown_env_ids(unknown)
            return experiments

        try:
            experiments = store.search(query=query)
        except QueryParseError as e:
            raise tornado.web.HTTPError(400, reason=_reason(str(e)))
        if wanted is not None:
            by_id = {experiment.env_id: experiment for experiment in experiments}
            unknown = [
                env_id
                for env_id in wanted
                if env_id not in by_id and store.get_experiment(env_id) is None
            ]
            if unknown:
                raise _unknown_env_ids(unknown)
            experiments = [by_id[eid] for eid in wanted if eid in by_id]
        return experiments

    @staticmethod
    def wrap_func(handler, args):
        store = ExperimentStore(handler.storage)
        experiments = ExperimentHparamsHandler._select(
            store, args.get("query"), args.get("env_ids"), args.get("mode")
        )
        content = flatten_experiments(
            [experiment.to_dict() for experiment in experiments]
        )

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
        register_window(handler, p, eid)

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)
