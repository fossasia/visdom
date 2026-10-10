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
way, and the handlers hold the no-disk-on-the-loop line with no exception left
since follow-up 4j closed -- in both shapes it can be broken in, the backend
called directly and a store-taking helper called inline, which is how ``/close``
kept writing its undo file on the loop after the route itself had moved off it.
The cross-document claims -- the benchmark
table, the proxied-name count, the invariants restated in
``.agents/context/architecture.md`` -- are compared against their sources
rather than trusted.

The companion for the user-facing async docs is ``unit/async_docs.py``.
"""

import ast
import inspect
import os
import re

import pytest

from visdom.async_client import _PROXIED
from visdom.utils import server_utils

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

SNAPSHOT_CALLS = {"snapshot_env", "snapshot_envs", "snapshot_state"}
OFF_LOOP_SAVES = ["save_env_off_loop", "save_envs_off_loop", "save_all_off_loop"]


def call_name(node):
    """The called name of an ``ast.Call``, or ``None`` for anything else."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def snapshot_bound_before(function, name, lineno):
    """Whether ``name``'s last assignment before ``lineno`` is a snapshot call."""
    assignments = sorted(
        (node.lineno, call_name(node.value) in SNAPSHOT_CALLS)
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and node.lineno < lineno
        and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    )
    return bool(assignments) and assignments[-1][1]


def reads_live_state(node):
    """Whether ``node`` reaches ``.state`` other than through a snapshot call."""
    if call_name(node) in SNAPSHOT_CALLS:
        return False
    if isinstance(node, ast.Attribute) and node.attr == "state":
        return True
    return any(reads_live_state(child) for child in ast.iter_child_nodes(node))


@pytest.mark.parametrize("helper", OFF_LOOP_SAVES)
def test_off_loop_saves_snapshot_before_handing_over(helper):
    """A save must copy on the loop; passing live state lets the loop mutate
    an env mid-write.

    Calling a snapshot helper somewhere in the function is not enough: it has
    to run before the executor call, and what it returns has to be what the
    executor is handed. So the arguments after ``(handler, func)`` are checked
    one by one -- each is a snapshot call, a name last bound from one earlier
    in the function, or something that never touches ``.state``.
    """
    function = find_function(parse(SERVER_UTILS), helper)
    submits = [
        node
        for node in ast.walk(function)
        if call_name(node) == "run_on_storage_executor"
    ]
    assert len(submits) == 1, f"{helper} should submit exactly one write"
    submit = submits[0]
    handed = submit.args[2:]
    assert handed, f"{helper} hands the executor nothing to write"

    from_snapshot = []
    for argument in handed:
        if call_name(argument) in SNAPSHOT_CALLS:
            from_snapshot.append(argument)
        elif isinstance(argument, ast.Name) and snapshot_bound_before(
            function, argument.id, submit.lineno
        ):
            from_snapshot.append(argument)
        else:
            assert not reads_live_state(
                argument
            ), f"{helper} hands the executor live state: {ast.unparse(argument)}"
    assert from_snapshot, (
        f"{helper} no longer hands the executor a snapshot taken before the "
        f"call: {[ast.unparse(argument) for argument in handed]}"
    )


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

# Recorded, not condoned: a site that has to stay on the loop for now is listed
# here with a follow-up in REFACTORING.md. Follow-up 4j emptied it, and anything
# not on this list is a new violation.
KNOWN_ON_LOOP_WRITES = set()


def handler_trees():
    """Every handler module, as ``(filename, tree)``."""
    trees = []
    for filename in sorted(os.listdir(HANDLER_DIR)):
        if filename.endswith(".py"):
            trees.append((filename, parse(os.path.join(HANDLER_DIR, filename))))
    return trees


def module_functions(tree):
    """Every function of a module, as ``(qualified name, node)``.

    Module level and one class deep, which is every shape the handler modules
    use: the ``post``/``on_message``/``wrap_func`` members and the worker shims
    they hand to the executor.
    """
    for classnode in [None] + [
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ]:
        scope = tree if classnode is None else classnode
        prefix = "" if classnode is None else classnode.name + "."
        for node in scope.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield prefix + node.name, node


