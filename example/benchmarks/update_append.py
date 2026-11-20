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

``--breakdown`` attributes that cost to the operations the append actually
reaches, by timing them in place; ``--server`` measures the same append
end-to-end against a running server.

    python example/benchmarks/update_append.py
    python example/benchmarks/update_append.py --breakdown
    python example/benchmarks/update_append.py --server --port 8097
"""

import contextlib
import json
import time
from unittest.mock import patch

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
            breakdowns.append(
                (n_points, breakdown_rows(handler, pane, append, n_points, args))
            )
    harness.table(["points", "p50 ms", "p95 ms", "appends/s", "pane KB"], rows)
    for n_points, operations in breakdowns:
        print("\nbreakdown at %d points -- mean cost of one append" % n_points)
        harness.table(["operation", "calls", "ms", "share"], operations)


class OpTimer:
    """Times named operations wherever the code under test calls them.

    The breakdown used to call ``stringify``, ``make_patch`` and the rest
    directly, on a pane of the right size. That answers "what do these
    operations cost", which is not the same question as "what does an append
    spend": it prints a row for an operation whether or not the handler still
    reaches it, so a commit that takes a call off the update path reports an
    unchanged breakdown. These wrappers go on the attributes ``wrap_func``
    resolves instead, so an operation is timed only when it is actually
    called, with the arguments it is actually called with, and one that is no
    longer on the path reports zero calls and no time.
    """

    def __init__(self):
        # ``label -> [calls, milliseconds]``, in registration order, which is
        # the order the rows print in.
        self.records = {}

    def wrap(self, label, func):
        record = self.records.setdefault(label, [0, 0.0])

        def timed(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                record[0] += 1
                record[1] += (time.perf_counter() - start) * 1000.0

        return timed

    def reset(self):
        for record in self.records.values():
            record[0], record[1] = 0, 0.0


class ModuleProxy:
    """Stands in for a module, with some of its functions timed.

    ``web_handlers`` reaches ``json.dumps``, ``copy.deepcopy`` and
    ``jsonpatch.make_patch`` through the module objects it imported, so a
    wrapper meant for that one caller has to replace the module rather than
    the function -- patching ``json.dumps`` itself would also time the copies
    ``stringify`` makes internally, and then the shares would double-count.
    Every other attribute falls through to the real module.
    """

    def __init__(self, module, wrapped):
        self._module = module
        for name, func in wrapped.items():
            setattr(self, name, func)

    def __getattr__(self, name):
        return getattr(self._module, name)


def instrumented(timer):
    """Patches putting ``timer`` on the operations an append runs.

    One entry per operation the update path is expected to reach, so a size
    column of zeros is a finding rather than a missing row.
    """
    from visdom.server.handlers import web_handlers

    def proxy(module, name, label):
        return ModuleProxy(module, {name: timer.wrap(label, getattr(module, name))})

    return [
        patch.object(
            web_handlers, "stringify", timer.wrap("stringify", web_handlers.stringify)
        ),
        patch.object(
            web_handlers, "copy", proxy(web_handlers.copy, "deepcopy", "deepcopy")
        ),
        patch.object(
            web_handlers,
            "jsonpatch",
            proxy(web_handlers.jsonpatch, "make_patch", "make_patch"),
        ),
        patch.object(
            web_handlers,
            "json",
            proxy(web_handlers.json, "dumps", "broadcast encode"),
        ),
    ]


def breakdown_rows(handler, pane, append, n_points, args):
    """Attribute one append's cost to the operations it reaches.

    Runs the same ``wrap_func`` the table above times, with the operations
    wrapped, and divides each total by the iteration count. Timing in place
    costs a pair of ``perf_counter`` calls per operation, so the accounted
    total here runs a shade above the uninstrumented ``p50``; the share column
    is what to read, and ``unattributed`` is the handler's own work plus that
    overhead.
    """
    from visdom.server.handlers.web_handlers import UpdateHandler

    repeat = max(10, args.repeat // 10)

    def call():
        UpdateHandler.wrap_func(handler, append)

    def setup():
        harness.truncate_traces(pane, n_points)

    timer = OpTimer()
    with contextlib.ExitStack() as stack:
        for patcher in instrumented(timer):
            stack.enter_context(patcher)
        for _ in range(args.warmup):
            setup()
            call()
        # The warmup ran through the same wrappers. Drop it, so ``calls`` is
        # per append and the attributed time covers ``repeat`` appends.
        timer.reset()
        result = harness.measure(call, repeat, setup=setup)

    per_append = result.mean

    def row(label, calls, milliseconds):
        share = "%.0f%%" % (100.0 * milliseconds / per_append) if per_append else "-"
        return (label, calls, "%.3f" % milliseconds, share)

    rows, attributed = [], 0.0
    for label, (calls, milliseconds) in timer.records.items():
        attributed += milliseconds
        rows.append(row(label, "%g" % (calls / repeat), milliseconds / repeat))
    rows.append(row("unattributed", "-", per_append - attributed / repeat))
    rows.append(row("one append", "1", per_append))
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
        # ``--traces n`` has to shape the pane here too, or the row would be
        # labelled with a trace count only the in-process path ever honoured.
        # Visdom reads a column per trace out of a two-dimensional ``Y``.
        if args.traces > 1:
            y = np.column_stack([y + offset for offset in range(args.traces)])
        win = client.line(X=x, Y=y, env="benchmark")
        tip = np.array([float(n_points)])
        tip_y = np.full((1, args.traces), 0.5) if args.traces > 1 else np.array([0.5])

        def append(win=win, tip=tip, tip_y=tip_y):
            client.line(X=tip, Y=tip_y, win=win, env="benchmark", update="append")

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
