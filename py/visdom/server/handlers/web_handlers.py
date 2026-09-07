#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Handlers for the different types of web request events. Mostly handles parsing
and processing the web events themselves and interfacing with the server as
necessary, but defers underlying manipulations of the server's data to
the data_model itself.
"""

import copy
import getpass
import hmac
import json
import jsonpatch
import logging
import os
import uuid
from collections import OrderedDict

from collections.abc import Mapping, Sequence

import tornado.escape
from visdom.utils.shared_utils import (
    get_rand_id,
    _coerce_image_slider_index,
    _is_missing_value,
    NanSafeEncoder,
)
from visdom.utils.server_utils import (
    check_auth,
    check_readonly,
    delete_env_off_loop,
    ensure_env_loaded,
    ensure_env_present,
    check_readonly_message,
    reject_readonly,
    extract_eid,
    run_on_storage_executor,
    save_env_off_loop,
    save_envs_off_loop,
    snapshot_env,
    warm_env,
    window,
    register_window,
    gather_envs,
    broadcast_envs,
    broadcast_tags,
    escape_eid,
    compare_envs,
    load_env,
    broadcast,
    update_window,
    hash_password_off_loop,
    stringify,
    push_deleted,
    notify,
    LazyEnvData,
)
from visdom.server.handlers.base_handlers import BaseHandler
from visdom.experiments import (
    DEFAULT_SORT_FIELD,
    Experiment,
    ExperimentStore,
    ExperimentFinishedError,
    QueryParseError,
    retarget_experiment,
    STATUS_FINISHED,
    tags_to_mapping,
)

logger = logging.getLogger(__name__)


# TODO move the logic that actually parses environments and layouts to
# new classes in the data_model folder.
class PostHandler(BaseHandler):
    @check_auth
    @check_readonly
    async def post(self):
        req = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )

        if req.get("func") is not None:
            raise Exception(
                "Support for Lua Torch was deprecated following `v0.1.8.4`. "
                "If you'd like to use torch support, you'll need to download "
                "that release. You can follow the usage instructions there, "
                "but it is no longer officially supported."
            )

        eid = extract_eid(req)
        await ensure_env_loaded(self, eid)

        p = window(req)
        register_window(self, p, eid)


class ExistsHandler(BaseHandler):
    @staticmethod
    def wrap_func(handler, args):
        if "win" not in args:
            raise tornado.web.HTTPError(400, reason="missing required field: win")
        eid = extract_eid(args)
        if eid in handler.state and args["win"] in handler.state[eid]["jsons"]:
            handler.write("true")
        else:
            handler.write("false")

    @check_auth
    async def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        await ensure_env_loaded(self, extract_eid(args))
        self.wrap_func(self, args)


class UpdateHandler(BaseHandler):
    @staticmethod
    def update_packet(
        p, args, max_text_lines, max_old_content, max_image_history, max_plot_history
    ):
        # Shallow copy the packet to dynamically capture changes to top-level keys.
        old_p = p.copy()

        # Deepcopy only the nested structures known to be mutated in-place.
        if "content" in p:
            old_p["content"] = copy.deepcopy(p["content"])
        if "old_content" in p:
            old_p["old_content"] = copy.deepcopy(p["old_content"])

        p = UpdateHandler.update(
            p,
            args,
            max_text_lines,
            max_old_content,
            max_image_history,
            max_plot_history,
        )
        p["contentID"] = get_rand_id()

        patch = jsonpatch.make_patch(old_p, p)
        return p, patch.patch

    @staticmethod
    def update_embeddings_packet(p, args, max_old_content):
        update_type = args["data"]["update_type"]
        content_id = get_rand_id()
        if update_type == "EntitySelected":
            selected = args["data"]["selected"]
            p["content"]["selected"] = selected
            p["contentID"] = content_id
            # `selected` may not exist yet on the first selection, so use "add"
            # (which also overwrites when the key is already present).
            return [
                {"op": "add", "path": "/content/selected", "value": selected},
                {"op": "replace", "path": "/contentID", "value": content_id},
            ]
        if update_type == "RegionSelected":
            old_data = p["content"]["data"]
            new_data = args["data"]["points"]
            p["old_content"].append(old_data)
            # Cap retained history to prevent unbounded in-memory growth (#1320).
            if len(p["old_content"]) > max_old_content:
                p["old_content"] = p["old_content"][-max_old_content:]
            p["content"]["data"] = new_data
            p["content"]["has_previous"] = True
            p["content"]["selected"] = None
            p["contentID"] = content_id
            return [
                {"op": "replace", "path": "/content/data", "value": new_data},
                {"op": "add", "path": "/content/has_previous", "value": True},
                {"op": "add", "path": "/content/selected", "value": None},
                {"op": "replace", "path": "/contentID", "value": content_id},
            ]
        return []

    @staticmethod
    def update(
        p, args, max_text_lines, max_old_content, max_image_history, max_plot_history
    ):
        # Update text in window, separated by a line break
        if p["type"] == "text":
            p["content"] += "<br>" + args["data"][0]["content"]
            lines = p["content"].split("<br>")
            if len(lines) > max_text_lines:
                p["content"] = "<br>".join(lines[-max_text_lines:])
            return p
        if p["type"] == "image_history":
            utype = args["data"][0]["type"]
            if utype == "image_history":
                p["content"].append(args["data"][0]["content"])
                if len(p["content"]) > max_image_history:
                    p["content"] = p["content"][-max_image_history:]
                p["selected"] = len(p["content"]) - 1
            elif utype == "image_update_selected":
                if not p["content"]:
                    return p
                selected = _coerce_image_slider_index(args["data"][0]["selected"])
                selected = min(max(0, selected), len(p["content"]) - 1)
                p["selected"] = selected
            return p
        if p["type"] == "plot_history":
            utype = args["data"][0]["type"]
            if utype == "plot_history":
                p["content"].append(args["data"][0]["content"])
                # A plot frame is a whole figure, so an unbounded history grows
                # the env until the process runs out of memory. Keep the newest
                # ``max_plot_history`` frames, as image history already does.
                if len(p["content"]) > max_plot_history:
                    p["content"] = p["content"][-max_plot_history:]
                p["selected"] = len(p["content"]) - 1
            elif utype == "plot_update_selected":
                selected = args["data"][0]["selected"]
                selected_not_neg = max(0, selected)
                selected_exists = min(len(p["content"]) - 1, selected_not_neg)
                p["selected"] = selected_exists
            return p
        if p["type"] == "table":
            logging.warning(
                "update(): ignoring /update call on win %r, which is a "
                "'table' pane; use vis.table() to replace its content "
                "instead",
                p.get("id"),
            )
            return p

        pdata = p["content"]["data"]

        new_data = args.get("data")
        p = update_window(p, args)
        name = args.get("name")
        delete = args.get("delete")
        # An unnamed delete carries no name and no data, which this shortcut used
        # to read as "opts-only update" and return early, silently dropping the
        # deletion. Ask about the delete flag first. ``not new_data`` also covers
        # an empty list, which a layout-only update sends in place of None.
        if not delete and name is None and not new_data:
            return p  # we only updated the opts or layout
        append = args.get("append")

        idxs = list(range(len(pdata)))

        if name is not None:
            if not delete and len(new_data) != 1:
                raise tornado.web.HTTPError(
                    400, reason="a named trace update takes exactly one data entry"
                )
            idxs = [i for i in idxs if pdata[i]["name"] == name]

        # Delete a trace
        if delete:
            idxs_set = set(idxs)
            p["content"]["data"] = [e for i, e in enumerate(pdata) if i not in idxs_set]
            return p

        # add new heatmap data if plot has been deleted previously
        if len(idxs) == 0 and new_data[0]["type"] == "heatmap":
            pdata.append(new_data[0])
            return p

        # update heatmap
        if len(idxs) == 1 and pdata[idxs[0]]["type"] == "heatmap":
            plot = pdata[idxs[0]]
            new_data = new_data[0]
            dz = new_data["z"]
            updateDir = args["updateDir"]

            # first check if operation is valid
            if updateDir != "replace":
                del new_data["z"]

                if updateDir in ["appendRow", "prependRow"]:
                    checkdir = "y"
                    if len(plot["z"][0]) != len(dz[0]):
                        logging.error(
                            "ERROR: There is a mismatch between the number of columns in existing plot ('%i') and new data ('%i')."
                            % (len(plot["z"][0]), len(dz[0]))
                        )
                        return p
                else:
                    checkdir = "x"
                    if len(plot["z"]) != len(dz):
                        logging.error(
                            "ERROR: There is a mismatch between the number of rows in existing plot ('%i') and new data ('%i')."
                            % (len(plot["z"]), len(dz))
                        )
                        return p
                updateNames = False
                if plot[checkdir] is not None and new_data[checkdir] is not None:
                    updateNames = True
                    if plot[checkdir] is not None and any(
                        label in plot[checkdir] for label in new_data[checkdir]
                    ):
                        logging.error(
                            "ERROR: The new column names appear already in the plot. Please make sure to specify unique column names."
                        )
                        return p
                elif plot[checkdir] is not None:
                    logging.error(
                        "ERROR: The column names have been specified in plot, however the requested update does not specify column names."
                    )
                    return p
                elif new_data[checkdir] is not None:
                    logging.error(
                        "ERROR: The column names have been specified for update, however the plot to update does not specify column names."
                    )
                    return p

            # append according to direction
            if updateDir == "appendRow":
                plot["z"] += dz
                if updateNames:
                    plot["y"] += new_data["y"]

            elif updateDir == "prependRow":
                plot["z"] = dz + plot["z"]
                if updateNames:
                    plot["y"] = new_data["y"] + plot["y"]

            elif updateDir == "appendColumn":
                for i, dzi in enumerate(dz):
                    plot["z"][i] += dzi
                if updateNames:
                    plot["x"] += new_data["x"]

            elif updateDir == "prependColumn":
                for i, dzi in enumerate(dz):
                    plot["z"][i] = dzi + plot["z"][i]
                if updateNames:
                    plot["x"] = new_data["x"] + plot["x"]

            # update opts
            # note: if we are appending, we do not want to modify the labels, as they have already been altered above
            if append:
                if "x" in new_data:
                    del new_data["x"]
                if "y" in new_data:
                    del new_data["y"]
            for k in new_data:
                if new_data[k] is not None or not append:
                    plot[k] = new_data[k]

            return p

        # Inject a new trace. This used to clone ``pdata[0]`` before overwriting
        # every key of the clone, which raised IndexError once a plot had all of
        # its traces deleted. The clone was dead work anyway, so build the trace
        # from the update alone.
        if len(idxs) == 0:
            trace = dict(new_data[0])
            trace["name"] = name
            pdata.append(trace)
            return p

        # Update traces. An unnamed update may carry fewer entries than the plot
        # has traces, so walk only as far as the data reaches instead of
        # indexing past the end of it.
        for idx, new_trace in zip(idxs, new_data):
            if all(_is_missing_value(i) for i in new_trace["x"]):
                continue
            # handle data for plotting
            axes = ["x", "y"]
            if pdata[idx]["type"] == "scatter3d":
                axes.append("z")
            for axis in axes:
                pdata[idx][axis] = (
                    (pdata[idx][axis] + new_trace[axis]) if append else new_trace[axis]
                )

            # handle marker properties
            if "marker" not in new_trace:
                continue
            if "marker" not in pdata[idx]:
                pdata[idx]["marker"] = {}
            pdata_marker = pdata[idx]["marker"]
            for marker_prop in ["color"]:
                if marker_prop not in new_trace["marker"]:
                    continue
                if marker_prop not in pdata[idx]["marker"]:
                    pdata[idx]["marker"][marker_prop] = []
                pdata_marker[marker_prop] = (
                    (pdata_marker[marker_prop] + new_trace["marker"][marker_prop])
                    if append
                    else new_trace["marker"][marker_prop]
                )

        return p

    @staticmethod
    def broadcast_window_update(handler, args, eid, p, diff_packet):
        broadcast_packet = {
            "command": "window_update",
            "win": args["win"],
            "eid": eid,
            "content": diff_packet,
            "version": p.get("version", 1),
        }
        broadcast(handler, json.dumps(broadcast_packet, cls=NanSafeEncoder), eid)

    @staticmethod
    def wrap_func(handler, args):
        if "win" not in args:
            raise tornado.web.HTTPError(400, reason="missing required field: win")
        if "data" not in args and args.get("append"):
            raise tornado.web.HTTPError(400, reason="missing required field: data")
        if "data" not in args and "layout" not in args and "opts" not in args:
            raise tornado.web.HTTPError(
                400, reason="request must include one of: data, layout, or opts"
            )
        eid = extract_eid(args)

        if eid not in handler.state:
            handler.state[eid] = {"jsons": {}, "reload": {}}

        if args["win"] not in handler.state[eid]["jsons"]:
            # Append to a window that doesn't exist attempts to create
            # that window
            append = args.get("append")
            if append:
                p = window(args)
                register_window(handler, p, eid)
            else:
                handler.write("win does not exist")
            return

        p = handler.state[eid]["jsons"][args["win"]]
        data = args.get("data")
        is_image_slider_update = isinstance(data, list) and any(
            isinstance(entry, dict) and entry.get("type") == "image_update_selected"
            for entry in data
        )

        if is_image_slider_update and p["type"] != "image_history":
            handler.set_status(400)
            handler.write("win is not image_history; was {}".format(p["type"]))
            return

        if not (
            p["type"] == "text"
            or p["type"] == "image_history"
            or p["type"] == "plot_history"
            or p["type"] == "embeddings"
            or p["type"] == "table"
            or (
                len(p["content"]["data"]) == 0
                or p["content"]["data"][0]["type"]
                in ["scatter", "scatter3d", "scattergl", "custom", "heatmap"]
            )
        ):
            handler.write(
                "win is not scatter, heatmap, custom, image_history, plot_history, embeddings, or text; "
                "was {}".format(
                    p["content"]["data"][0]["type"]
                    if len(p["content"]["data"]) > 0
                    else "empty"
                )
            )
            return

        if p["type"] == "embeddings":
            diff_packet = UpdateHandler.update_embeddings_packet(
                p, args, handler.max_old_content
            )
            UpdateHandler.broadcast_window_update(handler, args, eid, p, diff_packet)
            handler.mark_dirty(eid)
            handler.write(p["id"])
            return

        try:
            p, diff_packet = UpdateHandler.update_packet(
                p,
                args,
                handler.max_text_lines,
                handler.max_old_content,
                handler.max_image_history,
                handler.max_plot_history,
            )
        except (TypeError, ValueError) as exc:
            if is_image_slider_update:
                handler.set_status(400)
                handler.write(str(exc))
                return
            raise
        # send the smaller of the patch and the updated pane
        if len(stringify(p)) <= len(stringify(diff_packet)):
            broadcast_msg = dict(p)
            broadcast_msg["eid"] = eid
            broadcast(handler, json.dumps(broadcast_msg, cls=NanSafeEncoder), eid)
        else:
            UpdateHandler.broadcast_window_update(handler, args, eid, p, diff_packet)
        handler.mark_dirty(eid)
        handler.write(p["id"])

    @check_auth
    @check_readonly
    async def post(self):
        if self.login_enabled and not self.current_user:
            self.set_status(400)
            return
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        await ensure_env_loaded(self, extract_eid(args))
        self.wrap_func(self, args)


class CloseHandler(BaseHandler):
    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)
        win = args.get("win")

        keys = list(handler.state[eid]["jsons"].keys()) if win is None else [win]
        for win in keys:
            p_data = handler.state[eid]["jsons"].pop(win, None)
            if p_data is not None:
                push_deleted(handler.storage, eid, win, p_data)
                handler.mark_dirty(eid)
            broadcast(handler, json.dumps({"command": "close", "data": win}), eid)

    @check_auth
    @check_readonly
    async def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        await ensure_env_loaded(self, extract_eid(args))
        self.wrap_func(self, args)


class DeleteEnvHandler(BaseHandler):
    @staticmethod
    def wrap_func(handler, args):
        """Drop an env, answering with the future for its removal from disk.

        The env leaves memory and the subscribers hear about it here; the files
        it owns -- its undo stack as well as the env itself -- are handed to
        the storage worker, so callers that need the disk to be settled -- the
        request handler below, and tests -- await what comes back. ``None``
        means there was nothing to delete.
        """
        eid = args.get("eid")
        if eid is None:
            return None
        eid = escape_eid(eid)
        if eid == "main":
            return None
        handler.state.pop(eid, None)
        removal = delete_env_off_loop(handler, eid)
        broadcast_envs(handler)
        return removal

    @check_auth
    @check_readonly
    async def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        removal = self.wrap_func(self, args)
        if removal is not None:
            await removal


class EnvStateHandler(BaseHandler):
    @staticmethod
    def wrap_func(handler, args):
        eid = args.get("eid")
        if eid is not None:
            eid = escape_eid(str(eid))
            if eid not in handler.state:
                handler.set_status(404)
                handler.write(json.dumps({"error": "env '{}' not found".format(eid)}))
                return
            handler.write(json.dumps(handler.state[eid]["jsons"], cls=NanSafeEncoder))
        else:
            all_eids = list(handler.state.keys())
            handler.write(json.dumps(all_eids))

    @check_auth
    async def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        eid = args.get("eid")
        if eid is not None:
            await ensure_env_loaded(self, escape_eid(str(eid)))
        self.wrap_func(self, args)


class ForkEnvHandler(BaseHandler):
    @staticmethod
    async def wrap_func(handler, args):
        prev_eid = escape_eid(args.get("prev_eid"))
        eid = escape_eid(args.get("eid"))

        if prev_eid not in handler.state:
            # the eid stays out of the reason: it is echoed on the status line,
            # which is latin-1 only, and eids are free-form unicode.
            raise tornado.web.HTTPError(400, reason="env to be forked doesn't exist")

        # the source is read before it is copied: deep-copying a cold
        # LazyEnvData copied its source's id rather than its data, so the fork
        # had nothing of its own to write out and went on reading whatever the
        # env it was forked from held. The copy also carries the source env's
        # experiment metadata, whose env_id still names the env it was forked
        # from; retarget it so the fork does not answer to its parent's id.
        source = handler.state[prev_eid]
        await ensure_env_loaded(handler, prev_eid)
        if handler.state.get(prev_eid) is not source:
            # the source was deleted while it was being read off the worker,
            # so answer as though it had never been there -- indexing it here
            # would raise, and forking whatever replaced it is not what was
            # asked for.
            raise tornado.web.HTTPError(400, reason="env to be forked doesn't exist")
        handler.state[eid] = retarget_experiment(snapshot_env(source), eid)
        await save_env_off_loop(handler, eid)
        broadcast_envs(handler)

        handler.write(eid)

    @check_auth
    @check_readonly
    async def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        await self.wrap_func(self, args)


class EnvHandler(BaseHandler):
    @check_auth
    def get(self, eid):
        if eid not in self.state:
            raise tornado.web.HTTPError(404, reason=f"Environment '{eid}' not found")
        self.render(
            "index.html",
            wrap_socket=self.wrap_socket,
        )

    @check_auth
    async def post(self, args):
        msg_args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        if "sid" in msg_args:
            sid = msg_args["sid"]
            if sid in self.subs:
                eid = escape_eid(args)
                try:
                    undo_count = await warm_env(self, eid)
                    load_env(
                        self.state,
                        eid,
                        self.subs[sid],
                        self.storage,
                        undo_count,
                        warmed=True,
                    )
                except ValueError:
                    notify(
                        self,
                        "Could not load environment: invalid environment JSON format",
                        type="error",
                        target_subs=[self.subs[sid]],
                    )
                    return
        if "eid" in msg_args:
            eid = escape_eid(msg_args["eid"])
            if eid not in self.state:
                self.state[eid] = {"jsons": {}, "reload": {}}
                broadcast_envs(self)


class CompareHandler(BaseHandler):
    @check_auth
    def get(self, eids):
        for eid in eids.split("+"):
            if eid not in self.state:
                raise tornado.web.HTTPError(
                    404, reason=f"Environment '{eid}' not found"
                )
        self.render(
            "index.html",
            wrap_socket=self.wrap_socket,
        )

    @check_auth
    async def post(self, args):
        body = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        sid = body["sid"]
        show_all = body.get("show_all", False)
        if sid in self.subs:
            eids = args.split("+")
            try:
                # comparison reads every named env in full, and reads it from
                # state -- so each one is brought into memory here, where the
                # read costs a worker thread rather than the loop.
                for eid in eids:
                    await ensure_env_present(self, eid)
                compare_envs(
                    self.state,
                    eids,
                    self.subs[sid],
                    self.storage,
                    show_all=show_all,
                    warmed=True,
                )
            except ValueError:
                notify(
                    self,
                    "Could not compare environments: invalid environment JSON format",
                    type="error",
                    target_subs=[self.subs[sid]],
                )
                return


class SaveHandler(BaseHandler):
    @staticmethod
    async def wrap_func(handler, args):
        envs = args["data"]
        envs = [escape_eid(eid) for eid in envs]
        # this drops invalid env ids
        ret = await save_envs_off_loop(handler, envs)
        handler.write(json.dumps(ret))

    @check_auth
    @check_readonly
    async def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        await self.wrap_func(self, args)


class DataHandler(BaseHandler):
    @staticmethod
    def wrap_func(handler, args):
        eid = extract_eid(args)

        if "data" in args:
            # Load data from client. This is the one write behind an endpoint
            # that also reads, so it cannot be refused by the decorator.
            if handler.readonly:
                reject_readonly(handler)
                return

            data = json.loads(args["data"])

            if eid not in handler.state:
                handler.state[eid] = {"jsons": {}, "reload": {}}

            if "win" in args and args["win"] is None:
                handler.state[eid]["jsons"] = data
            else:
                handler.state[eid]["jsons"][args["win"]] = data

            handler.mark_dirty(eid)
            broadcast_envs(handler)
        else:
            # Dump data to client
            if "win" in args and args["win"] is None:
                handler.write(
                    json.dumps(handler.state[eid]["jsons"], cls=NanSafeEncoder)
                )
            else:
                if args["win"] not in handler.state[eid]["jsons"]:
                    raise tornado.web.HTTPError(
                        400, reason="window doesn't exist in this env"
                    )
                handler.write(
                    json.dumps(
                        handler.state[eid]["jsons"][args["win"]], cls=NanSafeEncoder
                    )
                )

    @check_auth
    async def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        await ensure_env_loaded(self, extract_eid(args))
        self.wrap_func(self, args)


class IndexHandler(BaseHandler):
    def initialize(self, server_state):
        super().initialize(server_state)
        self.base_url = (
            self.server_state.base_url if self.server_state.base_url != "" else "/"
        )

    def get(self, args, **kwargs):
        if (not self.login_enabled) or self.current_user:
            """self.current_user is an authenticated user provided by Tornado,
            available when we set self.get_current_user in BaseHandler,
            and the default value of self.current_user is None
            """
            if args not in ("", "/"):
                raise tornado.web.HTTPError(
                    404, reason=f"Path '{self.request.path}' not found"
                )
            self.render(
                "index.html",
                wrap_socket=self.wrap_socket,
            )
        elif self.login_enabled:
            items = gather_envs(self.state, self.storage)
            self.render(
                "login.html",
                user=getpass.getuser(),
                items=items,
                active_item="",
                base_url=self.base_url,
            )

    async def post(self, arg, **kwargs):
        json_obj = tornado.escape.json_decode(self.request.body)
        username = json_obj["username"]
        stored = self.user_credential["password"]
        salt = stored.split("$")[0]
        password = await hash_password_off_loop(json_obj["password"], salt)

        # Constant-time comparison: `==` on the derived key returns as soon as
        # two characters differ, so response timing tells an attacker how much
        # of a guess was right. Both halves are always compared, which keeps a
        # wrong username costing the same as a wrong password.
        username_ok = hmac.compare_digest(
            str(username).encode("utf-8"),
            self.user_credential["username"].encode("utf-8"),
        )
        password_ok = hmac.compare_digest(
            password.encode("utf-8"), stored.encode("utf-8")
        )

        if username_ok and password_ok:
            self.set_secure_cookie("user_password", username + password)
        else:
            self.set_status(400)


class UserSettingsHandler(BaseHandler):
    def get(self, path):
        if path == "style.css":
            self.set_status(200)
            self.set_header("Content-type", "text/css")
            self.write(self.user_settings["user_css"])


class ErrorHandler(BaseHandler):
    def get(self, text):
        if not text or not text.strip().isdigit():
            raise tornado.web.HTTPError(400, reason="Invalid status code")

        status_code = int(text.strip())

        if not 400 <= status_code <= 599:
            raise tornado.web.HTTPError(400, reason="Invalid status code")

        raise tornado.web.HTTPError(status_code)


class UploadEnvHandler(BaseHandler):
    @check_auth
    @check_readonly_message("Uploads are disabled while the server is in readonly mode")
    async def post(self):
        # 100mb file size limit
        MAX_SIZE = 100 * 1024 * 1024

        if "file" not in self.request.files:
            self.set_status(400)
            self.write({"success": False, "error": "No file uploaded"})
            return

        file_info = self.request.files["file"][0]
        filename = file_info["filename"]
        body = file_info["body"]

        if len(body) > MAX_SIZE:
            self.set_status(413)
            self.write(
                {
                    "success": False,
                    "error": f"File is too large. Max {MAX_SIZE//(1024*1024)}MB",
                }
            )
            return

        try:
            data = tornado.escape.json_decode(body)
        except Exception:
            self.set_status(400)
            self.write({"success": False, "error": "Invalid JSON file"})
            return

        if not (isinstance(data, dict) and "jsons" in data and "reload" in data):
            self.set_status(400)
            self.write({"success": False, "error": "This is not a valid Visdom JSON"})
            return

        uid = uuid.uuid4().hex[:8]
        new_eid = f"uploaded_{uid}"
        if filename.endswith(".json"):
            suggested_name = escape_eid(os.path.basename(filename[:-5]))
            if suggested_name and suggested_name != "main":
                new_eid = f"uploaded_{suggested_name}_{uid}"

        self.state[new_eid] = {"jsons": data["jsons"], "reload": data["reload"]}

        await save_env_off_loop(self, new_eid)

        broadcast_envs(self)

        self.write(
            {
                "success": True,
                "eid": new_eid,
                "message": f"Dashboard loaded successfully as '{new_eid}'",
            }
        )


# ---- Experiment metadata, written on the loop and persisted off it ---- #


def _no_write(eid, env):
    """``ExperimentStore`` persist hook that writes nothing.

    Handed to a store whose caller does the writing itself, so the change lands
    on the env here and the file write happens where the caller puts it.
    """


async def _write_experiment_metadata(handler, eid, mutate):
    """Apply one metadata change to ``eid``'s env; return it and whether it is new.

    Both trips to disk stay off the loop -- the env is read through
    ``ensure_env_present`` and written through ``save_env_off_loop`` -- but the
    change itself is applied here, to the very object the server is serving.

    Applying it on the worker instead means reading the env from its file,
    editing that copy, and writing the whole file back, while the loop goes on
    editing the env it holds for the entire time the worker takes. Nothing
    reconciles the two: whichever writes the file last wins it outright, and
    everything the other one changed is gone. That is a window added while an
    experiment was being logged, or a tag set while a metric was, and no error
    is raised for either -- the losing request has already answered 200. The
    env is the unit that is written, so it is the unit that is lost.

    Applied here, every writer of an environment is back to being serialised by
    the loop, and the snapshots they produce reach the single-threaded storage
    worker in the order the loop made them. ``mutate`` runs before the env is
    filed under ``state`` and before anything is queued, so a change the store
    rejects leaves behind neither a new environment nor a write.
    """
    is_new_env = eid not in handler.state
    await ensure_env_present(handler, eid)
    env = handler.state.get(eid)
    if env is None:
        env = {"jsons": {}, "reload": {}}

    # the env is handed over directly rather than through ``state.get``: it has
    # just been materialised, and a store that went looking for it again would
    # read the file for an env that has none -- on the loop.
    experiment = mutate(
        ExperimentStore(
            handler.storage,
            env_provider=lambda _eid, _env=env: _env,
            persist=_no_write,
        )
    )
    if experiment is None:
        return None, is_new_env

    if eid not in handler.state:
        handler.state[eid] = env
    await save_env_off_loop(handler, eid)
    return experiment, is_new_env


# ---- Experiment reads, as they run on the storage worker ---- #
#
# Both of these read every environment file the store knows, which is the whole
# of what the endpoints below cost. They take the DataStore rather than a live
# ``ExperimentStore`` because the executor is handed plain positional
# arguments, and they touch no server state, so the worker is never looking at
# anything the loop may be editing underneath it. Reading metadata from the
# files alone is still current: every endpoint that changes an experiment
# persists it before it answers.


def _search_experiments(store, query, sort_by, descending, offset, limit):
    """Return one page of matches and the unpaged total, as ``(page, total)``.

    Paging on the worker rather than after it keeps the memory a search costs
    set by the page asked for, so the ranking never holds every experiment on
    the server just to hand back the first few.
    """
    return ExperimentStore(store).search_page(
        query=query,
        sort_by=sort_by,
        descending=descending,
        offset=offset,
        limit=limit,
    )


def _compare_experiments(store, env_ids):
    return ExperimentStore(store).compare(env_ids)


def _decode_json_body(body):
    """Return a request body decoded into a dict of arguments.

    Shared by the ``/experiments/*`` endpoints, whose bodies are all optional
    JSON objects, so an empty body is read as an empty object and each handler
    decides on its own whether the arguments it needs are missing. Anything else
    that is not a JSON object is the caller's error: without this check,
    malformed JSON or a bare list would surface as an unhandled exception and a
    500 rather than a 400 naming what was wrong with the request.
    """
    try:
        text = tornado.escape.to_basestring(body).strip()
        if not text:
            return {}
        args = tornado.escape.json_decode(text)
    except ValueError:
        raise tornado.web.HTTPError(400, reason="request body must be valid JSON")
    if not isinstance(args, Mapping):
        raise tornado.web.HTTPError(400, reason="request body must be an object")
    return args


class ExperimentLogHandler(BaseHandler):
    """POST ``/experiments/log`` — record experiment metadata for an environment.

    The JSON body carries an ``action`` selecting one of three operations:

    * ``"log"`` (default) — create or update the experiment (``name``/``params``/
      ``tags``/``description``); repeated calls merge rather than replace.
    * ``"metrics"`` — append one or more ``{name: value}`` metric observations at
      an optional ``step``, creating the experiment if it does not exist yet.
    * ``"finish"`` — mark the experiment terminal (``status`` finished/failed).

    Once an experiment is terminal, every action — including a second
    ``"finish"`` — is rejected with 409 Conflict, so neither a finished run's
    recorded data nor its final status can change after the fact.

    Metadata is persisted through the server's existing ``DataStore``
    (:class:`ExperimentStore` over ``handler.storage``) and mirrored into the
    in-memory env state so a later full-env save writes it back rather than
    dropping it. The stored experiment is written back to the client as JSON.

    Each action then marks the environment on the server's live-update queue
    (:func:`~visdom.server.handlers.experiments_handler.make_live_queue`), which
    refreshes the hyper-parameter panes showing this run shortly afterwards.
    ``finish`` marks too: the status a pane displays has just changed. Marking
    only records the environment, so a run logging every step pays for a set
    insert rather than a rebuild.

    All three actions write, so the endpoint is rejected with 403 while the
    server runs in readonly mode.
    """

    VALID_ACTIONS = ("log", "metrics", "finish")

    @staticmethod
    def _require_mapping(args, field):
        """Return ``args[field]`` if it is a mapping (or absent); else raise 400."""
        value = args.get(field)
        if value is not None and not isinstance(value, Mapping):
            raise tornado.web.HTTPError(
                400, reason="'{0}' must be an object".format(field)
            )
        return value

    @staticmethod
    async def wrap_func(handler, args):
        action = args.get("action", "log")
        if action not in ExperimentLogHandler.VALID_ACTIONS:
            raise tornado.web.HTTPError(
                400, reason="unknown action {0!r}".format(action)
            )

        eid = extract_eid(args)

        if action == "metrics":
            metrics = ExperimentLogHandler._require_mapping(args, "metrics")
            if not metrics:
                raise tornado.web.HTTPError(
                    400, reason="'metrics' must be a non-empty object"
                )
        elif action == "log":
            params = ExperimentLogHandler._require_mapping(args, "params")
            tags = ExperimentLogHandler._require_mapping(args, "tags")

        try:
            if action == "log":
                experiment, is_new_env = await _write_experiment_metadata(
                    handler,
                    eid,
                    lambda store: store.log_experiment(
                        eid,
                        name=args.get("name"),
                        params=params,
                        tags=tags,
                        description=args.get("description"),
                    ),
                )
            elif action == "metrics":
                rejected = []

                def apply_metrics(store):
                    """Apply the request's observations, holding back a rejection.

                    Each is applied in turn, as it was when every observation
                    was its own read-append-write, so a metric the store
                    refuses still leaves the ones before it recorded. The
                    refusal is held rather than raised so that what did apply
                    is persisted before the request reports it.
                    """
                    experiment = None
                    for key, value in metrics.items():
                        try:
                            experiment = store.log_metric(
                                eid, key, value, args.get("step")
                            )
                        except (
                            ExperimentFinishedError,
                            TypeError,
                            ValueError,
                        ) as error:
                            rejected.append(error)
                            break
                    return experiment

                experiment, is_new_env = await _write_experiment_metadata(
                    handler, eid, apply_metrics
                )
                if rejected:
                    raise rejected[0]
            else:
                experiment, is_new_env = await _write_experiment_metadata(
                    handler,
                    eid,
                    lambda store: store.finish_experiment(
                        eid, args.get("status", STATUS_FINISHED)
                    ),
                )
        except ExperimentFinishedError as e:
            raise tornado.web.HTTPError(409, reason=str(e))
        except KeyError:
            raise tornado.web.HTTPError(
                404, reason="no experiment logged for env {0!r}".format(eid)
            )
        except ValueError as e:
            raise tornado.web.HTTPError(400, reason=str(e))

        # the store wrote the blob into the env the server is holding, so there
        # is nothing left to mirror here; the env is marked so the autosave
        # covers it too, whatever else on it has changed since.
        handler.mark_dirty(eid)
        if is_new_env:
            broadcast_envs(handler)

        live_updates = getattr(handler, "live_updates", None)
        if live_updates is not None:
            live_updates.mark(eid)

        handler.write_json(experiment.to_dict())

    @check_auth
    @check_readonly_message(
        "Experiment logging is disabled while the server is in readonly mode"
    )
    async def post(self):
        args = tornado.escape.json_decode(
            tornado.escape.to_basestring(self.request.body)
        )
        await self.wrap_func(self, args)


class ExperimentSearchHandler(BaseHandler):
    """POST ``/experiments/search`` — find experiments across all environments.

    The JSON body carries a ``query`` in the syntax of
    :mod:`~visdom.experiments.query` (``"lr < 0.01 AND acc > 90"``); an absent or
    blank query matches every experiment. Queries are parsed into a predicate and
    evaluated in Python — never eval'd — so a hostile query is a parse error, not
    an execution.

    Results are sorted (``sort_by``/``descending``, newest first by default) and
    then paged with ``limit``/``offset``, and the reply reports the unpaged
    ``total`` so a caller can page through it:

        {"experiments": [...], "total": 42, "limit": 100, "offset": 0, "query": ""}

    Experiments are read back through the server's ``DataStore``, which means a
    server running with ``env_path=None`` — where nothing is persisted at all —
    has nothing to search and returns no results.

    A reply is capped at ``MAX_LIMIT`` experiments. A larger ``limit``, or a
    ``null`` one, is coerced down rather than refused, and the reply reports the
    ``limit`` it actually applied, so a caller can always see what it got; the
    ``total`` is unaffected and remains the count of every match. Without a cap
    one request could ask the server to serialize everything it stores.

    Paging depth is capped too: a page at ``offset`` is found by ranking every
    match down to ``offset + limit`` and discarding all but the last ``limit``
    of them, so a deep page costs the server its whole depth even though it
    returns one page. ``MAX_WINDOW`` bounds that depth, and a request past it is
    refused with a 400 rather than coerced — a coerced ``limit`` returns fewer
    experiments and says so, but a coerced ``offset`` would return a *different*
    page than the one asked for, and the caller could not tell. Reaching further
    than the window means narrowing the query, not paging deeper.
    """

    DEFAULT_LIMIT = 100
    MAX_LIMIT = 1000
    MAX_WINDOW = 10000

    @staticmethod
    def _require_index(args, field, default, maximum=None):
        """Return ``args[field]`` as a non-negative int, capped at ``maximum``.

        A JSON body has no int/float distinction, so a client that sends ``10.0``
        means the index 10; anything with a fractional part is a mistake.

        ``None`` means "as many as allowed": with a ``maximum`` it becomes that
        maximum, and without one it stays unbounded. A value above ``maximum``
        is coerced down rather than rejected, so raising a page size can never
        turn a working request into a failing one.
        """
        value = args.get(field, default)
        if value is None:
            return maximum
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            raise tornado.web.HTTPError(
                400, reason="'{0}' must be an integer".format(field)
            )
        if value < 0:
            raise tornado.web.HTTPError(
                400, reason="'{0}' must not be negative".format(field)
            )
        if maximum is not None and value > maximum:
            return maximum
        return value

    @staticmethod
    def _require_window(offset, limit):
        """Raise 400 if the page at ``offset`` reaches past ``MAX_WINDOW``.

        ``offset`` is checked against ``limit`` rather than on its own because
        the cost is the pair: the store ranks ``offset + limit`` matches to
        answer either. Capping ``limit`` alone would leave a one-experiment page
        at a large enough ``offset`` costing more than the whole-store reply the
        ``limit`` cap exists to prevent.
        """
        window = offset + limit
        if window > ExperimentSearchHandler.MAX_WINDOW:
            raise tornado.web.HTTPError(
                400,
                reason=(
                    "'offset' + 'limit' must not exceed {0} (got {1}); "
                    "narrow the query instead of paging further".format(
                        ExperimentSearchHandler.MAX_WINDOW, window
                    )
                ),
            )

    @staticmethod
    def _require_text(args, field):
        """Return ``args[field]`` if it is a string (or absent); else raise 400."""
        value = args.get(field)
        if value is not None and not isinstance(value, str):
            raise tornado.web.HTTPError(
                400, reason="'{0}' must be a string".format(field)
            )
        return value

    @staticmethod
    def _require_flag(args, field, default):
        """Return ``args[field]`` as a bool; else raise 400.

        Deliberately not ``bool(value)``: JSON has real booleans, so a client
        sending the *string* ``"false"`` means false, and coercing it would
        truthily flip the result to its opposite without a word.
        """
        value = args.get(field, default)
        if not isinstance(value, bool):
            raise tornado.web.HTTPError(
                400, reason="'{0}' must be a boolean".format(field)
            )
        return value

    @staticmethod
    async def wrap_func(handler, args):
        query = ExperimentSearchHandler._require_text(args, "query")
        sort_by = ExperimentSearchHandler._require_text(args, "sort_by")
        limit = ExperimentSearchHandler._require_index(
            args,
            "limit",
            ExperimentSearchHandler.DEFAULT_LIMIT,
            maximum=ExperimentSearchHandler.MAX_LIMIT,
        )
        offset = ExperimentSearchHandler._require_index(args, "offset", 0)
        descending = ExperimentSearchHandler._require_flag(args, "descending", True)
        ExperimentSearchHandler._require_window(offset, limit)

        try:
            # searching reads every environment on disk -- the longest read the
            # server makes, and the one it must not make on the loop.
            page, total = await run_on_storage_executor(
                handler,
                _search_experiments,
                handler.storage,
                query,
                sort_by or DEFAULT_SORT_FIELD,
                descending,
                offset,
                limit,
            )
        except QueryParseError as e:
            raise tornado.web.HTTPError(400, reason=str(e))

        handler.write_json(
            {
                "experiments": [e.to_dict() for e in page],
                "total": total,
                "limit": limit,
                "offset": offset,
                "query": query or "",
            }
        )

    @check_auth
    async def post(self):
        await self.wrap_func(self, _decode_json_body(self.request.body))


class ExperimentCompareHandler(BaseHandler):
    """POST ``/experiments/compare`` — diff the named experiments field by field.

    The JSON body names the runs to compare::

        {"env_ids": ["run-a", "run-b"]}

    Every id must have an experiment — a 404 names the ones that do not, since
    quietly comparing the remainder would answer a question the caller did not
    ask. Finding the runs is ``/experiments/search``'s job: it answers "which runs
    match?", this answers "how do these runs differ?". A caller comparing a
    query's matches searches first and passes the ids on.

    The reply carries the compared runs (``env_ids``, ``experiments``) and a diff
    per section, each listing the union of ``fields``, the ``shared`` ones every
    run agrees on, the ``differing`` rest, and the per-run ``values``::

        {"env_ids": [...], "experiments": [...],
         "params": {"fields": [...], "shared": {...},
                    "differing": [...], "values": {...}},
         "metrics": {...}, "tags": {...}}

    Experiments are read through the server's ``DataStore``, so as with search a
    server running with ``env_path=None`` has nothing to compare. The body is
    decoded by the shared ``_decode_json_body``, so the two endpoints
    answer malformed JSON and non-object bodies with the same 400; unlike
    search, an empty body is not a valid request here, since ``env_ids`` is
    required and there is no comparison to make without it.

    At most ``MAX_ENV_IDS`` runs are compared in one request: every named run is
    loaded and echoed back in full, so the reply grows with the list. The list
    is refused rather than truncated, for the same reason a missing run is a 404
    — a diff of some of the runs asked for is a different answer, not a smaller
    one, and nothing in the reply would reveal the difference. The cap matches
    search's ``MAX_LIMIT``, so any single page of search results can be handed
    straight to compare; a longer list is compared in batches.
    """

    MAX_ENV_IDS = 1000

    @staticmethod
    def _require_env_ids(args):
        """Return ``args["env_ids"]`` as a list of ids; raise 400 if unusable.

        A bare string is rejected rather than treated as a one-id list: it would
        otherwise be iterated character by character into a comparison of runs
        named ``"r"``, ``"u"``, ``"n"``.

        Length is checked before the ids are read, since the cost being bounded
        is loading them.
        """
        value = args.get("env_ids")
        if value is None:
            raise tornado.web.HTTPError(400, reason="'env_ids' is required")
        if not isinstance(value, list):
            raise tornado.web.HTTPError(400, reason="'env_ids' must be a list of ids")
        if not value:
            raise tornado.web.HTTPError(
                400, reason="'env_ids' must name at least one environment"
            )
        if len(value) > ExperimentCompareHandler.MAX_ENV_IDS:
            raise tornado.web.HTTPError(
                400,
                reason=(
                    "'env_ids' must not name more than {0} environments "
                    "(got {1}); compare them in batches".format(
                        ExperimentCompareHandler.MAX_ENV_IDS, len(value)
                    )
                ),
            )
        if not all(isinstance(env_id, str) for env_id in value):
            raise tornado.web.HTTPError(400, reason="'env_ids' must contain strings")
        return value

    @staticmethod
    async def wrap_func(handler, args):
        env_ids = ExperimentCompareHandler._require_env_ids(args)
        try:
            comparison = await run_on_storage_executor(
                handler, _compare_experiments, handler.storage, env_ids
            )
        except KeyError as e:
            raise tornado.web.HTTPError(404, reason=str(e.args[0]))

        handler.write_json(comparison)

    @check_auth
    async def post(self):
        await self.wrap_func(self, _decode_json_body(self.request.body))


class ExperimentSuggestHandler(BaseHandler):
    """POST ``/experiments/suggest`` — suggest parameters for the next run.

    Reserved endpoint. Choosing the next set of hyper-parameters to try is a
    search-strategy problem (Optuna-backed) that belongs to a later release, so
    this is a stub: it accepts the request and replies ``501 Not Implemented``
    with a JSON body rather than a made-up suggestion. Wiring the route, the
    :meth:`Visdom.suggest_experiment` client method and the API docs now means
    the strategy can be dropped in later without changing the surface, and a
    caller gets a stable, decodable answer it can tell apart from a real one::

        {"status": "not_implemented", "detail": "...", "suggestion": null}

    The request body is validated and passed through like the sibling handlers
    so that shape is already in place, but it is otherwise ignored until the
    strategy lands. A body that is not a JSON object is still rejected with 400:
    a caller sending a malformed search space should hear about it now rather
    than have it silently accepted here and rejected once the strategy lands.
    """

    #: The stub reply, carrying ``suggestion: null`` so the eventual field is
    #: already named and a caller can distinguish the stub from a real result.
    NOT_IMPLEMENTED = {
        "status": "not_implemented",
        "detail": (
            "experiment suggestion is not implemented yet; the endpoint is "
            "reserved for a later release"
        ),
        "suggestion": None,
    }

    @staticmethod
    def wrap_func(handler, args):
        handler.set_status(501)
        handler.write_json(ExperimentSuggestHandler.NOT_IMPLEMENTED)

    @check_auth
    def post(self):
        self.wrap_func(self, _decode_json_body(self.request.body))


class TagsHandler(BaseHandler):
    """Read and update environment tags backed by experiment metadata."""

    VALID_ACTIONS = ("get", "set")

    @staticmethod
    def _experiment_from_env(eid, env):
        """Return an experiment from one materialized in-memory environment."""
        blob = env.get("experiment")
        if not isinstance(blob, Mapping):
            return None
        experiment = Experiment.from_dict(blob)
        experiment.env_id = eid
        return experiment

    @staticmethod
    def _read_experiment(handler, eid):
        """Read one experiment without materializing unrelated environments."""
        env = handler.state.get(eid)
        if env is None or (isinstance(env, LazyEnvData) and not env.is_loaded):
            return ExperimentStore(handler.storage).get_experiment(eid)
        experiment = TagsHandler._experiment_from_env(eid, env)
        if experiment is not None:
            return experiment
        return ExperimentStore(handler.storage).get_experiment(eid)

    @staticmethod
    def _experiment_map(handler):
        """Return stored experiments overlaid with materialized state only."""
        store = ExperimentStore(handler.storage)
        experiments = {exp.env_id: exp for exp in store.list_experiments()}
        for eid, env in handler.state.items():
            if isinstance(env, LazyEnvData) and not env.is_loaded:
                continue
            experiment = TagsHandler._experiment_from_env(eid, env)
            if experiment is not None:
                experiments[eid] = experiment
        return experiments

    @staticmethod
    def _write_tags(handler, eid=None):
        if eid is not None:
            experiment = TagsHandler._read_experiment(handler, eid)
            tags = tags_to_mapping(experiment.tags) if experiment else {}
            handler.write_json(tags)
            return
        experiments = TagsHandler._experiment_map(handler)
        tag_map = {
            env_id: tags_to_mapping(experiment.tags)
            for env_id, experiment in experiments.items()
            if experiment.tags
        }
        handler.write_json(tag_map)

    @staticmethod
    async def wrap_func(handler, args):
        action = args.get("action", "set")
        if action not in TagsHandler.VALID_ACTIONS:
            raise tornado.web.HTTPError(
                400, reason="unknown action {0!r}".format(action)
            )

        if action == "get":
            eid = extract_eid(args) if args.get("eid") is not None else None
            TagsHandler._write_tags(handler, eid)
            return

        if handler.readonly:
            handler.set_status(403)
            handler.write(
                {
                    "success": False,
                    "error": "Tag updates are disabled while the server is "
                    "in readonly mode",
                }
            )
            return

        if "tags" not in args:
            raise tornado.web.HTTPError(400, reason="'tags' is required for set action")

        eid = extract_eid(args)
        append = args.get("append", False)
        try:
            # tags share the environment file with the experiment they organise
            # and with every window in it, so setting one goes through the same
            # single writer as the rest: applied to the live env here, queued
            # onto the storage worker behind whatever the loop queued before it.
            experiment, is_new_env = await _write_experiment_metadata(
                handler,
                eid,
                lambda store: store.update_tags(eid, args["tags"], append=append),
            )
        except (TypeError, ValueError) as error:
            raise tornado.web.HTTPError(400, reason=str(error))

        tags = tags_to_mapping(experiment.tags)
        if is_new_env:
            broadcast_envs(handler)
        broadcast_tags(handler, eid, tags)
        handler.write_json(tags)

    @check_auth
    async def get(self):
        eid = self.get_query_argument("eid", default=None)
        await self.wrap_func(self, {"action": "get", "eid": eid})

    @check_auth
    async def post(self):
        await self.wrap_func(self, _decode_json_body(self.request.body))


class HealthHandler(BaseHandler):
    def get(self):
        self.write({"status": "ok"})
