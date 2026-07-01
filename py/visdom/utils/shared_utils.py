#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Utilities that could be potentially useful in various different
parts of the visdom stack. Not to be used for particularly specific
helper functions.
"""

import importlib
import json
import math
import uuid
import warnings
import os

import numpy as np

_seen_warnings = set()


def warn_once(msg, warningtype=None):
    """
    Raise a warning, but only once.
    :param str msg: Message to display
    :param Warning warningtype: Type of warning, e.g. DeprecationWarning
    """
    global _seen_warnings
    if msg not in _seen_warnings:
        _seen_warnings.add(msg)
        warnings.warn(msg, warningtype, stacklevel=2)


def get_rand_id():
    """Returns a random id string"""
    return str(uuid.uuid4())


def get_new_window_id():
    """Return a string to be used for a new window"""
    return f"window_{get_rand_id()}"


def ensure_dir_exists(path):
    """Make sure the dir exists so we can write a file."""
    os.makedirs(os.path.abspath(path), exist_ok=True)


def get_visdom_path(filename=None):
    """Get the path to an asset."""
    cwd = os.path.dirname(importlib.util.find_spec("visdom").origin)
    if filename is None:
        return cwd
    return os.path.join(cwd, filename)


def _sanitize_nans(obj):
    """Recursively replace NaN/Inf floats with None in nested structures."""
    if isinstance(obj, (float, np.floating)) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nans(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_nans(v) for v in obj]
    return obj


class NanSafeEncoder(json.JSONEncoder):
    """JSON encoder that converts NaN and Inf float values to None.

    Standard JSON does not support NaN/Inf. This encoder handles them
    automatically so callers don't need manual nan2none() preprocessing.
    """

    def encode(self, o):
        return super().encode(_sanitize_nans(o))

    def iterencode(self, o, _one_shot=False):
        return super().iterencode(_sanitize_nans(o), _one_shot=_one_shot)
