#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Numpy arrays that record how the code under test traversed them.

Replacing a per-element Python loop with a whole-array numpy call is a change
in the *shape* of the work, not just its duration, and shape is the only half
of it that can be asserted on a shared CI runner. ``recording_array`` returns
an ordinary ndarray that counts the three traversals a Python loop needs and
nothing else:

* ``iter(a)`` -- ``for value in a`` and every comprehension over ``a``
* ``a[i]`` for an integer ``i`` -- the ``for i in range(len(a))`` idiom
* ``a.take(...)`` -- a column pulled out of a 2-D array

Operations numpy performs in C are invisible to the counters, which is the
point: a vectorised helper touches its argument once and leaves every counter
at zero. Only the array the test builds carries counters, so arrays derived
from it (views, results) never inflate them.
"""

import numpy as np


class RecordingArray(np.ndarray):
    """An ndarray carrying a ``counts`` dict of Python-level traversals."""

    def __new__(cls, values, dtype=None):
        obj = np.asarray(values, dtype=dtype).view(cls)
        obj.counts = {"iter": 0, "getitem": 0, "take": 0}
        return obj

    def __array_finalize__(self, obj):
        # Runs for views and for numpy's own results, both of which should
        # stay uncounted; ``__new__`` installs the dict afterwards.
        self.counts = None

    def _record(self, traversal):
        if self.counts is not None:
            self.counts[traversal] += 1

    def __iter__(self):
        self._record("iter")
        return super().__iter__()

    def __getitem__(self, key):
        if isinstance(key, (int, np.integer)):
            self._record("getitem")
        return super().__getitem__(key)

    def take(self, *args, **kwargs):
        self._record("take")
        return super().take(*args, **kwargs)


def recording_array(values, dtype=None):
    """Build a :class:`RecordingArray` from ``values``."""
    return RecordingArray(values, dtype=dtype)
