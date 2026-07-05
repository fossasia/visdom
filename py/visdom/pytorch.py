import datetime


class VisdomLogger:
    """Context manager for logging scalar metrics to Visdom from a raw PyTorch
    training loop.

    Handles window creation, step tracking, and log_every throttling
    automatically. The user calls log(name, value) for every metric — no
    viz.line() arguments needed.

    Usage::

        from visdom.pytorch import VisdomLogger

        with VisdomLogger(viz, env="run_1", log_every=10) as tracker:
            for x, y in loader:
                loss = criterion(model(x), y)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                tracker.log("loss", loss.item())
                tracker.log("lr", optimizer.param_groups[0]["lr"])

            tracker.log("val/loss", val_loss)
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

    def log(self, name, value):
        """Log a scalar value under the given metric name.

        Skips the send if log_every throttle has not been reached.
        Creates a new Visdom window on the first call for each name,
        then appends on subsequent calls.
        """
        self._counter[name] = self._counter.get(name, 0) + 1
        if self._counter[name] % self.log_every != 0:
            return

        step = self._step.get(name, 0)

        if name not in self._wins:
            win = self.viz.line(
                X=[step],
                Y=[value],
                env=self.env,
                opts={"title": name, "xlabel": "step", "ylabel": name},
            )
            self._wins[name] = win
        else:
            self.viz.line(
                X=[step],
                Y=[value],
                win=self._wins[name],
                env=self.env,
                update="append",
            )

        self._step[name] = step + 1
