#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Task 4 — Profile hook overhead in PyTorch
==========================================
Measures the wall-clock and per-step overhead introduced by attaching
different kinds of PyTorch hooks to a model.  The results inform the
design of the auto-logging system: we only want to pay the cost of
hooks we actually need.

Hooks tested
------------
  1. No hooks (baseline)
  2. forward_pre_hook   — fires before each layer's forward pass
  3. forward_hook       — fires after each layer's forward pass
  4. full_backward_hook — fires after each layer during backprop
  5. gradient_norm hook — accumulates ‖grad‖₂ per parameter on backward

Run
---
    python example/hook_overhead_profile.py

Output: a plain-text table and (if a Visdom server is running) a bar chart
comparing overhead in microseconds per forward+backward pass.
"""

import time
import statistics
from typing import Any, Callable, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# Toy model — same LeNet-style CNN from pytorch_mnist_demo.py so numbers
# are directly comparable to an actual training scenario.
# ---------------------------------------------------------------------------


class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc1 = nn.Linear(64 * 7 * 7, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = x.view(x.size(0), -1)
        x = F.relu(self.fc1(x))
        return self.fc2(x)


# ---------------------------------------------------------------------------
# Hook factories
# ---------------------------------------------------------------------------


def _make_forward_pre_hook():
    """Fires *before* each module's forward; captures input shape."""
    captured: List[Tuple] = []

    def hook(module, inputs):
        captured.append(tuple(i.shape for i in inputs if isinstance(i, torch.Tensor)))

    return hook, captured


def _make_forward_hook():
    """Fires *after* each module's forward; captures output shape + mean."""
    captured: List[Tuple] = []

    def hook(module, inputs, output):
        if isinstance(output, torch.Tensor):
            captured.append((output.shape, output.mean().item()))

    return hook, captured


def _make_backward_hook():
    """Fires after each module during backprop; captures grad-output norm."""
    captured: List[float] = []

    def hook(module, grad_input, grad_output):
        for g in grad_output:
            if g is not None:
                captured.append(g.norm(2).item())

    return hook, captured


# Gradient-norm hook registered on the *model* (not per-layer).
# This is the pattern used by the Visdom GradientNormCallback below.
def _make_grad_norm_hook(model: nn.Module):
    """
    After every backward pass, compute the global L2 gradient norm and
    append it to a list.  This approximates "full backward hook" semantics
    by attaching a tensor autograd hook to a sentinel parameter on the model.
    """
    norms: List[float] = []

    def post_backward():
        total = sum(
            p.grad.norm(2).item() ** 2 for p in model.parameters() if p.grad is not None
        )
        norms.append(total**0.5)

    # PyTorch doesn't have a single "post-all-backward" hook on nn.Module;
    # we use a tensor autograd hook on a sentinel parameter instead.
    _sentinel = list(model.parameters())[-1]

    def tensor_hook(grad):
        post_backward()
        return grad

    handle = _sentinel.register_hook(tensor_hook)
    return handle, norms


# ---------------------------------------------------------------------------
# Benchmark harness
# ---------------------------------------------------------------------------

BATCH_SIZE = 64
NUM_WARMUP = 5  # steps to discard (JIT compilation / CUDA caching)
NUM_STEPS = 100  # steps to measure
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CRITERION = nn.CrossEntropyLoss()


def _one_step(model: nn.Module, x: torch.Tensor, y: torch.Tensor) -> float:
    """Forward + backward pass; return wall time in seconds."""
    t0 = time.perf_counter()
    loss = CRITERION(model(x), y)
    loss.backward()
    # zero grads — mirrors real training; avoids grad accumulation skewing norms
    for p in model.parameters():
        p.grad = None
    t1 = time.perf_counter()
    return t1 - t0


