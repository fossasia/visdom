#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""How much CPU does the Python client spend building one payload?

Everything above the socket is timed: the argument validators, the trace and
layout construction, and the ``NanSafeEncoder`` pass in ``_send``. Only
``_handle_post`` is stubbed out.

Read the small sizes as a floor rather than a cost: see README.md.

    python example/benchmarks/payload_build.py
    python example/benchmarks/payload_build.py --sizes 1,1000,100000
"""

import numpy as np

import _harness as harness


def plot_workloads(client, n_points):
    """The plot calls to time at a given number of points."""
    x = np.arange(n_points, dtype=np.float64)
    y = np.sin(x / 50.0)
    labels = np.arange(n_points) % 4 + 1
    xy = np.column_stack([x, y])
    return [
        ("line", lambda: client.line(X=x, Y=y, win="bench_line")),
        (
            "line append 1",
            lambda: client.line(X=x[:1], Y=y[:1], win="bench_line", update="append"),
        ),
        ("scatter", lambda: client.scatter(X=xy, Y=labels, win="bench_scatter")),
        ("heatmap", lambda: client.heatmap(X=y.reshape(-1, 1), win="bench_heat")),
    ]


def media_workloads(client):
    """Media encodes, which do not scale with the plot sizes."""
    rng = np.random.default_rng(0)
    image = rng.integers(0, 255, (3, 512, 512)).astype(np.float64)
    batch = rng.integers(0, 255, (16, 3, 64, 64)).astype(np.float64)
    return [
        ("image 512x512", lambda: client.image(image, win="bench_image")),
        ("images 16x64x64", lambda: client.images(batch, win="bench_images")),
    ]


def main():
    parser = harness.arg_parser(
        __doc__.splitlines()[0], sizes="1,1000,20000", repeat=50
    )
    parser.add_argument("--skip-media", action="store_true", help="plots only")
    args = parser.parse_args()

    client = harness.offline_client()
    rows = []
    for n_points in harness.parse_sizes(args):
        for name, call in plot_workloads(client, n_points):
            result = harness.measure(call, args.repeat, args.warmup)
            rows.append(
                (
                    name,
                    n_points,
                    "%.3f" % result.p50,
                    "%.3f" % result.p95,
                    "%.0f" % result.per_sec,
                    "%.1f" % (len(client.last_payload) / 1024.0),
                )
            )
    if not args.skip_media:
        for name, call in media_workloads(client):
            result = harness.measure(call, max(5, args.repeat // 5), 2)
            rows.append(
                (
                    name,
                    "-",
                    "%.3f" % result.p50,
                    "%.3f" % result.p95,
                    "%.0f" % result.per_sec,
                    "%.1f" % (len(client.last_payload) / 1024.0),
                )
            )
    harness.table(
        ["workload", "points", "p50 ms", "p95 ms", "calls/s", "payload KB"], rows
    )


if __name__ == "__main__":
    main()
