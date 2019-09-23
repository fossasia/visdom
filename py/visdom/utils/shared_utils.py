#!/usr/bin/env python3

# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Utilities that could be potentially useful in various different
parts of the visdom stack. Not to be used for particularly specific
helper functions.
"""

import inspect
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
    return f'win_{get_rand_id()}'


def ensure_dir_exists(path):
    """Make sure the parent dir exists for path so we can write a file."""
    try:
        os.makedirs(os.path.dirname(path))
    except OSError as e1:
        assert e1.errno == 17  # errno.EEXIST


def get_visdom_path():
    """Get the path to the visdom/py/visdom directory."""
    cwd = os.path.dirname(
        os.path.abspath(inspect.getfile(inspect.currentframe())))
    return os.path.dirname(cwd)


def get_visdom_path_to(filename):
    """Get the path to a file in the visdom/py/visdom directory."""
    return os.path.join(get_visdom_path(), filename)
