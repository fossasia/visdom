#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Drift tests for the async client's documentation and demo.

``AsyncVisdom`` has no ``async def line``: every plotting method is manufactured
by ``__getattr__`` for the names in ``_PROXIED``. So a README snippet that calls
a method which does not exist raises ``AttributeError`` only when someone runs
it, and one that forgets an ``await`` silently plots nothing and returns a
coroutine -- neither of which any import or type check would catch.

These tests read the shipped prose the way a reader would: they parse the
``python`` fences out of the README section, the website page and
``example/async_demo.py``, and check every ``vis.<name>`` against the real
class -- name exists, coroutines are consumed, non-coroutines are not awaited.
The claims those documents make about defaults are checked against
``AsyncVisdom.create`` itself rather than restated.
"""

import ast
import asyncio
import inspect
import os
import re

import pytest

import visdom.async_client as async_client
from visdom.async_client import _PROXIED, AsyncVisdom

pytestmark = pytest.mark.unit

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
README = os.path.join(REPO_ROOT, "README.md")
WEBSITE_PAGE = os.path.join(REPO_ROOT, "website", "docs", "api", "async-client.md")
SIDEBARS = os.path.join(REPO_ROOT, "website", "sidebars.js")
DEMO = os.path.join(REPO_ROOT, "example", "async_demo.py")

README_SECTION = "### Async usage (Python only)"

if not os.path.exists(DEMO):
    # An installed copy of the package has the module but none of the prose.
    pytest.skip(
        "docs and examples are not part of an installed visdom", allow_module_level=True
    )


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def readme_async_section():
    """The README's async section, up to the next heading of its level."""
    text = read(README)
    start = text.index(README_SECTION)
    end = text.index("\n### ", start + len(README_SECTION))
    return text[start:end]


def python_blocks(markdown):
    """Every ```python fence in ``markdown``, in order."""
    return re.findall(r"^```python\n(.*?)^```", markdown, re.MULTILINE | re.DOTALL)


def parents_of(tree):
    """Map each node to its parent, so ancestry can be walked upwards."""
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def is_consumed(node, parents):
    """Whether the value of ``node`` is awaited, directly or by ``gather``.

    ``asyncio.gather(...)`` is the documented way to run several calls at once,
    and the coroutines it is handed are awaited by it rather than by the
    caller -- including the ones built inside a generator expression.
    """
    current = node
    while current in parents:
        parent = parents[current]
        if isinstance(parent, ast.Await):
            return True
        if isinstance(parent, ast.Call):
            func = parent.func
            if isinstance(func, ast.Attribute) and func.attr == "gather":
                return True
        current = parent
    return False


def client_uses(source, receiver="vis"):
    """Yield ``(name, is_call, consumed)`` for each ``<receiver>.<name>`` use."""
    tree = ast.parse(source)
    parents = parents_of(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id == receiver):
            continue
        parent = parents.get(node)
        is_call = isinstance(parent, ast.Call) and parent.func is node
        target = parent if is_call else node
        yield node.attr, is_call, is_consumed(target, parents)


def documented_sources():
    """Every python snippet that drives a client, with a label for failures."""
    sources = [("example/async_demo.py", read(DEMO))]
    for index, block in enumerate(python_blocks(readme_async_section())):
        sources.append(("README.md block {0}".format(index), block))
    for index, block in enumerate(python_blocks(read(WEBSITE_PAGE))):
        sources.append(("website async-client.md block {0}".format(index), block))
    return sources


DOCUMENTED_SOURCES = documented_sources()


@pytest.mark.parametrize("label,source", DOCUMENTED_SOURCES)
def test_snippet_parses(label, source):
    ast.parse(source)


@pytest.mark.parametrize("label,source", DOCUMENTED_SOURCES)
def test_client_attributes_exist(label, source):
    for name, _is_call, _consumed in client_uses(source):
        assert name in _PROXIED or hasattr(
            AsyncVisdom, name
        ), "{0} uses vis.{1}, which AsyncVisdom does not have".format(label, name)


@pytest.mark.parametrize("label,source", DOCUMENTED_SOURCES)
def test_coroutine_calls_are_awaited(label, source):
    for name, is_call, consumed in client_uses(source):
        if name in _PROXIED and is_call:
            assert consumed, "{0} calls vis.{1}() without awaiting it".format(
                label, name
            )


@pytest.mark.parametrize("label,source", DOCUMENTED_SOURCES)
def test_plain_methods_are_not_awaited(label, source):
    for name, _is_call, consumed in client_uses(source):
        if name not in _PROXIED:
            assert not consumed, "{0} awaits vis.{1}, which is not a coroutine".format(
                label, name
            )


def test_demo_imports_and_exposes_its_demos():
    namespace = {"__name__": "async_demo_under_test", "__file__": DEMO}
    exec(compile(read(DEMO), DEMO, "exec"), namespace)
    demos = namespace["DEMOS"]
    assert demos, "the demo exposes no sections"
    for name, section in demos.items():
        assert inspect.iscoroutinefunction(
            section
        ), "demo section {0!r} is not a coroutine function".format(name)


