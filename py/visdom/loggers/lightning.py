#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import warnings

try:
    from lightning.pytorch.loggers import Logger
    from lightning.pytorch.loggers.logger import rank_zero_experiment
    from lightning.pytorch.utilities import rank_zero_only
except ImportError:
    try:
        from pytorch_lightning.loggers import Logger
        from pytorch_lightning.loggers.logger import rank_zero_experiment
        from pytorch_lightning.utilities import rank_zero_only
    except ImportError:
        raise ImportError(
            "lightning is required for VisdomLightningLogger. Install with: "
            "pip install lightning (or pip install pytorch-lightning)"
        )


class VisdomLightningLogger(Logger):
    """Plots PyTorch Lightning metrics to Visdom as training runs.

    Implements Lightning's Logger protocol. Lightning aggregates every
    ``self.log()`` / ``self.log_dict()`` call in a LightningModule and
    hands the result to ``log_metrics(metrics, step)``, so there is no
    separate history dict to read and no change to the training loop --
    the user passes one ``logger=`` argument to ``Trainer``.

    Each metric key gets its own window -- one key, one line chart, with
    no train/val name parsing. The bookkeeping ``epoch`` key Lightning
    mixes into the dict is not plotted. Values that do not convert to a
    float (non-numeric strings, multi-element tensors, ``None``) are
    skipped with a warning rather than raising.

    How often ``log_metrics`` fires is controlled entirely by Lightning
    (``Trainer(log_every_n_steps=...)`` for step metrics, once per epoch
    for epoch metrics) -- this logger adds no throttling of its own. Each
    call to ``viz.line()`` is a synchronous network request made on the
    thread Lightning calls from, so a very small ``log_every_n_steps``
    with many metrics can stall training while it waits on the server.

    Gradient norms come from Lightning, not this logger. Add to your
    LightningModule::

        from lightning.pytorch.utilities import grad_norm

        def on_before_optimizer_step(self, optimizer):
            self.log_dict(grad_norm(self, norm_type=2))

    Lightning computes the norms with its own utility and they arrive
    through ``log_metrics`` like any other metric.

    When training ends (success or failure) ``finalize`` saves the env on
    the server so the run can be reloaded later.

    Multi-GPU: ``log_metrics``, ``log_hyperparams`` and ``finalize`` run
    on rank zero only. Use one logger instance per ``Trainer`` run. Not
    thread-safe: ``_wins``/``_step`` have no locking.

    Usage::

        import lightning.pytorch as pl
        import visdom
        from visdom.loggers import VisdomLightningLogger

        viz = visdom.Visdom()
        logger = VisdomLightningLogger(viz, env="lightning_run")

        trainer = pl.Trainer(max_epochs=20, logger=logger,
                             log_every_n_steps=5)
        trainer.fit(model, train_loader, val_loader)
    """

    def __init__(self, viz, env=None):
        super().__init__()
        self.viz = viz
        _viz_env = getattr(viz, "env", None)
        self.env = (
            env
            or (_viz_env if _viz_env and _viz_env != "main" else None)
            or "lightning_{}".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        )
        self._wins = {}
        self._hparam_win = None
        self._step = 0

    @property
    def name(self):
        return "visdom"

    @property
    def version(self):
        return self.env

    @property
    @rank_zero_experiment
    def experiment(self):
        return self.viz

    @staticmethod
    def _to_float(value):
        """Coerce a logged value to a plottable float, or None if it is
        not numeric (a string, None, a multi-element array, ...)."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _plot(self, key, x, value):
        win = self._wins.get(key)
        if win:
            self.viz.line(
                X=[x],
                Y=[value],
                win=win,
                env=self.env,
                update="append",
            )
            return
        win = self.viz.line(
            X=[x],
            Y=[value],
            env=self.env,
            opts={"title": key, "xlabel": "step", "ylabel": key},
        )
        if win:
            self._wins[key] = win

    @rank_zero_only
    def log_metrics(self, metrics, step=None):
        if not metrics:
            return
        if step is None:
            x = self._step
            self._step += 1
        else:
            try:
                x = int(step)
            except (TypeError, ValueError):
                x = self._step
                self._step += 1
        for key, value in metrics.items():
            if key == "epoch":
                continue
            y = self._to_float(value)
            if y is None:
                warnings.warn(
                    "VisdomLightningLogger skipping non-numeric metric {}".format(key)
                )
                continue
            try:
                self._plot(key, x, y)
            except Exception as e:
                warnings.warn(
                    "VisdomLightningLogger failed to log {}: {}".format(key, e)
                )

    @rank_zero_only
    def log_hyperparams(self, params, *args, **kwargs):
        if params is None:
            return
        if not isinstance(params, dict):
            params = dict(params) if hasattr(params, "items") else vars(params)
        if not params:
            return
        content = [
            {"type": "text", "name": str(k), "value": str(v)} for k, v in params.items()
        ]
        try:
            if self._hparam_win:
                self.viz.properties(
                    content,
                    win=self._hparam_win,
                    env=self.env,
                    opts={"title": "hyperparameters"},
                )
            else:
                win = self.viz.properties(
                    content, env=self.env, opts={"title": "hyperparameters"}
                )
                if win:
                    self._hparam_win = win
        except Exception as e:
            warnings.warn(
                "VisdomLightningLogger failed to log hyperparameters: {}".format(e)
            )

    @rank_zero_only
    def finalize(self, status):
        try:
            self.viz.save([self.env])
        except Exception as e:
            warnings.warn("VisdomLightningLogger failed to save env: {}".format(e))
