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

import copy
import json

import jsonpatch
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


# --------------------------------------------------------------------------
# Building the append patch directly (#1805)
# --------------------------------------------------------------------------

CAPS = (500, 50, 4, 4)
FIXED_ID = "<content-id>"


def diffed_update_packet(p, args):
    """``update_packet`` as it worked before the append patch was built directly.

    Every claim about the direct patch is checked against this rather than
    against a description of it, so the comparison is with the behaviour that
    actually shipped: deepcopy the pane, mutate it, bump the version, hand both
    copies to ``jsonpatch``. The bump sits where ``update_packet`` puts it --
    after the mutation and before the diff, so the patch carries the new value
    (#1775) -- because a mirror that skipped it would report every version
    difference as a disagreement about the data.
    """
    old_p = p.copy()
    if "content" in p:
        old_p["content"] = copy.deepcopy(p["content"])
    if "old_content" in p:
        old_p["old_content"] = copy.deepcopy(p["old_content"])
    p = UpdateHandler.update(p, args, *CAPS)
    UpdateHandler.bump_version(p)
    p["contentID"] = FIXED_ID
    return p, jsonpatch.make_patch(old_p, p).patch


def comparable(ops):
    """Ops as an order-independent set, with the random content id pinned.

    ``jsonpatch`` diffs dict keys through a ``set``, so the *order* it emits
    ops in moves with ``PYTHONHASHSEED``. Asserting the patches are
    byte-identical would therefore be flaky by construction; asserting they
    carry the same ops, and that applying either yields the same document, is
    deterministic and says more about the content.
    """
    pinned = [
        dict(op, value=FIXED_ID) if op["path"] == "/contentID" else op for op in ops
    ]
    return sorted(json.dumps(op, sort_keys=True) for op in pinned)


def plot_pane(
    trace_type="scatter",
    traces=1,
    marker=False,
    names=None,
    n_points=12,
    layout=None,
):
    """A stored plot pane, built the way ``/events`` builds one."""
    data = []
    for index in range(traces):
        trace = plot_data(
            trace_type=trace_type,
            x=[float(i) for i in range(n_points)],
            y=[i * 1.5 for i in range(n_points)],
            name=names[index] if names else None,
        )
        if trace_type == "scatter3d":
            trace["z"] = [i * 2.0 for i in range(n_points)]
        if marker:
            trace["marker"] = {"color": ["#%06x" % (i * 11) for i in range(n_points)]}
        data.append(trace)
    return window(window_args(data=data, win="win_0", layout=layout))


def heatmap_pane(rows=3, cols=2):
    """A stored heatmap pane. Its ``z`` is a grid, which no append can predict."""
    trace = {
        "type": "heatmap",
        "z": [[float(r * cols + c) for c in range(cols)] for r in range(rows)],
        "x": ["c%d" % c for c in range(cols)],
        "y": ["r%d" % r for r in range(rows)],
    }
    return window(window_args(data=[trace], win="win_0"))


def trace_append_args(
    trace_type="scatter", traces=1, marker=False, n_points=1, name=None, **extra
):
    """The args a client posts to append ``n_points`` to each of ``traces``."""
    data = []
    for _ in range(traces):
        entry = {
            "type": trace_type,
            "x": [100.0 + j for j in range(n_points)],
            "y": [200.0 + j for j in range(n_points)],
        }
        if trace_type == "scatter3d":
            entry["z"] = [300.0 + j for j in range(n_points)]
        if marker:
            entry["marker"] = {"color": ["#abcdef"] * n_points}
        data.append(entry)
    args = {"win": "win_0", "eid": "main", "data": data, "append": True, "name": name}
    args.update(extra)
    return args


