#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The ``%visdom`` line magic.

    %load_ext visdom.notebook
    %visdom --port 8097 --env run-7

Starts a server on the kernel's own machine if nothing answers on the port,
then embeds that dashboard in the output cell.

IPython is never imported here: ``load_ipython_extension`` is handed the shell
to register against, and the magic returns the same ``_repr_html_`` object
``Visdom.show`` does. ``visdom/__init__.py`` does not import this module, so
the import cost of ``import visdom`` is unchanged.
"""

import argparse
import atexit
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse, urlunparse

import requests

from visdom import _is_loopback, _NotebookEmbed, Visdom
from visdom.server.defaults import DEFAULT_BASE_URL, DEFAULT_PORT

DEFAULT_SERVER = "http://localhost"
DEFAULT_ENV = "main"
DEFAULT_HEIGHT = 600
DEFAULT_WIDTH = "100%"
# run_server's own port validator sits behind a tornado import, which %load_ext
# should not pay for.
MAX_PORT = 65535
PROBE_TIMEOUT = 2.0
START_TIMEOUT = 20.0
POLL_INTERVAL = 0.25

# Servers this kernel started, as port -> (process, log path), so a second
# '%visdom' on the same port waits for the first one instead of spawning a
# rival for the socket.
_started = {}


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
    port = int(value)
    if not 1 <= port <= MAX_PORT:
        raise ValueError(
            "port must be between 1 and {0}, got {1}".format(MAX_PORT, port)
        )
    return port


def _dimension(value):
    """An iframe dimension from the command line: digits are pixels, else CSS."""
    if not value.lstrip("+").isdigit():
        return value
    pixels = int(value)
    if pixels <= 0:
        raise ValueError("iframe dimensions must be positive, got {0}".format(value))
    return pixels


def _normalize_server(server):
    """A server url with a scheme and nothing after the host, as ``Visdom`` keeps it."""
    parsed = urlparse(server)
    if parsed.scheme not in ("http", "https"):
        parsed = urlparse("http://{0}".format(server))
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _normalize_base_url(base_url):
    """A ``base_url`` shaped the way ``Visdom`` and the server both want it."""
    trimmed = base_url.strip().strip("/")
    return DEFAULT_BASE_URL if not trimmed else "/{0}".format(trimmed)


def _build_parser():
    parser = _Parser(
        prog="%visdom",
        add_help=False,
        description="Embed a visdom dashboard in this notebook, starting a "
        "local server if one is not already running.",
    )
    parser.add_argument(
        "-h", "--help", action="store_true", help="print this message and stop"
    )
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT, help="server port")
    parser.add_argument(
        "--server", default=DEFAULT_SERVER, help="server url, without the port"
    )
    parser.add_argument(
        "--base_url", "--base-url", default=DEFAULT_BASE_URL, help="server base url"
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
    parser.add_argument(
        "--no-start",
        "--no_start",
        dest="no_start",
        action="store_true",
        help="embed whatever is already running and never start a server",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=START_TIMEOUT,
        help="seconds to wait for a server this magic started",
    )
    return parser


def _dashboard_root(server, port, base_url):
    tail = "" if base_url == DEFAULT_BASE_URL else base_url
    return "{0}:{1}{2}/".format(server, port, tail)


def _server_is_up(server, port, base_url, timeout=PROBE_TIMEOUT):
    """Whether anything answers HTTP there.

    Any reply counts, including the login form of a ``-enable_login`` server
    and the redirect in front of it: the question is whether a server already
    holds the port, not whether this caller may read it. A certificate this
    client will not accept is an answer too -- something is serving TLS there,
    and starting a second server on the port would only fail to bind.
    """
    try:
        requests.get(_dashboard_root(server, port, base_url), timeout=timeout)
    except requests.exceptions.SSLError:
        return True
    except requests.RequestException:
        return False
    return True


def _server_log():
    log = tempfile.NamedTemporaryFile(
        prefix="visdom-notebook-", suffix=".log", delete=False
    )
    log.close()
    return log.name


def _log_tail(path, lines=20):
    try:
        with open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return "".join(handle.readlines()[-lines:]).strip()
    except OSError:
        return ""


def _await_server(child, server, port, base_url, timeout, log_path):
    deadline = time.monotonic() + timeout
    while True:
        if _server_is_up(server, port, base_url):
            return
        if child.poll() is not None:
            raise RuntimeError(
                "the visdom server exited with status {0}. Its output is in "
                "{1}:\n{2}".format(child.returncode, log_path, _log_tail(log_path))
            )
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "the visdom server did not answer on port {0} within {1:g}s. "
                "Its output is in {2}:\n{3}".format(
                    port, timeout, log_path, _log_tail(log_path)
                )
            )
        time.sleep(POLL_INTERVAL)


def _start_server(server, port, base_url, timeout):
    """Spawn a server on this machine and wait until it answers.

    The server runs as a child process rather than in the kernel: it owns an
    asyncio loop of its own, and a notebook's loop is already taken.
    """
    running, running_log = _started.get(port, (None, None))
    if running is not None and running.poll() is None:
        _await_server(running, server, port, base_url, timeout, running_log)
        return running

    log_path = _server_log()
    command = [sys.executable, "-m", "visdom.server", "-port", str(port)]
    if base_url != DEFAULT_BASE_URL:
        command += ["-base_url", base_url]
    with open(log_path, "ab") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    _started[port] = (child, log_path)
    _await_server(child, server, port, base_url, timeout, log_path)
    print("Started a visdom server on port {0} (log: {1})".format(port, log_path))
    return child


def _stop_started_servers():
    """Stop the servers this kernel started, letting each one save first.

    ``terminate`` is SIGTERM, which the server turns into a normal shutdown, so
    the environments it still holds are written out.
    """
    for child, _ in _started.values():
        if child.poll() is not None:
            continue
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
    _started.clear()


atexit.register(_stop_started_servers)


def _refusal_to_start(server, port, no_start):
    """Why no server will be started for an address nothing answers at."""
    if no_start:
        return (
            "Nothing is answering at {0}:{1} and --no-start was given, so no "
            "server was started.".format(server, port)
        )
    if not _is_loopback(urlparse(server).hostname):
        return (
            "Nothing is answering at {0}:{1}. Only a server on this machine "
            "can be started from here, so start it on that host and run "
            "%visdom again.".format(server, port)
        )
    return None


def visdom_magic(line=""):
    """Embed a dashboard in the output cell. Registered as ``%visdom``.

    Returns the object ``Visdom.show`` returns, which the notebook renders as
    an iframe and anything else prints as the dashboard URL.
    """
    parser = _build_parser()
    args = parser.parse_args(shlex.split(line))
    if args.help:
        return parser.format_help()

    server = _normalize_server(args.server)
    base_url = _normalize_base_url(args.base_url)
    if not _server_is_up(server, args.port, base_url):
        note = _refusal_to_start(server, args.port, args.no_start)
        if note is not None:
            return _NotebookEmbed(None, args.height, args.width, note=note)
        _start_server(server, args.port, base_url, args.timeout)

    # Constructing the client registers the environment, which is what keeps
    # the deep link out of the 404 the dashboard answers for an env it has
    # never seen. No incoming socket: this client only names the env.
    client = Visdom(
        server=server,
        port=args.port,
        base_url=base_url,
        env=args.env,
        use_incoming_socket=False,
    )
    return client.show(height=args.height, width=args.width)


def load_ipython_extension(ipython):
    """Register ``%visdom``. IPython calls this for ``%load_ext``."""
    ipython.register_magic_function(visdom_magic, "line", "visdom")


def unload_ipython_extension(ipython):
    """Unregister ``%visdom``. IPython calls this for ``%unload_ext``."""
    manager = getattr(ipython, "magics_manager", None)
    if manager is not None:
        manager.magics.get("line", {}).pop("visdom", None)
