#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Shared gradient-norm math utilities.

These functions are used by:
  - visdom.Visdom.log_gradient_norm (manual logging)
  - visdom.lightning_logger.GradientNormCallback (hook-based auto-logging)

Keeping the math in one place means any bug fix applies everywhere.
"""

import torch


def compute_grad_norm(params, norm_type=2.0):
    """
    Compute the global gradient norm across an iterable of parameters.

    The global norm is defined as::

        global_norm = (sum_i ||grad_i||^p)^(1/p)

    where *p* = ``norm_type`` and the sum runs over every parameter in
    ``params`` that has a non-None gradient.

    This is the same formula used by ``torch.nn.utils.clip_grad_norm_``.

    Parameters
    ----------
    params : iterable of torch.nn.Parameter
        Model parameters.  Only those whose ``.grad`` attribute is not
        ``None`` are included in the computation.
    norm_type : float, optional
        The exponent *p* in the Lp norm (default ``2.0`` for L2).
        Must be strictly positive.

    Returns
    -------
    float
        The global gradient norm, or ``0.0`` when no parameter has a
        gradient (e.g. immediately after ``optimizer.zero_grad()``).

    Raises
    ------
    ValueError
        If ``norm_type`` is not strictly positive.

    Examples
    --------
    >>> import torch.nn as nn
    >>> model = nn.Linear(4, 2)
    >>> loss = model(torch.randn(3, 4)).sum()
    >>> loss.backward()
    >>> norm = compute_grad_norm(model.parameters())
    >>> isinstance(norm, float)
    True
    """
    if norm_type <= 0:
        raise ValueError(f"norm_type must be strictly positive, got {norm_type!r}")

    per_param = [
        torch.linalg.vector_norm(p.grad.detach(), ord=norm_type)
        for p in params
        if p.grad is not None
    ]

    if not per_param:
        return 0.0

    # stack into a 1-D tensor then take the global norm
    return torch.linalg.vector_norm(torch.stack(per_param), ord=norm_type).item()


def compute_layer_grad_norms(model, norm_type=2.0):
    """
    Compute per-layer (per named-parameter) gradient norms for a model.

    Parameters
    ----------
    model : torch.nn.Module
        Model whose ``.named_parameters()`` are inspected.
    norm_type : float, optional
        Lp exponent (default ``2.0``).

    Returns
    -------
    dict[str, float]
        Mapping ``{parameter_name: norm_value}``.  Parameters with
        ``grad=None`` are excluded.  Returns an empty dict when no
        gradients are present.
    """
    if norm_type <= 0:
        raise ValueError(f"norm_type must be strictly positive, got {norm_type!r}")

    # named_parameters() yields (name, param) pairs with human-readable
    # keys (e.g. "features.0.weight"), making them directly usable as
    # Visdom window titles.  For very large models with many parameters
    # consider aggregating (e.g. mean per layer group) to avoid spawning
    # too many Visdom windows.
    return {
        name: torch.linalg.vector_norm(p.grad.detach(), ord=norm_type).item()
        for name, p in model.named_parameters()
        if p.grad is not None
    }
