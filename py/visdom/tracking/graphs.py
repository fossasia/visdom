#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Auto-logging hook for Visdom's chart-drawing methods .

As (``tracking.core``) needs an explicit ``run.log_event(...)`` call
every time something worth recording happens. This module removes that for
the most common case -- plotting a metric -- by wrapping a ``Visdom``
instance so calling e.g. ``.line()`` through the wrapper also records the
update on the associated :class:`~visdom.tracking.core.RunTracker`, with no
change to how the plotting call itself is made::

    run = RunTracker("exp1", params={"lr": 0.01})
    tvis = run.track(vis)

    win = None
    for epoch in range(epochs):
        win = tvis.line(X=[epoch], Y=[loss], win=win, update="append" if win else None)
        # ^ logged automatically: which window, whether this is the window's
        # 1st/2nd/3rd... update, and how long since its previous update.

Intentionally scoped to chart methods only (see ``GRAPH_METHODS`` below) --
media methods like ``image``/``video``/``text``/``table`` are a separate
concern for a later part, since "how many times has this metric updated and
how far apart" isn't a meaningful question for a one-shot image upload the
same way it is for a line plot.
"""

from __future__ import annotations

import warnings
from typing import Any

from visdom.tracking.core import RunAlreadyFinishedError


GRAPH_METHODS = frozenset(
    {
        "line",
        "scatter",
        "bar",
        "heatmap",
        "histogram",
        "histogram2d",
        "boxplot",
        "pie",
        "stem",
        "surf",
        "contour",
        "quiver",
        "mesh",
        "violin",
        "dual_axis_lines",
        "parallel_coordinates",
        "sunburst",
        "sankey",
        "roc_curve",
        "pr_curve",
        "confusion_matrix",
        "learning_curve",
        "graph",
        "embeddings",
        "plotlyplot",
    }
)

NON_GRAPH_METHODS = frozenset(
    {
        "audio",
        "html_table",
        "image",
        "image_heatmap",
        "image_select",
        "images",
        "matplot",
        "properties",
        "svg",
        "table",
        "text",
        "update_image_slider",
        "video",
        "check_connection",
        "clear_event_handlers",
        "close",
        "delete_env",
        "delete_envs",
        "fork_env",
        "get_env_list",
        "get_env_state",
        "get_window_data",
        "register_event_handler",
        "replay_log",
        "save",
        "save_plotly_figure",
        "set_window_data",
        "setup_polling",
        "setup_socket",
        "update_window_opts",
        "win_exists",
        "compare_experiments",
        "experiment",
        "finish_experiment",
        "hparams",
        "log_metrics",
        "search_experiments",
        "suggest_experiment",
    }
)


def _resolve_win(result: Any, kwargs: dict) -> Any:
    """Best-effort figure out which window a call actually touched.

    Every wrapped method returns the resolved window id as a string on
    success -- including when the caller passed ``win=None`` and the server
    auto-generated a name (visdom's own examples rely on this: the common
    ``win = viz.line(...)`` pattern reuses that return value on later
    calls). That return value is authoritative, so it's preferred over
    whatever the caller passed in.

    Falls back to an explicit ``win=`` keyword argument if the return value
    isn't a usable string (e.g. a connection error returned ``False``/
    ``None`` instead of raising, when the client was built with
    ``raise_exceptions=False``). Returns ``None`` if neither is available,
    which tells the caller to skip logging rather than record a guess.

    Does not attempt to recover a positional ``win`` argument -- if a
    caller passes it positionally *and* the call didn't return a usable
    win, the update simply won't be auto-logged. Passing ``win=`` by
    keyword (as every visdom example does) avoids this entirely.
    """
    if isinstance(result, str) and result:
        return result
    win = kwargs.get("win")
    if isinstance(win, str) and win:
        return win
    return None


class TrackedVisdom:
    """Transparent proxy around a ``Visdom`` instance with auto-logged charts.

    Every attribute access other than the chart methods listed in
    ``GRAPH_METHODS`` passes straight through to the wrapped instance
    unchanged -- ``tvis.env``, ``tvis.image(...)``, ``tvis.close(...)`` all
    behave exactly as if you'd called them on ``vis`` directly. Only the
    charting calls get the extra logging.

    Delegation is safe against double-logging: several chart methods build
    on another one internally (``histogram`` calls ``self.bar``, ``stem``
    and ``quiver`` call ``self.scatter``, ``line`` calls ``self.scatter``,
    ``surf``/``contour`` share ``self._surface``, ``learning_curve`` calls
    ``self.line``) -- but that ``self`` is always the *real* ``Visdom``
    instance, never this proxy, so calling ``tvis.histogram(...)`` logs
    exactly one ``histogram`` event, not a ``histogram`` plus a ``bar``.

    Tracking failures never break plotting: if logging an update raises
    (e.g. the run already finished), the exception is swallowed and the
    plot call's own result is still returned untouched. A failure in the
    *plot* call itself is different -- that exception always propagates,
    and is logged as a ``plot_error`` event first (best-effort) so it shows
    up in the run's record too.
    """

    def __init__(self, vis, run):
        object.__setattr__(self, "_vis", vis)
        object.__setattr__(self, "_run", run)
        object.__setattr__(self, "_wrapped_cache", {})

    def __getattr__(self, item):
        if item in GRAPH_METHODS:
            cached = self._wrapped_cache.get(item)
            if cached is not None:
                return cached
            attr = getattr(self._vis, item)
            if not callable(attr):
                return attr
            wrapped = self._wrap(item, attr)
            self._wrapped_cache[item] = wrapped
            return wrapped
        return getattr(self._vis, item)

    def __setattr__(self, key, value):
        setattr(self._vis, key, value)

    def __repr__(self):
        return "TrackedVisdom({0!r}, run={1!r})".format(self._vis, self._run.run_id)

    def _wrap(self, method_name, bound_method):
        def wrapper(*args, **kwargs):
            try:
                result = bound_method(*args, **kwargs)
            except Exception as e:
                self._log_best_effort(
                    "plot_error",
                    win=kwargs.get("win"),
                    method=method_name,
                    error="{0}: {1}".format(type(e).__name__, e),
                )
                raise  # the plot call's own failure is never swallowed

            win = _resolve_win(result, kwargs)
            if win is not None:
                self._log_best_effort(
                    "plot_update",
                    win=win,
                    method=method_name,
                    update=kwargs.get("update"),
                )
            return result  # always the plotting call's real, untouched result

        wrapper.__name__ = getattr(bound_method, "__name__", method_name)
        wrapper.__doc__ = getattr(bound_method, "__doc__", None)
        return wrapper

    def _log_best_effort(self, kind, win, method, **extra):
        """Log to the run, but never let a tracking problem look like a
        plotting problem (or mask a real one -- see the except Exception
        callers above, which always re-raise their own exception after).

        ``RunAlreadyFinishedError`` is expected/benign (the run simply
        already ended) and is swallowed silently. Anything else is an
        unexpected bug in the tracking code itself -- still swallowed, so
        it can never surface as a broken plot call, but surfaced as a
        warning rather than vanishing without a trace, since a silently
        eaten TypeError/AttributeError here would otherwise be close to
        undebuggable.
        """
        try:
            if kind == "plot_update":
                self._run.log_plot_update(method, win, **extra)
            else:
                self._run.log_event(kind, win=win, method=method, **extra)
        except RunAlreadyFinishedError:
            pass
        except Exception as e:
            warnings.warn(
                "visdom.tracking: failed to record {0!r} for window {1!r} "
                "({2}: {3}) -- the plot call itself still succeeded "
                "normally, only the tracking record is affected.".format(
                    kind, win, type(e).__name__, e
                ),
                RuntimeWarning,
                stacklevel=3,
            )
