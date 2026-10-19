#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Withdrawing a workspace closes the sockets it already had open.

A workspace is refused when it is resolved, which stops anybody new getting in
and does nothing at all to a tab already open: a live socket never resolves
again. These cover the part that closes those.
"""

import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import pytest

from visdom.server.app import Application
from visdom.server.workspace_manager import WorkspaceManager
from visdom.server.ownership import (
    MOVED_REASON,
    WITHDRAWN_REASON,
    WS_POLICY_VIOLATION,
    WS_TRY_AGAIN_LATER,
    OwnershipMonitor,
    local_addresses,
)

pytestmark = pytest.mark.unit


class FakeSocket:
    """Records how it was closed, and refuses to be closed twice."""

    def __init__(self, broken=False):
        self.broken = broken
        self.closed_with = None

    def close(self, code, reason):
        if self.broken:
            raise RuntimeError("this socket is already gone")
        self.closed_with = (code, reason)


class TestEviction(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = Application(port=8097, env_path=self._tmp.name)
        self.addCleanup(self.app.shutdown_storage)

    def space(self, workspace_id, slug):
        return self.app.workspace_env_manager.space(workspace_id, slug=slug)

    def test_both_viewers_and_writers_are_closed(self):
        """An ownership eviction leaves writers alone, because a moved
        workspace is still somebody's to write to. A withdrawn one is not."""
        space = self.space("ws-a", "alpha")
        viewer, writer = FakeSocket(), FakeSocket()
        space.subs["v1"] = viewer
        space.sources["w1"] = writer

        self.assertEqual(self.app.evict_workspace("alpha"), 2)
        self.assertEqual(viewer.closed_with, (WS_POLICY_VIOLATION, WITHDRAWN_REASON))
        self.assertEqual(writer.closed_with, (WS_POLICY_VIOLATION, WITHDRAWN_REASON))

    def test_only_the_named_workspace_is_touched(self):
        """The whole point of the workspace layer."""
        mine = self.space("ws-a", "alpha")
        theirs = self.space("ws-b", "beta")
        mine.subs["v1"] = FakeSocket()
        theirs.subs["v2"] = FakeSocket()

        self.assertEqual(self.app.evict_workspace("alpha"), 1)
        self.assertIsNone(theirs.subs["v2"].closed_with)

    def test_the_code_is_the_one_a_refused_connection_gets(self):
        """1008, not the 1013 that invites a reconnect. A viewer told to come
        back would reconnect in a loop the gateway then refuses every time."""
        space = self.space("ws-a", "alpha")
        space.subs["v1"] = FakeSocket()

        self.app.evict_workspace("alpha")
        self.assertEqual(space.subs["v1"].closed_with[0], WS_POLICY_VIOLATION)

    def test_a_socket_that_cannot_be_closed_does_not_stop_the_rest(self):
        """A socket the client already dropped raises on close. Letting that
        escape would leave the sockets after it in the list still open."""
        space = self.space("ws-a", "alpha")
        space.subs["dead"] = FakeSocket(broken=True)
        space.subs["live"] = FakeSocket()

        self.assertEqual(self.app.evict_workspace("alpha"), 1)
        self.assertIsNotNone(space.subs["live"].closed_with)

    def test_an_unknown_slug_closes_nothing(self):
        self.space("ws-a", "alpha").subs["v1"] = FakeSocket()
        self.assertEqual(self.app.evict_workspace("no-such-workspace"), 0)

    def test_a_custom_reason_reaches_the_client(self):
        """The gateway says whether it was suspended or trashed, because the
        two mean different things to whoever is on the other end."""
        space = self.space("ws-a", "alpha")
        space.subs["v1"] = FakeSocket()

        self.app.evict_workspace("alpha", "this workspace is in the trash")
        self.assertEqual(
            space.subs["v1"].closed_with,
            (WS_POLICY_VIOLATION, "this workspace is in the trash"),
        )

    def test_a_withdrawn_workspace_is_asked_about_again(self):
        manager = WorkspaceManager(gateway_url="http://gateway:8085")
        self.app.workspace_manager = manager
        member = SimpleNamespace(
            status_code=200, json=lambda: {"workspace_id": "ws-a", "role": "member"}
        )
        with mock.patch(
            "visdom.server.workspace_manager.requests.post", return_value=member
        ) as post:
            manager.resolve("key-a", "alpha")
            manager.resolve("key-b", "beta")

            self.app.evict_workspace("alpha")
            manager.resolve("key-a", "alpha")
            manager.resolve("key-b", "beta")

        self.assertEqual(post.call_count, 3)


