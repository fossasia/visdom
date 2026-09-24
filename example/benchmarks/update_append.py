#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""How much does the server spend appending one point to a line plot?

This is the benchmark behind issues #1805 and #695. It times one whole
``/update`` append -- ``UpdateHandler.wrap_func``, so the diff, the
smaller-of-patch-or-pane comparison and the broadcast encode are all included
-- against a pane that already holds ``n`` points, for several ``n``.

``--breakdown`` attributes that cost to the individual operations on the path;
``--server`` measures the same append end-to-end against a running server.

    python example/benchmarks/update_append.py
    python example/benchmarks/update_append.py --breakdown
    python example/benchmarks/update_append.py --server --port 8097
"""

import copy
import json

import _harness as harness


def fixture(n_points, traces):
    """A registered pane of ``n_points`` per trace, and one append's args."""
    create, append = harness.line_payloads(n_points, traces=traces)
    handler = harness.StubHandler()
    return handler, harness.register_pane(handler, create), append


def measure_append(args):
    from visdom.server.handlers.web_handlers import UpdateHandler

    rows, breakdowns = [], []
    for n_points in harness.parse_sizes(args):
        handler, pane, append = fixture(n_points, args.traces)
        result = harness.measure(
            lambda: UpdateHandler.wrap_func(handler, append),
            args.repeat,
            args.warmup,
            setup=lambda: harness.truncate_traces(pane, n_points),
        )
        rows.append(
            (
                n_points,
                "%.3f" % result.p50,
                "%.3f" % result.p95,
                "%.0f" % result.per_sec,
                "%.1f" % (len(json.dumps(pane)) / 1024.0),
            )
        )
        if args.breakdown:
            breakdowns.append((n_points, breakdown_rows(pane, n_points, args)))
    harness.table(["points", "p50 ms", "p95 ms", "appends/s", "pane KB"], rows)
    for n_points, operations in breakdowns:
        print("\nbreakdown at %d points" % n_points)
        harness.table(["operation", "p50 ms"], operations)


def breakdown_rows(pane, n_points, args):
    """Time the individual operations one append runs, on a pane this size."""
    import jsonpatch

    from visdom.utils.server_utils import recursive_order, stringify

    harness.truncate_traces(pane, n_points)
    repeat = max(10, args.repeat // 10)

    def timed(call):
        return "%.3f" % harness.measure(call, repeat, 2).p50

    rows = [
        ("stringify", timed(lambda: stringify(pane))),
        ("json.dumps", timed(lambda: json.dumps(pane))),
        ("recursive_order", timed(lambda: recursive_order(pane))),
        ("deepcopy(content)", timed(lambda: copy.deepcopy(pane["content"]))),
    ]

    # Built only now: a second live copy of a multi-MB pane changes what the
    # measurements above cost, by way of the garbage collector.
    old = {"contentID": pane["contentID"], "content": copy.deepcopy(pane["content"])}
    new = {"contentID": "new", "content": pane["content"]}
    for trace in new["content"]["data"]:
        trace["x"].append(float(n_points))
        trace["y"].append(0.5)
    rows.append(("make_patch", timed(lambda: jsonpatch.make_patch(old, new))))
    return rows


def measure_server(args):
    """End-to-end appends/s against a server that is already running."""
    import numpy as np
    import visdom

    client = visdom.Visdom(port=args.port, env="benchmark", use_incoming_socket=False)
    if not client.check_connection():
        raise SystemExit("no visdom server answering on port %d" % args.port)

    rows = []
    for n_points in harness.parse_sizes(args):
        x = np.arange(n_points, dtype=np.float64)
        y = np.sin(x / 50.0)
        win = client.line(X=x, Y=y, env="benchmark")
        tip = np.array([float(n_points)])

        def append(win=win, tip=tip):
            client.line(X=tip, Y=tip, win=win, env="benchmark", update="append")

        # The pane lives on the server and every append grows it, so without a
        # reset the row labelled ``n_points`` would measure a pane that ends at
        # ``n_points + warmup + repeat``. Re-plotting the whole trace replaces
        # the stored pane outright, which is the over-HTTP equivalent of the
        # ``truncate_traces`` the in-process path uses, and it stays outside
        # the timed call.
        def reset(win=win, x=x, y=y):
            client.line(X=x, Y=y, win=win, env="benchmark")

        result = harness.measure(append, args.repeat, args.warmup, setup=reset)
        rows.append(
            (
                n_points,
                "%.3f" % result.p50,
                "%.3f" % result.p95,
                "%.0f" % result.per_sec,
            )
        )
    harness.table(["points", "p50 ms", "p95 ms", "appends/s"], rows)


def main():
    parser = harness.arg_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--traces", type=harness.positive_int, default=1, help="traces in the pane"
    )
    parser.add_argument("--breakdown", action="store_true", help="time the pieces")
    parser.add_argument("--server", action="store_true", help="drive a live server")
    parser.add_argument(
        "--port", type=harness.positive_int, default=8097, help="port for --server"
    )
    args = parser.parse_args()
    if args.server:
        measure_server(args)
    else:
        measure_append(args)


if __name__ == "__main__":
    main()
