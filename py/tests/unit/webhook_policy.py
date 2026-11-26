#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for where the server will post an alert webhook.

The policy is the only thing standing between "a client may write a url onto
an experiment record" and "this server makes an HTTP request to that url", so
what is asserted here is mostly what it *refuses*: a server nobody configured,
a host nobody named, and the address ranges that are not a destination on the
internet. Each refusal is a sentence rather than a boolean, because the
endpoint puts it in a response body and the dispatch puts it in a log line,
and both have to name the flag that would change the answer.
"""

import pytest

from visdom.server.webhooks import parse_hosts, WebhookPolicy

pytestmark = pytest.mark.unit

ALLOWED = "https://hooks.example.com/t"


def allowing(**kwargs):
    """A policy that allows ``hooks.example.com`` unless told otherwise."""
    kwargs.setdefault("enabled", True)
    kwargs.setdefault("hosts", "hooks.example.com")
    return WebhookPolicy(**kwargs)


class TestDefaults:
    def test_a_policy_nobody_configured_refuses_everything(self):
        policy = WebhookPolicy()
        assert policy.refusal(ALLOWED) is not None
        assert "-allow_webhooks" in policy.refusal(ALLOWED)

    def test_the_flag_alone_is_not_enough(self):
        # An empty allowlist refuses every target rather than allowing all of
        # them: the url is written by whoever can reach the endpoint, and the
        # server is what makes the request.
        policy = WebhookPolicy(enabled=True)
        assert "-webhook_hosts" in policy.refusal(ALLOWED)

    def test_an_allowed_host_is_allowed(self):
        assert allowing().refusal(ALLOWED) is None


class TestAllowlist:
    def test_a_host_outside_the_list_is_refused(self):
        refusal = allowing().refusal("https://attacker.example/t")
        assert "attacker.example" in refusal
        assert "-webhook_hosts" in refusal

    def test_matching_ignores_case_on_both_sides(self):
        policy = allowing(hosts="HOOKS.Example.COM")
        assert policy.refusal("https://Hooks.Example.com/t") is None

    def test_a_subdomain_is_not_a_host(self):
        # The exact form means exactly that host. A provider handing out
        # per-integration subdomains is what the dotted form below is for.
        assert allowing().refusal("https://evil.hooks.example.com/t") is not None

    def test_a_dotted_entry_matches_the_domain_and_its_subdomains(self):
        policy = allowing(hosts=".example.com")
        assert policy.refusal("https://hooks.example.com/t") is None
        assert policy.refusal("https://deep.hooks.example.com/t") is None
        assert policy.refusal("https://example.com/t") is None

    def test_a_dotted_entry_does_not_match_a_lookalike(self):
        # notexample.com must not match .example.com, which a bare suffix
        # comparison without the dot would let through.
        policy = allowing(hosts=".example.com")
        assert policy.refusal("https://notexample.com/t") is not None

    def test_the_port_is_not_part_of_the_host(self):
        assert allowing().refusal("https://hooks.example.com:8443/t") is None

    def test_several_entries_are_taken_from_one_flag(self):
        policy = allowing(hosts="hooks.example.com, relay.example.net ,")
        assert policy.refusal("https://relay.example.net/t") is None
        assert policy.refusal("https://hooks.example.com/t") is None


class TestLocalTargets:
    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "localhost",
            "0.0.0.0",
            "10.1.2.3",
            "192.168.1.9",
            "172.16.0.1",
            "169.254.169.254",
            "[::1]",
            "[fe80::1]",
        ],
    )
    def test_an_address_off_the_internet_is_refused_by_default(self, host):
        # 169.254.169.254 is the one that matters: a server that posts
        # wherever a rule says is a server that reads its own cloud
        # credentials out to whoever wrote the rule.
        policy = allowing(hosts=host.strip("[]") + ",localhost")
        refusal = policy.refusal("http://{0}/t".format(host))
        assert refusal is not None
        assert "-allow_local_webhooks" in refusal

    def test_the_operator_can_opt_in(self):
        policy = allowing(hosts="127.0.0.1", allow_local=True)
        assert policy.refusal("http://127.0.0.1:9000/t") is None

    def test_opting_in_does_not_skip_the_allowlist(self):
        # The two flags answer different questions, and both have to say yes.
        policy = allowing(hosts="relay.example.net", allow_local=True)
        assert policy.refusal("http://127.0.0.1:9000/t") is not None

    def test_a_public_address_is_allowed_without_the_local_flag(self):
        policy = allowing(hosts="93.184.216.34")
        assert policy.refusal("https://93.184.216.34/t") is None


class TestMalformedTargets:
    @pytest.mark.parametrize("url", ["", "https://", "not a url", None])
    def test_a_url_with_no_host_is_refused(self, url):
        # The policy is asked again at dispatch time, where the url comes off
        # a record that something else may have written, so it answers rather
        # than raising on input a rule would never have carried.
        assert allowing().refusal(url) is not None

    def test_a_url_the_stdlib_cannot_take_apart_is_refused(self):
        assert allowing().refusal("http://[notanaddress]/t") is not None


class TestParseHosts:
    def test_a_comma_separated_flag_becomes_entries(self):
        assert parse_hosts("a.example, b.example") == ("a.example", "b.example")

    def test_entries_are_lowercased_once_here(self):
        assert parse_hosts("A.Example") == ("a.example",)

    def test_blank_entries_are_dropped_rather_than_matching_nothing(self):
        assert parse_hosts(" , a.example , ") == ("a.example",)

    def test_duplicates_collapse(self):
        assert parse_hosts("a.example,a.example") == ("a.example",)

    @pytest.mark.parametrize("value", ["", None, (), []])
    def test_nothing_named_is_an_empty_allowlist(self, value):
        assert parse_hosts(value) == ()

    def test_a_list_is_accepted_as_well_as_a_flag_string(self):
        # ``Application`` is constructed directly by the tests and by anyone
        # embedding the server, and a list is the natural thing to pass there.
        assert parse_hosts(["a.example", "B.example"]) == ("a.example", "b.example")
