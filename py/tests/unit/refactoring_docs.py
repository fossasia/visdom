#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Drift tests for the Phase 4 record in ``REFACTORING.md``.

That section is a closeout: it says what the async work landed, and -- the part
worth guarding -- it states four invariants that a later change can break
without breaking a test. A single-worker storage executor widened to two is not
a slower server, it is interleaved writes and a truncated env file. A save
handed live state instead of a snapshot corrupts only under load. A disk write
that slips back onto the IOLoop stalls every other connection and nothing goes
red.

So these tests read the prose and then check the code against it: the paths and
symbols it names resolve, ``max_workers`` really is 1, the off-loop helpers
really snapshot first, ``shutdown_storage`` really orders its three steps that
way, and the handlers hold the no-disk-on-the-loop line except at the two sites
the doc records as follow-up 4j. The cross-document claims -- the benchmark
table, the proxied-name count, the invariants restated in
``.agents/context/architecture.md`` -- are compared against their sources
rather than trusted.

The companion for the user-facing async docs is ``unit/async_docs.py``.
"""

import ast
import os
import re

import pytest

from visdom.async_client import _PROXIED

pytestmark = pytest.mark.unit

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
REFACTORING = os.path.join(REPO_ROOT, "REFACTORING.md")
README = os.path.join(REPO_ROOT, "README.md")
ARCHITECTURE = os.path.join(REPO_ROOT, ".agents", "context", "architecture.md")
SERVER_STATE = os.path.join(REPO_ROOT, "py", "visdom", "server", "server_state.py")
SERVER_UTILS = os.path.join(REPO_ROOT, "py", "visdom", "utils", "server_utils.py")
HANDLER_DIR = os.path.join(REPO_ROOT, "py", "visdom", "server", "handlers")

PHASE_4_HEADING = "## Phase 4: Async I/O Modernization"
ARCHITECTURE_HEADING = "## Concurrency Model"

if not os.path.exists(REFACTORING):
    # An installed copy of the package has the modules but none of the prose.
    pytest.skip(
        "the roadmap is not part of an installed visdom", allow_module_level=True
    )


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section(path, heading, level="## "):
    """The named section of a markdown file, up to the next heading of its level."""
    text = read(path)
    start = text.index(heading)
    try:
        end = text.index("\n" + level, start + len(heading))
    except ValueError:
        end = len(text)
    return text[start:end]


PHASE_4 = section(REFACTORING, PHASE_4_HEADING)
CONCURRENCY = section(ARCHITECTURE, ARCHITECTURE_HEADING)


def parse(path):
    return ast.parse(read(path), filename=path)


def find_function(tree, name, classname=None):
    """The named function, optionally the one inside the named class."""
    scope = tree
    if classname is not None:
        scope = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == classname
        )
    for node in ast.walk(scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    raise AssertionError(f"{classname or ''}.{name} not found")


def called_names(node):
    """Every name called anywhere inside ``node``, attribute calls included."""
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


# --- what the section names must exist -------------------------------------

# Paths the prose points a reader at. A rename that misses the doc sends the
# next reader to a file that is not there.
PATHS_NAMED = [
    "py/visdom/server/server_state.py",
    "py/visdom/async_client.py",
    "py/tests/unit/async_docs.py",
    "py/tests/unit/client_stubs.py",
    "example/async_demo.py",
]

# Symbols the section leans on, as (module, attribute) or (module, class, attr).
SYMBOLS_NAMED = [
    ("visdom.utils.server_utils", "run_on_storage_executor"),
    ("visdom.utils.server_utils", "save_env_off_loop"),
    ("visdom.utils.server_utils", "save_envs_off_loop"),
    ("visdom.utils.server_utils", "save_all_off_loop"),
    ("visdom.utils.server_utils", "ensure_env_loaded"),
    ("visdom.utils.server_utils", "snapshot_env"),
    ("visdom.utils.server_utils", "snapshot_envs"),
    ("visdom.utils.server_utils", "check_auth"),
    ("visdom.async_client", "AsyncVisdom"),
    ("visdom.async_client", "_BridgedVisdom"),
    ("visdom.async_client", "_PROXIED"),
]


@pytest.mark.parametrize("relative", PATHS_NAMED)
def test_named_paths_exist(relative):
    assert relative in PHASE_4, f"{relative} is no longer named in the section"
    assert os.path.exists(os.path.join(REPO_ROOT, relative))


@pytest.mark.parametrize("module_name,attribute", SYMBOLS_NAMED)
def test_named_symbols_resolve(module_name, attribute):
    assert f"`{attribute}`" in PHASE_4, f"{attribute} is no longer named"
    module = __import__(module_name, fromlist=[attribute])
    assert hasattr(module, attribute)


def test_named_server_state_attributes_exist():
    from visdom.server.server_state import ServerState

    for attribute in ("storage_executor", "deleting_envs", "shutdown_storage"):
        assert f"`{attribute}`" in PHASE_4 or f"`ServerState.{attribute}`" in PHASE_4
    for attribute in ("shutdown_storage", "save_layouts"):
        assert callable(getattr(ServerState, attribute))


def test_bridge_overrides_only_the_transport_seam():
    """The section's central claim: one override, no duplicated plotting."""
    from visdom import Visdom
    from visdom.async_client import _BridgedVisdom

    assert issubclass(_BridgedVisdom, Visdom)
    inherited = {
        name
        for name in vars(_BridgedVisdom)
        if not name.startswith("__") and hasattr(Visdom, name)
    }
    assert inherited <= {
        "_handle_post",
        "_start_session_reaper",
        "setup_socket",
    }, f"_BridgedVisdom now overrides {sorted(inherited)}"