class TestOwnership(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = Application(port=8097, env_path=self._tmp.name)
        self.addCleanup(self.app.shutdown_storage)
        self.space = self.app.workspace_env_manager.space("ws-a", slug="alpha")
        self.viewer, self.writer = FakeSocket(), FakeSocket()
        self.space.subs["v1"] = self.viewer
        self.space.sources["w1"] = self.writer

    def check(self, owner):
        monitor = OwnershipMonitor(
            self.app,
            "http://proxy",
            "/vis/_shard",
            30,
            {"10.0.0.1:8097", "172.18.0.4:8097"},
        )

        async def owner_of(slug):
            return owner

        monitor.owner_of = owner_of
        return asyncio.run(monitor.check())

    def test_a_workspace_that_moved_closes_its_viewers_with_a_retry(self):
        self.assertEqual(self.check("10.0.0.2:8097"), 1)
        self.assertEqual(self.viewer.closed_with, (WS_TRY_AGAIN_LATER, MOVED_REASON))

    def test_a_moved_workspace_keeps_its_writers(self):
        self.check("10.0.0.2:8097")
        self.assertIsNone(self.writer.closed_with)

    def test_a_workspace_still_here_is_left_alone(self):
        self.assertEqual(self.check("10.0.0.1:8097"), 0)
        self.assertIsNone(self.viewer.closed_with)

    def test_a_workspace_on_any_of_its_own_addresses_is_left_alone(self):
        self.assertEqual(self.check("172.18.0.4:8097"), 0)
        self.assertIsNone(self.viewer.closed_with)

    def test_a_monitor_without_its_own_address_closes_nothing(self):
        monitor = OwnershipMonitor(self.app, "http://proxy", "/vis/_shard", 30, ())

        async def owner_of(slug):
            return "10.0.0.2:8097"

        monitor.owner_of = owner_of
        self.assertEqual(asyncio.run(monitor.check()), 0)
        self.assertIsNone(self.viewer.closed_with)

    def test_no_answer_from_the_proxy_closes_nothing(self):
        self.assertEqual(self.check(None), 0)
        self.assertIsNone(self.viewer.closed_with)

    def test_the_owner_is_read_from_the_proxys_last_upstream(self):
        monitor = OwnershipMonitor(self.app, "http://proxy/", "/vis/_shard", 30, None)
        asked = []

        async def fetch(url, **kwargs):
            asked.append((url, kwargs["headers"]))
            return SimpleNamespace(
                headers={"X-Visdom-Upstream": "10.0.0.3:8097, 10.0.0.2:8097"}
            )

        monitor.client = SimpleNamespace(fetch=fetch)

        self.assertEqual(asyncio.run(monitor.owner_of("alpha")), "10.0.0.2:8097")
        self.assertEqual(
            asked, [("http://proxy/vis/_shard", {"X-Visdom-Workspace": "alpha"})]
        )

    def test_the_monitor_is_off_without_a_proxy(self):
        with mock.patch.dict("os.environ", {}, clear=False) as environ:
            environ.pop("VISDOM_PROXY_URL", None)
            self.assertIsNone(self.app.start_ownership_monitor())

    def test_the_monitor_starts_when_a_proxy_is_named(self):
        with mock.patch.dict(
            "os.environ",
            {"VISDOM_PROXY_URL": "http://proxy", "VISDOM_OWNERSHIP_INTERVAL": "15"},
        ), mock.patch.object(OwnershipMonitor, "start") as start, mock.patch(
            "visdom.server.app.local_addresses", return_value={"10.0.0.1:8097"}
        ):
            monitor = self.app.start_ownership_monitor()

        start.assert_called_once()
        self.assertEqual(monitor.interval, 15)
        self.assertEqual(monitor.probe_path, "/_shard")

    def test_the_monitor_stays_off_without_its_own_address(self):
        with mock.patch.dict(
            "os.environ", {"VISDOM_PROXY_URL": "http://proxy"}
        ), mock.patch.object(OwnershipMonitor, "start") as start, mock.patch(
            "visdom.server.app.local_addresses", return_value=frozenset()
        ):
            self.assertIsNone(self.app.start_ownership_monitor())
        start.assert_not_called()


def _resolving(*hosts):
    return [(None, None, None, "", (host, 8097)) for host in hosts]


class TestLocalAddresses(unittest.TestCase):
    def addresses(self, found):
        with mock.patch(
            "visdom.server.ownership.socket_module.getaddrinfo", **found
        ), mock.patch(
            "visdom.server.ownership.socket_module.gethostname", return_value="box"
        ):
            return local_addresses(8097)

    def test_every_address_of_the_host_is_its_own(self):
        found = self.addresses({"return_value": _resolving("172.18.0.4", "10.0.0.1")})
        self.assertEqual(found, {"172.18.0.4:8097", "10.0.0.1:8097"})

    def test_loopback_is_never_its_own(self):
        found = self.addresses({"return_value": _resolving("127.0.1.1", "::1")})
        self.assertEqual(found, frozenset())

    def test_an_ipv6_address_is_named_as_nginx_names_it(self):
        found = self.addresses({"return_value": _resolving("fd00::4")})
        self.assertEqual(found, {"[fd00::4]:8097"})

    def test_a_hostname_that_does_not_resolve_gives_nothing(self):
        found = self.addresses({"side_effect": OSError("no such host")})
        self.assertEqual(found, frozenset())


class TestDrain(unittest.TestCase):
    def test_shutting_down_tells_every_viewer_to_come_back(self):
        with tempfile.TemporaryDirectory() as path:
            app = Application(port=8097, env_path=path)
            own = FakeSocket()
            app.workspace_env_manager.space(None).subs["v0"] = own
            space = app.workspace_env_manager.space("ws-a", slug="alpha")
            viewer, broken = FakeSocket(), FakeSocket(broken=True)
            space.subs["v1"] = viewer
            space.subs["v2"] = broken

            self.assertEqual(app.drain_sockets(), 2)
            app.shutdown_storage()

        self.assertEqual(own.closed_with[0], WS_TRY_AGAIN_LATER)
        self.assertEqual(viewer.closed_with[0], WS_TRY_AGAIN_LATER)


if __name__ == "__main__":
    unittest.main()
