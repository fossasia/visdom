#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
PyTorch Lightning integration for Visdom.

Two components are provided:

``VisdomLogger``
    A ``lightning.pytorch.loggers.Logger`` subclass.  Pass it to
    ``Trainer(logger=...)`` and every ``self.log()`` call inside a
    ``LightningModule`` is automatically forwarded to a Visdom line chart —
    one window per metric key.

``GradientNormCallback``
    A ``lightning.pytorch.Callback`` that attaches a parameter-level tensor
    hook to every trainable weight and, before each optimizer step, calls
    ``pl_module.log("grad_norm", ...)`` so that gradient norms appear in
    Visdom without any manual instrumentation.  Supports:

    * configurable Lp norm type
    * optional per-layer logging
    * optional hook-overhead profiling (wall-time in ms)

Requires
--------
    pip install lightning   # or  pip install pytorch-lightning

Usage
-----
::

    import lightning as L
    from visdom.lightning_logger import VisdomLogger, GradientNormCallback

    logger   = VisdomLogger(env="my_run", port=8097)
    callback = GradientNormCallback(log_every=1, per_layer=False)

    trainer = L.Trainer(
        max_epochs=10,
        logger=logger,
        callbacks=[callback],
    )
    trainer.fit(model, train_dl, val_dl)
