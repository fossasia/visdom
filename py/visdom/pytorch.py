import datetime


class VisdomLogger:
    """Context manager for logging scalar metrics to Visdom from a raw PyTorch
    training loop.

    Handles window creation, step tracking, and log_every throttling
    automatically. The user calls log(name, value) for every metric — no
    viz.line() arguments needed.

    Usage::

        from visdom.pytorch import VisdomLogger

        with VisdomLogger(viz, env="run_1") as tracker:
            for epoch in range(num_epochs):
                train_loss = run_train_epoch(model, loader)
                val_loss   = run_val_epoch(model, val_loader)

                tracker.log("Train Loss", train_loss)
                tracker.log("Val Loss",   val_loss)
                tracker.log("LR",         optimizer.param_groups[0]["lr"])
    """

    def __init__(self, viz, env=None, log_every=1):
        self.viz = viz
        self.env = env or "run_{}".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        self.log_every = log_every
        self._wins = {}
        self._step = {}
        self._counter = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

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
            throttling by design.
        """
        self._counter[name] = self._counter.get(name, 0) + 1
        if self._counter[name] % self.log_every != 0:
            return

        x_val = x if x is not None else self._step.get(name, 1)

        if name not in self._wins:
            win = self.viz.line(
                X=[x_val],
                Y=[value],
                env=self.env,
                opts={"title": name, "xlabel": xlabel, "ylabel": name},
            )
            self._wins[name] = win
        else:
            self.viz.line(
                X=[x_val],
                Y=[value],
                win=self._wins[name],
                env=self.env,
                update="append",
            )

        if x is None:
            self._step[name] = self._step.get(name, 1) + 1