# --- invariant 1: one storage worker ---------------------------------------


def storage_executor_call():
    """The ``ThreadPoolExecutor(...)`` assigned to ``self.storage_executor``."""
    tree = parse(SERVER_STATE)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.attr for t in node.targets if isinstance(t, ast.Attribute)]
        if "storage_executor" not in targets:
            continue
        assert isinstance(node.value, ast.Call)
        return node.value
    raise AssertionError("self.storage_executor is no longer assigned an executor")


def test_storage_executor_has_exactly_one_worker():
    call = storage_executor_call()
    workers = {kw.arg: kw.value for kw in call.keywords if kw.arg == "max_workers"}
    assert "max_workers" in workers, "max_workers is no longer passed explicitly"
    value = workers["max_workers"]
    assert isinstance(value, ast.Constant) and value.value == 1, (
        "the storage executor must keep exactly one worker: it is what "
        "serializes writes. Two workers interleave saves of the same env."
    )


def test_the_single_worker_invariant_is_still_documented():
    assert "max_workers=1" in PHASE_4
    assert "max_workers=1" in CONCURRENCY


# --- invariant 2: snapshot on the loop -------------------------------------


@pytest.mark.parametrize(
    "helper", ["save_env_off_loop", "save_envs_off_loop", "save_all_off_loop"]
)
def test_off_loop_saves_snapshot_before_handing_over(helper):
    """A save must copy on the loop; passing live state lets the loop mutate
    an env mid-write."""
    tree = parse(SERVER_UTILS)
    called = called_names(find_function(tree, helper))
    assert called & {
        "snapshot_env",
        "snapshot_envs",
        "snapshot_state",
    }, f"{helper} no longer snapshots before the executor call"
    assert "run_on_storage_executor" in called


def test_run_on_storage_executor_targets_the_storage_pool():
    tree = parse(SERVER_UTILS)
    source = ast.get_source_segment(
        read(SERVER_UTILS), find_function(tree, "run_on_storage_executor")
    )
    assert "storage_executor" in source
    assert "run_in_executor" in source


# --- invariant 4: shutdown order -------------------------------------------


def test_shutdown_storage_orders_its_three_steps():
    """Stop autosave, drain, then save. Draining after the final save lets a
    queued write land on top of it and put stale state back on disk."""
    tree = parse(SERVER_STATE)
    body = find_function(tree, "shutdown_storage", "ServerState")
    order = []
    for node in ast.walk(body):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr == "stop_autosave":
            order.append(("autosave", node.lineno))
        elif attr == "shutdown":
            order.append(("drain", node.lineno))
        elif attr == "save_all":
            order.append(("save", node.lineno))
    steps = [name for name, _ in sorted(order, key=lambda item: item[1])]
    assert steps == ["autosave", "drain", "save"], steps


# --- invariant 1 (the other half): no disk writes on the loop --------------

BLOCKING_STORE_CALLS = ("save_env", "save_envs", "save_all", "load_env")

