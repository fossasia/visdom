#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the experiments query parser.

The query language turns a human string such as ``lr < 0.01 AND acc > 90``
into a predicate tree that is evaluated against a plain ``dict``. These tests
cover tokenising, the full grammar (comparisons, AND/OR precedence, nested
parentheses), type-aware casting (numeric vs string vs bool), the ``contains``
operator, malformed input, the length/depth limits enforced at the parse
boundary, injection-style strings (which must be inert), and the
:func:`build_record` bridge from a real :class:`Experiment`.
"""

import unittest

from visdom.experiments import (
    Experiment,
    MAX_QUERY_DEPTH,
    MAX_QUERY_LENGTH,
    Query,
    QueryParseError,
    build_record,
    parse_query,
)
from visdom.experiments.query import And, Comparison, Or, tokenize


def match(text, record):
    """Parse ``text`` and evaluate it against ``record`` in one step."""
    return parse_query(text).matches(record)


class TestTokenizer(unittest.TestCase):
    """The tokeniser classifies numbers, strings, ops and keywords."""

    def test_numbers_int_vs_float(self):
        self.assertEqual(tokenize("3")[0].value, 3)
        self.assertIsInstance(tokenize("3")[0].value, int)
        self.assertEqual(tokenize("3.5")[0].value, 3.5)
        self.assertIsInstance(tokenize("3.5")[0].value, float)
        self.assertEqual(tokenize("1e3")[0].value, 1000.0)
        self.assertIsInstance(tokenize("1e3")[0].value, float)

    def test_negative_number(self):
        toks = tokenize("acc > -0.5")
        self.assertEqual([t.kind for t in toks], ["IDENT", "OP", "NUMBER"])
        self.assertEqual(toks[2].value, -0.5)

    def test_quoted_strings_and_escapes(self):
        self.assertEqual(tokenize('"hello world"')[0].value, "hello world")
        self.assertEqual(tokenize("'single'")[0].value, "single")
        self.assertEqual(tokenize(r'"a\"b"')[0].value, 'a"b')
        self.assertEqual(tokenize(r'"line\nbreak"')[0].value, "line\nbreak")

    def test_operator_normalisation(self):
        self.assertEqual(tokenize("==")[0].value, "=")
        self.assertEqual(tokenize("!=")[0].value, "!=")
        self.assertEqual(tokenize("<=")[0].value, "<=")

    def test_keywords_are_case_insensitive(self):
        kinds = [t.kind for t in tokenize("a = 1 and b = 2 OR c = 3")]
        self.assertIn("AND", kinds)
        self.assertIn("OR", kinds)
        contains = tokenize("name Contains x")[1]
        self.assertEqual((contains.kind, contains.value), ("OP", "contains"))

    def test_unexpected_character_raises(self):
        with self.assertRaises(QueryParseError):
            tokenize("a = 1 @ b")


class TestComparisons(unittest.TestCase):
    """Individual comparison operators against numeric and string fields."""

    def setUp(self):
        self.record = {"lr": 0.01, "acc": 92.5, "name": "resnet50", "epochs": 10}

    def test_less_than(self):
        self.assertTrue(match("lr < 0.05", self.record))
        self.assertFalse(match("lr < 0.001", self.record))

    def test_all_ordering_operators(self):
        self.assertTrue(match("acc > 90", self.record))
        self.assertTrue(match("acc >= 92.5", self.record))
        self.assertTrue(match("acc <= 92.5", self.record))
        self.assertFalse(match("acc < 92.5", self.record))
        self.assertTrue(match("epochs = 10", self.record))
        self.assertTrue(match("epochs != 5", self.record))

    def test_equality_is_type_aware(self):
        self.assertTrue(match("epochs = 10", {"epochs": "10"}))
        self.assertTrue(match("lr = 0.010", {"lr": 0.01}))
        self.assertFalse(match("lr = 0.02", {"lr": 0.01}))

    def test_string_equality_exact(self):
        self.assertTrue(match("name = resnet50", self.record))
        self.assertFalse(match("name = resnet", self.record))

    def test_string_ordering_is_lexicographic(self):
        self.assertTrue(match("name > abc", {"name": "xyz"}))
        self.assertFalse(match("name < abc", {"name": "xyz"}))

    def test_missing_field_never_matches(self):
        self.assertFalse(match("missing = 1", self.record))
        self.assertFalse(match("missing != 1", self.record))
        self.assertFalse(match("missing contains x", self.record))

    def test_non_numeric_field_vs_numeric_literal(self):
        self.assertFalse(match("name > 5", {"name": "abc"}))


class TestBooleans(unittest.TestCase):
    """Unquoted true/false parse as booleans and cast type-aware."""

    def test_bool_literals(self):
        self.assertTrue(match("amp = true", {"amp": True}))
        self.assertTrue(match("amp = false", {"amp": False}))
        self.assertFalse(match("amp = true", {"amp": False}))

    def test_bool_from_string_field(self):
        self.assertTrue(match("amp = true", {"amp": "true"}))
        self.assertTrue(match("amp = false", {"amp": "False"}))

    def test_number_literal_does_not_match_bool(self):
        self.assertFalse(match("amp = 1", {"amp": True}))


class TestContains(unittest.TestCase):
    """The contains operator does substring / membership matching."""

    def test_substring(self):
        self.assertTrue(match("name contains res", {"name": "resnet"}))
        self.assertFalse(match("name contains xyz", {"name": "resnet"}))

    def test_quoted_substring_with_space(self):
        self.assertTrue(match('desc contains "big model"', {"desc": "a big model"}))

    def test_list_membership(self):
        self.assertTrue(match("tags contains vision", {"tags": ["vision", "nlp"]}))
        self.assertFalse(match("tags contains audio", {"tags": ["vision", "nlp"]}))

    def test_numeric_substring(self):
        self.assertTrue(match("name contains 50", {"name": "resnet50"}))


class TestLogicAndPrecedence(unittest.TestCase):
    """AND binds tighter than OR; parentheses override precedence."""

    def setUp(self):
        self.record = {"lr": 0.01, "acc": 92.5, "status": "finished"}

    def test_and(self):
        self.assertTrue(match("lr < 0.05 AND acc > 90", self.record))
        self.assertFalse(match("lr < 0.05 AND acc > 99", self.record))

    def test_or(self):
        self.assertTrue(match("lr > 1 OR acc > 90", self.record))
        self.assertFalse(match("lr > 1 OR acc > 99", self.record))

    def test_and_binds_tighter_than_or(self):
        record = {"a": 0, "b": 1, "c": 1}
        node = parse_query("a = 1 AND b = 1 OR c = 1")
        self.assertIsInstance(node, Or)
        self.assertIsInstance(node.children[0], And)
        self.assertTrue(node.matches(record))
        self.assertFalse(node.matches({"a": 0, "b": 1, "c": 0}))

    def test_parentheses_override(self):
        record = {"a": 0, "b": 1, "c": 1}
        self.assertFalse(match("a = 1 AND (b = 1 OR c = 1)", record))
        self.assertTrue(match("(a = 1 OR b = 1) AND c = 1", record))

    def test_nested_parentheses(self):
        record = {"a": 1, "b": 0, "c": 1, "d": 1}
        self.assertTrue(match("a = 1 AND ((b = 1 OR c = 1) AND d = 1)", record))

    def test_chained_and(self):
        node = parse_query("a = 1 AND b = 1 AND c = 1")
        self.assertIsInstance(node, And)
        self.assertEqual(len(node.children), 3)
        self.assertTrue(node.matches({"a": 1, "b": 1, "c": 1}))
        self.assertFalse(node.matches({"a": 1, "b": 1, "c": 0}))


class TestSingleComparisonAst(unittest.TestCase):
    """A lone comparison is not needlessly wrapped in And/Or."""

    def test_lone_comparison_shape(self):
        node = parse_query("lr < 0.01")
        self.assertIsInstance(node, Comparison)
        self.assertEqual((node.key, node.op, node.value), ("lr", "<", 0.01))

    def test_dotted_key_preserved(self):
        node = parse_query("tag.owner = alice")
        self.assertEqual(node.key, "tag.owner")


class TestMalformedInput(unittest.TestCase):
    """Malformed queries raise QueryParseError, never crash or silently pass."""

    def test_empty_query(self):
        for text in ("", "   "):
            with self.assertRaises(QueryParseError):
                parse_query(text)

    def test_missing_operator(self):
        with self.assertRaises(QueryParseError):
            parse_query("lr 0.01")

    def test_missing_value(self):
        with self.assertRaises(QueryParseError):
            parse_query("lr <")

    def test_missing_key(self):
        with self.assertRaises(QueryParseError):
            parse_query("< 0.01")

    def test_trailing_tokens(self):
        with self.assertRaises(QueryParseError):
            parse_query("lr < 0.01 0.02")

    def test_dangling_boolean_operator(self):
        with self.assertRaises(QueryParseError):
            parse_query("lr < 0.01 AND")

    def test_unbalanced_parentheses(self):
        with self.assertRaises(QueryParseError):
            parse_query("(lr < 0.01")
        with self.assertRaises(QueryParseError):
            parse_query("lr < 0.01)")

    def test_empty_parentheses(self):
        with self.assertRaises(QueryParseError):
            parse_query("()")

    def test_reserved_word_as_bare_value(self):
        with self.assertRaises(QueryParseError):
            parse_query("owner = and")

    def test_reserved_word_as_bare_field_name(self):
        """A field named exactly after a keyword reads as an operator, not a name."""
        for text in ("and = 5", "or = 1", "contains = 7"):
            with self.assertRaises(QueryParseError):
                parse_query(text)

    def test_reserved_field_name_is_reachable_when_namespaced(self):
        """The namespaced key is the way to query such a field."""
        record = {"param.and": 5, "metric.contains": 7, "tag.or": "alice"}
        self.assertTrue(match("param.and = 5", record))
        self.assertTrue(match("metric.contains = 7", record))
        self.assertTrue(match("tag.or = alice", record))

    def test_names_merely_starting_with_a_keyword_are_ordinary(self):
        """Only a whole token is reserved, so ``and_steps`` needs no escaping."""
        record = {"and_steps": 5, "containsX": 1}
        self.assertTrue(match("and_steps = 5 AND containsX = 1", record))


class TestParseLimits(unittest.TestCase):
    """Oversized queries are rejected at the boundary, not parsed into work."""

    def test_query_at_the_length_limit_is_accepted(self):
        padding = "x" * (MAX_QUERY_LENGTH - len("name = "))
        text = "name = " + padding
        self.assertEqual(len(text), MAX_QUERY_LENGTH)
        self.assertTrue(parse_query(text).matches({"name": padding}))

    def test_query_over_the_length_limit_is_rejected(self):
        text = "name = " + "x" * MAX_QUERY_LENGTH
        with self.assertRaises(QueryParseError) as ctx:
            parse_query(text)
        self.assertIn(str(MAX_QUERY_LENGTH), str(ctx.exception))

    def test_length_limit_applies_to_the_wrapper_and_tokenizer(self):
        text = "name = " + "x" * MAX_QUERY_LENGTH
        with self.assertRaises(QueryParseError):
            Query(text)
        with self.assertRaises(QueryParseError):
            tokenize(text)

    def test_nesting_at_the_depth_limit_is_accepted(self):
        text = "(" * MAX_QUERY_DEPTH + "lr < 0.01" + ")" * MAX_QUERY_DEPTH
        self.assertTrue(parse_query(text).matches({"lr": 0.001}))

    def test_nesting_over_the_depth_limit_is_rejected(self):
        depth = MAX_QUERY_DEPTH + 1
        text = "(" * depth + "lr < 0.01" + ")" * depth
        with self.assertRaises(QueryParseError) as ctx:
            parse_query(text)
        self.assertIn(str(MAX_QUERY_DEPTH), str(ctx.exception))

    def test_deep_nesting_within_length_limit_does_not_recurse_away(self):
        """A query that fits the length cap can still out-nest the interpreter."""
        depth = 1000
        text = "(" * depth + "lr < 0.01" + ")" * depth
        self.assertLessEqual(len(text), MAX_QUERY_LENGTH)
        with self.assertRaises(QueryParseError):
            parse_query(text)

    def test_sibling_groups_do_not_accumulate_depth(self):
        """Depth is nesting, not a count of parentheses seen."""
        text = " OR ".join("(lr < 0.01)" for _ in range(MAX_QUERY_DEPTH * 2))
        self.assertTrue(parse_query(text).matches({"lr": 0.001}))


class TestInjectionSafety(unittest.TestCase):
    """Injection-style payloads are inert: they parse to string literals or fail."""

    def test_sql_injection_is_a_string_literal(self):
        record = {"name": "resnet"}
        self.assertFalse(match("name = '1; DROP TABLE experiments'", record))
        self.assertTrue(
            match(
                "name = '1; DROP TABLE experiments'",
                {"name": "1; DROP TABLE experiments"},
            )
        )

    def test_python_expression_is_not_evaluated(self):
        self.assertTrue(
            match("cmd contains import", {"cmd": "__import__('os').system('x')"})
        )
        self.assertFalse(match("x = 2", {"x": "1+1"}))

    def test_unquoted_injection_fails_to_parse(self):
        with self.assertRaises(QueryParseError):
            parse_query("name = 1); DROP TABLE experiments; --")


class TestQueryWrapper(unittest.TestCase):
    """The Query convenience wrapper compiles once and filters many records."""

    def test_matches_and_filter(self):
        query = Query("acc > 90")
        records = [{"acc": 95}, {"acc": 80}, {"acc": 91}]
        self.assertEqual(list(query.filter(records)), [{"acc": 95}, {"acc": 91}])
        self.assertTrue(query.matches({"acc": 95}))

    def test_wrapper_reports_parse_error_eagerly(self):
        with self.assertRaises(QueryParseError):
            Query("broken <")


class TestBuildRecord(unittest.TestCase):
    """build_record flattens a real Experiment into a queryable dict."""

    def _experiment(self):
        exp = Experiment(env_id="run1", name="resnet-run", description="baseline")
        exp.set_param("lr", 0.01)
        exp.set_param("epochs", 30)
        exp.add_metric("acc", 88.0, step=1)
        exp.add_metric("acc", 92.5, step=2)
        exp.set_tag("owner", "alice")
        return exp

    def test_builtins_params_metrics_tags(self):
        record = build_record(self._experiment())
        self.assertEqual(record["status"], "running")
        self.assertEqual(record["name"], "resnet-run")
        self.assertEqual(record["lr"], 0.01)
        self.assertEqual(record["param.lr"], 0.01)
        self.assertEqual(record["acc"], 92.5)
        self.assertEqual(record["metric.acc"], 92.5)
        self.assertEqual(record["tag.owner"], "alice")
        self.assertEqual(record["owner"], "alice")

    def test_query_against_built_record(self):
        record = build_record(self._experiment())
        self.assertTrue(Query("lr < 0.05 AND acc > 90").matches(record))
        self.assertTrue(Query("status = running").matches(record))
        self.assertTrue(Query("name contains resnet").matches(record))
        self.assertTrue(Query("tag.owner = alice").matches(record))
        self.assertFalse(Query("epochs > 100").matches(record))

    def test_builtin_takes_precedence_over_bare_param(self):
        exp = Experiment(env_id="run2")
        exp.set_param("status", "custom")
        record = build_record(exp)
        self.assertEqual(record["status"], "running")
        self.assertEqual(record["param.status"], "custom")

    def test_bare_name_precedence_is_param_then_metric_then_tag(self):
        exp = Experiment(env_id="run3")
        exp.set_param("score", "from-param")
        exp.add_metric("score", 1.0)
        exp.set_tag("score", "from-tag")
        exp.add_metric("loss", 0.5)
        exp.set_tag("loss", "from-tag")
        record = build_record(exp)

        self.assertEqual(record["score"], "from-param")
        self.assertEqual(record["loss"], 0.5)
        self.assertEqual(record["param.score"], "from-param")
        self.assertEqual(record["metric.score"], 1.0)
        self.assertEqual(record["tag.score"], "from-tag")
        self.assertEqual(record["tag.loss"], "from-tag")

    def test_latest_metric_wins_regardless_of_step_order(self):
        exp = Experiment(env_id="run4")
        exp.add_metric("acc", 90.0, step=5)
        exp.add_metric("acc", 70.0, step=1)
        self.assertEqual(build_record(exp)["acc"], 70.0)


class _FakeNamedValue:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class _FakeExperiment:
    """Experiment-shaped without being an Experiment; satisfies ExperimentLike."""

    def __init__(self):
        self.env_id = "fake1"
        self.name = "fake-run"
        self.description = ""
        self.status = "finished"
        self.created_at = 0.0
        self.finished_at = 1.0
        self.params = [_FakeNamedValue("lr", 0.5)]
        self.metrics = [_FakeNamedValue("acc", 99.0)]
        self.tags = [_FakeNamedValue("owner", "bob")]


class TestBuildRecordIsDecoupledFromModels(unittest.TestCase):
    """build_record reads a structural shape, not the concrete Experiment class."""

    def test_accepts_any_experiment_shaped_object(self):
        record = build_record(_FakeExperiment())
        self.assertEqual(record["lr"], 0.5)
        self.assertEqual(record["metric.acc"], 99.0)
        self.assertEqual(record["tag.owner"], "bob")
        self.assertTrue(Query("lr < 1 AND acc > 90").matches(record))


if __name__ == "__main__":
    unittest.main()
