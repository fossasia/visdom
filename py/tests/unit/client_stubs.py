#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Parity tests for the shipped type stubs.

``py/visdom/__init__.pyi`` and ``py/visdom/async_client.pyi`` are what a type
checker sees instead of the modules -- ``py.typed`` is in the wheel, so mypy and
every IDE read the stubs and never look at the implementation. A stub that
drifts is therefore worse than no stub at all: it reports a call the runtime
accepts as an error, or silently blesses one that raises. Nothing in a stub
executes, so nothing else in this suite can notice.

``AsyncVisdom`` makes that sharper. It has no ``async def line``; the method is
manufactured by ``__getattr__`` for any name in ``_PROXIED``, so its stub has to
spell out all 62 of them by hand and there is no import that would fail if one
were missing.

The checks are structural -- names, parameter order, parameter kinds -- and
deliberately not about the annotations themselves: the point is that a call
which type-checks is a call the runtime accepts, in both directions.
"""

import ast
import inspect
import os

import pytest

import visdom
import visdom.async_client as async_client
from visdom.async_client import _PROXIED, AsyncVisdom

pytestmark = pytest.mark.unit

STUB_DIR = os.path.dirname(os.path.abspath(visdom.__file__))
CLIENT_STUB = os.path.join(STUB_DIR, "__init__.pyi")
ASYNC_STUB = os.path.join(STUB_DIR, "async_client.pyi")

# Declared on ``AsyncVisdom`` itself rather than proxied through to the inner
# client, so they have no counterpart in the synchronous stub.
ASYNC_ONLY = frozenset(
    {
        "__aenter__",
        "__aexit__",
        "__dir__",
        "__init__",
        "clear_event_handlers",
        "create",
        "register_event_handler",
        "shutdown",
    }
)

# Arguments ``AsyncVisdom.create`` adds on top of the ``Visdom`` constructor.
CREATE_EXTRAS = frozenset({"max_clients", "max_concurrency", "transport"})

# ``Visdom`` takes these; ``AsyncVisdom.create`` raises NotImplementedError for
# them, because tornado's AsyncHTTPClient cannot proxy without pycurl.
CREATE_REJECTS = frozenset({"http_proxy_host", "http_proxy_port", "proxies"})


def parse_stub(path):
    with open(path) as handle:
        return ast.parse(handle.read(), filename=path)


def stub_class(path, name):
    for node in parse_stub(path).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError("{0} declares no class {1}".format(path, name))


def stub_functions(class_node):
    """Map name -> node for the class's stubbed functions, properties aside."""
    found = {}
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [ast.unparse(d) for d in node.decorator_list]
        if any("property" in d or "setter" in d for d in decorators):
            continue
        found[node.name] = node
    return found


def stub_properties(class_node):
    return {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any("property" in ast.unparse(d) for d in node.decorator_list)
    }


def stub_signature(node):
    """(positional names, keyword-only names, *args?, **kwargs?) of a stub."""
    args = node.args
    positional = [
        a.arg for a in args.posonlyargs + args.args if a.arg not in ("self", "cls")
    ]
    return (
        positional,
        sorted(a.arg for a in args.kwonlyargs),
        args.vararg is not None,
        args.kwarg is not None,
    )


def runtime_signature(function):
    parameters = list(inspect.signature(function).parameters.values())
    positional = [
        p.name
        for p in parameters
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        and p.name not in ("self", "cls")
    ]
    return (
        positional,
        sorted(p.name for p in parameters if p.kind is p.KEYWORD_ONLY),
        any(p.kind is p.VAR_POSITIONAL for p in parameters),
        any(p.kind is p.VAR_KEYWORD for p in parameters),
    )


def runtime_methods(cls):
    return {
        name: member for name, member in vars(cls).items() if inspect.isfunction(member)
    }


def stub_classes(path):
    """Map name -> node for every class the stub declares."""
    return {
        node.name: node
        for node in parse_stub(path).body
        if isinstance(node, ast.ClassDef)
    }


