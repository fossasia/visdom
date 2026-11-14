#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Requests a browser sends on behalf of another site's page are refused.

Browsers label where a request came from: ``Sec-Fetch-Site`` on current ones,
``Origin`` on older ones. The visdom UI only talks to its own origin, so a
state-changing request labelled as coming from elsewhere is refused with 403.
Callers that are not browsers -- the python client, curl -- send neither
header and must keep working, as must reads.
"""

import json

import pytest

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


class TestCrossSiteRequests(VisdomHTTPTestCase):
    def post_from(self, path, body, **headers):
        return self.fetch(path, method="POST", body=json.dumps(body), headers=headers)

    def setUp(self):
        super().setUp()
        self.create_text_window(eid="victim", content="results")

    def env_exists(self, eid):
        return eid in self.get_envs()

    def test_cross_site_delete_is_refused(self):
        resp = self.post_from(
            "/delete_env", {"eid": "victim"}, **{"Sec-Fetch-Site": "cross-site"}
        )
        self.assertEqual(resp.code, 403)
        self.assertTrue(self.env_exists("victim"))

    def test_same_site_page_on_another_port_is_refused(self):
        # localhost:9000 and localhost:8097 are the same site but not the same
        # origin, so a page on another local port must not get through either.
        text_pane = {
            "eid": "planted",
            "data": [{"type": "text", "content": "<b>from another page</b>"}],
            "layout": {},
            "opts": {},
        }
        resp = self.post_from("/events", text_pane, **{"Sec-Fetch-Site": "same-site"})
        self.assertEqual(resp.code, 403)
        self.assertFalse(self.env_exists("planted"))

    def test_foreign_origin_is_refused_without_fetch_metadata(self):
        resp = self.post_from(
            "/delete_env", {"eid": "victim"}, Origin="http://attacker.example"
        )
        self.assertEqual(resp.code, 403)
        self.assertTrue(self.env_exists("victim"))

    def test_null_origin_is_refused(self):
        resp = self.post_from("/delete_env", {"eid": "victim"}, Origin="null")
        self.assertEqual(resp.code, 403)

    def test_the_visdom_page_itself_is_allowed(self):
        resp = self.post_from(
            "/delete_env", {"eid": "victim"}, **{"Sec-Fetch-Site": "same-origin"}
        )
        self.assertEqual(resp.code, 200)
        self.assertFalse(self.env_exists("victim"))

    def test_own_origin_is_allowed_without_fetch_metadata(self):
        origin = "http://localhost:%d" % self.get_http_port()
        resp = self.post_from(
            "/delete_env",
            {"eid": "victim"},
            Origin=origin,
            Host="localhost:%d" % self.get_http_port(),
        )
        self.assertEqual(resp.code, 200)

    def test_origin_matching_the_proxy_forwarded_host_is_allowed(self):
        # Behind a reverse proxy Host may be rewritten to the upstream name,
        # while the browser's Origin carries the public one.
        resp = self.post_from(
            "/delete_env",
            {"eid": "victim"},
            Origin="https://visdom.example.org",
            **{"X-Forwarded-Host": "visdom.example.org"},
        )
        self.assertEqual(resp.code, 200)

    def test_clients_without_browser_headers_are_unaffected(self):
        # What the python client and curl send: no Origin, no Sec-Fetch-Site.
        self.assertEqual(self.post_json("/delete_env", {"eid": "victim"}).code, 200)

    def test_reads_are_not_checked(self):
        resp = self.fetch("/", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(resp.code, 200)
