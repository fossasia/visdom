#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Utilities for the server architecture that don't really have
a more appropriate place.

At the moment, this just inherited all of the floating functions
in the previous server.py class.
"""


import copy
import hashlib
import json
import logging
import os
import time
import tornado.escape
from collections import OrderedDict

try:
    # for after python 3.8
    from collections.abc import Mapping, Sequence
except ImportError:
    # for python 3.7 and below
    from collections import Mapping, Sequence
from visdom.server.defaults import (
    LAYOUT_FILE,
    DEFAULT_BASE_URL,
    DEFAULT_ENV_PATH,
    DEFAULT_HOSTNAME,
    DEFAULT_PORT,
)
from visdom.utils.shared_utils import warn_once, get_rand_id, get_new_window_id


# ---- Vaguely server-security related functions ---- #


def check_auth(f):
    """
    Wrapper for server access methods to ensure that the access
    is authorized.
    """

    def _check_auth(handler, *args, **kwargs):
        # TODO this should call a shared method of the handler
        handler.last_access = time.time()
        if handler.login_enabled and not handler.current_user:
            handler.set_status(400)
            return
        f(handler, *args, **kwargs)

    return _check_auth


def set_cookie(value=None):
    """Create cookie secret key for authentication"""
    if value is not None:
        cookie_secret = value
    else:
        cookie_secret = input("Please input your cookie secret key here: ")
    with open(DEFAULT_ENV_PATH + "COOKIE_SECRET", "w") as cookie_file:
        cookie_file.write(cookie_secret)


def hash_password(password):
    """Hashing Password with SHA-256"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ------- File management helprs ----- #


class LazyEnvData(Mapping):
    def __init__(self, env_path_file):
        self._env_path_file = env_path_file
        self._raw_dict = None

    def lazy_load_data(self):
        if self._raw_dict is not None:
            return

        try:
            with open(self._env_path_file, "r") as fn:
                env_data = tornado.escape.json_decode(fn.read())
        except Exception as e:
            raise ValueError(
                "Failed loading environment json: {} - {}".format(
                    self._env_path_file, repr(e)
                )
            )
        self._raw_dict = {"jsons": env_data["jsons"], "reload": env_data["reload"]}

    def __getitem__(self, key):
        self.lazy_load_data()
        return self._raw_dict.__getitem__(key)

    def __setitem__(self, key, value):
        self.lazy_load_data()
        return self._raw_dict.__setitem__(key, value)

    def __iter__(self):
        self.lazy_load_data()
        return iter(self._raw_dict)

    def __len__(self):
        self.lazy_load_data()
        return len(self._raw_dict)


def serialize_env(state, eids, env_path=DEFAULT_ENV_PATH):
    env_ids = [i for i in eids if i in state]
    if env_path is not None:
        for env_id in env_ids:
            env_path_file = os.path.join(env_path, "{0}.json".format(env_id))
            with open(env_path_file, "w") as fn:
                if isinstance(state[env_id], LazyEnvData):
                    fn.write(json.dumps(state[env_id]._raw_dict))
                else:
                    fn.write(json.dumps(state[env_id]))
    return env_ids


def serialize_all(state, env_path=DEFAULT_ENV_PATH):
    serialize_env(state, list(state.keys()), env_path=env_path)


# ------- Environment management helpers ----- #


def escape_eid(eid):
    """Replace slashes with underscores, to avoid recognizing them
    as directories.
    """
    return eid.replace("/", "_")


def extract_eid(args):
    """Extract eid from args. If eid does not exist in args,
    it returns 'main'."""
    eid = "main" if args.get("eid") is None else args.get("eid")
    return escape_eid(eid)


def update_window(p, args):
    """Adds new args to a window if they exist"""
    content = p["content"]
    layout_update = args.get("layout", {})
    for layout_name, layout_val in layout_update.items():
        if layout_val is not None:
            content["layout"][layout_name] = layout_val
    opts = args.get("opts", {})
    for opt_name, opt_val in opts.items():
        if opt_val is not None:
            p[opt_name] = opt_val

    if "legend" in opts:
        pdata = p["content"]["data"]
        for i, d in enumerate(pdata):
            d["name"] = opts["legend"][i]
    return p


