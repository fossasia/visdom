#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for compiled template caching behavior in server settings."""

import asyncio

import pytest
import tornado.web

from visdom.server.app import Application, tornado_settings

pytestmark = pytest.mark.integration


def test_tornado_settings_does_not_disable_template_caching():
    """compiled_template_cache should not be explicitly forced to False."""
    assert "compiled_template_cache" not in tornado_settings


def test_template_caching_active_in_production():
    """In production mode (debug=False), Tornado enables template cache."""
    settings = dict(tornado_settings)
    settings["debug"] = False
    app = tornado.web.Application([], **settings)
    assert app.settings.get("compiled_template_cache", True) is True


def test_template_caching_disabled_in_debug():
    """In debug mode (debug=True), Tornado disables template cache."""
    settings = dict(tornado_settings)
    settings["debug"] = True
    settings["autoreload"] = False
    app = tornado.web.Application([], **settings)
    assert app.settings.get("compiled_template_cache", True) is False


def test_application_explicit_debug_flag(tmp_path):
    """Application accepts an explicit debug flag and sets template cache."""
    from tornado import autoreload

    app_prod = Application(env_path=str(tmp_path), debug=False)
    assert app_prod.settings.get("debug") is False
    assert app_prod.settings.get("compiled_template_cache", True) is True
    assert app_prod.shutdown_storage not in autoreload._reload_hooks

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app_dbg = None
    try:
        app_dbg = Application(env_path=str(tmp_path), debug=True)
        assert app_dbg.settings.get("debug") is True
        assert app_dbg.settings.get("compiled_template_cache", True) is False
        assert app_dbg.shutdown_storage in autoreload._reload_hooks
    finally:
        if app_dbg and app_dbg.shutdown_storage in autoreload._reload_hooks:
            autoreload._reload_hooks.remove(app_dbg.shutdown_storage)
        loop.close()
        asyncio.set_event_loop(None)


def test_autoreload_hook_saves_dirty_environments(tmp_path):
    """Autoreload hook persists unsaved environment state before reload."""
    from tornado import autoreload

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = None
    try:
        app = Application(env_path=str(tmp_path), debug=True)
        assert app.shutdown_storage in autoreload._reload_hooks

        # Stage dirty state in an environment
        env_name = "test_autoreload_env"
        app.server_state.state[env_name] = {
            "jsons": {"win1": {"data": "test_content"}},
            "reload": {},
        }
        app.server_state.dirty_envs[env_name] += 1

        # Simulate Tornado triggering reload hooks before execv
        for hook in list(autoreload._reload_hooks):
            if hook == app.shutdown_storage:
                hook()

        # Verify dirty environment was flushed to disk and dirty_envs cleared
        saved_file = tmp_path / f"{env_name}.json"
        assert saved_file.exists()
        assert env_name not in app.server_state.dirty_envs
    finally:
        if app and app.shutdown_storage in autoreload._reload_hooks:
            autoreload._reload_hooks.remove(app.shutdown_storage)
        loop.close()
        asyncio.set_event_loop(None)


def test_application_explicit_autoreload_false(tmp_path):
    """When autoreload=False, autoreload is disabled even with debug=True."""
    from tornado import autoreload

    app = Application(env_path=str(tmp_path), debug=True, autoreload=False)
    assert app.settings.get("debug") is True
    assert app.settings.get("autoreload") is False
    assert app.shutdown_storage not in autoreload._reload_hooks