"""

from __future__ import annotations

import html
import time
import warnings
from argparse import Namespace
from typing import Any, Dict, List, Optional, Union

import numpy as np

# ---------------------------------------------------------------------------
# Resolve Lightning import (supports 'lightning' 2.x and 'pytorch_lightning')
# ---------------------------------------------------------------------------
try:
    import lightning.pytorch as pl
    from lightning.pytorch.loggers import Logger as _LightningLogger
    from lightning.pytorch.utilities import rank_zero_only
    from lightning.pytorch import Callback
except ImportError:
    try:
        import pytorch_lightning as pl
        from pytorch_lightning.loggers import Logger as _LightningLogger
        from pytorch_lightning.utilities import rank_zero_only
        from pytorch_lightning import Callback
    except ImportError as exc:
        raise ImportError(
            "PyTorch Lightning is required for visdom.lightning_logger.\n"
            "Install with:  pip install lightning\n"
            "  or (older):  pip install pytorch-lightning"
        ) from exc

import visdom
from visdom.grad_norm import compute_grad_norm, compute_layer_grad_norms

# ---------------------------------------------------------------------------
# VisdomLogger
# ---------------------------------------------------------------------------


class VisdomLogger(_LightningLogger):
    """
    PyTorch Lightning logger that sends every scalar metric to Visdom.

    One Visdom window is created per distinct metric key.  All windows are
    placed in the same Visdom environment (``env``) so they appear together
    in the dashboard sidebar.

    Parameters
    ----------
    name : str
        Experiment name shown by the Trainer progress bar and used as the
        Visdom environment prefix.
    version : str or int or None
        Run identifier.  ``None`` generates a timestamp-based string so
        successive runs never overwrite each other in Visdom.
    port : int
        Port of the running Visdom server (default ``8097``).
    server : str
        Hostname of the Visdom server (default ``"localhost"``).
    env : str or None
        Override the Visdom environment name completely.  When ``None`` the
        env is derived as ``"{name}-v{version}"``.
    opts : dict or None
        Extra Visdom ``line()`` opts applied to *every* metric window
        (e.g. ``{"showlegend": True}``).
    fail_on_no_connection : bool
        Raise ``RuntimeError`` if the Visdom server is unreachable when the
        first metric is logged.  Default ``True``.

    Examples
    --------
    ::

        logger = VisdomLogger(name="mnist", port=8097)
        trainer = Trainer(max_epochs=5, logger=logger)
        trainer.fit(model, train_dl)
    """

    def __init__(
        self,
        name: str = "visdom_experiment",
        version: Optional[Union[int, str]] = None,
        port: int = 8097,
        server: str = "localhost",
        env: Optional[str] = None,
        opts: Optional[Dict[str, Any]] = None,
        fail_on_no_connection: bool = True,
    ) -> None:
        super().__init__()
        self._name = name
        self._version = (
            version if version is not None else time.strftime("%Y%m%d_%H%M%S")
        )
        self._port = port
        self._server = server
        self._env = env or f"{self._name}-v{self._version}"
        self._extra_opts: Dict[str, Any] = opts or {}
        self._fail_on_no_connection = fail_on_no_connection

        # Lazy Visdom connection (created on first log call)
        self._viz: Optional[visdom.Visdom] = None
        # Windows that have already been created (use append afterwards)
        self._created_windows: set = set()

    # ------------------------------------------------------------------
    # Required Logger properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Experiment name (displayed in Trainer output)."""
        return self._name

    @property
    def version(self) -> Union[int, str]:
        """
        Run identifier.

        Lightning uses this for checkpoint sub-directory naming and to
        distinguish runs when multiple loggers are active simultaneously.
        """
        return self._version

    @property
    def experiment(self) -> visdom.Visdom:
        """
        The underlying ``visdom.Visdom`` connection (lazy).

        Exposes the raw connection so power-users can make custom Visdom
        calls::

            trainer.logger.experiment.images(img_tensor, win="debug")
        """
        if self._viz is None:
            self._viz = visdom.Visdom(
                server=self._server,
                port=self._port,
                env=self._env,
            )
            if self._fail_on_no_connection and not self._viz.check_connection():
                raise RuntimeError(
                    f"Cannot reach Visdom at {self._server}:{self._port}. "
                    "Start the server with:  python -m visdom.server"
                )
        return self._viz

    # ------------------------------------------------------------------
    # Core logging methods (abstract in the Lightning Logger base class)
    # ------------------------------------------------------------------

    @rank_zero_only
    def log_metrics(
        self,
        metrics: Dict[str, float],
        step: Optional[int] = None,
    ) -> None:
        """
        Forward scalar metrics from Lightning to Visdom line charts.

        Called automatically after every step or epoch that contains a
        ``self.log()`` call inside a ``LightningModule``.  The
        ``@rank_zero_only`` decorator suppresses duplicate sends from
        non-primary processes during multi-GPU / DDP training.

        Parameters
        ----------
        metrics : dict
            ``{metric_name: scalar_value}`` mapping, e.g.
            ``{"train_loss": 0.42, "epoch": 3}``.
        step : int or None
            Global training step.  When ``None`` the epoch counter stored
            in *metrics* (key ``"epoch"``) is used as the X-axis value.
        """
        x_val = step if step is not None else int(metrics.get("epoch", 0))

        for key, value in metrics.items():
            if key == "epoch":
                continue
            try:
                scalar = float(value)
            except (TypeError, ValueError):
                continue

            win = f"{self._env}/{key}"
            already = win in self._created_windows

            # Train metrics → blue  |  val metrics → orange (easy to scan)
            color = (
                np.array([[31, 119, 180]])  # matplotlib blue
                if "val" not in key
                else np.array([[255, 127, 14]])  # matplotlib orange
            )

            opts = dict(
                title=key,
                xlabel="Step",
                ylabel=key,
                linecolor=color,
            )
            opts.update(self._extra_opts)

            try:
                self.experiment.line(
                    Y=np.array([scalar]),
                    X=np.array([x_val]),
                    win=win,
                    env=self._env,
                    update="append" if already else None,
                    opts=opts,
                )
                self._created_windows.add(win)
            except Exception as exc:  # pragma: no cover
                if self._fail_on_no_connection:
                    raise
                warnings.warn(f"[VisdomLogger] Failed to log '{key}': {exc}")

    @rank_zero_only
    def log_hyperparams(
        self,
        params: Union[Dict[str, Any], Namespace],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        Display hyperparameters in a Visdom text window.

        Called by Lightning once before training when
        ``LightningModule.save_hyperparameters()`` is used or when the
        Trainer detects a set of hyperparameters to record.
        """
        if isinstance(params, Namespace):
            params = vars(params)

        rows = "\n".join(
            f"<tr><td><b>{html.escape(str(k))}</b></td>"
            f"<td>{html.escape(str(v))}</td></tr>"
            for k, v in sorted(params.items())
        )
        html_text = f"<b>Hyperparameters</b><br><table>{rows}</table>"

        try:
            self.experiment.text(
                html_text,
                win=f"{self._env}/hparams",
                env=self._env,
                opts=dict(title="Hyperparameters"),
            )
        except Exception as exc:  # pragma: no cover
            warnings.warn(f"[VisdomLogger] Failed to log hyperparams: {exc}")

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    @rank_zero_only
    def finalize(self, status: str) -> None:
        """Print the dashboard URL when training ends."""
        url = f"http://{self._server}:{self._port}/env/{self._env}"
        print(f"\n[VisdomLogger] Training {status}. Dashboard: {url}\n")

    @rank_zero_only
    def save(self) -> None:
        """Persist the Visdom environment to the server's save directory."""
        if self._viz is not None:
            self._viz.save([self._env])


# ---------------------------------------------------------------------------
# GradientNormCallback
# ---------------------------------------------------------------------------


class GradientNormCallback(Callback):
    """
    Automatically log gradient norms to Visdom via PyTorch tensor hooks.

    Attaches a ``register_hook`` to every trainable parameter at the start
    of ``fit``.  Uses ``on_before_optimizer_step`` to aggregate and log the
    global (and optionally per-layer) norms once per ``log_every`` steps.

    Because the hooks run in the autograd engine, we only record *timestamps*
    inside the hook and do the actual Visdom logging outside — this keeps hook
    overhead minimal and measurable.

    Parameters
    ----------
    log_every : int
        Log gradient norms every *N* optimizer steps (default ``1``).
    norm_type : float
        Lp exponent used by ``compute_grad_norm`` (default ``2.0``).
    per_layer : bool
        If ``True``, also log ``"grad_norm/<param_name>"`` for each layer
        via ``pl_module.log()``.  Default ``False``.
        For large models with many named parameters this creates one
        Visdom window per parameter; use sparingly or set
        ``log_every`` to a larger value to reduce noise.
    profile_hooks : bool
        If ``True``, measure the wall-time each tensor hook takes and log
        the mean as ``"grad_hook_ms"`` at each step.  Default ``False``.

    Examples
    --------
    ::

        callback = GradientNormCallback(
            log_every=10,
            per_layer=True,
            profile_hooks=True,
        )
        trainer = Trainer(callbacks=[callback])
    """

    def __init__(
        self,
        log_every: int = 1,
        norm_type: float = 2.0,
        per_layer: bool = False,
        profile_hooks: bool = False,
    ) -> None:
        super().__init__()
        if log_every < 1:
            raise ValueError(f"log_every must be >= 1, got {log_every!r}")
        if norm_type <= 0:
            raise ValueError(f"norm_type must be positive, got {norm_type!r}")
        self.log_every = log_every
        self.norm_type = norm_type
        self.per_layer = per_layer
        self.profile_hooks = profile_hooks

        self._handles: List = []  # registered hook handles
        self._hook_times_ms: List[float] = []  # profiling accumulator

    # ------------------------------------------------------------------
    # Callback lifecycle
    # ------------------------------------------------------------------

    def setup(self, trainer, pl_module, stage: str) -> None:
        """Register tensor hooks on every trainable parameter."""
        if stage != "fit":
            return
        for _name, p in pl_module.named_parameters():
            if p.requires_grad:
                handle = p.register_hook(self._make_hook())
                self._handles.append(handle)

    def _make_hook(self):
        """Return a per-parameter grad hook that optionally profiles itself.

        When ``profile_hooks=False`` (the default) the returned hook is a
        true zero-cost pass-through: the autograd engine calls it but no
        Python work is done beyond returning the unmodified gradient.
        """
        profile = self.profile_hooks
        times = self._hook_times_ms

        def hook(grad):
            if profile:
                t0 = time.perf_counter()
                # Measure the cost of a norm call inside the hook so that
                # profile_hooks=True reports realistic per-hook overhead.
                # This op is only performed when profiling is explicitly
                # requested; plain usage is a true zero-overhead pass-through.
                _ = grad.detach().norm(2)
                times.append((time.perf_counter() - t0) * 1000.0)
            return grad  # pass-through — never modifies the gradient

        return hook

    def on_before_optimizer_step(self, trainer, pl_module, optimizer) -> None:
        """Compute and log gradient norms before weights are updated."""
        if trainer.global_step % self.log_every != 0:
            return

        if not hasattr(pl_module, "log"):
            raise TypeError(
                "GradientNormCallback requires a LightningModule with a "
                ".log() method."
            )

        total_norm = compute_grad_norm(pl_module.parameters(), self.norm_type)
        pl_module.log(
            "grad_norm",
            total_norm,
            on_step=True,
            on_epoch=False,
            prog_bar=False,
        )

        if self.per_layer:
            # Use pl_module directly — works for any LightningModule regardless
            # of whether the model is wrapped in a .model attribute or not.
            for name, norm_val in compute_layer_grad_norms(
                pl_module, self.norm_type
            ).items():
                pl_module.log(
                    f"grad_norm/{name.replace('.', '/')}",
                    norm_val,
                    on_step=True,
                    on_epoch=False,
                )

        if self.profile_hooks:
            if self._hook_times_ms:
                mean_ms = sum(self._hook_times_ms) / len(self._hook_times_ms)
                pl_module.log(
                    "grad_hook_ms",
                    mean_ms,
                    on_step=True,
                    on_epoch=False,
                )
            # Always clear to prevent unbounded memory growth between log steps
            self._hook_times_ms.clear()

    def _remove_hooks(self) -> None:
        """Detach all registered tensor hooks."""
        for handle in self._handles:
            handle.remove()
        self._handles.clear()

    def on_fit_end(self, trainer, pl_module) -> None:
        """Remove all registered hooks when training completes normally."""
        self._remove_hooks()

    def teardown(self, trainer, pl_module, stage: str) -> None:
        """Ensure hooks are removed even if training exits due to an error."""
        if stage == "fit":
            self._remove_hooks()
