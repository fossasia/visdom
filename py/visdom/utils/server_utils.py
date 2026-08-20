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
import html
import json
import logging
import os
import errno
from collections import OrderedDict

MAX_ENV_NAME_LEN = 25
from collections.abc import Mapping, Sequence
from visdom.server.defaults import (
    DEFAULT_BASE_URL,
    DEFAULT_ENV_PATH,
    DEFAULT_HOSTNAME,
    DEFAULT_MAX_UNDO_HISTORY,
    DEFAULT_PORT,
)
from visdom.utils.shared_utils import (
    warn_once,
    get_rand_id,
    get_new_window_id,
    NanSafeEncoder,
)

# ---- Vaguely server-security related functions ---- #


def check_auth(f):
    """
    Wrapper for server access methods to ensure that the access
    is authorized.
    """

    def _check_auth(handler, *args, **kwargs):
        if not handler.is_authorized():
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


def hash_password(password, salt=None):
    """Hash password using PBKDF2-HMAC-SHA256 with a random salt."""
    if salt is None:
        salt = os.urandom(32)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt.hex() + "$" + dk.hex()


# ------- File management helpers ----- #


class LazyEnvData(Mapping):
    def __init__(self, store, eid):
        self._store = store
        self._eid = eid
        self._raw_dict = None

    def lazy_load_data(self):
        if self._raw_dict is not None:
            return

        try:
            env_data = self._store.load_env(self._eid)
            raw = dict(env_data)
            raw["jsons"] = env_data["jsons"]
            raw["reload"] = env_data["reload"]
            self._raw_dict = raw
        except (KeyError, TypeError) as e:
            raise ValueError(
                "Failed loading environment json: {} - {}".format(self._eid, repr(e))
            )

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


# ------- Environment management helpers ----- #


def escape_eid(eid):
    """Replace forward slashes and other problematic characters
    with underscores and backslashes with hyphen, to avoid recognizing them as
    directories or breaking URLs and filenames.

    Also strips surrounding whitespace. As ``JSONStore`` independently
    strips whitespace before deriving an on-disk filename from an eid,
    so two in-memory eids that differ only by leading/trailing whitespace
    (e.g. ``"main"`` and ``"main "``) would otherwise stay distinct in ``self.state``
    while silently colliding on disk - whichever one is saved last clobbers the other.
    Stripping here, at the single choke point every eid passes through (HTTP handlers,
    websocket handlers, and the storage layer all call this), keeps the in-memory key
    and the on-disk filename in agreement.
    """
    return (
        eid.strip()
        .replace("/", "_")
        .replace("\\", "_")
        .replace("\n", "-")
        .replace("\r", "-")
    )


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
            if opt_name == "caption":
                if isinstance(p.get("content"), dict):
                    p["content"]["caption"] = opt_val
            else:
                p[opt_name] = opt_val

    if "legend" in opts:
        legend = opts["legend"]
        pdata = p["content"]["data"]
        name = args.get("name")
        if name is not None:
            if len(legend) > 0:
                for d in pdata:
                    if d.get("name") == name:
                        d["name"] = legend[0]
        else:
            if len(legend) < len(pdata):
                logging.warning(
                    "update_window: legend has %d entries but pane has %d"
                    " traces; leaving trailing traces' names unchanged",
                    len(legend),
                    len(pdata),
                )
            for i, d in enumerate(pdata):
                if i < len(legend):
                    d["name"] = legend[i]
    p["version"] += 1
    return p


