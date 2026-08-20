#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import copy
import errno
import hashlib
import json
import logging
import os
import re

from visdom.data_model.base import DataStore
from visdom.server.defaults import LAYOUT_FILE, UNDO_DIRNAME
from visdom.utils.server_utils import escape_eid, LazyEnvData
from visdom.utils.shared_utils import ensure_dir_exists, NanSafeEncoder

HASHED_ENV_RE = re.compile(r"^hash_[a-f0-9]{64}\.json$", re.IGNORECASE)


class JSONStore(DataStore):
    """DataStore backed by one ``<eid>.json`` file per environment.

    Environments too long to use as a filename are stored under a
    ``hash_<sha256>.json`` fallback with their real id kept inside the file.
    When ``env_path`` is ``None`` persistence is disabled and the store behaves
    as a no-op (matching Visdom's in-memory-only mode).
    """

    def __init__(self, env_path):
        """Create a store rooted at ``env_path`` (``None`` disables persistence)."""
        self.env_path = env_path

    def _safe_eid(self, eid):
        """Sanitise ``eid`` into the id used for on-disk filenames.

        Strips surrounding whitespace and neutralises path separators (via
        ``escape_eid``) so a crafted id such as ``../evil`` cannot escape
        ``env_path``. Saves, loads, deletes and existence checks all funnel
        through this so they agree on the file a given ``eid`` maps to.
        """
        return escape_eid(eid.strip())

    def _primary_path(self, eid):
        """Return the canonical ``<env_path>/<eid>.json`` path for ``eid``.

        Returns ``None`` if the resolved path would escape ``env_path`` (guards
        against path traversal via a crafted env id).
        """
        safe_eid = self._safe_eid(eid)
        base = os.path.abspath(self.env_path)
        path = os.path.abspath(os.path.join(base, "{0}.json".format(safe_eid)))
        try:
            is_safe = os.path.commonpath([path, base]) == base
        except ValueError:
            is_safe = False
        return path if is_safe else None

    def _hash_path(self, eid):
        """Return the ``hash_<sha256>.json`` fallback path for ``eid``."""
        safe_eid = self._safe_eid(eid)
        hashed_id = hashlib.sha256(safe_eid.encode("utf-8")).hexdigest()
        return os.path.join(self.env_path, "hash_{0}.json".format(hashed_id))

    def _resolve_existing(self, eid):
        """Return the existing file path for ``eid`` (primary or hash), or ``None``."""
        primary = self._primary_path(eid)
        if primary is not None and os.path.exists(primary):
            return primary
        hashed = self._hash_path(eid)
        if os.path.exists(hashed):
            return hashed
        return None

    def save_env(self, eid, env_data):
        """Persist a single environment; return ``True`` if written, else ``False``."""
        return bool(self.save_envs({eid: env_data}, [eid]))

    def save_envs(self, state, eids):
        """Persist the named subset of ``state``; return the ids actually written.

        Each id is sanitised (see :meth:`_safe_eid`) before it becomes a
        filename, so a crafted id cannot write outside ``env_path``. The real
        (unsanitised) ids are returned, matching how callers refer to them.
        """
        if self.env_path is None:
            return []
        os.makedirs(os.path.abspath(self.env_path), exist_ok=True)
        written = []
        for eid in eids:
            if eid not in state:
                continue
            if self.serialize_env(eid, state[eid]):
                written.append(eid)
        return written

    def _atomic_write(self, path, payload):
        """Write ``payload`` to ``path`` via a temporary file and one rename.

        Writing straight to ``path`` truncates the previous contents before the
        new ones are complete, so an interrupted write leaves a half-file that
        :meth:`load_env` cannot parse and silently reports as an empty
        environment. Staging into ``<path>.tmp`` and calling :func:`os.replace`
        keeps the old file readable until the new one is whole. This mirrors
        :meth:`save_undo`.
        """
        tmp = path + ".tmp"
        with open(tmp, "w") as fn:
            fn.write(payload)
        os.replace(tmp, path)

    def serialize_env(self, eid, env_data):
        """Write one environment to disk; return ``True`` if written.

        A :class:`LazyEnvData` that was never materialised (``_raw_dict`` is
        ``None``) is skipped and ``False`` is returned: its on-disk copy is
        already current, so there is nothing to rewrite and no reason to force
        it into memory. The write funnels through :meth:`_primary_path` /
        :meth:`_hash_path` so it agrees with load/delete/exists on the file a
        given ``eid`` maps to; over-long ids fall back to ``hash_<sha256>.json``
        with the real id kept in a ``name`` field.

        The write itself is atomic (see :meth:`_atomic_write`), so a crash
        part-way through cannot destroy the environment already on disk. The
        staging file carries a ``.tmp`` suffix rather than ``.json``, so a
        stranded one is never mistaken for an environment by :meth:`list_envs`.
        """
        if isinstance(env_data, LazyEnvData):
            if env_data._raw_dict is None:
                return False
            env_data.lazy_load_data()
            payload = env_data._raw_dict
        else:
            payload = env_data

        primary = self._primary_path(eid)
        try:
            if primary is None:
                raise OSError(errno.ENAMETOOLONG, "env id maps outside env_path")
            self._atomic_write(primary, json.dumps(payload, cls=NanSafeEncoder))
        except OSError as e:
            if e.errno != errno.ENAMETOOLONG and getattr(e, "winerror", None) != 206:
                raise
            data_to_save = copy.deepcopy(payload)
            data_to_save["name"] = self._safe_eid(eid)
            self._atomic_write(
                self._hash_path(eid), json.dumps(data_to_save, cls=NanSafeEncoder)
            )
        return True

    def save_all(self, state):
        """Persist every environment in ``state``; return the ids written."""
        return self.save_envs(state, list(state.keys()))

    def load_env(self, eid):
        """Read one environment by ``eid``; return ``{}`` if it is absent.

        Only the canonical env fields are returned: ``jsons`` and ``reload``,
        plus the ``experiment`` metadata blob when present. Internal bookkeeping
        such as the ``name`` field written for hashed long-id files is dropped.
        """
        if self.env_path is None:
            return {}
        path = self._resolve_existing(eid)
        if path is None:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fn:
                data = json.load(fn)
        except (OSError, ValueError):
            return {}
        if not (isinstance(data, dict) and "jsons" in data and "reload" in data):
            return {}
        env = {"jsons": data.get("jsons", {}), "reload": data.get("reload", {})}
        if "experiment" in data:
            env["experiment"] = data["experiment"]
        return env

    def list_envs(self):
        """Return the ids of all environments stored on disk.

        Hash-fallback files are recognised by their exact ``hash_<64 hex>.json``
        shape and resolved to the real id kept inside; every other ``.json`` file
        yields its filename stem. Sub-directories (e.g. ``view/``) are skipped.
        """
        if self.env_path is None or not os.path.isdir(self.env_path):
            return []
        envs = []
        for name in os.listdir(self.env_path):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.env_path, name)
            if not os.path.isfile(path):
                continue
            if HASHED_ENV_RE.match(name):
                try:
                    with open(path, "r", encoding="utf-8") as fn:
                        envs.append(json.load(fn)["name"])
                except (OSError, UnicodeError, ValueError, KeyError):
                    continue
            else:
                envs.append(name[: -len(".json")])
        return sorted(envs)

    def delete_env(self, eid):
        """Remove ``eid`` from disk; return ``True`` if a file was removed."""
        if self.env_path is None:
            return False
        path = self._resolve_existing(eid)
        if path is None:
            return False
        try:
            os.remove(path)
        except FileNotFoundError:
            return False
        except OSError as e:
            logging.error(f"Failed to delete {path}: {e}")
            return False
        return True

    def env_exists(self, eid):
        """Return whether an environment ``eid`` is present on disk."""
        if self.env_path is None:
            return False
        return self._resolve_existing(eid) is not None

    def _layout_path(self):
        """Return the ``<env_path>/view/<LAYOUT_FILE>`` path for saved layouts."""
        return os.path.join(self.env_path, "view", LAYOUT_FILE)

    def save_layouts(self, layouts):
        """Write the saved-views layout string; no-op when persistence is off."""
        if self.env_path is None:
            return
        layout_path = self._layout_path()
        ensure_dir_exists(os.path.dirname(layout_path))
        with open(layout_path, "w") as fn:
            fn.write(layouts)

    def load_layouts(self):
        """Read the saved-views layout string; return ``""`` if none is stored."""
        if self.env_path is None:
            return ""
        layout_path = self._layout_path()
        if os.path.isfile(layout_path):
            with open(layout_path, "r") as fn:
                return fn.read()
        return ""

    def _undo_paths(self, eid):
        """Return ``(undo_dir, plain_path, hashed_path)`` for ``eid``'s undo file.

        ``hashed_path`` mirrors ``serialize_env``'s fallback for env ids whose
        plain filename would exceed the filesystem limit.
        """
        safe_eid = self._safe_eid(eid)
        undo_dir = os.path.join(self.env_path, UNDO_DIRNAME)
        plain = os.path.join(undo_dir, "{0}.json".format(safe_eid))
        hashed_id = hashlib.sha256(safe_eid.encode("utf-8")).hexdigest()
        hashed = os.path.join(undo_dir, "hash_{0}.json".format(hashed_id))
        return undo_dir, plain, hashed

    def load_undo(self, eid):
        """Return ``eid``'s undo stack (a list), or ``[]`` if missing/corrupt."""
        if self.env_path is None:
            return []
        _, plain, hashed = self._undo_paths(eid)
        path = plain if os.path.exists(plain) else hashed
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r") as fn:
                data = json.loads(fn.read())
        except (OSError, ValueError):
            logging.warning(f"Could not read undo stack for env {eid}; ignoring it")
            return []
        return data if isinstance(data, list) else []

    def save_undo(self, eid, stack):
        """Atomically persist ``eid``'s undo stack; no-op when persistence is off."""
        if self.env_path is None:
            return
        undo_dir, plain, hashed = self._undo_paths(eid)
        os.makedirs(undo_dir, exist_ok=True)
        payload = json.dumps(stack, cls=NanSafeEncoder)
        try:
            target = plain
            self._atomic_write(plain, payload)
        except OSError as e:
            if e.errno != errno.ENAMETOOLONG and getattr(e, "winerror", None) != 206:
                raise
            target = hashed
            self._atomic_write(hashed, payload)
        return target

    def clear_undo(self, eid):
        """Remove ``eid``'s on-disk undo history; no-op when persistence is off."""
        if self.env_path is None:
            return
        _, plain, hashed = self._undo_paths(eid)
        for path in (plain, hashed):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    logging.error(f"Failed to delete undo file {path}: {e}")