def assert_patches_agree(pane, args):
    """The direct patch and the diffed patch describe the same change.

    Three assertions, because any one of them alone would let a real bug
    through: the mutated panes match, the ops match as sets, and applying
    either patch to the pane as it was reproduces the mutated pane. The last
    one is what the frontend actually does with the message.
    """
    before = copy.deepcopy(pane)
    direct_pane, direct_ops = UpdateHandler.update_packet(
        copy.deepcopy(pane), copy.deepcopy(args), *CAPS
    )
    direct_pane["contentID"] = FIXED_ID
    diffed_pane, diffed_ops = diffed_update_packet(
        copy.deepcopy(pane), copy.deepcopy(args)
    )

    assert direct_pane == diffed_pane
    assert comparable(direct_ops) == comparable(diffed_ops)
    applied_direct = jsonpatch.apply_patch(copy.deepcopy(before), direct_ops)
    applied_diffed = jsonpatch.apply_patch(copy.deepcopy(before), diffed_ops)
    applied_direct["contentID"] = FIXED_ID
    applied_diffed["contentID"] = FIXED_ID
    assert applied_direct == applied_diffed == direct_pane
    return direct_ops


@pytest.mark.parametrize("trace_type", ["scatter", "scatter3d", "scattergl", "custom"])
@pytest.mark.parametrize("traces", [1, 3])
@pytest.mark.parametrize("marker", [False, True], ids=["plain", "marker"])
@pytest.mark.parametrize("n_points", [1, 5])
def test_direct_patch_matches_the_diffed_patch(trace_type, traces, marker, n_points):
    """Across every appendable pane shape, the patch does not change.

    The frontend applies this patch to its own copy of the pane
    (``js/main.js``), so a direct patch that merely looks reasonable is not
    enough -- it has to be the patch the diff would have produced.
    """
    pane = plot_pane(trace_type, traces=traces, marker=marker)
    args = trace_append_args(
        trace_type, traces=traces, marker=marker, n_points=n_points
    )

    assert UpdateHandler.appendable(pane, args) is True
    ops = assert_patches_agree(pane, args)

    axes = 3 if trace_type == "scatter3d" else 2
    adds = axes * n_points + (n_points if marker else 0)
    assert len(ops) == traces * adds + 2


def test_direct_patch_uses_index_form_paths():
    """``add`` at the index the point lands on, which is what the diff emits.

    ``jsonpatch`` writes ``/content/data/0/x/12``, not the ``/-`` append form,
    and the frontend's patch library reads the index. Appending several points
    at once has to count up from the pre-append length.
    """
    pane = plot_pane(n_points=12)
    ops = assert_patches_agree(pane, trace_append_args(n_points=3))

    added = {op["path"]: op["value"] for op in ops if op["op"] == "add"}
    assert added["/content/data/0/x/12"] == 100.0
    assert added["/content/data/0/x/13"] == 101.0
    assert added["/content/data/0/x/14"] == 102.0
    assert added["/content/data/0/y/12"] == 200.0


def test_append_patch_carries_a_version_op():
    """``update_packet`` bumps the version on every accepted update.

    Leaving it out of a hand-built patch desyncs the frontend's copy of the
    pane from the server's, which no assertion about the data would catch.
    """
    pane = plot_pane()
    before = pane["version"]
    ops = assert_patches_agree(pane, trace_append_args())

    versions = [op for op in ops if op["path"] == "/version"]
    assert versions == [{"op": "replace", "path": "/version", "value": before + 1}]
    assert [op["path"] for op in ops].count("/contentID") == 1


