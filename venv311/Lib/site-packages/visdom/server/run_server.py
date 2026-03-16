#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Provides simple entrypoints to set up and run the main visdom server.
"""

import argparse
import getpass
import logging
import os
import sys
from tornado import ioloop
from visdom.server.app import Application
from visdom.server.defaults import (
    DEFAULT_BASE_URL,
    DEFAULT_ENV_PATH,
    DEFAULT_HOSTNAME,
    DEFAULT_PORT,
)
from visdom.server.build import download_scripts
from visdom.utils.server_utils import hash_password, set_cookie


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
):
    print("It's Alive!")
    app = Application(
        port=port,
        base_url=base_url,
        env_path=env_path,
        readonly=readonly,
        user_credential=user_credential,
        use_frontend_client_polling=use_frontend_client_polling,
        eager_data_loading=eager_data_loading,
    )
    if bind_local:
        app.listen(port, max_buffer_size=1024**3, address="127.0.0.1")
    else:
        app.listen(port, max_buffer_size=1024**3)
    logging.info("Application Started")
    logging.info(f"Working directory: {os.path.abspath(env_path)}")

    if "HOSTNAME" in os.environ and hostname == DEFAULT_HOSTNAME:
        hostname = os.environ["HOSTNAME"]
    else:
        hostname = hostname
    if print_func is None:
        print("You can navigate to http://%s:%s%s" % (hostname, port, base_url))
    else:
        print_func(port)
    ioloop.IOLoop.instance().start()
    app.subs = []
    app.sources = []


def main(print_func=None):
    """
    Run a server from the command line, first parsing arguments from the
    command line
    """
    parser = argparse.ArgumentParser(description="Start the visdom server.")
    parser.add_argument(
        "-port",
        metavar="port",
        type=int,
        default=DEFAULT_PORT,
        help="port to run the server on.",
    )
    parser.add_argument(
        "--hostname",
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
    FLAGS = parser.parse_args()

    # Process base_url
    base_url = FLAGS.base_url if FLAGS.base_url != DEFAULT_BASE_URL else ""
    assert base_url == "" or base_url.startswith("/"), "base_url should start with /"
    assert base_url == "" or not base_url.endswith(
        "/"
    ), "base_url should not end with / as it is appended automatically"

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

        user_credential = {
            "username": username,
            "password": hash_password(hash_password(password)),
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
    )


def download_scripts_and_run():
    download_scripts()
    main()


if __name__ == "__main__":
    download_scripts_and_run()
