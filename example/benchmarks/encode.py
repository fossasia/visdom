#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""What do visdom's two JSON passes cost over a plain ``json.dumps``?

Both run on the hot path and both are charged per byte of the pane:

* ``NanSafeEncoder`` encodes every byte the server broadcasts, every window it
  hands back and every env file it writes, and the client encodes every
  payload with it too.
* ``stringify`` is called twice per ``/update`` purely to compare the length of
  the patch against the length of the pane. Its ``recursive_order`` pass sorts
  every mapping in the payload recursively before encoding it.

The ratio column is what an optimisation on either pass has to beat, and it
should stay flat as the pane grows.

    python example/benchmarks/encode.py
"""

import json

import _harness as harness


def encoders(pane):
    from visdom.utils.server_utils import stringify
    from visdom.utils.shared_utils import NanSafeEncoder

    compact = {"separators": (",", ":")}
    return [
        ("json.dumps", lambda: json.dumps(pane), None),
        ("NanSafeEncoder", lambda: json.dumps(pane, cls=NanSafeEncoder), "json.dumps"),
        ("json.dumps compact", lambda: json.dumps(pane, **compact), None),
        ("stringify", lambda: stringify(pane), "json.dumps compact"),
    ]


def main():
    args = harness.arg_parser(__doc__.splitlines()[0], repeat=50).parse_args()

    rows = []
    for n_points in harness.parse_sizes(args):
        create, _ = harness.line_payloads(n_points)
        pane = harness.register_pane(harness.StubHandler(), create)
        baselines = {}
        for name, call, baseline in encoders(pane):
            result = harness.measure(call, args.repeat, args.warmup)
            baselines[name] = result.p50
            ratio = "-"
            if baseline is not None and baselines[baseline]:
                ratio = "%.1fx" % (result.p50 / baselines[baseline])
            rows.append(
                (n_points, name, "%.3f" % result.p50, "%.3f" % result.p95, ratio)
            )
    harness.table(["points", "encoder", "p50 ms", "p95 ms", "vs baseline"], rows)


if __name__ == "__main__":
    main()
