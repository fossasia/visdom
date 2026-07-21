#!/usr/bin/env python3
"""
Micro-benchmark for UpdateHandler.update_packet hot paths.

Usage:
  python py/tests/bench_update_packet.py --iterations 20000
"""

import argparse
import copy
import time

from visdom.server.handlers.web_handlers import UpdateHandler


def _bench_text(iters):
    pane_template = {"id": "w1", "type": "text", "content": "line", "contentID": "old"}
    args = {"data": [{"content": "next"}]}
    start = time.perf_counter()
    for _ in range(iters):
        pane = copy.deepcopy(pane_template)
        UpdateHandler.update_packet(pane, args, 200, 50, 50)
    return time.perf_counter() - start


def _bench_image_select(iters):
    pane_template = {
        "id": "w2",
        "type": "image_history",
        "content": [{"v": 1}, {"v": 2}],
        "selected": 0,
        "contentID": "old",
    }
    args = {"data": [{"type": "image_update_selected", "selected": 1}]}
    start = time.perf_counter()
    for _ in range(iters):
        pane = copy.deepcopy(pane_template)
        UpdateHandler.update_packet(pane, args, 200, 50, 50)
    return time.perf_counter() - start


def _bench_plot_append(iters):
    pane_template = {
        "id": "w3",
        "type": "plot_history",
        "content": [{"x": [1], "y": [2]}],
        "selected": 0,
        "contentID": "old",
    }
    args = {"data": [{"type": "plot_history", "content": {"x": [2], "y": [3]}}]}
    start = time.perf_counter()
    for _ in range(iters):
        pane = copy.deepcopy(pane_template)
        UpdateHandler.update_packet(pane, args, 200, 50, 50)
    return time.perf_counter() - start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=20000)
    args = parser.parse_args()

    results = {
        "text": _bench_text(args.iterations),
        "image_update_selected": _bench_image_select(args.iterations),
        "plot_history_append": _bench_plot_append(args.iterations),
    }

    print(f"iterations={args.iterations}")
    for name, elapsed in results.items():
        ops_per_sec = args.iterations / elapsed if elapsed > 0 else float("inf")
        print(f"{name:24} {elapsed:.4f}s  ({ops_per_sec:,.0f} ops/s)")


if __name__ == "__main__":
    main()
