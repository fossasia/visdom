#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Which message ``POST /update`` broadcasts, and what it costs to decide.

``UpdateHandler.wrap_func`` can announce a change two ways: ``window`` carries
the whole pane, ``window_update`` carries a JSON patch the frontend applies to
its own copy (``js/main.js``). Either leaves the browser in the same state, so
picking between them is a bandwidth heuristic -- and the cost of *deciding* must
not grow with the data already plotted, which is what issues #1805 and #695
describe from opposite ends.

The assertions here are on shape, never wall-clock: which messages go out, how
many encodes it took, and that an append's decision costs the same at 1,000
points as at 10. See ``example/benchmarks/README.md`` for why timing assertions
do not belong in CI.
"""

import json

import pytest

from visdom.server.handlers import web_handlers
from visdom.server.handlers.web_handlers import UpdateHandler
from visdom.utils.server_utils import window, NanSafeEncoder

from testutils.fakes import FakeHandler
from testutils.payloads import plot_data, window_args

pytestmark = pytest.mark.unit


def make_pane(handler, n_points, win="win_0", eid="main"):
    """Register a scatter pane holding ``n_points`` per trace, as /events would."""
    xs = [float(i) for i in range(n_points)]
    ys = [i * 1.5 + 0.25 for i in range(n_points)]
    args = window_args(data=[plot_data(x=xs, y=ys)], win=win)
    pane = window(args)
    handler.state.setdefault(eid, {"jsons": {}, "reload": {}})
    handler.state[eid]["jsons"][pane["id"]] = pane
    return pane


def append_args(win="win_0", eid="main", x=99.0, y=42.5):
    """The args a client posts to append one point to trace 0."""
    return {
        "win": win,
        "eid": eid,
        "data": [{"type": "scatter", "x": [x], "y": [y]}],
        "append": True,
    }


def counting_dumps(monkeypatch):
    """Replace ``web_handlers.json.dumps`` with a counting passthrough.

    Returns the list it records each encoded object into, so a test can assert
    how many times the update path serialised something and how big each one
    was.
    """
    real_dumps = json.dumps
    calls = []

    def spy(obj, *args, **kwargs):
        out = real_dumps(obj, *args, **kwargs)
        calls.append(out)
        return out

    monkeypatch.setattr(web_handlers.json, "dumps", spy)
    return calls


def test_append_broadcasts_a_patch():
    handler = FakeHandler()
    sub = handler.add_sub()
    make_pane(handler, 50)

    UpdateHandler.wrap_func(handler, append_args())

    msg = sub.last()
    assert msg["command"] == "window_update"
    assert msg["win"] == "win_0"
    assert msg["eid"] == "main"


def test_append_patch_carries_the_new_point():
    handler = FakeHandler()
    sub = handler.add_sub()
    make_pane(handler, 10)

    UpdateHandler.wrap_func(handler, append_args(x=99.0, y=42.5))

    ops = sub.last("window_update")["content"]
    added = [op for op in ops if op["op"] == "add"]
    assert {"path": "/content/data/0/x/10", "value": 99.0} in [
        {"path": op["path"], "value": op["value"]} for op in added
    ]
    assert {"path": "/content/data/0/y/10", "value": 42.5} in [
        {"path": op["path"], "value": op["value"]} for op in added
    ]


def test_append_broadcast_does_not_grow_with_the_plot():
    """A 100x larger plot produces a near-identical append broadcast.

    The patch is not byte-identical across sizes -- the JSON Pointer it carries
    gains a digit as the index does (``/x/10`` -> ``/x/1000``) -- so the
    invariant is that it tracks the index's digit count and not the data. A pane
    encode leaking back onto this path would show up here as a message growing
    in step with the pane, which is the #1805 regression in one assertion.
    """
    sizes = (10, 100, 1000)
    messages, panes = [], []
    for n_points in sizes:
        handler = FakeHandler()
        sub = handler.add_sub()
        pane = make_pane(handler, n_points)
        UpdateHandler.wrap_func(handler, append_args())
        assert sub.last()["command"] == "window_update"
        messages.append(len(sub.messages[-1]))
        panes.append(len(json.dumps(pane)))

    assert max(messages) - min(messages) <= 8, dict(zip(sizes, messages))
    # At the largest size the patch is shorter than the pane's lower bound, so
    # the pane encode was skipped outright rather than merely losing.
    assert messages[-1] < UpdateHandler.pane_min_bytes(pane)
    # The pane really did grow by two orders of magnitude over that range, so
    # the flat broadcast above is evidence rather than a small-input artefact.
    assert panes[-1] > 20 * panes[0]


def test_append_encodes_exactly_once(monkeypatch):
    """One append, one serialisation -- the pane is never encoded to measure it."""
    handler = FakeHandler()
    handler.add_sub()
    make_pane(handler, 1000)
    calls = counting_dumps(monkeypatch)

    UpdateHandler.wrap_func(handler, append_args())

    assert len(calls) == 1
    assert json.loads(calls[0])["command"] == "window_update"


def test_small_pane_beats_a_patch_that_is_small_in_absolute_terms(monkeypatch):
    """A compact pane wins even when the patch it beats is only a few hundred bytes.

    Rewriting every point of a short trace yields a patch that is longer than
    the whole pane while still looking cheap by any absolute byte count. A
    threshold on the patch's own size would ship the larger message here; the
    pane's lower bound is below the patch, so the comparison runs and the pane
    wins. Both encodes happen, and both are O(a handful of points).
    """
    handler = FakeHandler()
    sub = handler.add_sub()
    n_points = 20
    make_pane(handler, n_points)
    calls = counting_dumps(monkeypatch)

    xs = [float(i) + 0.5 for i in range(n_points)]
    ys = [i * 1.7 + 0.3 for i in range(n_points)]
    UpdateHandler.wrap_func(
        handler,
        {
            "win": "win_0",
            "eid": "main",
            "data": [{"type": "scatter", "x": xs, "y": ys}],
        },
    )

    assert sub.last()["command"] == "window"
    patch_msg, pane_msg = calls
    assert json.loads(patch_msg)["command"] == "window_update"
    assert len(pane_msg) < len(patch_msg) < 4096


def test_full_replacement_broadcasts_the_pane():
    """A patch larger than the pane still loses: the heuristic is intact."""
    handler = FakeHandler()
    sub = handler.add_sub()
    n_points = 1000
    make_pane(handler, n_points)

    # Every point changes, so jsonpatch emits a replace op per element and the
    # patch comes out several times the size of the pane it describes.
    xs = [float(i) + 0.5 for i in range(n_points)]
    ys = [i * 1.7 + 0.3 for i in range(n_points)]
    UpdateHandler.wrap_func(
        handler,
        {
            "win": "win_0",
            "eid": "main",
            "data": [{"type": "scatter", "x": xs, "y": ys}],
        },
    )

    msg = sub.last()
    assert msg["command"] == "window"
    assert msg["eid"] == "main"
    assert msg["content"]["data"][0]["y"][0] == pytest.approx(0.3)


@pytest.mark.parametrize(
    "trace",
    [
        pytest.param({"type": "scatter", "x": [], "y": []}, id="empty"),
        pytest.param({"type": "scatter", "x": [0.0], "y": [1.0]}, id="one-point"),
        pytest.param(
            {"type": "scatter", "x": [float(i) for i in range(500)], "y": [1.5] * 500},
            id="floats",
        ),
        pytest.param(
            {"type": "scatter", "x": [None] * 50, "y": [None] * 50}, id="nulls"
        ),
        pytest.param({"type": "scatter", "x": [""] * 50, "y": [""] * 50}, id="strings"),
        pytest.param(
            {"type": "scatter", "x": [float("nan")] * 50, "y": [1.0] * 50}, id="nans"
        ),
        pytest.param(
            {"type": "surface", "z": [[0.0] * 3 for _ in range(50)]}, id="nested"
        ),
    ],
)
def test_pane_min_bytes_never_exceeds_the_real_encoding(trace):
    """The bound must understate, or a pane that would have won gets skipped.

    Everything the skip decision rests on is here: if any element type could
    encode to fewer characters than the bound allows for it, the broadcast
    could pick the larger message without ever comparing.
    """
    pane = window(window_args(data=[trace], win="win_0"))
    broadcast_msg = dict(pane)
    broadcast_msg["eid"] = "main"
    encoded = json.dumps(broadcast_msg, cls=NanSafeEncoder)

    assert UpdateHandler.pane_min_bytes(pane) <= len(encoded)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("<h1>a text pane</h1>", id="text"),
        pytest.param(["not", "a", "trace", "dict"], id="list"),
        pytest.param(None, id="none"),
        pytest.param({"src": "data:image/png;base64,iVBOR"}, id="image"),
        pytest.param({"data": "not a list"}, id="data-not-a-list"),
        pytest.param({"data": ["not a trace dict"]}, id="trace-not-a-dict"),
    ],
)
def test_pane_min_bytes_handles_panes_without_traces(content):
    """Not every pane is a plot, and the bound is asked for before we know.

    Text, HTML and image panes reach the same broadcast decision, so a bound
    that assumed ``content`` was a dict of traces would turn every update to
    one of them into a 500.
    """
    assert UpdateHandler.pane_min_bytes({"content": content}) == 0


def test_window_update_message_matches_what_is_broadcast():
    """The extracted encoder produces exactly the bytes the broadcast sends."""
    handler = FakeHandler()
    sub = handler.add_sub()
    pane = make_pane(handler, 10)
    diff_packet = [{"op": "replace", "path": "/contentID", "value": "abc"}]
    args = {"win": pane["id"], "eid": "main"}

    UpdateHandler.broadcast_window_update(handler, args, "main", pane, diff_packet)

    assert sub.messages[-1] == UpdateHandler.window_update_message(
        args, "main", pane, diff_packet
    )


def test_update_still_reports_the_window_id_and_marks_dirty():
    handler = FakeHandler()
    handler.add_sub()
    pane = make_pane(handler, 10)

    UpdateHandler.wrap_func(handler, append_args())

    assert handler.body == pane["id"]
    assert handler.dirtied == ["main"]
