#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import json
import os
from unittest import mock

import pytest

from visdom.server import internal

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration

KEYS = {
    "VISDOM_INTERNAL_READ_KEYS": "read-key",
    "VISDOM_METRICS_TOKENS": "scrape-token",
}


class TestActivityNeedsASignature(VisdomHTTPTestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, KEYS)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_an_unsigned_request_is_refused(self):
        for path in ("/_activity", "/_metrics"):
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path).code, 401)

    def test_a_wrong_key_is_refused(self):
        headers = internal.signed_headers("guess", "GET", "/_activity")

        self.assertEqual(self.fetch("/_activity", headers=headers).code, 401)

    def test_a_signed_request_gets_the_activity(self):
        headers = internal.signed_headers("read-key", "GET", "/_activity")
        response = self.fetch("/_activity", headers=headers)

        self.assertEqual(response.code, 200)
        self.assertIn("workspaces", json.loads(response.body))

    def test_a_scraper_can_use_its_token(self):
        response = self.fetch(
            "/_metrics", headers={"Authorization": "Bearer scrape-token"}
        )

        self.assertEqual(response.code, 200)

    def test_with_no_key_set_everything_is_refused(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            headers = internal.signed_headers("", "GET", "/_activity")

            self.assertEqual(self.fetch("/_activity", headers=headers).code, 401)
