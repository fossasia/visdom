#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from visdom.utils.shared_utils import get_new_window_id
from visdom import server
import os.path
import requests
import traceback
import threading
import websocket  # type: ignore
import json
import hashlib

try:
    # for after python 3.8
    from collections.abc import Sequence
except ImportError:
    # for python 3.7 and below
    from collections import Sequence
import math
import re
import base64
import numpy as np  # type: ignore
from PIL import Image  # type: ignore
import base64 as b64  # type: ignore
import numbers
from urllib.parse import urlparse, urlunparse
import logging
import warnings
import time
import errno
from io import BytesIO, StringIO
from functools import wraps

try:
    import bs4  # type: ignore

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

import sys

assert sys.version_info[0] >= 3, "To use visdom with python 2, downgrade to v0.1.8.9"

try:
    # TODO try to import https://github.com/CannyLab/tsne-cuda first? will be
    # faster but requires more setup
    import visdom.extra_deps.bhtsne.bhtsne as bhtsne

    def do_tsne(X):
        num_entities = len(X)

        # the number of entities provided must be at least 3x the perplexity
        perplexity = (
            50
            if num_entities >= 150
            else num_entities // 3
            if num_entities >= 21
            else 7
        )
        Y = bhtsne.run_bh_tsne(
            X, initial_dims=X.shape[1], perplexity=perplexity, verbose=True
        )
        xmin, xmax = min(Y[:, 0]), max(Y[:, 0])
        ymin, ymax = min(Y[:, 1]), max(Y[:, 1])
        normx = ((Y[:, 0] - xmin) / (xmax - xmin)) * 2 - 1
        normy = ((Y[:, 1] - ymin) / (ymax - ymin)) * 2 - 1
        normY = list(zip(normx, normy))
        return normY

except ImportError:

    def do_tsne(X):
        raise Exception(
            "In order to use the embeddings feature, you'll "
            "need to install a backend to support the calculation. "
            "Currently we support the bhtsne implementation at "
            "https://github.com/lvdmaaten/bhtsne/, and you can install "
            "this by cloning it into the /py/visdom/extra_deps/ directory "
            "and running the installation steps as listed on that github "
            "in the created /py/visdom/extra_deps/bhtsne directory."
        )


here = os.path.abspath(os.path.dirname(__file__))

try:
    with open(os.path.join(here, "VERSION")) as version_file:
        __version__ = version_file.read().strip()
except Exception:
    __version__ = "no_version_file"

logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


def get_rand_id():
    return str(hex(int(time.time() * 10000000))[2:])


def isstr(s):
    return isinstance(s, (str,))


def isnum(n):
    return isinstance(n, numbers.Number)


def isndarray(n):
    return isinstance(n, (np.ndarray))


# Only works on (possibly nested) lists of numbers
# TODO: Create our own JSONEncoder that automatically does this.
#       Maybe we can port plotly's over:
#       https://github.com/plotly/plotly.py/blob/81629273ff6d7a30257a42572ed0e4e6ad436009/_plotly_utils/utils.py#L16
# TODO: Also, in appropriate places, we need to change many numpy calls to use
#       nan-aware ones, e.g., `X.max` => `np.nanmax(X)`.
def nan2none(l):
    for idx, val in enumerate(l):
        if isinstance(val, Sequence):
            l[idx] = nan2none(l[idx])
        elif isnum(val) and math.isnan(val):
            l[idx] = None
    return l


def loadfile(filename):
    assert os.path.isfile(filename), "could not find file %s" % filename
    fileobj = open(filename, "rb")
    assert fileobj, "could not open file %s" % filename
    str = fileobj.read()
    fileobj.close()
    return str


def _title2str(opts):
    if opts.get("title"):
        if isnum(opts.get("title")):
            title = str(opts.get("title"))
            logger.warn("Numerical title %s has been casted to a string" % title)
            opts["title"] = title
            return opts
        else:
            return opts


def _scrub_dict(d):
    if isinstance(d, dict):
        return {
            k: _scrub_dict(v)
            for k, v in list(d.items())
            if v is not None and _scrub_dict(v) is not None
        }
    else:
        return d


def _axisformat(xy, opts):
    fields = [
        "type",
        "label",
        "tickmin",
        "tickmax",
        "tickvals",
        "ticklabels",
        "tick",
        "tickfont",
    ]
    if any(opts.get(xy + i) for i in fields):
        has_ticks = (opts.get(xy + "tickmin") and opts.get(xy + "tickmax")) is not None
        return {
            "type": opts.get(xy + "type"),
            "title": opts.get(xy + "label"),
            "range": [opts.get(xy + "tickmin"), opts.get(xy + "tickmax")]
            if has_ticks
            else None,
            "tickvals": opts.get(xy + "tickvals"),
            "ticktext": opts.get(xy + "ticklabels"),
            "dtick": opts.get(xy + "tickstep"),
            "showticklabels": opts.get(xy + "tick"),
            "tickfont": opts.get(xy + "tickfont"),
        }


def _axisformat3d(xyz, opts):
    fields = [
        "type",
        "label",
        "tickmin",
        "tickmax",
        "tickvals",
        "ticklabels",
        "tick",
        "tickfont",
    ]
    if any(opts.get(xyz + i) for i in fields):
        has_ticks = (
            opts.get(xyz + "tickmin") and opts.get(xyz + "tickmax")
        ) is not None
        has_step = has_ticks and opts.get(xyz + "tickstep") is not None
        return {
            "type": opts.get(xyz + "type"),
            "title": opts.get(xyz + "label"),
            "range": [opts.get(xyz + "tickmin"), opts.get(xyz + "tickmax")]
            if has_ticks
            else None,
            "tickvals": opts.get(xyz + "tickvals"),
            "ticktext": opts.get(xyz + "ticklabels"),
            "nticks": (
                (opts.get(xyz + "tickmax") - opts.get(xyz + "tickmin"))
                / opts.get(xyz + "tickstep")
            )
            if has_step
            else None,
            "tickfont": opts.get(xyz + "tickfont"),
        }


def _opts2layout(opts, is3d=False):
    layout = {
        "showlegend": opts.get("showlegend", "legend" in opts),
        "title": opts.get("title"),
        "margin": {
            "l": opts.get("marginleft", 0 if is3d else 60),
            "r": opts.get("marginright", 60),
            "t": opts.get("margintop", 20 if is3d else 60),
            "b": opts.get("marginbottom", 0 if is3d else 60),
        },
    }

    if is3d:
        layout["scene"] = {
            "xaxis": _axisformat3d("x", opts),
            "yaxis": _axisformat3d("y", opts),
            "zaxis": _axisformat3d("z", opts),
        }
    else:
        layout["xaxis"] = _axisformat("x", opts)
        layout["yaxis"] = _axisformat("y", opts)

    if opts.get("stacked"):
        layout["barmode"] = "stack" if opts.get("stacked") else "group"

    layout_opts = opts.get("layoutopts")
    if layout_opts is not None:
        if "plotly" in layout_opts:
            layout.update(layout_opts["plotly"])

    return _scrub_dict(layout)


def _markerColorCheck(mc, X, Y, L):
    assert isndarray(mc), "mc should be a numpy ndarray"
    assert mc.shape[0] == L or (
        mc.shape[0] == X.shape[0]
        and (mc.ndim == 1 or mc.ndim == 2 and mc.shape[1] == 3)
    ), (
        "marker colors have to be of size `%d` or `%d x 3` "
        + " or `%d` or `%d x 3`, but got: %s"
    ) % (
        X.shape[0],
        X.shape[1],
        L,
        L,
        "x".join(map(str, mc.shape)),
    )

    assert (mc >= 0).all(), "marker colors have to be >= 0"
    assert (mc <= 255).all(), "marker colors have to be <= 255"
    assert (mc == np.floor(mc)).all(), "marker colors are assumed to be ints"

    mc = np.uint8(mc)

    if mc.ndim == 1:
        markercolor = ["rgba(0, 0, 255, %s)" % (mc[i] / 255.0) for i in range(len(mc))]
    else:
        markercolor = ["#%02x%02x%02x" % (i[0], i[1], i[2]) for i in mc]

    if mc.shape[0] != X.shape[0]:
        markercolor = [markercolor[Y[i] - 1] for i in range(Y.shape[0])]

    ret = {}
    for k, v in enumerate(markercolor):
        ret[Y[k]] = ret.get(Y[k], []) + [v]

    return ret


def _lineColorCheck(lc, K):
    assert isndarray(lc), "lc should be a numpy ndarray"
    assert lc.shape[0] == K, "lc should be same shape as K"

    assert (lc >= 0).all(), "line colors have to be >= 0"
    assert (lc <= 255).all(), "line colors have to be <= 255"
    assert (lc == np.floor(lc)).all(), "line colors are assumed to be ints"

    return ["#%02x%02x%02x" % (i[0], i[1], i[2]) for i in lc]


def _dashCheck(dash, K):
    assert isndarray(dash), "dash should be a numpy ndarray"
    assert dash.shape[0] == K, "dash should be same shape as K"

    return dash


