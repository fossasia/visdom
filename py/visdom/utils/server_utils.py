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
import functools
import hashlib
import html
import json
import logging
import os
import errno
from collections import OrderedDict

import tornado.ioloop

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

    The wrapped method's return value is handed back untouched, so an
    ``async def`` handler's coroutine reaches tornado to be awaited.
    """

    @functools.wraps(f)
    def _check_auth(handler, *args, **kwargs):
        if not handler.is_authorized():
            return None
        return f(handler, *args, **kwargs)

    return _check_auth


DEFAULT_READONLY_MESSAGE = "The server is running in readonly mode"


def reject_readonly(handler, message=DEFAULT_READONLY_MESSAGE):
    """Answer 403 for a write attempted against a readonly server.

    ``message`` names the capability that is disabled, since "uploads" and
    "experiment logging" are refused for the same reason but are not the same
    thing to the caller.
    """
    handler.set_status(403)
    handler.write({"success": False, "error": message})


def check_readonly(f):
    """
    Wrapper for handler methods that change server state, so a server
    started with ``-readonly`` refuses them instead of applying them.

    Sockets are already short-circuited wholesale in
    ``AnySocketHandlerOrWrapper.on_message``; this is the HTTP half of the
    same rule. Stack it under ``check_auth`` so an unauthenticated request
    still answers 401 rather than 403.

    Passes the wrapped method's return value through for the same reason
    ``check_auth`` does.
    """

    @functools.wraps(f)
    def _check_readonly(handler, *args, **kwargs):
        if handler.readonly:
            reject_readonly(handler)
            return None
        return f(handler, *args, **kwargs)

    return _check_readonly


def check_readonly_message(message):
    """``check_readonly`` for a handler that names the capability it refuses.

    The guarded method is never entered: the response is 403 with a JSON body
    explaining which capability is disabled.

    Written as a decorator, and applied under ``check_auth``, so that a handler
    declares "this writes" once at its entry point rather than restating the
    check in the body -- the omission that let readonly writes through before.

    Passes the wrapped method's return value through for the same reason
    ``check_auth`` does.
    """

    def _decorate(f):
        @functools.wraps(f)
        def _check_readonly(handler, *args, **kwargs):
            if getattr(handler, "readonly", False):
                reject_readonly(handler, message)
                return None
            return f(handler, *args, **kwargs)

        return _check_readonly

    return _decorate


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


def hash_password_off_loop(password, salt):
    """Derive the key on a worker thread, returning a future.

    The derivation is deliberately expensive -- 100k iterations, tens of
    milliseconds of solid CPU -- which is the whole server stalled for the
    length of every login attempt. It goes to the default executor rather than
    the storage worker: a login has no reason to queue behind environment
    writes, and several may be in flight at once.
    """
    return tornado.ioloop.IOLoop.current().run_in_executor(
        None, hash_password, password, salt
    )


# ------- File management helpers ----- #


class LazyEnvData(Mapping):
    def __init__(self, store, eid):
        self._store = store
        self._eid = eid
        self._raw_dict = None

    @property
    def is_loaded(self):
        """Whether this environment has been materialized in memory."""
        return self._raw_dict is not None

    def lazy_load_data(self):
        if self._raw_dict is not None:
            return
        self.prime(self._store.load_env(self._eid))

    def prime(self, env_data):
        """Install an env that has already been read, skipping the disk hit.

        Priming an env that is already loaded leaves it alone.
        """
        if self._raw_dict is not None:
            return

        try:
            raw = dict(env_data)
            raw["jsons"] = env_data["jsons"]
            raw["reload"] = env_data["reload"]
        except (KeyError, TypeError) as e:
            raise ValueError(
                "Failed loading environment json: {} - {}".format(self._eid, repr(e))
            )
        self._raw_dict = raw

    def __getitem__(self, key):
        self.lazy_load_data()
        return self._raw_dict.__getitem__(key)

    def __setitem__(self, key, value):
        self.lazy_load_data()
        return self._raw_dict.__setitem__(key, value)

    def __delitem__(self, key):
        self.lazy_load_data()
        return self._raw_dict.__delitem__(key)

    def __iter__(self):
        self.lazy_load_data()
        return iter(self._raw_dict)

    def __len__(self):
        self.lazy_load_data()
        return len(self._raw_dict)


# ------- Off-loop storage helpers ----- #


def snapshot_env(env):
    """Deep-copy one env so a worker thread can serialize it safely.

    Returns ``None`` for a lazy env that was never read: its on-disk copy is
    already current, so there is nothing to write.
    """
    if isinstance(env, LazyEnvData) and not env.is_loaded:
        return None
    return copy.deepcopy(dict(env))


def snapshot_envs(state, eids):
    """Deep-copy the named envs, dropping the unknown and the still-cold ones."""
    snapshot = {}
    for eid in eids:
        env = state.get(eid)
        copied = None if env is None else snapshot_env(env)
        if copied is not None:
            snapshot[eid] = copied
    return snapshot


def snapshot_state(state):
    """Deep-copy every materialised env, dropping the ones still cold."""
    return snapshot_envs(state, list(state))


def run_on_storage_executor(handler, func, *args):
    """Submit disk work to the app's storage executor, returning a future."""
    return tornado.ioloop.IOLoop.current().run_in_executor(
        getattr(handler, "storage_executor", None), func, *args
    )


