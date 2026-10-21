#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""How much does reading experiment metadata cost, and how often is it paid?

An environment is one JSON document, so reaching the few hundred bytes of
experiment metadata inside it means parsing every window in the file -- and
``ExperimentStore.iter_experiments`` does that for *every* environment on disk.
One ``/experiments/search``, one ``/experiments/hparams``, and every
``GET /experiments/tags`` the UI issues on page load, each pay the whole
``~/.visdom`` directory.

So the number that matters is not one read but a repeated one: the first scan
has to parse the files whatever the server does, and the question is what the
second one costs. Each row therefore reports both.

The baseline is dev's own ``json_store.py``, read out of git and imported as a
second live module, rather than a reimplementation of it -- and the two are
measured alternately, because a separate process per side measures the
machine's drift as much as the code (see README.md).

    python example/benchmarks/experiment_scan.py
    python example/benchmarks/experiment_scan.py --envs 50 --sizes 4000
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import types

from _harness import arg_parser, parse_sizes, positive_int, Result, table

DEV_STORE_PATH = "py/visdom/data_model/json_store.py"


def repo_root():
    """The checkout this file lives in."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def merge_base():
    """The commit this branch forked from, i.e. the baseline to compare against."""
    return (
        subprocess.check_output(
            ["git", "merge-base", "upstream/dev", "HEAD"], cwd=repo_root()
        )
        .decode()
        .strip()
    )


def dev_store_class(commit):
    """``JSONStore`` as of ``commit``, imported as a second live module.

    The file's imports are absolute, so they bind to this checkout's
    ``data_model.base`` and ``utils`` exactly as the branch's copy does: the
    only thing that differs between the two classes under test is the file
    being compared.
    """
    source = subprocess.check_output(
        ["git", "show", "%s:%s" % (commit, DEV_STORE_PATH)], cwd=repo_root()
    )
    name = "dev_json_store_%s" % commit[:8]
    module = types.ModuleType(name)
    module.__file__ = "<%s:%s>" % (commit[:8], DEV_STORE_PATH)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module.JSONStore


def seed(env_path, envs, points):
    """Write ``envs`` env files, each one window of ``points`` and a run's metadata."""
    from visdom.data_model import JSONStore
    from visdom.experiments import ExperimentStore

    store = JSONStore(env_path)
    experiments = ExperimentStore(store)
    series = [
        {"key": "acc", "value": 0.5 + i / (2.0 * points), "step": i, "timestamp": 0.0}
        for i in range(min(points, 200))
    ]
    for index in range(envs):
        eid = "run-%03d" % index
        experiments.log_experiment(
            eid,
            name="run %d" % index,
            params={"lr": 0.1 / (index + 1), "epochs": 10 + index},
            tags={"dataset": "mnist"},
        )
        env = store.load_env(eid)
        env["jsons"] = {
            "win_0": {
                "id": "win_0",
                "type": "plot",
                "content": {
                    "data": [
                        {
                            "x": list(range(points)),
                            "y": [i / 7.0 for i in range(points)],
                            "type": "scatter",
                        }
                    ],
                    "layout": {"title": {"text": eid}},
                },
            }
        }
        env["experiment"]["metrics"] = list(series)
        store.save_env(eid, env)
    return os.path.getsize(os.path.join(env_path, "run-000.json"))


def scan(store_class, env_path):
    """One full search across every environment, as the endpoint performs it."""
    from visdom.experiments import ExperimentStore

    return len(ExperimentStore(store_class(env_path)).search())


def interleaved(sides, repeat, warmup):
    """Time each side once per round, alternating, and return a Result each.

    One side per process would be cleaner, but then the two numbers come from
    different moments on a machine that is doing other things, and the drift
    between them lands in the comparison. Alternating puts both sides under the
    same conditions.

    The order within a round is swapped every other round. Running one side
    first every time gives it a systematic advantage or handicap -- it is the
    call that pays for a cold page cache, a scheduler slice ending, whatever
    the other side then finds already warm -- and the bias lands in the ratio
    rather than averaging out across rounds, which is exactly what alternating
    was supposed to prevent.
    """
    samples = {name: [] for name in sides}
    order = list(sides)
    for round_index in range(warmup + repeat):
        for name in order if round_index % 2 == 0 else reversed(order):
            start = time.perf_counter()
            sides[name]()
            elapsed = (time.perf_counter() - start) * 1000.0
            if round_index >= warmup:
                samples[name].append(elapsed)
    return {name: Result(values) for name, values in samples.items()}


def main():
    parser = arg_parser(
        "experiment metadata reads, before and after the metadata index",
        sizes="500,4000,20000",
        repeat=5,
    )
    parser.add_argument(
        "--envs", type=positive_int, default=20, help="environments on disk"
    )
    args = parser.parse_args()

    from visdom.data_model import JSONStore

    base = merge_base()
    DevStore = dev_store_class(base)
    print("baseline: %s:%s (%s)\n" % (base[:8], DEV_STORE_PATH, "dev"))

    rows = []
    for points in parse_sizes(args):
        env_path = tempfile.mkdtemp(prefix="visdom_scan_bench_")
        try:
            env_bytes = seed(env_path, args.envs, points)

            # A fresh store per call is what "cold" means: nothing cached yet,
            # which is every call on dev and the first call on the branch.
            cold = interleaved(
                {
                    "dev": lambda: scan(DevStore, env_path),
                    "branch": lambda: scan(JSONStore, env_path),
                },
                args.repeat,
                args.warmup,
            )

            # Warm: one store serving repeated requests, as the server does.
            dev_store = DevStore(env_path)
            branch_store = JSONStore(env_path)
            from visdom.experiments import ExperimentStore

            # Prime both stores before timing anything, independently of
            # --warmup: a store's first search is by definition a cold one, so
            # with --warmup 0 the "warm" column would otherwise report a cold
            # number for whichever side caches.
            for store in (dev_store, branch_store):
                ExperimentStore(store).search()

            warm = interleaved(
                {
                    "dev": lambda: len(ExperimentStore(dev_store).search()),
                    "branch": lambda: len(ExperimentStore(branch_store).search()),
                },
                args.repeat,
                args.warmup,
            )

            rows.append(
                [
                    points,
                    "%.0f KB" % (env_bytes / 1024.0),
                    "%.1f" % cold["dev"].p50,
                    "%.1f" % cold["branch"].p50,
                    "%.1f" % warm["dev"].p50,
                    "%.1f" % warm["branch"].p50,
                    "%.1fx" % (warm["dev"].p50 / warm["branch"].p50),
                ]
            )
        finally:
            shutil.rmtree(env_path, ignore_errors=True)

    print("%d environments, one search each (ms, p50)\n" % args.envs)
    table(
        [
            "points/env",
            "env file",
            "cold dev",
            "cold branch",
            "warm dev",
            "warm branch",
            "warm speedup",
        ],
        rows,
    )
    print(
        "\nCold is a search that has to parse the files, and the branch does not"
        "\nmake it faster -- the parse is unavoidable the first time. Warm is"
        "\nevery search after it, which is what a running server serves."
    )


if __name__ == "__main__":
    main()
