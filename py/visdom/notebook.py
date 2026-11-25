#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The ``%visdom`` line magic.

    %load_ext visdom.notebook
    %visdom --port 8097 --env run-7

Embeds a visdom dashboard in the output cell.

IPython is never imported here, and ``visdom/__init__.py`` does not import
this module, so ``import visdom`` costs what it always did.
"""

import argparse
import shlex
from urllib.parse import urlparse, urlunparse

from visdom import Visdom, _embed_size
from visdom.server.defaults import DEFAULT_PORT

DEFAULT_SERVER = "http://localhost"
DEFAULT_ENV = "main"
DEFAULT_HEIGHT = 600
DEFAULT_WIDTH = "100%"
# Not run_server's validator: that one sits behind a tornado import.
MAX_PORT = 65535
# requests' (connect, read) for this client's POSTs, in seconds.
CONNECT_TIMEOUT = 20
READ_TIMEOUT = 20

# (server, port, env) -> client, reused because a Visdom's session reaper
# lives as long as the process and holds its client.
_clients = {}


class _Parser(argparse.ArgumentParser):
    """Reports a bad flag to the caller instead of ending the kernel.

    argparse's own answer is ``SystemExit``, which reads as a crashed cell.
    """

    def error(self, message):
        raise ValueError("%visdom: {0}\n{1}".format(message, self.format_usage()))

    def exit(self, status=0, message=None):
        raise ValueError(message or "%visdom: could not parse the command line")


def _port(value):
    """A port from the command line.

    ``ArgumentTypeError`` because argparse replaces a ``ValueError`` with
    "invalid _port value", which names this function rather than the problem.
    """
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "port must be a number, got {0!r}".format(value)
        )
    if not 1 <= port <= MAX_PORT:
        raise argparse.ArgumentTypeError(
            "port must be between 1 and {0}, got {1}".format(MAX_PORT, port)
        )
    return port


def _as_number(text):
    """The number ``text`` spells, or ``None`` when it spells something else.

    ``int`` first so a whole number stays whole: ``show()`` renders a float
    as ``600.0px``, a length nobody typed.
    """
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


def _dimension(value):
    """An iframe dimension from the command line: a number is pixels, else CSS.

    Any number, not only a whole one: read as CSS, ``600.5`` reaches the
    browser as a length with no unit and is dropped rather than refused.

    Checked here, at parse time, by ``show()``'s own ``_embed_size``: the
    environment is registered between parsing and the embed, so a dimension
    only the embed refuses would create one on its way to the error.
    """
    text = value.strip()
    number = _as_number(text)
    dimension = value if number is None else number
    try:
        _embed_size(dimension)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None
    return dimension


def _normalize_server(server):
    """A server url as ``Visdom`` keeps it, and the port the url named.

    Returns ``(url, port)``, ``port`` being ``None`` unless the url carried
    one: the client builds every request as ``server:port/...``, so a port
    left in the url asks for ``http://localhost:8097:8097/env/main``.

    ``http://`` is filled in for a bare host only. Re-parsing any other
    scheme as a host reads ``htps://box`` as the host ``htps:``, turning a
    typo into an address nothing listens on.

    Anything after the host is refused rather than dropped: a dashboard under
    a proxy path is a different address, and framing the server root instead
    would show whatever else answers there.
    """
    text = server.strip()
    if "://" in text:
        parsed = urlparse(text)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                "%visdom: --server must be an http or https url, got {0!r}".format(
                    server
                )
            )
    else:
        parsed = urlparse("http://{0}".format(text))

    try:
        port = parsed.port
    except ValueError:
        # urlparse reads the port only when asked, and raises for both a
        # non-numeric one and one out of range.
        raise ValueError(
            "%visdom: --server does not name a usable port: {0!r}".format(server)
        ) from None
    if port is not None and not 1 <= port <= MAX_PORT:
        raise ValueError(
            "%visdom: --server names port {0}; it must be between 1 and {1}".format(
                port, MAX_PORT
            )
        )
    if not parsed.hostname:
        raise ValueError("%visdom: --server names no host: {0!r}".format(server))
    if parsed.path.strip("/") or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(
            "%visdom: --server is a scheme, a host and a port, with nothing "
            "after them, got {0!r}".format(server)
        )

    netloc = parsed.netloc
    if port is not None or netloc.endswith(":"):
        # rsplit: an IPv6 host and a 'user:password@host' keep their colons.
        netloc = netloc.rsplit(":", 1)[0]
    return urlunparse((parsed.scheme, netloc, "", "", "", "")), port


def _resolve_port(in_url, flag):
    """The port to talk to, from the one in ``--server`` and the one in ``--port``.

    Either spelling is fine, but a line that gives both has said two things,
    and picking one is how ``--port 9000`` ends up silently ignored.
    """
    if in_url is None:
        return DEFAULT_PORT if flag is None else flag
    if flag is not None and flag != in_url:
        raise ValueError(
            "%visdom: --server names port {0} and --port says {1}; "
            "give the port once".format(in_url, flag)
        )
    return in_url


def _build_parser():
    parser = _Parser(
        prog="%visdom",
        add_help=False,
        description="Embed a visdom dashboard in this notebook.",
    )
    parser.add_argument(
        "-h", "--help", action="store_true", help="print this message and stop"
    )
    # No default: 'the user did not say' is what tells a port given only in
    # --server apart from the two of them disagreeing.
    parser.add_argument(
        "--port",
        type=_port,
        default=None,
        help="server port, if it is not part of --server. Default {0}".format(
            DEFAULT_PORT
        ),
    )
    parser.add_argument(
        "--server", default=DEFAULT_SERVER, help="server url, with or without the port"
    )
    parser.add_argument(
        "--env", default=DEFAULT_ENV, help="environment to open in the frame"
    )
    parser.add_argument(
        "--height",
        type=_dimension,
        default=DEFAULT_HEIGHT,
        help="iframe height: a number is pixels, anything else is CSS",
    )
    parser.add_argument(
        "--width", type=_dimension, default=DEFAULT_WIDTH, help="iframe width"
    )
    return parser


class _NotebookClient(Visdom):
    """A client whose POSTs cannot hold the cell that ran them open forever.

    ``Visdom`` leaves the read half unbounded so a send can carry a video the
    server is still writing out. Registering an env is not that, and a cell
    has nothing to interrupt it.
    """

    post_timeout = (CONNECT_TIMEOUT, READ_TIMEOUT)


def _client_for(server, port, env):
    """The client for this address and environment, built once per kernel.

    Constructing it registers the environment, so the frame deep-links to one
    the dashboard knows. No incoming socket: this client only names the env.

    Cached to save the session reaper thread each ``Visdom`` starts, which a
    notebook re-running the same cell all day would otherwise leak. A client
    whose registration did not land is cached too -- the thread is there
    either way -- but is asked to register again, so a ``%visdom`` typed
    before the server was up does not frame a ``404`` for the session.
    """
    key = (server, port, env)
    client = _clients.get(key)
    if client is None:
        client = _NotebookClient(
            server=server,
            port=port,
            env=env,
            use_incoming_socket=False,
        )
        _clients[key] = client
    elif not client._env_registered:
        client._register_env(env)
    return client


def visdom_magic(line=""):
    """Embed a dashboard in the output cell. Registered as ``%visdom``.

    Returns the object ``Visdom.show`` returns, which the notebook renders as
    an iframe and anything else prints as the dashboard URL.
    """
    parser = _build_parser()
    args = parser.parse_args(shlex.split(line))
    if args.help:
        # Printed, not returned: a cell shows a returned string through its
        # repr, line breaks spelled '\n'.
        print(parser.format_help(), end="")
        return None

    server, port_in_url = _normalize_server(args.server)
    client = _client_for(server, _resolve_port(port_in_url, args.port), args.env)
    return client.show(height=args.height, width=args.width)


def load_ipython_extension(ipython):
    """Register ``%visdom``. IPython calls this for ``%load_ext``."""
    ipython.register_magic_function(visdom_magic, "line", "visdom")


def unload_ipython_extension(ipython):
    """Unregister ``%visdom``. IPython calls this for ``%unload_ext``.

    Only this extension's own entry: whoever took the name over since
    ``%load_ext`` keeps it.
    """
    manager = getattr(ipython, "magics_manager", None)
    if manager is None:
        return
    line_magics = manager.magics.get("line", {})
    if line_magics.get("visdom") is visdom_magic:
        del line_magics["visdom"]