def window(args):
    """Build a window dict structure for sending to client"""
    uid = args.get("win", get_new_window_id())
    if uid is None:
        uid = get_new_window_id()
    opts = args.get("opts", {})

    ptype = args["data"][0]["type"]

    p = {
        "command": "window",
        "id": str(uid),
        "title": opts.get("title", ""),
        "inflate": opts.get("inflate", True),
        "width": opts.get("width"),
        "height": opts.get("height"),
        "contentID": get_rand_id(),  # to detected updated windows
    }

    if ptype == "image_history":
        p.update(
            {
                "content": [args["data"][0]["content"]],
                "selected": 0,
                "type": ptype,
                "show_slider": opts.get("show_slider", True),
            }
        )
    elif ptype in ["image", "text", "properties"]:
        p.update({"content": args["data"][0]["content"], "type": ptype})
    elif ptype == "network":
        p.update(
            {
                "content": args["data"][0]["content"],
                "type": ptype,
                "directed": opts.get("directed", False),
                "showEdgeLabels": opts.get("showEdgeLabels", "hover"),
                "showVertexLabels": opts.get("showVertexLabels", "hover"),
            }
        )
    elif ptype in ["embeddings"]:
        p.update(
            {
                "content": args["data"][0]["content"],
                "type": ptype,
                "old_content": [],  # Used to cache previous to prevent recompute
            }
        )
        p["content"]["has_previous"] = False
    else:
        p["content"] = {"data": args["data"], "layout": args["layout"]}
        p["type"] = "plot"

    return p


def gather_envs(state, env_path=DEFAULT_ENV_PATH):
    if env_path is not None:
        items = [i.replace(".json", "") for i in os.listdir(env_path) if ".json" in i]
    else:
        items = []
    return sorted(list(set(items + list(state.keys()))))


def compare_envs(state, eids, socket, env_path=DEFAULT_ENV_PATH):
    logging.info("comparing envs")
    eidNums = {e: str(i) for i, e in enumerate(eids)}
    env = {}
    envs = {}
    for eid in eids:
        if eid in state:
            envs[eid] = state.get(eid)
        elif env_path is not None:
            p = os.path.join(env_path, eid.strip(), ".json")
            if os.path.exists(p):
                with open(p, "r") as fn:
                    env = tornado.escape.json_decode(fn.read())
                    state[eid] = env
                    envs[eid] = env

    res = copy.deepcopy(envs[list(envs.keys())[0]])
    name2Wid = {
        res["jsons"][wid].get("title", None): wid + "_compare"
        for wid in res.get("jsons", {})
        if "title" in res["jsons"][wid]
    }
    for wid in list(res["jsons"].keys()):
        res["jsons"][wid + "_compare"] = res["jsons"][wid]
        res["jsons"][wid] = None
        res["jsons"].pop(wid)

    for ix, eid in enumerate(sorted(envs.keys())):
        env = envs[eid]
        for wid in env.get("jsons", {}).keys():
            win = env["jsons"][wid]
            if win.get("type", None) != "plot":
                continue
            if "content" not in win:
                continue
            if "title" not in win:
                continue
            title = win["title"]
            if title not in name2Wid or title == "":
                continue

            destWid = name2Wid[title]
            destWidJson = res["jsons"][destWid]
            # Combine plots with the same window title. If plot data source was
            # labeled "name" in the legend, rename to "envId_legend" where
            # envId is enumeration of the selected environments (not the long
            # environment id string). This makes plot lines more readable.
            if ix == 0:
                if "name" not in destWidJson["content"]["data"][0]:
                    continue  # Skip windows with unnamed data
                destWidJson["has_compare"] = False
                destWidJson["content"]["layout"]["showlegend"] = True
                destWidJson["contentID"] = get_rand_id()
                for dataIdx, data in enumerate(destWidJson["content"]["data"]):
                    if "name" not in data:
                        break  # stop working with this plot, not right format
                    destWidJson["content"]["data"][dataIdx]["name"] = "{}_{}".format(
                        eidNums[eid], data["name"]
                    )
            else:
                if "name" not in destWidJson["content"]["data"][0]:
                    continue  # Skip windows with unnamed data
                # has_compare will be set to True only if the window title is
                # shared by at least 2 envs.
                destWidJson["has_compare"] = True
                for _dataIdx, data in enumerate(win["content"]["data"]):
                    data = copy.deepcopy(data)
                    if "name" not in data:
                        destWidJson["has_compare"] = False
                        break  # stop working with this plot, not right format
                    data["name"] = "{}_{}".format(eidNums[eid], data["name"])
                    destWidJson["content"]["data"].append(data)

    # Make sure that only plots that are shared by at least two envs are shown.
    # Check has_compare flag
    for destWid in list(res["jsons"].keys()):
        if ("has_compare" not in res["jsons"][destWid]) or (
            not res["jsons"][destWid]["has_compare"]
        ):
            del res["jsons"][destWid]

    # create legend mapping environment names to environment numbers so one can
    # look it up for the new legend
    tableRows = [
        "<tr> <td> {} </td> <td> {} </td> </tr>".format(v, eidNums[v]) for v in eidNums
    ]

    tbl = """"<style>
    table, th, td {{
        border: 1px solid black;
    }}
    </style>
    <table> {} </table>""".format(
        " ".join(tableRows)
    )

    res["jsons"]["window_compare_legend"] = {
        "command": "window",
        "id": "window_compare_legend",
        "title": "compare_legend",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": "compare_legend",
        "content": tbl,
        "type": "text",
        "layout": {"title": "compare_legend"},
        "i": 1,
        "has_compare": True,
    }
    if "reload" in res:
        socket.write_message(json.dumps({"command": "reload", "data": res["reload"]}))

    jsons = list(res.get("jsons", {}).values())
    windows = sorted(jsons, key=lambda k: ("i" not in k, k.get("i", None)))
    for v in windows:
        socket.write_message(v)

    socket.write_message(json.dumps({"command": "layout"}))
    socket.eid = eids


