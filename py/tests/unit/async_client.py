#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for ``AsyncVisdom`` and its transport.

Nothing here binds a socket. The client is built with a recording transport
handed to ``AsyncVisdom.create``, so the full construction path -- worker
thread, opening POST to ``/env/<eid>``, proxying -- runs while the wire is a
list of tuples. The transport's own request building and error translation are
checked directly, without a loop.

Coroutine bodies run under ``tornado.testing.AsyncTestCase`` + ``@gen_test``;
the suite has no pytest-asyncio and tornado's own harness is already the
pattern used by the handler tests.
"""

import asyncio
import ssl
import threading

import pytest
import requests
import tornado.testing
from tornado.httpclient import AsyncHTTPClient, HTTPClientError
from tornado.simple_httpclient import HTTPTimeoutError
from tornado.testing import gen_test

from visdom.async_client import (
    AsyncVisdom,
    DEFAULT_MAX_CONCURRENCY,
    _AsyncTransport,
    _as_requests_error,
    _BridgedVisdom,
    _extract_cookie,
    _PROXIED,
)

pytestmark = pytest.mark.unit


class RecordingTransport(object):
    """Stands in for ``_AsyncTransport``: records posts, answers canned text."""

    def __init__(self, response=""):
        self.calls = []
        self.response = response
        self.closed = False

    async def post(self, url, data=None):
        self.calls.append((url, data))
        if callable(self.response):
            return self.response(url, data)
        return self.response

    def close(self):
        self.closed = True

    @property
    def endpoints(self):
        """Just the path of each recorded call, in order."""
        return [url.split("8097", 1)[-1] for url, _ in self.calls]


async def make_client(transport=None, **kwargs):
    """An ``AsyncVisdom`` wired to a recording transport instead of a server."""
    transport = RecordingTransport() if transport is None else transport
    kwargs.setdefault("raise_exceptions", False)
    client = await AsyncVisdom.create(transport=transport, **kwargs)
    return client, transport


# ------------------------------------------------------------------ transport --


def test_extract_cookie_finds_the_named_cookie():
    response = _FakeResponse(
        set_cookie=[
            "other=1; Path=/",
            'user_password="abc|123"; expires=Fri; Path=/',
        ]
    )
    assert _extract_cookie(response, "user_password") == 'user_password="abc|123"'


def test_extract_cookie_returns_none_when_absent():
    assert (
        _extract_cookie(_FakeResponse(set_cookie=["other=1"]), "user_password") is None
    )


def test_ssl_failures_translate_to_the_requests_ssl_error():
    """``_send`` matches on ``requests.exceptions.SSLError`` to print the
    mkcert hint, so a tornado TLS failure has to arrive as that type."""
    translated = _as_requests_error(ssl.SSLCertVerificationError("bad cert"))
    assert isinstance(translated, requests.exceptions.SSLError)


def test_timeouts_translate_to_the_requests_timeout():
    translated = _as_requests_error(HTTPTimeoutError("Timeout while connecting"))
    assert isinstance(translated, requests.exceptions.Timeout)


def test_other_transport_failures_translate_to_a_connection_error():
    translated = _as_requests_error(HTTPClientError(599, "Stream closed"))
    assert isinstance(translated, requests.exceptions.ConnectionError)
    assert isinstance(
        _as_requests_error(ConnectionRefusedError("nope")),
        requests.exceptions.ConnectionError,
    )


def test_request_mirrors_the_sync_client_timeouts():
    """``timeout=(20, None)`` in the sync client: bound connect, not read."""
    transport = _AsyncTransport("http://localhost", 8097)
    request = transport._request("http://localhost:8097/events", "{}")
    assert request.method == "POST"
    assert request.body == b"{}"
    assert request.connect_timeout == 20.0
    assert request.request_timeout == 0


def test_request_carries_the_login_cookie_once_set():
    transport = _AsyncTransport("http://localhost", 8097, username="u", password="p")
    assert "Cookie" not in transport._request("http://x", "").headers
    transport.cookie = "user_password=abc"
    request = transport._request("http://x", "")
    assert request.headers["Cookie"] == "user_password=abc"


def test_ssl_verify_string_becomes_a_ca_bundle():
    transport = _AsyncTransport("https://localhost", 8097, ssl_verify="/tmp/ca.pem")
    assert transport._request("https://x", "").ca_certs == "/tmp/ca.pem"


def test_max_clients_defaults_to_the_shared_concurrency_limit():
    assert _AsyncTransport("http://localhost", 8097).max_clients == (
        DEFAULT_MAX_CONCURRENCY
    )


def test_ssl_verify_false_disables_validation():
    transport = _AsyncTransport("https://localhost", 8097, ssl_verify=False)
    assert transport._request("https://x", "").validate_cert is False


class _FakeResponse(object):
    def __init__(self, set_cookie=(), code=200, body=b""):
        self.code = code
        self.body = body
        self.headers = _FakeHeaders(list(set_cookie))


class _FakeHeaders(object):
    def __init__(self, cookies):
        self._cookies = cookies

    def get_list(self, name):
        return self._cookies if name == "Set-Cookie" else []


# ----------------------------------------------------------------- allowlist --


def test_allowlist_covers_every_public_visdom_method_but_the_socket_ones():
    """A method added to ``Visdom`` should not join the async API by accident,
    and one removed from it should not linger here."""
    import inspect

    from visdom import Visdom

    public = {
        name
        for name, value in inspect.getmembers(Visdom)
        if not name.startswith("_") and inspect.isfunction(value)
    }
    assert _PROXIED - public == set()
    assert public - _PROXIED == {
        "register_event_handler",
        "clear_event_handlers",
        "setup_socket",
        "setup_polling",
    }


# -------------------------------------------------------------------- client --


class TestAsyncVisdomConstruction(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_create_posts_the_env_once(self):
        """``Visdom.__init__`` announces the env; the bridge must carry it."""
        _, transport = await make_client(env="demo")
        assert transport.endpoints == ["/env/demo"]

    @gen_test
    async def test_create_rejects_the_incoming_socket(self):
        with pytest.raises(NotImplementedError, match="events"):
            await AsyncVisdom.create(
                transport=RecordingTransport(), use_incoming_socket=True
            )

    @gen_test
    async def test_create_rejects_polling(self):
        with pytest.raises(NotImplementedError, match="events"):
            await AsyncVisdom.create(transport=RecordingTransport(), use_polling=True)

    @gen_test
    async def test_create_rejects_proxies(self):
        with pytest.raises(NotImplementedError, match="prox"):
            await AsyncVisdom.create(
                transport=RecordingTransport(), proxies={"http": "localhost:3128"}
            )

    @gen_test
    async def test_a_failed_construction_closes_the_transport(self):
        """``create`` is the only one who can: the caller never sees the object.

        ``Visdom.__init__`` POSTs, and that POST is what builds the private
        ``AsyncHTTPClient``. When the announcement is refused -- a bad login, a
        rejected env -- the half-built bridge is discarded with a live transport
        still attached, and no wrapper exists to call ``shutdown()`` on.
        """

        class FailingTransport(RecordingTransport):
            async def post(self, url, data=None):
                self.calls.append((url, data))
                raise requests.exceptions.ConnectionError("refused")

        transport = FailingTransport()
        with pytest.raises(ConnectionError):
            await AsyncVisdom.create(transport=transport, raise_exceptions=True)
        assert transport.closed is True

    @gen_test
    async def test_no_session_reaper_thread_is_started(self):
        """There is no ``requests`` session here, so reaping one is pointless
        -- and a daemon thread per client would be a leak."""
        client, _ = await make_client()
        assert not hasattr(client.client, "session_reaper_thread")

    @gen_test
    async def test_setup_socket_on_the_inner_client_is_refused(self):
        client, _ = await make_client()
        with pytest.raises(NotImplementedError):
            client.client.setup_socket()


class TestTransportHTTPClient(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_max_clients_reaches_the_http_client(self):
        """Built lazily because an ``AsyncHTTPClient`` binds to its loop."""
        transport = _AsyncTransport("http://localhost", 8097, max_clients=3)
        assert transport.client.max_clients == 3

    @gen_test
    async def test_the_http_client_is_a_private_instance(self):
        """``AsyncHTTPClient()`` hands back a per-loop singleton; closing that
        on shutdown would break every other user of the loop."""
        transport = _AsyncTransport("http://localhost", 8097)
        assert transport.client is not AsyncHTTPClient()
        transport.close()


class TestTransportLogin(tornado.testing.AsyncTestCase):
    """A configured ``username`` makes the login the first thing that touches
    the network, so it is where an unreachable server is met first."""

    @staticmethod
    def _failing(error):
        transport = _AsyncTransport(
            "http://localhost", 8097, username="u", password="p"
        )

        async def _fetch(request):
            raise error

        transport._fetch = _fetch
        return transport

    @gen_test
    async def test_a_refused_login_arrives_as_a_requests_connection_error(self):
        """``_send`` matches ``requests`` exceptions by type. A tornado error
        escaping the login would skip ``raise_exceptions`` and crash the call
        that the sync client answers with ``False``."""
        transport = self._failing(ConnectionRefusedError("nope"))
        with pytest.raises(requests.exceptions.ConnectionError):
            await transport._ensure_login()

    @gen_test
    async def test_a_login_tls_failure_keeps_the_ssl_type(self):
        """``_send`` prints the mkcert hint only for ``requests`` SSLError."""
        transport = self._failing(ssl.SSLCertVerificationError("bad cert"))
        with pytest.raises(requests.exceptions.SSLError):
            await transport._ensure_login()

    @gen_test
    async def test_a_login_timeout_keeps_the_timeout_type(self):
        transport = self._failing(HTTPTimeoutError("Timeout while connecting"))
        with pytest.raises(requests.exceptions.Timeout):
            await transport._ensure_login()

    @gen_test
    async def test_a_rejected_password_still_raises_authentication_failed(self):
        """Only transport failures are translated: a served 403 is a real
        credential error and the sync client raises there too."""
        transport = _AsyncTransport(
            "http://localhost", 8097, username="u", password="p"
        )

        async def _fetch(request):
            return _FakeResponse(code=403)

        transport._fetch = _fetch
        with pytest.raises(RuntimeError, match="Authentication failed"):
            await transport._ensure_login()

    @gen_test
    async def test_a_failed_login_does_not_retry_as_an_unauthenticated_post(self):
        """``post`` retries a recycled connection, but the login must not be
        swept into that retry: the second attempt would carry no cookie."""
        transport = self._failing(ConnectionRefusedError("nope"))
        transport._connected = True
        with pytest.raises(requests.exceptions.ConnectionError):
            await transport.post("http://localhost:8097/events", "{}")


class TestAsyncVisdomProxying(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_plot_methods_are_coroutines_returning_the_window_id(self):
        client, transport = await make_client()
        win = await client.text("hello", win="w1")
        assert win == ""  # the recording transport's canned body
        assert transport.endpoints[-1] == "/events"

    @gen_test
    async def test_payload_matches_the_sync_client(self):
        """The plot bodies are the untouched synchronous ones, so the bytes on
        the wire have to be identical -- that is the whole point of the bridge."""
        import json

        client, transport = await make_client()
        await client.text("hello", win="w1", env="e1")
        _, data = transport.calls[-1]
        payload = json.loads(data)
        assert payload["win"] == "w1"
        assert payload["eid"] == "e1"
        assert payload["data"][0]["content"] == "hello"

    @gen_test
    async def test_proxy_keeps_the_wrapped_name_and_docstring(self):
        client, _ = await make_client()
        assert client.line.__name__ == "line"
        assert client.line.__doc__ == type(client.client).line.__doc__

    @gen_test
    async def test_unknown_attributes_raise_attribute_error(self):
        client, _ = await make_client()
        with pytest.raises(AttributeError):
            client.not_a_method

    @gen_test
    async def test_private_attributes_are_not_proxied(self):
        """``__getattr__`` must reject private names before touching
        ``self._inner``, or a missing ``_inner`` recurses forever."""
        client, _ = await make_client()
        with pytest.raises(AttributeError):
            client._send

    @gen_test
    async def test_socket_entry_points_say_what_is_missing(self):
        client, _ = await make_client()
        with pytest.raises(NotImplementedError, match="event"):
            client.register_event_handler(lambda m: None, "t")
        with pytest.raises(NotImplementedError, match="event"):
            client.clear_event_handlers("t")

    @gen_test
    async def test_dir_advertises_the_proxied_methods(self):
        client, _ = await make_client()
        assert "line" in dir(client)
        assert "scatter" in dir(client)

    @gen_test
    async def test_env_is_readable_and_writable(self):
        client, transport = await make_client(env="one")
        assert client.env == "one"
        client.env = "two"
        await client.text("hi")
        import json

        assert json.loads(transport.calls[-1][1])["eid"] == "two"

    @gen_test
    async def test_env_list_and_win_data_pass_through(self):
        client, _ = await make_client(env="one")
        assert client.env_list == client.client.env_list
        assert client.win_data is client.client.win_data
        assert client.offline is False


class TestAsyncVisdomConcurrency(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_gather_runs_calls_concurrently(self):
        client, transport = await make_client()
        await asyncio.gather(*[client.text("m", win="w%d" % i) for i in range(5)])
        assert len(transport.calls) == 6  # the env announcement plus five texts

    @gen_test
    async def test_the_event_loop_stays_free_while_a_call_is_in_flight(self):
        """The bridge blocks the worker thread, never the loop.

        The gate is only opened by a coroutine scheduled after the plot call
        starts, so if ``_handle_post`` blocked the loop this would deadlock and
        time out rather than fail an assertion.
        """
        gate = asyncio.Event()

        class GatedTransport(RecordingTransport):
            async def post(self, url, data=None):
                self.calls.append((url, data))
                if self.calls[1:]:  # let construction through unhindered
                    await gate.wait()
                return ""

        client, transport = await make_client(GatedTransport())
        task = asyncio.ensure_future(client.text("hello"))
        await asyncio.sleep(0)
        gate.set()
        await task
        assert len(transport.calls) == 2

    @gen_test
    async def test_calls_run_on_the_clients_own_thread_pool(self):
        """Not ``asyncio.to_thread``: see the deadlock guarded below."""
        client, _ = await make_client()
        client.client.text = lambda *a, **kw: threading.current_thread().name
        assert (await client.text("x")).startswith("visdom-async-client")

    @gen_test
    async def test_more_calls_than_workers_all_complete(self):
        """The regression guard for the default-executor deadlock.

        asyncio resolves hostnames on the default executor. While the proxies
        used ``asyncio.to_thread``, a gather wider than that pool left no
        thread for ``getaddrinfo``, and every request in the batch hung until
        its connect timeout instead of finishing. A private pool cannot starve
        the loop's own resolver, so a batch far wider than the pool is fine.
        """
        client, transport = await make_client(max_concurrency=2)
        await asyncio.gather(*[client.text("m", win="w%d" % i) for i in range(20)])
        assert len(transport.calls) == 21

    @gen_test
    async def test_max_concurrency_sizes_the_pool_and_the_http_client(self):
        """One knob has to move both, or requests queue inside tornado with
        their connect timeout already running."""
        client, _ = await make_client(max_concurrency=3)
        assert client._executor._max_workers == 3
        assert client.client._max_clients == 3


class TestAsyncVisdomErrors(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_connection_errors_keep_the_sync_return_false_contract(self):
        """``_send`` swallows ``requests`` errors when ``raise_exceptions`` is
        False. Translating tornado failures into ``requests`` types is what
        keeps that behavior identical for async callers."""

        class FailingTransport(RecordingTransport):
            async def post(self, url, data=None):
                raise requests.exceptions.ConnectionError("down")

        client, _ = await make_client(FailingTransport(), raise_exceptions=False)
        assert await client.text("hello") is False

    @gen_test
    async def test_connection_errors_raise_when_asked_to(self):
        class FailingTransport(RecordingTransport):
            def __init__(self):
                super().__init__()
                self.first = True

            async def post(self, url, data=None):
                if self.first:  # construction has to succeed
                    self.first = False
                    return ""
                raise requests.exceptions.ConnectionError("down")

        client, _ = await make_client(FailingTransport(), raise_exceptions=True)
        with pytest.raises(ConnectionError):
            await client.text("hello")

    @gen_test
    async def test_ssl_errors_still_produce_the_certificate_hint(self):
        class SSLFailingTransport(RecordingTransport):
            def __init__(self):
                super().__init__()
                self.first = True

            async def post(self, url, data=None):
                if self.first:
                    self.first = False
                    return ""
                raise requests.exceptions.SSLError("bad cert")

        client, _ = await make_client(SSLFailingTransport(), raise_exceptions=True)
        with pytest.raises(ConnectionError, match="ssl_verify=False"):
            await client.text("hello")


class TestAsyncVisdomLifecycle(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_shutdown_closes_the_transport(self):
        client, transport = await make_client()
        await client.shutdown()
        assert transport.closed is True

    @gen_test
    async def test_shutdown_is_idempotent(self):
        client, transport = await make_client()
        await client.shutdown()
        await client.shutdown()
        assert transport.closed is True

    @gen_test
    async def test_shutdown_releases_the_worker_pool(self):
        """The pool is the client's, so shutting the client down must reclaim
        its threads rather than leave one pool per client alive."""
        client, _ = await make_client()
        await client.shutdown()
        with pytest.raises(RuntimeError):
            await client.text("hello")

    @gen_test
    async def test_cancelling_a_call_cancels_the_request_it_is_on(self):
        """``run_in_executor`` cannot interrupt a worker, so the cancel has to
        reach the POST itself.

        ``REQUEST_TIMEOUT`` is 0 -- deliberately, a slow upload is not a failure
        -- so a request nobody awaits any more would hold its worker forever.
        Once ``max_concurrency`` of them accumulate, every later call queues
        behind them and the client is wedged.
        """
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class HangingTransport(RecordingTransport):
            async def post(self, url, data=None):
                self.calls.append((url, data))
                if len(self.calls) == 1:  # let construction through
                    return ""
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        client, _ = await make_client(HangingTransport())
        task = asyncio.ensure_future(client.text("hello"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), timeout=5)

    @gen_test
    async def test_shutdown_waits_for_a_call_already_in_flight(self):
        """Closing the transport first would pull it out from under the POST.

        ``_AsyncTransport.close`` only drops the client and the ``transport``
        property rebuilds it, so an unfinished call would quietly reopen the
        HTTP client and keep talking to the server after ``shutdown`` returned.
        """
        release = asyncio.Event()
        finished = []

        class GatedTransport(RecordingTransport):
            async def post(self, url, data=None):
                self.calls.append((url, data))
                if len(self.calls) > 1:
                    await release.wait()
                    finished.append(url)
                return ""

        client, transport = await make_client(GatedTransport())
        call = asyncio.ensure_future(client.text("hello"))
        await asyncio.sleep(0)
        shutdown = asyncio.ensure_future(client.shutdown())
        await asyncio.sleep(0)
        assert transport.closed is False, "closed while a call was still running"
        release.set()
        await call
        await shutdown
        assert finished, "the in-flight call never completed"
        assert transport.closed is True

    @gen_test
    async def test_a_call_queued_behind_shutdown_never_reaches_the_wire(self):
        """``shutdown(wait=False)`` does not cancel what is already queued.

        With one worker, a second call is still sitting in the pool's queue when
        ``shutdown`` runs; without ``cancel_futures`` it starts afterwards and
        POSTs through a client the caller believes is released.
        """
        release = asyncio.Event()

        class GatedTransport(RecordingTransport):
            async def post(self, url, data=None):
                self.calls.append((url, data))
                if len(self.calls) > 1:
                    await release.wait()
                return ""

        client, transport = await make_client(GatedTransport(), max_concurrency=1)
        running = asyncio.ensure_future(client.text("first", win="w1"))
        await asyncio.sleep(0)
        queued = asyncio.ensure_future(client.text("second", win="w2"))
        await asyncio.sleep(0)

        shutdown = asyncio.ensure_future(client.shutdown())
        await asyncio.sleep(0)
        release.set()
        await running
        with pytest.raises((asyncio.CancelledError, RuntimeError)):
            await queued
        await shutdown

        # construction plus the one call that had already started
        assert len(transport.calls) == 2

    @gen_test
    async def test_context_manager_shuts_down_on_exit(self):
        client, transport = await make_client()
        async with client as entered:
            assert entered is client
        assert transport.closed is True


class TestBridgedVisdom(tornado.testing.AsyncTestCase):
    @gen_test
    async def test_transport_is_built_from_the_normalized_url_fields(self):
        """Built lazily off the instance, so it picks up the scheme/port/base
        url exactly as ``Visdom.__init__`` parsed them."""
        inner = await asyncio.to_thread(
            _BridgedVisdom,
            asyncio.get_running_loop(),
            transport=RecordingTransport(),
            server="localhost",
            port=9999,
            base_url="/proxy",
            use_incoming_socket=False,
        )
        inner._transport = None
        transport = inner.transport
        assert transport.server == "http://localhost"
        assert transport.port == 9999
        assert transport.base_url == "/proxy"

    @gen_test
    async def test_offline_clients_never_reach_the_transport(
        self,
    ):
        """Offline mode short-circuits inside ``_send``; the bridge must not
        change that."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".log") as log:
            transport = RecordingTransport()
            client = await AsyncVisdom.create(
                transport=transport, offline=True, log_to_filename=log.name
            )
            await client.text("hello", win="w1")
            assert transport.calls == []