def _benchmark(setup_fn: Optional[Callable[[nn.Module], Any]] = None) -> Dict:
    """
    Run NUM_STEPS steps on a fresh model, optionally with hooks attached.

    Parameters
    ----------
    setup_fn : callable | None
        If provided, called with the new model before training starts so
        hooks can be registered.

    Returns
    -------
    dict with keys: mean_us, median_us, stdev_us, min_us, max_us
    """
    model = SimpleCNN().to(DEVICE)
    model.train()

    handles = []
    if setup_fn is not None:
        result = setup_fn(model)
        if result:  # some setups return (handle, data)
            handles = result if isinstance(result, list) else [result]

    x = torch.randn(BATCH_SIZE, 1, 28, 28, device=DEVICE)
    y = torch.randint(0, 10, (BATCH_SIZE,), device=DEVICE)

    # warm-up
    for _ in range(NUM_WARMUP):
        _one_step(model, x, y)

    # measure
    times_us = []
    for _ in range(NUM_STEPS):
        times_us.append(_one_step(model, x, y) * 1e6)  # → microseconds

    # detach hooks to avoid interference with later benchmarks
    for h in handles:
        if hasattr(h, "remove"):
            h.remove()

    return {
        "mean_us": statistics.mean(times_us),
        "median_us": statistics.median(times_us),
        "stdev_us": statistics.stdev(times_us),
        "min_us": min(times_us),
        "max_us": max(times_us),
    }


# ---------------------------------------------------------------------------
# Individual scenario setup functions
# ---------------------------------------------------------------------------


def _setup_forward_pre(model: nn.Module):
    handles = []
    for m in model.modules():
        hook, _ = _make_forward_pre_hook()
        handles.append(m.register_forward_pre_hook(hook))
    return handles


def _setup_forward(model: nn.Module):
    handles = []
    for m in model.modules():
        hook, _ = _make_forward_hook()
        handles.append(m.register_forward_hook(hook))
    return handles


def _setup_backward(model: nn.Module):
    handles = []
    for m in model.modules():
        hook, _ = _make_backward_hook()
        handles.append(m.register_full_backward_hook(hook))
    return handles


def _setup_grad_norm(model: nn.Module):
    handle, _ = _make_grad_norm_hook(model)
    return [handle]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SCENARIOS = [
    ("No hooks (baseline)", None),
    ("forward_pre_hook  (all layers)", _setup_forward_pre),
    ("forward_hook      (all layers)", _setup_forward),
    ("full_backward_hook(all layers)", _setup_backward),
    ("gradient_norm hook(1 param)  ", _setup_grad_norm),
]


def _print_table(results: Dict[str, Dict]) -> None:
    col_w = max(len(k) for k in results) + 2
    header = f"{'Scenario':<{col_w}}  {'mean µs':>10}  {'median µs':>10}  {'stdev µs':>9}  {'overhead %':>10}"
    print()
    print(header)
    print("-" * len(header))

    baseline = results[SCENARIOS[0][0]]["mean_us"]
    for name, stats in results.items():
        overhead = ((stats["mean_us"] - baseline) / baseline * 100) if baseline else 0.0
        print(
            f"{name:<{col_w}}  "
            f"{stats['mean_us']:>10.1f}  "
            f"{stats['median_us']:>10.1f}  "
            f"{stats['stdev_us']:>9.1f}  "
            f"{overhead:>+9.1f}%"
        )
    print()


def _plot_bar(results: Dict[str, Dict]) -> None:
    """Bar chart in Visdom (silently skipped when server is unavailable)."""
    try:
        import visdom
        import numpy as np

        viz = visdom.Visdom(port=8097)
        if not viz.check_connection(timeout_seconds=2):
            return

        labels = list(results.keys())
        values = np.array([v["mean_us"] for v in results.values()])

        viz.bar(
            X=values,
            opts=dict(
                title="Hook overhead — mean step time (µs)",
                rownames=labels,
                ylabel="µs / step",
                width=700,
                height=400,
            ),
        )
        print("  bar chart sent to Visdom at http://localhost:8097")
    except Exception:
        pass  # Visdom is optional for this profiler


if __name__ == "__main__":
    print(
        f"Profiling hook overhead  |  device={DEVICE}  "
        f"batch={BATCH_SIZE}  steps={NUM_STEPS}"
    )

    results = {}
    for scenario_name, setup_fn in SCENARIOS:
        print(f"  running: {scenario_name} ...", end="", flush=True)
        stats = _benchmark(setup_fn)
        results[scenario_name] = stats
        print(f"  mean={stats['mean_us']:.1f} µs")

    _print_table(results)
    _plot_bar(results)
