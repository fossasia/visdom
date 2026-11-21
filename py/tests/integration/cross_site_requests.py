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
from tornado.httpclient import HTTPClientError, HTTPRequest
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

from testutils.http import VisdomHTTPTestCase
from visdom.server import handlers

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
            **{
                "X-Forwarded-Host": "visdom.example.org",
                "X-Forwarded-Proto": "https",
            },
        )
        self.assertEqual(resp.code, 200)

    def test_an_http_page_is_refused_by_an_https_server(self):
        # http://host and https://host are different origins. An http page is
        # the one a network attacker can tamper with, so it must not reach a
        # server the browser talks to over https.
        resp = self.post_from(
            "/delete_env",
            {"eid": "victim"},
            Origin="http://visdom.example.org",
            **{
                "X-Forwarded-Host": "visdom.example.org",
                "X-Forwarded-Proto": "https",
            },
        )
        self.assertEqual(resp.code, 403)
        self.assertTrue(self.env_exists("victim"))

    def test_without_forwarded_proto_only_the_arrival_scheme_is_accepted(self):
        # A proxy that ends TLS without X-Forwarded-Proto leaves no way to tell
        # an https page from an http one, so only the scheme the request came
        # in on is accepted, and the operator is told what to set.
        handlers.base_handlers._warned_missing_forwarded_proto = False
        here = "localhost:%d" % self.get_http_port()
        with self.assertLogs(level="WARNING") as logs:
            resp = self.post_from(
                "/delete_env", {"eid": "victim"}, Origin="https://" + here, Host=here
            )
        self.assertEqual(resp.code, 403)
        self.assertTrue(self.env_exists("victim"))
        self.assertIn("X-Forwarded-Proto", "\n".join(logs.output))

    def test_https_behind_a_proxy_that_sets_forwarded_proto_is_allowed(self):
        here = "localhost:%d" % self.get_http_port()
        resp = self.post_from(
            "/delete_env",
            {"eid": "victim"},
            Origin="https://" + here,
            Host=here,
            **{"X-Forwarded-Proto": "https"},
        )
        self.assertEqual(resp.code, 200)

    def test_clients_without_browser_headers_are_unaffected(self):
        # What the python client and curl send: no Origin, no Sec-Fetch-Site.
        self.assertEqual(self.post_json("/delete_env", {"eid": "victim"}).code, 200)

    def test_reads_are_not_checked(self):
        resp = self.fetch("/", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(resp.code, 200)

    def test_origin_must_be_exactly_scheme_and_host(self):
        # A browser sends Origin as scheme://host only; a path, query, missing
        # host or credentials means it is not a real Origin, so it is refused.
        here = "localhost:%d" % self.get_http_port()
        for origin in (
            "http://%s/path" % here,
            "http://%s/?q=1" % here,
            "http://user@%s" % here,
            "http://",
        ):
            resp = self.post_from(
                "/delete_env", {"eid": "victim"}, Origin=origin, Host=here
            )
            self.assertEqual(resp.code, 403, origin)
        self.assertTrue(self.env_exists("victim"))

    def test_cross_site_polling_handshake_is_refused(self):
        # GET /socket_wrap registers a subscriber, so it counts as a write.
        subs_before = len(self._app.server_state.subs)
        resp = self.fetch("/socket_wrap", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(resp.code, 403)
        self.assertEqual(len(self._app.server_state.subs), subs_before)

    def test_own_polling_handshake_is_allowed(self):
        resp = self.fetch("/socket_wrap", headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(resp.code, 200)
        self.assertTrue(json.loads(resp.body)["success"])

    # WebSockets are covered by tornado itself: WebSocketHandler.check_origin
    # refuses a handshake whose Origin is not this server's own host.

    async def open_socket(self, path, origin):
        here = "127.0.0.1:%d" % self.get_http_port()
        request = HTTPRequest("ws://%s%s" % (here, path), headers={"Origin": origin})
        return await websocket_connect(request)

    @gen_test
    async def test_cross_site_websockets_are_refused(self):
        for path in ("/socket", "/vis_socket"):
            with self.assertRaises(HTTPClientError) as refused:
                await self.open_socket(path, "http://attacker.example")
            self.assertEqual(refused.exception.code, 403, path)

    @gen_test
    async def test_own_websockets_are_allowed(self):
        here = "http://127.0.0.1:%d" % self.get_http_port()
        for path in ("/socket", "/vis_socket"):
            connection = await self.open_socket(path, here)
            connection.close()
