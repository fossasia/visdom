#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import warnings

try:
    from tensorflow.keras.callbacks import Callback
except ImportError:
    try:
        from keras.callbacks import Callback
    except ImportError:
        raise ImportError(
            "tensorflow or keras is required for VisdomKerasLogger. "
            "Install with: pip install tensorflow (or pip install keras)"
        )


class VisdomKerasLogger(Callback):
    """Plots Keras train/val metrics to Visdom as epochs complete.

    Implements keras's Callback protocol. on_epoch_end() receives logs
    directly from Keras after every epoch, so there is no separate
    history dict to read. A metric named val_<name> is plotted as a
    "val" trace on the same window its train counterpart <name> plots
    as a "train" trace, matching how Keras already splits train/val by
    key prefix.

    Pass an instance via callbacks= to fit(). One instance can be reused
    across multiple fit() calls; a new run's epoch 0 replaces the
    previous run's curve on the same windows in place, rather than
    opening a duplicate set of windows for every fit() call.

    Passing log_every plots every metric at batch granularity too (one
    window per metric, titled "<name> (step)"), throttled to one send
    every log_every batches so large datasets don't flood the server.
    The step count is global across the whole fit() call, not reset
    per epoch. Off by default — on_train_batch_end otherwise fires on
    every batch for every user of this logger regardless of whether
    they want step-level detail, which is not something to default on.
    When enabled, the optimizer's current learning rate is read (not
    computed — it's whatever the optimizer already has) and plotted
    alongside the batch metrics as "lr".

    Each call to viz.line() is a synchronous network request, made on
    the training thread. Pick a log_every large enough that it doesn't
    stall training waiting on the server — 50+ is a reasonable default
    on GPU; log_every=1 sends a request every single batch.

    Not thread-safe: _step/_wins/_step_wins have no locking, so calling
    fit() on the same instance from multiple threads can race.

    Usage::

        from visdom.loggers import VisdomKerasLogger

        logger = VisdomKerasLogger(viz)
        model.fit(x_train, y_train, validation_data=(x_val, y_val),
                  epochs=10, callbacks=[logger])

        # with per-batch logging + LR tracking, one send every 50 batches
        logger = VisdomKerasLogger(viz, log_every=50)
        model.fit(x_train, y_train, epochs=10, callbacks=[logger])
    """

    def __init__(self, viz, env=None, log_every=None):
        super().__init__()
        self.viz = viz
        _viz_env = getattr(viz, "env", None)
        self.env = (
            env
            or (_viz_env if _viz_env and _viz_env != "main" else None)
            or "keras_{}".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        )
        if log_every is not None:
            log_every = int(log_every)
            if log_every < 1:
                raise ValueError("log_every must be >= 1, got {}".format(log_every))
        self.log_every = log_every
        self._wins = {}
        self._step_wins = {}
        self._step = 0

    def on_train_begin(self, logs=None):
        self._step = 0

    def on_epoch_end(self, epoch, logs=None):
        if not logs:
            return
        try:
            for key, value in logs.items():
                if key.startswith("val_"):
                    win_name = key[len("val_") :]
                    trace_name = "val"
                else:
                    win_name = key
                    trace_name = "train"
                if win_name not in self._wins:
                    self._wins[win_name] = self.viz.line(
                        X=[epoch],
                        Y=[value],
                        env=self.env,
                        name=trace_name,
                        opts={
                            "title": win_name,
                            "xlabel": "epoch",
                            "ylabel": win_name,
                            "showlegend": True,
                        },
                    )
                elif epoch == 0:
                    # New run reusing an old window, or a val_ trace
                    # appearing on a window its train_ counterpart just
                    # created this epoch — seed the trace, don't append.
                    self.viz.line(
                        X=[epoch],
                        Y=[value],
                        win=self._wins[win_name],
                        env=self.env,
                        name=trace_name,
                        update="replace",
                    )
                else:
                    self.viz.line(
                        X=[epoch],
                        Y=[value],
                        win=self._wins[win_name],
                        env=self.env,
                        name=trace_name,
                        update="append",
                    )
        except Exception as e:
            warnings.warn(
                "VisdomKerasLogger failed to log epoch {}: {}".format(epoch, e)
            )

    def _plot_step(self, win_name, value, replace):
        if win_name not in self._step_wins:
            self._step_wins[win_name] = self.viz.line(
                X=[self._step],
                Y=[value],
                env=self.env,
                opts={
                    "title": "{} (step)".format(win_name),
                    "xlabel": "step",
                    "ylabel": win_name,
                },
            )
        elif replace:
            self.viz.line(
                X=[self._step],
                Y=[value],
                win=self._step_wins[win_name],
                env=self.env,
                update="replace",
            )
        else:
            self.viz.line(
                X=[self._step],
                Y=[value],
                win=self._step_wins[win_name],
                env=self.env,
                update="append",
            )

    def _read_lr(self):
        optimizer = getattr(self.model, "optimizer", None)
        if optimizer is None:
            return None
        lr = getattr(optimizer, "learning_rate", None)
        if lr is None:
            return None
        if callable(lr):
            # LearningRateSchedule — evaluate at the optimizer's own
            # step counter, the same value it uses internally.
            lr = lr(getattr(optimizer, "iterations", self._step))
        if hasattr(lr, "numpy"):
            lr = lr.numpy()
        return float(lr)

    def on_train_batch_end(self, batch, logs=None):
        if self.log_every is None or not logs:
            return
        is_new_run = self._step == 0
        try:
            if is_new_run or self._step % self.log_every == 0:
                for key, value in logs.items():
                    self._plot_step(key, value, replace=is_new_run)
                lr = self._read_lr()
                if lr is not None:
                    self._plot_step("lr", lr, replace=is_new_run)
        except Exception as e:
            warnings.warn(
                "VisdomKerasLogger failed to log step {}: {}".format(self._step, e)
            )
        self._step += 1
