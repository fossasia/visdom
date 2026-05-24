# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Auto-versioning utility for Visdom environments."""

import re


def get_next_version(viz, base_env="run"):
    """Return the next available versioned environment name.

    Scans existing Visdom environments that match the pattern
    ``{base_env}_NNN`` and returns the next sequential version string.

    Args:
        viz: A connected :class:`visdom.Visdom` instance.
        base_env: Prefix used for environment names (default ``"run"``).

    Returns:
        A tuple ``(env_name, version)`` where *env_name* is a string like
        ``"run_001"`` and *version* is the integer version number (e.g. ``1``).

    Examples:
        >>> # If envs ["run_000", "run_001"] exist:
        >>> get_next_version(viz, "run")
        ('run_002', 2)
    """
    pattern = re.compile(r"^" + re.escape(base_env) + r"_(\d+)$")
    max_version = -1

    try:
        env_list = viz.get_env_list()
    except Exception:
        # Server unreachable or offline mode — start from 0.
        env_list = []

    for env_name in env_list:
        m = pattern.match(env_name)
        if m:
            max_version = max(max_version, int(m.group(1)))

    next_version = max_version + 1
    return "{base}_{ver:03d}".format(base=base_env, ver=next_version), next_version
