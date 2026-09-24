#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Timing loop and fixtures shared by the benchmarks here. See README.md."""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

# A benchmark compares two commits of *this* checkout, so prefer the sibling
# ``py/`` tree over whatever ``visdom`` happens to be installed in the
# environment -- an editable install may well point somewhere else entirely.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "py"))

DEFAULT_SIZES = "500,4000,20000"


def positive_int(value):
    """An ``argparse`` type that rejects zero and negative counts.

    ``--repeat 0`` would otherwise reach ``Result`` with no samples at all,
    where ``statistics.median`` raises and ``p95`` indexes an empty list. That
    surfaces as a traceback out of the reporting code rather than a word about
    the argument that caused it.
    """
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected an integer, got %r" % value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer, got %r" % value)
    return number


def non_negative_int(value):
    """Like ``positive_int``, except that no warmup at all is a valid ask."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected an integer, got %r" % value)
    if number < 0:
        raise argparse.ArgumentTypeError("expected zero or more, got %r" % value)
    return number


def size_list(value):
    """Parse ``--sizes`` into positive ints.

    A zero or negative size reaches the client fixture and trips an assertion
    inside ``Visdom.line``, which has no array to plot; rejecting it here names
    the argument instead of failing several frames deeper.
    """
    sizes = [positive_int(chunk) for chunk in value.split(",") if chunk.strip()]
    if not sizes:
        raise argparse.ArgumentTypeError("expected at least one size")
    return sizes


def arg_parser(description, sizes=DEFAULT_SIZES, repeat=200):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--sizes", type=size_list, default=sizes, help="comma-separated sizes"
    )
    parser.add_argument(
        "--repeat", type=positive_int, default=repeat, help="timed calls"
    )
    parser.add_argument(
        "--warmup", type=non_negative_int, default=20, help="untimed calls"
    )
    return parser


def parse_sizes(args):
    """The parsed ``--sizes``. ``size_list`` already validated and split it."""
    return args.sizes


class Result:
    """Per-call durations, in milliseconds."""

    def __init__(self, samples):
        if not samples:
            raise ValueError("no samples to summarise")
        self.samples = sorted(samples)

    @property
    def p50(self):
        return statistics.median(self.samples)

    @property
    def p95(self):
        return self.samples[int(round(0.95 * (len(self.samples) - 1)))]

    @property
    def per_sec(self):
        return 1000.0 / self.p50 if self.p50 else float("inf")


def measure(call, repeat, warmup=0, setup=None):
    """Time ``call``, running ``setup`` untimed before each iteration.

    ``setup`` is how a benchmark whose call mutates its own fixture keeps every
    iteration the same size: the append benchmark truncates the trace back to
    ``n`` points there, so the last timed append costs what the first did.
    Every call that appends needs one, over HTTP as much as in process --
    without it the pane carries ``warmup`` plus every prior timed append, and
    the row is labelled with a size only its first sample ever saw.
    """
    if repeat < 1:
        raise ValueError("repeat must be at least 1, got %r" % repeat)
    if warmup < 0:
        raise ValueError("warmup cannot be negative, got %r" % warmup)
    samples = []
    for i in range(warmup + repeat):
        if setup is not None:
            setup()
        start = time.perf_counter()
        call()
        elapsed = (time.perf_counter() - start) * 1000.0
        if i >= warmup:
            samples.append(elapsed)
    return Result(samples)


def table(headers, rows):
    """Print a markdown table, ready to paste into a PR body."""
    cells = [[str(value) for value in row] for row in rows]
    widths = [
        max([len(header)] + [len(row[i]) for row in cells])
        for i, header in enumerate(headers)
    ]

    def line(values):
        padded = (value.ljust(width) for value, width in zip(values, widths))
        return "| " + " | ".join(padded) + " |"

    print(line(headers))
    print("|" + "|".join("-" * (width + 2) for width in widths) + "|")
    for row in cells:
        print(line(row))


def offline_client(**kwargs):
    """A ``Visdom`` client with its transport removed.

    ``Visdom(send=False)`` no longer exists, so the transport goes away by
    replacing ``_handle_post``. Everything above it stays inside the
    measurement, including the ``NanSafeEncoder`` pass ``_send`` runs over the
    finished payload, and the payload itself is kept on ``last_payload`` as the
    raw string so capturing it costs an assignment rather than a decode.
    """
    import visdom

    with (
        patch.object(visdom.Visdom, "_handle_post", return_value=True),
        patch.object(visdom.Visdom, "_start_session_reaper"),
        patch.object(visdom.logger, "warning"),
    ):
        client = visdom.Visdom(use_incoming_socket=False, **kwargs)

    def handle_post(url, data=None):
        client.last_payload = data
        return True

    client.last_payload = None
    client._handle_post = handle_post
    return client


class StubHandler:
    """Carries the attributes a ``web_handlers`` wrap function reads.

    Handlers copy what they need off the application in ``initialize()``
    instead of reaching through ``self.app``, so a wrap function runs against
    any object that has those names -- the property that lets
    ``py/tests/testutils/fakes.py`` drive them without a Tornado request. The
    handler is its own subscriber, so the broadcast encode is paid here as it
    is in production.
    """

    def __init__(self, eid="main"):
        from visdom.server import defaults

        self.state = {}
        self.subs = {"sub_0": self}
        self.sources = {}
        self.eid = eid
        self.broadcast_bytes = 0
        self.max_text_lines = defaults.DEFAULT_MAX_TEXT_LINES
        self.max_old_content = defaults.DEFAULT_MAX_OLD_CONTENT
        self.max_image_history = defaults.DEFAULT_MAX_IMAGE_HISTORY
        self.max_plot_history = defaults.DEFAULT_MAX_PLOT_HISTORY

    def mark_dirty(self, eid):
        pass

    def set_status(self, code, reason=None):
        pass

    def write(self, chunk):
        pass

    def write_message(self, msg):
        self.broadcast_bytes += len(msg)


def line_payloads(n_points, traces=1, win="bench_win", env="main"):
    """The two payloads a client posts to plot ``n_points`` and append one.

    Built with the real client so the pane under test is the pane the server
    really stores, down to the marker dict and the derived layout.
    """
    import numpy as np

    client = offline_client(env=env)
    x = np.arange(n_points, dtype=np.float64)
    y = np.sin(x / 50.0)
    if traces > 1:
        y = np.column_stack([y + offset for offset in range(traces)])
    client.line(X=x, Y=y, win=win, env=env)
    create = json.loads(client.last_payload)

    tip = np.array([float(n_points)])
    client.line(
        X=tip,
        Y=np.full((1, traces), 0.5) if traces > 1 else np.array([0.5]),
        win=win,
        env=env,
        update="append",
    )
    return create, json.loads(client.last_payload)


def register_pane(handler, create, eid="main"):
    """Turn a create payload into a stored pane, as ``/events`` would."""
    from visdom.utils.server_utils import window

    pane = window(create)
    handler.state.setdefault(eid, {"jsons": {}, "reload": {}})
    handler.state[eid]["jsons"][pane["id"]] = pane
    return pane


def truncate_traces(pane, n_points):
    """Drop everything appended past ``n_points``, so a run does not drift."""
    for trace in pane["content"]["data"]:
        for axis in ("x", "y", "z"):
            if isinstance(trace.get(axis), list):
                del trace[axis][n_points:]
        color = trace.get("marker", {}).get("color")
        if isinstance(color, list):
            del color[n_points:]
