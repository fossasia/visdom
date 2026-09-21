#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""An asyncio-native front end for the visdom client.

``AsyncVisdom`` exposes the whole :class:`~visdom.Visdom` plotting surface as
coroutines without duplicating a single plot method. The 60-odd public methods
keep running as the synchronous code they already are, on a worker thread; only
the wire hop is asynchronous.

    vis = await AsyncVisdom.create(server="http://localhost", port=8097)
    await asyncio.gather(
        vis.line(Y=ys, win="a"),
        vis.line(Y=ys, win="b"),
    )
    await vis.shutdown()

The bridge is the reason this shape was chosen over rewriting the methods as
``async def``. Several of them (``scatter``, ``image``) need the *result* of a
mid-method ``win_exists`` preflight before they can build the rest of the
payload, and a synchronous body cannot await. Running the body on a worker
thread and awaiting only the POST keeps every plot method byte-for-byte
identical while the event loop stays free: the CPU-heavy encodes (PNG,
base64, ``savefig``) end up off the loop for free, and concurrency comes from
fanning several calls out with ``gather``.

Each client owns the thread pool those calls run on, rather than borrowing
asyncio's default executor. That is not tidiness: asyncio resolves hostnames on
the default executor, so plot calls parked there waiting on their POST can
starve the ``getaddrinfo`` that same POST is waiting for, and a ``gather`` wider
than the default pool deadlocks until every request hits its connect timeout.

The synchronous :class:`~visdom.Visdom` is untouched by this module; importing
it changes no behavior for existing users.

Transport is :class:`tornado.httpclient.AsyncHTTPClient`, which visdom already
depends on for the server, so this adds no dependency. Transport failures are
re-raised as the ``requests`` exceptions the inherited ``_send`` already knows
how to handle, so error semantics -- ``raise_exceptions``, the SSL hint, the
``return False`` fallback -- match the synchronous client exactly.