# Recorded, not condoned: follow-up 4j in REFACTORING.md. These two predate the
# async series -- they arrived with the hparams track -- and converting them is
# a change to a live write path, so it gets its own PR. Anything not on this
# list is a new violation.
KNOWN_ON_LOOP_WRITES = {
    ("experiments_handler.py", "ExperimentHparamsHandler.wrap_func", "save_env"),
    (
        "experiments_handler.py",
        "ExperimentHparamsUpdateHandler.wrap_func",
        "save_env",
    ),
}


def direct_storage_calls():
    """Every ``<something>.storage.<blocking call>`` inside a handler module."""
    found = set()
    for filename in sorted(os.listdir(HANDLER_DIR)):
        if not filename.endswith(".py"):
            continue
        path = os.path.join(HANDLER_DIR, filename)
        tree = parse(path)
        for classnode in [None] + [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            scope = tree if classnode is None else classnode
            prefix = "" if classnode is None else classnode.name + "."
            for node in scope.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for call in ast.walk(node):
                    if not isinstance(call, ast.Call):
                        continue
                    func = call.func
                    if not isinstance(func, ast.Attribute):
                        continue
                    if func.attr not in BLOCKING_STORE_CALLS:
                        continue
                    owner = func.value
                    if isinstance(owner, ast.Attribute) and owner.attr == "storage":
                        found.add((filename, prefix + node.name, func.attr))
    return found


def test_handlers_do_not_write_to_disk_on_the_loop():
    found = direct_storage_calls()
    new = found - KNOWN_ON_LOOP_WRITES
    assert not new, (
        "these call the storage backend directly, which blocks the IOLoop; "
        f"use run_on_storage_executor or a *_off_loop helper: {sorted(new)}"
    )


def test_the_recorded_on_loop_writes_are_still_there():
    """When 4j is done, delete the entry rather than letting it go stale."""
    stale = KNOWN_ON_LOOP_WRITES - direct_storage_calls()
    assert not stale, (
        f"{sorted(stale)} no longer blocks the loop -- drop it from "
        "KNOWN_ON_LOOP_WRITES and close follow-up 4j in REFACTORING.md"
    )


def test_followup_4j_is_documented():
    assert "| 4j |" in PHASE_4


# --- cross-document claims -------------------------------------------------


def test_proxied_count_matches_the_class():
    match = re.search(r"proxies (\d+) names", PHASE_4)
    assert match, "the proxied-name count is no longer stated"
    assert int(match.group(1)) == len(_PROXIED)


def benchmark_rows(markdown):
    """The numeric cells of the first plots/s table in ``markdown``."""
    rows = []
    for line in markdown.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 4:
            continue
        numbers = re.findall(r"[\d.]+", " ".join(cells[1:]))
        if len(numbers) == 3:
            rows.append(tuple(numbers))
    return rows


def test_roadmap_and_readme_quote_the_same_benchmarks():
    roadmap = benchmark_rows(PHASE_4)
    readme = benchmark_rows(read(README))
    assert len(roadmap) == 4, roadmap
    assert roadmap == readme[: len(roadmap)], (roadmap, readme[:4])


def backticked(markdown, symbol):
    """``symbol`` appears inside a code span, with or without a qualifier."""
    return any(symbol in span for span in re.findall(r"`([^`]+)`", markdown))


def test_architecture_and_roadmap_name_the_same_helpers():
    for symbol in ("run_on_storage_executor", "snapshot_env", "deleting_envs"):
        assert backticked(CONCURRENCY, symbol), f"{symbol} dropped from architecture.md"
        assert backticked(PHASE_4, symbol), f"{symbol} dropped from REFACTORING.md"


def test_architecture_points_back_at_the_roadmap():
    assert "REFACTORING.md" in CONCURRENCY


# --- the tables themselves --------------------------------------------------


def test_landed_pull_requests_are_unique_and_well_formed():
    links = re.findall(
        r"\[#(\d+)\]\(https://github\.com/fossasia/visdom/pull/(\d+)\)", PHASE_4
    )
    assert len(links) >= 11, links
    for label, target in links:
        assert label == target, f"#{label} links to pull/{target}"
    numbers = [int(label) for label, _ in links]
    assert len(numbers) == len(set(numbers)), "a pull request is listed twice"


def test_followups_are_uniquely_numbered_and_in_order():
    ids = re.findall(r"^\| (4[a-z]) \|", PHASE_4, re.MULTILINE)
    assert ids, "the follow-up table lost its rows"
    assert len(ids) == len(set(ids)), ids
    assert ids == sorted(ids), ids
