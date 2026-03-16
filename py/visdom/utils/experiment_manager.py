#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import os
import json
import platform
import subprocess
import sys
import logging
from datetime import datetime
from visdom.utils.shared_utils import ensure_dir_exists

class ExperimentManager:
    def __init__(self, experiment_path):
        self.experiment_path = experiment_path
        ensure_dir_exists(self.experiment_path)

    def get_environment_metadata(self):
        """Captures OS, Python version, installed packages, and Git info."""
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "os": platform.platform(),
            "python_version": sys.version,
            "platform": platform.system(),
            "processor": platform.processor(),
            "pip_freeze": self._get_pip_freeze(),
            "git_info": self._get_git_info()
        }
        return metadata

    def _get_pip_freeze(self):
        try:
            return subprocess.check_output([sys.executable, "-m", "pip", "freeze"]).decode("utf-8")
        except Exception as e:
            logging.error(f"Failed to capture pip freeze: {e}")
            return "Unknown"

    def _get_git_info(self):
        try:
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
            branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode("utf-8").strip()
            is_dirty = subprocess.call(["git", "diff", "--quiet"]) != 0
            return {
                "sha": sha,
                "branch": branch,
                "is_dirty": is_dirty
            }
        except Exception:
            return "Not a git repository"

    def archive_experiment(self, eid, state, config=None):
        """Snapshots an environment and its metadata into a permanent archive."""
        metadata = self.get_environment_metadata()
        if config:
            metadata["config"] = config

        snapshot = {
            "eid": eid,
            "metadata": metadata,
            "data": state[eid] if eid in state else {"jsons": {}, "reload": {}}
        }

        archive_file = os.path.join(self.experiment_path, f"{eid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.exp")
        with open(archive_file, "w") as f:
            json.dump(snapshot, f)
        
        return archive_file

    def list_experiments(self):
        """Lists all archived experiments."""
        return [f for f in os.listdir(self.experiment_path) if f.endswith(".exp")]

    def load_experiment(self, filename):
        """Loads an archived experiment snapshot."""
        archive_file = os.path.join(self.experiment_path, filename)
        with open(archive_file, "r") as f:
            return json.load(f)