def test_repeated_append_broadcasts_carry_consecutive_versions():
    """A run of appends has to move the counter once per broadcast.

    ``update_window`` does not touch ``version``; ``update_packet`` advances it
    (#1775). The fast path returns before the general path's bump, so it has to
    do its own -- and nothing in ``pane_versions.py`` would notice if it did
    not, because every plot case there is a replace rather than an append and
    so never reaches this branch.

    The frontend applies a patch only when it reads ``pane.version + 1``
    (``updateWindow`` in ``js/main.js``). A repeated version makes it discard
    the patch and re-request the whole environment, which is the #1805 cost
    back in full through the path meant to remove it -- and the broadcast would
    still look correct, since the data ops are all there.
    """
    handler = FakeHandler()
    sub = handler.add_sub()
    pane = make_pane(handler, 5)
    stored = handler.state["main"]["jsons"][pane["id"]]
    assert UpdateHandler.appendable(stored, append_args()) is True

    for _ in range(5):
        UpdateHandler.wrap_func(handler, append_args())

    broadcasts = [
        msg for msg in sub.sent if msg.get("command") in ("window", "window_update")
    ]
    assert [msg["version"] for msg in broadcasts] == [2, 3, 4, 5, 6]
    assert stored["version"] == 6


def test_append_calls_neither_deepcopy_nor_make_patch(monkeypatch):
    """The regression guard: an append must not pay for either of them.

    Both are O(points already plotted), so if one creeps back onto this path
    the per-append cost starts tracking the size of the plot again -- #1805
    exactly. Asserting on wall-clock would be flaky on CI's shared runners;
    asserting the calls never happen is not.
    """
    handler = FakeHandler()
    handler.add_sub()
    make_pane(handler, 1000)

    def forbidden(*args, **kwargs):
        raise AssertionError("an append must not reach this")

    monkeypatch.setattr(web_handlers.copy, "deepcopy", forbidden)
    monkeypatch.setattr(web_handlers.jsonpatch, "make_patch", forbidden)

    UpdateHandler.wrap_func(handler, append_args())

    assert handler.dirtied == ["main"]


def test_append_extends_the_series_in_place():
    """The second O(n^2): ``series + new`` copied every point on every append.

    Concatenation reallocates the whole series each time, which is quadratic in
    the number of appends regardless of what the patch costs, so the list
    object has to survive the append. No patch assertion can see this.
    """
    pane = plot_pane(marker=True, n_points=20)
    xs = pane["content"]["data"][0]["x"]
    colors = pane["content"]["data"][0]["marker"]["color"]

    UpdateHandler.update_packet(pane, trace_append_args(marker=True), *CAPS)

    assert pane["content"]["data"][0]["x"] is xs
    assert pane["content"]["data"][0]["marker"]["color"] is colors
    assert xs[-1] == 100.0
    assert colors[-1] == "#abcdef"


def test_a_replacing_update_still_rebinds_the_series():
    """Only an append extends in place; a replace must not mutate the old list.

    ``old_content`` and the pre-update snapshot the diffed path takes both read
    the series, so extending it on a replace would corrupt the patch.
    """
    pane = plot_pane(n_points=5)
    xs = pane["content"]["data"][0]["x"]
    args = trace_append_args(n_points=3)
    args["append"] = False

    UpdateHandler.update_packet(pane, args, *CAPS)

    assert pane["content"]["data"][0]["x"] is not xs
    assert pane["content"]["data"][0]["x"] == [100.0, 101.0, 102.0]


def test_named_append_patches_only_the_trace_it_names():
    pane = plot_pane(traces=3, names=["a", "b", "c"])
    ops = assert_patches_agree(pane, trace_append_args(name="b"))

    paths = [op["path"] for op in ops if op["op"] == "add"]
    assert all(path.startswith("/content/data/1/") for path in paths), paths


