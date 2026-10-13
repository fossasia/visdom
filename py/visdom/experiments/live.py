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

The queue is handed a resolver and a rebuild coroutine rather than reaching for
either itself, which is what lets the server point it at the existing
``experiments/hparams/update`` write path without this module knowing about
Tornado, handlers or windows. A rebuild reads and writes disk, so it is awaited
rather than called: on the server that work runs on the storage worker, and the
event loop stays free while it does.
"""

import asyncio
import logging

DEFAULT_DEBOUNCE_SECONDS = 0.25

#: Drains started by :func:`_call_later_on_running_loop` that have not finished.
_DRAINS = set()


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


def _call_later_on_running_loop(delay, drain):
    """Run the coroutine function ``drain`` on the running loop after ``delay``.

    The loop keeps only a weak reference to a task, so a drain parked on the
    storage worker could be collected half way through; each one is held in
    ``_DRAINS`` until it finishes. Called without a running loop this raises
    ``RuntimeError``, which :class:`LiveUpdateQueue` logs and recovers from.
    """
    loop = asyncio.get_running_loop()

    def start():
        task = loop.create_task(drain())
        _DRAINS.add(task)
        task.add_done_callback(_DRAINS.discard)

    loop.call_later(delay, start)


class LiveUpdateQueue:
    """Coalesce "this env changed" notices and rebuild the panes showing it.

    ``resolve`` maps the set of changed env ids to the panes to rebuild (see
    :func:`resolve_targets`); ``rebuild`` is a coroutine function awaited once
    per pane as ``await rebuild(eid, win_id)``.

    ``schedule`` is how a drain is deferred: it is called as
    ``schedule(delay, drain)`` with the coroutine function :meth:`drain`, and
    owns running it. Left as ``None`` the drain becomes a task on the running
    event loop, which is the server's loop, since only a request marks.

    Drains never overlap. A mark arriving while one runs is recorded, and the
    next drain is armed when the current one finishes, so a pane is never
    rebuilt by two drains at once however long its selection takes to read.

    A rebuild that raises is logged and skipped. The queue runs detached from
    the request that triggered it, so one unbuildable pane must cost neither the
    other panes their update nor the caller its response.
    """

    def __init__(self, resolve, rebuild, delay=DEFAULT_DEBOUNCE_SECONDS, schedule=None):
        self._resolve = resolve
        self._rebuild = rebuild
        self._delay = delay
        self._schedule = schedule or _call_later_on_running_loop
        self._pending = set()
        self._scheduled = False
        self._draining = False

    def mark(self, eid):
        """Record that ``eid`` changed and arrange for a drain."""
        self._pending.add(eid)
        if self._scheduled or self._draining:
            return
        self._arm()

    def _arm(self):
        self._scheduled = True
        try:
            self._schedule(self._delay, self.drain)
        except Exception:
            self._scheduled = False
            logging.exception("could not schedule an hparams live update")

    async def drain(self):
        """Rebuild the panes affected by the marks collected so far.

        The pending marks are taken before anything is rebuilt, so a mark
        arriving while a rebuild runs opens the next round instead of being
        swallowed by this one; that round is armed once this one is done.

        Resolving is guarded as well as rebuilding: the marks it was handed
        have already left ``_pending``, so letting it raise would lose that
        batch outright rather than one pane of it.
        """
        self._scheduled = False
        changed, self._pending = self._pending, set()
        if not changed:
            return

        self._draining = True
        try:
            await self._rebuild_targets(changed)
        finally:
            self._draining = False
            if self._pending and not self._scheduled:
                self._arm()

    async def _rebuild_targets(self, changed):
        try:
            targets = self._resolve(changed)
        except Exception:
            logging.exception("could not resolve the hparams panes to live-update")
            return

        for eid, win_id in targets:
            try:
                await self._rebuild(eid, win_id)
            except Exception:
                logging.exception(
                    "could not live-update hparams window %r in env %r", win_id, eid
                )
