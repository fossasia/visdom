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

import json
import logging
import os
import unittest

import pytest

from testutils.fakes import FakeSocket
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


class TestErrorPageDetails(VisdomHTTPTestCase):
    """What a 500 tells the client on an ordinary server.

    The error page renders the exception, its traceback and the request the
    handler was serving whenever the app is built with error details on. That
    used to be unconditional, so ``error.html``'s own "what happened" branch
    for a production server was unreachable.
    """

    def test_the_status_is_still_reported(self):
        body = self.fetch("/error/500").body.decode()

        self.assertIn("500", body)
        self.assertIn("Internal Server Error", body)

    def test_the_production_message_is_shown_instead(self):
        self.assertIn("What happened", self.fetch("/error/500").body.decode())

    def test_the_traceback_is_not_rendered(self):
        self.assertNotIn("Traceback", self.fetch("/error/500").body.decode())

    def test_the_source_paths_are_not_rendered(self):
        self.assertNotIn("web_handlers.py", self.fetch("/error/500").body.decode())

    def test_the_request_is_not_rendered(self):
        body = self.fetch("/error/500").body.decode()

        self.assertNotIn("Remote IP", body)
        self.assertNotIn("127.0.0.1", body)


class TestErrorPageUnderDebugLogging(VisdomHTTPTestCase):
    """``-logging_level DEBUG`` is the operator asking for the detail back."""

    def get_app(self):
        root = logging.getLogger()
        previous = root.level
        root.setLevel(logging.DEBUG)
        try:
            return super().get_app()
        finally:
            root.setLevel(previous)

    def test_the_traceback_is_rendered(self):
        self.assertIn("Traceback", self.fetch("/error/500").body.decode())

    def test_the_request_is_rendered(self):
        body = self.fetch("/error/500").body.decode()

        self.assertIn("Remote IP", body)
        self.assertIn("127.0.0.1", body)


class TestRenderedPages(VisdomHTTPTestCase):
    def test_env_page_renders(self):
        self.assertEqual(self.fetch("/env/main").code, 200)

    def test_compare_page_renders(self):
        self.assertEqual(self.fetch("/compare/main+main").code, 200)

    def test_compare_page_escapes_environment_ids(self):
        """Compare page sanitizes environment IDs containing surrounding whitespace."""
        self.assertEqual(self.fetch("/compare/%20main%20+main").code, 200)


