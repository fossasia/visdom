from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Tuple

import torch


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, torch.Tensor):
        return float(value.detach().float().mean().item())
    return float(value)


def gradient_norm(
    parameters: Iterable[torch.nn.Parameter],
    norm_type: float = 2.0,
) -> float:
    total = 0.0
    for p in parameters:
        if p.grad is None:
            continue
        param_norm = float(p.grad.detach().norm(norm_type).item())
        total += param_norm ** norm_type
    return total ** (1.0 / norm_type) if total > 0 else 0.0


def parameter_stats(
    named_parameters: Iterable[Tuple[str, torch.nn.Parameter]],
) -> Dict[str, Dict[str, float]]:
    stats: Dict[str, Dict[str, float]] = {}
    for name, p in named_parameters:
        if p.grad is None:
            continue

        g = p.grad.detach()
        numel = g.numel()

        stats[name] = {
            "grad_norm": float(g.norm(2).item()) if numel else 0.0,
            "grad_mean": float(g.mean().item()) if numel else 0.0,
            "grad_std": float(g.std(unbiased=False).item()) if numel > 1 else 0.0,
            "grad_max": float(g.abs().max().item()) if numel else 0.0,
        }
    return stats


def discover_basic_metrics(
    outputs: torch.Tensor | None,
    targets: torch.Tensor | None,
) -> Dict[str, float]:
    """
    Safe, limited auto-metric discovery:
    - classification logits + class targets -> accuracy + confidence
    - regression-like same-shape tensors -> mse + mae
    """
    metrics: Dict[str, float] = {}

    if outputs is None or targets is None:
        return metrics
    if not isinstance(outputs, torch.Tensor) or not isinstance(targets, torch.Tensor):
        return metrics
    if outputs.numel() == 0 or targets.numel() == 0:
        return metrics

    # Classification
    if outputs.ndim == 2 and targets.ndim == 1 and outputs.shape[0] == targets.shape[0]:
        preds = outputs.argmax(dim=1)
        metrics["accuracy"] = float((preds == targets).float().mean().item())
        probs = torch.softmax(outputs.detach(), dim=1)
        metrics["confidence"] = float(probs.max(dim=1).values.mean().item())
        return metrics

    # Regression
    if outputs.shape == targets.shape:
        diff = outputs.detach() - targets.detach()
        metrics["mse"] = float((diff ** 2).mean().item())
        metrics["mae"] = float(diff.abs().mean().item())
        return metrics

    return metrics