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

    Usage::

        from visdom.loggers import VisdomKerasLogger

        logger = VisdomKerasLogger(viz)
        model.fit(x_train, y_train, validation_data=(x_val, y_val),
                  epochs=10, callbacks=[logger])
    """

    def __init__(self, viz, env=None):
        super().__init__()
        self.viz = viz
        _viz_env = getattr(viz, "env", None)
        self.env = (
            env
            or (_viz_env if _viz_env and _viz_env != "main" else None)
            or "keras_{}".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        )
        self._wins = {}

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