def window(args):
    """Build a window dict structure for sending to client"""
    uid = args.get("win", get_new_window_id())
    version = args.get("version", 1)
    if uid is None:
        uid = get_new_window_id()
    opts = args.get("opts", {})

    ptype = args["data"][0]["type"]
    is_visdom_type = "content" in args["data"][0]

    p = {
        "command": "window",
        "version": version,
        "id": str(uid),
        "title": opts.get("title", ""),
        "inflate": opts.get("inflate", True),
        "width": opts.get("width"),
        "height": opts.get("height"),
        "contentID": get_rand_id(),  # to detected updated windows
        "comment": opts.get("comment", ""),
    }

    if ptype in ["image_history", "plot_history"] and is_visdom_type:
        p.update(
            {
                "content": [args["data"][0]["content"]],
                "selected": 0,
                "type": ptype,
                "show_slider": opts.get("show_slider", True),
            }
        )
    elif ptype in ["image", "text", "properties", "hparams"] and is_visdom_type:
        p.update({"content": args["data"][0]["content"], "type": ptype})
    elif ptype == "table" and is_visdom_type:
        p.update(
            {
                "content": args["data"][0]["content"],
                "type": ptype,
                "editable": opts.get("editable", True),
            }
        )
    elif ptype == "network" and is_visdom_type:
        p.update(
            {
                "content": args["data"][0]["content"],
                "type": ptype,
                "directed": opts.get("directed", False),
                "showEdgeLabels": opts.get("showEdgeLabels", "hover"),
                "showVertexLabels": opts.get("showVertexLabels", "hover"),
            }
        )
    elif ptype in ["embeddings"] and is_visdom_type:
        p.update(
            {
                "content": args["data"][0]["content"],
                "type": ptype,
                "old_content": [],  # Used to cache previous to prevent recompute
            }
        )
        p["content"]["has_previous"] = False
    else:
        p["content"] = {
            "data": args["data"],
            "layout": args["layout"],
            "caption": opts.get("caption"),
        }
        p["type"] = "plot"

    return p


def gather_envs(state, store):
    return sorted(set(store.list_envs() + list(state.keys())))


