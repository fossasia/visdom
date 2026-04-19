from __future__ import annotations

from typing import Callable, List

import torch

GradientCallback = Callable[[str, torch.Tensor], None]


def register_parameter_hooks(
    model: torch.nn.Module,
    callback: GradientCallback,
) -> List[torch.utils.hooks.RemovableHandle]:
    handles: List[torch.utils.hooks.RemovableHandle] = []

    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue

        def _hook(grad, param_name=name):
            callback(param_name, grad)

        handles.append(param.register_hook(_hook))

    return handles


def remove_hooks(handles: List[torch.utils.hooks.RemovableHandle]) -> None:
    for handle in handles:
        handle.remove()