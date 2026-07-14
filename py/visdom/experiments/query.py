#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""A small, injection-safe query language for filtering experiments.

The search layer (added in a later PR) lets a user filter experiments with a
human-readable expression such as::

    lr < 0.01 AND acc > 90
    status = finished AND (name contains resnet OR tag.owner = alice)

This module turns such a string into a **predicate tree** and evaluates it
against a plain ``dict`` describing one experiment. Because evaluation is a
pure Python walk over the tree — never ``eval``/``exec`` and never SQL — a
value like ``"1; DROP TABLE experiments"`` is just an ordinary string literal
that can never do anything but fail to match; there is no injection surface.

The grammar (lowest-to-highest precedence)::

    expr        := or_expr
    or_expr     := and_expr ( OR and_expr )*
    and_expr    := term ( AND term )*
    term        := "(" expr ")" | comparison
    comparison  := IDENT OP value
    OP          := "<" | "<=" | ">" | ">=" | "=" | "==" | "!=" | "contains"
    value       := NUMBER | STRING | BOOL | BAREWORD

``AND``/``OR``/``contains`` are case-insensitive keywords; ``true``/``false``
(unquoted) parse as booleans. Anything else on the value side is a string —
quote it (``"..."`` or ``'...'``) if it contains spaces or a reserved word.

The public surface is deliberately tiny: :func:`parse_query` (text → AST),
the :class:`Query` convenience wrapper, :func:`build_record` (Experiment →
queryable dict), and :class:`QueryParseError`.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Iterator, List, NamedTuple, Optional

__all__ = [
    "QueryParseError",
    "parse_query",
    "Query",
    "build_record",
    "Node",
    "And",
    "Or",
    "Comparison",
]

_COMPARISON_OPS = ("<", "<=", ">", ">=", "=", "!=", "contains")

_ORDER_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}

_MISSING = object()


class QueryParseError(ValueError):
    """Raised when a query string is malformed and cannot be parsed."""


class Token(NamedTuple):
    """A single lexical token: its kind, parsed value, and source position."""

    kind: str
    value: Any
    pos: int


_TOKEN_RE = re.compile(
    r"""
      (?P<WS>\s+)
    | (?P<NUMBER>-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
    | (?P<STRING>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<OP><=|>=|!=|==|<|>|=)
    | (?P<LPAREN>\()
    | (?P<RPAREN>\))
    | (?P<IDENT>[A-Za-z_][A-Za-z0-9_.]*)
    """,
    re.VERBOSE,
)

_STRING_ESCAPES = {'\\"': '"', "\\'": "'", "\\\\": "\\", "\\n": "\n", "\\t": "\t"}


def _unescape(raw: str) -> str:
    """Strip the surrounding quotes from a STRING token and unescape it."""
    body = raw[1:-1]
    return re.sub(r"\\[\"'\\nt]", lambda m: _STRING_ESCAPES[m.group(0)], body)


def _number(raw: str) -> Any:
    """Parse a NUMBER token as ``int`` when it has no fractional/exponent part."""
    if "." in raw or "e" in raw or "E" in raw:
        return float(raw)
    return int(raw)


def tokenize(text: str) -> List[Token]:
    """Split ``text`` into tokens, raising :class:`QueryParseError` on garbage.

    Keywords are recognised here so the parser sees dedicated ``AND``/``OR``
    tokens and a normalised ``contains`` operator, and never has to special-case
    identifiers by spelling.
    """
    tokens: List[Token] = []
    pos = 0
    length = len(text)
    while pos < length:
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise QueryParseError(
                "unexpected character {0!r} at position {1}".format(text[pos], pos)
            )
        pos = match.end()
        kind = match.lastgroup
        raw = match.group()
        if kind == "WS":
            continue
        if kind == "NUMBER":
            tokens.append(Token("NUMBER", _number(raw), match.start()))
        elif kind == "STRING":
            tokens.append(Token("STRING", _unescape(raw), match.start()))
        elif kind == "OP":
            tokens.append(Token("OP", "=" if raw == "==" else raw, match.start()))
        elif kind == "LPAREN":
            tokens.append(Token("LPAREN", raw, match.start()))
        elif kind == "RPAREN":
            tokens.append(Token("RPAREN", raw, match.start()))
        else:
            upper = raw.upper()
            if upper == "AND":
                tokens.append(Token("AND", raw, match.start()))
            elif upper == "OR":
                tokens.append(Token("OR", raw, match.start()))
            elif raw.lower() == "contains":
                tokens.append(Token("OP", "contains", match.start()))
            else:
                tokens.append(Token("IDENT", raw, match.start()))
    return tokens


