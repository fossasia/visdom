#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Shared helpers for the visdom test suite.

Importable as ``testutils`` because ``py/tests`` is on ``pythonpath`` (see
``pyproject.toml``). Note that ``py/tests`` deliberately has no ``__init__.py``:
``setup.py`` runs ``find_packages(where="py")``, and a package there would be
shipped to users as a top-level ``tests`` distribution.
"""

from testutils.arrays import RecordingArray, recording_array
from testutils.fakes import FakeHandler, FakeSocket, SpyStore
from testutils.http import VisdomHTTPTestCase
from testutils.payloads import content_args, env_payload, plot_data, window_args
from testutils.sockets import (
    commands,
    last,
    open_source,
    open_sub,
    sent,
    socket_double,
)

__all__ = [
    "FakeHandler",
    "FakeSocket",
    "RecordingArray",
    "SpyStore",
    "VisdomHTTPTestCase",
    "commands",
    "content_args",
    "env_payload",
    "last",
    "open_source",
    "open_sub",
    "plot_data",
    "recording_array",
    "sent",
    "socket_double",
    "window_args",
]