def compare_envs(state, eids, socket, store, show_all=False):
    logging.info("comparing envs")
    use_env_names = all(len(str(eid)) <= MAX_ENV_NAME_LEN for eid in eids)
    eidNums = {e: e if use_env_names else str(i) for i, e in enumerate(eids)}
    envs = {}
    for eid in eids:
        if eid in state:
            envs[eid] = state.get(eid)
        else:
            env = store.load_env(eid)
            if env:
                state[eid] = env
                envs[eid] = env

    valid_eids = [eid for eid in eids if eid in envs]
    if not valid_eids:
        socket.write_message(json.dumps({"command": "layout"}, cls=NanSafeEncoder))
        socket.eid = eids
        return
    base_eid = valid_eids[0]
    res = copy.deepcopy(envs[base_eid])
    name2Wid = {
        res["jsons"][wid].get("title", None): wid + "_compare"
        for wid in res.get("jsons", {})
        if "title" in res["jsons"][wid]
    }
    for wid in list(res["jsons"].keys()):
        res["jsons"][wid + "_compare"] = res["jsons"][wid]
        res["jsons"][wid] = None
        res["jsons"].pop(wid)
    seen_dest_wids = set()
    for ix, eid in enumerate(valid_eids):
        env = envs[eid]
        for wid in env.get("jsons", {}).keys():
            win = env["jsons"][wid]
            ptype = win.get("type", None)
            if ptype not in ["plot", "image"]:
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
            base_ptype = destWidJson.get("type", None)
            if base_ptype == "image_compare":
                base_ptype = "image"
            if ptype != base_ptype:
                continue
            # Combine windows only when the shared title also maps to the same
            # supported window type across envs. For plots, if a data source is
            # labeled "name" in the legend, rename it to "envId_legend", where
            # envId is the enumeration of the selected environments (not the
            # long environment id string), to make combined plot lines readable.
            if ptype == "image":
                if ix == 0 and destWid not in seen_dest_wids:
                    seen_dest_wids.add(destWid)
                    destWidJson["has_compare"] = False
                    destWidJson["contentID"] = get_rand_id()

                    first_img = copy.deepcopy(destWidJson["content"])
                    caption = first_img.get("caption")
                    first_img["caption"] = "{}_{}".format(
                        eidNums[eid], caption if caption is not None else "image"
                    )

                    destWidJson["content"] = [first_img]
                    destWidJson["type"] = "image_compare"
                else:
                    if destWid not in seen_dest_wids:
                        continue  # base image never initialised; skip
                    destWidJson["has_compare"] = True
                    next_img = copy.deepcopy(win["content"])
                    caption = next_img.get("caption")
                    next_img["caption"] = "{}_{}".format(
                        eidNums[eid], caption if caption is not None else "image"
                    )
                    destWidJson["content"].append(next_img)
            elif ptype == "plot":
                if ix == 0:
                    if "name" not in destWidJson["content"]["data"][0]:
                        continue  # Skip windows with unnamed data
                    destWidJson["has_compare"] = False
                    destWidJson["content"]["layout"]["showlegend"] = True
                    destWidJson["contentID"] = get_rand_id()
                    for dataIdx, data in enumerate(destWidJson["content"]["data"]):
                        if "name" not in data:
                            break  # stop working with this plot, not right format
                        destWidJson["content"]["data"][dataIdx][
                            "name"
                        ] = "{}_{}".format(eidNums[eid], data["name"])
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

    # Make sure that only windows shared by at least two envs are shown.
    # Check the has_compare flag for plots, image comparisons, and similar windows.
    for destWid in list(res["jsons"].keys()):
        if ("has_compare" not in res["jsons"][destWid]) or (
            not res["jsons"][destWid]["has_compare"]
        ):
            del res["jsons"][destWid]

    if show_all:
        for eid in sorted(envs.keys()):
            eid_num = eidNums[eid]
            for wid, win in envs[eid].get("jsons", {}).items():
                win_title = win.get("title", "")
                new_wid = "{}_env_{}".format(eid, wid)
                if new_wid in res["jsons"]:
                    continue
                win_copy = copy.deepcopy(win)
                win_copy["id"] = new_wid
                label = (
                    "[{}] {}".format(eid_num, html.escape(win_title))
                    if win_title
                    else "[{}]".format(eid_num)
                )
                win_copy["title"] = label
                if isinstance(win_copy.get("layout"), dict):
                    win_copy["layout"]["title"] = {"text": label}
                if isinstance(win_copy.get("content"), dict) and isinstance(
                    win_copy["content"].get("layout"), dict
                ):
                    win_copy["content"]["layout"]["title"] = {"text": label}
                win_copy["has_compare"] = True
                res["jsons"][new_wid] = win_copy

    # create legend mapping environment names to environment numbers so one can
    # look it up for the new legend
    tableRows = [
        "<tr> <td> {} </td> <td> {} </td> </tr>".format(
            html.escape(str(v)), html.escape(str(eidNums[v]))
        )
        for v in sorted(eidNums)
    ]

    tbl = """<style>
    table, th, td {{
        border: 1px solid black;
    }}
    </style>
    <table> {} </table>""".format(
        " ".join(tableRows)
    )

    res["jsons"]["window_compare_legend"] = {
        "command": "window",
        "version": 1,
        "id": "window_compare_legend",
        "title": "compare_legend",
        "inflate": True,
        "width": None,
        "height": None,
        "contentID": "compare_legend",
        "content": tbl,
        "type": "text",
        "layout": {"title": {"text": "compare_legend"}},
        "i": 1,
        "has_compare": True,
        "commentsDisabled": True,
    }
    if "reload" in res:
        socket.write_message(
            json.dumps({"command": "reload", "data": res["reload"]}, cls=NanSafeEncoder)
        )

    jsons = list(res.get("jsons", {}).values())
    windows = sorted(jsons, key=lambda k: ("i" not in k, k.get("i", None)))
    for v in windows:
        socket.write_message(json.dumps(v, cls=NanSafeEncoder))

    socket.write_message(json.dumps({"command": "layout"}, cls=NanSafeEncoder))
    socket.eid = eids


# ------- Broadcasting functions ---------- #


def broadcast_envs(handler, target_subs=None):
    if target_subs is None:
        target_subs = handler.subs.values()
    for sub in target_subs:
        sub.write_message(
            json.dumps(
                {"command": "env_update", "data": list(handler.state.keys())},
                cls=NanSafeEncoder,
            )
        )


def broadcast_tags(handler, eid, tags, target_subs=None):
    """Broadcast one environment's key/value tags to browser clients."""
    if target_subs is None:
        target_subs = handler.subs.values()
    message = json.dumps(
        {"command": "tags_update", "data": {"eid": eid, "tags": tags}},
        cls=NanSafeEncoder,
    )
    for sub in target_subs:
        sub.write_message(message)


def send_to_sources(handler, msg):
    target_sources = handler.sources.values()
    for source in target_sources:
        source.write_message(json.dumps(msg, cls=NanSafeEncoder))