def direct_storage_calls():
    """Every ``<something>.storage.<blocking call>`` inside a handler module."""
    found = set()
    for filename, tree in handler_trees():
        for qualname, node in module_functions(tree):
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
                    found.add((filename, qualname, func.attr))
    return found


def test_handlers_do_not_write_to_disk_on_the_loop():
    found = direct_storage_calls()
    new = found - KNOWN_ON_LOOP_WRITES
    assert not new, (
        "these call the storage backend directly, which blocks the IOLoop; "
        f"use run_on_storage_executor or a *_off_loop helper: {sorted(new)}"
    )


def test_the_recorded_on_loop_writes_are_still_there():
    """A recorded site that has been fixed is deleted, not left to go stale."""
    stale = KNOWN_ON_LOOP_WRITES - direct_storage_calls()
    assert not stale, (
        f"{sorted(stale)} no longer blocks the loop -- drop it from "
        "KNOWN_ON_LOOP_WRITES and close its follow-up in REFACTORING.md"
    )


# --- invariant 1 (the last part): helpers that take the store as an argument -

# ``<handler>.storage.save_env(...)`` is not the only way to reach the disk on
# the loop. A ``server_utils`` helper that takes a ``DataStore`` reaches it just
# as surely, one argument deeper, and the scanner above sees nothing: the store
# is being passed, not called. Which helpers those are is ``server_utils``'s
# own answer, read off their signatures rather than listed here, so a new one
# is covered the day it is written.

# The exceptions, and what makes them exceptions: an argument that says the
# caller has already done the read off the loop and is handing the answer in.
# Without it the same call does reach disk, so the keyword is the whole licence.
READ_FREE_ARGUMENT = {
    "load_env": "warmed",
    "compare_envs": "warmed",
    "broadcast_undo_state": "count",
}


def store_taking_helpers():
    """``server_utils`` functions that reach a store through a parameter.

    Maps each to its parameter names, so a call's positional arguments can be
    bound the way Python would bind them.
    """
    helpers = {}
    for name, value in vars(server_utils).items():
        if not inspect.isfunction(value):
            continue
        if value.__module__ != server_utils.__name__:
            continue
        params = list(inspect.signature(value).parameters)
        if "store" in params:
            helpers[name] = params
    return helpers


def takes_a_store(node):
    """This function is worker code: the store arrives as an argument."""
    return any(arg.arg in ("store", "storage") for arg in node.args.args)


def store_helper_calls_on_the_loop(trees=None):
    """Every store-taking helper a handler module calls inline.

    Functions that take a store themselves are skipped -- those are the shims
    handed to the executor, and reaching the disk is their job.
    """
    helpers = store_taking_helpers()
    found = set()
    for filename, tree in handler_trees() if trees is None else trees:
        for qualname, node in module_functions(tree):
            if takes_a_store(node):
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                if not isinstance(call.func, ast.Name):
                    continue
                params = helpers.get(call.func.id)
                if params is None:
                    continue
                passed = set(params[: len(call.args)])
                passed.update(keyword.arg for keyword in call.keywords)
                if READ_FREE_ARGUMENT.get(call.func.id) in passed:
                    continue
                found.add((filename, qualname, call.func.id))
    return found


def test_the_store_taking_helpers_are_discovered_by_signature():
    """A scan that found nothing would let every one of them through."""
    helpers = store_taking_helpers()
    assert {"push_deleted", "count_deleted", "load_env", "compare_envs"} <= set(helpers)


def test_every_read_free_argument_is_a_real_parameter():
    """An exemption naming an argument the helper no longer takes is a hole."""
    helpers = store_taking_helpers()
    for name, argument in READ_FREE_ARGUMENT.items():
        assert name in helpers, f"{name} no longer takes a store"
        assert argument in helpers[name], (name, argument)


