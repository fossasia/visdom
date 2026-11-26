#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Whether the server may post a webhook, where, and the posting itself.

A rule's url is shape-checked where the rule is built
(:func:`visdom.experiments.alerts.parse_webhook_url`). What is decided here is
the question that depends on the server rather than on the rule: may this
server make an outbound request at all, and is this host one the operator
named. Both are the operator's answers, so both come from flags, and both
default to no.

The reason that split exists is that the two questions have different
lifetimes. A rule outlives the process that stored it -- it is on the
experiment record, forked and reloaded with the environment -- while the flags
belong to the server that happens to be running. A rule written on a server
with webhooks on has to reload on a server with them off without becoming
unreadable, and it does: it reloads, and it is refused when it tries to go
out.
"""

import asyncio
import ipaddress
import json
import logging
from urllib.parse import urlsplit

from tornado.httpclient import AsyncHTTPClient

from visdom.utils.shared_utils import NanSafeEncoder

# Hostnames that name this machine without being an address.
LOCAL_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost")

# A webhook is a courtesy to a third party rather than part of the observation
# the caller asked to have recorded, so it is kept on a short leash.
CONNECT_TIMEOUT = 2
REQUEST_TIMEOUT = 5

# How long a shutdown waits for deliveries already in flight.
SHUTDOWN_DRAIN = 2


def _is_local_address(host):
    """Whether ``host`` is a literal address that never leaves the network.

    Loopback, link-local, private and the rest of the ranges that are not a
    destination on the internet. Link-local is the one that matters most:
    ``169.254.169.254`` is the cloud metadata service, and a server that will
    POST wherever a rule says is a server that will read its own credentials
    out and hand them to whoever wrote the rule.

    A *name* that resolves to one of these is not caught here, because the
    resolution would be a blocking call on the event loop and the answer can
    change between the check and the request anyway. The allowlist is what
    actually bounds where this server posts; this is the floor under it.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.lower() in LOCAL_NAMES
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_unspecified
        or address.is_reserved
        or address.is_multicast
    )


def parse_hosts(value):
    """The allowlist as the ``-webhook_hosts`` flag spells it.

    A comma-separated list, because that is how every other list-shaped flag
    on this server is written. Entries are lowercased here so the comparison
    does not have to be, and an empty entry is dropped rather than becoming a
    host that matches nothing.
    """
    if not value:
        return ()
    if isinstance(value, str):
        candidates = value.split(",")
    else:
        candidates = list(value)
    return tuple(
        sorted({entry.strip().lower() for entry in candidates if entry.strip()})
    )


class WebhookPolicy:
    """The operator's answer to "may the server post this, and where".

    Three flags, and all three default to refusing:

    * ``enabled`` (``-allow_webhooks``) -- off, so upgrading adds no outbound
      traffic to a server that did not ask for any.
    * ``hosts`` (``-webhook_hosts``) -- an allowlist, and an empty one refuses
      every target rather than allowing all of them. The url is written by
      whoever can reach the endpoint while the *server* is what makes the
      request, so without an allowlist a rule is a request this server will
      make to anywhere its network can reach.
    * ``allow_local`` (``-allow_local_webhooks``) -- loopback, link-local and
      private targets are refused unless the operator opts in. Opting in does
      not skip the allowlist; it only stops the address range itself being the
      refusal, which is what lets an operator point a rule at a relay running
      beside the server.

    An entry matches a host exactly, case-insensitively. An entry written with
    a leading dot (``.example.com``) matches that domain and its subdomains,
    which is the one form that is worth having: a webhook provider hands out
    per-integration subdomains, and naming them one by one would mean
    restarting the server for every new rule.
    """

    def __init__(self, enabled=False, hosts=(), allow_local=False):
        self.enabled = bool(enabled)
        self.hosts = parse_hosts(hosts)
        self.allow_local = bool(allow_local)

    def __repr__(self):  # pragma: no cover - diagnostics only
        return "WebhookPolicy(enabled={0!r}, hosts={1!r}, allow_local={2!r})".format(
            self.enabled, self.hosts, self.allow_local
        )

    def allows(self, host):
        """Whether ``host`` is named by the allowlist."""
        host = (host or "").lower()
        if not host:
            return False
        for entry in self.hosts:
            if entry.startswith("."):
                if host == entry[1:] or host.endswith(entry):
                    return True
            elif host == entry:
                return True
        return False

    def refusal(self, url):
        """Why ``url`` may not be posted to, or ``None`` when it may.

        A sentence rather than a boolean, because every caller of this has to
        tell somebody why: the endpoint puts it in the body of a 403, and the
        dispatch puts it in a log line. Each one names the flag that would
        change the answer -- a refusal an operator cannot act on is a bug
        report they have to write instead.
        """
        if not self.enabled:
            return (
                "webhook alerts are disabled on this server; start it with "
                "-allow_webhooks to allow them"
            )
        try:
            host = urlsplit(url).hostname
        except ValueError:
            host = None
        if not host:
            return "{0!r} names no host to post to".format(url)
        if not self.allow_local and _is_local_address(host):
            return (
                "{0!r} is not a destination on the network; start the server "
                "with -allow_local_webhooks to post to one anyway".format(host)
            )
        if not self.allows(host):
            return (
                "{0!r} is not an allowed webhook host; name it in "
                "-webhook_hosts".format(host)
            )
        return None


