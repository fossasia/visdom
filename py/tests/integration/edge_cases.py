#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Inputs the server has to survive rather than serve.

Environment ids become file names, so ``escape_eid`` rewrites the characters
that would escape the storage directory, and names too long for a file system
fall back to a hash. Everything else here is the awkward end of the range:
missing envs and windows, twenty creations in a row, empty and enormous and
markup-bearing content, and the pages that render straight from state.
"""

import os
import unittest

import pytest

from testutils.http import VisdomHTTPTestCase

pytestmark = pytest.mark.integration


class TestEnvIdEscaping(VisdomHTTPTestCase):
    def _assert_escaped_to(self, eid, stored):
        self.create_text_window(eid=eid, content="escaped")
        envs = self.get_envs()
        self.assertIn(stored, envs)
        if stored != eid:
            self.assertNotIn(eid, envs)

    def test_forward_slash_becomes_underscore(self):
        self._assert_escaped_to("a/b", "a_b")

    def test_backslash_becomes_underscore(self):
        self._assert_escaped_to("a\\b", "a_b")

    def test_newline_becomes_hyphen(self):
        self._assert_escaped_to("a\nb", "a-b")

    def test_unicode_is_kept(self):
        self._assert_escaped_to("env_éàü", "env_éàü")

    def test_an_over_long_env_name_falls_back_to_a_hash_file(self):
        long_name = "x" * 300
        self.create_text_window(eid=long_name, content="long name")
        self.save([long_name])
        files = os.listdir(self.env_path)
        hashed = [f for f in files if f.startswith("hash_") and f.endswith(".json")]
        self.assertTrue(hashed, files)


class TestErrorRoutes(VisdomHTTPTestCase):
    def test_non_numeric_status_is_rejected(self):
        self.assertEqual(self.fetch("/error/test_error_msg").code, 400)

    def test_server_error_status_is_echoed(self):
        self.assertEqual(self.fetch("/error/500").code, 500)

    def test_not_found_status_is_echoed(self):
        self.assertEqual(self.fetch("/error/404").code, 404)

    def test_the_server_survives_a_requested_error(self):
        self.fetch("/error/500")
        self.assertEqual(self.fetch("/health").code, 200)


class TestMalformedRequests(VisdomHTTPTestCase):
    def test_reading_an_unknown_window_is_a_bad_request(self):
        resp = self.post_json("/win_data", {"eid": "main", "win": "nonexistent"})
        self.assertEqual(resp.code, 400)
        self.assertIn("window doesn't exist", resp.reason)

    def test_naming_a_trace_while_sending_several_is_a_bad_request(self):
        trace = {"type": "scatter", "x": [1, 2], "y": [3, 4], "name": "t1"}
        win = self.create_window([trace])

        resp = self.update(win, [trace, dict(trace, name="t2")], name="t1")

        self.assertEqual(resp.code, 400)
        self.assertIn("exactly one data entry", resp.reason)

    def test_a_named_trace_update_with_one_entry_is_accepted(self):
        trace = {"type": "scatter", "x": [1, 2], "y": [3, 4], "name": "t1"}
        win = self.create_window([trace])

        replacement = dict(trace, y=[9, 9])
        self.assertEqual(self.update(win, [replacement], name="t1").code, 200)
        self.assertEqual(self.get_win_data(win)["content"]["data"][0]["y"], [9, 9])

    def test_updating_a_window_in_an_unknown_env_does_not_crash(self):
        resp = self.update(
            "w1", [{"type": "text", "content": "fail"}], eid="nonexistent_env"
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body.decode(), "win does not exist")


class TestVolumeAndIsolation(VisdomHTTPTestCase):
    def test_twenty_windows_in_a_row_all_land(self):
        wins = [self.create_text_window(content="win_%d" % n) for n in range(20)]
        self.assertEqual(len(set(wins)), 20)

        panes = self.panes()
        self.assertEqual(len(panes), 20)
        self.assertEqual(sorted(pane["i"] for pane in panes.values()), list(range(20)))

    def test_windows_do_not_leak_between_envs(self):
        self.create_text_window(eid="env_a", content="a_only", win="wa")
        self.create_text_window(eid="env_b", content="b_only", win="wb")

        self.assertTrue(self.win_exists("wa", eid="env_a"))
        self.assertFalse(self.win_exists("wb", eid="env_a"))
        self.assertTrue(self.win_exists("wb", eid="env_b"))
        self.assertFalse(self.win_exists("wa", eid="env_b"))


class TestAwkwardContent(VisdomHTTPTestCase):
    def _assert_round_trips(self, content):
        win = self.create_text_window(content=content)
        self.assertEqual(self.get_win_data(win)["content"], content)

    def test_empty_content_round_trips(self):
        self._assert_round_trips("")

    def test_very_long_content_round_trips(self):
        self._assert_round_trips("x" * 100000)

    def test_quotes_and_markup_round_trip(self):
        self._assert_round_trips('He said "hello" & <script>alert(1)</script>')


class TestDeleteMissingEnv(VisdomHTTPTestCase):
    def test_deleting_an_unknown_env_is_a_no_op(self):
        self.assertEqual(
            self.post_json("/delete_env", {"eid": "never_existed"}).code, 200
        )

    def test_deleting_a_none_env_is_a_no_op(self):
        self.assertEqual(self.post_json("/delete_env", {"eid": None}).code, 200)


class TestRenderedPages(VisdomHTTPTestCase):
    def test_env_page_renders(self):
        self.assertEqual(self.fetch("/env/main").code, 200)

    def test_compare_page_renders(self):
        self.assertEqual(self.fetch("/compare/main+main").code, 200)


if __name__ == "__main__":
    unittest.main()