The backchannel that carries server events is asyncio too: a task on the
caller's loop reads a ``websocket_connect`` connection (or polls the HTTP
fallback) and feeds ``_handle_incoming_message``, the same seam the
synchronous client feeds. It is opt-in here: ``create()`` defaults
``use_incoming_socket`` to ``False``, unlike ``Visdom``.
"""

import asyncio
import functools
import inspect
import json
import logging
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from tornado.httpclient import AsyncHTTPClient, HTTPClientError, HTTPRequest
from tornado.simple_httpclient import HTTPTimeoutError
from tornado.websocket import websocket_connect

from visdom import Visdom

logger = logging.getLogger(__name__)

# Bound the connect and the request alike. This is deliberately stricter than
# the synchronous client's `timeout=(20, None)`: a read that never returns here
# holds one of only ``max_concurrency`` worker threads, so a wedged server
# costs the whole client rather than the single call that hit it.
CONNECT_TIMEOUT = 20.0
REQUEST_TIMEOUT = 20.0

# The backchannel handshake is exempt: the connection it opens is held for the
# life of the client, not for one request. tornado reads 0 as "no timeout".
SOCKET_REQUEST_TIMEOUT = 0

# How many plot calls may be in flight at once. It sizes the client's own
# thread pool and tornado's ``max_clients`` together, so a worker thread only
# ever exists for a request tornado is willing to start immediately; anything
# beyond that waits in the pool rather than in tornado's queue, where the
# connect timeout would already be ticking.
DEFAULT_MAX_CONCURRENCY = 10

# Backchannel timings, matching the synchronous client: the handshake budget
# ``Visdom.__init__`` waits out, its three-second reconnect gap, its poll
# interval. Pings have no counterpart -- the synchronous client sets a pong
# deadline but never pings, so a half-open connection sits there until the OS
# notices; tornado defaults the pong deadline to the interval.
HANDSHAKE_TIMEOUT = 5.0
RECONNECT_DELAY = 3.0
POLL_INTERVAL = 0.1
PING_INTERVAL = 30.0

# How long ``shutdown`` waits for a handler that was already running when the
# backchannel closed. A thread pool cannot interrupt a worker, so this is a
# backstop rather than a guarantee: past it the handler is assumed wedged and
# what it is waiting on is cancelled, rather than holding the caller forever.
DISPATCH_DRAIN_TIMEOUT = 5.0


class _AsyncTransport(object):
    """The one piece of the client that actually talks asyncio.

    Owns a private ``AsyncHTTPClient`` (``force_instance=True``, so closing it
    never touches the per-loop singleton other code may share) and the login
    cookie. Every method must be called on the event loop the client was
    created for.
    """

    def __init__(
        self,
        server,
        port,
        base_url="",
        username=None,
        password=None,
        ssl_verify=True,
        max_clients=DEFAULT_MAX_CONCURRENCY,
    ):
        self.server = server
        self.port = port
        self.base_url = base_url
        self.username = username
        # Already sha256-hashed by ``Visdom.__init__``; this is the value the
        # login route expects, so it is passed straight through.
        self.password = password
        self.ssl_verify = ssl_verify
        self.max_clients = max_clients
        self.cookie = None
        self._connected = False
        self._client = None
        self._login_lock = None

    # -- Plumbing -------------------------------------------------------------

    @property
    def client(self):
        """Lazily built, because an ``AsyncHTTPClient`` binds to its loop."""
        if self._client is None:
            self._client = AsyncHTTPClient(
                force_instance=True, max_clients=self.max_clients
            )
        return self._client

    def _request(self, url, body, headers=None):
        request_headers = {}
        if self.cookie:
            request_headers["Cookie"] = self.cookie
        if headers:
            request_headers.update(headers)
        kwargs = {
            "method": "POST",
            "body": body,
            "headers": request_headers,
            "connect_timeout": CONNECT_TIMEOUT,
            "request_timeout": REQUEST_TIMEOUT,
        }
        if isinstance(self.ssl_verify, str):
            kwargs["ca_certs"] = self.ssl_verify
        elif not self.ssl_verify:
            kwargs["validate_cert"] = False
        return HTTPRequest(url, **kwargs)

    def websocket_url(self):
        """``ws(s)://host:port<base_url>/vis_socket``, off the POST url."""
        parsed = urlparse(self.server)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return "{0}://{1}:{2}{3}/vis_socket".format(
            scheme, parsed.netloc, self.port, self.base_url
        )

    def websocket_request(self):
        """The handshake request, with the login cookie and TLS settings.

        Not built through ``_request``: the handshake is a GET, and its
        ``request_timeout`` has to stay off rather than follow
        ``REQUEST_TIMEOUT``. That bound exists to stop a wedged POST from
        holding a worker thread; this connection is meant to stay open for the
        life of the client, so tornado would tear a healthy socket down once
        the deadline passed.
        """
        headers = {}
        if self.cookie:
            headers["Cookie"] = self.cookie
        kwargs = {
            "headers": headers,
            "connect_timeout": CONNECT_TIMEOUT,
            "request_timeout": SOCKET_REQUEST_TIMEOUT,
        }
        if isinstance(self.ssl_verify, str):
            kwargs["ca_certs"] = self.ssl_verify
        elif not self.ssl_verify:
            kwargs["validate_cert"] = False
        return HTTPRequest(self.websocket_url(), **kwargs)

    async def _fetch(self, request):
        # ``raise_error=False`` suppresses only the HTTP status error, which is
        # what makes this match ``requests``: a 400 or a 403 comes back as a
        # body for the caller to read, exactly as ``r.text`` would. Connection
        # and TLS failures still raise.
        return await self.client.fetch(request, raise_error=False)

    async def _ensure_login(self):
        """POST the credentials once and keep the ``user_password`` cookie.

        The synchronous client does this while building its ``requests``
        session; there is no session here, so the cookie is cached on the
        transport instead.

        The sync client logs in through ``requests`` from inside ``_send``'s
        ``try``, so a server that is down fails there as a
        ``requests.ConnectionError`` and ``raise_exceptions`` still decides
        what the caller sees. Translating here keeps that contract: the login
        is the first thing a configured ``username`` touches, and a tornado
        error escaping it would bypass ``_send`` entirely.
        """
        if not self.username or self.cookie is not None:
            return
        if self._login_lock is None:
            self._login_lock = asyncio.Lock()
        async with self._login_lock:
            if self.cookie is not None:
                return
            url = "{0}:{1}{2}".format(self.server, self.port, self.base_url)
            request = self._request(
                url,
                json.dumps({"username": self.username, "password": self.password}),
                headers={"Content-Type": "application/json"},
            )
            try:
                response = await self._fetch(request)
            except (OSError, HTTPClientError) as e:
                raise _as_requests_error(e) from e
            if response.code != 200:
                raise RuntimeError("Authentication failed")
            logger.info("Authentication succeeded")
            self.cookie = _extract_cookie(response, "user_password")

    # -- Public surface -------------------------------------------------------

    async def post(self, url, data=None):
        """POST ``data`` to ``url`` and return the response body as text.

        Raises the ``requests`` exception the synchronous ``_send`` expects, so
        callers cannot tell which transport produced the failure.
        """
        await self._ensure_login()
        body = "" if data is None else data
        try:
            response = await self._fetch(self._request(url, body))
        except (OSError, HTTPClientError) as e:
            # The synchronous client only retries once a session has already
            # worked, so a server that is simply down still fails on the first
            # connect instead of costing two connect timeouts. A connection
            # that used to work and just got recycled is worth one retry.
            if isinstance(e, ssl.SSLError) or not self._connected:
                raise _as_requests_error(e) from e
            logger.warning("Connection failed, retrying...")
            try:
                response = await self._fetch(self._request(url, body))
            except (OSError, HTTPClientError) as retry_error:
                raise _as_requests_error(retry_error) from e
        self._connected = True
        return response.body.decode("utf-8") if response.body else ""

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None


def _extract_cookie(response, name):
    """Pull one cookie out of a response's ``Set-Cookie`` headers."""
    prefix = name + "="
    for header in response.headers.get_list("Set-Cookie"):
        for part in header.split(";"):
            part = part.strip()
            if part.startswith(prefix):
                return part
    return None


