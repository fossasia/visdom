#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Unit tests for server utility functions.
No server needed — these test pure functions directly.
"""

import unittest

from visdom.utils.server_utils import (
    escape_eid,
    extract_eid,
    hash_password,
    stringify,
    recursive_order,
)


class TestEscapeEid(unittest.TestCase):
    """Tests for escape_eid() — sanitizes environment IDs."""

    def test_forward_slash_replaced(self):
        self.assertEqual(escape_eid("a/b"), "a_b")

    def test_backslash_replaced(self):
        self.assertEqual(escape_eid("a\\b"), "a_b")

    def test_newline_replaced(self):
        self.assertEqual(escape_eid("a\nb"), "a-b")

    def test_carriage_return_replaced(self):
        self.assertEqual(escape_eid("a\rb"), "a-b")

    def test_multiple_special_chars(self):
        self.assertEqual(escape_eid("a/b\\c\nd\re"), "a_b_c-d-e")

    def test_normal_string_unchanged(self):
        self.assertEqual(escape_eid("my_environment"), "my_environment")

    def test_unicode_preserved(self):
        self.assertEqual(escape_eid("env_éàü"), "env_éàü")

    def test_empty_string(self):
        self.assertEqual(escape_eid(""), "")

    def test_leading_whitespace_stripped(self):
        self.assertEqual(escape_eid("  main"), "main")

    def test_trailing_whitespace_stripped(self):
        self.assertEqual(escape_eid("main  "), "main")

    def test_surrounding_whitespace_stripped(self):
        self.assertEqual(escape_eid("  main  "), "main")

    def test_whitespace_only_differing_ids_collapse_to_same_value(self):
        """'main' and 'main ' must normalise identically.

        JSONStore strips whitespace before deriving an on-disk filename, so
        if escape_eid did not also strip, these two eids would stay distinct
        in the in-memory state dict while silently colliding on disk.
        """
        self.assertEqual(escape_eid("main"), escape_eid("main "))
        self.assertEqual(escape_eid("main"), escape_eid(" main"))

    def test_internal_whitespace_preserved(self):
        """Only leading/trailing whitespace is stripped, not internal."""
        self.assertEqual(escape_eid("my env"), "my env")


class TestExtractEid(unittest.TestCase):
    """Tests for extract_eid() — extracts and escapes eid from args dict."""

    def test_default_is_main(self):
        self.assertEqual(extract_eid({}), "main")

    def test_none_value_returns_main(self):
        self.assertEqual(extract_eid({"eid": None}), "main")

    def test_with_value(self):
        self.assertEqual(extract_eid({"eid": "test"}), "test")

    def test_escapes_value(self):
        self.assertEqual(extract_eid({"eid": "a/b"}), "a_b")

    def test_whitespace_stripped(self):
        self.assertEqual(extract_eid({"eid": "main "}), "main")


class TestHashPassword(unittest.TestCase):
    """Tests for hash_password() — PBKDF2-HMAC-SHA256 with salt."""

    def test_same_password_same_salt_matches(self):
        h1 = hash_password("secret")
        salt = h1.split("$")[0]
        h2 = hash_password("secret", salt=salt)
        self.assertEqual(h1, h2)

    def test_same_password_different_salt_differs(self):
        h1 = hash_password("secret")
        h2 = hash_password("secret")
        self.assertNotEqual(h1, h2)

    def test_different_passwords_same_salt_differs(self):
        h1 = hash_password("password1")
        salt = h1.split("$")[0]
        h2 = hash_password("password2", salt=salt)
        self.assertNotEqual(h1, h2)

    def test_output_format(self):
        h = hash_password("test")
        parts = h.split("$")
        self.assertEqual(len(parts), 2)
        salt_hex, dk_hex = parts
        self.assertEqual(len(salt_hex), 64)
        self.assertEqual(len(dk_hex), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in salt_hex))
        self.assertTrue(all(c in "0123456789abcdef" for c in dk_hex))

    def test_full_login_flow(self):
        import hashlib as hl

        raw_password = "admin123"
        client_hash = hl.sha256(raw_password.encode("utf-8")).hexdigest()
        stored = hash_password(client_hash)
        salt = stored.split("$")[0]
        login_hash = hash_password(client_hash, salt=salt)
        self.assertEqual(stored, login_hash)


class TestStringify(unittest.TestCase):
    """Tests for stringify() — deterministic JSON serialization."""

    def test_orders_keys(self):
        result = stringify({"b": 1, "a": 2})
        self.assertLess(result.index('"a"'), result.index('"b"'))

    def test_converts_integer_floats(self):
        result = stringify({"x": 1.0})
        self.assertIn(":1", result)
        self.assertNotIn("1.0", result)

    def test_preserves_non_integer_floats(self):
        result = stringify({"x": 1.5})
        self.assertIn("1.5", result)

    def test_nested_key_ordering(self):
        result = stringify({"z": {"b": 1, "a": 2}, "a": 3})
        # "a":3 should come before "z"
        self.assertLess(result.index('"a":3'), result.index('"z"'))

    def test_minimal_separators(self):
        result = stringify({"a": 1, "b": 2})
        # No spaces around : or ,
        self.assertNotIn(": ", result)
        self.assertNotIn(", ", result)


class TestRecursiveOrder(unittest.TestCase):
    """Tests for recursive_order() — used by stringify."""

    def test_orders_dict_keys(self):
        result = recursive_order({"c": 1, "a": 2, "b": 3})
        self.assertEqual(list(result.keys()), ["a", "b", "c"])

    def test_handles_list(self):
        result = recursive_order([3, 1, 2])
        self.assertEqual(result, [3, 1, 2])  # Lists not sorted, just traversed

    def test_handles_nested(self):
        result = recursive_order({"b": {"d": 1, "c": 2}, "a": 3})
        self.assertEqual(list(result.keys()), ["a", "b"])
        self.assertEqual(list(result["b"].keys()), ["c", "d"])

    def test_integer_float_conversion(self):
        self.assertEqual(recursive_order(3.0), 3)
        self.assertIsInstance(recursive_order(3.0), int)

    def test_non_integer_float_preserved(self):
        self.assertEqual(recursive_order(3.5), 3.5)
        self.assertIsInstance(recursive_order(3.5), float)

    def test_string_unchanged(self):
        self.assertEqual(recursive_order("hello"), "hello")

    def test_bytes_unchanged(self):
        self.assertEqual(recursive_order(b"hello"), b"hello")


if __name__ == "__main__":
    unittest.main()
