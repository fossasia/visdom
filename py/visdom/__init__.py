#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from visdom.utils.shared_utils import get_new_window_id
from visdom import server
import os
import os.path
import requests
import traceback
import threading
import websocket  # type: ignore
import json
import hashlib

import math
import re
import base64
import binascii
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
import html

try:
    import bs4  # type: ignore

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

import sys

if sys.version_info < (3, 12):
    raise RuntimeError("Visdom requires Python 3.12 or newer.")


def _normalize_tsne(Y):
    Y = np.asarray(Y)
    xmin, xmax = np.min(Y[:, 0]), np.max(Y[:, 0])
    ymin, ymax = np.min(Y[:, 1]), np.max(Y[:, 1])
    xrange = xmax - xmin
    yrange = ymax - ymin
    normx = (
        ((Y[:, 0] - xmin) / xrange) * 2 - 1 if xrange > 0 else np.zeros_like(Y[:, 0])
    )
    normy = (
        ((Y[:, 1] - ymin) / yrange) * 2 - 1 if yrange > 0 else np.zeros_like(Y[:, 1])
    )
    return list(zip(normx, normy))


def _get_perplexity(num_entities):
    if num_entities >= 150:
        base = 50
    elif num_entities >= 21:
        base = num_entities // 3
    else:
        base = 7
    max_perplexity = max(1, (num_entities - 1) // 3)
    return min(base, max_perplexity)


try:
    from openTSNE import TSNE as TSNE_OPEN

    def do_tsne(X):
        perplexity = _get_perplexity(len(X))
        tsne = TSNE_OPEN(n_components=2, perplexity=perplexity, verbose=True)
        Y = tsne.fit(X)
        return _normalize_tsne(Y)

except ImportError:
    try:
        import visdom.extra_deps.bhtsne.bhtsne as bhtsne

        def do_tsne(X):
            perplexity = _get_perplexity(len(X))
            Y = bhtsne.run_bh_tsne(
                X, initial_dims=X.shape[1], perplexity=perplexity, verbose=True
            )
            return _normalize_tsne(Y)

    except ImportError:

        def do_tsne(X):
            raise Exception(
                "In order to use the embeddings feature, you'll "
                "need to install a backend to support the calculation. "
                "Currently we support openTSNE "
                "(https://github.com/pavlin-policar/openTSNE) for "
                "t-SNE computation, or the bhtsne implementation at "
                "https://github.com/lvdmaaten/bhtsne/. Install openTSNE via "
                "pip install openTSNE, or install bhtsne by cloning it into "
                "the /py/visdom/extra_deps/ directory and running the "
                "installation steps as listed on that github "
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

SESSION_IDLE_TIMEOUT = 600
SESSION_IDLE_CHECK_INTERVAL = 60


def get_rand_id():
    return str(hex(int(time.time() * 10000000))[2:])


def isstr(s):
    return isinstance(s, (str,))


def isnum(n):
    return isinstance(n, numbers.Number) and not isinstance(n, bool)


def isndarray(n):
    return isinstance(n, (np.ndarray))


from visdom.utils.shared_utils import NanSafeEncoder

# TODO: In appropriate places, we need to change many numpy calls to use
#       nan-aware ones, e.g., `X.max` => `np.nanmax(X)`.


def loadfile(filename):
    assert os.path.isfile(filename), "could not find file %s" % filename
    fileobj = open(filename, "rb")
    assert fileobj, "could not open file %s" % filename
    str = fileobj.read()
    fileobj.close()
    return str


def _title2str(opts):
    if opts.get("title") is not None:
        if isnum(opts.get("title")):
            title = str(opts.get("title"))
            logger.warning("Numerical title %s has been cast to a string" % title)
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
    if any(opts.get(xy + i) is not None for i in fields):
        has_ticks = (
            opts.get(xy + "tickmin") is not None
            and opts.get(xy + "tickmax") is not None
        )
        return {
            "type": opts.get(xy + "type"),
            "title": opts.get(xy + "label"),
            "range": (
                [opts.get(xy + "tickmin"), opts.get(xy + "tickmax")]
                if has_ticks
                else None
            ),
            "tickvals": opts.get(xy + "tickvals"),
            "ticktext": opts.get(xy + "ticklabels"),
            "dtick": opts.get(xy + "tickstep"),
            "showticklabels": opts.get(xy + "tick"),
            "tickfont": opts.get(xy + "tickfont"),
            "automargin": opts.get("tight_layout", False) or None,
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
    if any(opts.get(xyz + i) is not None for i in fields):
        has_ticks = (
            opts.get(xyz + "tickmin") is not None
            and opts.get(xyz + "tickmax") is not None
        )
        has_step = has_ticks and opts.get(xyz + "tickstep") is not None
        return {
            "type": opts.get(xyz + "type"),
            "title": opts.get(xyz + "label"),
            "range": (
                [opts.get(xyz + "tickmin"), opts.get(xyz + "tickmax")]
                if has_ticks
                else None
            ),
            "tickvals": opts.get(xyz + "tickvals"),
            "ticktext": opts.get(xyz + "ticklabels"),
            "nticks": (
                (
                    (opts.get(xyz + "tickmax") - opts.get(xyz + "tickmin"))
                    / opts.get(xyz + "tickstep")
                )
                if has_step
                else None
            ),
            "tickfont": opts.get(xyz + "tickfont"),
        }


def _opts2layout(opts, is3d=False):
    tight = opts.get("tight_layout", False)
    layout = {
        "showlegend": opts.get("showlegend", "legend" in opts),
        "title": opts.get("title"),
        "margin": {
            "l": opts.get("marginleft", 0 if (is3d or tight) else 60),
            "r": opts.get("marginright", 0 if tight else 60),
            "t": opts.get("margintop", 20 if is3d else (30 if tight else 60)),
            "b": opts.get("marginbottom", 0 if (is3d or tight) else 60),
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


def _normalize_labels(Y):
    """
    Normalizes arbitrary labels (int, float, string) to 1-based indices.
    Returns:
        Y_normalized (np.ndarray): 1-based integer labels
        label_values (np.ndarray or None): Original unique label values, or None if Y
                                           was already a valid set of 1-based integer labels.
        K (int): Number of unique labels
    """
    Y = np.ravel(Y)

    try:
        is_integer_labels = (
            np.issubdtype(Y.dtype, np.number)
            and np.equal(np.mod(Y, 1), 0).all()
            and np.nanmin(Y) >= 1
        )
    except TypeError:
        is_integer_labels = False

    if is_integer_labels:
        Y_normalized = Y.astype(int, copy=False)
        K = int(np.nanmax(Y_normalized))
        label_values = None
    else:
        if np.issubdtype(Y.dtype, np.number):
            assert np.isfinite(Y).all(), "labels must be finite (no NaN/Inf)"
        label_values = np.unique(Y)
        K = len(label_values)
        Y_normalized = (np.searchsorted(label_values, Y) + 1).astype(int)

    return Y_normalized, label_values, K


def _markerColorCheck(mc, X, Y, L):
    assert isndarray(mc), "mc should be a numpy ndarray"
    if mc.ndim == 1:
        valid = (mc.shape[0] >= L) or (mc.shape[0] == X.shape[0])
    elif mc.ndim == 2:
        valid = (mc.shape[1] == 3) and (
            (mc.shape[0] >= L) or (mc.shape[0] == X.shape[0])
        )
    else:
        valid = False

    assert valid, (
        "marker colors have to be of size `%d` or `%d x 3` "
        "(per-point) or at least `%d` or at least `%d x 3` "
        "(palette), but got: %s"
    ) % (
        X.shape[0],
        X.shape[0],
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


def _markerSizeCheck(ms, X, Y):
    """Validate and return per-point marker sizes as a numpy array."""
    if isinstance(ms, (list, tuple)):
        ms = np.array(ms, dtype=float)
    assert isndarray(ms), "markersize array should be a numpy ndarray"
    assert ms.ndim == 1, "markersize array should be 1-dimensional"
    assert (ms > 0).all(), "all marker sizes must be positive"

    if ms.shape[0] == X.shape[0]:
        return np.array(ms, dtype=float)

    K = int(np.nanmax(Y)) if len(Y) > 0 else 0
    assert ms.shape[0] >= K, (
        "markersize should be of size `%d` (per-point) or at least `%d` "
        "(per-label), but got: %d" % (X.shape[0], K, ms.shape[0])
    )

    return np.array([ms[Y[i] - 1] for i in range(len(Y))], dtype=float)


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
            logger.warning(
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

    if opts.get("markersize") is not None:
        ms = opts.get("markersize")
        if isinstance(ms, (list, tuple, np.ndarray)):
            assert all(m > 0 for m in ms), "all marker sizes must be positive"
        else:
            assert isnum(ms) and ms > 0, "marker size should be a positive number"

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

    if "title" in opts and opts.get("title") is not None:
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
    for kind in torch_types:
        if isinstance(a, kind):
            return a.detach().cpu().numpy()
    return a


def pytorch_wrap(f):
    @wraps(f)
    def wrapped_f(*args, **kwargs):
        args = (_to_numpy(arg) for arg in args)
        kwargs = {k: _to_numpy(v) for (k, v) in kwargs.items()}
        return f(*args, **kwargs)

    return wrapped_f


def _binary_clf_curve(y_true, y_score, pos_label=1):
    """Compute true/false positives per distinct score threshold."""
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score)

    if y_true.ndim != 1:
        raise ValueError("y_true should have 1 dim")
    if y_score.ndim != 1:
        raise ValueError("y_score should have 1 dim")
    if y_true.shape[0] != y_score.shape[0]:
        raise ValueError("y_true and y_score should match")
    if y_true.shape[0] == 0:
        raise ValueError("y_true and y_score should be non-empty")
    if not np.all(np.isfinite(y_score)):
        raise ValueError("y_score should only contain finite values")

    y_true = y_true == pos_label
    desc_score_indices = np.argsort(y_score, kind="mergesort")[::-1]
    y_score = y_score[desc_score_indices]
    y_true = y_true[desc_score_indices]

    distinct_value_indices = np.where(np.diff(y_score))[0]
    threshold_idxs = np.r_[distinct_value_indices, y_true.size - 1]

    tps = np.cumsum(y_true, dtype=float)[threshold_idxs]
    fps = 1 + threshold_idxs - tps
    return fps, tps


def _compute_roc_curve(y_true, y_score, pos_label=1):
    """Compute ROC curve (fpr, tpr) from raw labels and scores."""
    fps, tps = _binary_clf_curve(y_true=y_true, y_score=y_score, pos_label=pos_label)
    pos_total = float(tps[-1])
    neg_total = float(fps[-1])
    if pos_total <= 0:
        raise ValueError("y_true has no positive samples")
    if neg_total <= 0:
        raise ValueError("y_true has no negative samples")

    fpr = np.r_[0.0, fps / neg_total]
    tpr = np.r_[0.0, tps / pos_total]
    return fpr, tpr


def _compute_pr_curve(y_true, y_score, pos_label=1):
    """Compute precision-recall curve from raw labels and scores."""
    fps, tps = _binary_clf_curve(y_true=y_true, y_score=y_score, pos_label=pos_label)
    pos_total = float(tps[-1])
    if pos_total <= 0:
        raise ValueError("y_true has no positive samples")

    precision = tps / (tps + fps)
    recall = tps / pos_total

    precision = np.r_[1.0, precision]
    recall = np.r_[0.0, recall]
    return precision, recall


def _coerce_curve_xy(x, y, x_name, y_name):
    """Validate and sort precomputed curve arrays by x."""
    x = np.asarray(x)
    y = np.asarray(y)
    if x.ndim != 1:
        raise ValueError("{} should have 1 dim".format(x_name))
    if y.ndim != 1:
        raise ValueError("{} should have 1 dim".format(y_name))
    if x.shape[0] != y.shape[0]:
        raise ValueError("{} and {} should match".format(x_name, y_name))
    if x.shape[0] <= 1:
        raise ValueError(
            "{} and {} should have at least 2 points".format(x_name, y_name)
        )

    order = np.argsort(x, kind="mergesort")
    return x[order], y[order]


def _validate_curve_range(values, name):
    """Validate that values are finite and within [0, 1]."""
    values = np.asarray(values)
    if not np.all(np.isfinite(values)):
        raise ValueError("{} should only contain finite values".format(name))
    if not np.all((values >= 0.0) & (values <= 1.0)):
        raise ValueError("{} should be within [0, 1]".format(name))


def _curve_legend(legend, default_legend):
    """Return user-provided legend or default 2-element list."""
    if not isinstance(legend, (tuple, list)) or len(legend) < 2:
        if legend is not None:
            warnings.warn(
                "legend should be a list/tuple with at least 2 elements, "
                "falling back to default: {}".format(default_legend),
                UserWarning,
            )
        return list(default_legend)
    return list(legend)


def _trapz_area(y, x):
    """Compute trapezoidal area under curve, compatible with numpy >= 2.0."""
    trapezoid = getattr(np, "trapezoid", None)
    if trapezoid is not None:
        return float(trapezoid(y, x))
    return float(np.trapz(y, x))


def _average_precision(precision, recall):
    """Compute average precision: AP = sum((R_n - R_{n-1}) * P_n)."""
    precision = np.asarray(precision)
    recall = np.asarray(recall)
    return float(np.sum(np.diff(recall) * precision[1:]))


def _compute_confusion_matrix(y_true, y_pred, labels):
    """Build an NxN confusion matrix from label vectors (numpy only).

    ``y_true``/``y_pred`` are expected to be 1-D numpy arrays; the public
    ``confusion_matrix`` caller ravels them before calling this helper.
    """
    if y_true.shape[0] != y_pred.shape[0]:
        raise ValueError("y_true and y_pred must have the same length")
    if y_true.shape[0] == 0:
        raise ValueError("y_true and y_pred must be non-empty")

    label_to_idx = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    cm = np.zeros((n, n), dtype=int)
    skipped = 0
    for t, p in zip(y_true, y_pred):
        if t in label_to_idx and p in label_to_idx:
            cm[label_to_idx[t], label_to_idx[p]] += 1
        else:
            skipped += 1
    if skipped > 0:
        warnings.warn(
            "{} samples had labels not in the provided labels list "
            "and were ignored".format(skipped),
            UserWarning,
        )
    return cm


def _decode_binary_arrays(obj):
    """Decode Plotly 6+ binary-encoded arrays back to plain Python lists."""
    if isinstance(obj, dict):
        if "dtype" in obj and "bdata" in obj:
            try:
                arr = np.frombuffer(
                    base64.b64decode(obj["bdata"]), dtype=np.dtype(obj["dtype"])
                )
                if "shape" in obj:
                    arr = arr.reshape(obj["shape"])
                return arr.tolist()
            except (binascii.Error, ValueError, TypeError):
                return obj
        return {k: _decode_binary_arrays(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode_binary_arrays(v) for v in obj]
    return obj


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
        session_idle_timeout=SESSION_IDLE_TIMEOUT,
        session_idle_check_interval=SESSION_IDLE_CHECK_INTERVAL,
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
        self.env = (
            env.replace("/", "_")
            .replace("\\", "_")
            .replace("\n", "-")
            .replace("\r", "-")
        )
        self.env_list = {self.env}  # default env
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
        self._pid = os.getpid()
        self._session_lock = threading.Lock()
        self._last_post_time = time.time()
        self.session_idle_timeout = session_idle_timeout
        self.session_idle_check_interval = session_idle_check_interval
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
            logger.warning(
                "Without the incoming socket you cannot receive events from "
                "the server or register event handlers to your Visdom client."
            )
        if send:
            self._start_session_reaper()
        # Wait for initialization before starting
        time_spent = 0
        inc = 0.1
        while self.use_socket and not self.socket_alive and time_spent < 5:
            time.sleep(inc)
            time_spent += inc
            inc *= 2
        if time_spent > 5:
            logger.warning(
                "Visdom python client failed to establish socket to get "
                "messages from the server. This feature is optional and "
                "can be disabled by initializing Visdom with "
                "`use_incoming_socket=False`, which will prevent waiting for "
                "this request to timeout."
            )

    @property
    def session(self):
        with self._session_lock:
            current_pid = os.getpid()
            if self._session and self._pid == current_pid:
                return self._session

            if self._session:
                try:
                    self._session.close()
                except Exception:
                    pass
            self._pid = current_pid
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

    def _start_session_reaper(self):
        def run_reaper():
            while True:
                time.sleep(self.session_idle_check_interval)
                idle_for = time.time() - self._last_post_time
                if idle_for <= self.session_idle_timeout:
                    continue
                with self._session_lock:
                    if (
                        self._session is not None
                        and time.time() - self._last_post_time
                        > self.session_idle_timeout
                    ):
                        logger.info(
                            "Closing idle visdom HTTP session after %ds of "
                            "inactivity; it will be recreated on the next send.",
                            int(idle_for),
                        )
                        try:
                            self._session.close()
                        except Exception:
                            pass
                        self._session = None

        self.session_reaper_thread = threading.Thread(
            target=run_reaper, name="Visdom-Session-Reaper", daemon=True
        )
        self.session_reaper_thread.start()

    def register_event_handler(self, handler, target, env=None):
        assert callable(handler), "Event handler must be a function"
        assert (
            self.use_socket
        ), "Must be using the incoming socket to register events to web actions"

        key = (env, target)
        if key not in self.event_handlers:
            self.event_handlers[key] = []
        self.event_handlers[key].append(handler)

    def clear_event_handlers(self, target, env=None):
        self.event_handlers.pop((env, target), None)

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
                        logger.warning(
                            "Visdom server failed handshake, may not "
                            "be properly connected"
                        )
            if "target" in message:
                env = message.get("eid")
                key = (env, message["target"])

                for handler in list(self.event_handlers.get(key, [])):
                    handler(message)

                if env is not None:
                    global_key = (None, message["target"])
                    for handler in list(self.event_handlers.get(global_key, [])):
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
                        logger.warning(
                            "Visdom server failed handshake, may not "
                            "be properly connected"
                        )
            if "target" in message:
                env = message.get("eid")
                key = (env, message["target"])

                handlers = list(self.event_handlers.get(key, []))
                if env is not None:
                    global_key = (None, message["target"])
                    handlers.extend(list(self.event_handlers.get(global_key, [])))

                for handler in handlers:
                    try:
                        handler(message)
                    except Exception as e:
                        logger.warning(
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

        def on_close(ws, close_status_code=None, close_msg=None):
            self.socket_alive = False
            if not self.socket_connection_achieved:
                logger.warning(
                    "WebSocket closed before connection achieved "
                    "(close_status_code=%s). If login is enabled, "
                    "pass username/password to Visdom().",
                    close_status_code,
                )
                self.use_socket = False

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
                            "Cookie": "user_password="
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
                            ],
                            cls=NanSafeEncoder,
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
        self._last_post_time = time.time()
        had_session = self._session is not None
        try:
            r = self.session.post(url, data=data)
            return r.text
        except (requests.ConnectionError, requests.Timeout):
            if not had_session:
                raise
            logger.warning("Connection failed, resetting session and retrying...")
            with self._session_lock:
                try:
                    if self._session is not None:
                        self._session.close()
                except Exception:
                    pass
                self._session = None
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
                data=json.dumps(msg, cls=NanSafeEncoder),
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

    def delete_envs(self, env_list):
        """This function deletes a list of environments."""
        if not isinstance(env_list, list):
            raise TypeError("env_list must be a list of strings")
        responses = []
        for env in env_list:
            if not isinstance(env, str):
                raise TypeError(f"Environment ID must be a string, got {type(env)}")
            responses.append(self.delete_env(env))
        return responses

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

    def get_env_state(self, env):
        """
        This function returns the state of a specific environment,
        containing all window data as a dict of {window_id: window_json}.

        Returns None if the environment does not exist.
        """
        assert isinstance(env, str), "env should be a string"
        if self.offline:
            return None
        response = self._send({"eid": env}, endpoint="env_state", quiet=True)
        if response is False:
            return None
        parsed = json.loads(response)
        if isinstance(parsed, dict) and "error" in parsed:
            return None
        return parsed

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
                    raise ImportError("No module named 'lxml'") from e
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

    def save_plotly_figure(self, figure, filepath, **kwargs):
        """
        Save a Plotly figure to an image file from Python (no browser click required).

        This allows programmatic saving of plots that would otherwise require
        using the "Download plot as a png" button in the Visdom UI. You can
        build the same figure, save it to file with this method, and optionally
        display it in Visdom with plotlyplot().

        Args:
            figure: A Plotly Figure object (e.g. from plotly.graph_objects or
                make_subplots).
            filepath: Path for the output file (e.g. "plot.png", "figure.svg").
                The format is inferred from the extension (png, svg, pdf, etc.).
            **kwargs: Optional arguments passed to Plotly's write_image (e.g.
                width, height, scale).

        Raises:
            RuntimeError: If plotly or kaleido is not installed.

        Note: Requires the 'kaleido' package for image export. Install with
        `pip install kaleido`.
        """
        try:
            import plotly
        except ImportError:
            raise RuntimeError(
                "Plotly must be installed to save Plotly figures. "
                "Install with: pip install plotly"
            )
        try:
            figure.write_image(filepath, **kwargs)
        except ValueError as e:
            if "kaleido" in str(e).lower() or "orca" in str(e).lower():
                raise RuntimeError(
                    "Saving Plotly figures to image requires the 'kaleido' package. "
                    "Install with: pip install kaleido"
                ) from e
            raise

    def plotlyplot(self, figure, win=None, env=None, save_path=None, save_kwargs=None):
        """
        This function draws a Plotly 'Figure' object. It does not explicitly
        take options as it assumes you have already explicitly configured the
        figure's layout.

        To save the figure as an image from code (without using the browser
        download button), pass save_path (e.g. save_path="plot.png"). Optional
        arguments for Plotly's write_image should be passed via save_kwargs,
        e.g. save_kwargs={"width": 800, "height": 600}. This requires the
        optional 'kaleido' package (pip install kaleido).

        Note: You must have the 'plotly' Python package installed to use
        this function.
        """
        if save_kwargs is None:
            save_kwargs = {}
        try:
            import plotly

            if save_path is not None:
                self.save_plotly_figure(figure, save_path, **save_kwargs)

            # We do a round-trip of JSON encoding and decoding to make use of
            # the Plotly JSON Encoder. The JSON encoder deals with converting
            # numpy arrays to Python lists and several other edge cases.
            figure_json = json.dumps(figure, cls=plotly.utils.PlotlyJSONEncoder)
            figure_dict = json.loads(figure_json)
            # Plotly 6+ encodes large arrays as binary dicts {"dtype":..., "bdata":...}.
            # Decode them back to plain Python lists so the frontend can render them.
            if '"bdata"' in figure_json:
                figure_dict = _decode_binary_arrays(figure_dict)

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
            if "width" in figure_dict["layout"]:
                opts["width"] = figure_dict["layout"]["width"]
            if "height" in figure_dict["layout"]:
                opts["height"] = figure_dict["layout"]["height"]

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
                if data_getter is not None and data_type == "html":
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
                return

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

        self.register_event_handler(embedding_event_handler, win, env=env)

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

        labels_normalized, _, _ = _normalize_labels(labels)
        points = [
            {
                "group": int(labels_normalized[i] - 1),
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
        This function draws an img. It takes as input a `CxHxW` (where C is 1, 3, or 4)
        or `HxW` tensor `img` that contains the image. The array values can be uint8 in
        [0, 255] or float. Float arrays are converted as follows: images whose
        full range is within [0, 1] are scaled to [0, 255]; images whose full
        range is within [-1, 1] but includes negative values are mapped from
        [-1, 1] to [0, 255]; all other float values are clipped to [0, 255].
        Pass `opts.normalize=True` to min-max scale the image to fill [0, 255]
        instead.

        The following `opts` are supported:

        - `opts.normalize`: min-max scale float image to [0, 255] (`boolean`; default = `False`)
        - `opts.jpgquality`: quality of the JPEG image (`number` in (0, 100]; default = `None` for PNG)
        - `opts.caption`: caption below the image (`string`; optional)
        - `opts.store_history`: append to image history pane (`boolean`)
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)
        if np.issubdtype(img.dtype, np.floating):
            finite = img[np.isfinite(img)]
            if finite.size > 0:
                img_min, img_max = float(finite.min()), float(finite.max())
            else:
                img_min, img_max = 0.0, 0.0
            if opts.get("normalize", False):
                if img_max > img_min:
                    img = (img - img_min) / (img_max - img_min) * 255.0
                else:
                    img = np.zeros_like(img)
            elif img_min >= -1e-5 and img_max <= 1.0 + 1e-5:
                img = img * 255.0
            elif img_min >= -1.0 - 1e-5 and img_max <= 1.0 + 1e-5:
                img = (img + 1.0) / 2.0 * 255.0
            img = np.nan_to_num(img, nan=0.0, posinf=255.0, neginf=0.0)
            img = np.uint8(np.clip(img, 0, 255))

        # extract dimensions and process formats
        if img.ndim == 2:
            # grayscale - shape(H,W)
            nchannels = 1
            opts["width"] = opts.get("width", img.shape[1])
            opts["height"] = opts.get("height", img.shape[0])
            im = Image.fromarray(img, mode="L")
        elif img.ndim == 3:
            nchannels = img.shape[0]
            opts["width"] = opts.get("width", img.shape[2])
            opts["height"] = opts.get("height", img.shape[1])

            if nchannels == 1:
                im = Image.fromarray(img[0, :, :], mode="L")
            elif nchannels == 3:
                img = np.transpose(img, (1, 2, 0))
                im = Image.fromarray(img, mode="RGB")
            elif nchannels == 4:  # RGBA (4,H,W)
                img = np.transpose(img, (1, 2, 0))
                im = Image.fromarray(img, mode="RGBA")
            else:
                raise ValueError(
                    f"Unsupported number of image channels: {nchannels}. "
                    "Only 1 (grayscale), 3 (RGB), or 4 (RGBA) channels are supported."
                )
        else:
            raise ValueError(
                f"Unsupported image dimensions: {img.ndim}. "
                "Image tensor must be 2D (HxW) or 3D (CxHxW)."
            )
        buf = BytesIO()
        image_type = "png"
        imsave_args = {}
        jpgquality = opts.get("jpgquality")
        if jpgquality is not None and nchannels != 4:
            image_type = "jpeg"
            imsave_args["quality"] = jpgquality

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

    def image_select(self, win, selected, env=None):
        """
        Set the selected frame index in an image_history window.

        This function updates which frame is currently displayed in a window
        that was created with ``opts=dict(store_history=True)`` via the
        `image` function.
        """
        assert win is not None, "Must specify a window"
        assert isinstance(selected, int), "selected must be an integer"

        data = [{"type": "image_update_selected", "selected": selected}]
        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
            },
            endpoint="update",
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
        - `opts.caption`: caption to display below the player (`string`; optional)
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
            max_val = np.max(np.abs(tensor))
            if max_val == 0:
                # When all zero tensor, skip normalisation to avoid division by zero
                tensor = np.zeros_like(tensor, dtype=np.int16)
            else:
                tensor = np.int16(tensor / max_val * 32767)
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
        if opts.get("caption"):
            audiodata += "<p>%s</p>" % html.escape(str(opts["caption"]))
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
        - `opts.caption`: caption to display below the player (`string`; optional)
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
        if opts.get("caption"):
            videodata += "<p>%s</p>" % html.escape(str(opts["caption"]))
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
        - `opts.markersize`       : marker size (`number` or `np.array`; default = `'10'`)
        - `opts.markercolor`      : marker color (`np.array`; default = `None`)
        - `opts.markerborderwidth`: marker border line width (`float`; default = 0.5)
        - `opts.dash`             : dash type (`np.array`; default = 'solid'`)
        - `opts.textlabels`       : text label for each point (`list`: default = `None`)
        - `opts.legend`           : `list` or `tuple` containing legend names
        """
        if opts and opts.get("store_history") and update is not None:
            raise ValueError(
                "Cannot use store_history=True together with the update parameter"
            )

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
            if win is None:
                raise ValueError("Must define a window to update")

            if update == "append":
                if not self.offline:
                    exists = self.win_exists(win, env)
                    if exists is False:
                        update = None
            # case when X is 1 dimensional and corresponding values on y-axis
            # are passed in parameter Y
            if name:
                assert len(name) > 0, "name of trace should be non-empty string"
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
        assert X.shape[0] > 0, "X should have at least one point"

        if Y is not None:
            Y = np.ravel(Y)
            assert X.shape[0] == Y.shape[0], "sizes of X and Y should match"
            Y, label_values, K = _normalize_labels(Y)
            labels = np.unique(Y)
            assert (
                len(labels) == 1 or name is None
            ), "name should not be specified with multiple labels or lines"
        else:
            Y = np.ones(X.shape[0], dtype=int)
            labels = np.ones(1, dtype=int)
            K = 1  # largest label
            label_values = None  # single unlabelled trace

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

        if opts.get("markersize") is not None and isinstance(
            opts["markersize"], (list, tuple, np.ndarray)
        ):
            opts["markersize"] = _markerSizeCheck(opts["markersize"], X, Y)

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
        ms = (
            opts.get("markersize")
            if isinstance(opts.get("markersize"), np.ndarray)
            else None
        )
        lc = opts.get("linecolor")

        for k in labels:
            ind = np.equal(Y, k)
            if ind.any():
                if "legend" in opts:
                    trace_name = opts.get("legend")[k - 1]
                elif len(labels) == 1 and name is not None:
                    trace_name = name
                else:
                    # For float-remapped labels show the original value;
                    # for integer labels keep existing str(k) behaviour.
                    if label_values is not None:
                        trace_name = str(label_values[k - 1])
                    else:
                        trace_name = str(k)
                use_gl = opts.get("webgl", False)
                _data = {
                    "x": X.take(0, 1)[ind].tolist(),
                    "y": X.take(1, 1)[ind].tolist(),
                    "name": trace_name,
                    "type": (
                        "scatter3d" if is3d else ("scattergl" if use_gl else "scatter")
                    ),
                    "mode": opts.get("mode"),
                    "text": L[ind].tolist() if L is not None else None,
                    "textposition": "right",
                    "line": {
                        "dash": dash[k - 1] if dash is not None else None,
                        "color": lc[k - 1] if lc is not None else None,
                    },
                    "marker": {
                        "size": (
                            ms[ind].tolist()
                            if ms is not None
                            else opts.get("markersize")
                        ),
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
            if ms is not None and "markersize" in opts:
                del opts["markersize"]
            for line_prop in ["linecolor"]:
                if line_prop in opts:
                    del opts[line_prop]
            for dash in ["dash"]:
                if dash in opts:
                    del opts[dash]

        if opts.get("store_history"):
            layout = _opts2layout(opts, is3d)
            data_to_send = {
                "data": [
                    {
                        "type": "plot_history",
                        "content": {
                            "data": data,
                            "layout": layout,
                            "caption": opts.get("caption"),
                        },
                    }
                ],
                "win": win,
                "eid": env,
                "opts": opts,
            }
            endpoint = "events"
            if win is not None and self.win_exists(win, env):
                endpoint = "update"
            return self._send(data_to_send, endpoint=endpoint)

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
    def line(
        self,
        Y,
        X=None,
        win=None,
        env=None,
        opts=None,
        update=None,
        name=None,
        Z=None,
        is3d=False,
    ):
        """
        This function draws a line plot. It takes in an `N` or `NxM` tensor
        `Y` that specifies the values of the `M` lines (that connect `N` points)
        to plot. It also takes an optional `X` tensor that specifies the
        corresponding x-axis values; `X` can be an `N` tensor (in which case all
        lines will share the same x-axis values) or have the same size as `Y`.

        For 3D line plots, an optional `Z` tensor can be provided with the same
        size as `Y` (or as an `N` tensor shared across lines). When `Z` is
        provided, the plot is rendered as a 3D line plot.

        `update` can be used to efficiently update the data of an existing line.
        Use 'append' to append data, 'replace' to use new data, and 'remove' to
        delete the trace that is specified in `name`. If updating a
        single trace, use `name` to specify the name of the trace to be updated.
        Update data that is all NaN is ignored (can be used for masking update).
        Using `update='append'` will create a plot if it doesn't exist
        and append to the existing plot otherwise.

        The following `opts` are supported:

        - `opts.fillarea`    : fill area below line (`boolean`; not supported for 3D)
        - `opts.markers`     : show markers (`boolean`; default = `false`)
        - `opts.markersymbol`: marker symbol (`string`; default = `'dot'`)
        - `opts.markersize`  : marker size (`number` or `np.array`; default = `'10'`)
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
        if is3d:
            assert Z is not None, (
                "Z values are required for 3D line plots. "
                "Pass Z when creating or updating a 3D line plot."
            )
        assert Y.ndim == 1 or Y.ndim == 2, "Y should have 1 or 2 dim"
        assert Y.shape[-1] > 0, "must plot one line at least"

        if Z is not None:
            assert Z.ndim == 1 or Z.ndim == 2, "Z should have 1 or 2 dim"

        if Y.ndim == 2 and Y.shape[1] == 1:
            Y = Y.ravel()
            if X is not None and X.ndim == 2 and X.shape[1] == 1:
                X = X.ravel()
            if Z is not None and Z.ndim == 2 and Z.shape[1] == 1:
                Z = Z.ravel()

        if X is not None:
            assert X.ndim == 1 or X.ndim == 2, "X should have 1 or 2 dim"
        else:
            X = np.linspace(0, 1, Y.shape[0])

        if Y.ndim == 2 and X.ndim == 1:
            X = np.tile(X, (Y.shape[1], 1)).transpose()

        if Z is not None and Y.ndim == 2 and Z.ndim == 1:
            Z = np.tile(Z, (Y.shape[1], 1)).transpose()

        assert X.shape == Y.shape, "X and Y should be the same shape"
        if Z is not None:
            assert Z.shape == Y.shape, "Z and Y should be the same shape"

        opts = {} if opts is None else opts
        opts["markers"] = opts.get("markers", False)
        opts["fillarea"] = opts.get("fillarea", False)
        if Z is not None and opts["fillarea"]:
            warnings.warn(
                "fillarea is not supported for 3D line plots",
                UserWarning,
                stacklevel=2,
            )
            opts["fillarea"] = False
        opts["mode"] = "lines+markers" if opts.get("markers") else "lines"

        _title2str(opts)
        _assert_opts(opts)

        if Y.ndim == 1:
            if Z is not None:
                linedata = np.column_stack((X, Y, Z))
            else:
                linedata = np.column_stack((X, Y))
        else:
            cols = [X.ravel(order="F"), Y.ravel(order="F")]
            if Z is not None:
                cols.append(Z.ravel(order="F"))
            linedata = np.column_stack(cols)

        labels = None
        if Y.ndim == 2:
            labels = np.arange(1, Y.shape[1] + 1)
            labels = np.tile(labels, (Y.shape[0], 1)).ravel(order="F")

        return self.scatter(
            X=linedata, Y=labels, opts=opts, win=win, env=env, update=update, name=name
        )

    @pytorch_wrap
    def roc_curve(
        self,
        y_true=None,
        y_score=None,
        fpr=None,
        tpr=None,
        pos_label=1,
        win=None,
        env=None,
        opts=None,
    ):
        """
        Draw a ROC curve for binary classification.

        You can either provide raw labels/scores (`y_true`, `y_score`) or
        precomputed points (`fpr`, `tpr`).

        The following `opts` are supported:

        - `opts.title`      : plot title (`string`; default includes ROC-AUC)
        - `opts.legend`     : two legend labels for curve and baseline (`list`)
        - `opts.xlabel`     : x-axis label (`string`; default = `False Positive Rate`)
        - `opts.ylabel`     : y-axis label (`string`; default = `True Positive Rate`)
        - `opts.layoutopts` : additional backend layout options (`dict`)
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        has_raw = y_true is not None or y_score is not None
        has_points = fpr is not None or tpr is not None
        if has_raw == has_points:
            raise ValueError(
                "provide exactly one input mode: (y_true, y_score) or (fpr, tpr)"
            )

        if has_raw:
            if y_true is None or y_score is None:
                raise ValueError("both y_true and y_score are required")
            fpr, tpr = _compute_roc_curve(
                y_true=np.ravel(y_true),
                y_score=np.ravel(y_score),
                pos_label=pos_label,
            )
        else:
            if fpr is None or tpr is None:
                raise ValueError("both fpr and tpr are required")
            fpr, tpr = _coerce_curve_xy(fpr, tpr, "fpr", "tpr")

        _validate_curve_range(fpr, "fpr")
        _validate_curve_range(tpr, "tpr")

        auc = _trapz_area(tpr, fpr)

        opts = dict(opts)
        opts["xlabel"] = opts.get("xlabel", "False Positive Rate")
        opts["ylabel"] = opts.get("ylabel", "True Positive Rate")
        opts["legend"] = _curve_legend(opts.get("legend"), ["ROC", "Chance"])
        opts["title"] = opts.get("title", "ROC Curve (AUC={:.4f})".format(auc))

        data = [
            {
                "x": fpr.tolist(),
                "y": tpr.tolist(),
                "name": opts["legend"][0],
                "type": "scatter",
                "mode": "lines",
            },
            {
                "x": [0.0, 1.0],
                "y": [0.0, 1.0],
                "name": opts["legend"][1],
                "type": "scatter",
                "mode": "lines",
                "line": {"dash": "dash"},
            },
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
    def pr_curve(
        self,
        y_true=None,
        y_score=None,
        precision=None,
        recall=None,
        pos_label=1,
        win=None,
        env=None,
        opts=None,
    ):
        """
        Draw a precision-recall curve for binary classification.

        You can either provide raw labels/scores (`y_true`, `y_score`) or
        precomputed points (`precision`, `recall`).

        The following `opts` are supported:

        - `opts.title`      : plot title (`string`; default includes PR-AUC)
        - `opts.legend`     : two legend labels for curve and baseline (`list`)
        - `opts.xlabel`     : x-axis label (`string`; default = `Recall`)
        - `opts.ylabel`     : y-axis label (`string`; default = `Precision`)
        - `opts.layoutopts` : additional backend layout options (`dict`)
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        has_raw = y_true is not None or y_score is not None
        has_points = precision is not None or recall is not None
        if has_raw == has_points:
            raise ValueError(
                "provide exactly one input mode:"
                " (y_true, y_score) or (precision, recall)"
            )

        if has_raw:
            if y_true is None or y_score is None:
                raise ValueError("both y_true and y_score are required")
            precision, recall = _compute_pr_curve(
                y_true=np.ravel(y_true),
                y_score=np.ravel(y_score),
                pos_label=pos_label,
            )
        else:
            if precision is None or recall is None:
                raise ValueError("both precision and recall are required")
            recall, precision = _coerce_curve_xy(
                recall, precision, "recall", "precision"
            )

        _validate_curve_range(recall, "recall")
        _validate_curve_range(precision, "precision")

        auc = _average_precision(precision, recall)

        opts = dict(opts)
        opts["xlabel"] = opts.get("xlabel", "Recall")
        opts["ylabel"] = opts.get("ylabel", "Precision")
        opts["legend"] = _curve_legend(opts.get("legend"), ["PR", "Baseline"])
        opts["title"] = opts.get("title", "PR Curve (AUC={:.4f})".format(auc))

        if has_raw:
            y_true_arr = np.ravel(np.asarray(y_true))
            positive_rate = float(np.mean(y_true_arr == pos_label))
        else:
            positive_rate = float(precision[0]) if float(recall[0]) == 0.0 else None

        baseline = [positive_rate, positive_rate] if positive_rate is not None else None

        data = [
            {
                "x": recall.tolist(),
                "y": precision.tolist(),
                "name": opts["legend"][0],
                "type": "scatter",
                "mode": "lines",
            },
        ]
        if baseline is not None:
            data.append(
                {
                    "x": [0.0, 1.0],
                    "y": baseline,
                    "name": opts["legend"][1],
                    "type": "scatter",
                    "mode": "lines",
                    "line": {"dash": "dash"},
                }
            )

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
    def heatmap(self, X, win=None, env=None, update=None, opts=None):
        """
        This function draws a heatmap. It takes as input an `NxM` tensor `X`
        that specifies the value at each location in the heatmap.

        `update` can be used to efficiently update the data of an existing plot
        saved to a window given by `win`. Use the value 'appendRow' to append
        data row-wise, 'appendColumn' to append data column-wise,
        'prependRow' to prepend data row-wise,
        'prependColumn' to prepend data column-wise, 'replace' to use new data,
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
                "z": X.tolist(),
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
    def confusion_matrix(
        self,
        y_true=None,
        y_pred=None,
        cm=None,
        labels=None,
        normalize=None,
        update=None,
        win=None,
        env=None,
        opts=None,
    ):
        """
        Draw a confusion matrix for classification evaluation.

        You can either provide raw label vectors (`y_true`, `y_pred`) or a
        precomputed confusion matrix (`cm`).

        The following `opts` are supported:

        - `opts.title`       : plot title (`string`; default = `Confusion Matrix`)
        - `opts.xlabel`      : x-axis label (`string`; default = `Predicted`)
        - `opts.ylabel`      : y-axis label (`string`; default = `Actual`)
        - `opts.colormap`    : Plotly colorscale (`string`; default = `Blues`)
        - `opts.showCounts`  : show raw counts in cells (`bool`; default = `True`)
        - `opts.showPercent` : show percentages in cells (`bool`; default = `True`
                               when normalized, `False` otherwise)
        - `opts.layoutopts`  : additional backend layout options (`dict`)

        `update` may be used to modify an existing confusion matrix window
        instead of creating a new one; it takes one of `None`, `'replace'`
        (redraw the whole matrix in `win`) or `'remove'` (delete `win`).
        """
        opts = {} if opts is None else dict(opts)
        _title2str(opts)
        _assert_opts(opts)

        valid_update = (None, "replace", "remove")
        assert update in valid_update, "update must be one of: {}".format(valid_update)

        if update == "remove":
            assert win is not None, "win must be provided to remove a window"
            return self._send(
                {"data": [], "delete": True, "win": win, "eid": env},
                endpoint="update",
            )

        has_raw = y_true is not None or y_pred is not None
        has_matrix = cm is not None
        if has_raw == has_matrix:
            raise ValueError("provide exactly one input mode: (y_true, y_pred) or (cm)")

        if has_raw:
            if y_true is None or y_pred is None:
                raise ValueError("both y_true and y_pred are required")
            y_true = np.asarray(y_true).ravel()
            y_pred = np.asarray(y_pred).ravel()
            if labels is None:
                labels = np.unique(np.concatenate([y_true, y_pred])).tolist()
        else:
            cm = np.asarray(cm)
            if cm.ndim != 2 or cm.shape[0] != cm.shape[1]:
                raise ValueError("cm must be a square 2D array")
            if labels is None:
                labels = list(range(cm.shape[0]))
            if len(labels) != cm.shape[0]:
                raise ValueError(
                    "number of labels must match confusion matrix dimensions"
                )

        if len(set(labels)) != len(labels):
            raise ValueError("labels must be unique")

        if has_raw:
            cm = _compute_confusion_matrix(y_true, y_pred, labels)

        valid_normalize = (None, "true", "pred", "all")
        if normalize not in valid_normalize:
            raise ValueError("normalize must be one of: {}".format(valid_normalize))

        raw_cm = cm.copy()
        if normalize == "true":
            row_sums = cm.sum(axis=1, keepdims=True).astype(float)
            row_sums[row_sums == 0] = 1
            cm = cm.astype(float) / row_sums
        elif normalize == "pred":
            col_sums = cm.sum(axis=0, keepdims=True).astype(float)
            col_sums[col_sums == 0] = 1
            cm = cm.astype(float) / col_sums
        elif normalize == "all":
            total = float(cm.sum())
            if total == 0:
                warnings.warn(
                    "confusion matrix sum is zero; normalized values will be zero",
                    UserWarning,
                )
                cm = cm.astype(float)
            else:
                cm = cm.astype(float) / total

        str_labels = [str(lbl) for lbl in labels]

        opts["xlabel"] = opts.get("xlabel", "Predicted")
        opts["ylabel"] = opts.get("ylabel", "Actual")
        opts["title"] = opts.get("title", "Confusion Matrix")
        colormap = opts.get("colormap", "Blues")

        show_counts = opts.get("showCounts", True)
        show_percent = opts.get("showPercent", normalize is not None)

        data = [
            {
                "z": cm.tolist(),
                "x": str_labels,
                "y": str_labels,
                "type": "heatmap",
                "colorscale": colormap,
                "showscale": True,
            }
        ]

        annotations = []
        max_val = float(cm.max()) if cm.size > 0 else 1.0
        threshold = max_val / 2.0
        raw_total = float(raw_cm.sum())
        raw_is_integer = np.issubdtype(raw_cm.dtype, np.integer)

        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                cell_val = cm[i, j]
                parts = []
                if show_counts:
                    raw_val = raw_cm[i, j]
                    if raw_is_integer:
                        parts.append(str(int(raw_val)))
                    else:
                        parts.append("{:.3g}".format(float(raw_val)))
                if show_percent:
                    if normalize is not None:
                        parts.append("{:.1%}".format(cell_val))
                    else:
                        pct = raw_cm[i, j] / raw_total if raw_total > 0 else 0
                        parts.append("{:.1%}".format(pct))
                text = "<br>".join(parts) if parts else ""

                font_color = "white" if cell_val > threshold else "black"

                annotations.append(
                    {
                        "x": str_labels[j],
                        "y": str_labels[i],
                        "text": text,
                        "showarrow": False,
                        "font": {"color": font_color},
                    }
                )

        layout = _opts2layout(opts)
        layout["annotations"] = annotations
        layout["xaxis"] = layout.get("xaxis", {})
        layout["xaxis"]["title"] = opts["xlabel"]
        layout["xaxis"]["side"] = "bottom"
        layout["yaxis"] = layout.get("yaxis", {})
        layout["yaxis"]["title"] = opts["ylabel"]
        layout["yaxis"]["autorange"] = "reversed"

        data_to_send = {
            "data": data,
            "win": win,
            "eid": env,
            "layout": layout,
            "opts": opts,
        }
        endpoint = "events"
        if update:
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

        minx, maxx = np.nanmin(X), np.nanmax(X)
        bins = np.histogram(X, bins=opts["numbins"], range=(minx, maxx))[0]
        linrange = np.linspace(minx, maxx, opts["numbins"])

        return self.bar(X=bins, Y=linrange, opts=opts, win=win, env=env)

    @pytorch_wrap
    def histogram2d(self, X, Y, win=None, env=None, opts=None):
        """
        This function draws a 2D histogram (density map) of paired data. It
        takes two `N` tensors `X` and `Y` of equal length that hold the
        coordinates of `N` points; the points are binned into a 2D grid and
        each cell is colored by the number of points that fall in it.

        The following plot-specific `opts` are supported:

        - `opts.xnumbins`: number of bins along the x-axis
                           (`number`; default lets Plotly choose)
        - `opts.ynumbins`: number of bins along the y-axis
                           (`number`; default lets Plotly choose)
        - `opts.colormap`: colormap (`string`; default = `'Viridis'`)
        - `opts.histnorm`: normalization of the bin counts, one of `''`,
                           `'percent'`, `'probability'`, `'density'`, or
                           `'probability density'`
        """

        X = np.squeeze(np.asarray(X))
        Y = np.squeeze(np.asarray(Y))
        assert X.ndim == 1 and Y.ndim == 1, "X and Y should be one-dimensional"
        assert len(X) == len(Y), "X and Y should have the same length"

        opts = {} if opts is None else opts
        opts["colormap"] = opts.get("colormap", "Viridis")
        _title2str(opts)
        _assert_opts(opts)

        trace = {
            "x": X.tolist(),
            "y": Y.tolist(),
            "type": "histogram2d",
            "colorscale": opts.get("colormap"),
        }
        if opts.get("xnumbins") is not None:
            trace["nbinsx"] = opts["xnumbins"]
        if opts.get("ynumbins") is not None:
            trace["nbinsy"] = opts["ynumbins"]
        if opts.get("histnorm") is not None:
            trace["histnorm"] = opts["histnorm"]

        return self._send(
            {
                "data": [trace],
                "win": win,
                "eid": env,
                "layout": _opts2layout(opts),
                "opts": opts,
            },
            endpoint="events",
        )

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
            ), "number of legend labels must match number of columns"

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
        opts["xmin"] = float(opts.get("xmin", np.nanmin(X)))
        opts["xmax"] = float(opts.get("xmax", np.nanmax(X)))
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
                isinstance(opts["normalize"], numbers.Number)
                and opts["normalize"] > 0
                and np.isfinite(opts["normalize"])
            ), "opts.normalize should be a finite positive number"
            magnitude = np.sqrt(np.add(np.multiply(X, X), np.multiply(Y, Y)))
            finite_mask = np.isfinite(magnitude)

            if not np.any(finite_mask):
                warnings.warn(
                    "Skipping quiver normalization: all magnitudes are non-finite (NaN or Inf)",
                    RuntimeWarning,
                )
            else:
                max_mag = magnitude[finite_mask].max()

                if max_mag <= 0:
                    warnings.warn(
                        "Skipping quiver normalization: max magnitude is zero",
                        RuntimeWarning,
                    )
                else:
                    scale = max_mag / opts["normalize"]

                    if scale <= 0 or not np.isfinite(scale):
                        warnings.warn(
                            "Skipping quiver normalization: invalid scale computed",
                            RuntimeWarning,
                        )
                    else:
                        X = np.where(np.isfinite(X), X, np.nan)
                        Y = np.where(np.isfinite(Y), Y, np.nan)
                        X = X / scale
                        Y = Y / scale

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
            ), "length of values should be equal to length of labels and parents"

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
    def sankey(self, source, target, value, labels=None, win=None, env=None, opts=None):
        """
        This function draws a Sankey (flow) diagram. Flows are defined by three
        equal-length arrays:

        - `source`: source node index of each link (`N` array of ints)
        - `target`: target node index of each link (`N` array of ints)
        - `value` : magnitude of each link (`N` array of non-negative numbers)

        `labels` is an optional list of node names. If omitted, nodes are
        referenced by their index alone.

        The following `opts` are supported:

        - `opts.labels`     : list of node labels (alternative to the `labels` arg)
        - `opts.pad`        : node padding in px (`number`; default = 15)
        - `opts.thickness`  : node thickness in px (`number`; default = 20)
        - `opts.orientation`: `'h'` (default) or `'v'`
        - `opts.nodecolor`  : node color(s) (`string` or list of strings)
        - `opts.linkcolor`  : link color(s) (`string` or list of strings)
        - `opts.layoutopts` : `dict` of additional backend layout options, e.g.
          `layoutopts = {'plotly': {'font': {'size': 10}}}`.
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        source = np.asarray(source)
        target = np.asarray(target)
        value = np.asarray(value)
        for name, arr in (("source", source), ("target", target), ("value", value)):
            assert arr.ndim <= 1, "sankey {} must be 1-D, got shape {}".format(
                name, arr.shape
            )
        source = source.ravel()
        target = target.ravel()
        value = value.ravel()
        assert (
            len(source) == len(target) == len(value)
        ), "source, target and value must have the same length"
        assert (source >= 0).all(), "sankey source indices must be non-negative"
        assert (target >= 0).all(), "sankey target indices must be non-negative"
        assert (
            source == source.astype(int)
        ).all(), "sankey source indices must be integers"
        assert (
            target == target.astype(int)
        ).all(), "sankey target indices must be integers"
        assert (value >= 0).all(), "sankey link values must be non-negative"

        labels = labels if labels is not None else opts.get("labels")
        if labels is not None and len(source) > 0:
            num_nodes = max(int(source.max()), int(target.max())) + 1
            assert len(labels) >= num_nodes, (
                "labels must cover every referenced node "
                "({} labels for {} nodes)".format(len(labels), num_nodes)
            )

        pad = opts.get("pad", 15)
        thickness = opts.get("thickness", 20)
        orientation = opts.get("orientation", "h")
        assert (
            isinstance(pad, numbers.Number) and pad >= 0
        ), "opts.pad must be a non-negative number"
        assert (
            isinstance(thickness, numbers.Number) and thickness > 0
        ), "opts.thickness must be a positive number"
        assert orientation in ("h", "v"), "opts.orientation must be 'h' or 'v'"

        node = {"pad": pad, "thickness": thickness}
        if labels is not None:
            node["label"] = list(labels)
        if opts.get("nodecolor") is not None:
            node["color"] = opts.get("nodecolor")

        link = {
            "source": source.astype(int).tolist(),
            "target": target.astype(int).tolist(),
            "value": value.tolist(),
        }
        if opts.get("linkcolor") is not None:
            link["color"] = opts.get("linkcolor")

        data = [
            {
                "type": "sankey",
                "orientation": orientation,
                "node": node,
                "link": link,
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
        assert X is not None, "X Cannot be None"
        assert Y1 is not None, "Y1 Cannot be None"
        assert Y2 is not None, "Y2 Cannot be None"
        X = np.asarray(X)
        Y1 = np.asarray(Y1)
        Y2 = np.asarray(Y2)
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
                    "color": opts.get("color_title_y2", "rgb(148, 103, 189)")
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
        self, edges, edgeLabels=None, nodeLabels=None, opts=None, env=None, win=None
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
                * `scheme` : {"same", "different"} nodes with "same" or "different" colors; "same" by default
                * `height` : height of the Pane
                * `width` : width of the Pane
        """
        opts = {} if opts is None else opts
        try:
            import networkx as nx
        except ImportError:
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

    @pytorch_wrap
    def violin(self, X, win=None, env=None, opts=None):
        """
        This function draws violin plots of the specified data. It takes
        input `N` or `NxM` tensor `X` that specifies the `N` data values
        of which to construct the `M` violin plots.

        The following plot-specific `opts` are currently supported:

        - `opts.legend` : labels for each of the columns in `X`
        - `opts.showbox` : overlay a mini box plot inside the violin
                                  (`bool` and default = `True`)
        - `opts.showmeanline` : overlay the mean line (`bool` and default = `True`)
        - `opts.points` : which raw points to show alongside the violin
                                  One of `all`, `outliers`,
                                  `suspectedoutliers`, or `False`
                                  (default = `False`)
        - `opts.jitter` : amount of jitter applied to displayed points
                                  (`float` in `[0, 1]`, default = `0.3`)
        - `opts.orientation` : `v` for vertical and `h` for horizontal
                                  violins
        - `opts.bandwidth` : bandwidth of the kernel density estimate
                                  `None` lets Plotly choose automatically
        - `opts.side` : which side of the centre line to draw.
                                  One of `both` , `positive`,
                                  or `negative`
        """

        X = np.asarray(X)
        if X.ndim > 2:
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
            ), "number of legend labels must match number of columns in X"

        showbox = opts.get("showbox", True)
        showmeanline = opts.get("showmeanline", True)
        points = opts.get("points", False)
        jitter = opts.get("jitter", 0.3)
        orientation = opts.get("orientation", "v")
        bandwidth = opts.get("bandwidth", None)
        side = opts.get("side", "both")

        assert orientation in (
            "v",
            "h",
        ), "opts.orientation must be 'v' (vertical) or 'h' (horizontal)"
        assert side in (
            "both",
            "positive",
            "negative",
        ), "opts.side must be one of 'both', 'positive', or 'negative'"
        assert points in ("all", "outliers", "suspectedoutliers", False), (
            "opts.points must be one of 'all', 'outliers', "
            "'suspectedoutliers', or False"
        )
        if jitter is not None:
            assert (
                isnum(jitter) and 0 <= jitter <= 1
            ), "opts.jitter must be a float between 0 and 1"
        if bandwidth is not None:
            assert (
                isnum(bandwidth) and bandwidth > 0
            ), "opts.bandwidth must be a positive number"

        data = []
        for k in range(X.shape[1]):
            col_data = X.take(k, 1).tolist()
            label = opts["legend"][k] if opts.get("legend") else "column " + str(k)

            trace = {
                "type": "violin",
                "name": label,
                "box": {"visible": showbox},
                "meanline": {"visible": showmeanline},
                "points": points,
                "side": side,
            }
            if jitter is not None:
                trace["jitter"] = jitter

            if orientation == "v":
                trace["y"] = col_data
            else:
                trace["x"] = col_data
                trace["orientation"] = "h"

            if bandwidth is not None:
                trace["bandwidth"] = bandwidth

            if opts.get("opacity") is not None:
                trace["opacity"] = opts["opacity"]

            data.append(trace)

        return self._send(
            {
                "data": data,
                "win": win,
                "eid": env,
                "layout": _opts2layout(opts),
                "opts": opts,
            }
        )

    def table(self, headers, data, win=None, env=None, opts=None):
        """
        This function renders structured data as a styled HTML table.

        - `headers`: a `list` of column header names (`string` or any
           type convertible to `string`).
        - `data`: a 2D `list` of row data, where each row is list or
          `tuple` with same number of elements as `headers`. In case
           of empty list, a table with only header will be rendered.

        The following `opts` are supported:

        - `opts.title`: title for the window (`string`; optional)
        """
        opts = {} if opts is None else opts
        _title2str(opts)
        _assert_opts(opts)

        assert isinstance(headers, list), "headers should be a list"
        assert isinstance(data, list), "data should be a list of rows"
        assert all(
            isinstance(row, (list, tuple)) for row in data
        ), "each row in data should be a list or tuple"
        assert all(
            len(row) == len(headers) for row in data
        ), "each data row must have the same number of columns as headers"

        style = """
            <style>
            .visdom-table {
                font-family: monospace;
                border-collapse: collapse;
                width: 100%;
            }
            .visdom-table th {
                background-color: #2196F3;
                color: white;
                padding: 8px 12px;
                text-align: left;
            }
            .visdom-table td {
                padding: 6px 12px;
                border-bottom: 1px solid #ddd;
            }
            .visdom-table tr:nth-child(even) td {
                background-color: #f2f2f2;
            }
            .visdom-table tr:nth-child(odd) td {
                background-color: #ffffff;
            }
            .visdom-table tr:hover td {
                background-color: #ddeeff;
            }
            </style>
        """

        header_html = "".join("<th>%s</th>" % html.escape(str(h)) for h in headers)
        rows_html = "".join(
            "<tr>%s</tr>"
            % "".join("<td>%s</td>" % html.escape(str(cell)) for cell in row)
            for row in data
        )

        table_html = (
            "%s<table class='visdom-table'>"
            "<thead><tr>%s</tr></thead>"
            "<tbody>%s</tbody>"
            "</table>"
        ) % (style, header_html, rows_html)

        return self.text(text=table_html, win=win, env=env, opts=opts)