def load_env(state, eid, socket, store):
    """load an environment to a client by socket"""
    env = {}
    if eid in state:
        env = state.get(eid)
    else:
        loaded = store.load_env(eid)
        if loaded:
            env = loaded
            state[eid] = env

    if "reload" in env:
        socket.write_message(
            json.dumps({"command": "reload", "data": env["reload"]}, cls=NanSafeEncoder)
        )

    jsons = list(env.get("jsons", {}).values())
    windows = sorted(jsons, key=lambda k: ("i" not in k, k.get("i", None)))
    for v in windows:
        msg = dict(v)
        msg["eid"] = eid
        socket.write_message(json.dumps(msg, cls=NanSafeEncoder))

    socket.write_message(json.dumps({"command": "layout"}, cls=NanSafeEncoder))
    socket.write_message(
        json.dumps(
            {
                "command": "undo_state",
                "eid": eid,
                "count": count_deleted(store, eid),
            },
            cls=NanSafeEncoder,
        )
    )
    socket.eid = eid


def broadcast(self, msg, eid):
    for s in self.subs:
        if isinstance(self.subs[s].eid, (list, dict, set)):
            if eid in self.subs[s].eid:
                self.subs[s].write_message(msg)
        else:
            if self.subs[s].eid == eid:
                self.subs[s].write_message(msg)


def push_deleted(store, eid, win_id, p_data):
    """Append a closed pane to the environment's undo stack (LIFO), keeping at
    most DEFAULT_MAX_UNDO_HISTORY entries. Persistence is delegated to ``store``
    (a DataStore), which no-ops when running without an env_path."""
    stack = store.load_undo(eid)
    stack.append([win_id, p_data])
    if len(stack) > DEFAULT_MAX_UNDO_HISTORY:
        stack = stack[-DEFAULT_MAX_UNDO_HISTORY:]
    store.save_undo(eid, stack)


def pop_deleted(store, eid):
    """Pop and return the most recently closed pane as (win_id, p_data),
    or None if the environment has no undo history."""
    stack = store.load_undo(eid)
    if not stack:
        return None
    win_id, p_data = stack.pop()
    if stack:
        store.save_undo(eid, stack)
    else:
        store.clear_undo(eid)
    return win_id, p_data


def clear_deleted(store, eid):
    """Remove an environment's undo history via the ``store`` backend."""
    store.clear_undo(eid)


def count_deleted(store, eid):
    """Return the number of closed panes available to undo for an env."""
    return len(store.load_undo(eid))


def broadcast_undo_state(handler, eid, store):
    """Tell subscribers of an env how many closed panes remain to undo."""
    msg = json.dumps(
        {
            "command": "undo_state",
            "eid": eid,
            "count": count_deleted(store, eid),
        },
        cls=NanSafeEncoder,
    )
    broadcast(handler, msg, eid)


def notify(handler, message, type="info", duration=None, eid=None, target_subs=None):
    payload = {"message": message, "type": type}
    if duration is not None:
        payload["duration"] = duration

    msg = json.dumps({"command": "notification", "data": payload}, cls=NanSafeEncoder)

    if target_subs is not None:
        for sub in target_subs:
            sub.write_message(msg)
        return

    if eid is not None:
        broadcast(handler, msg, eid)
        return

    for sub in handler.subs.values():
        sub.write_message(msg)


def register_window(self, p, eid):
    # in case env doesn't exist
    is_new_env = False
    if eid not in self.state:
        is_new_env = True
        self.state[eid] = {"jsons": {}, "reload": {}}

    env = self.state[eid]["jsons"]

    if p["id"] in env:
        p["i"] = env[p["id"]]["i"]
        p["comment"] = env[p["id"]].get("comment", p.get("comment", ""))
    else:
        # not len(env): closing any window but the last would hand the next
        # one an index that is still in use. Same rule as the undo path.
        p["i"] = max((w.get("i", -1) for w in env.values()), default=-1) + 1

    env[p["id"]] = p
    self.mark_dirty(eid)

    broadcast_msg = dict(p)
    broadcast_msg["eid"] = eid
    broadcast(self, json.dumps(broadcast_msg, cls=NanSafeEncoder), eid)
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