def _assert_opts(opts):
    remove_nones = ["title"]
    for to_remove in remove_nones:
        if to_remove in opts and opts[to_remove] is None:
            logger.warn(
                "None-incompatible opt {} was provided None value "
                "and was thus ignored".format(to_remove)
            )
            del opts[to_remove]

    if opts.get("color"):
        assert isstr(opts.get("color")), "color should be a string"

    if opts.get("colormap"):
        assert isstr(opts.get("colormap")), "colormap should be string"

    if opts.get("mode"):
        assert isstr(opts.get("mode")), "mode should be a string"

    if opts.get("markersymbol"):
        assert isstr(opts.get("markersymbol")), "marker symbol should be string"

    if opts.get("markersize"):
        assert (
            isnum(opts.get("markersize")) and opts.get("markersize") > 0
        ), "marker size should be a positive number"

    if opts.get("markerborderwidth"):
        assert (
            isnum(opts.get("markerborderwidth")) and opts.get("markerborderwidth") >= 0
        ), "marker border width should be a nonnegative number"

    if opts.get("columnnames"):
        assert isinstance(
            opts.get("columnnames"), list
        ), "columnnames should be a list with column names"

    if opts.get("rownames"):
        assert isinstance(
            opts.get("rownames"), list
        ), "rownames should be a list with row names"

    if opts.get("jpgquality"):
        assert isnum(opts.get("jpgquality")), "JPG quality should be a number"
        assert (
            opts.get("jpgquality") > 0 and opts.get("jpgquality") <= 100
        ), "JPG quality should be number between 0 and 100"

    if opts.get("opacity"):
        assert isnum(opts.get("opacity")), "opacity should be a number"
        assert (
            0 <= opts.get("opacity") <= 1
        ), "opacity should be a number between 0 and 1"

    if opts.get("fps"):
        assert isnum(opts.get("fps")), "fps should be a number"
        assert opts.get("fps") > 0, "fps must be greater than 0"

    if opts.get("title"):
        assert isstr(opts.get("title")), "title should be a string"


torch_types = []
try:
    import torch

    torch_types.append(torch.Tensor)
    torch_types.append(torch.nn.Parameter)
except (ImportError, AttributeError):
    pass


def _to_numpy(a):
    if isinstance(a, list):
        return np.array(a)
    if len(torch_types) > 0:
        if isinstance(a, torch.autograd.Variable):
            # For PyTorch < 0.4 comptability.
            warnings.warn(
                "Support for versions of PyTorch less than 0.4 is deprecated "
                "and will eventually be removed.",
                DeprecationWarning,
            )
            a = a.data
    for kind in torch_types:
        if isinstance(a, kind):
            # For PyTorch < 0.4 comptability, where non-Variable
            # tensors do not have a 'detach' method. Will be removed.
            if hasattr(a, "detach"):
                a = a.detach()
            return a.cpu().numpy()
    return a


def pytorch_wrap(f):
    @wraps(f)
    def wrapped_f(*args, **kwargs):
        args = (_to_numpy(arg) for arg in args)
        kwargs = {k: _to_numpy(v) for (k, v) in kwargs.items()}
        return f(*args, **kwargs)

    return wrapped_f