def test_append_with_fewer_entries_than_traces_patches_the_ones_it_reaches():
    """``update`` walks ``zip(idxs, data)``, so a short update is a short patch."""
    pane = plot_pane(traces=3)
    ops = assert_patches_agree(pane, trace_append_args(traces=1))

    paths = [op["path"] for op in ops if op["op"] == "add"]
    assert all(path.startswith("/content/data/0/") for path in paths), paths


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"opts": {"title": "a new title"}}, id="opts-change"),
        pytest.param({"opts": {"legend": ["renamed"]}}, id="opts-legend"),
        pytest.param({"opts": {"caption": "new caption"}}, id="opts-caption"),
        pytest.param({"layout": {"showlegend": True}}, id="layout-change"),
    ],
)
def test_an_append_that_also_changes_the_pane_keeps_the_diffed_path(extra):
    """Those mutations are not knowable up front, so the general path takes them.

    ``update_window`` writes arbitrary keys onto the pane, writes into its
    layout and renames traces from ``legend``. A hand-built patch covering only
    the appended points would silently drop all of it.
    """
    pane = plot_pane()
    args = trace_append_args(**extra)

    assert UpdateHandler.appendable(pane, args) is False
    assert_patches_agree(pane, args)


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"opts": {"title": ""}}, id="same-title"),
        pytest.param({"opts": {"title": None}}, id="title-is-none"),
        pytest.param({"layout": {"showlegend": False}}, id="same-showlegend"),
        pytest.param({"layout": {}}, id="empty-layout"),
    ],
)
def test_resent_opts_that_change_nothing_still_take_the_fast_path(extra):
    """The client resends the same ``opts`` on every append, so this is the norm.

    A guard that merely checked whether ``opts`` was *present* would send every
    real append down the slow path and the optimisation would never run in
    production.
    """
    pane = plot_pane(layout={"showlegend": False})
    args = trace_append_args(**extra)

    assert UpdateHandler.appendable(pane, args) is True
    assert_patches_agree(pane, args)


def test_the_first_append_after_a_plot_is_created_falls_back_and_is_correct():
    """A fresh pane lacks the keys the client's ``opts`` carry, so they are adds.

    This is the one append per plot that cannot take the fast path, and the
    patch it produces has to carry those new keys as well as the new point.
    """
    pane = plot_pane()
    args = trace_append_args(opts={"markersize": 10, "mode": "lines"})

    assert UpdateHandler.appendable(pane, args) is False
    ops = assert_patches_agree(pane, args)

    assert {"op": "add", "path": "/markersize", "value": 10} in ops


@pytest.mark.parametrize(
    "pane,args",
    [
        pytest.param(
            heatmap_pane(),
            {
                "win": "win_0",
                "eid": "main",
                "data": [{"type": "heatmap", "z": [[7.0, 8.0]], "x": None, "y": ["d"]}],
                "name": None,
                "updateDir": "appendRow",
                "append": True,
            },
            id="heatmap",
        ),
        pytest.param(
            plot_pane(traces=2, names=["a", "b"]),
            trace_append_args(name="not-a-trace"),
            id="named-trace-missing",
        ),
        pytest.param(
            plot_pane(),
            dict(trace_append_args(), append=False),
            id="replace-not-append",
        ),
        pytest.param(
            plot_pane(),
            dict(trace_append_args(), data=[], delete=True),
            id="delete",
        ),
    ],
)
def test_updates_that_are_not_plain_appends_keep_the_diffed_path(pane, args):
    assert UpdateHandler.appendable(pane, args) is False
    assert_patches_agree(pane, args)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("<h1>a text pane</h1>", id="text"),
        pytest.param(["a", "frame", "history"], id="list"),
        pytest.param(None, id="none"),
        pytest.param({"src": "data:image/png;base64,iVBOR"}, id="image"),
        pytest.param({"data": "not a list"}, id="data-not-a-list"),
        pytest.param({"data": []}, id="no-traces"),
    ],
)
def test_appendable_handles_panes_that_are_not_plots(content):
    """Asked before the pane's type has been checked, so it must not raise.

    A text pane's ``content`` is a ``str``: reaching into ``content["data"]``
    turns every update to one into a 500. The same class of bug as #1856, and
    the reason ``pane_min_bytes`` needed fixing.
    """
    pane = {"type": "text", "version": 1, "content": content}
    args = {"win": "win_0", "eid": "main", "append": True, "data": [{"x": [1.0]}]}

    assert UpdateHandler.appendable(pane, args) is False
