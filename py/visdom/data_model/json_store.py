#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import json
import logging
import os
import re

from visdom.data_model.base import DataStore
from visdom.server.defaults import LAYOUT_FILE
from visdom.utils.server_utils import escape_eid, serialize_env
from visdom.utils.shared_utils import ensure_dir_exists

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

    def _primary_path(self, eid):
        """Return the canonical ``<env_path>/<eid>.json`` path for ``eid``.

        Returns ``None`` if the resolved path would escape ``env_path`` (guards
        against path traversal via a crafted env id).
        """
        safe_eid = escape_eid(eid.strip())
        base = os.path.abspath(self.env_path)
        path = os.path.abspath(os.path.join(base, "{0}.json".format(safe_eid)))
        try:
            is_safe = os.path.commonpath([path, base]) == base
        except ValueError:
            is_safe = False
        return path if is_safe else None

    def _hash_path(self, eid):
        """Return the ``hash_<sha256>.json`` fallback path for ``eid``."""
        safe_eid = escape_eid(eid.strip())
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
        if self.env_path is None:
            return False
        serialize_env({eid: env_data}, [eid], env_path=self.env_path)
        return True

    def save_envs(self, state, eids):
        """Persist the named subset of ``state``; return the ids actually written."""
        if self.env_path is None:
            return []
        return serialize_env(state, eids, env_path=self.env_path)

    def save_all(self, state):
        """Persist every environment in ``state``; return the ids written."""
        if self.env_path is None:
            return []
        return serialize_env(state, list(state.keys()), env_path=self.env_path)

    def load_env(self, eid):
        """Read one environment by ``eid``; return ``{}`` if it is absent."""
        if self.env_path is None:
            return {}
        path = self._resolve_existing(eid)
        if path is None:
            return {}
        with open(path, "r") as fn:
            return json.loads(fn.read())

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
                    with open(path, "r") as fn:
                        envs.append(json.loads(fn.read())["name"])
                except (OSError, ValueError, KeyError):
                    continue
            else:
                envs.append(name[: -len(".json")])
        return envs

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
