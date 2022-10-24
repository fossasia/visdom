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
import uuid
import warnings
import os

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
    try:
        os.makedirs(os.path.abspath(path))
    except OSError as e1:
        assert e1.errno == 17  # errno.EEXIST


def get_visdom_path(filename=None):
    """Get the path to an asset."""
    cwd = os.path.dirname(importlib.util.find_spec("visdom").origin)
    if filename is None:
        return cwd
    return os.path.join(cwd, filename)
