#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from types import SimpleNamespace

import pytest

from visdom.server import internal

pytestmark = pytest.mark.unit

NOW = 1_800_000_000


def request(headers, method="GET", uri="/_activity", body=b""):
    return SimpleNamespace(method=method, uri=uri, body=body, headers=headers)


def signed(key, method="GET", uri="/_activity", body=b"", at=NOW):
    return request(
        internal.signed_headers(key, method, uri, body, now=at), method, uri, body
    )


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("VISDOM_INTERNAL_READ_KEYS", "read-one")
    monkeypatch.setenv("VISDOM_INTERNAL_ADMIN_KEYS", "admin-one")


def test_a_request_signed_with_the_read_key_passes(keys):
    assert internal.is_signed(signed("read-one"), internal.READ, now=NOW)


def test_an_unsigned_request_is_refused(keys):
    assert not internal.is_signed(request({}), internal.READ, now=NOW)


def test_a_wrong_key_is_refused(keys):
    assert not internal.is_signed(signed("guess"), internal.READ, now=NOW)


def test_the_read_key_does_not_open_the_admin_scope(keys):
    assert not internal.is_signed(signed("read-one"), internal.ADMIN, now=NOW)
    assert internal.is_signed(signed("admin-one"), internal.ADMIN, now=NOW)


def test_with_no_key_set_everything_is_refused(monkeypatch):
    monkeypatch.delenv("VISDOM_INTERNAL_READ_KEYS", raising=False)

    assert not internal.is_signed(signed(""), internal.READ, now=NOW)


@pytest.mark.parametrize("age", [61, -61])
def test_a_signature_outside_the_window_is_refused(keys, age):
    assert not internal.is_signed(
        signed("read-one", at=NOW - age), internal.READ, now=NOW
    )


def test_a_changed_body_breaks_the_signature(keys):
    sent = signed("admin-one", "POST", "/_drop", b'{"workspace_id": "a"}')
    sent.body = b'{"workspace_id": "b"}'

    assert not internal.is_signed(sent, internal.ADMIN, now=NOW)


def test_a_changed_path_breaks_the_signature(keys):
    sent = signed("read-one", uri="/_activity")
    sent.uri = "/_metrics"

    assert not internal.is_signed(sent, internal.READ, now=NOW)


def test_both_keys_work_while_one_is_being_replaced(monkeypatch):
    monkeypatch.setenv("VISDOM_INTERNAL_READ_KEYS", "old-key, new-key")

    assert internal.is_signed(signed("old-key"), internal.READ, now=NOW)
    assert internal.is_signed(signed("new-key"), internal.READ, now=NOW)


def test_a_metrics_token_is_checked(monkeypatch):
    monkeypatch.setenv("VISDOM_METRICS_TOKENS", "scrape-me")

    assert internal.has_metrics_token(request({"Authorization": "Bearer scrape-me"}))
    assert not internal.has_metrics_token(request({"Authorization": "Bearer nope"}))
    assert not internal.has_metrics_token(request({}))


def test_with_no_metrics_token_set_none_is_accepted(monkeypatch):
    monkeypatch.delenv("VISDOM_METRICS_TOKENS", raising=False)

    assert not internal.has_metrics_token(request({"Authorization": "Bearer "}))


def test_the_signature_matches_what_the_gateway_sends():
    assert (
        internal.signature("test-key", "GET", "/vis/_activity", 1800000000, b"")
        == "0d322e34f6824f7fc34f64a830f5bf19b82cf6ccccdf70984a68eccc1562c1a9"
    )
    assert (
        internal.signature(
            "test-key", "POST", "/vis/_drop", 1800000000, b'{"workspace_id": "ws-a"}'
        )
        == "56bdd87730abd4c3a545707937679b3ad3cabc131adf186a219f737b698e3ecf"
    )