def annotated_names(body):
    return {
        node.target.id
        for node in body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def module_annotations(path):
    """Map name -> annotation source for the stub's module-level variables."""
    return {
        node.target.id: ast.unparse(node.annotation)
        for node in parse_stub(path).body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def runtime_properties(cls):
    return {name for name, member in vars(cls).items() if isinstance(member, property)}


def private_runtime_classes():
    return {
        name: member
        for name, member in vars(async_client).items()
        if inspect.isclass(member)
        and member.__module__ == async_client.__name__
        and name.startswith("_")
    }


def declared_in_stub(name, class_node, stubs):
    """Whether the class or one of its stubbed bases declares ``name``."""
    if name in stub_functions(class_node) or name in stub_properties(class_node):
        return True
    for base in class_node.bases:
        base_name = ast.unparse(base)
        if base_name == "Visdom":
            parent = stub_class(CLIENT_STUB, "Visdom")
        elif base_name in stubs:
            parent = stubs[base_name]
        else:
            continue
        if declared_in_stub(name, parent, stubs):
            return True
    return False


# What the module-level declarations in the async stub have to hold at runtime.
# 'float' also accepts an int, the way a checker does.
ANNOTATION_TYPES = {
    "bool": bool,
    "int": int,
    "float": (int, float),
    "Text": str,
    "FrozenSet": frozenset,
}


@pytest.fixture(scope="module")
def client_stub():
    return stub_class(CLIENT_STUB, "Visdom")


@pytest.fixture(scope="module")
def async_stub():
    return stub_class(ASYNC_STUB, "AsyncVisdom")


@pytest.fixture(scope="module")
def async_stubs():
    return stub_classes(ASYNC_STUB)


class TestClientStub:
    """``visdom/__init__.pyi`` against the real ``Visdom``."""

    def test_stub_covers_every_public_method(self, client_stub):
        stubbed = {n for n in stub_functions(client_stub) if not n.startswith("_")}
        actual = {n for n in runtime_methods(visdom.Visdom) if not n.startswith("_")}
        assert stubbed == actual

    def test_stub_declares_no_method_that_does_not_exist(self, client_stub):
        # A stub for an absent method type-checks a call that raises
        # AttributeError -- how the long-gone 'grid' entry survived.
        for name in stub_functions(client_stub):
            assert hasattr(visdom.Visdom, name), name

    @pytest.mark.parametrize(
        "name",
        sorted(n for n in runtime_methods(visdom.Visdom) if not n.startswith("_")),
    )
    def test_signatures_match(self, client_stub, name):
        stubbed = stub_functions(client_stub)[name]
        assert stub_signature(stubbed) == runtime_signature(
            getattr(visdom.Visdom, name)
        )

    def test_constructor_signature_matches(self, client_stub):
        stubbed = stub_functions(client_stub)["__init__"]
        assert stub_signature(stubbed) == runtime_signature(visdom.Visdom.__init__)

    def test_documented_state_is_declared(self, client_stub):
        # The connection flags callers poll. They are plain attributes, so only
        # an explicit annotation puts them in front of a checker.
        declared = {
            node.target.id
            for node in client_stub.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        assert {
            "env",
            "env_list",
            "event_handlers",
            "offline",
            "socket_alive",
            "use_preflight_checks",
            "use_socket",
            "win_data",
        } <= declared


class TestAsyncStub:
    """``visdom/async_client.pyi`` against ``AsyncVisdom`` and the sync stub."""

    def test_every_proxied_name_is_stubbed_as_a_coroutine(self, async_stub):
        coroutines = {
            node.name
            for node in async_stub.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        assert _PROXIED == frozenset(coroutines - ASYNC_ONLY)

    def test_no_plain_def_stands_in_for_a_proxied_method(self, async_stub):
        # A proxied name stubbed as 'def' would type-check 'vis.line(...)'
        # without the await that actually runs it.
        plain = {
            node.name for node in async_stub.body if isinstance(node, ast.FunctionDef)
        }
        assert not plain & _PROXIED

    @pytest.mark.parametrize("name", sorted(_PROXIED))
    def test_proxied_signatures_mirror_the_sync_stub(
        self, async_stub, client_stub, name
    ):
        # The proxy forwards *args/**kwargs verbatim, so any difference here is
        # a call that checks against one client and not the other.
        assert stub_signature(stub_functions(async_stub)[name]) == stub_signature(
            stub_functions(client_stub)[name]
        )

    def test_stub_does_not_declare_getattr(self, async_stub):
        # '__getattr__' in a stub makes a checker accept every attribute name,
        # which would defeat the point of writing the allowlist out.
        names = {
            node.name
            for node in async_stub.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "__getattr__" not in names

    def test_own_methods_are_stubbed(self, async_stub):
        stubbed = set(stub_functions(async_stub))
        actual = {
            name
            for name in runtime_methods(AsyncVisdom)
            if not name.startswith("_") or name in ASYNC_ONLY
        }
        assert actual <= stubbed

    def test_own_signatures_match(self, async_stub):
        stubbed = stub_functions(async_stub)
        for name in ("shutdown", "register_event_handler", "clear_event_handlers"):
            assert stub_signature(stubbed[name]) == runtime_signature(
                getattr(AsyncVisdom, name)
            ), name

    def test_passthrough_properties_are_stubbed(self, async_stub):
        actual = {
            name
            for name, member in vars(AsyncVisdom).items()
            if isinstance(member, property)
        }
        assert actual <= stub_properties(async_stub)

    def test_create_accepts_the_constructor_arguments(self, async_stub, client_stub):
        create = stub_functions(async_stub)["create"]
        positional, keyword, _, _ = stub_signature(create)
        accepted = set(positional) | set(keyword)
        constructor = stub_functions(client_stub)["__init__"]
        expected = set(stub_signature(constructor)[0]) | set(
            stub_signature(constructor)[1]
        )
        assert (expected - CREATE_REJECTS) <= accepted
        assert CREATE_EXTRAS <= accepted

    def test_create_leaves_no_room_for_a_proxy(self, async_stub):
        # create() raises NotImplementedError for any of these. The two
        # positional slots stay so that every later argument keeps its position,
        # but nothing except None fits them; 'proxies' is keyword-only upstream,
        # so it is simply absent.
        create = stub_functions(async_stub)["create"]
        assert not {a.arg for a in create.args.kwonlyargs} & CREATE_REJECTS
        annotated = {
            a.arg: ast.unparse(a.annotation)
            for a in create.args.args
            if a.annotation is not None
        }
        assert annotated["http_proxy_host"] == "None"
        assert annotated["http_proxy_port"] == "None"


class TestAsyncPrivateStub:
    """The helper declarations in ``async_client.pyi``.

    Nothing outside the module names these classes, so the parity tests above
    never reach them, and a stub is not executed either -- a declaration that
    never matched the implementation, or one left behind by a rename, simply
    stands. A checker then blesses a call that raises ``AttributeError``:
    ``_BridgedVisdom.cancel_call`` was declared here and never existed at all,
    and ``_Call`` was declared with two public attributes it does not have
    instead of the three methods it does.
    """

    def test_every_private_class_is_declared(self, async_stubs):
        declared = {name for name in async_stubs if name.startswith("_")}
        assert declared == set(private_runtime_classes())

    @pytest.mark.parametrize("name", sorted(private_runtime_classes()))
    def test_declared_members_exist(self, async_stubs, name):
        cls = private_runtime_classes()[name]
        for member in stub_functions(async_stubs[name]):
            assert hasattr(cls, member), "{0}.{1}".format(name, member)
        for member in stub_properties(async_stubs[name]):
            assert hasattr(cls, member), "{0}.{1}".format(name, member)

    @pytest.mark.parametrize("name", sorted(private_runtime_classes()))
    def test_declared_signatures_match(self, async_stubs, name):
        cls = private_runtime_classes()[name]
        for member, node in stub_functions(async_stubs[name]).items():
            runtime = getattr(cls, member)
            if not inspect.isfunction(runtime):
                continue
            assert stub_signature(node) == runtime_signature(runtime), "{0}.{1}".format(
                name, member
            )

    @pytest.mark.parametrize("name", sorted(private_runtime_classes()))
    def test_public_members_are_declared(self, async_stubs, name):
        cls = private_runtime_classes()[name]
        members = set(runtime_methods(cls)) | runtime_properties(cls)
        for member in members:
            if member.startswith("_"):
                continue
            assert declared_in_stub(
                member, async_stubs[name], async_stubs
            ), "{0}.{1}".format(name, member)

    @pytest.mark.parametrize("name", sorted(private_runtime_classes()))
    def test_no_attribute_outside_the_slots_is_declared(self, async_stubs, name):
        # '_Call' and '_Construction' are slotted, so an annotated attribute
        # the class cannot hold is a declaration a checker would let through.
        cls = private_runtime_classes()[name]
        slots = getattr(cls, "__slots__", None)
        if slots is None:
            return
        assert annotated_names(async_stubs[name].body) <= set(slots)

    def test_module_constants_are_declared(self):
        declared = set(module_annotations(ASYNC_STUB))
        actual = {
            attribute
            for attribute in vars(async_client)
            if attribute.isupper() and not attribute.startswith("_")
        }
        assert actual <= declared

    def test_module_constants_hold_what_they_declare(self):
        for attribute, annotation in module_annotations(ASYNC_STUB).items():
            assert hasattr(async_client, attribute), attribute
            expected = ANNOTATION_TYPES.get(annotation.split("[")[0])
            if expected is None:
                continue
            assert isinstance(
                getattr(async_client, attribute), expected
            ), "{0}: {1}".format(attribute, annotation)
