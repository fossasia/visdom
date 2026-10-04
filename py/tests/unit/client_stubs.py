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

The checks are structural -- names, parameter order, parameter kinds, and which
parameters carry a default -- and deliberately not about the annotations
themselves: the point is that a call which type-checks is a call the
runtime accepts, in both directions.
"""

import ast
import collections
import inspect
import os
import textwrap

import pytest

import visdom
from visdom import async_client
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

POSITIONAL_ONLY = "positional-only"
POSITIONAL_OR_KEYWORD = "positional-or-keyword"
KEYWORD_ONLY = "keyword-only"

RUNTIME_KINDS = {
    inspect.Parameter.POSITIONAL_ONLY: POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD: POSITIONAL_OR_KEYWORD,
    inspect.Parameter.KEYWORD_ONLY: KEYWORD_ONLY,
}

# One parameter as a caller meets it. ``optional`` is whether it has a default,
# which a comparison of names alone cannot see: it counts a stub demanding an
# argument the runtime defaults as a match, and a checker then rejects a call
# the runtime accepts -- ``Visdom.audio`` defaults 'tensor' to None, and its
# stub required it.
Parameter = collections.namedtuple("Parameter", ("name", "kind", "optional"))

# The whole contract. ``positional`` keeps declaration order, because that order
# is what a positional call binds against; ``keyword`` is sorted by name,
# because the order keyword-only parameters are declared in cannot change which
# calls are accepted.
Signature = collections.namedtuple(
    "Signature", ("positional", "keyword", "varargs", "kwargs")
)


# The module's non-public classes are stubbed too, and a checker believes those
# declarations for anyone who imports them -- the tests and the transport
# injection in ``create(transport=...)`` do. Nothing here executes, so only a
# parity check notices when one of them describes an API that is not there.
INTERNAL_CLASSES = (
    "_AsyncTransport",
    "_AsyncBackchannel",
    "_AsyncWebSocket",
    "_AsyncPolling",
    "_Call",
    "_Construction",
    "_BridgedVisdom",
)


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
    """The call contract ``node`` declares, as a ``Signature``."""
    args = node.args
    slots = [(a, POSITIONAL_ONLY) for a in args.posonlyargs]
    slots += [(a, POSITIONAL_OR_KEYWORD) for a in args.args]
    # ast pads the defaults from the right, across both positional groups.
    defaults = [None] * (len(slots) - len(args.defaults)) + list(args.defaults)
    positional = [
        Parameter(arg.arg, kind, default is not None)
        for (arg, kind), default in zip(slots, defaults)
        if arg.arg not in ("self", "cls")
    ]
    keyword = [
        Parameter(arg.arg, KEYWORD_ONLY, default is not None)
        for arg, default in zip(args.kwonlyargs, args.kw_defaults)
    ]
    return Signature(
        tuple(positional),
        tuple(sorted(keyword)),
        args.vararg is not None,
        args.kwarg is not None,
    )


def runtime_signature(function):
    """The call contract ``function`` has at runtime, as a ``Signature``."""
    parameters = [
        p
        for p in inspect.signature(function).parameters.values()
        if p.name not in ("self", "cls")
    ]
    positional = [
        Parameter(p.name, RUNTIME_KINDS[p.kind], p.default is not p.empty)
        for p in parameters
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    keyword = [
        Parameter(p.name, KEYWORD_ONLY, p.default is not p.empty)
        for p in parameters
        if p.kind is p.KEYWORD_ONLY
    ]
    return Signature(
        tuple(positional),
        tuple(sorted(keyword)),
        any(p.kind is p.VAR_POSITIONAL for p in parameters),
        any(p.kind is p.VAR_KEYWORD for p in parameters),
    )


def runtime_methods(cls):
    return {
        name: member for name, member in vars(cls).items() if inspect.isfunction(member)
    }


def runtime_attributes(cls):
    """Every name the class could answer to: its own members, its ``__slots__``
    and anything it assigns to ``self``.

    Instance attributes are set in ``__init__``, so ``hasattr`` on the class
    cannot see them -- but a stub that annotates one is making a promise about
    them all the same, and ``__slots__`` makes a wrong one raise.
    """
    found = set(vars(cls)) | set(getattr(cls, "__slots__", ()))
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            found.add(node.attr)
    return found


def stub_annotations(class_node):
    """Map name -> annotation for the class's annotated attributes."""
    return {
        node.target.id: ast.unparse(node.annotation)
        for node in class_node.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def stub_declared(path, name):
    """Every name a class's stub offers, its stubbed bases included.

    A subclass that only overrides a value -- ``_AsyncPolling.name`` -- is
    declared on the base it inherits the annotation from, and re-stating it
    would be the drift this file exists to catch.
    """
    node = stub_class(path, name)
    declared = (
        set(stub_functions(node)) | stub_properties(node) | set(stub_annotations(node))
    )
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in INTERNAL_CLASSES:
            declared |= stub_declared(path, base.id)
    return declared


def module_annotations(path):
    return {
        node.target.id: ast.unparse(node.annotation)
        for node in parse_stub(path).body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


@pytest.fixture(scope="module")
def client_stub():
    return stub_class(CLIENT_STUB, "Visdom")


@pytest.fixture(scope="module")
def async_stub():
    return stub_class(ASYNC_STUB, "AsyncVisdom")


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
        # Names alone are not the contract. A shared argument has to keep its
        # position, its kind and its default as well, or a call that checks
        # against Visdom(...) is rejected against AsyncVisdom.create(...).
        create = stub_signature(stub_functions(async_stub)["create"])
        constructor = stub_signature(stub_functions(client_stub)["__init__"])

        # Positionally nothing moves, rejects included: they keep their slots so
        # that every argument after them stays where Visdom(...) puts it. Only
        # their annotation narrows -- test_create_leaves_no_room_for_a_proxy.
        assert create.positional == constructor.positional

        # Keyword-only, the rejected ones are dropped and create's own added.
        # Both tuples are sorted by name, so removing a subset keeps them aligned.
        assert tuple(p for p in create.keyword if p.name not in CREATE_EXTRAS) == tuple(
            p for p in constructor.keyword if p.name not in CREATE_REJECTS
        )
        assert {
            p.name for p in create.keyword if p.name in CREATE_EXTRAS
        } == CREATE_EXTRAS
        assert all(p.optional for p in create.keyword)

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


class TestAsyncStubInternals:
    """``visdom/async_client.pyi`` against the module's non-public surface.

    ``AsyncVisdom`` is covered above by its own ``_PROXIED``-driven checks. The
    classes behind it are covered here, and they drift for the same reason: a
    method can be renamed, an attribute can move behind ``__slots__`` under a
    private name, and nothing anywhere fails.
    """

    @pytest.mark.parametrize("name", INTERNAL_CLASSES)
    def test_the_class_exists_on_both_sides(self, name):
        assert hasattr(async_client, name), name
        stub_class(ASYNC_STUB, name)

    @pytest.mark.parametrize("name", INTERNAL_CLASSES)
    def test_stub_declares_no_member_that_does_not_exist(self, name):
        # '_Call.future' was declared here for a value that lives in
        # '__slots__' as '_future': reading it type-checks and raises.
        runtime = getattr(async_client, name)
        declared = stub_class(ASYNC_STUB, name)
        reachable = runtime_attributes(runtime)
        for member in list(stub_functions(declared)) + list(stub_properties(declared)):
            assert hasattr(runtime, member), "{0}.{1}".format(name, member)
        for attribute in stub_annotations(declared):
            assert attribute in reachable, "{0}.{1}".format(name, attribute)

    @pytest.mark.parametrize("name", INTERNAL_CLASSES)
    def test_public_members_are_stubbed(self, name):
        runtime = getattr(async_client, name)
        declared = stub_declared(ASYNC_STUB, name)
        own = {n for n in vars(runtime) if not n.startswith("_")}
        assert own <= declared, "{0}: {1}".format(name, sorted(own - declared))

    @pytest.mark.parametrize("name", INTERNAL_CLASSES)
    def test_signatures_match(self, name):
        runtime = getattr(async_client, name)
        for member, node in stub_functions(stub_class(ASYNC_STUB, name)).items():
            function = vars(runtime).get(member)
            if not inspect.isfunction(function):
                continue  # inherited, and checked against the class declaring it
            assert stub_signature(node) == runtime_signature(
                function
            ), "{0}.{1}".format(name, member)

    def test_every_module_constant_is_declared(self):
        declared = module_annotations(ASYNC_STUB)
        actual = {n for n in vars(async_client) if n.isupper()}
        assert actual <= set(declared), sorted(actual - set(declared))

    def test_constant_types_match_their_values(self):
        # 'REQUEST_TIMEOUT: int' stood over a 20.0, which makes a checker
        # reject the float a caller passes back into a tornado request.
        for name, annotation in module_annotations(ASYNC_STUB).items():
            if not name.isupper():
                continue
            value = getattr(async_client, name)
            if annotation == "int":
                assert isinstance(value, int) and not isinstance(value, bool), name
            elif annotation == "float":
                # An int where a float is annotated is fine -- PEP 484 promotes
                # it -- but a float under 'int' is the mismatch that matters.
                assert isinstance(value, (int, float)), name
