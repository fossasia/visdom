#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""What does saving an environment cost before the write even starts?

Writing an env happens on the storage worker, but the copy it writes from is
taken on the IOLoop -- that is the only place the env is not being mutated by a
request handler. So every save pays a full walk of the whole environment on the
loop, however little of it changed, and it is paid on a timer: every
``DEFAULT_SAVE_INTERVAL`` seconds, or straight away once an env has taken
``DEFAULT_SAVE_THRESHOLD`` updates. A run plotting into a long-lived env pays
it again and again, which is the shape issue #695 describes -- CPU that grows
with how much is already plotted rather than with what is being asked for.

The two sides here are the same snapshot, copied two ways: ``copy.deepcopy``,
which is what ``snapshot_env`` used to call, and the env-shaped copy it calls
now. They are timed alternately in one process, because a separate run per
side measures the machine's drift as much as the code (see README.md).

    python example/benchmarks/env_snapshot.py
    python example/benchmarks/env_snapshot.py --panes 40 --sizes 1000
"""

import copy
import json

from _harness import (
    arg_parser,
    interleaved,
    line_payloads,
    parse_sizes,
    positive_int,
    register_pane,
    StubHandler,
    table,
)


def seed_env(panes, points):
    """An env holding ``panes`` panes of ``points`` points each.

    The panes come from the real client and the real ``window()``, so what is
    copied is the pane the server really stores, down to the marker dict and
    the derived layout -- an env of hand-written dicts would be missing most of
    the small nested containers that a copy actually spends its time on.
    """
    handler = StubHandler()
    for index in range(panes):
        create, _ = line_payloads(points, win="bench_win_%d" % index)
        register_pane(handler, create)
    return handler.state["main"]


def main():
    parser = arg_parser(
        "what one environment snapshot costs the IOLoop",
        sizes="500,4000,20000",
        repeat=20,
    )
    parser.add_argument(
        "--panes", type=positive_int, default=1, help="windows in the environment"
    )
    args = parser.parse_args()

    from visdom.server import defaults
    from visdom.utils.server_utils import snapshot_env

    rows = []
    for points in parse_sizes(args):
        env = seed_env(args.panes, points)
        # The env is measured before the timing starts and the figure kept as a
        # number: holding a second live copy of a multi-megabyte env across the
        # measurement puts the garbage collector's walk of it inside the
        # samples, which is worth ~2x at the larger sizes.
        env_kb = len(json.dumps(env)) / 1024.0

        result = interleaved(
            {
                # dev's ``snapshot_env`` body, inlined -- it is one line, so
                # there is nothing to load out of git the way the baseline
                # store in experiment_scan.py has to be.
                "dev": lambda env=env: copy.deepcopy(dict(env)),
                "branch": lambda env=env: snapshot_env(env),
            },
            args.repeat,
            args.warmup,
        )

        rows.append(
            [
                points,
                args.panes,
                "%.0f KB" % env_kb,
                "%.2f" % result["dev"].p50,
                "%.2f" % result["branch"].p50,
                "%.1fx" % (result["dev"].p50 / result["branch"].p50),
            ]
        )

    print("one snapshot of one environment (ms, p50)\n")
    table(["points/pane", "panes", "env json", "deepcopy", "env copy", "speedup"], rows)
    print(
        "\nPaid on the IOLoop every %d updates to an environment, or every %d"
        "\nseconds, whichever comes first -- for the whole environment, not for"
        "\nthe window that changed."
        % (
            defaults.DEFAULT_SAVE_THRESHOLD,
            defaults.DEFAULT_SAVE_INTERVAL,
        )
    )


if __name__ == "__main__":
    main()
