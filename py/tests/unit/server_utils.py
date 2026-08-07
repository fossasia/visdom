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

import pytest

from visdom.utils.server_utils import (
    escape_eid,
    extract_eid,
    hash_password,
    stringify,
    recursive_order,
)

pytestmark = pytest.mark.unit


# ------------------------------------------------------------- escape_eid ----


@pytest.mark.parametrize(
    "raw, escaped",
    [
        ("a/b", "a_b"),
        ("a\\b", "a_b"),
        ("a\nb", "a-b"),
        ("a\rb", "a-b"),
        ("a/b\\c\nd\re", "a_b_c-d-e"),
        ("my_environment", "my_environment"),
        ("env_éàü", "env_éàü"),
        ("", ""),
    ],
    ids=[
        "forward_slash",
        "backslash",
        "newline",
        "carriage_return",
        "multiple_special_chars",
        "normal_string",
        "unicode",
        "empty",
    ],
)
def test_escape_eid_sanitizes(raw, escaped):
    assert escape_eid(raw) == escaped


# ------------------------------------------------------------- extract_eid ----


@pytest.mark.parametrize(
    "args, eid",
    [
        ({}, "main"),
        ({"eid": None}, "main"),
        ({"eid": "test"}, "test"),
        ({"eid": "a/b"}, "a_b"),
    ],
    ids=["default", "none_value", "with_value", "escapes_value"],
)
def test_extract_eid(args, eid):
    assert extract_eid(args) == eid


# ----------------------------------------------------------- hash_password ----


def test_hash_password_same_password_same_salt_matches():
    h1 = hash_password("secret")
    salt = h1.split("$")[0]
    assert hash_password("secret", salt=salt) == h1


def test_hash_password_same_password_different_salt_differs():
    assert hash_password("secret") != hash_password("secret")


def test_hash_password_different_passwords_same_salt_differs():
    h1 = hash_password("password1")
    salt = h1.split("$")[0]
    assert hash_password("password2", salt=salt) != h1


def test_hash_password_output_format():
    parts = hash_password("test").split("$")
    assert len(parts) == 2
    salt_hex, dk_hex = parts
    assert len(salt_hex) == 64
    assert len(dk_hex) == 64
    assert all(c in "0123456789abcdef" for c in salt_hex)
    assert all(c in "0123456789abcdef" for c in dk_hex)


def test_hash_password_full_login_flow():
    import hashlib as hl

    client_hash = hl.sha256("admin123".encode("utf-8")).hexdigest()
    stored = hash_password(client_hash)
    salt = stored.split("$")[0]
    assert hash_password(client_hash, salt=salt) == stored


# --------------------------------------------------------------- stringify ----


def test_stringify_orders_keys():
    result = stringify({"b": 1, "a": 2})
    assert result.index('"a"') < result.index('"b"')


def test_stringify_converts_integer_floats():
    result = stringify({"x": 1.0})
    assert ":1" in result
    assert "1.0" not in result


def test_stringify_preserves_non_integer_floats():
    assert "1.5" in stringify({"x": 1.5})


def test_stringify_nested_key_ordering():
    result = stringify({"z": {"b": 1, "a": 2}, "a": 3})
    assert result.index('"a":3') < result.index('"z"')


def test_stringify_uses_minimal_separators():
    result = stringify({"a": 1, "b": 2})
    assert ": " not in result
    assert ", " not in result


# --------------------------------------------------------- recursive_order ----


def test_recursive_order_orders_dict_keys():
    assert list(recursive_order({"c": 1, "a": 2, "b": 3}).keys()) == ["a", "b", "c"]


def test_recursive_order_traverses_a_list_without_sorting_it():
    assert recursive_order([3, 1, 2]) == [3, 1, 2]


def test_recursive_order_handles_nested_dicts():
    result = recursive_order({"b": {"d": 1, "c": 2}, "a": 3})
    assert list(result.keys()) == ["a", "b"]
    assert list(result["b"].keys()) == ["c", "d"]


@pytest.mark.parametrize(
    "value, expected, expected_type",
    [
        (3.0, 3, int),
        (3.5, 3.5, float),
        ("hello", "hello", str),
        (b"hello", b"hello", bytes),
    ],
    ids=["integer_float", "non_integer_float", "string", "bytes"],
)
def test_recursive_order_scalars(value, expected, expected_type):
    result = recursive_order(value)
    assert result == expected
    assert isinstance(result, expected_type)
