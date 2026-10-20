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
    also record every metric update to that run's local reproducibility
    record. This is independent of ``params=`` (a different, local-JSON-file
    mechanism) and the two can be used together, separately, or not at all::

        from visdom.tracking import RunTracker
        from visdom.pytorch import VisdomLogger

        with RunTracker("exp1", params={"lr": 0.01}) as run:
            with VisdomLogger(viz, env="run_1", run=run) as tracker:
                for epoch in range(num_epochs):
                    tracker.log("Train Loss", train_loss)  # plotted AND tracked

    Nest in that order -- ``run`` outer, ``VisdomLogger`` inner -- not the
    reverse, or a value flushed at exit will find ``run`` already finished
    and silently fail to record.

    Only values that actually get plotted are recorded to ``run``/``params``
    -- a send that fails (whether it raises, or returns False/None the way
    a client built with ``raise_exceptions=False`` can) is skipped rather
    than recorded as if it had succeeded.

    When ``viz.line()`` can't report a real window id (offline mode), this
    metric's own name is used as a stand-in identity for ``run=`` tracking
    instead. That stand-in is only unique within one ``VisdomLogger``
    instance, so sharing one ``run=`` across multiple instances with the
    same metric name, in offline mode, can merge their sequences -- give
    each instance its own ``run=`` if you need that.

    ``run=``, if passed, must be a :class:`~visdom.tracking.RunTracker` (or
    a duck-typed equivalent exposing a callable ``log_plot_update()``) —
    anything else raises ``TypeError`` immediately.

    Do not pass a proxy returned by ``run.track(viz)`` as ``viz`` here
    while also passing that same run as ``run=`` — that double-tracks
    every update. Use exactly one of the two: either
    ``VisdomLogger(viz, run=run)`` with the plain Visdom instance, or
    ``run.track(viz)`` on its own.

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
            # Fail fast here rather than crashing confusingly on the first
            # logged metric.
            raise TypeError(
                "run must be a visdom.tracking.RunTracker (or a duck-typed "
                "equivalent exposing a callable log_plot_update()), got "
                "{!r}".format(run)
            )
        self.run = run
        # run.track(viz) stores the run it's attached to as viz._run.
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
        # Metrics whose _pending entry actually failed to send, as opposed
        # to one merely withheld by throttling. See log() below.
        self._pending_failed = set()

    @staticmethod
    def _check_experiment_reply(reply, action):
        """Warn if the server rejected an experiment-tracking call.

        A successful reply is always the stored experiment dict (keyed by
        "env_id"); `reply is True` is the offline-mode sentinel, not a
        rejection. Returns whether the call succeeded (or was offline).
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
        # Last chance to send anything still buffered -- there's no later
        # log() call to retry on, so a failure here is warned about (with
        # the metric and value named) instead of being dropped silently,
        # and the point is left in _pending/_pending_failed for inspection.
        for name, (x_val, value, xlabel) in list(self._pending.items()):
            if self._plot(name, x_val, value, xlabel):
                self._pending.pop(name, None)
                self._pending_failed.discard(name)
            else:
                self._pending_failed.add(name)
                _safe_warn(
                    "VisdomLogger: final flush of metric {0!r} (value={1!r}) "
                    "failed and will not be retried. It remains available "
                    "in tracker._pending[{0!r}].".format(name, value),
                    UserWarning,
                )
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

    @staticmethod
    def _looks_like_a_window_id(win):
        """Whether `win` could plausibly be a real window id: a single
        token with no whitespace, not starting with '{', '[' or '<'
        (which rules out JSON and HTML), and containing at least one
        digit (which rules out plain-word error bodies like "Forbidden",
        "Unauthorized" or "ERROR" -- every window id Visdom actually
        generates, client-side (``"window_" + <hex timestamp>``) or
        server-side (``"window_" + <uuid4>``), is built from a
        random/hex/uuid suffix and so always contains a digit; a
        caller-supplied win is never checked here since _plot() only
        ever reaches this heuristic for server-generated ids).
        Visdom's transport returns the raw HTTP response body without
        checking the status code, so a rejected request can come back as
        an ordinary truthy string too, and this is what tells the two
        apart when there's nothing else to go on (see _is_verified_win).
        This is still only a heuristic, not a guarantee -- a status-code
        check at the transport level would be airtight where this can't
        be, but is outside what this method can do with a plain string.
        """
        return (
            isinstance(win, str)
            and bool(win)
            and win[0] not in "{[<"
            and not any(c.isspace() for c in win)
            and any(c.isdigit() for c in win)
        )

    @classmethod
    def _is_verified_win(cls, win, expected_win):
        """Whether `win` -- whatever viz.line() returned -- actually proves
        the server applied this point, strongly enough to record it to
        params=/run=.

        If `expected_win` is itself trustworthy (a value that looks like
        a real window id, or the offline sentinel True), a real success
        must echo it back exactly -- this is what makes an append's
        check airtight regardless of what a failure response looks like,
        and it is checked *before* the `win is True` fallback below so
        that sentinel can't be used to rubber-stamp a mismatch against an
        already-established id (e.g. a real cached window id with a
        later True response -- that is not proof this specific window
        was updated, whatever caused it). Without a trustworthy id to
        compare against (a fresh creation, or a window whose cached id
        was never actually verified), True is accepted as genuine (the
        offline sentinel), and otherwise this falls back to just
        checking `win` itself looks like a plausible id.
        """
        if cls._looks_like_a_window_id(expected_win):
            return win == expected_win
        if expected_win is True:
            return win is True
        if win is True:
            return True
        return cls._looks_like_a_window_id(win)

    def _plot(self, name, x_val, value, xlabel):
        """Send one point to viz.line(), then best-effort mirror it to
        params=/run= tracking if the send actually succeeded.

        Returns True if the point was actually plotted, False if the send
        failed (or raised) -- log() uses this to decide whether to clear
        the metric's pending buffer or retry on its next due call (see
        self._pending_failed), or at the context manager's exit flush.
        """
        expected_win = self._wins.get(name)
        try:
            if expected_win is None:
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
                    win=expected_win,
                    env=self.env,
                    update="append",
                )
        except Exception as e:
            _safe_warn(
                "VisdomLogger failed to log {!r}: {}".format(name, e), UserWarning
            )
            return False

        # A non-raising failed send (raise_exceptions=False) returns
        # False/None instead. Plain truthiness is enough here to decide
        # whether to keep reusing this window id and stop retrying --
        # params=/run= tracking needs the stronger _is_verified_win check
        # below instead, since it's a durable claim, not just "got
        # something back".
        if not win:
            return False
        if expected_win is None:
            self._wins[name] = win

        verified = self._is_verified_win(win, expected_win)
        if verified and self._params is not None:
            try:
                reply = self.viz.log_metrics({name: value}, step=x_val, env=self.env)
                self._check_experiment_reply(reply, "log metric {!r}".format(name))
            except Exception as e:
                _safe_warn(
                    "VisdomLogger failed to log metric {!r}: {}".format(name, e),
                    UserWarning,
                )
        if verified and self.run is not None:
            # RunTracker keys its per-window sequence on win, and every
            # offline-mode call returns the same True sentinel, so name is
            # used as a per-metric stand-in in that case instead.
            tracked_win = win if isinstance(win, str) else name
            self._log_to_run(name, tracked_win, x_val, value, xlabel)
        return True

    def _log_to_run(self, name, win, x_val, value, xlabel):
        """Best-effort record this already-plotted update on self.run.

        A failure here never affects the plot itself (which already
        succeeded) -- it's reported as its own warning rather than raised,
        except for RunAlreadyFinishedError, which is expected/benign and
        stays silent.
        """
        try:
            self.run.log_plot_update(
                "line", win, name=name, value=value, x=x_val, xlabel=xlabel
            )
        except RunAlreadyFinishedError:
            pass
        except Exception as e:
            _safe_warn(
                "visdom.pytorch: failed to record metric {0!r} on run "
                "{1!r} ({2}: {3}) -- the plot itself still succeeded "
                "normally, only the tracking record is affected.".format(
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
            when the context manager exits is flushed automatically.

            A point that fails to send is retried on the metric's next due
            call (the next call where log_every would otherwise trigger a
            send), rather than being silently replaced by a newer value in
            the meantime. There's only one pending slot per metric though:
            if that retry fails again, the newer value isn't queued either
            -- the same point keeps getting retried until it succeeds or
            the context manager exits.
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
            # Off-interval: buffer the value, unless a previous send
            # genuinely failed and is still waiting to be retried -- that
            # one must not be overwritten before it gets a chance.
            if name not in self._pending_failed:
                self._pending[name] = (x_val, value, xlabel)
            return

        # Due call: first call ever, or the log_every-th since the last
        # attempt. Retry a previously-failed point first, since it's the
        # oldest thing still owed to the server.
        if name in self._pending_failed:
            failed_x, failed_value, failed_xlabel = self._pending[name]
            if self._plot(name, failed_x, failed_value, failed_xlabel):
                self._pending.pop(name, None)
                self._pending_failed.discard(name)
                # Retry succeeded -- fall through to also send this call's
                # own value now, rather than stranding it until some
                # future call (which, with log_every == 1, might never
                # come via the throttling branch above).
            else:
                return

        if self._plot(name, x_val, value, xlabel):
            self._pending.pop(name, None)
        else:
            self._pending[name] = (x_val, value, xlabel)
            self._pending_failed.add(name)
