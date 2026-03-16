"""
Task 3: Custom Lightning-compatible Visdom logger.

After the exploration of Logger (task 2) we implement a basic custom lightning logger.
"""
from lightning.pytorch.loggers import Logger
from visdom import Visdom
from argparse import Namespace


# custom lightning logger:
class VisdomLogger(Logger):
    def __init__(self, env="main", port=8097):
        super().__init__()
        self._viz = Visdom(port=port, env=env)
        self._env = env

    # from the output of the Logger inspection I understand that Lightning requires every logger to have a name...
    @property
    def name(self):
        return "VisdomLogger"

    # ...and a version:
    @property
    def version(self):
        return "0.1"

    # function for the logging of the model settings (loss, accuracy and learning rate)
    def log_hyperparams(self, params, *args, **kwargs):
        if isinstance(params, Namespace):
            params = vars(params)
        text = "<br>".join(f"<b>{k}</b>: {v}" for k, v in params.items())
        self._viz.text(text, win="hyperparams", opts=dict(title="Hyperparameters"))

    # eveytime a metric get logged this runs and plot each one on visdom automatically
    # notice how the viz.line command of two cells ago it inside a for now, so it get repeated
    def log_metrics(self, metrics, step=None):
        for key, value in metrics.items():
            self._viz.line(
                Y=[float(value)], X=[step or 0],
                win=key, update='append',
                opts=dict(title=key, xlabel='step', ylabel=key),
            )
