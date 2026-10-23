#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Contain the basic web request handlers that all other handlers derive from
"""

import json
import logging
import traceback
import http.client
import time

import tornado.web
import tornado.websocket

from visdom.server.server_state import StateAccessorsMixin
from visdom.server.workspace_manager import WorkspaceAuthError
from visdom.utils.shared_utils import NanSafeEncoder

# POST endpoints that mutate environment state; viewers are denied these.
WRITE_ENDPOINTS = {
    "events",
    "update",
    "close",
    "delete_env",
    "save",
    "fork_env",
    "upload_env",
}

FILL_ENDPOINTS = (WRITE_ENDPOINTS - {"close", "delete_env"}) | {"log"}


def build_cloud_context(slug, role):
    """Serialise the console context for the index template, or None when not in a workspace."""
    if not slug:
        return None
    payload = json.dumps({"slug": slug, "role": role})
    return payload.replace("</", "<\\/")


class WorkspaceScopedMixin:
    """Shared workspace resolution and state-binding for HTTP and socket handlers.

    ``resolve_workspace`` maps the request's X-Visdom-Workspace header plus its
    credential (the X-API-KEY header on the write path, or the ``session_token``
    cookie on the browser read path) to (workspace_id, role) via the gateway.

    ``bind_workspace`` then swaps the handler's ``server_state`` for that
    workspace's own one. Every accessor a handler reads through resolves against
    whichever state is bound, so the handler bodies need to know nothing about
    workspaces. Returns None (no binding) for ordinary keyless or local traffic,
    which leaves the server's own state in place.
    """

    workspace_id = None
    workspace_slug = None
    workspace_role = None

    @property
    def readonly(self):
        return self.workspace_role == "viewer" or super().readonly

    @property
    def workspace_manager(self):
        """The gateway resolver, carried on the state every handler is given.

        Passing it as a handler argument instead would mean every handler that
        overrides ``initialize`` with its own signature had to accept it.
        """
        return getattr(self._bound_state, "workspace_manager", None)

    @property
    def workspace_env_manager(self):
        return getattr(self._bound_state, "workspace_env_manager", None)

    @property
    def _bound_state(self):
        """The state this handler was given, if it was given one at all.

        A handler registered without one, such as the health endpoint, has no
        state to scope and no managers to find; it must not raise on the way to
        discovering that.
        """
        return getattr(self, "server_state", None)

    def resolve_workspace(self):
        asked = self._workspace_credential()
        if asked is None:
            return None
        method, credential, workspace_slug = asked
        return getattr(self.workspace_manager, method)(credential, workspace_slug)

    async def resolve_workspace_off_loop(self):
        asked = self._workspace_credential()
        if asked is None:
            return None
        return await self.workspace_manager.resolve_off_loop(*asked)

    def _workspace_credential(self):
        if self.workspace_manager is None:
            return None
        # Socket test doubles stand in a bare object for the request, and a
        # connection with no headers carries no workspace to resolve either way.
        headers = getattr(getattr(self, "request", None), "headers", None)
        if headers is None:
            return None
        workspace_slug = headers.get("X-Visdom-Workspace")
        if not workspace_slug:
            return None
        api_key = headers.get("X-API-KEY")
        session_token = self.get_cookie("session_token")
        if api_key:
            return "resolve", api_key, workspace_slug
        if session_token:
            return "resolve_session", session_token, workspace_slug
        raise WorkspaceAuthError(401, "Sign in to use this workspace.")

    def storage_refusal(self):
        if self.workspace_id is None or self.workspace_manager is None:
            return None
        return self.workspace_manager.storage_refusal(self.workspace_id)

    def bind_workspace(self, workspace_id, slug=None):
        self.workspace_id = workspace_id
        if self.workspace_env_manager is None:
            return
        if slug is None:
            # Socket test doubles have no request, hence the guard rather than
            # a direct attribute read.
            request = getattr(self, "request", None)
            if request is not None:
                slug = request.headers.get("X-Visdom-Workspace")
        self.server_state = self.workspace_env_manager.space(workspace_id, slug=slug)


class BaseWebSocketHandler(
    WorkspaceScopedMixin, StateAccessorsMixin, tornado.websocket.WebSocketHandler
):
    """
    Implements any required overriden functionality from the basic tornado
    websocket handler. Also contains some shared logic for all WebSocketHandler
    classes.
    """

    def initialize(self, server_state=None):
        """Common initialization shared by WebSocket handlers."""
        self.server_state = server_state

    def get_current_user(self):
        """
        This method determines the self.current_user
        based the value of cookies that set in POST method
        at IndexHandler by self.set_secure_cookie
        """
        app = getattr(self, "application", None)
        if not app or not app.settings.get("cookie_secret"):
            return None
        return self.get_secure_cookie("user_password")

    async def get(self, *args, **kwargs):
        try:
            await self.resolve_workspace_off_loop()
        except WorkspaceAuthError:
            pass
        return await super().get(*args, **kwargs)


class BaseHandler(
    WorkspaceScopedMixin, StateAccessorsMixin, tornado.web.RequestHandler
):
    """
    Implements any required overriden functionality from the basic tornado
    request handlers, and contains any convenient shared logic helpers.
    """

    def initialize(self, server_state=None):
        """Common initialization shared by most handlers.

        Stores the shared ``ServerState`` facade; the ``StateAccessorsMixin``
        exposes its fields as ``self.state``, ``self.env_path``, etc.
        Subclasses that need additional attributes should call
        ``super().initialize(server_state)`` and then set their own.

        The ``server_state`` parameter defaults to ``None`` so that handlers
        registered without initialization arguments (e.g. HealthHandler) still work;
        such handlers simply never touch the state accessors.
        """
        self.server_state = server_state

    def write_json(self, payload):
        """Answer with ``payload`` as a JSON body, typed and inert.

        ``self.write(a_dict)`` would already do this, but the endpoints that
        echo experiment data serialize through :class:`NanSafeEncoder` first,
        so a NaN metric reaches the client as ``null`` rather than as the
        ``NaN`` literal no JSON parser accepts. Handing the resulting *string*
        back to ``write`` would leave Tornado's default ``text/html`` on a body
        that repeats the caller's own query verbatim, which a browser is then
        free to render as a page — so the type is declared, ``nosniff`` stops
        it being guessed back to HTML, and the three characters that could open
        a tag are written as JSON escapes, which decode to the same string.
        """
        body = (
            json.dumps(payload, cls=NanSafeEncoder)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.finish(body)

    def render(self, template_name, **kwargs):
        kwargs.setdefault(
            "cloud_context",
            build_cloud_context(self.workspace_slug, self.workspace_role),
        )
        return super().render(template_name, **kwargs)

    def write_text(self, body):
        """Answer with ``body`` as a plain-text body, typed and inert.

        The routes that answer with a bare identifier -- ``/update`` returns
        the window it updated, which the Python client hands back as the return
        value of ``vis.line()`` -- cannot wrap it in JSON without changing what
        every existing client reads off the wire. So the bytes stay exactly as
        they were and only the type is fixed: ``self.write(a_str)`` leaves
        Tornado's default ``text/html`` on a body that repeats an identifier
        the caller chose, which a browser is free to render as a page, and
        ``nosniff`` stops the declared type being guessed back to HTML.
        """
        self.set_header("Content-Type", "text/plain; charset=UTF-8")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.finish(body)

    def is_authorized(self):
        """Update access time and validate authentication for protected methods."""
        self.last_access = time.time()
        if self.login_enabled and not self.current_user:
            self.set_status(401)
            return False
        return True

    def __init__(self, *request, **kwargs):
        self.include_host = False
        super(BaseHandler, self).__init__(*request, **kwargs)

    async def prepare(self):
        """Bind a workspace-authenticated request to its workspace's state slice.

        Engages only when the request carries the X-Visdom-Workspace header (set
        by the python client on the write path, or injected by nginx from the
        ``/vis/w/<slug>/`` path on the browser read path), so ordinary visdom
        traffic (health checks, keyless clients) is unaffected. Authenticates via
        either the X-API-KEY header (write path) or the ``session_token`` cookie
        (browser read path), denies writes for the viewer role, denies new data
        while the gateway says the workspace is out of storage, and re-points this
        handler's state/storage/subs/sources at that workspace's isolated space so
        all subsequent handler logic operates on that workspace's environments.
        """
        try:
            resolved = await self.resolve_workspace_off_loop()
        except WorkspaceAuthError as exc:
            self.set_status(exc.status_code)
            self.finish({"error": exc.message})
            return
        if resolved is None:
            return

        workspace_id, role = resolved
        self.workspace_slug = self.request.headers.get("X-Visdom-Workspace")
        self.workspace_role = role
        if role == "viewer" and self._writes():
            self.set_status(403)
            self.finish({"error": "Your role is read-only in this workspace."})
            return
        refusal = self.workspace_manager.storage_refusal(workspace_id)
        if refusal and self._writes(FILL_ENDPOINTS):
            self.set_status(402)
            self.finish({"error": refusal})
            return

        self.bind_workspace(workspace_id)

    def _writes(self, endpoints=WRITE_ENDPOINTS):
        endpoint = self.request.path.rstrip("/").rsplit("/", 1)[-1]
        return (
            self.request.method == "POST"
            and not self.path_args
            and endpoint in endpoints
        )

    def get_current_user(self):
        """
        This method determines the self.current_user
        based the value of cookies that set in POST method
        at IndexHandler by self.set_secure_cookie
        """
        app = getattr(self, "application", None)
        if not app or not app.settings.get("cookie_secret"):
            return None
        return self.get_secure_cookie("user_password")

    def write_error(self, status_code, **kwargs):
        logging.error("ERROR: %s: %s" % (status_code, kwargs))
        if "exc_info" in kwargs:
            logging.info(
                "Traceback: {}".format(traceback.format_exception(*kwargs["exc_info"]))
            )
            show_details = self.settings.get("show_error_details", False)
            title = http.client.responses.get(status_code, "Unknown Error")
            logging.error("rendering error page")
            exc_info = kwargs["exc_info"]
            # exc_info is a tuple consisting of:
            # 1. The class of the Exception
            # 2. The actual Exception that was thrown
            # 3. The traceback object
            try:
                params = {
                    "error": exc_info[1] if show_details else None,
                    "trace_info": (
                        traceback.format_exception(*exc_info) if show_details else None
                    ),
                    "request": self.request.__dict__ if show_details else None,
                    "status_code": status_code,
                    "title": title,
                }
                self.render("error.html", **params)
                logging.error("rendering complete")
                return
            except Exception as e:
                logging.error(e)
            self.set_status(status_code)
            self.write(
                f"""
                <h1>{status_code} - {title}</h1>
                """
            )
