from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import torch


@dataclass
class AnomalyConfig:
    exploding_grad_threshold: float = 100.0
    dead_grad_threshold: float = 1e-8


def analyze_gradient(
    grad: torch.Tensor | None,
    config: AnomalyConfig | None = None,
) -> dict:
    if config is None:
        config = AnomalyConfig()

    if grad is None:
        return {
            "status": "no_grad",
            "finite": True,
            "norm": 0.0,
            "mean": 0.0,
            "std": 0.0,
            "max_abs": 0.0,
        }

    g = grad.detach()
    finite = bool(torch.isfinite(g).all().item())
    norm = float(g.norm(2).item()) if g.numel() else 0.0
    mean = float(g.mean().item()) if g.numel() else 0.0
    std = float(g.std(unbiased=False).item()) if g.numel() > 1 else 0.0
    max_abs = float(g.abs().max().item()) if g.numel() else 0.0

    if not finite:
        status = "nan_or_inf"
    elif norm >= config.exploding_grad_threshold:
        status = "exploding"
    elif norm <= config.dead_grad_threshold:
        status = "dead"
    else:
        status = "ok"

    return {
        "status": status,
        "finite": finite,
        "norm": norm,
        "mean": mean,
        "std": std,
        "max_abs": max_abs,
    }


def model_health_matrix(
    model: torch.nn.Module,
    max_layers: int | None = None,
) -> Tuple[List[str], np.ndarray, List[str]]:
    """
    Returns:
        names: parameter names used as columns
        matrix: shape [rows, columns]
        row_names: list of row labels
    """
    names: List[str] = []
    rows: List[List[float]] = []

    row_names = [
        "weight_norm",
        "weight_mean",
        "weight_std",
        "grad_norm",
        "grad_mean",
        "grad_std",
    ]

    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        if param.ndim == 0:
            continue
        if max_layers is not None and len(names) >= max_layers:
            break

        w = param.detach()
        g = param.grad.detach() if param.grad is not None else None

        weight_norm = float(w.norm(2).item()) if w.numel() else 0.0
        weight_mean = float(w.mean().item()) if w.numel() else 0.0
        weight_std = float(w.std(unbiased=False).item()) if w.numel() > 1 else 0.0

        if g is None:
            grad_norm = 0.0
            grad_mean = 0.0
            grad_std = 0.0
        else:
            grad_norm = float(g.norm(2).item()) if g.numel() else 0.0
            grad_mean = float(g.mean().item()) if g.numel() else 0.0
            grad_std = float(g.std(unbiased=False).item()) if g.numel() > 1 else 0.0

        names.append(name)
        rows.append(
            [
                weight_norm,
                weight_mean,
                weight_std,
                grad_norm,
                grad_mean,
                grad_std,
            ]
        )

    if not names:
        return [], np.empty((0, 0), dtype=np.float32), row_names

    matrix = np.asarray(rows, dtype=np.float32).T
    return names, matrix, row_names