def payload(event, env_id, message):
    """The JSON body one firing is posted as.

    ``message`` is the sentence the toast would have carried, since a chat
    endpoint renders a body it does not understand as nothing at all; the rest
    is the firing taken apart for a receiver that is a program.
    """
    alert = event.alert
    return {
        "env": env_id,
        "metric": alert.key,
        "condition": alert.condition,
        "threshold": alert.threshold,
        "value": event.value,
        "step": event.step,
        "message": message,
        "fire_count": alert.fire_count,
        "fired_at": alert.last_fired_at,
    }


async def post(url, body, client=None):
    """POST one webhook. Answers with what went wrong, never by raising.

    Nothing from the rule reaches the request except its url: the method, the
    headers and the body are the server's own, redirects are not followed so an
    allowlisted host cannot bounce the request elsewhere, and the timeouts are
    short because nobody is waiting on the answer.
    """
    client = AsyncHTTPClient() if client is None else client
    try:
        response = await client.fetch(
            url,
            method="POST",
            body=json.dumps(body, cls=NanSafeEncoder),
            headers={"Content-Type": "application/json"},
            follow_redirects=False,
            connect_timeout=CONNECT_TIMEOUT,
            request_timeout=REQUEST_TIMEOUT,
            raise_error=False,
        )
    except Exception as error:
        # ``raise_error=False`` covers a refused connection, not a url the
        # client cannot start on at all.
        return "could not be reached: {0}".format(error)
    if 200 <= response.code < 300:
        return None
    if 300 <= response.code < 400:
        return "answered {0} with a redirect, which is not followed".format(
            response.code
        )
    return "answered {0}".format(response.code)


async def _deliver(url, body, client=None):
    """One delivery attempt, with its failure ending in the log."""
    refusal = await post(url, body, client=client)
    if refusal is not None:
        logging.warning("the alert webhook to %s %s", url, refusal)


def dispatch(policy, event, env_id, message, pending, client=None):
    """Send one fired rule to its webhook, without waiting for the answer.

    The observation is recorded either way, so an endpoint that is down is no
    reason to fail the training loop that logged a number: the task is started,
    registered in ``pending`` so nothing garbage-collects it mid-flight, and
    its failure ends in a log line. The policy is asked again here, and not
    only at set time, because a rule outlives the flags it was set under.
    """
    refusal = policy.refusal(event.alert.url)
    if refusal is not None:
        logging.warning(
            "not posting the alert for %r in %r: %s",
            event.alert.key,
            env_id,
            refusal,
        )
        return None

    body = payload(event, env_id, message)
    try:
        task = asyncio.ensure_future(_deliver(event.alert.url, body, client=client))
    except RuntimeError:
        # No running loop to attach to, and still not a reason to fail the
        # thing that fired.
        logging.warning(
            "could not schedule the alert webhook for %r in %r", event.alert.key, env_id
        )
        return None
    pending.add(task)
    task.add_done_callback(pending.discard)
    return task


async def drain(pending, timeout=None):
    """Wait for the deliveries already in flight.

    For the two callers that have to: a test asserting on what arrived, and a
    shutdown that would rather let a POST finish than kill it in flight.
    """
    while pending:
        awaiting = list(pending)
        if timeout is None:
            await asyncio.gather(*awaiting, return_exceptions=True)
        else:
            await asyncio.wait(awaiting, timeout=timeout)
            return
