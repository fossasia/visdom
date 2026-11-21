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

IPython is never imported here: ``load_ipython_extension`` is handed the shell
to register against, and the magic returns the same ``_repr_html_`` object
``Visdom.show`` does. ``visdom/__init__.py`` does not import this module, so
the import cost of ``import visdom`` is unchanged.
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
# run_server's own port validator sits behind a tornado import, which %load_ext
# should not pay for.
MAX_PORT = 65535
# requests' (connect, read) for this client's POSTs, in seconds.
CONNECT_TIMEOUT = 20
READ_TIMEOUT = 20

# Clients this kernel built, as (server, port, env) -> client. Reused
# because a Visdom's session reaper lives as long as the process and holds its
# client, so a client per cell execution is a thread per cell execution.
_clients = {}


class _Parser(argparse.ArgumentParser):
    """Reports a bad flag to the caller instead of ending the kernel.

    ``argparse`` answers an unparseable command line with ``SystemExit``, which
    in a notebook reads as a crashed cell rather than a typo.
    """

    def error(self, message):
        raise ValueError("%visdom: {0}\n{1}".format(message, self.format_usage()))

    def exit(self, status=0, message=None):
        raise ValueError(message or "%visdom: could not parse the command line")


def _port(value):
    """A port from the command line.

    ``ArgumentTypeError`` rather than ``ValueError`` because argparse keeps
    the message of the former and replaces the latter with "invalid _port
    value", which names this function instead of saying what was wrong.
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

    ``int`` first so that a whole number stays whole: ``show()`` formats an
    integer as ``600px`` and a float as ``600.0px``, and the second is a
    length the browser honours but nobody typed.
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

    Any number, not only a whole one -- ``--height 600.5`` is 600.5 pixels,
    exactly as ``show(height=600.5)`` is. Read as CSS instead it reaches the
    browser as ``height:600.5``, a length with no unit, which the browser
    drops: the dimension is then ignored rather than refused, and the frame
    is whatever size it would have been without the flag.

    Checked by ``show()``'s own ``_embed_size`` rather than by a rule of its
    own, so the command line cannot accept a dimension the embed then refuses.
    It is checked here, at parse time, because registering the environment
    happens between the two: a dimension rejected by the embed would otherwise
    have created an environment on the server on its way to the error.
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

    Returns ``(url, port)``, where ``port`` is ``None`` unless the url
    carried one. The client builds every request as ``server:port/...``, so a
    port left in the url is a second port: ``--server localhost:8097`` on the
    default port asked for ``http://localhost:8097:8097/env/main``, which no
    server answers at and no browser can load.

    ``http://`` is filled in for a bare host, but only for a bare host: an
    explicit scheme has to be one a browser frame and the client can both
    speak. Re-parsing any other scheme as a host reads ``htps://box`` as the
    host ``htps:`` and drops the rest of the line, so a typo in the scheme
    became an address nothing is listening on.

    Anything after the host is refused rather than dropped. A dashboard
    mounted under a proxy path is at a different address, not at the same one
    with a decoration, and quietly embedding the server root instead would
    frame whatever else is answering there.
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
        # urlparse only reads the port when asked, and answers both a port
        # that is not a number and one out of range with a ValueError.
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
        # rsplit, so an IPv6 host keeps the colons inside its brackets and
        # 'user:password@host' keeps the one in its userinfo.
        netloc = netloc.rsplit(":", 1)[0]
    return urlunparse((parsed.scheme, netloc, "", "", "", "")), port


def _resolve_port(in_url, flag):
    """The port to talk to, from the one in ``--server`` and the one in ``--port``.

    Either spelling is fine and ``localhost:8097`` is the more natural one to
    paste, but a line that gives both has said two things, and picking one of
    them is how ``--port 9000`` ends up silently ignored.
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
    # No default: the port can also be part of --server, and 'the user did
    # not say' is what tells the two apart from a disagreement between them.
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

    ``Visdom`` leaves the read half of its POST timeout unbounded, because a
    send can carry a video the server is still writing out when the
    connection goes quiet. Registering an environment is not that, and a cell
    has nothing to interrupt it: a server that accepts the connection and
    then says nothing would keep the kernel on this line for as long as it
    stayed up.
    """

    post_timeout = (CONNECT_TIMEOUT, READ_TIMEOUT)


def _client_for(server, port, env):
    """The client for this address and environment, built once per kernel.

    Constructing it registers the environment, so the deep link the frame
    loads names an environment the dashboard knows rather than one it has
    never seen. No incoming socket: this client only names the env.

    It is cached because a ``Visdom`` starts a session reaper that loops for
    the life of the process and holds the client while it does. Building a new
    one per cell execution would leave a thread and a client behind on every
    run, and a notebook runs the same cell all day.

    A client is cached even when that registration did not land, since the
    thread it holds is there either way -- but the registration is then tried
    again on the next run. The cache is here to save a thread, not to make
    the first run's failure permanent: a ``%visdom`` typed before the server
    was up would otherwise frame a ``404`` for the rest of the session, and
    re-running the cell, the one thing anybody would try, would change
    nothing.
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
        # Printed rather than returned: a cell displays a returned string
        # through its repr, which puts the usage in quotes with its line
        # breaks spelled '\n'.
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

    Only this extension's own entry: if a user or another extension has taken
    the name over since ``%load_ext``, unloading this extension is not a
    licence to remove what they registered.
    """
    manager = getattr(ipython, "magics_manager", None)
    if manager is None:
        return
    line_magics = manager.magics.get("line", {})
    if line_magics.get("visdom") is visdom_magic:
        del line_magics["visdom"]