def test_handlers_do_not_call_a_store_taking_helper_on_the_loop():
    found = store_helper_calls_on_the_loop()
    assert not found, (
        "these hand the store to a helper that reads or writes it, on the "
        f"loop; go through the executor or a *_off_loop helper: {sorted(found)}"
    )


def test_the_guard_catches_a_helper_called_inline():
    """The scanner has to bite, or the test above passes for the wrong reason."""
    source = (
        "class CloseHandler:\n"
        "    async def post(self):\n"
        "        push_deleted(self.storage, 'e', 'w', {})\n"
    )
    found = store_helper_calls_on_the_loop([("web_handlers.py", ast.parse(source))])
    assert found == {("web_handlers.py", "CloseHandler.post", "push_deleted")}


def test_the_guard_accepts_a_helper_told_not_to_read():
    """Both shapes the handlers use: the keyword, and the depth passed in."""
    source = (
        "class EnvHandler:\n"
        "    async def post(self):\n"
        "        load_env(self.state, 'e', sub, self.storage, 0, warmed=True)\n"
        "        broadcast_undo_state(self, 'e', self.storage, 3)\n"
    )
    assert store_helper_calls_on_the_loop([("x.py", ast.parse(source))]) == set()


def test_the_guard_leaves_the_worker_shims_alone():
    """A function that is handed the store is the code running off the loop."""
    source = "def _select(store, eid):\n" "    return count_deleted(store, eid)\n"
    assert store_helper_calls_on_the_loop([("x.py", ast.parse(source))]) == set()


def test_followup_4j_is_recorded_as_delivered():
    """4j closed with the list above emptied; the roadmap has to say so too."""
    assert not KNOWN_ON_LOOP_WRITES
    delivered = section(REFACTORING, "### Follow-ups delivered", level="### ")
    assert "| 4j |" in delivered
    not_taken = section(REFACTORING, "### Follow-ups not taken", level="### ")
    assert "| 4j |" not in not_taken


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


LANDED_PR_COUNT = 11


def test_landed_pull_requests_are_unique_and_well_formed():
    links = re.findall(
        r"\[#(\d+)\]\(https://github\.com/fossasia/visdom/pull/(\d+)\)", PHASE_4
    )
    assert len(links) == LANDED_PR_COUNT, links
    for label, target in links:
        assert label == target, f"#{label} links to pull/{target}"
    numbers = [int(label) for label, _ in links]
    assert len(numbers) == len(set(numbers)), "a pull request is listed twice"


def test_every_statement_of_the_pr_count_agrees_with_the_table():
    """The header and the closing estimate both restate the table's length."""
    header = re.search(r"\| PRs: (\d+) \|", PHASE_4)
    assert header, "the Phase 4 header no longer states a PR count"
    assert int(header.group(1)) == LANDED_PR_COUNT
    closing = re.search(r"Phase 4 took (\d+) of its own", read(REFACTORING))
    assert closing, "the closing estimate no longer states Phase 4's PR count"
    assert int(closing.group(1)) == LANDED_PR_COUNT


FOLLOWUP_TABLES = ("### Follow-ups not taken", "### Follow-ups delivered")


def followup_ids(markdown):
    return re.findall(r"^\| (4[a-z]) \|", markdown, re.MULTILINE)


def test_followups_are_uniquely_numbered_and_in_order():
    """Unique across both tables, and in order within each one.

    The numbers are how the phase refers to itself -- a pull request closing 4j
    has to find exactly one row. Order is checked per table rather than over the
    section: a follow-up that gets delivered moves out of the first table into
    the second, which leaves the two tables' numbers interleaved for good.
    """
    tables = [
        followup_ids(section(REFACTORING, heading, level="### "))
        for heading in FOLLOWUP_TABLES
    ]
    assert all(tables), tables
    for ids in tables:
        assert ids == sorted(ids), ids
    listed = [followup for ids in tables for followup in ids]
    assert len(listed) == len(set(listed)), listed
    assert set(listed) == set(followup_ids(PHASE_4)), "a follow-up row is off-table"
