from pytorch_lightning.loggers.logger import Logger
from pytorch_lightning.utilities.rank_zero import rank_zero_only
from pytorch_lightning.callbacks import Callback
import visdom


class VisdomLogger(Logger):
    def __init__(self, server="http://localhost", port=8097, env="main", **kwargs):
        super().__init__()
        self._vis = visdom.Visdom(server=server, port=port, env=env, **kwargs)
        self._env = env
        self._name = "VisdomLogger"
        self._version = "0.1"

        # Dictionary to keep track of window IDs so we can append to existing plots
        self.windows = {}

    @property
    def name(self):
        return self._name

    @property
    def version(self):
        return self._version

    @property
    def experiment(self):
        return self._vis

    @rank_zero_only
    def log_hyperparams(self, params):
        # We will implement this later to log model config
        pass

    @rank_zero_only
    def log_metrics(self, metrics, step):
        # This is the core function Lightning calls every logging step
        for metric_name, metric_value in metrics.items():

            # Skip non-numeric metrics for line plots
            if not isinstance(metric_value, (int, float)):
                continue

            # If the window doesn't exist, create it. Otherwise, append.
            if metric_name not in self.windows:
                self.windows[metric_name] = self._vis.line(
                    X=[step],
                    Y=[metric_value],
                    opts=dict(title=metric_name, xlabel="Step", ylabel=metric_name),
                )
            else:
                self._vis.line(
                    X=[step],
                    Y=[metric_value],
                    win=self.windows[metric_name],
                    update="append",
                )

    @rank_zero_only
    def watch(self, model, log_freq=100, norm_type=2.0):
        """
        Automatically hooks into the PyTorch model to compute and log gradient norms
        to Visdom at the specified frequency.

        Note:
            Gradient hooks are registered per-parameter, but logging is aggregated
            per backward pass so that `log_freq` refers to the number of backward
            steps rather than the number of per-parameter gradient computations.
        """
        self._log_freq = log_freq
        self._norm_type = norm_type
        self._step_count = 0
        self._num_tracked_params = 0

        for name, parameter in model.named_parameters():
            if parameter.requires_grad:
                self._num_tracked_params += 1
                parameter.register_hook(self._make_grad_hook(name))

    def _make_grad_hook(self, name):
        def hook(grad):
            # Count every per-parameter gradient, but interpret logging frequency
            # in terms of backward steps (i.e., once all tracked parameters have
            # received a gradient).
            self._step_count += 1

            # If for some reason no parameters are tracked, do nothing.
            if getattr(self, "_num_tracked_params", 0) == 0:
                return

            # One backward step corresponds to gradients computed for all tracked
            # parameters.
            if self._step_count % self._num_tracked_params != 0:
                return

            backward_step = self._step_count // self._num_tracked_params
            if backward_step % self._log_freq != 0:
                return

            norm = grad.norm(self._norm_type).item()
            metric_name = f"grad_norm/{name}"
            self.log_metrics({metric_name: norm}, step=backward_step)
        return hook


class VisdomGradNormCallback(Callback):
    """
    Lightning Callback that automatically calculates and logs the total
    gradient norm of the model before every optimizer step.
    """

    def __init__(self, norm_type=2.0):
        self.norm_type = float(norm_type)

    def on_before_optimizer_step(self, trainer, pl_module, optimizer):
        total_norm = 0.0
        parameters = [p for p in pl_module.parameters() if p.grad is not None]
        if not parameters:
            return

        for p in parameters:
            param_norm = p.grad.detach().norm(self.norm_type)
            total_norm += param_norm.item() ** self.norm_type
        total_norm = total_norm ** (1.0 / self.norm_type)

        if hasattr(trainer, "logger") and isinstance(trainer.logger, VisdomLogger):
            trainer.logger.log_metrics(
                {"total_grad_norm": total_norm}, step=trainer.global_step
            )
