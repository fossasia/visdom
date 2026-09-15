#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Keep hyper-parameter panes in step with the runs they show.

A pane is built once from a selection and then frozen, so every run logged
afterwards leaves it a little staler until somebody refreshes it by hand. This
module holds the two decisions that close that gap, both free of any server
dependency so they can be exercised on their own:

* :class:`LiveUpdateQueue` — *when* to rebuild. ``mark(env_id)`` records that an
  environment changed and schedules a drain; marks arriving before that drain
  runs are coalesced, so a training loop logging a metric every step costs one
  rebuild per burst rather than one per step.
* :func:`resolve_targets` — *what* to rebuild. Given the server's env state and
  the environments that just changed, it names the explicit-id panes affected.

The queue is handed a resolver and a rebuild callback rather than reaching for
either itself, which is what lets the server point it at the existing
``experiments/hparams/update`` write path without this module knowing about
Tornado, handlers or windows.
"""

import logging

DEFAULT_DEBOUNCE_SECONDS = 0.25


def _named_env_ids(spec):
    """Return the run ids a pane names explicitly, ignoring anything else.

    A stored spec holds whatever was written to it, so ``env_ids`` may be
    missing, a mapping, or a list carrying values that are not ids at all. Only
    strings inside a sequence name a run; treating the rest as naming nothing
    keeps the membership test in :func:`resolve_targets` away from values it
    cannot hash, which would otherwise fail the whole resolve over one bad
    pane.
    """
    env_ids = spec.get("env_ids")
    if not isinstance(env_ids, (list, tuple, set, frozenset)):
        return ()
    return [env_id for env_id in env_ids if isinstance(env_id, str)]


def resolve_targets(state, changed):
    """Name the hparams panes that changes to the ``changed`` envs could affect.

    ``state`` is the server's env state and ``changed`` an iterable of the env
    ids just written. Returns ``(eid, win_id)`` pairs — what a rebuild needs to
    identify a pane — in a stable order, grouped by environment.

    Only a pane that names its runs explicitly (``mode="env_ids"``) is refreshed
    automatically, and only when one of those runs changed. Query selections
    require a whole-store scan, so ``query`` and ``both`` panes are refreshed
    only when requested explicitly.

    Environments that are not resident in memory are skipped rather than paged
    in. With an env per file, touching them all on every logged metric would
    make logging cost the whole store, and an env nobody has opened has no
    client watching its panes; such a pane refreshes on the next explicit
    update, exactly as it did before live updates existed.
    """
    changed = set(changed or ())
    if not changed:
        return []

    targets = []
    for eid in list(state.keys()):
        env = state.get(eid)
        if env is None:
            continue
        if not getattr(env, "is_loaded", True):
            continue
        for win_id, win in list((env.get("jsons") or {}).items()):
            if not isinstance(win, dict) or win.get("type") != "hparams":
                continue
            spec = win.get("hparams")
            if not isinstance(spec, dict):
                continue
            if spec.get("mode") != "env_ids":
                continue
            if not changed.intersection(_named_env_ids(spec)):
                continue
            targets.append((eid, win_id))
    return targets


class LiveUpdateQueue:
    """Coalesce "this env changed" notices and rebuild the panes showing it.

    ``resolve`` maps the set of changed env ids to the panes to rebuild (see
    :func:`resolve_targets`); ``rebuild`` is called once per pane as
    ``rebuild(eid, win_id)``.

    ``schedule`` is how a drain is deferred: it is called as
    ``schedule(delay, callback)`` and is the event loop's timer on a running
    server. Left as ``None`` a mark drains inline, which keeps the queue usable
    where there is no loop to defer onto.

    A rebuild that raises is logged and skipped. The queue runs detached from
    the request that triggered it, so one unbuildable pane must cost neither the
    other panes their update nor the caller its response.
    """

    def __init__(self, resolve, rebuild, delay=DEFAULT_DEBOUNCE_SECONDS, schedule=None):
        self._resolve = resolve
        self._rebuild = rebuild
        self._delay = delay
        self._schedule = schedule
        self._pending = set()
        self._scheduled = False

    def mark(self, eid):
        """Record that ``eid`` changed and arrange for a drain."""
        self._pending.add(eid)
        if self._schedule is None:
            self.drain()
            return
        if self._scheduled:
            return

        self._scheduled = True
        try:
            self._schedule(self._delay, self.drain)
        except Exception:
            self._scheduled = False
            logging.exception("could not schedule an hparams live update")

    def drain(self):
        """Rebuild the panes affected by the marks collected so far.

        The pending marks are taken before anything is rebuilt, so a mark
        arriving while a rebuild runs opens the next round instead of being
        swallowed by this one.

        Resolving is guarded as well as rebuilding: the marks it was handed
        have already left ``_pending``, so letting it raise would lose that
        batch outright rather than one pane of it.
        """
        self._scheduled = False
        changed, self._pending = self._pending, set()
        if not changed:
            return

        try:
            targets = self._resolve(changed)
        except Exception:
            logging.exception("could not resolve the hparams panes to live-update")
            return

        for eid, win_id in targets:
            try:
                self._rebuild(eid, win_id)
            except Exception:
                logging.exception(
                    "could not live-update hparams window %r in env %r", win_id, eid
                )
