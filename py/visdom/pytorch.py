#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import datetime

from visdom.tracking.core import RunAlreadyFinishedError, _safe_warn


class VisdomLogger:
    """Context manager for logging scalar metrics to Visdom from a raw PyTorch
    training loop.

    Handles window creation, step tracking, and log_every throttling
    automatically. The user calls log(name, value) for every metric — no
    viz.line() arguments needed.

    Passing params opts into experiment tracking: the run is recorded in
    the ExperimentStore (viz.experiment() on enter, viz.log_metrics()
    alongside every plotted point, viz.finish_experiment() on exit) so it
    becomes queryable via viz.search_experiments() / viz.compare_experiments().
    Without params, VisdomLogger only ever calls viz.line() — same as
    before this existed. status is "failed" if the with-block raised,
    "finished" otherwise.

    Separately, pass a :class:`visdom.tracking.RunTracker` via ``run=`` to
    additionally record every metric update to that run's local
    reproducibility record (params, environment, and this training curve's
    timeline) — a different, local-JSON-file mechanism from the
    server-side ExperimentStore that ``params=`` uses. The two are
    independent and can be used together, separately, or not at all; the
    run's own lifecycle (finish reason, params, etc.) stays entirely under
    your control, since the two context managers compose independently
    rather than one driving the other::

        from visdom.tracking import RunTracker
        from visdom.pytorch import VisdomLogger

        with RunTracker("exp1", params={"lr": 0.01}) as run:
            with VisdomLogger(viz, env="run_1", run=run) as tracker:
                for epoch in range(num_epochs):
                    tracker.log("Train Loss", train_loss)  # plotted AND tracked

    Nest in that order -- ``run`` outer, ``VisdomLogger`` inner, as above
    -- not the reverse. ``VisdomLogger.__exit__`` flushes any value still
    held back by ``log_every`` throttling, and that flush has to happen
    while ``run`` is still open to be recorded; nesting the other way
    finishes ``run`` first, so the flushed value's tracking call silently
    no-ops (``RunAlreadyFinishedError`` is swallowed, by design, same as
    any other already-finished-run write) instead of raising to tell you
    something was dropped.

    Only values that actually get plotted are recorded to ``run`` — a value
    withheld by ``log_every`` throttling and later flushed on exit is
    recorded once, at the point it's actually plotted, not once per raw
    ``log()`` call. "Actually get plotted" is checked, not assumed: a
    client built with ``raise_exceptions=False`` can have ``viz.line()``
    return ``False``/``None`` on a failed send instead of raising, and that
    point is skipped for both ``run=`` and ``params=`` tracking rather than
    recorded as if it had succeeded. A failure while recording to ``run``
    never breaks the plot itself: the ``viz.line()`` call has already
    succeeded by the time recording is attempted, and any unexpected
    recording failure surfaces as a warning rather than an exception (the
    run already having finished is expected/benign and stays silent).

    ``run=``, if passed, must be a :class:`~visdom.tracking.RunTracker` (or
    a duck-typed equivalent exposing a callable ``log_plot_update()``) —
    anything else raises ``TypeError`` immediately, rather than appearing
    to work and then failing confusingly on the first logged metric.

    Do not pass a proxy returned by ``run.track(viz)`` as ``viz`` here
    while also passing that same run as ``run=`` — that double-tracks
    every update (once via the proxy, once via this class's own ``run=``
    handling). Use exactly one of the two integration points for a given
    ``viz``/``run`` pair: either ``VisdomLogger(viz, run=run)`` with the
    *plain* Visdom instance, or ``run.track(viz)`` on its own without also
    passing ``run=`` here.

    Usage::

        from visdom.pytorch import VisdomLogger

        with VisdomLogger(viz, env="run_1") as tracker:
            for epoch in range(num_epochs):
                train_loss = run_train_epoch(model, loader)
                val_loss   = run_val_epoch(model, val_loader)

                tracker.log("Train Loss", train_loss)
                tracker.log("Val Loss",   val_loss)
                tracker.log("LR",         optimizer.param_groups[0]["lr"])

        # with experiment tracking
        with VisdomLogger(viz, env="run_1", params={"lr": 0.01}) as tracker:
            for epoch in range(num_epochs):
                tracker.log("Train Loss", train_loss)
    """

    def __init__(self, viz, env=None, log_every=1, params=None, run=None):
        self.viz = viz
        self.env = env or "run_{}".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        self.log_every = int(log_every)
        if self.log_every < 1:
            raise ValueError("log_every must be >= 1, got {}".format(log_every))
        self._params = params
        if run is not None and not callable(getattr(run, "log_plot_update", None)):
            # Fail fast and clearly here, at construction time, rather than
            # letting a nonsensical run= (a plain string, an int, some
            # unrelated object) silently no-op its way to a crash deep
            # inside _log_to_run's own warning formatting the first time a
            # metric is logged -- see the run_id access there, which
            # assumes `run` is at least roughly RunTracker-shaped. callable(),
            # not just hasattr(): an object whose log_plot_update is present
            # but None (or any other non-callable) would pass a bare hasattr
            # check and then raise TypeError on every single logged metric
            # when _log_to_run actually tries to call it -- every point
            # silently untracked and warned about, instead of one clear
            # error up front. Checking for log_plot_update specifically
            # (not isinstance(run, RunTracker)) keeps the same deliberate
            # duck-typing this module already uses for the run.track(viz)
            # detection below, so a test double/mock with the right
            # interface still works.
            raise TypeError(
                "run must be a visdom.tracking.RunTracker (or a duck-typed "
                "equivalent exposing a callable log_plot_update()), got "
                "{!r}".format(run)
            )
        self.run = run
        # Best-effort detection of the double-tracking mistake described
        # above: run.track(viz) returns a proxy that stores the run it's
        # attached to as `_run` (see visdom.tracking.graphs.TrackedVisdom).
        # Not imported/isinstance-checked here on purpose, to avoid a
        # hard dependency on that module from this one -- duck-typed
        # instead, since all that actually matters is "does this viz
        # appear to already be tracking to the exact run= we were also
        # given".
        if run is not None and getattr(viz, "_run", None) is run:
            _safe_warn(
                "VisdomLogger was given a viz that already tracks to "
                "the same run (e.g. via run.track(viz)) and run= was "
                "also passed -- every logged metric will be recorded "
                "twice. Use either run.track(viz) on its own, or "
                "VisdomLogger(viz, run=run) with the plain Visdom "
                "instance, not both together.",
                RuntimeWarning,
                stacklevel=2,
            )
        self._wins = {}
        self._step = {}
        self._counter = {}
        self._pending = {}

    @staticmethod
    def _check_experiment_reply(reply, action):
        """Warn if the server rejected an experiment-tracking call.

        Connection failures raise and are caught by the callers below, but a
        server-side rejection (readonly server, already-finished experiment,
        unknown env) comes back as an ordinary reply with no exception. A
        successful reply is always the stored experiment dict, keyed by
        "env_id"; anything else means nothing was recorded. `reply is True`
        is `_send`'s own sentinel for offline mode, where nothing was sent
        to a server at all, so it is not a rejection.

        Returns True if the call succeeded (or was offline), False if it
        was rejected, so __enter__ can stop retrying after a failed handshake.
        """
        if reply is True:
            return True
        if not isinstance(reply, dict) or "env_id" not in reply:
            _safe_warn(
                "VisdomLogger failed to {}: {}".format(action, reply), UserWarning
            )
            return False
        return True

    def __enter__(self):
        if self._params is not None:
            try:
                reply = self.viz.experiment(params=self._params, env=self.env)
                if not self._check_experiment_reply(reply, "start experiment tracking"):
                    self._params = None
            except Exception as e:
                _safe_warn(
                    "VisdomLogger failed to start experiment tracking: {}".format(e),
                    UserWarning,
                )
                self._params = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for name, (x_val, value, xlabel) in self._pending.items():
            self._plot(name, x_val, value, xlabel)
        if self._params is not None:
            try:
                reply = self.viz.finish_experiment(
                    status="failed" if exc_type else "finished", env=self.env
                )
                self._check_experiment_reply(reply, "finish experiment tracking")
            except Exception as e:
                _safe_warn(
                    "VisdomLogger failed to finish experiment tracking: {}".format(e),
                    UserWarning,
                )
        return False

    def _plot(self, name, x_val, value, xlabel):
        """Send one point to viz.line(), then best-effort mirror it to
        params=/run= tracking if (and only if) the send actually succeeded.

        Returns True if the point was actually plotted, False if the send
        failed (or raised) -- log() uses this to decide whether to clear
        the metric's pending buffer or keep the value there for a retry
        on the metric's next call, or at the context manager's exit flush.
        """
        win = None
        try:
            if name not in self._wins:
                win = self.viz.line(
                    X=[x_val],
                    Y=[value],
                    env=self.env,
                    opts={"title": name, "xlabel": xlabel, "ylabel": name},
                )
            else:
                win = self.viz.line(
                    X=[x_val],
                    Y=[value],
                    win=self._wins[name],
                    env=self.env,
                    update="append",
                )
        except Exception as e:
            _safe_warn(
                "VisdomLogger failed to log {!r}: {}".format(name, e), UserWarning
            )
            return False
        # viz.line() doesn't always raise on failure: a client built with
        # raise_exceptions=False can return False/None from a failed send
        # instead -- a real attempt that the server never actually applied.
        # Plain truthiness is deliberately all that's checked here (not,
        # say, requiring a str): the real client only ever returns a
        # string win id or the True offline-mode sentinel on success (see
        # _check_experiment_reply's docstring above), but this also has to
        # keep working for any other truthy stand-in a wrapped/mocked viz
        # returns, matching the plain `if win:` convention this module's
        # window-caching already uses elsewhere. Without this check at
        # all, a non-raising failed append would silently keep whatever
        # window id the *previous, genuinely successful* call left behind
        # and have both log_metrics() and run= tracking below record this
        # failed point as if it had actually been plotted.
        send_ok = bool(win)
        if not send_ok:
            return False
        if name not in self._wins:
            # Only cache a window id once creation has actually succeeded
            # (send_ok is True here) -- caching a falsy one would make
            # every later call for this metric believe a window already
            # exists (the check right above is membership, not
            # truthiness) and permanently skip retrying creation; log()'s
            # own throttle is based on the call counter rather than this
            # dict precisely so a failed creation doesn't also disable
            # throttling. An append's own win is deliberately never
            # (re)cached here: the id already on file from the successful
            # creation is the one every later append keeps using,
            # regardless of this particular call's result.
            self._wins[name] = win

        # send_ok (just above) only asks "did we get *something* back to
        # reuse" -- enough to stop retrying and to key the next append.
        # params=/run= tracking is a separate, stronger claim ("this point
        # is durably recorded as plotted"), so it needs a correspondingly
        # stronger check: the real client only ever returns a string
        # window id or the True offline-mode sentinel on success: nothing
        # else is a value _resolve_win (visdom.tracking.graphs) or
        # RunTracker.log_plot_update know how to validate either. A
        # wrapped/mocked viz.line() that returns some other truthy
        # placeholder (an int, a Mock, a list) still gets cached/reused
        # above so it isn't retried forever, but that alone isn't grounds
        # to tell params=/run= the point was verifiably plotted.
        verified = win is True or (isinstance(win, str) and win)
        if verified and self._params is not None:
            # Its own try/except, separate from the viz.line() one above:
            # log_metrics() is a second, unrelated call (to the
            # ExperimentStore, not the plot itself), and a failure here
            # must not look like the plot itself failed -- in particular,
            # it must not suppress run= tracking below, since the point
            # genuinely was plotted successfully regardless of whether
            # this ExperimentStore call succeeds.
            try:
                reply = self.viz.log_metrics({name: value}, step=x_val, env=self.env)
                self._check_experiment_reply(reply, "log metric {!r}".format(name))
            except Exception as e:
                _safe_warn(
                    "VisdomLogger failed to log metric {!r}: {}".format(name, e),
                    UserWarning,
                )
        if verified and self.run is not None:
            # RunTracker.log_plot_update keys its per-window sequence
            # counters on win, so passing True straight through would
            # collapse every metric onto that one shared value instead of
            # keeping each metric's window_update_seq independent (every
            # offline-mode call returns the identical True sentinel).
            # name is used as the fallback here specifically because it's
            # already guaranteed to be a non-empty string, unique per
            # metric within this VisdomLogger instance.
            tracked_win = win if isinstance(win, str) and win else name
            self._log_to_run(name, tracked_win, x_val, value, xlabel)
        return True

    def _log_to_run(self, name, win, x_val, value, xlabel):
        """Best-effort record this already-plotted update on self.run.

        Reuses RunTracker.log_plot_update -- the same per-window
        sequence/timing primitive TrackedVisdom (visdom.tracking.graphs)
        uses for auto-logged chart calls -- rather than a separate,
        parallel bookkeeping mechanism. Kept as a separate try/except from
        _plot()'s own (which guards the actual viz.line()/log_metrics()
        calls) so a tracking-only failure here is reported with its own,
        more specific message rather than being folded into _plot()'s
        generic "failed to log" warning -- and, since this method never
        lets anything escape (RunAlreadyFinishedError is swallowed
        silently, anything else becomes a warning via _safe_warn), it's
        safe to call after _plot()'s own try/except has already
        succeeded, with no risk of a tracking failure retroactively
        looking like a plotting failure.
        """
        try:
            self.run.log_plot_update(
                "line", win, name=name, value=value, x=x_val, xlabel=xlabel
            )
        except RunAlreadyFinishedError:
            pass
        except Exception as e:
            # stacklevel=4: warn() -> _log_to_run -> _plot -> log() (or
            # __exit__, for a value flushed at context-manager exit) ->
            # the user's call site. One deeper than the equivalent warning
            # in visdom.tracking.graphs, since _plot is an extra frame of
            # indirection that TrackedVisdom's wrapper doesn't have.
            _safe_warn(
                "visdom.pytorch: failed to record metric {0!r} on run "
                "{1!r} ({2}: {3}) -- the plot itself still succeeded "
                "normally, only the tracking record is affected.".format(
                    # getattr, not self.run.run_id directly: __init__
                    # already rejects a run= that lacks log_plot_update
                    # entirely, but a duck-typed object can still satisfy
                    # that check while lacking run_id specifically (e.g. a
                    # test double, or a genuinely broken log_plot_update
                    # implementation on an otherwise-valid-looking object).
                    # That must not turn this best-effort warning itself
                    # into a second, unrelated crash.
                    name,
                    getattr(self.run, "run_id", repr(self.run)),
                    type(e).__name__,
                    e,
                ),
                RuntimeWarning,
                stacklevel=4,
            )

    def log(self, name, value, x=None, xlabel="epoch"):
        """Log a scalar value under the given metric name.

        Call once per epoch outside the batch loop. The x-axis auto-increments
        from 1 so graphs read "epoch 1 ... N" with no extra arguments needed.

        Args:
            name: metric name, used as the window title and y-axis label.
            value: scalar value to plot.
            x: override the x-axis position. Use only when you need an
               explicit value (e.g. global batch step for per-batch logging).
            xlabel: x-axis label (default: "epoch"). Set to "step" when
               logging inside the batch loop with log_every.

        Note:
            log_every is intended for per-batch logging only. When logging
            once per epoch, leave log_every=1 — the epoch counter handles
            throttling by design. The first call for a metric is always
            plotted immediately, and any value still waiting on log_every
            when the context manager exits is flushed automatically — no
            metric is ever silently dropped.
        """
        if not isinstance(name, str) or not name:
            raise TypeError("name must be a non-empty string, got {!r}".format(name))

        if hasattr(value, "item"):
            value = value.item()
        if not isinstance(value, (int, float)):
            raise TypeError(
                "value must be a number, got {!r}".format(type(value).__name__)
            )

        self._counter[name] = self._counter.get(name, 0) + 1
        if x is None:
            self._step[name] = self._step.get(name, 1) + 1

        x_val = x if x is not None else self._step.get(name, 1) - 1

        if self._counter[name] > 1 and self._counter[name] % self.log_every != 0:
            self._pending[name] = (x_val, value, xlabel)
            return

        if self._plot(name, x_val, value, xlabel):
            self._pending.pop(name, None)
        else:
            self._pending[name] = (x_val, value, xlabel)
