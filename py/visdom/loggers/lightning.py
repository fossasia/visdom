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
    from lightning.pytorch.utilities import rank_zero_only
except ImportError:
    try:
        from pytorch_lightning.loggers import Logger
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
    mixes into the dict is not plotted.

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

    Multi-GPU: ``log_metrics`` and ``log_hyperparams`` run on rank zero
    only. Use one logger instance per ``Trainer`` run. Not thread-safe:
    ``_wins``/``_step`` have no locking.

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
    def experiment(self):
        return self.viz

    def _plot(self, key, x, value):
        if key not in self._wins:
            self._wins[key] = self.viz.line(
                X=[x],
                Y=[value],
                env=self.env,
                opts={"title": key, "xlabel": "step", "ylabel": key},
            )
        else:
            self.viz.line(
                X=[x],
                Y=[value],
                win=self._wins[key],
                env=self.env,
                update="append",
            )

    @rank_zero_only
    def log_metrics(self, metrics, step=None):
        if not metrics:
            return
        if step is None:
            x = self._step
            self._step += 1
        else:
            x = int(step)
        for key, value in metrics.items():
            if key == "epoch":
                continue
            try:
                self._plot(key, x, float(value))
            except Exception as e:
                warnings.warn(
                    "VisdomLightningLogger failed to log {}: {}".format(key, e)
                )

    @rank_zero_only
    def log_hyperparams(self, params, *args, **kwargs):
        if params is None:
            return
        if not isinstance(params, dict):
            params = vars(params)
        if not params:
            return
        content = [
            {"type": "text", "name": str(k), "value": str(v)} for k, v in params.items()
        ]
        try:
            if self._hparam_win is None:
                self._hparam_win = self.viz.properties(
                    content, env=self.env, opts={"title": "hyperparameters"}
                )
            else:
                self.viz.properties(
                    content,
                    win=self._hparam_win,
                    env=self.env,
                    opts={"title": "hyperparameters"},
                )
        except Exception as e:
            warnings.warn(
                "VisdomLightningLogger failed to log hyperparameters: {}".format(e)
            )
