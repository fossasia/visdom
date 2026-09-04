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

Incoming-socket support (event handlers) is not part of this module yet;
``create()`` rejects ``use_incoming_socket``/``use_polling`` rather than
pretending to deliver events.
"""

import asyncio
import functools
import json
import logging
import ssl
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from tornado.httpclient import AsyncHTTPClient, HTTPClientError, HTTPRequest
from tornado.simple_httpclient import HTTPTimeoutError

from visdom import Visdom

logger = logging.getLogger(__name__)

# Mirrors the synchronous client's `timeout=(20, None)`: bound the connect,
# never the read, because a slow plot upload is not a failure.
CONNECT_TIMEOUT = 20.0
REQUEST_TIMEOUT = 0  # tornado reads 0 as "no timeout"

# How many plot calls may be in flight at once. It sizes the client's own
# thread pool and tornado's ``max_clients`` together, so a worker thread only
# ever exists for a request tornado is willing to start immediately; anything
# beyond that waits in the pool rather than in tornado's queue, where the
# connect timeout would already be ticking.
DEFAULT_MAX_CONCURRENCY = 10


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
        **kwargs,
    ):
        # Both are read by ``_handle_post``, which ``super().__init__`` reaches
        # through its opening ``_send``, so they have to exist first.
        self._aloop = loop
        self._transport = transport
        self._max_clients = max_clients
        super().__init__(*args, **kwargs)

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

    def _handle_post(self, url, data=None):
        """Hand the POST to the event loop and block this worker thread only.

        ``run_coroutine_threadsafe`` is what makes the bridge work: the loop
        keeps serving other requests while ``result()`` parks the thread that
        called a plot method.
        """
        self._last_post_time = time.time()
        future = asyncio.run_coroutine_threadsafe(
            self.transport.post(url, data), self._aloop
        )
        return future.result()

    def _start_session_reaper(self):
        """No-op: there is no ``requests`` session to reap."""

    def setup_socket(self, polling=False):
        raise NotImplementedError(
            "AsyncVisdom has no incoming socket yet; construct it with "
            "use_incoming_socket=False, or use the synchronous Visdom client "
            "if you need event handlers."
        )

    def setup_polling(self):
        self.setup_socket(polling=True)


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

    @classmethod
    async def create(cls, *args, max_concurrency=DEFAULT_MAX_CONCURRENCY, **kwargs):
        """Connect and return a ready client.

        Accepts every :class:`~visdom.Visdom` argument. ``use_incoming_socket``
        defaults to ``False`` here (the synchronous client defaults it to
        ``True``) because the backchannel is not implemented yet; asking for it
        explicitly raises rather than quietly dropping server events.
        """
        kwargs.setdefault("use_incoming_socket", False)
        if kwargs.get("use_incoming_socket") or kwargs.get("use_polling"):
            raise NotImplementedError(
                "AsyncVisdom cannot receive server events yet. Pass "
                "use_incoming_socket=False, or use the synchronous Visdom "
                "client if you need event handlers."
            )
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
        try:
            # ``Visdom.__init__`` POSTs, so it has to run off the loop that is
            # going to serve that POST.
            inner = await loop.run_in_executor(
                executor, functools.partial(_BridgedVisdom, loop, *args, **kwargs)
            )
        except BaseException:
            executor.shutdown(wait=False)
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
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._executor, functools.partial(bound, *args, **kwargs)
            )

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

    # -- Not available yet ----------------------------------------------------

    def register_event_handler(self, *args, **kwargs):
        raise NotImplementedError(
            "AsyncVisdom has no incoming socket yet, so no events arrive to "
            "handle. Use the synchronous Visdom client for event handlers."
        )

    def clear_event_handlers(self, *args, **kwargs):
        raise NotImplementedError(
            "AsyncVisdom has no incoming socket yet, so no events arrive to "
            "handle. Use the synchronous Visdom client for event handlers."
        )

    # -- Lifecycle ------------------------------------------------------------

    async def shutdown(self):
        """Release the HTTP client and the worker pool.

        The wrapper is unusable afterwards; calls made after it raise. Safe to
        call twice, which is what makes the context manager usable around code
        that also shuts down explicitly.
        """
        if self._inner._transport is not None:
            self._inner._transport.close()
        self._executor.shutdown(wait=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.shutdown()
        return False
