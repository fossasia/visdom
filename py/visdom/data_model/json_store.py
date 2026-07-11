#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import json
import os
import re

from visdom.data_model.base import DataStore
from visdom.utils.server_utils import escape_eid, serialize_env

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
            safe_eid = self._safe_eid(eid)
            serialize_env({safe_eid: state[eid]}, [safe_eid], env_path=self.env_path)
            written.append(eid)
        return written

    def save_all(self, state):
        """Persist every environment in ``state``; return the ids written."""
        return self.save_envs(state, list(state.keys()))

    def load_env(self, eid):
        """Read one environment by ``eid``; return ``{}`` if it is absent."""
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
        if isinstance(data, dict) and "jsons" in data and "reload" in data:
            return {"jsons": data.get("jsons", {}), "reload": data.get("reload", {})}
        return {}

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
        except OSError:
            return False
        return True

    def env_exists(self, eid):
        """Return whether an environment ``eid`` is present on disk."""
        if self.env_path is None:
            return False
        return self._resolve_existing(eid) is not None