def _as_requests_error(error):
    """Translate a tornado/socket failure into its ``requests`` equivalent.

    ``Visdom._send`` catches ``requests`` exceptions by type, so a tornado
    error escaping this module would bypass ``raise_exceptions`` handling and
    surface as an unhandled traceback instead of the documented ``False``.
    """
    if isinstance(error, ssl.SSLError):
        return requests.exceptions.SSLError(str(error))
    if isinstance(error, (HTTPTimeoutError, TimeoutError)):
        return requests.exceptions.Timeout(str(error))
    return requests.exceptions.ConnectionError(str(error))


class _AsyncBackchannel(object):
    """Base for the two ways a client hears back from the server.

    Owns a task on the caller's loop that keeps one session alive and restarts
    it after a failure, as the synchronous client's socket thread does -- but
    only once a handshake has arrived: a session that ends before one did, for
    whatever reason, drops the client to socketless instead.
    Subclasses provide ``_session``, which returns when the connection is gone
    and raises when it could not be made.

    Messages go to ``_handle_incoming_message`` on a private single-thread
    executor: handlers are blocking functions written against the synchronous
    client, so the loop must not run them, and one thread keeps them in arrival
    order. The pool is its own because the plot pool can be fully parked on
    POSTs -- a ``max_concurrency=1`` client is parked for the whole time its
    constructor waits on this handshake.
    """

    name = "Socket"

    def __init__(self, client, loop, transport):
        self._client = client
        self._loop = loop
        self._transport = transport
        self._task = None
        self._closing = False
        self._dispatch_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="visdom-async-events"
        )
        # Submission and shutdown of that pool, paired. ``submit`` raises once
        # the pool is shut down, so the check and the submit have to be one
        # step -- and the shutdown itself has to see whatever the last submit
        # left behind, which is the handler :meth:`drain` waits on.
        self._dispatch_lock = threading.Lock()
        self._dispatch_closed = False
        self._dispatch_call = None

    def start(self):
        """Spawn the reader task. Must run on the event loop thread."""
        if self._task is None:
            self._task = self._loop.create_task(self._run())

    async def _run(self):
        while self._client.use_socket and not self._closing:
            error = None
            try:
                await self._session()
            except Exception as e:
                error = e
            finally:
                self._client.socket_alive = False
            if self._closing or not self._client.use_socket:
                break
            # Checked here, after every kind of ending, rather than in each
            # session: a rejected upgrade, a timed-out handshake or a failed
            # polling ``init`` would otherwise retry forever.
            if error is None:
                reason = (
                    "{0} closed before the handshake arrived (if login is "
                    "enabled, pass username/password to AsyncVisdom.create)"
                ).format(self.name)
            else:
                reason = "{0} failed before the handshake arrived: {1}".format(
                    self.name, error
                )
            if self._give_up_if_never_connected(reason):
                break
            if error is not None:
                logger.error("%s had error %s, attempting restart", self.name, error)
            await asyncio.sleep(RECONNECT_DELAY)

    async def _session(self):
        raise NotImplementedError

    async def _dispatch(self, raw_message, handshake):
        """Deliver one message, off the handshake clock.

        Until ``vis_alive`` arrives the session runs under
        ``HANDSHAKE_TIMEOUT``: an open connection is not a handshake, and a
        server that accepts one without ever sending ``vis_alive`` would
        otherwise hold the session forever, out of reach of both the retry loop
        and the socketless fallback.

        Handler code must not be spent out of that budget, though. The handlers
        are the caller's own and may take as long as they like; counted against
        the handshake, one slower than ``HANDSHAKE_TIMEOUT`` would tear down the
        very session that had just delivered ``vis_alive``. Polling made that
        worse, because it delivers a whole batch between two checks: a slow
        handler on an earlier message in the batch could bury the handshake that
        came behind it. So the deadline is lifted for the length of the
        delivery, and put back -- pushed out by however long the delivery took
        -- only if the message turned out not to be the handshake. Once it is,
        the connection is meant to last, and the deadline stays gone.
        """
        deadline = handshake.when()
        if deadline is None:
            await self._deliver(raw_message)
            return
        handshake.reschedule(None)
        started = self._loop.time()
        try:
            await self._deliver(raw_message)
        finally:
            if not self._client.socket_alive:
                handshake.reschedule(deadline + (self._loop.time() - started))

    async def _deliver(self, raw_message):
        """Run one message through ``_handle_incoming_message`` on the handler
        thread, and wait for it there rather than on the loop."""
        call = self._submit(raw_message)
        if call is not None:
            await asyncio.wrap_future(call, loop=self._loop)

    def _submit(self, raw_message):
        """Queue one message on the handler thread, or ``None`` once closed.

        Kept under the lock that :meth:`drain` takes: the pool is shut down in
        there, and a submit that had merely checked a flag beforehand could
        still land after it and raise ``cannot schedule new futures``.
        """
        with self._dispatch_lock:
            if self._dispatch_closed:
                return None
            call = self._dispatch_executor.submit(
                self._client._handle_incoming_message, raw_message
            )
            self._dispatch_call = call
            return call

    def _give_up_if_never_connected(self, reason):
        """Stop retrying a backchannel that never worked once: a server
        without the route, a proxy that refuses the upgrade, or a login this
        client cannot pass degrades to socketless instead of looping forever.
        One that did connect keeps retrying, so a server restart is survived."""
        if self._client.socket_connection_achieved:
            return False
        logger.warning("%s; running socketless", reason)
        self._client.use_socket = False
        return True

    def close(self):
        """Stop the backchannel. Idempotent, and safe to call on the loop.

        Only the half that cannot block: nothing new is read and nothing new is
        dispatched from here on. What is already running is settled by
        :meth:`drain`, which needs to await.
        """
        self._closing = True
        self._client.use_socket = False
        self._client.socket_alive = False
        if self._task is not None:
            self._task.cancel()

    async def drain(self):
        """Settle the reader task and the handler thread. Returns whether it
        managed to, within ``DISPATCH_DRAIN_TIMEOUT``.

        ``close`` stops the reader, but a thread pool cannot interrupt a worker:
        a handler already inside ``_handle_incoming_message`` runs to completion
        on its own thread regardless. Shutting the pool down ``wait=False`` and
        returning left that handler firing into a client the caller had been
        told was closed -- and, for a coroutine handler, worse: those finish by
        waiting on *this* loop, so one still running when the loop closes parks
        its thread forever, where the interpreter-exit join every
        ``ThreadPoolExecutor`` registers then hangs the process.

        So the wait happens here, while the loop is still turning to feed it.
        The reader task goes first; the handler it was last awaiting outlives
        its cancellation and is waited on separately.
        """
        task, self._task = self._task, None
        if task is not None:
            await asyncio.wait({task})
        with self._dispatch_lock:
            self._dispatch_closed = True
            call, self._dispatch_call = self._dispatch_call, None
        settled = True
        if call is not None and not call.done():
            waiter = asyncio.wrap_future(call, loop=self._loop)
            done, pending = await asyncio.wait({waiter}, timeout=DISPATCH_DRAIN_TIMEOUT)
            for unfinished in pending:
                unfinished.cancel()
            settled = bool(done)
            if not settled:
                logger.warning(
                    "%s handler did not finish within %ss of shutdown",
                    self.name,
                    DISPATCH_DRAIN_TIMEOUT,
                )
        self._dispatch_executor.shutdown(wait=False)
        return settled