# ------- Broadcasting functions ---------- #


def broadcast_envs(handler, target_subs=None):
    if target_subs is None:
        target_subs = handler.subs.values()
    for sub in target_subs:
        sub.write_message(
            json.dumps({"command": "env_update", "data": list(handler.state.keys())})
        )


def send_to_sources(handler, msg):
    target_sources = handler.sources.values()
    for source in target_sources:
        source.write_message(json.dumps(msg))


def load_env(state, eid, socket, env_path=DEFAULT_ENV_PATH):
    """load an environment to a client by socket"""
    env = {}
    if eid in state:
        env = state.get(eid)
    elif env_path is not None:
        p = os.path.join(env_path, eid.strip(), ".json")
        if os.path.exists(p):
            with open(p, "r") as fn:
                env = tornado.escape.json_decode(fn.read())
                state[eid] = env

    if "reload" in env:
        socket.write_message(json.dumps({"command": "reload", "data": env["reload"]}))

    jsons = list(env.get("jsons", {}).values())
    windows = sorted(jsons, key=lambda k: ("i" not in k, k.get("i", None)))
    for v in windows:
        socket.write_message(v)

    socket.write_message(json.dumps({"command": "layout"}))
    socket.eid = eid


def broadcast(self, msg, eid):
    for s in self.subs:
        if isinstance(self.subs[s].eid, dict):
            if eid in self.subs[s].eid:
                self.subs[s].write_message(msg)
        else:
            if self.subs[s].eid == eid:
                self.subs[s].write_message(msg)


def register_window(self, p, eid):
    # in case env doesn't exist
    is_new_env = False
    if eid not in self.state:
        is_new_env = True
        self.state[eid] = {"jsons": {}, "reload": {}}

    env = self.state[eid]["jsons"]

    if p["id"] in env:
        p["i"] = env[p["id"]]["i"]
    else:
        p["i"] = len(env)

    env[p["id"]] = p

    broadcast(self, p, eid)
    if is_new_env:
        broadcast_envs(self)
    self.write(p["id"])


# ----- Json patch helpers ---------- #


def order_by_key(kv):
    key, val = kv
    return key


# Based on json-stable-stringify-python from @haochi with some usecase modifications
def recursive_order(node):
    if isinstance(node, Mapping):
        ordered_mapping = OrderedDict(sorted(node.items(), key=order_by_key))
        for key, value in ordered_mapping.items():
            ordered_mapping[key] = recursive_order(value)
        return ordered_mapping
    elif isinstance(node, Sequence):
        if isinstance(node, (bytes,)):
            return node
        elif isinstance(node, (str,)):
            return node
        else:
            return [recursive_order(item) for item in node]
    if isinstance(node, float) and node.is_integer():
        return int(node)
    return node


def stringify(node):
    return json.dumps(recursive_order(node), separators=(",", ":"))


def hash_md_window(window_json):
    json_string = stringify(window_json).encode("utf-8")
    return hashlib.md5(json_string).hexdigest()
