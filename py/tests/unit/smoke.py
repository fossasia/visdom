#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Smoke tests to verify the pytest suite is discovered and the package imports.

These require no running visdom server, so they run under ``pytest -m "not server"``.
"""


def test_smoke():
    assert True


def test_import_visdom():
    import visdom

    assert hasattr(visdom, "Visdom")