class _AsyncWebSocket(_AsyncBackchannel):
    """The ``/vis_socket`` backchannel over ``websocket_connect``."""

    def __init__(self, client, loop, transport):
        super().__init__(client, loop, transport)
        self._connection = None

    async def _session(self):
        await self._transport._ensure_login()
        # One budget for the connect and the ``vis_alive`` after it. Bounded
        # here rather than by tornado's connect timeout, which a server that
        # accepts the connection and never upgrades never trips -- and which
        # stops counting at the upgrade, long before the handshake.
        async with asyncio.timeout(HANDSHAKE_TIMEOUT) as handshake:
            connection = await websocket_connect(
                self._transport.websocket_request(),
                ping_interval=PING_INTERVAL,
            )
            self._connection = connection
            try:
                while True:
                    message = await connection.read_message()
                    if message is None:
                        break
                    await self._dispatch(message, handshake)
            finally:
                self._connection = None
                connection.close()

    def close(self):
        # Before the cancel, so the read loop wakes with a ``None`` message
        # instead of being torn out of a live read.
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        super().close()


class _AsyncPolling(_AsyncBackchannel):
    """The ``/vis_socket_wrap`` backchannel, for deployments that cannot hold
    a websocket open. Same two-step protocol the synchronous client speaks --
    an ``init`` POST for a sid, then ``query`` POSTs -- but the wait between
    polls is an ``await`` rather than a parked thread."""

    name = "Polling"

    @property
    def _url(self):
        return "{0}:{1}{2}/vis_socket_wrap".format(
            self._transport.server, self._transport.port, self._transport.base_url
        )

    async def _post(self, payload):
        return json.loads(await self._transport.post(self._url, json.dumps(payload)))

    async def _session(self):
        # The same handshake budget as the websocket: a wrapper that answers
        # every query without ever queueing ``vis_alive`` is not connected.
        async with asyncio.timeout(HANDSHAKE_TIMEOUT) as handshake:
            response = await self._post({"message_type": "init"})
            sid = response["sid"]
            self._client.vis_sid = sid
            while self._client.use_socket and not self._closing:
                response = await self._post({"message_type": "query", "sid": sid})
                if not response.get("success"):
                    raise RuntimeError(
                        "polling query rejected: {0}".format(response.get("detail"))
                    )
                for message in response["messages"]:
                    await self._dispatch(message, handshake)
                await asyncio.sleep(POLL_INTERVAL)