def test_demo_run_choices_match_its_sections():
    tree = ast.parse(read(DEMO))
    choices = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and node.args
        and getattr(node.args[0], "value", None) == "-run"
        for keyword in node.keywords
        if keyword.arg == "choices"
    ]
    assert len(choices) == 1, "the demo has no single -run argument"
    # ``["all"] + list(DEMOS)`` -- the keys are not literals, so check the shape
    # rather than the values, which ``test_demo_imports_and_exposes_its_demos``
    # already has in hand.
    rendered = ast.unparse(choices[0])
    assert "DEMOS" in rendered and "'all'" in rendered, (
        "-run choices must be derived from DEMOS, not written out: " + rendered
    )


class _RecordingVisdom(object):
    """Stands in for the bridged client, so ``create`` never opens a socket."""

    seen = None

    def __init__(self, loop, *args, **kwargs):
        _RecordingVisdom.seen = dict(kwargs)
        self._transport = None

    def close_backchannel(self):
        return None


def create_kwargs(monkeypatch, **kwargs):
    """The kwargs ``create`` hands the inner client, after its defaults."""
    monkeypatch.setattr(async_client, "_BridgedVisdom", _RecordingVisdom)

    async def run():
        client = await AsyncVisdom.create(**kwargs)
        await client.shutdown()

    asyncio.run(run())
    return _RecordingVisdom.seen


def test_documented_defaults_hold(monkeypatch):
    # Both the README and the website page carry a table saying these two
    # differ from ``Visdom``; this is the half of it that can be checked.
    seen = create_kwargs(monkeypatch)
    assert seen["use_incoming_socket"] is False
    assert seen["use_preflight_checks"] is False


def test_documented_defaults_are_overridable(monkeypatch):
    seen = create_kwargs(
        monkeypatch, use_incoming_socket=True, use_preflight_checks=True
    )
    assert seen["use_incoming_socket"] is True
    assert seen["use_preflight_checks"] is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"proxies": {"http": "foo.bar:3128"}},
        {"http_proxy_host": "foo.bar"},
        {"http_proxy_port": 3128},
    ],
)
def test_documented_proxy_limitation_holds(kwargs):
    # The "Limitations" section promises NotImplementedError, not a hang.
    async def run():
        await AsyncVisdom.create(**kwargs)

    with pytest.raises(NotImplementedError):
        asyncio.run(run())


def test_readme_and_website_quote_the_same_benchmarks():
    def rows(text):
        return [
            re.sub(r"\s+", " ", line).strip()
            for line in text.splitlines()
            if line.startswith("| `Visdom`") or line.startswith("| `AsyncVisdom`")
        ]

    readme_rows = rows(readme_async_section())
    website_rows = rows(read(WEBSITE_PAGE))
    assert readme_rows, "the README async section lost its benchmark table"
    assert readme_rows == website_rows


def test_docs_point_at_the_demo():
    demo_reference = "example/async_demo.py"
    assert demo_reference in read(README)
    assert demo_reference in read(WEBSITE_PAGE)


def test_website_page_is_in_the_sidebar():
    assert "'api/async-client'" in read(SIDEBARS)


def test_website_links_resolve():
    page = read(WEBSITE_PAGE)
    links = re.findall(r"\]\((\.[^)]+)\)", page)
    assert links, "the async page links to nothing"
    for link in links:
        path, _, anchor = link.partition("#")
        target = os.path.normpath(os.path.join(os.path.dirname(WEBSITE_PAGE), path))
        assert os.path.exists(target), "broken link to {0}".format(link)
        if anchor:
            headings = [
                re.sub(r"[^a-z0-9]+", "-", line.lstrip("#").strip().lower()).strip("-")
                for line in read(target).splitlines()
                if line.startswith("#")
            ]
            assert anchor in headings, "broken anchor in {0}".format(link)


# -- The guard's own guard ---------------------------------------------------
#
# Every check above is only worth the drift it would catch, and all of them run
# against documents that currently pass. These run the same helper over
# snippets that are wrong on purpose.


def test_missing_await_is_detected():
    source = "async def f(vis):\n    vis.line(Y=[1])\n"
    assert list(client_uses(source)) == [("line", True, False)]


def test_gather_counts_as_awaiting():
    source = (
        "async def f(vis):\n"
        "    await asyncio.gather(*(vis.line(Y=[i], win=str(i)) for i in range(2)))\n"
    )
    assert list(client_uses(source)) == [("line", True, True)]


def test_awaited_plain_method_is_detected():
    source = "async def f(vis, win):\n    await vis.register_event_handler(f, win)\n"
    assert list(client_uses(source)) == [("register_event_handler", True, True)]


def test_bare_attribute_reads_are_not_calls():
    source = "async def f(vis):\n    return vis.use_socket\n"
    assert list(client_uses(source)) == [("use_socket", False, False)]
