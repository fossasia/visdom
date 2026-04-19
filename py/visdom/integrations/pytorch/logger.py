from __future__ import annotations

from collections import defaultdict
from time import monotonic
from typing import Any, Callable, DefaultDict, Dict, Mapping, Optional, Tuple

import numpy as np
import torch

from visdom import Visdom

from .diagnostics import AnomalyConfig, analyze_gradient, model_health_matrix
from .hooks import register_parameter_hooks, remove_hooks
from .metrics import discover_basic_metrics, gradient_norm, parameter_stats, to_float


CustomMetricFn = Callable[[Any, Any], Any]


class VisdomDiagnosticsLogger:
    """
    PyTorch-native Visdom logger with:
    - scalar batching
    - gradient anomaly detection
    - warning namespace
    - limited auto-metric discovery
    - custom metric registry
    - model health summary dashboard
    - safe attach/detach lifecycle
    """

    def __init__(
        self,
        server: str = "http://localhost",
        port: int = 8097,
        env: str = "main",
        base_url: str = "/",
        flush_every: int = 20,
        flush_seconds: float = 2.0,
        exploding_grad_threshold: float = 100.0,
        dead_grad_threshold: float = 1e-8,
        enable_histograms: bool = False,
        enable_model_health: bool = False,
        max_histograms: int = 4,
        track_parameter_stats: bool = False,
        show_extra_model_stats: bool = False,
        diagnostics_interval: int = 50,
        visdom_client: Optional[Any] = None,
        **visdom_kwargs: Any,
    ) -> None:
        self.vis = visdom_client or Visdom(
            server=server,
            port=port,
            env=env,
            base_url=base_url,
            **visdom_kwargs,
        )

        self.env = env
        self.flush_every = max(int(flush_every), 1)
        self.flush_seconds = float(flush_seconds)

        self.anomaly_config = AnomalyConfig(
            exploding_grad_threshold=exploding_grad_threshold,
            dead_grad_threshold=dead_grad_threshold,
        )

        self.enable_histograms = enable_histograms
        self.enable_model_health = enable_model_health
        self.max_histograms = max_histograms
        self.track_parameter_stats = track_parameter_stats
        self.show_extra_model_stats = show_extra_model_stats
        self.diagnostics_interval = max(int(diagnostics_interval), 1)

        self._model = None
        self._optimizer = None
        self._hooks = []
        self._step = 0

        self._buffers: DefaultDict[str, list[Tuple[int, float]]] = defaultdict(list)
        self._windows: Dict[str, str] = {}
        self._custom_metrics: Dict[str, Tuple[str, CustomMetricFn]] = {}

        self._pending_points = 0
        self._last_flush = monotonic()
        self._last_diagnostics_step = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def attach(
        self,
        model: torch.nn.Module,
        optimizer: Any = None,
        with_parameter_hooks: bool = False,
    ) -> "VisdomDiagnosticsLogger":
        self._model = model
        if optimizer is not None:
            self._optimizer = optimizer

        if with_parameter_hooks:
            self._hooks = register_parameter_hooks(model, self._on_grad)

        return self

    def detach(self) -> None:
        if self._hooks:
            remove_hooks(self._hooks)
            self._hooks = []

    def close(self) -> None:
        self.flush(force=True)
        self.detach()

    def step(self, step: Optional[int] = None) -> int:
        if step is None:
            self._step += 1
        else:
            self._step = int(step)
        return self._step

    def register_metric(
        self,
        name: str,
        fn: CustomMetricFn,
        group: str = "custom",
    ) -> None:
        self._custom_metrics[name] = (group, fn)

    def _series_key(self, group: str, name: str) -> str:
        group = group.strip()
        name = name.strip()
        return f"{group}/{name}" if group else name

    def _queue_scalar(self, series: str, value: float, step: int) -> None:
        self._buffers[series].append((int(step), float(value)))
        self._pending_points += 1
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        elapsed = monotonic() - self._last_flush
        if self._pending_points >= self.flush_every or elapsed >= self.flush_seconds:
            self.flush()

    def log_scalar(
        self,
        name: str,
        value: Any,
        step: Optional[int] = None,
        group: str = "",
    ) -> None:
        if step is None:
            step = self._step
        series = self._series_key(group, name)
        self._queue_scalar(series, to_float(value), int(step))

    def log_warning(self, name: str, value: Any = 1.0, step: Optional[int] = None) -> None:
        self.log_scalar(name=name, value=value, step=step, group="warning")

    def log_metrics(
        self,
        metrics: Mapping[str, Any],
        step: Optional[int] = None,
        group: str = "",
    ) -> None:
        if step is None:
            step = self._step

        for key, value in metrics.items():
            if value is None:
                continue
            if isinstance(value, Mapping):
                self.log_metrics(value, step=step, group=self._series_key(group, key))
            else:
                self.log_scalar(key, value, step=step, group=group)

    def log_lr(self, step: Optional[int] = None) -> None:
        if self._optimizer is None:
            return
        if step is None:
            step = self._step

        for idx, group in enumerate(self._optimizer.param_groups):
            lr = group.get("lr")
            if lr is None:
                continue
            self.log_scalar(f"lr_group_{idx}", lr, step=step, group="optim")

    def _log_model_summary(self, step: Optional[int] = None) -> None:
        """
        Lightweight, aggregated model diagnostics.
        This keeps the useful gradient stats visible while leaving the rest
        of the heavier diagnostics optional.
        """
        if self._model is None:
            return
        if step is None:
            step = self._step

        total_params = 0
        params_with_grad = 0
        weight_norms = []
        grad_norms = []
        any_non_finite = False

        for p in self._model.parameters():
            total_params += 1

            w = p.detach()
            if w.numel() > 0:
                weight_norms.append(float(w.float().norm(2).item()))
                any_non_finite = any_non_finite or (not bool(torch.isfinite(w).all().item()))

            if p.grad is not None:
                g = p.grad.detach()
                params_with_grad += 1
                if g.numel() > 0:
                    grad_norms.append(float(g.float().norm(2).item()))
                    any_non_finite = any_non_finite or (not bool(torch.isfinite(g).all().item()))

        if total_params == 0:
            return

        if self.show_extra_model_stats:
            self.log_scalar("param_count", total_params, step=step, group="model")
            self.log_scalar("params_with_grad", params_with_grad, step=step, group="model")
            self.log_scalar(
                "grad_coverage",
                params_with_grad / float(total_params),
                step=step,
                group="model",
            )

            if weight_norms:
                self.log_scalar("weight_norm_mean", float(np.mean(weight_norms)), step=step, group="model")
                self.log_scalar("weight_norm_max", float(np.max(weight_norms)), step=step, group="model")

            if grad_norms:
                self.log_scalar("grad_norm_total", gradient_norm(self._model.parameters()), step=step, group="model")

            if any_non_finite:
                self.log_warning("non_finite_tensor", 1.0, step=step)

        if grad_norms:
            self.log_scalar("grad_norm_mean", float(np.mean(grad_norms)), step=step, group="model")
            self.log_scalar("grad_norm_max", float(np.max(grad_norms)), step=step, group="model")

    def _on_grad(self, param_name: str, grad: torch.Tensor) -> None:
        step = self._step
        info = analyze_gradient(grad, self.anomaly_config)

        # Keep only aggregated warnings here to avoid request spam.
        if info["status"] == "nan_or_inf":
            self.log_warning("nan_grad", 1.0, step=step)
        elif info["status"] == "exploding":
            self.log_warning("exploding_grad", info["norm"], step=step)
        elif info["status"] == "dead":
            self.log_warning("dead_layer", 1.0, step=step)

    def auto_log(
        self,
        outputs: torch.Tensor | None = None,
        targets: torch.Tensor | None = None,
        loss: Any = None,
        step: Optional[int] = None,
        group: str = "auto",
    ) -> None:
        if step is None:
            step = self._step

        payload: Dict[str, Any] = {}

        if loss is not None:
            payload["loss"] = loss

        payload.update(discover_basic_metrics(outputs, targets))

        for name, (metric_group, fn) in self._custom_metrics.items():
            try:
                payload[name] = fn(outputs, targets)
                if metric_group and metric_group != group:
                    self.log_scalar(name, payload[name], step=step, group=metric_group)
                    payload.pop(name, None)
            except Exception:
                self.log_warning(f"metric_error/{name}", 1.0, step=step)

        if payload:
            self.log_metrics(payload, step=step, group=group)

        # Extra safe diagnostics so the dashboard shows more than just 2 values.
        if self._model is not None and self.track_parameter_stats:
            self._log_model_summary(step=step)

    def log_model_health(self, step: Optional[int] = None, max_layers: int = 24) -> None:
        if not self.enable_model_health:
            return
        if self._model is None:
            return
        if step is None:
            step = self._step

        names, matrix, row_names = model_health_matrix(self._model, max_layers=max_layers)
        if len(names) == 0:
            return

        heatmap_key = "dashboard/model_health"
        opts = {
            "title": "dashboard/model_health",
            "rownames": row_names,
            "columnnames": names,
        }

        win = self._windows.get(heatmap_key)
        if win is None:
            win = self.vis.heatmap(X=matrix, win=None, env=self.env, opts=opts)
            self._windows[heatmap_key] = win
        else:
            self.vis.heatmap(X=matrix, win=win, env=self.env, update="replace", opts=opts)

        if self.enable_histograms:
            self.log_weight_histograms(step=step, max_histograms=self.max_histograms)

    def log_weight_histograms(self, step: Optional[int] = None, max_histograms: int = 4) -> None:
        if self._model is None or not self.enable_histograms:
            return

        count = 0
        for name, param in self._model.named_parameters():
            if not param.requires_grad or param.ndim == 0:
                continue
            if count >= max_histograms:
                break

            data = param.detach().cpu().float().flatten().numpy()
            hist_key = f"weights/{name}/hist"
            opts = {"title": hist_key}

            win = self._windows.get(hist_key)
            if win is None:
                win = self.vis.histogram(X=data, win=None, env=self.env, opts=opts)
                self._windows[hist_key] = win
            else:
                self.vis.histogram(X=data, win=win, env=self.env, opts=opts)

            count += 1

    def summary(self) -> Dict[str, Dict[str, float]]:
        if self._model is None:
            return {}
        return parameter_stats(self._model.named_parameters())

    def flush(self, force: bool = False) -> None:
        if not self._buffers:
            self._pending_points = 0
            self._last_flush = monotonic()
            return

        for series, points in list(self._buffers.items()):
            if not points:
                continue

            opts = {"title": series, "xlabel": "step", "ylabel": "value"}
            win = self._windows.get(series)

            if win is None:
                xs = np.asarray([p[0] for p in points], dtype=np.float32)
                ys = np.asarray([p[1] for p in points], dtype=np.float32)
                win = self.vis.line(Y=ys, X=xs, win=None, env=self.env, opts=opts)
                self._windows[series] = win
            else:
                for x, y in points:
                    self.vis.line(
                        Y=np.asarray([y], dtype=np.float32),
                        X=np.asarray([x], dtype=np.float32),
                        win=win,
                        env=self.env,
                        opts=opts,
                        update="append",
                    )

            self._buffers[series].clear()

        self._pending_points = 0
        self._last_flush = monotonic()

    def log_batch(
        self,
        *,
        loss: Any = None,
        accuracy: Any = None,
        metrics: Optional[Mapping[str, Any]] = None,
        outputs: torch.Tensor | None = None,
        targets: torch.Tensor | None = None,
        step: Optional[int] = None,
        group: str = "train",
    ) -> None:
        if step is None:
            step = self._step

        payload: Dict[str, Any] = {}
        if loss is not None:
            payload["loss"] = loss
        if accuracy is not None:
            payload["accuracy"] = accuracy
        if metrics:
            payload.update(metrics)

        self.log_metrics(payload, step=step, group=group)

        if outputs is not None and targets is not None:
            self.log_metrics(discover_basic_metrics(outputs, targets), step=step, group=group)

        if self._model is not None and self.track_parameter_stats:
            self._log_model_summary(step=step)

    def end_step(self, step: Optional[int] = None) -> None:
        if step is not None:
            self._step = int(step)

        self.log_lr(step=self._step)
        self._log_model_summary(step=self._step)

        # Keep the heavier visualizations periodic so the app stays responsive.
        if self.enable_model_health and (
            self._step - self._last_diagnostics_step
        ) >= self.diagnostics_interval:
            self.log_model_health(step=self._step)
            self._last_diagnostics_step = self._step

        self.flush(force=True)


VisdomLogger = VisdomDiagnosticsLogger