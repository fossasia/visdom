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

from visdom.data_model.json_store import JSONStore
from visdom.utils.server_utils import (
    LazyEnvData,
    escape_eid,
    extract_eid,
    hash_password,
    snapshot_env,
    snapshot_state,
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
        ("  main", "main"),
        ("main  ", "main"),
        ("  main  ", "main"),
        ("my env", "my env"),
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
        "leading_whitespace",
        "trailing_whitespace",
        "surrounding_whitespace",
        "internal_whitespace_preserved",
    ],
)
def test_escape_eid_sanitizes(raw, escaped):
    assert escape_eid(raw) == escaped


@pytest.mark.parametrize("padded", ["main ", " main"], ids=["trailing", "leading"])
def test_escape_eid_collapses_whitespace_only_differing_ids(padded):
    """'main' and 'main ' must normalise identically.

    JSONStore strips whitespace before deriving an on-disk filename, so if
    escape_eid did not also strip, these two eids would stay distinct in the
    in-memory state dict while silently colliding on disk.
    """
    assert escape_eid(padded) == escape_eid("main")


# ------------------------------------------------------------- extract_eid ----


@pytest.mark.parametrize(
    "args, eid",
    [
        ({}, "main"),
        ({"eid": None}, "main"),
        ({"eid": "test"}, "test"),
        ({"eid": "a/b"}, "a_b"),
        ({"eid": "main "}, "main"),
    ],
    ids=["default", "none_value", "with_value", "escapes_value", "strips_whitespace"],
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


# ------------------------------------------------- off-loop storage helpers ----


def env_dict(win="win_0"):
    return {"jsons": {win: {"id": win, "content": {}}}, "reload": {}}


def test_snapshot_env_copies_a_plain_dict():
    live = env_dict()
    copied = snapshot_env(live)

    assert copied == live
    assert copied is not live
    assert copied["jsons"] is not live["jsons"]
    assert copied["jsons"]["win_0"] is not live["jsons"]["win_0"]


def test_snapshot_env_is_unaffected_by_later_mutation():
    """The whole point: the worker sees the env as it was at hand-off."""
    live = env_dict()
    copied = snapshot_env(live)

    live["jsons"]["win_late"] = {"id": "win_late"}
    live["jsons"]["win_0"]["content"] = {"changed": True}

    assert list(copied["jsons"]) == ["win_0"]
    assert copied["jsons"]["win_0"]["content"] == {}


def test_snapshot_env_skips_a_cold_lazy_env(tmp_path):
    """A never-read env is already current on disk, so there is nothing to write."""
    lazy = LazyEnvData(JSONStore(str(tmp_path)), "cold")

    assert snapshot_env(lazy) is None
    assert not lazy.is_loaded


def test_snapshot_env_copies_a_primed_lazy_env(tmp_path):
    lazy = LazyEnvData(JSONStore(str(tmp_path)), "warm")
    lazy.prime(env_dict())

    copied = snapshot_env(lazy)

    assert copied["jsons"]["win_0"]["id"] == "win_0"
    assert copied["jsons"] is not lazy["jsons"]


def test_snapshot_state_drops_cold_envs_and_copies_the_rest(tmp_path):
    store = JSONStore(str(tmp_path))
    warm = LazyEnvData(store, "warm")
    warm.prime(env_dict("win_warm"))
    state = {
        "plain": env_dict("win_plain"),
        "warm": warm,
        "cold": LazyEnvData(store, "cold"),
    }

    snapshot = snapshot_state(state)

    assert sorted(snapshot) == ["plain", "warm"]
    assert snapshot["plain"] is not state["plain"]
    assert list(snapshot["warm"]["jsons"]) == ["win_warm"]


# ------------------------------------------------------------- LazyEnvData ----


def test_lazy_env_is_not_loaded_until_read(tmp_path):
    lazy = LazyEnvData(JSONStore(str(tmp_path)), "cold")
    assert lazy.is_loaded is False


def test_prime_installs_the_env_without_touching_disk(tmp_path):
    """Priming is how the off-loop read hands its result back to the loop."""

    class ExplodingStore(JSONStore):
        def load_env(self, eid):
            raise AssertionError("prime must not read from disk")

    lazy = LazyEnvData(ExplodingStore(str(tmp_path)), "warm")
    lazy.prime(env_dict())

    assert lazy.is_loaded is True
    assert lazy["jsons"]["win_0"]["id"] == "win_0"


def test_prime_leaves_an_already_loaded_env_alone():
    """Two racing primes must not clobber whichever landed first."""
    lazy = LazyEnvData(None, "warm")
    lazy.prime(env_dict("first"))
    lazy.prime(env_dict("second"))

    assert list(lazy["jsons"]) == ["first"]


def test_prime_rejects_a_malformed_env():
    lazy = LazyEnvData(None, "broken")
    with pytest.raises(ValueError):
        lazy.prime({"jsons": {}})
