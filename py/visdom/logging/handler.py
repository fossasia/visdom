# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Lightweight logging handler for vanilla PyTorch training loops.

Usage as a context manager::

    from visdom.logging import VisdomLoggingHandler

    with VisdomLoggingHandler(env="train_run") as logger:
        for epoch in range(100):
            loss = train_one_epoch(model, dataloader)
            logger.log({"loss": loss, "accuracy": acc}, step=epoch)

Usage as a decorator::

    @VisdomLoggingHandler(env="train_run")
    def train(logger):
        for epoch in range(10):
            logger.log({"loss": compute_loss()}, step=epoch)
"""

import threading
from fnmatch import fnmatch
from functools import wraps

import numpy as np

from visdom import Visdom


class VisdomLoggingHandler:
    """Context-manager / decorator that logs metrics to Visdom ``line`` plots.

    Each unique metric name gets its own Visdom window.  Subsequent calls to
    :meth:`log` with the same metric name *append* to the existing window.

    This class performs **no** gradient computation or training logic — it is a
    pure visualization bridge.

    Args:
        server: Visdom server address (default ``"http://localhost"``).
        port: Visdom server port (default ``8097``).
        base_url: Visdom base URL (default ``"/"``).
        env: Visdom environment name (default ``"main"``).
        include_metrics: Optional list of glob patterns.  If provided, only
            metric names matching at least one pattern will be logged.
        exclude_metrics: Optional list of glob patterns.  Metric names matching
            any pattern will be skipped.
        offline: If ``True``, log to file instead of a running server.
        log_to_filename: Path for offline logging file.
        viz: An existing :class:`~visdom.Visdom` instance to re-use.  When
            supplied, *server*, *port*, *base_url*, *env*, *offline*, and
            *log_to_filename* are ignored.
    """

    def __init__(
        self,
        server="http://localhost",
        port=8097,
        base_url="/",
        env="main",
        include_metrics=None,
        exclude_metrics=None,
        offline=False,
        log_to_filename=None,
        viz=None,
    ):
        self._server = server
        self._port = port
        self._base_url = base_url
        self._env = env
        self._include = include_metrics
        self._exclude = exclude_metrics
        self._offline = offline
        self._log_to_filename = log_to_filename

        # Lazily created / user-supplied Visdom instance.
        self._viz = viz

        # metric_name -> window_id
        self._windows = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_viz(self):
        """Return (and lazily create) the underlying Visdom connection."""
        if self._viz is None:
            self._viz = Visdom(
                server=self._server,
                port=self._port,
                base_url=self._base_url,
                env=self._env,
                raise_exceptions=True,
                use_incoming_socket=False,
                offline=self._offline,
                log_to_filename=self._log_to_filename,
            )
        return self._viz

    def _should_log(self, name):
        """Check metric *name* against include / exclude filters."""
        if self._exclude:
            for pat in self._exclude:
                if fnmatch(name, pat):
                    return False
        if self._include:
            return any(fnmatch(name, pat) for pat in self._include)
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(self, metrics, step=None):
        """Log a dictionary of scalar metrics.

        Args:
            metrics: ``dict[str, float]`` mapping metric names to values.
            step: Optional global step number used as the X-axis value.
                  If ``None``, points are appended sequentially.
        """
        viz = self._get_viz()
        for name, value in metrics.items():
            if not self._should_log(name):
                continue

            y = np.array([float(value)])
            x = np.array([float(step)]) if step is not None else None

            with self._lock:
                win = self._windows.get(name)

            if win is not None:
                viz.line(
                    Y=y,
                    X=x,
                    win=win,
                    env=self._env,
                    update="append",
                    opts=dict(title=name, xlabel="step", ylabel=name),
                )
            else:
                new_win = viz.line(
                    Y=y,
                    X=x,
                    env=self._env,
                    opts=dict(title=name, xlabel="step", ylabel=name),
                )
                with self._lock:
                    self._windows[name] = new_win

    def log_text(self, text, win=None, append=False):
        """Log arbitrary text / HTML to a Visdom text pane.

        Args:
            text: Text or HTML string to display.
            win: Optional window ID to target.
            append: If ``True``, append to an existing text pane.
        """
        viz = self._get_viz()
        return viz.text(text, win=win, env=self._env, append=append)

    def log_image(self, img, win=None, opts=None):
        """Log an image tensor to a Visdom image pane.

        Args:
            img: Image tensor (``CxHxW`` or ``HxW``).
            win: Optional window ID.
            opts: Optional Visdom image options dict.
        """
        viz = self._get_viz()
        return viz.image(img, win=win, env=self._env, opts=opts)

    @property
    def env(self):
        """Return the current Visdom environment name."""
        return self._env

    @property
    def windows(self):
        """Return a copy of the metric-name → window-ID mapping."""
        with self._lock:
            return dict(self._windows)

    # ------------------------------------------------------------------
    # Context-manager protocol
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False  # do not suppress exceptions

    # ------------------------------------------------------------------
    # Decorator protocol
    # ------------------------------------------------------------------

    def __call__(self, func):
        """Use as ``@VisdomLoggingHandler(...)`` decorator.

        The decorated function receives this handler as its first argument.
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(self, *args, **kwargs)

        return wrapper
