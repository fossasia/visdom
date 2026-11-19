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
import re
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
# A dimension that is a plain number, sign and all: '-1' is a number the embed
# refuses, not a CSS length to hand the browser.
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")

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


def _dimension(value):
    """An iframe dimension from the command line: a number is pixels, else CSS.

    Checked by ``show()``'s own ``_embed_size`` rather than by a rule of its
    own, so the command line cannot accept a dimension the embed then refuses.
    It is checked here, at parse time, because registering the environment
    happens between the two: a dimension rejected by the embed would otherwise
    have created an environment on the server on its way to the error.
    """
    text = value.strip()
    dimension = int(text) if _INTEGER.match(text) else value
    try:
        _embed_size(dimension)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None
    return dimension


def _normalize_server(server):
    """A server url with a scheme and nothing after the host, as ``Visdom`` keeps it.

    ``http://`` is filled in for a bare host, but only for a bare host: an
    explicit scheme has to be one a browser frame and the client can both
    speak. Re-parsing any other scheme as a host reads ``htps://box`` as the
    host ``htps:`` and drops the rest of the line, so a typo in the scheme
    became an address nothing is listening on.
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
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _build_parser():
    parser = _Parser(
        prog="%visdom",
        add_help=False,
        description="Embed a visdom dashboard in this notebook.",
    )
    parser.add_argument(
        "-h", "--help", action="store_true", help="print this message and stop"
    )
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT, help="server port")
    parser.add_argument(
        "--server", default=DEFAULT_SERVER, help="server url, without the port"
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


def _client_for(server, port, env):
    """The client for this address and environment, built once per kernel.

    Constructing it registers the environment, so the deep link the frame
    loads names an environment the dashboard knows rather than one it has
    never seen. No incoming socket: this client only names the env.

    It is cached because a ``Visdom`` starts a session reaper that loops for
    the life of the process and holds the client while it does. Building a new
    one per cell execution would leave a thread and a client behind on every
    run, and a notebook runs the same cell all day.
    """
    key = (server, port, env)
    client = _clients.get(key)
    if client is None:
        client = Visdom(
            server=server,
            port=port,
            env=env,
            use_incoming_socket=False,
        )
        _clients[key] = client
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

    server = _normalize_server(args.server)
    client = _client_for(server, args.port, args.env)
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
