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
* **downloaded** — plotly, d3, MathJax and friends, fetched by
  ``visdom/server/build.py`` and ignored by git. CI installs the package and
  runs pytest without ever downloading them, so they are absent there.
  Asserting them would make the job red for a reason that has nothing to do
  with the code under test, so each is skipped when it is not on disk and
  checked when it is.

Both lists mirror what the shipped HTML pages actually reference; when an asset
is dropped from ``index.html``/``login.html`` or from ``download_scripts()`` it
belongs out of here too.
"""

import os
import re

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
    os.path.join("css", "base.css"),
    os.path.join("css", "style.css"),
    os.path.join("css", "login.css"),
    os.path.join("css", "error.css"),
    os.path.join("css", "network.css"),
    os.path.join("css", "hparams.css"),
    os.path.join("css", "rc-tree-select-overrides.css"),
]

# Fetched by download_scripts() at first run; absent in a plain checkout.
DOWNLOADED_ASSETS = [
    "js/plotly-plotly.min.js",
    "js/d3.v3.min.js",
    "js/d3-selection-multi.v1.js",
    "js/saveSvgAsPng.js",
    "js/layout_bin_packer.js",
    "js/sjcl.js",
    "js/mathjax/3.2.2/es5/tex-mml-svg.js",
    "css/react-resizable-styles.css",
    "css/react-grid-layout-styles.css",
]

# The templates the server renders; every static_url() in them must resolve.
PAGES = ["index.html", "login.html", "error.html"]

# webpack emits well over a megabyte; anything near zero means a broken build
# that still produced a file.
MIN_BUNDLE_BYTES = 100_000


def _static(relpath):
    return os.path.join(get_visdom_path("static"), relpath)


@pytest.mark.parametrize("relpath", TRACKED_ASSETS)
def test_tracked_asset_exists(relpath):
    """Every committed static asset is present in the installed package."""
    assert os.path.exists(_static(relpath)), f"missing build artifact: {relpath}"


def _referenced_assets(page):
    """The static/ paths an HTML template asks the browser to load."""
    with open(_static(page), encoding="utf-8") as handle:
        markup = handle.read()
    refs = re.findall(r"""static_url\(\s*['"]([^'"]+)['"]""", markup)
    return [ref for ref in refs if not ref.startswith("..")]


@pytest.mark.parametrize("page", PAGES)
def test_referenced_assets_are_declared(page):
    """Nothing a page loads is missing from both asset lists."""
    declared = {
        os.path.join(*ref.split("/")) for ref in TRACKED_ASSETS + DOWNLOADED_ASSETS
    }
    for ref in _referenced_assets(page):
        assert (
            os.path.join(*ref.split("/")) in declared
        ), f"{page} loads {ref}, which is in neither asset list"


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
