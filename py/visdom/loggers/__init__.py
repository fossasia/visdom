#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from visdom.pytorch import VisdomLogger
from visdom.loggers.sklearn import VisdomSklearnLogger

__all__ = ["VisdomLogger", "VisdomSklearnLogger"]

try:
    from visdom.loggers.xgboost import VisdomXGBLogger

    __all__.append("VisdomXGBLogger")
except ImportError:
    pass

try:
    from visdom.loggers.keras import VisdomKerasLogger

    __all__.append("VisdomKerasLogger")
except ImportError:
    pass
