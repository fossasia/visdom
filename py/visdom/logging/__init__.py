# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Visdom Logging Bridge — thin, pure logging utilities for PyTorch workflows.

Provides:
    VisdomLoggingHandler : context-manager / decorator for vanilla PyTorch loops
    VisdomLogger         : PyTorch Lightning ``Logger`` subclass (requires
                           ``pytorch_lightning`` to be installed)
"""

from visdom.logging.handler import VisdomLoggingHandler

__all__ = ["VisdomLoggingHandler"]

try:
    from visdom.logging.logger import VisdomLogger

    __all__.append("VisdomLogger")
except ImportError:
    # pytorch_lightning is not installed — VisdomLogger is unavailable,
    # but VisdomLoggingHandler still works for vanilla PyTorch users.
    pass
