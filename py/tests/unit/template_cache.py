#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for compiled template caching behavior in server settings."""

import tornado.web
import pytest

from visdom.server.app import tornado_settings

pytestmark = pytest.mark.unit


def test_tornado_settings_does_not_disable_template_caching():
    """compiled_template_cache should not be explicitly forced to False."""
    assert "compiled_template_cache" not in tornado_settings


def test_template_caching_active_in_production():
    """In production mode (debug=False), Tornado enables template caching by default."""
    app = tornado.web.Application([], **tornado_settings)
    assert app.settings.get("compiled_template_cache", True) is True


def test_template_caching_disabled_in_debug():
    """In debug mode (debug=True), Tornado automatically disables template caching."""
    settings = dict(tornado_settings)
    settings["debug"] = True
    settings["autoreload"] = False
    app = tornado.web.Application([], **settings)
    assert app.settings.get("compiled_template_cache", True) is False