class _Call(object):
    """One call's link to the POST it is currently parked on.

    ``run_in_executor`` cannot interrupt a worker thread, so cancelling the
    awaitable a proxy returned has to reach the request itself. The worker
    records the ``run_coroutine_threadsafe`` future here as it makes each POST;
    cancelling that future is what cancels the tornado fetch on the loop.

    The lock pairing the two sides lives here rather than on the client because
    the client is not always there to hold it: the opening POST belongs to a
    ``Visdom.__init__`` that has not returned yet, so a caller who cancels
    :meth:`AsyncVisdom.create` has nothing but this object to cancel through.
    """

    __slots__ = ("_lock", "_future", "_cancelled")

    def __init__(self):
        self._lock = threading.Lock()
        self._future = None
        self._cancelled = False

    def attach(self, future):
        """Worker: record the POST this call is now on.

        Returns True when the call was already cancelled, which means the
        cancel landed between the check and the submit: the loop had nothing to
        cancel when it ran, so this POST has to cancel itself.
        """
        with self._lock:
            self._future = future
            return self._cancelled

    def detach(self):
        """Worker: the POST settled, so there is nothing left to cancel."""
        with self._lock:
            self._future = None

    def cancel(self):
        """Loop: cancel the POST in flight, and any this call has not made yet.

        A ``Visdom`` method can POST more than once -- a preflight and then the
        plot -- so the flag outlives the individual request: whichever POST is
        in flight is cancelled now, and the next one is cancelled as it is
        created.
        """
        with self._lock:
            self._cancelled = True
            future = self._future
        if future is not None:
            future.cancel()


class _Construction(object):
    """Ownership of a half-built client while ``create`` can still be cancelled.

    ``create`` runs ``Visdom.__init__`` on a worker thread, and a cancelled
    ``create`` returns no object -- so the ``AsyncHTTPClient`` that the opening
    POST builds can end up owned by nobody: the caller has no wrapper to
    ``shutdown``, and the coroutine that would have released it is already
    unwinding. Releasing it at the moment of the cancel does not work either,
    because ``run_in_executor`` cannot interrupt the worker: the transport
    usually does not exist yet, and the worker goes on to build it afterwards.

    So both sides report in here, and whichever finds the other already
    finished does the releasing. Exactly one of them ever does.
    """

    __slots__ = ("_lock", "_inner", "_done", "_abandoned")

    def __init__(self):
        self._lock = threading.Lock()
        self._inner = None
        self._done = False
        self._abandoned = False

    def publish(self, inner):
        """Worker: the instance exists, even though it is not initialized yet."""
        with self._lock:
            self._inner = inner

    def finish(self):
        """Worker: construction is over. True when the release is the worker's."""
        with self._lock:
            self._done = True
            return self._abandoned

    def abandon(self):
        """Loop: ``create`` gave up.

        Returns the instance to release when the worker has already finished,
        and ``None`` when it has not -- the worker releases it in that case.
        """
        with self._lock:
            self._abandoned = True
            return self._inner if self._done else None


class _BridgedVisdom(Visdom):
    """A ``Visdom`` whose only asynchronous part is the POST.

    Constructed on a worker thread (``Visdom.__init__`` POSTs to ``/env/<eid>``
    before it returns, which cannot happen on the event loop), so every method
    inherited from ``Visdom`` runs unchanged.
    """

    def __init__(
        self,
        loop,
        *args,
        transport=None,
        max_clients=DEFAULT_MAX_CONCURRENCY,
        call=None,
        **kwargs,
    ):
        # Both are read by ``_handle_post``, which ``super().__init__`` reaches
        # through its opening ``_send``, so they have to exist first.
        self._aloop = loop
        self._transport = transport
        self._max_clients = max_clients
        # ``super().__init__`` calls ``setup_socket`` when asked for a
        # backchannel, so the attribute has to exist before it runs.
        self._backchannel = None

        # Which ``_Call`` the running worker thread belongs to, so the POST it
        # is about to make can be found and cancelled from the loop.
        self._calls = threading.local()
        # ``super().__init__`` POSTs, and ``create`` can be cancelled while it
        # is in flight. Binding that call first is what lets the cancel reach
        # the opening request, rather than leaving this worker parked on it
        # until ``REQUEST_TIMEOUT``.
        self._calls.current = call
        try:
            super().__init__(*args, **kwargs)
        finally:
            self._calls.current = None

    @property
    def transport(self):
        """Built on first use, from the URL fields ``Visdom`` normalized."""
        if self._transport is None:
            self._transport = _AsyncTransport(
                server=self.server,
                port=self.port,
                base_url=self.base_url,
                username=self.username,
                password=getattr(self, "password", None),
                ssl_verify=self.ssl_verify,
                max_clients=self._max_clients,
            )
        return self._transport

    def run_call(self, call, bound, args, kwargs):
        """Run one proxied method on this worker under ``call``.

        Binding the ``_Call`` to the thread is what lets ``_handle_post`` file
        each POST it makes under the awaitable the caller is holding.
        """
        self._calls.current = call
        try:
            return bound(*args, **kwargs)
        finally:
            self._calls.current = None

    def _handle_post(self, url, data=None):
        """Hand the POST to the event loop and block this worker thread only.

        ``run_coroutine_threadsafe`` is what makes the bridge work: the loop
        keeps serving other requests while ``result()`` parks the thread that
        called a plot method. The future is also what a cancellation travels
        down: a request nobody is waiting for any more would otherwise hold its
        worker -- and, once ``max_concurrency`` of them pile up, every later
        call -- until ``REQUEST_TIMEOUT`` finally expires.
        """
        self._last_post_time = time.time()
        call = getattr(self._calls, "current", None)
        future = asyncio.run_coroutine_threadsafe(
            self.transport.post(url, data), self._aloop
        )
        if call is not None and call.attach(future):
            future.cancel()
        try:
            return future.result()
        finally:
            if call is not None:
                call.detach()

    def _start_session_reaper(self):
        """No-op: there is no ``requests`` session to reap."""

    def setup_socket(self, polling=False):
        """Start the backchannel on the event loop instead of on a thread.

        ``Visdom.__init__`` calls this from the worker thread it is being
        constructed on, so the task has to be handed to the loop. The
        constructor then waits out its usual sleep loop for ``socket_alive``,
        which the loop is free to deliver.
        """
        backchannel = _AsyncPolling if polling else _AsyncWebSocket
        self._backchannel = backchannel(self, self._aloop, self.transport)
        self._aloop.call_soon_threadsafe(self._backchannel.start)

    def close_backchannel(self):
        """Stop the backchannel and hand it back for the caller to drain.

        The stop is synchronous, so no event can be delivered after this
        returns; settling the reader task and the handler thread needs an
        await, and is the caller's ``drain``.
        """
        backchannel, self._backchannel = self._backchannel, None
        if backchannel is not None:
            backchannel.close()
        return backchannel