class Visdom(object):
    def __init__(
        self,
        server="http://localhost",
        endpoint="events",
        port=8097,
        base_url="/",
        ipv6=True,
        http_proxy_host=None,
        http_proxy_port=None,
        env="main",
        send=True,
        raise_exceptions=None,
        use_incoming_socket=True,
        log_to_filename=None,
        username=None,
        password=None,
        proxies=None,
        offline=False,
        use_polling=False,
    ):
        parsed_url = urlparse(server)
        if not parsed_url.scheme:
            parsed_url = urlparse("http://{}".format(server))
        self.server_base_name = parsed_url.netloc
        self.server = urlunparse((parsed_url.scheme, parsed_url.netloc, "", "", "", ""))
        self.endpoint = endpoint
        self.port = port
        # preprocess base_url
        self.base_url = base_url if base_url != "/" else ""
        assert self.base_url == "" or self.base_url.startswith(
            "/"
        ), "base_url should start with /"
        assert self.base_url == "" or not self.base_url.endswith(
            "/"
        ), "base_url should not end with / as it is appended automatically"

        self.ipv6 = ipv6
        self.env = env
        self.env_list = {f"{env}"}  # default env
        self.send = send
        self.event_handlers = {}  # Haven't registered any events
        self.socket_alive = False
        self.socket_connection_achieved = False
        self.use_socket = use_incoming_socket or use_polling
        # Flag to indicate whether to raise errors or suppress them
        self.raise_exceptions = raise_exceptions
        self.log_to_filename = log_to_filename
        self.offline = offline
        self._session = None
        self.proxies = proxies
        self.http_proxy_host = None
        self.http_proxy_port = None
        if proxies is not None and "http" in proxies:
            self.http_proxy_host, self.http_proxy_port = proxies["http"].split(":")

        if http_proxy_host is not None or http_proxy_port is not None:
            warnings.warn(
                "HTTP Proxy Port and Host args Deprecated. " "Please use proxies arg.",
                DeprecationWarning,
            )
            self.http_proxy_host = http_proxy_host
            self.http_proxy_port = http_proxy_port

        self.username = username
        if self.username:
            assert password, "no password given for authentication"
            self.password = hashlib.sha256(password.encode("utf-8")).hexdigest()

        self.win_data = {}
        if self.offline:
            self.use_socket = False
            assert (
                self.log_to_filename is not None
            ), "Must use a log_to_filename for offline visdom"

            return  # No need for the rest of this setup in offline visdom
        # storage for data associated with specific windows

        # Setup for online interactions
        self._send(
            {
                "eid": env,
            },
            endpoint="env/" + env,
        )

        # when talking to a server, get a backchannel
        if send and use_incoming_socket:
            self.setup_socket()
        elif send and use_polling:
            self.setup_polling()
        elif send and not use_incoming_socket:
            logger.warn(
                "Without the incoming socket you cannot receive events from "
                "the server or register event handlers to your Visdom client."
            )
        # Wait for initialization before starting
        time_spent = 0
        inc = 0.1
        while self.use_socket and not self.socket_alive and time_spent < 5:
            time.sleep(inc)
            time_spent += inc
            inc *= 2
        if time_spent > 5:
            logger.warn(
                "Visdom python client failed to establish socket to get "
                "messages from the server. This feature is optional and "
                "can be disabled by initializing Visdom with "
                "`use_incoming_socket=False`, which will prevent waiting for "
                "this request to timeout."
            )

    @property
    def session(self):
        if self._session:
            return self._session
        logger.warning("Setting up a new session...")
        sess = requests.Session()
        if self.proxies:
            sess.proxies.update(self.proxies)
        if self.username:
            resp = sess.post(
                "%s:%s%s" % (self.server, self.port, self.base_url),
                json=dict(username=self.username, password=self.password),
            )
            if resp.status_code != requests.codes.ok:
                raise RuntimeError("Authentication failed")
            logger.info("Authentication succeeded")
        self._session = sess
        return sess

    def register_event_handler(self, handler, target):
        assert callable(handler), "Event handler must be a function"
        assert self.use_socket, (
            "Must be using the incoming socket to " "register events to web actions"
        )
        if target not in self.event_handlers:
            self.event_handlers[target] = []
        self.event_handlers[target].append(handler)

    def clear_event_handlers(self, target):
        self.event_handlers[target] = []

    def setup_polling(self):
        # TODO merge with setup_socket?
        # Setup socket to server
        def on_message(message):
            message = json.loads(message)
            if "command" in message:
                # Handle server commands
                if message["command"] == "alive":
                    if "data" in message and message["data"] == "vis_alive":
                        logger.info("Visdom successfully connected to server")
                        self.socket_alive = True
                        self.socket_connection_achieved = True
                    else:
                        logger.warn(
                            "Visdom server failed handshake, may not "
                            "be properly connected"
                        )
            if "target" in message:
                for handler in list(self.event_handlers.get(message["target"], [])):
                    handler(message)

        def on_close(ws):
            self.socket_alive = False

        def run_socket(*args):
            # open a socket
            resp_json = self._handle_post(
                "{0}:{1}{2}/vis_socket_wrap".format(
                    self.server, self.port, self.base_url
                ),
                data=json.dumps({"message_type": "init"}),
            )
            resp = json.loads(resp_json)
            self.vis_sid = resp["sid"]
            while self.use_socket:
                resp_json = self._handle_post(
                    "{0}:{1}{2}/vis_socket_wrap".format(
                        self.server, self.port, self.base_url
                    ),
                    data=json.dumps({"message_type": "query", "sid": self.vis_sid}),
                )
                resp = json.loads(resp_json)
                for msg in resp["messages"]:
                    on_message(msg)
                time.sleep(0.1)

        # Start listening thread
        self.socket_thread = threading.Thread(
            target=run_socket, name="Visdom-Socket-Thread"
        )
        self.socket_thread.start()

    def setup_socket(self, polling=False):
        # Setup socket to server
        def on_message(ws, message):
            message = json.loads(message)
            if "command" in message:
                # Handle server commands
                if message["command"] == "alive":
                    if "data" in message and message["data"] == "vis_alive":
                        logger.info("Visdom successfully connected to server")
                        self.socket_alive = True
                        self.socket_connection_achieved = True
                    else:
                        logger.warn(
                            "Visdom server failed handshake, may not "
                            "be properly connected"
                        )
            if "target" in message:
                for handler in list(self.event_handlers.get(message["target"], [])):
                    try:
                        handler(message)
                    except Exception as e:
                        logger.warn(
                            "Visdom failed to handle a handler for {}: {}"
                            "".format(message, e)
                        )
                        import traceback

                        traceback.print_exc()

        def on_error(ws, error):
            if hasattr(error, "errno") and error.errno == errno.ECONNREFUSED:
                if not self.socket_connection_achieved:
                    #
                    # Visdom will stop trying to use the socket only if it
                    # never succeeded in acquiring it.
                    #
                    logger.info("Socket refused connection, running socketless")
                    self.use_socket = False
            logger.error(error)
            ws.close()

        def on_close(ws):
            self.socket_alive = False

        def run_socket(*args):
            host_scheme = urlparse(self.server).scheme
            if host_scheme == "https":
                ws_scheme = "wss"
            else:
                ws_scheme = "ws"
            while self.use_socket:
                try:
                    sock_addr = "{}://{}:{}{}/vis_socket".format(
                        ws_scheme, self.server_base_name, self.port, self.base_url
                    )
                    ws = websocket.WebSocketApp(
                        sock_addr,
                        on_message=on_message,
                        on_error=on_error,
                        on_close=on_close,
                        header={
                            "Cookie: user_password="
                            + self.session.cookies.get("user_password", "")
                        },
                    )
                    ws.run_forever(
                        http_proxy_host=self.http_proxy_host,
                        http_proxy_port=self.http_proxy_port,
                        ping_timeout=100.0,
                    )
                    ws.close()
                except Exception as e:
                    logger.error("Socket had error {}, attempting restart".format(e))
                time.sleep(3)

        # Start listening thread
        self.socket_thread = threading.Thread(
            target=run_socket, name="Visdom-Socket-Thread"
        )
        self.socket_thread.daemon = True
        self.socket_thread.start()

    # Utils
    def _log(self, msg, endpoint):
        if self.log_to_filename is not None:
            if endpoint in ["events", "update"]:
                with open(self.log_to_filename, "a+") as log_file:
                    log_file.write(
                        json.dumps(
                            [
                                endpoint,
                                msg,
                            ]
                        )
                        + "\n"
                    )

    def _handle_post(self, url, data=None):
        """
        This function has the responsibility of sending the request to the
        formatted endpoint. Classes that want to wrap the visdom functionality
        but use other methodologies may override either this or _send
        """
        if data is None:
            data = {}
        r = self.session.post(url, data=data)
        return r.text

    def _send(self, msg, endpoint="events", quiet=False, from_log=False, create=True):
        """
        This function sends specified JSON request to the Tornado server. This
        function should generally not be called by the user, unless you want to
        build the required JSON yourself. `endpoint` specifies the destination
        Tornado server endpoint for the request.

        If `create=True`, then if `win=None` in the message a new window will be
        created with a random name. If `create=False`, `win=None` indicates the
        operation should be applied to all windows.
        """
        if msg.get("eid", None) is None:
            msg["eid"] = self.env
            self.env_list.add(self.env)

        if msg.get("eid", None) is not None:
            self.env_list.add(msg["eid"])

        # TODO investigate send use cases, then deprecate
        if not self.send:
            return msg, endpoint

        if "win" in msg and msg["win"] is None and create:
            msg["win"] = "window_" + get_rand_id()

        if not from_log:
            self._log(msg, endpoint)

        if self.offline:
            # If offline, don't even try to post
            return msg["win"] if "win" in msg else True

        try:
            return self._handle_post(
                "{0}:{1}{2}/{3}".format(
                    self.server, self.port, self.base_url, endpoint
                ),
                data=json.dumps(msg),
            )
        except (requests.RequestException, requests.ConnectionError, requests.Timeout):
            if self.raise_exceptions:
                raise ConnectionError("Error connecting to Visdom server")
            else:
                if self.raise_exceptions is None:
                    warnings.warn(
                        "Visdom is eventually changing to default to raising "
                        "exceptions rather than ignoring/printing. This change"
                        " is expected to happen by July 2018. Please set "
                        "`raise_exceptions` to False to retain current "
                        "behavior.",
                        PendingDeprecationWarning,
                    )
                if not quiet:
                    print("Exception in user code:")
                    print("-" * 60)
                    traceback.print_exc()
                return False

    def save(self, envs):
        """
        This function allows the user to save envs that are alive on the
        Tornado server. The envs can be specified as a list of env ids.
        """
        assert isinstance(envs, list), "envs should be a list"
        if len(envs) > 0:
            for env in envs:
                assert isstr(env), "env should be a string"

        return self._send(
            {
                "data": envs,
            },
            "save",
        )

    def fork_env(self, prev_eid, eid):
        """This function allows the user to fork environments."""
        assert isstr(prev_eid), "prev_eid should be a string"
        assert isstr(eid), "eid should be a string"

        return self._send(msg={"prev_eid": prev_eid, "eid": eid}, endpoint="fork_env")

    def get_window_data(self, win=None, env=None):
        """
        This function returns all the window data for a specified window in
        an environment. Use `win=None` to get all the windows in the given
        environment. Env defaults to main
        """

        return self._send(
            msg={"win": win, "eid": env},
            endpoint="win_data",
            create=False,
        )

    def set_window_data(self, data, win=None, env=None):
        """
        This function sets all the window data for a specified window in
        an environment. Use `win=None` to set the data for all the windows in
        the given environment. Env defaults to main. `data` should be as returned
        from `get_window_data`.
        """
        return self._send(
            msg={"win": win, "eid": env, "data": data},
            endpoint="win_data",
            create=False,
        )

    def close(self, win=None, env=None):
        """
        This function closes a specific window.
        Use `win=None` to close all windows in an env.
        """

        return self._send(
            msg={"win": win, "eid": env},
            endpoint="close",
            create=False,
        )

    def delete_env(self, env):
        """This function deletes a specific environment."""
        return self._send(msg={"eid": env}, endpoint="delete_env")

    def _win_exists_wrap(self, win, env=None):
        """
        This function returns a string indicating whether
        or not a window exists on the server already. ['true' or 'false']
        Returns False if something went wrong
        """
        assert win is not None

        return self._send(
            {
                "win": win,
                "eid": env,
            },
            endpoint="win_exists",
            quiet=True,
        )

    def get_env_list(self):
        """
        This function returns a list of all of the env names that are currently
        in the server.
        """
        if self.offline:
            return list(self.env_list)
        else:
            return json.loads(self._send({}, endpoint="env_state", quiet=True))

    def win_exists(self, win, env=None):
        """
        This function returns a bool indicating whether
        or not a window exists on the server already.
        Returns None if something went wrong
        """
        try:
            e = self._win_exists_wrap(win, env)
        except ConnectionError:
            print("Error connecting to Visdom server!")
            return None

        if e == "true":
            return True
        elif e == "false":
            return False
        else:
            return None

    def _win_hash_wrap(self, win, env=None):
        """
        This function returns a hash of the contents of
        the window if the window exists.
        Return None otherwise.
        """
        assert win is not None

        return self._send(
            {
                "win": win,
                "env": env,
            },
            endpoint="win_hash",
            quiet=True,
        )

    def win_hash(self, win, env=None):
        """
        This function returns md5 hash of the contents
        of a window if it exists on the server.
        Returns None, otherwise
        """
        try:
            e = self._win_hash_wrap(win, env)
        except ConnectionError:
            print("Error connecting to Visdom server!")
            return None

        if re.match(r"([a-fA-F\d]{32})", e):
            return e

        return None

    def _has_connection(self):
        """
        This function returns a bool indicating whether or
        not the server is connected.
        """
        return (self.win_exists("") is not None) and (
            self.socket_alive or not self.use_socket
        )

    def check_connection(self, timeout_seconds=0):
        """
        This function returns a bool indicating whether or
        not the server is connected within some timeout. It waits for
        timeout_seconds before determining if the server responds.
        """
        while not self._has_connection() and timeout_seconds > 0:
            time.sleep(0.1)
            timeout_seconds -= 0.1
            print("waiting")

        return self._has_connection()

    def replay_log(self, log_filename):
        """
        This function takes the contents of a visdom log and replays them to
        the current server to restore the state or handle any missing entries.
        """
        with open(log_filename) as f:
            log_entries = f.readlines()
        for entry in log_entries:
            endpoint, msg = json.loads(entry)
            self._send(msg, endpoint, from_log=True)

    # Content

    def text(self, text, win=None, env=None, opts=None, append=False):
        """
        This function prints text in a box. It takes as input an `text` string.
        No specific `opts` are currently supported.
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)
        data = [{"content": text, "type": "text"}]

        if append:
            endpoint = "update"
        else:
            endpoint = "events"

        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "opts": opts,
            },
            endpoint=endpoint,
        )

    def properties(self, data, win=None, env=None, opts=None):
        """
        This function shows editable properties in a pane.
        Properties are expected to be a List of Dicts e.g.:
        ```
            properties = [
                {'type': 'text', 'name': 'Text input', 'value': 'initial'},
                {'type': 'number', 'name': 'Number input', 'value': '12'},
                {'type': 'button', 'name': 'Button', 'value': 'Start'},
                {'type': 'checkbox', 'name': 'Checkbox', 'value': True},
                {'type': 'select', 'name': 'Select', 'value': 1,
                 'values': ['Red', 'Green', 'Blue']},
            ]
        ```
        Supported types:
         - text: string
         - number: decimal number
         - button: button labeled with "value"
         - checkbox: boolean value rendered as a checkbox
         - select: multiple values select box
            - `value`: id of selected value (zero based)
            - `values`: list of possible values

        Callback are called on property value update:
         - `event_type`: `"PropertyUpdate"`
         - `propertyId`: position in the `properties` list
         - `value`: new value

        No specific `opts` are currently supported.
        """
        opts = {} if opts is None else opts
        _assert_opts(opts)
        data = [{"content": data, "type": "properties"}]

        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "opts": opts,
            },
            endpoint="events",
        )

    @pytorch_wrap
    def svg(self, svgstr=None, svgfile=None, win=None, env=None, opts=None):
        """
        This function draws an SVG object. It takes as input an SVG string or
        the name of an SVG file. The function does not support any
        plot-specific `opts`.
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        if svgfile is not None:
            svgstr = str(loadfile(svgfile))

        assert svgstr is not None, "should specify SVG string or filename"
        svg = re.search("<svg .+</svg>", svgstr, re.DOTALL)
        assert svg is not None, "could not parse SVG string"
        return self.text(text=svg.group(0), win=win, env=env, opts=opts)

    def matplot(self, plot, opts=None, env=None, win=None):
        """
        This function draws a Matplotlib `plot`. The function supports
        one plot-specific option: `resizable`. When set to `True` the plot
        is resized with the pane. You need `beautifulsoup4` and `lxml`
        packages installed to use this option.
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        # write plot to SVG buffer:
        buffer = StringIO()
        plot.savefig(buffer, format="svg")
        buffer.seek(0)
        svg = buffer.read()
        buffer.close()

        if opts.get("resizable", False):
            if not BS4_AVAILABLE:
                raise ImportError("No module named 'bs4'")
            else:
                try:
                    soup = bs4.BeautifulSoup(svg, "xml")
                except bs4.FeatureNotFound as e:
                    import six

                    six.raise_from(ImportError("No module named 'lxml'"), e)
                height = soup.svg.attrs.pop("height", None)
                width = soup.svg.attrs.pop("width", None)
                svg = str(soup)
        else:
            height = None
            width = None

        # show SVG:
        if "height" not in opts:
            height = height or re.search(r'height\="([0-9\.]*)pt"', svg)
            if height is not None:
                if not isstr(height):
                    height = height.group(1)
                height = height.replace("pt", "00")
                opts["height"] = 1.4 * int(math.ceil(float(height)))
        if "width" not in opts:
            width = width or re.search(r'width\="([0-9\.]*)pt"', svg)
            if width is not None:
                if not isstr(width):
                    width = width.group(1)
                width = width.replace("pt", "00")
                opts["width"] = 1.35 * int(math.ceil(float(width)))
        return self.svg(svgstr=svg, opts=opts, env=env, win=win)

    def plotlyplot(self, figure, win=None, env=None):
        """
        This function draws a Plotly 'Figure' object. It does not explicitly
        take options as it assumes you have already explicitly configured the
        figure's layout.

        Note: You must have the 'plotly' Python package installed to use
        this function.
        """
        try:
            import plotly

            # We do a round-trip of JSON encoding and decoding to make use of
            # the Plotly JSON Encoder. The JSON encoder deals with converting
            # numpy arrays to Python lists and several other edge cases.
            figure_dict = json.loads(
                json.dumps(figure, cls=plotly.utils.PlotlyJSONEncoder)
            )

            # If opts title is not added, the title is not added to the top right of the window.
            # We add the paramater to opts manually if it exists.
            opts = dict()
            if "title" in figure_dict["layout"]:
                title_prop = figure_dict["layout"]["title"]

                # The title is now officially under a 'text' subproperty. Previously, the property
                # itself could also directly reference the title.
                # Although this latter behavior is now deprecated, we support both possibilities.
                # Docs reference: https://plot.ly/python/reference/#layout-title-text
                opts["title"] = (
                    title_prop["text"] if "text" in title_prop else title_prop
                )

            return self._send(
                {
                    "data": figure_dict["data"],
                    "layout": figure_dict["layout"],
                    "win": win,
                    "eid": env,
                    "opts": opts,
                }
            )
        except ImportError:
            raise RuntimeError("Plotly must be installed to plot Plotly figures")

    def _register_embeddings(
        self, features, labels, points, data_getter, data_type, win, env, opts
    ):
        self.win_data[win] = {
            "features": features,
            "labels": labels,
            "points": points,
            "data": data_getter,
            "data_type": data_type,
            "env": env,
            "opts": opts,
        }

        def embedding_event_handler(event):
            window = event["target"]
            if event["event_type"] == "EntitySelected":
                # Hover events lead us to get the expected element and serve
                # them via an append event
                entity_id = event["entityId"]
                id = event["idx"]
                if data_getter is not None:
                    if data_type == "html":
                        selected = {"html": data_getter(int(id))}
                else:
                    selected = {"html": "<div>No preview available</div>"}

                selected["entityId"] = entity_id
                send_data = {"update_type": "EntitySelected", "selected": selected}
                self._send(
                    {
                        "data": send_data,
                        "win": window,
                        "eid": env,
                        "opts": opts,
                    },
                    endpoint="update",
                )
            elif event["event_type"] == "RegionSelected":
                # lasso events give us a subset of the data to re-run tsne on
                # so we generate
                selection = event["selectedIdxs"]
                sub_features = np.take(features, selection, axis=0)
                Y = do_tsne(sub_features)
                label_set = list(set(labels))
                points = [
                    {
                        "group": int(label_set.index(labels[i])),
                        "name": "Entity {}".format(i),
                        "position": xy,
                        "label": labels[i],
                        "idx": i,
                    }
                    for i, xy in zip(selection, Y)
                ]
                send_data = {
                    "update_type": "RegionSelected",
                    "points": points,
                }
            else:
                return  # Unsupported event
            self._send(
                {
                    "data": send_data,
                    "win": window,
                    "eid": env,
                    "opts": opts,
                },
                endpoint="update",
            )

        self.register_event_handler(embedding_event_handler, win)

    def embeddings(
        self,
        features,
        labels,
        data_getter=None,
        data_type=None,
        win=None,
        env=None,
        opts=None,
    ):
        """
        This function handles taking arbitrary features and compiling them into
        a set of embeddings. It then leverages the _register_embeddings to
        actually run the visualization.

        We assume that there are no more than 10 unique labels at the moment,
        in the future we can include a colormap in opts for other cases

        If you want to provide a preview on hover for your data, you can supply
        a getting function for data_getter and a data_type. At the moment the
        only data_type supported is 'html', which means your data_getter takes
        in an index into features that is currently selected and returns
        the html for what you'd like to display.
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        loading_message = {
            "content": {"isLoading": True},
            "type": "embeddings",
        }
        win = self._send(
            {
                "data": [loading_message],
                "win": win,
                "eid": env,
                "opts": opts,
            },
            endpoint="events",
        )

        Y = do_tsne(features)

        label_set = list(set(labels))
        points = [
            {
                "group": int(label_set.index(labels[i])),
                "name": "Entity {}".format(i),
                "label": labels[i],
                "position": xy,
                "idx": i,
            }
            for i, xy in enumerate(Y)
        ]
        send_data = [
            {
                "content": {"data": points},
                "type": "embeddings",
            }
        ]

        win = self._send(
            {
                "data": send_data,
                "win": win,
                "eid": env,
                "opts": opts,
            },
            endpoint="events",
        )

        # Register the handlers for managing this embeddings pane
        # TODO allow disabling this in a way that pushes onus for calculating
        # to the server or frontend client
        self._register_embeddings(
            features, labels, points, data_getter, data_type, win, env, opts
        )
        return win

    @pytorch_wrap
    def image(self, img, win=None, env=None, opts=None):
        """
        This function draws an img. It takes as input an `CxHxW` or `HxW` tensor
        `img` that contains the image. The array values can be float in [0,1] or
        uint8 in [0, 255].
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)
        opts["width"] = opts.get("width", img.shape[img.ndim - 1])
        opts["height"] = opts.get("height", img.shape[img.ndim - 2])

        nchannels = img.shape[0] if img.ndim == 3 else 1
        if nchannels == 1:
            img = np.squeeze(img)
            img = img[np.newaxis, :, :].repeat(3, axis=0)

        if "float" in str(img.dtype):
            if img.max() <= 1:
                img = img * 255.0
            img = np.uint8(img)

        img = np.transpose(img, (1, 2, 0))
        im = Image.fromarray(img)
        buf = BytesIO()
        image_type = "png"
        imsave_args = {}
        if "jpgquality" in opts:
            image_type = "jpeg"
            imsave_args["quality"] = opts["jpgquality"]

        im.save(buf, format=image_type.upper(), **imsave_args)

        b64encoded = b64.b64encode(buf.getvalue()).decode("utf-8")

        data = [
            {
                "content": {
                    "src": "data:image/" + image_type + ";base64," + b64encoded,
                    "caption": opts.get("caption"),
                },
                "type": "image_history" if opts.get("store_history") else "image",
            }
        ]

        endpoint = "events"
        if opts.get("store_history"):
            if win is not None and self.win_exists(win, env):
                endpoint = "update"

        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "opts": opts,
            },
            endpoint=endpoint,
        )

    @pytorch_wrap
    def images(self, tensor, nrow=8, padding=2, win=None, env=None, opts=None):
        """
        Given a 4D tensor of shape (B x C x H x W),
        or a list of images all of the same size,
        makes a grid of images of size (B / nrow, nrow).


        This is a modified from `make_grid()`
        https://github.com/pytorch/vision/blob/master/torchvision/utils.py
        """

        # If list of images, convert to a 4D tensor
        if isinstance(tensor, list):
            tensor = np.stack(tensor, 0)

        if tensor.ndim == 2:  # single image H x W
            tensor = np.expand_dims(tensor, 0)
        if tensor.ndim == 3:  # single image
            if tensor.shape[0] == 1:  # if single-channel, convert to 3-channel
                tensor = np.repeat(tensor, 3, 0)
            return self.image(tensor, win, env, opts)
        if tensor.ndim == 4 and tensor.shape[1] == 1:  # single-channel images
            tensor = np.repeat(tensor, 3, 1)

        # make 4D tensor of images into a grid
        nmaps = tensor.shape[0]
        xmaps = min(nrow, nmaps)
        ymaps = int(math.ceil(float(nmaps) / xmaps))
        height = int(tensor.shape[2] + 2 * padding)
        width = int(tensor.shape[3] + 2 * padding)

        grid = np.ones([tensor.shape[1], height * ymaps, width * xmaps])
        k = 0
        for y in range(ymaps):
            for x in range(xmaps):
                if k >= nmaps:
                    break
                h_start = y * height + 1 + padding
                h_end = h_start + tensor.shape[2]
                w_start = x * width + 1 + padding
                w_end = w_start + tensor.shape[3]
                grid[:, h_start:h_end, w_start:w_end] = tensor[k]
                k += 1

        return self.image(grid, win, env, opts)

    @pytorch_wrap
    def audio(self, tensor=None, audiofile=None, win=None, env=None, opts=None):
        """
        This function plays audio. It takes as input the filename of the audio
        file or an `N` tensor containing the waveform (use an `Nx2` matrix for
        stereo audio). The function does not support any plot-specific `opts`.

        The following `opts` are supported:

        - `opts.sample_frequency`: sample frequency (`integer` > 0; default = 44100)
        """
        opts = {} if opts is None else opts
        opts["sample_frequency"] = opts.get("sample_frequency", 44100)
        _title2str(opts)
        _assert_opts(opts)
        assert (
            tensor is not None or audiofile is not None
        ), "should specify audio tensor or file"
        if tensor is not None:
            assert tensor.ndim == 1 or (
                tensor.ndim == 2 and tensor.shape[1] == 2
            ), "tensor should be 1D vector or 2D matrix with 2 columns"

        if tensor is not None:
            import scipy.io.wavfile  # type: ignore
            import tempfile

            audiofile = os.path.join(
                tempfile.gettempdir(), "%s.wav" % next(tempfile._get_candidate_names())
            )
            tensor = np.int16(tensor / np.max(np.abs(tensor)) * 32767)
            scipy.io.wavfile.write(audiofile, opts.get("sample_frequency"), tensor)

        extension = audiofile.split(".")[-1].lower()
        mimetypes = {"wav": "wav", "mp3": "mp3", "ogg": "ogg", "flac": "flac"}
        mimetype = mimetypes.get(extension)
        assert mimetype is not None, "unknown audio type: %s" % extension

        bytestr = loadfile(audiofile)
        audiodata = """
            <audio controls>
                <source type="audio/%s" src="data:audio/%s;base64,%s">
                Your browser does not support the audio tag.
            </audio>
        """ % (
            mimetype,
            mimetype,
            base64.b64encode(bytestr).decode("utf-8"),
        )
        opts["height"] = 80
        opts["width"] = 330
        return self.text(text=audiodata, win=win, env=env, opts=opts)

    def _encode(self, tensor, fps):
        """
        This follows the [PyAV cookbook]
        (http://docs.mikeboers.com/pyav/develop/cookbook/numpy.html#generating-video)
        """
        import av  # type: ignore

        # Float tensors are assumed to have a domain of [0, 1], for
        # backward-compatibility with OpenCV.
        if np.issubdtype(tensor.dtype, np.floating):
            tensor = 255 * tensor
        tensor = tensor.astype(np.uint8).clip(0, 255)

        # Use BGR for backward-compatibility with OpenCV
        pixelformats = {1: "gray", 3: "bgr24"}
        pixelformat = pixelformats[tensor.shape[3]]

        content = BytesIO()
        container = av.open(content, "w", "mp4")

        stream = container.add_stream("h264", rate=fps)
        stream.height = tensor.shape[1]
        stream.width = tensor.shape[2]
        stream.pix_fmt = "yuv420p"

        for arr in tensor:
            frame = av.VideoFrame.from_ndarray(arr, format=pixelformat)
            container.mux(stream.encode(frame))
        # Flushing the stream here causes a deprecation warning in ffmpeg
        # https://ffmpeg.zeranoe.com/forum/viewtopic.php?t=3678
        # It's old and benign and possibly only apparent in homebrew-installed ffmpeg?
        container.mux(stream.encode())

        container.close()
        content = content.getvalue()

        return content, "mp4"

    @pytorch_wrap
    def video(
        self, tensor=None, dim="LxHxWxC", videofile=None, win=None, env=None, opts=None
    ):
        """
        This function plays a video. It takes as input the filename of the video
        `videofile` or a `LxHxWxC` or `LxCxHxW`-sized `tensor` containing all
        the frames of the video as input, as specified in `dim`. The color
        channels must be in BGR order.

        Internally, video encoding is done with [PyAV]
        (http://docs.mikeboers.com/pyav/develop/installation.html).
        The import is deferred as it's a dependency most Visdom users won't encounter.

        The function does not support any plot-specific `opts`. The following
        video `opts` are supported:

        - `opts.fps`: FPS for the video (`integer` > 0; default = 25)
        - `opts.autoplay`: whether to autoplay the video when ready (`boolean`; default = `false`)
        - `opts.loop`: whether to loop the video (`boolean`; default = `false`)
        """
        opts = {} if opts is None else opts
        opts["fps"] = opts.get("fps", 25)
        opts["loop"] = opts.get("loop", False)
        opts["autoplay"] = opts.get("autoplay", False)
        _title2str(opts)
        _assert_opts(opts)
        assert (
            tensor is not None or videofile is not None
        ), "should specify video tensor or file"

        if tensor is None:
            extension = videofile.split(".")[-1].lower()
            mimetypes = {"mp4": "mp4", "ogv": "ogg", "avi": "avi", "webm": "webm"}
            mimetype = mimetypes.get(extension)
            assert mimetype is not None, "unknown video type: %s" % extension
            bytestr = loadfile(videofile)
        else:
            assert tensor.ndim == 4, "video should be in 4D tensor"
            assert (
                dim == "LxHxWxC" or dim == "LxCxHxW"
            ), "dimension argument should be LxHxWxC or LxCxHxW"
            if dim == "LxCxHxW":
                tensor = tensor.transpose([0, 2, 3, 1])
            bytestr, mimetype = self._encode(tensor, opts["fps"])

        flags = " ".join([k for k in ("autoplay", "loop") if opts[k]])

        videodata = """
            <video controls %s>
                <source type="video/%s" src="data:video/%s;base64,%s">
                Your browser does not support the video tag.
            </video>
        """ % (
            flags,
            mimetype,
            mimetype,
            base64.b64encode(bytestr).decode("utf-8"),
        )
        return self.text(text=videodata, win=win, env=env, opts=opts)

    def update_window_opts(self, win, opts, env=None):
        """
        This function allows pushing new options to an existing plot window
        without updating the content
        """
        data_to_send = {
            "win": win,
            "eid": env,
            "layout": _opts2layout(opts),
            "opts": opts,
        }
        return self._send(data_to_send, endpoint="update")

    @pytorch_wrap
    def scatter(self, X, Y=None, win=None, env=None, opts=None, update=None, name=None):
        """
        This function draws a 2D or 3D scatter plot. It takes in an `Nx2` or
        `Nx3` tensor `X` that specifies the locations of the `N` points in the
        scatter plot. An optional `N` tensor `Y` containing discrete labels that
        range between `1` and `K` can be specified as well -- the labels will be
        reflected in the colors of the markers.

        `update` can be used to efficiently update the data of an existing plot.
        Use 'append' to append data, 'replace' to use new data, and 'remove' to
        delete the trace that is specified in `name`. If updating a single
        trace, use `name` to specify the name of the trace to be updated.
        Update data that is all NaN is ignored (can be used for masking update).
        Using `update='append'` will create a plot if it doesn't exist
        and append to the existing plot otherwise.

        The following `opts` are supported:

        - `opts.markersymbol`     : marker symbol (`string`; default = `'dot'`)
        - `opts.markersize`       : marker size (`number`; default = `'10'`)
        - `opts.markercolor`      : marker color (`np.array`; default = `None`)
        - `opts.markerborderwidth`: marker border line width (`float`; default = 0.5)
        - `opts.dash`             : dash type (`np.array`; default = 'solid'`)
        - `opts.textlabels`       : text label for each point (`list`: default = `None`)
        - `opts.legend`           : `list` or `tuple` containing legend names
        """
        if update == "remove":
            assert win is not None
            assert name is not None, "A trace must be specified for deletion"
            assert opts is None, "Opts cannot be updated on trace deletion"
            data_to_send = {
                "data": [],
                "name": name,
                "delete": True,
                "win": win,
                "eid": env,
            }

            return self._send(data_to_send, endpoint="update")

        elif update is not None:
            assert win is not None, "Must define a window to update"

            if update == "append":
                if win is None:
                    update = None
                elif not self.offline:
                    exists = self.win_exists(win, env)
                    if exists is False:
                        update = None
            # case when X is 1 dimensional and corresponding values on y-axis
            # are passed in parameter Y
            if name:
                assert len(name) >= 0, "name of trace should be non-empty string"
                assert X.ndim == 1 or X.ndim == 2, (
                    "updating by name should" "have 1-dim or 2-dim X."
                )
                if X.ndim == 1:
                    assert (
                        Y.ndim == 1
                    ), "update by name should have 1-dim Y when X is 1-dim"
                    assert X.shape[0] == Y.shape[0], "X and Y should have same shape"
                    X = np.column_stack((X, Y))
                    Y = None

        assert X.ndim == 2, "X should have two dims"
        assert X.shape[1] == 2 or X.shape[1] == 3, "X should have 2 or 3 cols"

        if Y is not None:
            Y = np.ravel(Y)
            assert X.shape[0] == Y.shape[0], "sizes of X and Y should match"
            assert np.equal(np.mod(Y, 1), 0).all(), "labels should be integers"
            assert Y.min() >= 1, "labels are assumed to be at least 1"
            labels = np.unique(Y.astype(int, copy=False))
            assert (
                len(labels) == 1 or name is None
            ), "name should not be specified with multiple labels or lines"
            K = int(Y.max())  # largest label
        else:
            Y = np.ones(X.shape[0], dtype=int)
            labels = np.ones(1, dtype=int)
            K = 1  # largest label

        is3d = X.shape[1] == 3

        opts = {} if opts is None else opts
        if opts.get("textlabels") is None:
            opts["mode"] = opts.get("mode", "markers")
        else:
            opts["mode"] = opts.get("mode", "markers+text")
        opts["markersymbol"] = opts.get("markersymbol", "dot")
        opts["markersize"] = opts.get("markersize", 10)
        opts["markerborderwidth"] = opts.get("markerborderwidth", 0.5)

        if opts.get("markercolor") is not None:
            opts["markercolor"] = _markerColorCheck(opts["markercolor"], X, Y, K)

        if opts.get("linecolor") is not None:
            opts["linecolor"] = _lineColorCheck(opts["linecolor"], K)

        if opts.get("dash") is not None:
            opts["dash"] = _dashCheck(opts["dash"], K)

        L = opts.get("textlabels")
        if L is not None:
            L = np.ravel(L)
            assert len(L) == X.shape[0], "textlabels and X should have same shape"

        _title2str(opts)
        _assert_opts(opts)

        if opts.get("legend"):
            assert isinstance(opts["legend"], (tuple, list)) and K <= len(
                opts["legend"]
            ), ("largest label should not be greater than size of " "the legends table")

        data = []
        trace_opts = opts.get("traceopts", {"plotly": {}})["plotly"]
        dash = opts.get("dash")
        mc = opts.get("markercolor")
        lc = opts.get("linecolor")

        for k in labels:
            ind = np.equal(Y, k)
            if ind.any():
                if "legend" in opts:
                    trace_name = opts.get("legend")[k - 1]
                elif len(labels) == 1 and name is not None:
                    trace_name = name
                else:
                    trace_name = str(k)
                use_gl = opts.get("webgl", False)
                _data = {
                    "x": nan2none(X.take(0, 1)[ind].tolist()),
                    "y": nan2none(X.take(1, 1)[ind].tolist()),
                    "name": trace_name,
                    "type": "scatter3d"
                    if is3d
                    else ("scattergl" if use_gl else "scatter"),
                    "mode": opts.get("mode"),
                    "text": L[ind].tolist() if L is not None else None,
                    "textposition": "right",
                    "line": {
                        "dash": dash[k - 1] if dash is not None else None,
                        "color": lc[k - 1] if lc is not None else None,
                    },
                    "marker": {
                        "size": opts.get("markersize"),
                        "symbol": opts.get("markersymbol"),
                        "color": mc[k] if mc is not None else None,
                        "line": {
                            "color": "#000000",
                            "width": opts.get("markerborderwidth"),
                        },
                    },
                }
                if opts.get("fillarea"):
                    _data["fill"] = "tonexty"

                if is3d:
                    _data["z"] = X.take(2, 1)[ind].tolist()

                if trace_name in trace_opts:
                    _data.update(trace_opts[trace_name])

                data.append(_scrub_dict(_data))

        if opts:
            for marker_prop in ["markercolor"]:
                if marker_prop in opts:
                    del opts[marker_prop]
            for line_prop in ["linecolor"]:
                if line_prop in opts:
                    del opts[line_prop]
            for dash in ["dash"]:
                if dash in opts:
                    del opts[dash]

        # Only send updates to the layout on the first plot, future updates
        # need to use `update_window_opts`
        data_to_send = {
            "data": data,
            "win": win,
            "eid": env,
            "layout": _opts2layout(opts, is3d) if update is None else {},
            "opts": opts,
        }
        endpoint = "events"
        if update:
            data_to_send["name"] = name
            data_to_send["append"] = update == "append"
            endpoint = "update"

        return self._send(data_to_send, endpoint=endpoint)

    @pytorch_wrap
    def line(self, Y, X=None, win=None, env=None, opts=None, update=None, name=None):
        """
        This function draws a line plot. It takes in an `N` or `NxM` tensor
        `Y` that specifies the values of the `M` lines (that connect `N` points)
        to plot. It also takes an optional `X` tensor that specifies the
        corresponding x-axis values; `X` can be an `N` tensor (in which case all
        lines will share the same x-axis values) or have the same size as `Y`.

        `update` can be used to efficiently update the data of an existing line.
        Use 'append' to append data, 'replace' to use new data, and 'remove' to
        delete the trace that is specified in `name`. If updating a
        single trace, use `name` to specify the name of the trace to be updated.
        Update data that is all NaN is ignored (can be used for masking update).
        Using `update='append'` will create a plot if it doesn't exist
        and append to the existing plot otherwise.

        The following `opts` are supported:

        - `opts.fillarea`    : fill area below line (`boolean`)
        - `opts.markers`     : show markers (`boolean`; default = `false`)
        - `opts.markersymbol`: marker symbol (`string`; default = `'dot'`)
        - `opts.markersize`  : marker size (`number`; default = `'10'`)
        - `opts.linecolor`   : line colors (`np.array`; default = None)
        - `opts.dash`        : line dash type (`np.array`; default = None)
        - `opts.legend`      : `list` or `tuple` containing legend names

        If `update` is specified, the figure will be updated without
        creating a new plot -- this can be used for efficient updating.
        """
        if update is not None:
            if update == "remove":
                return self.scatter(
                    X=None,
                    Y=None,
                    opts=opts,
                    win=win,
                    env=env,
                    update=update,
                    name=name,
                )
            else:
                assert X is not None, "must specify x-values for line update"
        assert Y.ndim == 1 or Y.ndim == 2, "Y should have 1 or 2 dim"
        assert Y.shape[-1] > 0, "must plot one line at least"

        if X is not None:
            assert X.ndim == 1 or X.ndim == 2, "X should have 1 or 2 dim"
        else:
            X = np.linspace(0, 1, Y.shape[0])

        if Y.ndim == 2 and X.ndim == 1:
            X = np.tile(X, (Y.shape[1], 1)).transpose()

        assert X.shape == Y.shape, "X and Y should be the same shape"

        opts = {} if opts is None else opts
        opts["markers"] = opts.get("markers", False)
        opts["fillarea"] = opts.get("fillarea", False)
        opts["mode"] = "lines+markers" if opts.get("markers") else "lines"

        _title2str(opts)
        _assert_opts(opts)

        if Y.ndim == 1:
            linedata = np.column_stack((X, Y))
        else:
            linedata = np.column_stack((X.ravel(order="F"), Y.ravel(order="F")))

        labels = None
        if Y.ndim == 2:
            labels = np.arange(1, Y.shape[1] + 1)
            labels = np.tile(labels, (Y.shape[0], 1)).ravel(order="F")

        return self.scatter(
            X=linedata, Y=labels, opts=opts, win=win, env=env, update=update, name=name
        )

    @pytorch_wrap
    def heatmap(self, X, win=None, env=None, update=None, opts=None):
        """
        This function draws a heatmap. It takes as input an `NxM` tensor `X`
        that specifies the value at each location in the heatmap.

        `update` can be used to efficiently update the data of an existing plot
        saved to a window given by `win`. Use the value 'appendRow' to append
        data row-wise, 'appendRow' to append data row-wise, 'appendColumn' to
        append data column-wise, 'prependRow' to prepend data row-wise,
        'prependColumn' to append data column-wise, 'replace' to use new data,
        and 'remove' to delete the plot. Using `update=appendRow` or
        `update='appendColumn'` will create a plot if it doesn't exist and
        append to the existing plot otherwise.

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `opts.xmax`    : clip maximum value (`number`; default = `X:max()`)
        - `opts.columnnames`: `list` containing x-axis labels
        - `opts.rownames`: `list` containing y-axis labels
        - `opts.nancolor`: if not None, color for plotting nan
                           (`string`; default = `None`)
        """
        validUpdateValues = [
            None,
            "replace",
            "remove",
            "appendRow",
            "appendColumn",
            "prependRow",
            "prependColumn",
        ]
        assert (
            update in validUpdateValues
        ), "update needs to take one of the following values: %s" % ", ".join(
            "'%s'" % str(s) if s is not None else "None" for s in validUpdateValues
        )
        is_appending = update in validUpdateValues[3:]

        if update == "remove":
            assert win is not None
            data_to_send = {
                "data": [],
                "delete": True,
                "win": win,
                "eid": env,
            }
            return self._send(data_to_send, endpoint="update")

        assert X.ndim == 2, "data should be two-dimensional"
        opts = {} if opts is None else opts
        opts["colormap"] = opts.get("colormap", "Viridis")
        _title2str(opts)
        _assert_opts(opts)

        if opts.get("columnnames") is not None:
            assert (
                len(opts["columnnames"]) == X.shape[1]
            ), "number of column names should match number of columns in X"

        if opts.get("rownames") is not None:
            assert (
                len(opts["rownames"]) == X.shape[0]
            ), "number of row names should match number of rows in X"

        data = [
            {
                "z": nan2none(X.tolist()),
                "x": opts.get("columnnames"),
                "y": opts.get("rownames"),
                "zmin": opts.get("xmin"),
                "zmax": opts.get("xmax"),
                "type": "heatmap",
                "colorscale": opts.get("colormap"),
            }
        ]

        nancolor = opts.get("nancolor")
        if nancolor is not None:
            # nan is plotted as transparent, so we just plot another trace as
            # background, before plotting real data.
            nantrace = {
                "z": np.zeros_like(X).tolist(),
                "x": data[0]["x"],
                "y": data[0]["y"],
                "type": "heatmap",
                "showscale": False,
                "colorscale": [[0, nancolor], [1, nancolor]],
            }
            data.insert(0, nantrace)

        # Only send updates to the layout on the first plot, future updates
        # need to use `update_window_opts`
        endpoint = "events"
        data_to_send = {
            "data": data,
            "win": win,
            "eid": env,
            "layout": _opts2layout(opts) if update is None else {},
            "opts": opts,
        }
        endpoint = "events"
        if update:
            data_to_send["append"] = is_appending
            data_to_send["updateDir"] = update
            endpoint = "update"

        return self._send(data_to_send, endpoint=endpoint)

    @pytorch_wrap
    def bar(self, X, Y=None, win=None, env=None, opts=None):
        """
        This function draws a regular, stacked, or grouped bar plot. It takes as
        input an `N` or `NxM` tensor `X` that specifies the height of each
        bar. If `X` contains `M` columns, the values corresponding to each row
        are either stacked or grouped (dependending on how `opts.stacked` is
        set). In addition to `X`, an (optional) `N` tensor `Y` can be specified
        that contains the corresponding x-axis values.

        The following plot-specific `opts` are currently supported:

            - `opts.rownames`: `list` containing x-axis labels
        - `opts.stacked` : stack multiple columns in `X`
            - `opts.legend`  : `list` containing legend labels
        """
        X = np.squeeze(X)
        assert X.ndim == 1 or X.ndim == 2, "X should be one or two-dimensional"
        if X.ndim == 1:
            if opts is not None and opts.get("legend") is not None:
                X = X[None, :]
                assert (
                    opts.get("rownames") is None
                ), "both rownames and legend cannot be specified \
                    for one-dimensional X values"
            else:
                X = X[:, None]
        if Y is not None:
            Y = np.squeeze(Y)
            assert Y.ndim == 1, "Y should be one-dimensional"
            assert len(X) == len(Y), "sizes of X and Y should match"
        else:
            Y = np.arange(1, len(X) + 1)

        opts = {} if opts is None else opts
        opts["stacked"] = opts.get("stacked", False)

        _title2str(opts)
        _assert_opts(opts)

        if opts.get("rownames") is not None:
            assert (
                len(opts["rownames"]) == X.shape[0]
            ), "number of row names should match number of rows in X"

        if opts.get("legend") is not None:
            assert (
                len(opts["legend"]) == X.shape[1]
            ), "number of legend labels must match number of columns in X"

        data = []
        for k in range(X.shape[1]):
            _data = {
                "y": X.take(k, 1).tolist(),
                "x": opts.get("rownames", Y.tolist()),
                "type": "bar",
            }
            if opts.get("legend"):
                _data["name"] = opts["legend"][k]
            data.append(_data)

        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "layout": _opts2layout(opts),
                "opts": opts,
            }
        )

    @pytorch_wrap
    def histogram(self, X, win=None, env=None, opts=None):
        """
        This function draws a histogram of the specified data. It takes as input
        an `N` tensor `X` that specifies the data of which to construct the
        histogram.

        The following plot-specific `opts` are currently supported:

        - `opts.numbins`: number of bins (`number`; default = 30)
        """

        X = np.squeeze(X)
        assert X.ndim == 1, "X should be one-dimensional"

        opts = {} if opts is None else opts
        opts["numbins"] = opts.get("numbins", min(30, len(X)))
        _title2str(opts)
        _assert_opts(opts)

        minx, maxx = X.min(), X.max()
        bins = np.histogram(X, bins=opts["numbins"], range=(minx, maxx))[0]
        linrange = np.linspace(minx, maxx, opts["numbins"])

        return self.bar(X=bins, Y=linrange, opts=opts, win=win, env=env)

    @pytorch_wrap
    def boxplot(self, X, win=None, env=None, opts=None):
        """
        This function draws boxplots of the specified data. It takes as input
        an `N` or an `NxM` tensor `X` that specifies the `N` data values of
        which to construct the `M` boxplots.

        The following plot-specific `opts` are currently supported:
        - `opts.legend`: labels for each of the columns in `X`
        """

        X = np.squeeze(X)
        assert X.ndim == 1 or X.ndim == 2, "X should be one or two-dimensional"
        if X.ndim == 1:
            X = X[:, None]

        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        if opts.get("legend") is not None:
            assert (
                len(opts["legend"]) == X.shape[1]
            ), "number of legened labels must match number of columns"

        data = []
        for k in range(X.shape[1]):
            _data = {
                "y": X.take(k, 1).tolist(),
                "type": "box",
            }
            if opts.get("legend"):
                _data["name"] = opts["legend"][k]
            else:
                _data["name"] = "column " + str(k)

            data.append(_data)

        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "layout": _opts2layout(opts),
                "opts": opts,
            }
        )

    @pytorch_wrap
    def _surface(self, X, stype, win=None, env=None, opts=None):
        """
        This function draws a surface plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the surface plot.

        `stype` is 'contour' (2D) or 'surface' (3D).

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `opts.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """
        X = np.squeeze(X)
        assert X.ndim == 2, "X should be two-dimensional"

        opts = {} if opts is None else opts
        opts["xmin"] = float(opts.get("xmin", X.min()))
        opts["xmax"] = float(opts.get("xmax", X.max()))
        opts["colormap"] = opts.get("colormap", "Viridis")
        _title2str(opts)
        _assert_opts(opts)

        data = [
            {
                "z": X.tolist(),
                "cmin": opts["xmin"],
                "cmax": opts["xmax"],
                "type": stype,
                "colorscale": opts["colormap"],
            }
        ]

        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "layout": _opts2layout(
                    opts, is3d=True if stype == "surface" else False
                ),
                "opts": opts,
            }
        )

    @pytorch_wrap
    def surf(self, X, win=None, env=None, opts=None):
        """
        This function draws a surface plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the surface plot.

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `opts.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """

        return self._surface(X=X, stype="surface", opts=opts, win=win, env=env)

    @pytorch_wrap
    def contour(self, X, win=None, env=None, opts=None):
        """
        This function draws a contour plot. It takes as input an `NxM` tensor
        `X` that specifies the value at each location in the contour plot.

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.xmin`    : clip minimum value (`number`; default = `X:min()`)
        - `opts.xmax`    : clip maximum value (`number`; default = `X:max()`)
        """

        return self._surface(X=X, stype="contour", opts=opts, win=win, env=env)

    @pytorch_wrap
    def quiver(self, X, Y, gridX=None, gridY=None, win=None, env=None, opts=None):
        """
        This function draws a quiver plot in which the direction and length of the
        arrows is determined by the `NxM` tensors `X` and `Y`. Two optional `NxM`
        tensors `gridX` and `gridY` can be provided that specify the offsets of
        the arrows; by default, the arrows will be done on a regular grid.

        The following `opts` are supported:

        - `opts.normalize`:  length of longest arrows (`number`)
        - `opts.arrowheads`: show arrow heads (`boolean`; default = `true`)
        """

        # assertions:
        assert X.ndim == 2, "X should be two-dimensional"
        assert Y.ndim == 2, "Y should be two-dimensional"
        assert Y.shape == X.shape, "X and Y should have the same size"

        # make sure we have a grid:
        N, M = X.shape[0], X.shape[1]
        if gridX is None:
            gridX = np.broadcast_to(np.expand_dims(np.arange(0, N), axis=1), (N, M))
        if gridY is None:
            gridY = np.broadcast_to(np.expand_dims(np.arange(0, M), axis=0), (N, M))
        assert gridX.shape == X.shape, "X and gridX should have the same size"
        assert gridY.shape == Y.shape, "Y and gridY should have the same size"

        # default options:
        opts = {} if opts is None else opts
        opts["mode"] = "lines"
        opts["arrowheads"] = opts.get("arrowheads", True)
        _title2str(opts)
        _assert_opts(opts)

        # normalize vectors to unit length:
        if opts.get("normalize", False):
            assert (
                isinstance(opts["normalize"], numbers.Number) and opts["normalize"] > 0
            ), "opts.normalize should be positive number"
            magnitude = np.sqrt(np.add(np.multiply(X, X), np.multiply(Y, Y))).max()
            X = X / (magnitude / opts["normalize"])
            Y = Y / (magnitude / opts["normalize"])

        # interleave X and Y with copies / NaNs to get lines:
        nans = np.full((X.shape[0], X.shape[1]), np.nan).flatten()
        tipX = gridX + X
        tipY = gridY + Y
        dX = np.column_stack((gridX.flatten(), tipX.flatten(), nans))
        dY = np.column_stack((gridY.flatten(), tipY.flatten(), nans))

        # convert data to scatter plot format:
        dX = np.resize(dX, (dX.shape[0] * 3, 1))
        dY = np.resize(dY, (dY.shape[0] * 3, 1))
        data = np.column_stack((dX.flatten(), dY.flatten()))

        # add arrow heads:
        if opts["arrowheads"]:

            # compute tip points:
            alpha = 0.33  # size of arrow head relative to vector length
            beta = 0.33  # width of the base of the arrow head
            Xbeta = (X + 1e-5) * beta
            Ybeta = (Y + 1e-5) * beta
            lX = np.add(-alpha * np.add(X, Ybeta), tipX)
            rX = np.add(-alpha * np.add(X, -Ybeta), tipX)
            lY = np.add(-alpha * np.add(Y, -Xbeta), tipY)
            rY = np.add(-alpha * np.add(Y, Xbeta), tipY)

            # add to data:
            hX = np.column_stack((lX.flatten(), tipX.flatten(), rX.flatten(), nans))
            hY = np.column_stack((lY.flatten(), tipY.flatten(), rY.flatten(), nans))
            hX = np.resize(hX, (hX.shape[0] * 4, 1))
            hY = np.resize(hY, (hY.shape[0] * 4, 1))
            data = np.concatenate(
                (data, np.column_stack((hX.flatten(), hY.flatten()))), axis=0
            )

        # generate scatter plot:
        return self.scatter(X=data, opts=opts, win=win, env=env)

    @pytorch_wrap
    def stem(self, X, Y=None, win=None, env=None, opts=None):
        """
        This function draws a stem plot. It takes as input an `N` or `NxM`tensor
        `X` that specifies the values of the `N` points in the `M` time series.
        An optional `N` or `NxM` tensor `Y` containing timestamps can be given
        as well; if `Y` is an `N` tensor then all `M` time series are assumed to
        have the same timestamps.

        The following `opts` are supported:

        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.legend`  : `list` containing legend names
        """

        X = np.squeeze(X)
        assert X.ndim == 1 or X.ndim == 2, "X should be one or two-dimensional"
        if X.ndim == 1:
            X = X[:, None]

        if Y is None:
            Y = np.arange(1, X.shape[0] + 1)
        if Y.ndim == 1:
            Y = Y[:, None]
        assert Y.shape[0] == X.shape[0], "number of rows in X and Y must match"
        assert (
            Y.shape[1] == 1 or Y.shape[1] == X.shape[1]
        ), "Y should be a single column or the same number of columns as X"

        if Y.shape[1] < X.shape[1]:
            Y = np.tile(Y, (1, X.shape[1]))

        Z = np.zeros((Y.shape))  # Zeros
        with np.errstate(divide="ignore", invalid="ignore"):
            N = Z / Z  # NaNs
        X = np.column_stack((Z, X, N)).reshape((X.shape[0] * 3, X.shape[1]))
        Y = np.column_stack((Y, Y, N)).reshape((Y.shape[0] * 3, Y.shape[1]))

        data = np.column_stack((Y.flatten(), X.flatten()))
        labels = np.arange(1, X.shape[1] + 1)[None, :]
        labels = np.tile(labels, (X.shape[0], 1)).flatten()

        opts = {} if opts is None else opts
        opts["mode"] = "lines"
        _title2str(opts)
        _assert_opts(opts)

        return self.scatter(X=data, Y=labels, opts=opts, win=win, env=env)

    @pytorch_wrap
    def sunburst(self, labels, parents, values=None, win=None, env=None, opts=None):
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        font_size = opts.get("size")
        font_color = opts.get("font_color")
        opacity = opts.get("opacity")
        line_width = opts.get("marker_width")

        assert len(parents.tolist()) == len(
            labels.tolist()
        ), "length of parents and labels should be equal"

        data_dict = [
            {
                "labels": labels.tolist(),
                "parents": parents.tolist(),
                "outsidetextfont": {"size": font_size, "color": font_color},
                "leaf": {"opacity": opacity},
                "marker": {"line": {"width": line_width}},
                "type": "sunburst",
            }
        ]
        if values is not None:
            values = np.squeeze(values)
            assert values.ndim == 1, "values should be one-dimensional"
            assert len(parents.tolist()) == len(
                values.tolist()
            ), "length of values should be equal to lenght of labels and parents"

            data_dict[0]["values"] = values.tolist()

        data = data_dict
        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "layout": _opts2layout(opts),
                "opts": opts,
            }
        )

    @pytorch_wrap
    def pie(self, X, win=None, env=None, opts=None):
        """
        This function draws a pie chart based on the `N` tensor `X`.

        The following `opts` are supported:

        - `opts.legend`: `list` containing legend names
        """

        X = np.squeeze(X)
        assert X.ndim == 1, "X should be one-dimensional"
        assert np.all(np.greater_equal(X, 0)), "X cannot contain negative values"

        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        data = [
            {
                "values": X.tolist(),
                "labels": opts.get("legend"),
                "type": "pie",
            }
        ]
        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "layout": _opts2layout(opts),
                "opts": opts,
            }
        )

    @pytorch_wrap
    def mesh(self, X, Y=None, win=None, env=None, opts=None):
        """
        This function draws a mesh plot from a set of vertices defined in an
        `Nx2` or `Nx3` matrix `X`, and polygons defined in an optional `Mx2` or
        `Mx3` matrix `Y`.

        The following `opts` are supported:

        - `opts.color`: color (`string`)
        - `opts.opacity`: opacity of polygons (`number` between 0 and 1)
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        X = np.asarray(X)
        assert X.ndim == 2, "X must have 2 dimensions"
        assert X.shape[1] == 2 or X.shape[1] == 3, "X must have 2 or 3 columns"
        is3d = X.shape[1] == 3

        ispoly = Y is not None
        if ispoly:
            Y = np.asarray(Y)
            assert Y.ndim == 2, "Y must have 2 dimensions"
            assert Y.shape[1] == X.shape[1], "X and Y must have same number of columns"

        data = [
            {
                "x": X[:, 0].tolist(),
                "y": X[:, 1].tolist(),
                "z": X[:, 2].tolist() if is3d else None,
                "i": Y[:, 0].tolist() if ispoly else None,
                "j": Y[:, 1].tolist() if ispoly else None,
                "k": Y[:, 2].tolist() if is3d and ispoly else None,
                "color": opts.get("color"),
                "opacity": opts.get("opacity"),
                "type": "mesh3d" if is3d else "mesh",
            }
        ]
        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "layout": _opts2layout(opts),
                "opts": opts,
            }
        )

    @pytorch_wrap
    def dual_axis_lines(self, X=None, Y1=None, Y2=None, opts=None, win=None, env=None):
        """
        This function will create a line plot using plotly with different Y-Axis.

        `X`  = A numpy array of the range.

        `Y1` = A numpy array of the same count as `X`.

        `Y2` = A numpy array of the same count as `X`.

        The following `opts` are supported:

        - `opts.height` : Height of the plot
        - `opts.width` :  Width of the plot
        - `opts.name_y1` : Axis name for Y1 plot
        - `opts.name_y2` : Axis name for Y2 plot
        - `opts.title` :  Title of the plot
        - `opts.color_title_y1` :  Color of the Y1 axis Title
        - `opts.color_tick_y1`  :  Color of the Y1 axis Ticks
        - `opts.color_title_y2` :  Color of the Y2 axis Title
        - `opts.color_tick_y2`  :  Color of the Y2 axis Ticks
        - `opts.side` :  Placement of y2 tick. Options 'right' or `left`.
        - `opts.showlegend` :  Display legends (boolean values)
        - `opts.top` :  Set the top margin of the plot
        - `opts.bottom` :  Set the bottom margin of the plot
        - `opts.right` :  Set the right margin of the plot
        - `opts.left` :  Set the left margin of the plot
        """
        X = np.asarray(X)
        Y1 = np.asarray(Y1)
        Y2 = np.asarray(Y2)
        assert X is not None, "X Cannot be None"
        assert Y1 is not None, "Y1 Cannot be None"
        assert Y2 is not None, "Y2 Cannot be None"
        assert X.shape == Y1.shape, "values of X and Y1 are not in proper shape"
        assert X.shape == Y2.shape, "values of X and Y2 are not in proper shape"
        if opts is None:
            opts = {}
            opts["height"] = 300
            opts["width"] = 500
        X = [float(value) for value in X]
        Y1 = [float(value) for value in Y1]
        Y2 = [float(value) for value in Y2]
        trace1 = {
            "x": X,
            "y": Y1,
            "name": opts.get("name_y1", "Y1 axis"),
            "type": "scatter",
        }

        trace2 = {
            "x": X,
            "y": Y2,
            "yaxis": "y2",
            "name": opts.get("name_y2", "Y2 axis"),
            "type": "scatter",
        }

        data = [trace1, trace2]

        layout = {
            "title": opts.get("title", "Example Double Y axis"),
            "yaxis": {
                "title": trace1["name"],
                "titlefont": {"color": opts.get("color_title_y1", "black")},
                "tickfont": {"color": opts.get("color_tick_y1", "black")},
            },
            "yaxis2": {
                "title": trace2["name"],
                "titlefont": {
                    "color": opts.get("color_title_y2", "rgb(148, 103, 0189)")
                },
                "tickfont": {"color": opts.get("color_tick_y2", "rgb(148, 103, 189)")},
                "overlaying": "y",
                "side": opts.get("side", "right"),
            },
            "showlegend": opts.get("showlegend", True),
            "margin": {
                "b": opts.get("bottom", 60),
                "r": opts.get("right", 60),
                "t": opts.get("top", 60),
                "l": opts.get("left", 60),
            },
        }
        if "height" not in opts:
            opts["height"] = 300
        if "width" not in opts:
            opts["width"] = 500
        if env is None:
            env = self.env
        datasend = {
            "win": win,
            "eid": env,
            "data": data,
            "layout": layout,
            "opts": opts,
        }
        return self._send(datasend, "events")

    @pytorch_wrap
    def graph(
        self, edges, edgeLabels=None, nodeLabels=None, opts=dict(), env=None, win=None
    ):
        """
        This function draws interactive network graphs. It takes list of edges as one of the arguments.
        The user can also provide custom edge Labels and node Labels in edgeLabels and nodeLabels respectively.
        Along with that we have different parameters in opts for making it more user friendly.

        Args:
            edges : list, required
                A list of graph edges in one of the following formats (source, destination)
            edgeLabels : list, optional
                list of custom edge-labels. length should be equal to that of "edges"
            nodeLabels : list, optional
                list of custom node-labels. length should be equal to number of nodes and sequence must be in ascending order.
            opts : dict, optional
                * `directed` : directed (True) or undirected (False) graph; False by default
                * `showVertexLabels` : boolean , if True displays vertex labels else hides the label; "True" by default
                * `showEdgeLabels` :  boolean , if True displays edge labels else hides the label; "False" by default
                * `scheme` : {"same", "different"} nodes with "same" or "diffent" colors; "same" by default
                * `height` : height of the Pane
                * `width` : width of the Pane
        """
        try:
            import networkx as nx
        except:
            raise RuntimeError("networkx must be installed to plot Graph figures")

        G = nx.Graph()
        G.add_edges_from(edges)
        node_data = list(G.nodes())
        link_data = list(G.edges())
        node_data.sort()
        if edgeLabels is not None:
            assert len(edgeLabels) == len(
                link_data
            ), "shape of edgeLabels does not match with the shape of links provided {len1} != {len2}".format(
                len1=len(edgeLabels), len2=len(link_data)
            )

        if nodeLabels is not None:
            assert len(nodeLabels) == len(
                node_data
            ), "length of nodeLabels does not match with the length of nodes {len1} != {len2}".format(
                len1=len(nodeLabels), len2=len(node_data)
            )

        for i in range(len(node_data)):
            if i != node_data[i]:
                raise RuntimeError(
                    "The nodes should be numbered from 0 to n-1 for n nodes! {} node is missing!".format(
                        i
                    )
                )

        opts["directed"] = opts.get("directed", False)
        opts["showVertexLabels"] = opts.get("showVertexLabels", False)
        opts["showEdgeLabels"] = opts.get("showEdgeLabels", False)
        opts["height"] = opts.get("height", 500)
        opts["width"] = opts.get("width", 500)
        opts["scheme"] = opts.get("scheme", "same")

        nodes = []
        edges = []

        for i in range(len(link_data)):
            edge = {}
            edge["source"] = int(link_data[i][0])
            edge["target"] = int(link_data[i][1])
            edge["label"] = (
                str(edgeLabels[i])
                if edgeLabels is not None
                else str(link_data[i][0]) + "-" + str(link_data[i][1])
            )
            edges.append(edge)

        for i in range(len(node_data)):
            node = {}
            node["name"] = int(node_data[i])
            node["label"] = (
                str(nodeLabels[i]) if nodeLabels is not None else str(node_data[i])
            )
            if opts["scheme"] == "different":
                node["club"] = int(i)
            nodes.append(node)

        data = [{"content": {"nodes": nodes, "edges": edges}, "type": "network"}]

        return self._send(
            {"data": data, "win": win, "eid": env, "opts": opts}, endpoint="events"
        )
