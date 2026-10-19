#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Resolves a caller plus workspace slug to a workspace id and the caller's role by
calling the visdom-cloud gateway, with a short-lived in-process cache so repeated
requests from the same caller do not hit the gateway each time. Two callers: the
write path (programmatic API key) and the browser read path (session token).

The gateway call itself is synchronous. Handlers answer a cache hit on the event
loop and send a miss through ``resolve_off_loop``, which runs the call on a small
thread pool, so a slow or unreachable gateway delays only the requests waiting on
it. Failures are cached so an unreachable gateway is asked once per
error_cache_ttl rather than on every request.
"""

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests


class WorkspaceAuthError(Exception):
    """Raised when the gateway declines or cannot service a resolve request."""

    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


MAX_ERROR_ENTRIES = 1024
MAX_CACHE_ENTRIES = 4096
RESOLVE_THREADS = 4
UNAVAILABLE = "Workspace sign-in is unavailable right now. Try again shortly."

_KINDS = {"resolve": "key", "resolve_session": "session"}


class WorkspaceManager:
    def __init__(
        self, gateway_url=None, cache_ttl=45.0, timeout=1.0, error_cache_ttl=5.0
    ):
        self.gateway_url = (
            gateway_url or os.environ.get("VISDOM_GATEWAY_URL", "http://localhost:8085")
        ).rstrip("/")
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.error_cache_ttl = error_cache_ttl
        self._cache = {}
        self._errors = {}
        self._full = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=RESOLVE_THREADS, thread_name_prefix="workspace-resolve"
        )

    def resolve(self, api_key, workspace_slug):
        """Write path: resolve an API key + slug to (workspace_id, role)."""
        return self._resolve_cached(
            ("key", api_key, workspace_slug),
            "resolve",
            {"X-API-KEY": api_key},
            workspace_slug,
        )

    def resolve_session(self, session_token, workspace_slug):
        """Browser read path: resolve a session token + slug to (workspace_id, role)."""
        return self._resolve_cached(
            ("session", session_token, workspace_slug),
            "resolve-session",
            {"Authorization": f"Bearer {session_token}"},
            workspace_slug,
        )

    async def resolve_off_loop(self, method, credential, workspace_slug):
        """Resolve as ``method`` would, without blocking the loop on a cache miss."""
        found = self._cached((_KINDS[method], credential, workspace_slug), time.time())
        if found is not None:
            return found
        return await asyncio.get_running_loop().run_in_executor(
            self._pool, getattr(self, method), credential, workspace_slug
        )

    def _cached(self, cache_key, now):
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and cached[2] > now:
                return cached[0], cached[1]
            failure = self._errors.get(cache_key)
            if failure is not None and failure[2] > now:
                raise WorkspaceAuthError(failure[0], failure[1])
        return None

    def _resolve_cached(self, cache_key, endpoint, headers, workspace_slug):
        now = time.time()
        found = self._cached(cache_key, now)
        if found is not None:
            return found

        try:
            workspace_id, role = self._fetch(endpoint, headers, workspace_slug)
        except WorkspaceAuthError as exc:
            self._remember_failure(cache_key, exc, now)
            raise

        with self._lock:
            self._errors.pop(cache_key, None)
            self._cache = _make_room(self._cache, MAX_CACHE_ENTRIES, now)
            self._cache[cache_key] = (workspace_id, role, now + self.cache_ttl)
        return workspace_id, role

    def _remember_failure(self, cache_key, exc, now):
        with self._lock:
            self._errors = _make_room(self._errors, MAX_ERROR_ENTRIES, now)
            self._errors[cache_key] = (
                exc.status_code,
                exc.message,
                now + self.error_cache_ttl,
            )

    def storage_refusal(self, workspace_id):
        with self._lock:
            return self._full.get(workspace_id)

    def _note_storage(self, workspace_id, refusal):
        with self._lock:
            if _filled(refusal):
                self._full[workspace_id] = refusal
            else:
                self._full.pop(workspace_id, None)

    def _fetch(self, endpoint, headers, workspace_slug):
        url = f"{self.gateway_url}/api/v1/visdom/{endpoint}"
        try:
            resp = requests.post(
                url,
                headers=headers,
                json={"workspace_slug": workspace_slug},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logging.warning("workspace resolve unavailable: %s", exc)
            raise WorkspaceAuthError(503, UNAVAILABLE)

        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                data = None
            if (
                isinstance(data, dict)
                and _filled(data.get("workspace_id"))
                and _filled(data.get("role"))
            ):
                self._note_storage(data["workspace_id"], data.get("storage_full"))
                return data["workspace_id"], data["role"]
            raise WorkspaceAuthError(502, "workspace resolve gave an unreadable answer")

        detail = "workspace resolution denied"
        try:
            data = resp.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("detail"), str):
            detail = data["detail"]
        raise WorkspaceAuthError(resp.status_code, detail)


def _filled(value):
    return isinstance(value, str) and value != ""


def _make_room(entries, limit, now):
    if len(entries) < limit:
        return entries
    entries = {key: value for key, value in entries.items() if value[2] > now}
    while len(entries) >= limit:
        entries.pop(next(iter(entries)))
    return entries
