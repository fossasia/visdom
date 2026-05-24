# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""PyTorch Lightning ``Logger`` subclass backed by Visdom.

Usage::

    from visdom.logging import VisdomLogger
    from pytorch_lightning import Trainer

    logger = VisdomLogger(base_env="my_experiment")
    trainer = Trainer(logger=logger)
    trainer.fit(model, datamodule)
"""

from argparse import Namespace
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional, Union

import numpy as np

from pytorch_lightning.loggers.logger import Logger, rank_zero_experiment
from pytorch_lightning.utilities import rank_zero_only

from visdom import Visdom
from visdom.logging._version import get_next_version


class VisdomLogger(Logger):
    r"""Log to a Visdom server.

    Each scalar metric logged via :meth:`log_metrics` gets its own
    ``viz.line()`` window.  Hyper-parameters logged via
    :meth:`log_hyperparams` are rendered as an HTML table in a text pane.

    This logger performs **no** gradient computation or training logic — it
    is a pure visualization bridge.

    Args:
        server: Visdom server address.
        port: Visdom server port.
        base_url: Visdom base URL.
        env: Explicit environment name.  When ``None``, an auto-versioned
            name is derived from *base_env* (e.g. ``"run_000"``).
        base_env: Prefix for auto-versioned environment names.
        include_metrics: Optional whitelist of glob patterns.
        exclude_metrics: Optional blacklist of glob patterns.
        global_step_key: Key in the *metrics* dict to use as the X-axis
            value.  Defaults to ``"global_step"``.  If the key is absent
            from a given ``log_metrics`` call the step argument is used.
        offline: Run in offline mode (log to file only).
        log_to_filename: File path for offline logging.
    """

    def __init__(
        self,
        server: str = "http://localhost",
        port: int = 8097,
        base_url: str = "/",
        env: Optional[str] = None,
        base_env: str = "run",
        include_metrics: Optional[List[str]] = None,
        exclude_metrics: Optional[List[str]] = None,
        global_step_key: str = "global_step",
        offline: bool = False,
        log_to_filename: Optional[str] = None,
    ):
        super().__init__()

        self._server = server
        self._port = port
        self._base_url = base_url
        self._base_env = base_env
        self._include = include_metrics
        self._exclude = exclude_metrics
        self._global_step_key = global_step_key
        self._offline = offline
        self._log_to_filename = log_to_filename

        # Lazily initialised.
        self._viz = None
        self._env = env
        self._version = None

        # metric_name -> window_id
        self._windows: Dict[str, str] = {}
        self._hparams_win: Optional[str] = None

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _get_viz(self) -> Visdom:
        if self._viz is None:
            self._viz = Visdom(
                server=self._server,
                port=self._port,
                base_url=self._base_url,
                env=self._resolved_env,
                raise_exceptions=True,
                use_incoming_socket=False,
                offline=self._offline,
                log_to_filename=self._log_to_filename,
            )
        return self._viz

    @property
    def _resolved_env(self) -> str:
        if self._env is None:
            # Auto-version: create a temporary Visdom connection to scan envs.
            tmp = Visdom(
                server=self._server,
                port=self._port,
                base_url=self._base_url,
                env="main",
                raise_exceptions=False,
                use_incoming_socket=False,
                offline=self._offline,
                log_to_filename=self._log_to_filename,
            )
            self._env, self._version = get_next_version(tmp, self._base_env)
        return self._env

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _should_log(self, name: str) -> bool:
        if self._exclude:
            for pat in self._exclude:
                if fnmatch(name, pat):
                    return False
        if self._include:
            return any(fnmatch(name, pat) for pat in self._include)
        return True

    # ------------------------------------------------------------------
    # Logger interface (required by Lightning)
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Return the experiment name (the base_env prefix)."""
        return self._base_env

    @property
    def version(self) -> Union[int, str]:
        """Return the experiment version."""
        if self._version is None:
            # Force resolution.
            _ = self._resolved_env
        return self._version if self._version is not None else 0

    @rank_zero_only
    def log_hyperparams(self, params: Union[Dict[str, Any], Namespace]) -> None:
        """Log hyper-parameters as a formatted HTML table."""
        if isinstance(params, Namespace):
            params = vars(params)

        rows = "".join(
            "<tr><td><b>{k}</b></td><td>{v}</td></tr>".format(k=k, v=v)
            for k, v in sorted(params.items())
        )
        html = (
            "<h3>Hyperparameters</h3>"
            '<table border="1" cellpadding="4" cellspacing="0">'
            "<tr><th>Parameter</th><th>Value</th></tr>"
            "{rows}</table>"
        ).format(rows=rows)

        viz = self._get_viz()
        if self._hparams_win is not None:
            viz.text(html, win=self._hparams_win, env=self._resolved_env)
        else:
            self._hparams_win = viz.text(html, env=self._resolved_env)

    @rank_zero_only
    def log_metrics(
        self, metrics: Dict[str, float], step: Optional[int] = None
    ) -> None:
        """Log scalar metrics — each metric gets its own ``viz.line()`` window."""
        viz = self._get_viz()
        x_val = metrics.pop(self._global_step_key, step)

        for name, value in metrics.items():
            if not self._should_log(name):
                continue

            y = np.array([float(value)])
            x = np.array([float(x_val)]) if x_val is not None else None
            win = self._windows.get(name)

            if win is not None:
                viz.line(
                    Y=y,
                    X=x,
                    win=win,
                    env=self._resolved_env,
                    update="append",
                    opts=dict(title=name, xlabel="step", ylabel=name),
                )
            else:
                new_win = viz.line(
                    Y=y,
                    X=x,
                    env=self._resolved_env,
                    opts=dict(title=name, xlabel="step", ylabel=name),
                )
                self._windows[name] = new_win

    @rank_zero_only
    def finalize(self, status: str) -> None:
        """Log the final training status to the environment."""
        viz = self._get_viz()
        viz.text(
            "<h3>Training finished</h3><p>Status: <b>{}</b></p>".format(status),
            env=self._resolved_env,
        )

    @property
    @rank_zero_experiment
    def experiment(self) -> Visdom:
        """Return the underlying :class:`~visdom.Visdom` instance.

        Useful for advanced users who want to call ``viz.image()``,
        ``viz.text()``, etc. directly.
        """
        return self._get_viz()