# Every public ``Visdom`` method that reaches the wire or is otherwise safe to
# run on a worker thread. Kept explicit rather than derived by introspection so
# that a new method on ``Visdom`` cannot silently become part of the async API
# without someone deciding it should be. The socket entry points are
# deliberately absent -- see the overrides on ``AsyncVisdom`` below.
_PROXIED = frozenset(
    {
        "audio",
        "bar",
        "boxplot",
        "check_connection",
        "close",
        "compare_experiments",
        "confusion_matrix",
        "contour",
        "delete_env",
        "delete_envs",
        "dual_axis_lines",
        "embeddings",
        "experiment",
        "finish_experiment",
        "fork_env",
        "get_env_list",
        "get_env_state",
        "get_tags",
        "get_window_data",
        "graph",
        "heatmap",
        "histogram",
        "histogram2d",
        "hparams",
        "html_table",
        "image",
        "image_heatmap",
        "image_select",
        "images",
        "learning_curve",
        "line",
        "log_metrics",
        "matplot",
        "mesh",
        "parallel_coordinates",
        "pie",
        "plotlyplot",
        "pr_curve",
        "properties",
        "quiver",
        "replay_log",
        "roc_curve",
        "sankey",
        "save",
        "save_plotly_figure",
        "scatter",
        "search_experiments",
        "set_tags",
        "set_window_data",
        "stem",
        "suggest_experiment",
        "sunburst",
        "surf",
        "svg",
        "table",
        "text",
        "update_hparams",
        "update_image_slider",
        "update_window_opts",
        "video",
        "violin",
        "win_exists",
    }
)