class TestCompareEndpoint(VisdomHTTPTestCase):
    """Integration tests for POST ``/compare/<eids>`` payload validation."""

    def test_missing_sid_returns_400(self):
        """A compare request without the required 'sid' returns HTTP 400."""
        resp = self.post_json("/compare/main+main", {"show_all": False})
        self.assertEqual(resp.code, 400)
        self.assertIn("missing required field: 'sid'", resp.reason)

    def test_empty_string_or_whitespace_sid_returns_400(self):
        """A compare request with empty or whitespace-only 'sid' returns HTTP 400."""
        for invalid_sid in ("", "   "):
            resp = self.post_json("/compare/main+main", {"sid": invalid_sid})
            self.assertEqual(resp.code, 400)
            self.assertIn("invalid required field: 'sid'", resp.reason)
            self.assertNotIn("missing", resp.reason)

    def test_non_string_sid_returns_400(self):
        """A compare request with non-string 'sid' (number, list, boolean) returns HTTP 400."""
        for invalid_sid in (123, [], True):
            resp = self.post_json("/compare/main+main", {"sid": invalid_sid})
            self.assertEqual(resp.code, 400)
            self.assertIn("invalid required field: 'sid'", resp.reason)
            self.assertNotIn("missing", resp.reason)

    def test_null_sid_uninitialized_socket_returns_200(self):
        """A compare request with null 'sid' (pre-socket client handshake) safely returns HTTP 200."""
        resp = self.post_json("/compare/main+main", {"sid": None, "show_all": False})
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body, b"")

    def test_malformed_json_body_returns_400(self):
        """A compare request with invalid JSON returns HTTP 400."""
        resp = self.fetch(
            "/compare/main+main",
            method="POST",
            body="not-valid-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)
        self.assertIn("request body must be valid JSON", resp.reason)

    def test_non_object_json_body_returns_400(self):
        """A compare request where body is a list or non-object returns HTTP 400."""
        resp = self.fetch(
            "/compare/main+main",
            method="POST",
            body="[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)
        self.assertIn("request body must be an object", resp.reason)

    def test_valid_sid_unknown_subscriber_returns_200(self):
        """A compare request with a valid string 'sid' unknown in self.subs returns HTTP 200."""
        resp = self.post_json(
            "/compare/main+main", {"sid": "valid-session-id", "show_all": False}
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body, b"")

    def test_compare_endpoint_escapes_environment_ids(self):
        """A compare request normalizes environment IDs through escape_eid."""
        subscriber = FakeSocket(sid="valid-session-id")
        self._app.subs[subscriber.sid] = subscriber
        resp = self.post_json(
            "/compare/%20main%20+main",
            {"sid": "valid-session-id", "show_all": False},
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body, b"")
        self.assertEqual(subscriber.eid, ["main", "main"])
        self.assertEqual(subscriber.commands(), ["reload", "window", "layout"])


class TestDeleteEnvEndpoint(VisdomHTTPTestCase):
    """Integration tests for POST ``/delete_env`` payload validation."""

    def test_malformed_json_body_returns_400(self):
        """A delete_env request with invalid JSON returns HTTP 400."""
        resp = self.fetch(
            "/delete_env",
            method="POST",
            body="not-valid-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)
        self.assertIn("request body must be valid JSON", resp.reason)

    def test_json_constants_in_body_returns_400(self):
        """A delete_env request with non-standard JSON constants returns HTTP 400."""
        for constant_body in (
            '{"eid": NaN}',
            '{"eid": Infinity}',
            '{"eid": -Infinity}',
        ):
            resp = self.fetch(
                "/delete_env",
                method="POST",
                body=constant_body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 400)
            self.assertIn("request body must be valid JSON", resp.reason)

    def test_non_object_json_body_returns_400(self):
        """A delete_env request where body is not a JSON object returns HTTP 400."""
        resp = self.fetch(
            "/delete_env",
            method="POST",
            body="[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)
        self.assertIn("request body must be an object", resp.reason)

    def test_numeric_eid_is_coerced(self):
        """A delete_env request with numeric 'eid' is safely coerced to string."""
        self.create_text_window(eid="123", content="numeric")
        self.assertIn("123", self.get_envs())
        resp = self.post_json("/delete_env", {"eid": 123})
        self.assertEqual(resp.code, 200)
        self.assertNotIn("123", self.get_envs())

    def test_boolean_eid_returns_400(self):
        """A delete_env request with boolean 'eid' returns HTTP 400."""
        resp = self.post_json("/delete_env", {"eid": True})
        self.assertEqual(resp.code, 400)
        self.assertIn("'eid' must be a string or number", resp.reason)

    def test_structured_eid_returns_400(self):
        """A delete_env request with structured 'eid' returns HTTP 400."""
        resp = self.post_json("/delete_env", {"eid": [1, 2]})
        self.assertEqual(resp.code, 400)
        self.assertIn("'eid' must be a string or number", resp.reason)

    def test_empty_string_or_whitespace_eid_is_noop(self):
        """A delete_env request with empty or whitespace-only 'eid' is a safe no-op returning 200."""
        for empty_eid in ("", "   "):
            resp = self.post_json("/delete_env", {"eid": empty_eid})
            self.assertEqual(resp.code, 200)

    def test_valid_eid_deletes_env(self):
        """A valid delete_env request deletes the environment."""
        self.create_text_window(eid="to_delete", content="hello")
        self.assertIn("to_delete", self.get_envs())
        resp = self.post_json("/delete_env", {"eid": "to_delete"})
        self.assertEqual(resp.code, 200)
        self.assertNotIn("to_delete", self.get_envs())


class TestEnvStateEndpoint(VisdomHTTPTestCase):
    """Integration tests for POST ``/env_state`` payload validation."""

    def test_malformed_json_body_returns_400(self):
        """An env_state request with invalid JSON returns HTTP 400."""
        resp = self.fetch(
            "/env_state",
            method="POST",
            body="not-valid-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)
        self.assertIn("request body must be valid JSON", resp.reason)

    def test_json_constants_in_body_returns_400(self):
        """An env_state request with non-standard JSON constants returns HTTP 400."""
        for constant_body in (
            '{"eid": NaN}',
            '{"eid": Infinity}',
            '{"eid": -Infinity}',
        ):
            resp = self.fetch(
                "/env_state",
                method="POST",
                body=constant_body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 400)
            self.assertIn("request body must be valid JSON", resp.reason)

    def test_non_object_json_body_returns_400(self):
        """An env_state request where body is not a JSON object returns HTTP 400."""
        resp = self.fetch(
            "/env_state",
            method="POST",
            body="[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)
        self.assertIn("request body must be an object", resp.reason)

    def test_numeric_eid_is_coerced_before_lookup(self):
        """An env_state request with numeric 'eid' is coerced to string before lookup."""
        resp = self.post_json("/env_state", {"eid": 123})
        self.assertEqual(resp.code, 404)
        self.assertIn("123", json.loads(resp.body)["error"])

    def test_boolean_eid_returns_400(self):
        """An env_state request with boolean 'eid' returns HTTP 400."""
        resp = self.post_json("/env_state", {"eid": True})
        self.assertEqual(resp.code, 400)
        self.assertIn("'eid' must be a string or number", resp.reason)

    def test_structured_eid_returns_400(self):
        """An env_state request with structured 'eid' returns HTTP 400."""
        resp = self.post_json("/env_state", {"eid": [1, 2]})
        self.assertEqual(resp.code, 400)
        self.assertIn("'eid' must be a string or number", resp.reason)

    def test_empty_body_returns_all_envs(self):
        """An env_state request with an empty object returns all environment IDs."""
        resp = self.post_json("/env_state", {})
        self.assertEqual(resp.code, 200)
        self.assertEqual(
            resp.headers.get("Content-Type"), "application/json; charset=UTF-8"
        )
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        envs = json.loads(resp.body.decode())
        self.assertIn("main", envs)

    def test_known_eid_success_uses_write_json_headers(self):
        """A known env_state request returns panes with write_json headers."""
        self.create_text_window(eid="main", content="hello")
        resp = self.post_json("/env_state", {"eid": "main"})
        self.assertEqual(resp.code, 200)
        self.assertEqual(
            resp.headers.get("Content-Type"), "application/json; charset=UTF-8"
        )
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        panes = json.loads(resp.body.decode())
        self.assertIsInstance(panes, dict)

    def test_all_envs_success_escapes_html_in_eid(self):
        """All-envs list escapes HTML in environment IDs via write_json."""
        xss_eid = "<img src=x onerror=alert(1)>"
        self.create_text_window(eid=xss_eid, content="test")
        resp = self.post_json("/env_state", {})
        self.assertEqual(resp.code, 200)
        self.assertEqual(
            resp.headers.get("Content-Type"), "application/json; charset=UTF-8"
        )
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn(b"\\u003cimg src=x onerror=alert(1)\\u003e", resp.body)
        self.assertNotIn(b"<", resp.body)
        self.assertNotIn(b">", resp.body)
        envs = json.loads(resp.body.decode())
        self.assertIn(xss_eid, envs)

    def test_unknown_eid_escapes_html_and_sets_json_headers(self):
        """Unknown eid errors use write_json to prevent reflected XSS."""
        resp = self.post_json("/env_state", {"eid": "<img src=x onerror=alert(1)>"})
        self.assertEqual(resp.code, 404)
        self.assertEqual(
            resp.headers.get("Content-Type"), "application/json; charset=UTF-8"
        )
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn(b"\\u003cimg src=x onerror=alert(1)\\u003e", resp.body)
        self.assertNotIn(b"<", resp.body)
        self.assertNotIn(b">", resp.body)
        parsed = json.loads(resp.body)
        self.assertEqual(
            parsed["error"], "env '<img src=x onerror=alert(1)>' not found"
        )


class TestWinExistsEndpoint(VisdomHTTPTestCase):
    """Integration tests for POST ``/win_exists`` payload validation."""

    def test_malformed_json_body_returns_400(self):
        """A win_exists request with invalid JSON returns HTTP 400."""
        resp = self.fetch(
            "/win_exists",
            method="POST",
            body="not-valid-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)
        self.assertIn("request body must be valid JSON", resp.reason)

    def test_non_object_json_body_returns_400(self):
        """A win_exists request where body is not a JSON object returns HTTP 400."""
        resp = self.fetch(
            "/win_exists",
            method="POST",
            body="[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)
        self.assertIn("request body must be an object", resp.reason)

    def test_missing_win_field_returns_400(self):
        """A win_exists request missing 'win' returns HTTP 400."""
        resp = self.post_json("/win_exists", {"eid": "main"})
        self.assertEqual(resp.code, 400)
        self.assertIn("missing required field: win", resp.reason)

    def test_boolean_eid_returns_400(self):
        """A win_exists request with boolean 'eid' returns HTTP 400."""
        resp = self.post_json("/win_exists", {"win": "w1", "eid": True})
        self.assertEqual(resp.code, 400)
        self.assertIn("'eid' must be a string or number", resp.reason)

    def test_structured_eid_returns_400(self):
        """A win_exists request with structured 'eid' returns HTTP 400."""
        resp = self.post_json("/win_exists", {"win": "w1", "eid": [1, 2]})
        self.assertEqual(resp.code, 400)
        self.assertIn("'eid' must be a string or number", resp.reason)


if __name__ == "__main__":
    unittest.main()