def save_env_off_loop(handler, eid):
    """Persist one env off the loop, or ``None`` when there is nothing to write."""
    snapshot = snapshot_env(handler.state[eid])
    if snapshot is None:
        return None
    return run_on_storage_executor(handler, handler.storage.save_env, eid, snapshot)


def save_envs_off_loop(handler, eids):
    """Persist the named envs off the loop; resolves to the ids written.

    The ids travel to the backend untouched, so it keeps the last word on what
    it accepted: an env that is unknown, or was never read off disk, has no
    snapshot to write and comes back unreported -- exactly as it did when the
    save ran inline.
    """
    eids = list(eids)
    return run_on_storage_executor(
        handler, handler.storage.save_envs, snapshot_envs(handler.state, eids), eids
    )


def save_all_off_loop(handler):
    """Persist every materialised env off the loop."""
    return run_on_storage_executor(
        handler, handler.storage.save_all, snapshot_state(handler.state)
    )


def load_env_off_loop(handler, eid):
    """Read one env from disk off the loop."""
    return run_on_storage_executor(handler, handler.storage.load_env, eid)


def purge_env(store, eid):
    """Remove everything an env owns on disk: its undo stack, then the env.

    Both files go in the one visit to the worker, so nothing the loop schedules
    in between can land between them.
    """
    clear_deleted(store, eid)
    store.delete_env(eid)


def _note_env_deleting(handler, eid):
    """Record that a delete of ``eid`` is on its way to disk."""
    handler.deleting_envs[eid] = handler.deleting_envs.get(eid, 0) + 1


def _note_env_deleted(handler, eid):
    """Drop that record once the delete has landed.

    A second delete of the same env keeps its own record: the env stays spoken
    for until the last of them is done with it.
    """
    remaining = handler.deleting_envs.get(eid, 0) - 1
    if remaining > 0:
        handler.deleting_envs[eid] = remaining
    else:
        handler.deleting_envs.pop(eid, None)


def env_is_deleting(handler, eid):
    """True while a delete of ``eid`` is queued or running.

    A read that started before the delete resolves after it, and filing what it
    read back under ``state`` would put the env the user just deleted back in
    the environment list. Readers that resume after yielding the loop ask this
    before storing anything.
    """
    return eid in handler.deleting_envs


