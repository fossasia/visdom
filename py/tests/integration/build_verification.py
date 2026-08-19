#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Checks that the frontend build output exists and is served.

Two kinds of asset live under ``py/visdom/static``:

* **tracked** — ``js/main.js`` and its source map, the three HTML pages, and the
  stylesheets under ``css/``. They are committed, so they are asserted outright.
* **downloaded** — plotly, d3 and the resizer stylesheet, fetched by ``build.py``
  and ignored by git (``.gitignore:17,19``). CI installs the package and runs
  pytest without ever building the frontend, so these are absent there.
  Asserting them would make the job red for a reason that has nothing to do
  with the code under test, so each is skipped when it is not on disk and
  checked when it is.
"""

import os

import pytest

from testutils import VisdomHTTPTestCase
from visdom.utils.shared_utils import get_visdom_path

pytestmark = pytest.mark.integration

# Committed by the repo; a missing one means the build output was clobbered.
TRACKED_ASSETS = [
    "index.html",
    "login.html",
    "error.html",
    os.path.join("js", "main.js"),
    os.path.join("js", "main.js.map"),
    os.path.join("css", "style.css"),
    os.path.join("css", "login.css"),
    os.path.join("css", "error.css"),
    os.path.join("css", "network.css"),
    os.path.join("css", "rc-tree-select-overrides.css"),
]

# Written by build.py at install time; absent in a plain checkout.
DOWNLOADED_ASSETS = [
    "js/plotly-plotly.min.js",
    "js/d3.v3.min.js",
    "css/react-resizable-styles.css",
]

# webpack emits well over a megabyte; anything near zero means a broken build
# that still produced a file.
MIN_BUNDLE_BYTES = 100_000


def _static(relpath):
    return os.path.join(get_visdom_path("static"), relpath)


@pytest.mark.parametrize("relpath", TRACKED_ASSETS)
def test_tracked_asset_exists(relpath):
    """Every committed static asset is present in the installed package."""
    assert os.path.exists(_static(relpath)), f"missing build artifact: {relpath}"


def test_main_bundle_is_not_a_stub():
    """main.js is a real bundle, not an empty or truncated file."""
    size = os.path.getsize(_static(os.path.join("js", "main.js")))
    assert size > MIN_BUNDLE_BYTES, f"bundle suspiciously small: {size} bytes"


class TestStaticServing(VisdomHTTPTestCase):
    """The Application serves the build output over HTTP."""

    def _assert_served(self, url):
        resp = self.fetch(url)
        self.assertEqual(resp.code, 200, f"{url} returned {resp.code}")
        return resp

    def test_index_page_returns_html(self):
        body = self._assert_served("/").body.decode()
        self.assertIn("<html", body.lower())

    def test_main_js_served_as_javascript(self):
        resp = self._assert_served("/static/js/main.js")
        content_type = resp.headers.get("Content-Type", "")
        self.assertIn(
            "javascript",
            content_type,
            f"unexpected Content-Type: {content_type}",
        )

    def test_main_js_served_whole(self):
        resp = self._assert_served("/static/js/main.js")
        self.assertGreater(len(resp.body), MIN_BUNDLE_BYTES)

    def test_style_css_served(self):
        self._assert_served("/static/css/style.css")

    def test_login_page_served(self):
        self._assert_served("/static/login.html")

    def test_downloaded_assets_served(self):
        """Assets build.py fetches are served when they have been downloaded."""
        served = 0
        for relpath in DOWNLOADED_ASSETS:
            if not os.path.exists(_static(relpath)):
                continue
            self._assert_served(f"/static/{relpath}")
            served += 1
        if served == 0:
            self.skipTest("frontend dependencies have not been downloaded")

    def test_unknown_static_path_is_404(self):
        resp = self.fetch("/static/js/does_not_exist.js")
        self.assertEqual(resp.code, 404)
