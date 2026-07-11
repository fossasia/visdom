#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from abc import ABC, abstractmethod


class DataStore(ABC):
    """Interface for persisting Visdom environments.

    Defines what Visdom needs from storage without fixing how it is stored, so
    that a concrete backend (JSON files today, a database later) can be swapped
    in without changing any caller. An environment is the dict the server holds
    in memory, of the form ``{"jsons": {...}, "reload": {...}}``, keyed by its
    id (``eid``).
    """

    @abstractmethod
    def save_env(self, eid, env_data):
        """Persist a single environment identified by ``eid``."""
        raise NotImplementedError

    @abstractmethod
    def save_envs(self, state, eids):
        """Persist the named subset of environments from ``state``."""
        raise NotImplementedError

    @abstractmethod
    def save_all(self, state):
        """Persist every environment in ``state``."""
        raise NotImplementedError

    @abstractmethod
    def load_env(self, eid):
        """Read and return one environment's data by ``eid``."""
        raise NotImplementedError

    @abstractmethod
    def list_envs(self):
        """Return the ids of all stored environments."""
        raise NotImplementedError

    @abstractmethod
    def delete_env(self, eid):
        """Remove one environment identified by ``eid``."""
        raise NotImplementedError

    @abstractmethod
    def env_exists(self, eid):
        """Return whether an environment with ``eid`` is stored."""
        raise NotImplementedError
