#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Provides simple entrypoints to set up and run the main visdom server.
"""

import asyncio
import atexit
import argparse
import getpass
import hashlib
import logging
import os
import signal
import ssl
import sys
import errno
import socket
import tornado.httpserver
import tornado.netutil
from visdom.server.app import Application
from visdom.server.defaults import (
    DEFAULT_BASE_URL,
    DEFAULT_ENV_PATH,
    DEFAULT_HOSTNAME,
    DEFAULT_PORT,
    DEFAULT_SAVE_INTERVAL,
    DEFAULT_SAVE_THRESHOLD,
)
from visdom.server.build import download_scripts
from visdom.utils.server_utils import hash_password, set_cookie

MAX_PORT = 65535


class PortValidationError(ValueError, argparse.ArgumentTypeError):
    """Validation error for port values that work for argparse and callers."""


def valid_port(value):
    """
    Validate that the port is an integer in the range [1, 65535].
    Note: Port 0 is excluded for HTTP/browser use because browsers block it
    with `ERR_UNSAFE_PORT`.
    It raises PortValidationError so argparse preserves the custom message when
    used as a `type=` argument, while programmatic callers can still treat it
    as a ValueError.
    """
    if isinstance(value, (bool, float)):
        raise PortValidationError(f"Port must be an integer, got: '{value}'")
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise PortValidationError(f"Port must be an integer, got: '{value}'")
    if not (1 <= port <= MAX_PORT):
        raise PortValidationError(f"Port must be between 1 and {MAX_PORT}, got: {port}")
    return port


def _exit_cleanly(signum, frame):
    """Turn a termination signal into a normal interpreter shutdown.

    Python's default disposition for SIGTERM ends the process outright, so the
    ``atexit`` save never runs and ``docker stop`` discards every unsaved
    environment. Raising SystemExit instead unwinds and lets that handler fire.
    """
    sys.exit(0)


def start_server(
    port=DEFAULT_PORT,
    hostname=DEFAULT_HOSTNAME,
    base_url=DEFAULT_BASE_URL,
    env_path=DEFAULT_ENV_PATH,
    readonly=False,
    print_func=None,
    user_credential=None,
    use_frontend_client_polling=False,
    bind_local=False,
    eager_data_loading=False,
    ssl_certfile=None,
    ssl_keyfile=None,
    save_interval=DEFAULT_SAVE_INTERVAL,
    save_threshold=DEFAULT_SAVE_THRESHOLD,
):
    logging.info("Server started")
    # Reading the certificate before anything is constructed keeps a bad path
    # from leaving a storage worker and an open port behind.
    ssl_ctx = _build_ssl_context(ssl_certfile, ssl_keyfile)
    asyncio.run(
        _serve(
            port=port,
            hostname=hostname,
            base_url=base_url,
            env_path=env_path,
            readonly=readonly,
            print_func=print_func,
            user_credential=user_credential,
            use_frontend_client_polling=use_frontend_client_polling,
            bind_local=bind_local,
            eager_data_loading=eager_data_loading,
            ssl_ctx=ssl_ctx,
            save_interval=save_interval,
            save_threshold=save_threshold,
        )
    )


def _build_ssl_context(ssl_certfile, ssl_keyfile):
    """Load the certificate pair, or return ``None`` when TLS is not configured."""
    if not (ssl_certfile and ssl_keyfile):
        return None
    if not os.path.isfile(ssl_certfile):
        raise FileNotFoundError(f"SSL certificate file not found: {ssl_certfile}")
    if not os.path.isfile(ssl_keyfile):
        raise FileNotFoundError(f"SSL key file not found: {ssl_keyfile}")
    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.load_cert_chain(ssl_certfile, ssl_keyfile)
    logging.info("SSL enabled")
    return ssl_ctx


def _install_stop_handlers(stop):
    """Ask for a graceful stop on SIGINT/SIGTERM, falling back to SystemExit.

    ``loop.add_signal_handler`` runs the callback *on* the loop, so the drain
    below is an ordinary awaited shutdown rather than something racing an
    interpreter teardown. It is POSIX-and-main-thread only, hence the fallback
    to the old ``signal.signal`` behaviour everywhere else -- Windows, and any
    caller running the server from a worker thread.
    """
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            if sig == getattr(signal, "SIGTERM", None):
                try:
                    signal.signal(sig, _exit_cleanly)
                except ValueError:
                    pass


async def _serve(
    port,
    hostname,
    base_url,
    env_path,
    readonly,
    print_func,
    user_credential,
    use_frontend_client_polling,
    bind_local,
    eager_data_loading,
    ssl_ctx,
    save_interval,
    save_threshold,
):
    """Build the server on a running loop, then serve until asked to stop.

    Everything here used to run before ``IOLoop.current().start()``, so the
    autosave timer and the storage executor were attached to a loop that
    tornado conjured out of the current asyncio policy. Constructing them
    inside ``asyncio.run`` means there is exactly one loop, it is already
    running, and it is closed on the way out.
    """
    app = Application(
        port=port,
        base_url=base_url,
        env_path=env_path,
        readonly=readonly,
        user_credential=user_credential,
        use_frontend_client_polling=use_frontend_client_polling,
        eager_data_loading=eager_data_loading,
        save_interval=save_interval,
        save_threshold=save_threshold,
    )
    bind_addr = "127.0.0.1" if bind_local else None
    family = socket.AF_INET if bind_local else socket.AF_UNSPEC

    server = tornado.httpserver.HTTPServer(
        app, max_buffer_size=1024**3, ssl_options=ssl_ctx
    )

    try:
        sockets = tornado.netutil.bind_sockets(port, address=bind_addr, family=family)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            logging.warning(f"Port {port} is already in use, assigning a free port")
            sockets = tornado.netutil.bind_sockets(0, address=bind_addr, family=family)
        else:
            logging.error(f"Failed to bind to port {port}: {e}")
            raise
    port = sockets[0].getsockname()[1]
    app.port = port
    server.add_sockets(sockets)

    logging.info("Application Started")
    logging.info(f"Working directory: {os.path.abspath(env_path)}")

    # Still registered: the graceful path below covers a signal or a normal
    # exit, this covers the ones that never unwind through it. The drain is
    # idempotent, so running twice costs nothing.
    atexit.register(app.shutdown_storage)

    stop = asyncio.Event()
    _install_stop_handlers(stop)

    app.server_state.start_autosave()

    if "HOSTNAME" in os.environ and hostname == DEFAULT_HOSTNAME:
        hostname = os.environ["HOSTNAME"]

    scheme = "https" if ssl_ctx else "http"

    if print_func is None:
        print("You can navigate to %s://%s:%s%s" % (scheme, hostname, port, base_url))
    else:
        print_func(port)

    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logging.info("Shutting down")
        server.stop()
        app.subs = []
        app.sources = []
        # Blocking, but nothing is being served by now: the listening sockets
        # are closed and this is the last thing the loop does.
        app.shutdown_storage()


def main(print_func=None):
    """
    Run a server from the command line, first parsing arguments from the
    command line
    """
    parser = argparse.ArgumentParser(description="Start the visdom server.")
    parser.add_argument(
        "-port",
        metavar="port",
        type=valid_port,
        default=DEFAULT_PORT,
        help="port to run the server on.",
    )
    parser.add_argument(
        "-hostname",
        metavar="hostname",
        type=str,
        default=DEFAULT_HOSTNAME,
        help="host to run the server on.",
    )
    parser.add_argument(
        "-base_url",
        metavar="base_url",
        type=str,
        default=DEFAULT_BASE_URL,
        help="base url for server (default = /).",
    )
    parser.add_argument(
        "-env_path",
        metavar="env_path",
        type=str,
        default=DEFAULT_ENV_PATH,
        help="path to serialized session to reload.",
    )
    parser.add_argument(
        "-logging_level",
        metavar="logger_level",
        default="INFO",
        help="logging level (default = INFO). Can take "
        "logging level name or int (example: 20)",
    )
    parser.add_argument("-readonly", help="start in readonly mode", action="store_true")
    parser.add_argument(
        "-enable_login",
        default=False,
        action="store_true",
        help="start the server with authentication",
    )
    parser.add_argument(
        "-force_new_cookie",
        default=False,
        action="store_true",
        help="start the server with the new cookie, "
        "available when -enable_login provided",
    )
    parser.add_argument(
        "-use_frontend_client_polling",
        default=False,
        action="store_true",
        help="Have the frontend communicate via polling "
        "rather than over websockets.",
    )
    parser.add_argument(
        "-bind_local",
        default=False,
        action="store_true",
        help="Make server only accessible only from " "localhost.",
    )
    parser.add_argument(
        "-eager_data_loading",
        default=False,
        action="store_true",
        help="Load data from filesystem when starting server (and not lazily upon first request).",
    )
    parser.add_argument(
        "-save_interval",
        metavar="save_interval",
        type=int,
        default=DEFAULT_SAVE_INTERVAL,
        help="Seconds between automatic saves of changed environments. "
        "0 disables the timer; with -save_threshold 0 as well, environments are "
        "only written to disk when asked and at shutdown.",
    )
    parser.add_argument(
        "-save_threshold",
        metavar="save_threshold",
        type=int,
        default=DEFAULT_SAVE_THRESHOLD,
        help="Save an environment early once it has taken this many updates, "
        "so a busy one is not left unsaved for a whole interval. 0 disables.",
    )
    parser.add_argument(
        "-ssl_certfile",
        metavar="ssl_certfile",
        type=str,
        default=None,
        help="Path to SSL certificate file (.pem or .crt) to enable HTTPS. "
        "Must be used together with -ssl_keyfile.",
    )
    parser.add_argument(
        "-ssl_keyfile",
        metavar="ssl_keyfile",
        type=str,
        default=None,
        help="Path to SSL private key file (.pem or .key) to enable HTTPS. "
        "Must be used together with -ssl_certfile.",
    )
    FLAGS = parser.parse_args()

    # Process base_url
    base_url = FLAGS.base_url if FLAGS.base_url != DEFAULT_BASE_URL else ""
    assert base_url == "" or base_url.startswith("/"), "base_url should start with /"
    assert base_url == "" or not base_url.endswith(
        "/"
    ), "base_url should not end with / as it is appended automatically"

    if bool(FLAGS.ssl_certfile) != bool(FLAGS.ssl_keyfile):
        parser.error("-ssl_certfile and -ssl_keyfile must be provided together.")

    try:
        logging_level = int(FLAGS.logging_level)
    except ValueError:
        try:
            logging_level = logging._checkLevel(FLAGS.logging_level)
        except ValueError:
            raise KeyError("Invalid logging level : {0}".format(FLAGS.logging_level))

    logging.getLogger().setLevel(logging_level)

    if FLAGS.enable_login:
        enable_env_login = "VISDOM_USE_ENV_CREDENTIALS"
        use_env = os.environ.get(enable_env_login, False)
        if use_env:
            username_var = "VISDOM_USERNAME"
            password_var = "VISDOM_PASSWORD"
            username = os.environ.get(username_var)
            password = os.environ.get(password_var)
            if not (username and password):
                print(
                    "*** Warning ***\n"
                    "You have set the {0} env variable but probably "
                    "forgot to setup one (or both) {{ {1}, {2} }} "
                    "variables.\nYou should setup these variables with "
                    "proper username and password to enable logging. Try to "
                    "setup the variables, or unset {0} to input credentials "
                    "via command line prompt instead.\n".format(
                        enable_env_login, username_var, password_var
                    )
                )
                sys.exit(1)

        else:
            username = input("Please input your username: ")
            password = getpass.getpass(prompt="Please input your password: ")

        client_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        user_credential = {
            "username": username,
            "password": hash_password(client_hash),
        }

        need_to_set_cookie = (
            not os.path.isfile(DEFAULT_ENV_PATH + "COOKIE_SECRET")
            or FLAGS.force_new_cookie
        )

        if need_to_set_cookie:
            if use_env:
                cookie_var = "VISDOM_COOKIE"
                env_cookie = os.environ.get(cookie_var)
                if env_cookie is None:
                    print(
                        "The cookie file is not found. Please setup {0} env "
                        "variable to provide a cookie value, or unset {1} env "
                        "variable to input credentials and cookie via command "
                        "line prompt.".format(cookie_var, enable_env_login)
                    )
                    sys.exit(1)
            else:
                env_cookie = None
            set_cookie(env_cookie)

    else:
        user_credential = None

    start_server(
        port=FLAGS.port,
        hostname=FLAGS.hostname,
        base_url=base_url,
        env_path=FLAGS.env_path,
        readonly=FLAGS.readonly,
        print_func=print_func,
        user_credential=user_credential,
        use_frontend_client_polling=FLAGS.use_frontend_client_polling,
        bind_local=FLAGS.bind_local,
        eager_data_loading=FLAGS.eager_data_loading,
        ssl_certfile=FLAGS.ssl_certfile,
        ssl_keyfile=FLAGS.ssl_keyfile,
        save_interval=FLAGS.save_interval,
        save_threshold=FLAGS.save_threshold,
    )


def download_scripts_and_run():
    download_scripts()
    main()


if __name__ == "__main__":
    download_scripts_and_run()