def delete_env_off_loop(handler, eid):
    """Remove one env from disk off the loop, behind any write already queued.

    Deleting here on the loop is what let a deleted environment come back: an
    autosave hands the worker a snapshot taken while the env still existed, the
    delete then removes the file, and the write lands afterwards and recreates
    it. The worker runs one task at a time, so submitting the delete rather
    than running it orders it after every write queued before it, and a write
    queued after it cannot see the env at all -- the loop dropped it from
    ``state`` before this was called.

    The undo stack goes with it, on the worker rather than on the loop, for the
    same reason: a close or an undo already on its way to disk would otherwise
    save the stack back after a clear that ran here, leaving a deleted env's
    undo history behind for whoever next takes its name.
    """
    _note_env_deleting(handler, eid)
    future = run_on_storage_executor(handler, purge_env, handler.storage, eid)

    def _settle(done):
        _note_env_deleted(handler, eid)
        _log_storage_failure(done)

    future.add_done_callback(_settle)
    return future


async def ensure_env_loaded(handler, eid):
    """Materialise a cold lazy env without blocking the loop on the read.

    A delete that lands while the read is on the worker takes the env out of
    ``state`` and its file off disk, so the read answers with nothing at all.
    Priming that would report a deleted env as a malformed one -- a 500 out of
    ``prime`` rather than whatever the caller means a missing env to be -- so
    the env is only primed if it is still the one this started reading. Every
    caller already decides for itself what an absent env means, and each of
    them is reached by returning here: the fork handlers answer 400, the
    experiment mirror treats it as a new env, and the window handlers recreate
    it.
    """
    env = handler.state.get(eid)
    if not isinstance(env, LazyEnvData) or env.is_loaded:
        return
    raw = await load_env_off_loop(handler, eid)
    if handler.state.get(eid) is not env:
        return
    env.prime(raw)


async def ensure_env_present(handler, eid):
    """Materialise an env the loop is about to read, cold or unknown alike.

    ``ensure_env_loaded`` serves the callers that only ever name an env the
    application already tracks. Comparison also names envs the store alone
    knows, and read those inline; this reads one off the loop and files it
    under ``state`` exactly as that inline read did. An env with nothing on
    disk stays absent, so the caller still decides what a missing env means.
    """
    if eid in handler.state:
        await ensure_env_loaded(handler, eid)
        return
    raw = await load_env_off_loop(handler, eid)
    if raw and not env_is_deleting(handler, eid):
        handler.state[eid] = raw


def _read_env_for_serving(store, eid, want_env):
    """Read what serving an env costs: the env itself and its undo depth."""
    return (store.load_env(eid) if want_env else None), len(store.load_undo(eid))


async def warm_env(handler, eid):
    """Bring an env into memory off the loop; return its undo depth.

    ``ensure_env_loaded`` serves the handlers that only ever address an env the
    application already knows about. Handing one to a browser is the wider
    case: it may be a cold ``LazyEnvData``, or absent from ``state`` altogether
    and known only by its file. Both reads that serving it needs -- the env and
    the undo stack behind the pane counter -- go to the worker as one task.

    A malformed env still raises ``ValueError`` here, as reading it through
    ``LazyEnvData`` did, so callers keep reporting it the way they always have.
    """
    env = handler.state.get(eid)
    cold = env is None or (isinstance(env, LazyEnvData) and not env.is_loaded)
    raw, undo_count = await run_on_storage_executor(
        handler, _read_env_for_serving, handler.storage, eid, cold
    )
    if not cold:
        return undo_count
    if env is None:
        if raw and not env_is_deleting(handler, eid):
            handler.state[eid] = raw
    else:
        env.prime(raw)
    return undo_count


def push_deleted_off_loop(handler, eid, win_id, p_data):
    """Record a closed pane off the loop; resolves to the new undo depth."""
    return run_on_storage_executor(
        handler, push_deleted, handler.storage, eid, win_id, p_data
    )


def pop_deleted_off_loop(handler, eid):
    """Undo the newest close off the loop; resolves to ``(popped, depth)``."""
    return run_on_storage_executor(
        handler, pop_deleted_with_depth, handler.storage, eid
    )


def count_deleted_off_loop(handler, eid):
    """Read an env's undo depth off the loop."""
    return run_on_storage_executor(handler, count_deleted, handler.storage, eid)


def save_layouts_off_loop(handler):
    """Persist the app's layouts off the loop, snapshotting them first.

    The blob is read here, on the loop, and travels to the worker as an
    argument: a later edit then cannot overtake this write and leave the two
    saves landing in the order the disk happened to finish them.
    """
    state = handler.server_state
    return run_on_storage_executor(handler, state.save_layouts, state.get_layouts())


