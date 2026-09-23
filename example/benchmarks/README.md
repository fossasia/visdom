<!-- Copyright 2017-present, The Visdom Authors
     All rights reserved.

     This source code is licensed under the license found in the
     LICENSE file in the root directory of this source tree. -->

# Benchmarks

Scripts here answer **"how fast is it, and does that change with the size of
the data already plotted?"** They are not tests: pytest does not collect them
(`testpaths` is `py/tests`) and nothing in CI runs them.

They exist because performance claims about visdom have historically been made
from scripts that were never checked in, so nobody could reproduce or extend
them. A number produced here can be re-run on any two commits.

| Script | Question |
|---|---|
| `update_append.py` | What does the server spend appending one point to a plot? |
| `payload_build.py` | What does the Python client spend building one payload? |
| `encode.py` | What do `NanSafeEncoder` and `stringify` cost over `json.dumps`? |

```bash
python example/benchmarks/update_append.py
python example/benchmarks/update_append.py --breakdown
python example/benchmarks/payload_build.py
python example/benchmarks/encode.py
```

Each accepts `--sizes` (comma-separated workload sizes), `--repeat` (timed
calls per size) and `--warmup` (untimed calls first). `--breakdown` uses a
tenth of `--repeat`, since it times five operations per size.

## How they measure

**In-process, by default.** The client's `_handle_post` and the server's
Tornado request are stubbed out, so what is timed is visdom's own Python work.
A number measured across a socket is dominated by the socket; the costs these
scripts track are CPU costs that grow with the plot, and they stay invisible
end-to-end until they are already large. `_harness.py` holds the timing loop
(`time.perf_counter`, p50 and p95 over sorted per-call samples) and the
fixtures, and it puts this checkout's `py/` ahead of any installed `visdom` so
that comparing two commits compares the two commits.

`update_append.py --server` is the exception: it drives a server that is
already running, over HTTP, for the end-to-end figure.

```bash
python -m visdom.server -port 8097            # in one shell
python example/benchmarks/update_append.py --server --port 8097
```

## Reading the output

Output is a markdown table, so it can be pasted straight into a PR body.

**The shape matters more than the absolute numbers.** Appending one point is
O(1) work, so a `p50 ms` column that climbs with `points` means a training run
costs time quadratic in its own length — which is what issues
[#1805](https://github.com/fossasia/visdom/issues/1805) and
[#695](https://github.com/fossasia/visdom/issues/695) describe from opposite
ends. Absolute milliseconds move with the machine; the growth does not.

For the same reason, the regression tests in `py/tests/` assert *shape* —
which functions an append calls, and that the work at 4,000 points matches the
work at 500 — never wall-clock time. CI runners are shared and noisy, and a
`assert elapsed < x` on a two-version matrix fails at random.

Small-payload client numbers are a floor, not a cost: a one-point append costs
the client far less than the wire it is about to cross. Client CPU matters for
large arrays, for media encodes, and under `AsyncVisdom`, where it is
GIL-serialised across the bridge's threads.
