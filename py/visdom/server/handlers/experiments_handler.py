#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Handler that builds the hyper-parameter pane.

``/experiments/hparams`` selects experiments, flattens them into the records
matrix the pane renders from, and stores an ``hparams`` window with that content
in the env state — so the ``Visdom.hparams`` client is a thin call to this
endpoint rather than gathering, flattening and creating the window itself. It
reads through the server's ``DataStore`` (:class:`ExperimentStore` over
``handler.storage``), so it stays backend-agnostic.

For now the window is only written into the state; it is served on the next env
load but not broadcast to connected clients, because the frontend does not yet
have a dedicated ``hparams`` pane to render it. Broadcasting is added together
with that pane.
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
    window,
)

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
    window content and written into the env state; the reply is the created
    window id.
    """

    @staticmethod
    def _select(store, query, env_ids, mode):
        """Resolve the mode, fetch the runs, and return them as experiments.

        Mirrors the selection the ``Visdom.hparams`` client used to do: a query
        goes through search, an ``env_ids`` selection reads only those
        environments, and ``both`` searches then narrows by ``env_ids``. Invalid
        argument combinations raise ``HTTPError(400)``.
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
            for env_id in wanted:
                experiment = store.get_experiment(env_id)
                if experiment is not None:
                    experiments.append(experiment)
            return experiments

        try:
            experiments = store.search(query=query)
        except QueryParseError as e:
            raise tornado.web.HTTPError(400, reason=str(e))
        if wanted is not None:
            by_id = {experiment.env_id: experiment for experiment in experiments}
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
        p = window(
            {
                "data": [{"content": content, "type": "hparams"}],
                "win": args.get("win"),
                "opts": args.get("opts", {}),
            }
        )
        ExperimentHparamsHandler._store_window(handler, p, eid)
        handler.write(p["id"])

    @staticmethod
    def _store_window(handler, p, eid):
        """Write ``p`` into ``eid``'s state so it is served on the next env load.

        This is the state half of :func:`register_window` without the socket
        broadcast: the pane is persisted but not pushed to connected clients,
        since the frontend has no ``hparams`` pane to render it yet.
        """
        if eid not in handler.state:
            handler.state[eid] = {"jsons": {}, "reload": {}}
        env = handler.state[eid]["jsons"]
        if p["id"] in env:
            p["i"] = env[p["id"]]["i"]
        else:
            p["i"] = len(env)
        env[p["id"]] = p

    @check_auth
    def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        self.wrap_func(self, args)
