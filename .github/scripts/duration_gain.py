# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
"""Estimate both shard layouts using times from the same fresh run.

Usage: duration_gain.py OLD_JSON FRESH_JSON COLLECTION_TXT SPLITS

COLLECTION_TXT is the output of ``pytest --collect-only -q``. Prints the
predicted slowest shard before/after and ``refresh=true|false`` for
``$GITHUB_OUTPUT``.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from pytest_split.algorithms import Algorithms

MIN_GAIN_SECONDS = 3

old_path, fresh_path, collection_path, count = sys.argv[1:]
old = json.loads(Path(old_path).read_text())
fresh = json.loads(Path(fresh_path).read_text())
items = [
    SimpleNamespace(nodeid=line)
    for line in dict.fromkeys(Path(collection_path).read_text().splitlines())
    if line.startswith("py/tests/") and "::" in line
]
if not items or not fresh:
    raise SystemExit("Missing collected tests or timing measurements")


def slowest(weights):
    shards = Algorithms.duration_based_chunks.value(int(count), items, weights)
    return max(
        sum(fresh.get(item.nodeid, 0) for item in shard.selected) for shard in shards
    )


before = slowest(old)
after = slowest(fresh)
print(
    f"Predicted longest shard with committed timings {before:.1f}s, "
    f"with refreshed timings {after:.1f}s."
)
print(f"refresh={'true' if before - after >= MIN_GAIN_SECONDS else 'false'}")