class AsyncVisdom(object):
    """Awaitable wrapper around a :class:`~visdom.Visdom` client.

    Build one with :meth:`create` -- ``__init__`` cannot await, and connecting
    means a POST. Every plotting method of the synchronous client is available
    as a coroutine with the same signature, the same arguments and the same
    return value::

        vis = await AsyncVisdom.create()
        win = await vis.line(Y=[1, 2, 3])
        await vis.shutdown()

    Note that :meth:`close` is ``Visdom.close`` -- it closes a *window*. The
    method that releases the transport is :meth:`shutdown`, also reachable by
    using the client as an async context manager.

    Concurrency comes from the caller: ``asyncio.gather`` of several calls runs
    them on separate worker threads against one shared inner client. That
    shared client is no more thread-safe than the synchronous one, so
    concurrent calls should target distinct windows.
    """

    def __init__(self, inner, executor):
        """Private -- use :meth:`create`."""
        self._inner = inner
        self._executor = executor
        self._closed = False
        # Calls handed to the pool and not yet settled. :meth:`shutdown` waits
        # on these before closing the transport out from under them.
        self._pending = set()
        # The single release of the transport, once :meth:`shutdown` has begun.
        # Held on the instance so that a caller who cancels its ``shutdown``
        # does not take the cleanup down with it.
        self._finalizer = None
        # Coroutine handlers currently parked on this loop, held by the thread
        # that bridged them. Shutdown cancels any that outlast the drain --
        # that thread cannot be interrupted, and what it waits on is about to
        # stop running.
        self._handler_calls = set()

    @classmethod
    async def create(cls, *args, max_concurrency=DEFAULT_MAX_CONCURRENCY, **kwargs):
        """Connect and return a ready client.

        Accepts every :class:`~visdom.Visdom` argument. ``use_incoming_socket``
        defaults to ``False`` here, where the synchronous client defaults it to
        ``True``: most async callers are after throughput and never register a
        handler, and a backchannel costs a held-open connection plus a thread
        to run handlers on. Pass ``use_incoming_socket=True`` for the
        websocket, or ``use_polling=True`` for the HTTP fallback, and the
        client will wait for the handshake exactly as the synchronous one
        does.

        ``use_preflight_checks`` defaults to ``False`` here as well. The
        synchronous client keeps it on so that nobody's wire traffic changes
        under them, but an async client is new code talking to a server that
        understands ``layout_create``, and halving the round trips per append
        is the point of using it. Pass ``use_preflight_checks=True`` to get the
        old two-POST behavior back against an older server.

        Cancelling the ``create`` itself is safe: the opening POST is cancelled
        with it, and whatever it managed to build is released rather than left
        holding a connection no caller can ever reach.
        """
        kwargs.setdefault("use_incoming_socket", False)
        kwargs.setdefault("use_preflight_checks", False)
        if (
            kwargs.get("proxies")
            or kwargs.get("http_proxy_host")
            or kwargs.get("http_proxy_port")
        ):
            raise NotImplementedError(
                "AsyncVisdom does not support HTTP proxies; tornado's "
                "AsyncHTTPClient has no proxy support without pycurl."
            )
        loop = asyncio.get_running_loop()
        # A private pool, not ``asyncio.to_thread``. The default executor is
        # also where asyncio resolves hostnames, so plot calls parked there
        # waiting on their POST can starve the very ``getaddrinfo`` those POSTs
        # need: gather more calls than the default pool has threads and every
        # request hangs until its connect timeout. Owning the pool also bounds
        # concurrency at ``max_concurrency``, which is what keeps requests out
        # of tornado's queue.
        executor = ThreadPoolExecutor(
            max_workers=max_concurrency, thread_name_prefix="visdom-async-client"
        )
        kwargs.setdefault("max_clients", max_concurrency)
        # ``Visdom.__init__`` POSTs, so the bridge is built on a worker. That
        # POST creates the private ``AsyncHTTPClient``, so a failure after it --
        # a bad login, a rejected env -- leaves a live transport attached to an
        # object the caller never receives and so can never shut down. Publishing
        # the half-built instance is what makes it reachable here.
        #
        # A cancel is the same leak arriving early. ``wait_for``, a task group
        # unwinding, a plain ``task.cancel()``: all of them resume this
        # coroutine while ``build`` is still inside the opening POST, and
        # ``run_in_executor`` cannot interrupt a worker that has started.
        # Releasing here and walking away would release nothing -- the
        # transport usually does not exist yet -- and the worker would go on to
        # build one for an object nobody holds. So ``_Construction`` hands the
        # release to whichever side finishes last, and ``call`` carries the
        # cancel down to the POST itself so the worker stops on the next loop
        # tick rather than at ``REQUEST_TIMEOUT``.
        call = _Call()
        state = _Construction()

        def release(inner):
            """Release a client the caller will never see. Runs on the loop."""
            transport = None if inner is None else getattr(inner, "_transport", None)
            if transport is not None:
                transport.close()
            executor.shutdown(wait=False)

        def build():
            inner = _BridgedVisdom.__new__(_BridgedVisdom)
            state.publish(inner)
            try:
                inner.__init__(loop, *args, call=call, **kwargs)
            finally:
                if state.finish():
                    # Nobody is waiting for this any more, so releasing it is
                    # this thread's job -- on the loop, which is the only
                    # thread allowed to close the HTTP client.
                    try:
                        loop.call_soon_threadsafe(release, inner)
                    except RuntimeError:
                        # The loop is closed, and its HTTP client with it.
                        executor.shutdown(wait=False)
            return inner

        work = executor.submit(build)
        try:
            inner = await asyncio.wrap_future(work, loop=loop)
        except BaseException:
            call.cancel()
            if work.cancel():
                # ``build`` never started and never will, so there is no worker
                # to hand the release to and nothing was built.
                release(None)
            else:
                abandoned = state.abandon()
                if abandoned is not None:
                    # The worker finished first; it left the release to us.
                    release(abandoned)
            raise
        return cls(inner, executor)

    # -- Proxying -------------------------------------------------------------

    def __getattr__(self, name):
        # Private names are rejected before ``self._inner`` is touched: during
        # construction (or unpickling) ``_inner`` does not exist yet, and
        # looking it up here would recurse forever.
        if name.startswith("_") or name not in _PROXIED:
            raise AttributeError(
                "{0!r} object has no attribute {1!r}".format(type(self).__name__, name)
            )
        bound = getattr(self._inner, name)

        @functools.wraps(bound)
        async def proxy(*args, **kwargs):
            if self._closed:
                raise RuntimeError(
                    "AsyncVisdom is shut down; its transport and worker pool "
                    "are released. Create a new client with AsyncVisdom.create()."
                )
            loop = asyncio.get_running_loop()
            call = _Call()
            future = loop.run_in_executor(
                self._executor,
                functools.partial(self._inner.run_call, call, bound, args, kwargs),
            )
            self._pending.add(future)
            future.add_done_callback(self._pending.discard)
            try:
                return await future
            except asyncio.CancelledError:
                # Cancelling ``future`` cannot stop a worker that has already
                # started, so reach past it to the POST the worker is parked on.
                call.cancel()
                raise

        return proxy

    def __dir__(self):
        return sorted(set(super().__dir__()) | _PROXIED)

    # -- Passthrough state ----------------------------------------------------

    @property
    def client(self):
        """The wrapped synchronous client, for anything not proxied."""
        return self._inner

    @property
    def env(self):
        return self._inner.env

    @env.setter
    def env(self, value):
        self._inner.env = value

    @property
    def env_list(self):
        return self._inner.env_list

    @property
    def win_data(self):
        return self._inner.win_data

    @property
    def offline(self):
        return self._inner.offline

    @property
    def socket_alive(self):
        """Whether the backchannel is connected and past its handshake."""
        return self._inner.socket_alive

    @property
    def use_socket(self):
        """Whether a backchannel was asked for and has not given up."""
        return self._inner.use_socket

    # -- Events ---------------------------------------------------------------

    def register_event_handler(self, handler, target, env=None):
        """Register ``handler`` for events on ``target``.

        Not a coroutine: registration is bookkeeping, and awaiting it would
        only suggest it reaches the server. ``handler`` may be a plain function
        or a coroutine function; a coroutine runs on this client's loop, so it
        can await other calls on this same client.

        Handlers run one at a time, in arrival order, on a thread of the
        client's own -- a slow one delays later events but nothing else.
        """
        assert callable(handler), "Event handler must be a function"
        if inspect.iscoroutinefunction(handler):
            handler = self._as_blocking_handler(handler)
        self._inner.register_event_handler(handler, target, env=env)

    def clear_event_handlers(self, target, env=None):
        self._inner.clear_event_handlers(target, env=env)

    def _as_blocking_handler(self, handler):
        """Run a coroutine handler on the loop, from the dispatch thread.

        Blocking that thread is the point: it keeps events in order while the
        loop stays free to run the coroutine.
        """
        loop = self._inner._aloop

        @functools.wraps(handler)
        def run(message):
            call = asyncio.run_coroutine_threadsafe(handler(message), loop)
            self._handler_calls.add(call)
            try:
                return call.result()
            finally:
                self._handler_calls.discard(call)

        return run

    # -- Lifecycle ------------------------------------------------------------

    async def shutdown(self):
        """Release the HTTP client and the worker pool.

        The wrapper is unusable afterwards; calls made after it raise. Safe to
        call twice, which is what makes the context manager usable around code
        that also shuts down explicitly.

        Order matters. ``ThreadPoolExecutor.shutdown(wait=False)`` does not
        cancel what is already queued, and ``_AsyncTransport.close`` only drops
        the client -- the ``transport`` property rebuilds it on next use. Closing
        first therefore let a call submitted a moment earlier start afterwards,
        reopen the HTTP client and POST through a wrapper the caller believes is
        already shut down. So: refuse new calls, drop the ones that never
        started, let the ones that did settle, and only then close.

        Waiting for those calls is a suspension point, which makes this
        cancellable at exactly the wrong moment. The release therefore runs as
        its own task and is awaited through :func:`asyncio.shield`: a caller who
        gives up -- or is cancelled by the ``wait_for`` or task group it sits in
        -- stops waiting without stopping the cleanup, and a later ``shutdown``
        awaits that same task rather than returning early on a ``_closed`` flag
        whose work never finished.
        """
        if self._finalizer is None:
            # Set before the first await, so no call slips in behind it.
            self._closed = True
            # Nothing new is accepted from here, in either direction: the
            # backchannel stops delivering events, the pool stops taking calls.
            self._executor.shutdown(wait=False, cancel_futures=True)
            # Closed here rather than in ``_release`` so that the backchannel is
            # already shut before the loop is given back, leaving no turn in
            # which one more event could still be delivered.
            self._finalizer = asyncio.ensure_future(
                self._release(self._inner.close_backchannel())
            )
        await asyncio.shield(self._finalizer)

    async def _release(self, backchannel):
        """Let the backchannel and the started calls settle, then close."""
        if backchannel is not None:
            # Awaited rather than merely stopped, so no task is left pending at
            # loop close and no handler is still running when this returns.
            if not await backchannel.drain():
                # A handler outlasted the drain. If it is a coroutine one it is
                # parked on this loop, which is about to be handed back, and
                # nothing would ever wake its thread again; cancelling is what
                # lets that thread unwind instead of being joined at exit.
                for call in tuple(self._handler_calls):
                    call.cancel()
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
        if self._inner._transport is not None:
            self._inner._transport.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.shutdown()
        return False