class Node:
    """Base class for a node in the predicate tree."""

    def matches(self, record: dict) -> bool:
        raise NotImplementedError


class And(Node):
    """Logical AND: matches when *every* child matches."""

    def __init__(self, children: List[Node]):
        self.children = children

    def matches(self, record: dict) -> bool:
        return all(child.matches(record) for child in self.children)

    def __repr__(self) -> str:
        return "And({0!r})".format(self.children)


class Or(Node):
    """Logical OR: matches when *any* child matches."""

    def __init__(self, children: List[Node]):
        self.children = children

    def matches(self, record: dict) -> bool:
        return any(child.matches(record) for child in self.children)

    def __repr__(self) -> str:
        return "Or({0!r})".format(self.children)


class Comparison(Node):
    """A single ``key OP value`` leaf, evaluated against a record dict."""

    def __init__(self, key: str, op: str, value: Any):
        if op not in _COMPARISON_OPS:
            raise QueryParseError("unknown operator {0!r}".format(op))
        self.key = key
        self.op = op
        self.value = value

    def matches(self, record: dict) -> bool:
        actual = _lookup(record, self.key)
        if actual is _MISSING:
            return False
        return _compare(actual, self.op, self.value)

    def __repr__(self) -> str:
        return "Comparison({0!r}, {1!r}, {2!r})".format(self.key, self.op, self.value)


class _Parser:
    """Turns a token stream into a :class:`Node` tree by recursive descent."""

    def __init__(self, tokens: List[Token]):
        self._tokens = tokens
        self._index = 0

    def parse(self) -> Node:
        if not self._tokens:
            raise QueryParseError("empty query")
        node = self._parse_or()
        if not self._at_end():
            token = self._peek()
            raise QueryParseError(
                "unexpected {0!r} at position {1}".format(token.value, token.pos)
            )
        return node

    def _parse_or(self) -> Node:
        children = [self._parse_and()]
        while self._match("OR"):
            children.append(self._parse_and())
        return children[0] if len(children) == 1 else Or(children)

    def _parse_and(self) -> Node:
        children = [self._parse_term()]
        while self._match("AND"):
            children.append(self._parse_term())
        return children[0] if len(children) == 1 else And(children)

    def _parse_term(self) -> Node:
        if self._match("LPAREN"):
            node = self._parse_or()
            self._expect("RPAREN")
            return node
        return self._parse_comparison()

    def _parse_comparison(self) -> Node:
        key_token = self._expect("IDENT", what="a field name")
        op_token = self._expect("OP", what="a comparison operator")
        value = self._parse_value()
        return Comparison(key_token.value, op_token.value, value)

    def _parse_value(self) -> Any:
        token = self._peek()
        if token is None:
            raise QueryParseError("expected a value but reached end of query")
        if token.kind in ("NUMBER", "STRING"):
            self._advance()
            return token.value
        if token.kind == "IDENT":
            self._advance()
            lowered = token.value.lower()
            if lowered == "true":
                return True
            if lowered == "false":
                return False
            return token.value
        raise QueryParseError(
            "expected a value but found {0!r} at position {1}".format(
                token.value, token.pos
            )
        )

    def _peek(self) -> Optional[Token]:
        if self._index < len(self._tokens):
            return self._tokens[self._index]
        return None

    def _advance(self) -> Token:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _at_end(self) -> bool:
        return self._index >= len(self._tokens)

    def _match(self, kind: str) -> bool:
        token = self._peek()
        if token is not None and token.kind == kind:
            self._advance()
            return True
        return False

    def _expect(self, kind: str, what: Optional[str] = None) -> Token:
        token = self._peek()
        if token is None:
            raise QueryParseError(
                "expected {0} but reached end of query".format(what or kind)
            )
        if token.kind != kind:
            raise QueryParseError(
                "expected {0} but found {1!r} at position {2}".format(
                    what or kind, token.value, token.pos
                )
            )
        return self._advance()