def _log_storage_failure(future):
    try:
        future.result()
    except Exception:
        logging.exception("Background storage write failed")


def fire_and_forget_save_all(handler):
    """Schedule a full save whose failure is logged rather than swallowed."""
    future = save_all_off_loop(handler)
    future.add_done_callback(_log_storage_failure)
    return future


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


def compare_envs(state, eids, socket, store, show_all=False, warmed=False):
    """Send a comparison of the named envs to one subscriber.

    ``warmed`` says the caller already read every env named here off the loop,
    so one still missing from ``state`` has nothing on disk -- or is on its way
    off it -- and reading it again here would only put the read, and an env the
    user just deleted, back on the loop.
    """
    logging.info("comparing envs")
    use_env_names = all(len(str(eid)) <= MAX_ENV_NAME_LEN for eid in eids)
    eidNums = {e: e if use_env_names else str(i) for i, e in enumerate(eids)}
    envs = {}
    for eid in eids:
        if eid in state:
            envs[eid] = state.get(eid)
        elif not warmed:
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
            if "content" not in destWidJson:
                continue  # nothing in the base env to merge into
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
                base_data = destWidJson["content"].get("data") or []
                if not base_data or "name" not in base_data[0]:
                    continue  # Skip windows with unnamed data
                if ix == 0:
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


def load_env(state, eid, socket, store, undo_count=None, warmed=False):
    """load an environment to a client by socket

    A caller that already warmed the env off the loop passes its ``undo_count``
    in rather than have the undo stack read here, where the read would land on
    the loop, and says so with ``warmed``: the env is either in ``state`` by
    now or has nothing on disk to read, so the fallback below would only repeat
    that read on the loop -- and would file the result away past the guard that
    keeps an env being deleted from coming back.
    """
    env = {}
    if eid in state:
        env = state.get(eid)
    elif not warmed:
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
                "count": (
                    count_deleted(store, eid) if undo_count is None else undo_count
                ),
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
    (a DataStore), which no-ops when running without an env_path.

    Returns the depth the stack was left at, so a caller that has to announce
    it does not pay for a second read of the file just written.
    """
    stack = store.load_undo(eid)
    stack.append([win_id, p_data])
    if len(stack) > DEFAULT_MAX_UNDO_HISTORY:
        stack = stack[-DEFAULT_MAX_UNDO_HISTORY:]
    store.save_undo(eid, stack)
    return len(stack)


def pop_deleted_with_depth(store, eid):
    """Pop the newest closed pane and report what is left behind it.

    Returns ``(popped, depth)`` where ``popped`` is ``(win_id, p_data)`` or
    ``None``. Undoing is always followed by telling subscribers how many panes
    remain, and both numbers come off the one stack this already read.
    """
    stack = store.load_undo(eid)
    if not stack:
        return None, 0
    win_id, p_data = stack.pop()
    if stack:
        store.save_undo(eid, stack)
    else:
        store.clear_undo(eid)
    return (win_id, p_data), len(stack)


def pop_deleted(store, eid):
    """Pop and return the most recently closed pane as (win_id, p_data),
    or None if the environment has no undo history."""
    popped, _depth = pop_deleted_with_depth(store, eid)
    return popped


def clear_deleted(store, eid):
    """Remove an environment's undo history via the ``store`` backend."""
    store.clear_undo(eid)


def count_deleted(store, eid):
    """Return the number of closed panes available to undo for an env."""
    return len(store.load_undo(eid))


def broadcast_undo_state(handler, eid, store, count=None):
    """Tell subscribers of an env how many closed panes remain to undo.

    A caller that already knows the depth -- because the push or pop it just
    made off the loop reported it -- passes ``count`` in rather than have the
    stack read here, where the read would land on the loop.
    """
    msg = json.dumps(
        {
            "command": "undo_state",
            "eid": eid,
            "count": count_deleted(store, eid) if count is None else count,
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
