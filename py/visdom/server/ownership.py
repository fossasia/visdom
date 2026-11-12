#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Closes sockets for workspaces this instance no longer owns.

The proxy hashes a workspace to one instance. When the pool changes, some
workspaces move, but sockets opened before the move stay attached to the old
instance: writes reach the new owner while the viewer waits on the old one and
its plots silently stop. An instance cannot detect this on its own, because
traffic for a lost workspace simply stops arriving and silence is not a signal.

So each instance periodically asks the proxy who owns the workspaces it is
holding sockets for, and closes the ones that have moved. The hash stays in one
place: this asks the component that owns the routing decision rather than
reimplementing it.
"""

import ipaddress
import logging
import socket as socket_module

from tornado.httpclient import AsyncHTTPClient
from tornado.ioloop import PeriodicCallback

from visdom.server.handlers.socket_handlers import (
    WS_POLICY_VIOLATION,
    WS_TRY_AGAIN_LATER,
)

MOVED_REASON = "workspace moved to another instance, reconnect"
# A moved workspace tells the client to come back; a withdrawn one must not,
# or every viewer of a suspended workspace reconnects in a loop that the
# gateway then has to refuse over and over.
WITHDRAWN_REASON = "this workspace is no longer available, contact an administrator"
UPSTREAM_HEADER = "X-Visdom-Upstream"


def local_addresses(port):
    """Every address the proxy might name this instance by in an upstream.

    Empty when the hostname does not resolve, or resolves only to loopback,
    which the proxy never names. The monitor then stays off: without its own
    address it would take every workspace for moved and close every viewer.
    """
    try:
        found = socket_module.getaddrinfo(
            socket_module.gethostname(), port, proto=socket_module.IPPROTO_TCP
        )
    except OSError:
        return frozenset()
    addresses = set()
    for info in found:
        host = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_unspecified:
            continue
        addresses.add(("[%s]:%d" if ip.version == 6 else "%s:%d") % (host, port))
    return frozenset(addresses)


class OwnershipMonitor:
    def __init__(self, app, proxy_url, probe_path, interval, self_addresses):
        self.app = app
        self.proxy_url = proxy_url.rstrip("/")
        self.probe_path = probe_path
        self.interval = interval
        self.self_addresses = frozenset(self_addresses or ())
        self.callback = None
        self.client = AsyncHTTPClient()

    async def owner_of(self, slug):
        """Ask the proxy which instance currently serves a workspace."""
        try:
            response = await self.client.fetch(
                self.proxy_url + self.probe_path,
                headers={"X-Visdom-Workspace": slug},
                raise_error=False,
                request_timeout=5,
            )
        except Exception as exc:
            logging.debug("ownership probe for %s failed: %s", slug, exc)
            return None
        upstream = response.headers.get(UPSTREAM_HEADER)
        if not upstream:
            return None
        return upstream.split(",")[-1].strip()

    def evict(self, space, owner):
        subs = list(space.subs.values())
        for sub in subs:
            try:
                sub.close(WS_TRY_AGAIN_LATER, MOVED_REASON)
            except Exception as exc:
                logging.debug("could not close a moved socket: %s", exc)
        logging.info(
            "workspace %s now served by %s, closed %d socket(s)",
            space.slug,
            owner,
            len(subs),
        )
        return len(subs)

    async def check(self):
        manager = getattr(self.app, "workspace_env_manager", None)
        if manager is None or not self.self_addresses:
            return 0
        closed = 0
        for _workspace_id, space in manager.workspace_spaces():
            if not space.subs or not space.slug:
                continue
            owner = await self.owner_of(space.slug)
            if owner is None or owner in self.self_addresses:
                continue
            closed += self.evict(space, owner)
        return closed

    def start(self):
        if self.callback is None and self.interval > 0:
            self.callback = PeriodicCallback(self.check, self.interval * 1000)
            self.callback.start()
        return self.callback

    def stop(self):
        if self.callback is not None:
            self.callback.stop()
            self.callback = None