def parse_query(text: str) -> Node:
    """Parse ``text`` into a predicate :class:`Node`.

    Raises :class:`QueryParseError` for an empty or malformed query.
    """
    return _Parser(tokenize(text)).parse()


def _lookup(record: dict, key: str) -> Any:
    """Resolve ``key`` in ``record``: exact key first, then dotted traversal."""
    if not isinstance(record, dict):
        return _MISSING
    if key in record:
        return record[key]
    cursor: Any = record
    for part in key.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return _MISSING
    return cursor


def _to_number(value: Any) -> Optional[float]:
    """Coerce ``value`` to a float for numeric comparison, or ``None``.

    ``bool`` is intentionally not treated as a number so that ``amp = 1`` does
    not silently match a boolean ``True``; booleans compare via :func:`_to_bool`.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _to_bool(value: Any) -> Optional[bool]:
    """Coerce ``value`` to a bool for boolean comparison, or ``None``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


def _equals(actual: Any, expected: Any) -> bool:
    """Type-aware equality between a stored value and a query literal."""
    if isinstance(expected, bool):
        actual_bool = _to_bool(actual)
        return actual_bool is not None and actual_bool == expected
    if isinstance(expected, (int, float)):
        actual_number = _to_number(actual)
        return actual_number is not None and actual_number == float(expected)
    return str(actual) == str(expected)


def _order(actual: Any, op: str, expected: Any) -> bool:
    """Apply an ordering operator, numerically when the literal is numeric."""
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        left = _to_number(actual)
        if left is None:
            return False
        right: Any = float(expected)
    else:
        left = str(actual)
        right = str(expected)
    return _ORDER_OPS[op](left, right)


def _contains(actual: Any, expected: Any) -> bool:
    """Membership for collections, substring match for everything else."""
    if isinstance(actual, (list, tuple, set)):
        if expected in actual:
            return True
        return any(str(item) == str(expected) for item in actual)
    return str(expected) in str(actual)


def _compare(actual: Any, op: str, expected: Any) -> bool:
    """Dispatch a single comparison to the right type-aware helper."""
    if op == "contains":
        return _contains(actual, expected)
    if op == "=":
        return _equals(actual, expected)
    if op == "!=":
        return not _equals(actual, expected)
    return _order(actual, op, expected)


class Query:
    """A compiled query: parse once, then match/filter many records."""

    def __init__(self, text: str):
        self.text = text
        self.root = parse_query(text)

    def matches(self, record: dict) -> bool:
        """Return ``True`` if ``record`` satisfies the query."""
        return self.root.matches(record)

    def filter(self, records: Iterable[dict]) -> Iterator[dict]:
        """Yield the records from ``records`` that satisfy the query."""
        return (record for record in records if self.root.matches(record))

    def __repr__(self) -> str:
        return "Query({0!r})".format(self.text)


def build_record(experiment: Any) -> dict:
    """Flatten an :class:`~visdom.experiments.models.Experiment` into a queryable dict.

    Each param, latest-metric value and tag is exposed both under its bare name
    (``lr``, ``acc``, ``owner``) and under a namespaced key (``param.lr``,
    ``metric.acc``, ``tag.owner``) so a query can disambiguate when names
    collide. Built-in fields (``name``, ``status`` …) take precedence over a
    bare param/metric/tag of the same name; the namespaced form always reaches
    the specific value. This is a duck-typed helper — it never imports the model
    class — so :mod:`query` stays free of storage dependencies.
    """
    record: dict = {
        "env_id": experiment.env_id,
        "name": experiment.name,
        "description": experiment.description,
        "status": experiment.status,
        "created_at": experiment.created_at,
        "finished_at": experiment.finished_at,
    }
    for param in experiment.params:
        record.setdefault(param.key, param.value)
        record["param." + param.key] = param.value
    for key in {metric.key for metric in experiment.metrics}:
        latest = experiment.latest_metric(key)
        if latest is not None:
            record.setdefault(key, latest.value)
            record["metric." + key] = latest.value
    for tag in experiment.tags:
        record.setdefault(tag.key, tag.value)
        record["tag." + tag.key] = tag.value
    return record
