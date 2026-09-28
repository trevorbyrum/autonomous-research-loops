"""The router's JSON Schema validator against an independent oracle.

Trace: task 1b ("validate every JSON document against gen2/schema/");
gen2/router/schemas.py; INVARIANTS C-2, A11 (timestamps are real instants).

Oracle: the pinned `jsonschema` 4.10.3 (gen2/requirements-dev.txt), an
independent implementation, reached through tools/gen2_schema_oracle.py as a
subprocess (no gen2 module is granted the package, tests included). The
router's validator must give the same valid/invalid verdict on every
committed fixture and on single-point mutations of every valid fixture, and
the documents the router itself emits (commit responses and receipts) must
satisfy the oracle. The two places where the router is deliberately stricter
are asserted separately, with the oracle's own laxer verdict beside them.

What this cannot show: agreement on inputs no fixture or mutation reaches,
or that the schemas themselves say the right thing (their fixtures' own Gate
C review does that).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from gen2.router import schemas as router_schemas
from gen2.tests.router_fixtures import RouterTestCase, empty_outcome, h

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "gen2_schema_oracle.py"
VALIDATOR = ROOT / "gen2" / "router" / "schemas.py"  # module global: tools/gen2_mutations.py points it at mutated copies


def run_tool(mode: str, cases: list | None = None) -> tuple[int, object]:
    result = subprocess.run([sys.executable, str(TOOL), mode, "--validator", str(VALIDATOR)], input=None if cases is None else json.dumps(cases),
                            capture_output=True, text=True, timeout=600, cwd=ROOT)
    try:
        report = json.loads(result.stdout)
    except ValueError:
        report = None
    if result.returncode not in (0, 1) or report is None:  # a failure, not an error: the comparison could not be made
        raise AssertionError(f"oracle tool failed ({result.returncode}): {result.stderr[-2000:]}")
    return result.returncode, report


def verdicts(*cases: tuple[object, str]) -> list[dict]:
    code, out = run_tool("check", [{"instance": instance, "target": target} for instance, target in cases])
    assert code == 0
    return out


class DifferentialTest(unittest.TestCase):
    def test_every_fixture_and_its_mutations_get_the_oracles_verdict(self) -> None:
        code, report = run_tool("differential")
        self.assertEqual(report["fixture_disagreements"], [])
        self.assertEqual(report["disagreements"][:5], [])
        self.assertEqual(code, 0)
        self.assertGreater(report["fixtures"], 240)
        self.assertGreater(report["compared"], 20000)


class StricterThanOracleTest(unittest.TestCase):
    """The deliberate differences (gen2/router/schemas.py docstring)."""

    def test_a_trailing_newline_does_not_satisfy_an_anchored_pattern(self) -> None:
        target = "common.schema.json#/$defs/invocation_id"
        newline, plain = verdicts(("inv_abcdefgh\n", target), ("inv_abcdefgh", target))
        self.assertEqual(newline, {"oracle": True, "router": False})  # Python's `$` matches before a final newline; ECMA's does not
        self.assertEqual(plain, {"oracle": True, "router": True})

    def test_digit_classes_are_ascii(self) -> None:
        extra = router_schemas.SchemaSet(extra={"probe": {"$defs": {"d": {"pattern": "^\\d+$"}}}})
        self.assertTrue(extra.errors("١٢٣", "probe#/$defs/d"))  # Arabic-Indic digits
        self.assertFalse(extra.errors("123", "probe#/$defs/d"))

    def test_date_time_is_a_real_instant(self) -> None:
        target = "common.schema.json#/$defs/timestamp"
        feb29, leap = verdicts(("2026-02-29T00:00:00Z", target), ("2028-02-29T00:00:00Z", target))
        self.assertEqual((feb29, leap), ({"oracle": False, "router": False}, {"oracle": True, "router": True}))


class BoundsTest(unittest.TestCase):
    """Length, count and exclusive bounds at their edges, and an untyped
    const, judged by both validators (single-point mutations rarely reach a
    maximum, and elsewhere a type check hides const's JSON equality)."""

    def test_bounds_at_their_edges(self) -> None:
        promotions = [{"claim_id": f"clm_{i:08d}", "revision": 1} for i in range(257)]
        connectors = {f"c{i}": {"connector_type": "sql"} for i in range(101)}
        recall = "contract-v2.schema.json#/$defs/stopping_rule/allOf/4/then/properties/params/properties/target_recall"
        generation_one = "export-manifest.schema.json#/allOf/1/then/properties/supersedes/properties/generation"
        cases = [
            ("x" * 500, "common.schema.json#/$defs/short_text", True), ("x" * 501, "common.schema.json#/$defs/short_text", False),
            (promotions[:256], "outcome-document.schema.json#/properties/claim_promotions", True),
            (promotions, "outcome-document.schema.json#/properties/claim_promotions", False),
            (dict(list(connectors.items())[:100]), "export-manifest.schema.json#/properties/expected_connectors", True),
            (connectors, "export-manifest.schema.json#/properties/expected_connectors", False),
            (0.5, recall, True), (0, recall, False), (1, recall, False),
            (2**53 - 1, "common.schema.json#/$defs/revision", True), (2**53, "common.schema.json#/$defs/revision", False),
            (1, generation_one, True), (True, generation_one, False),  # an untyped const: true is not 1
        ]
        results = verdicts(*((instance, target) for instance, target, _ in cases))
        for (instance, target, expected), result in zip(cases, results):
            with self.subTest(target=target, expected=expected):
                self.assertEqual(result, {"oracle": expected, "router": expected})


class RouterDocumentsSatisfyTheOracleTest(RouterTestCase):
    """What the router emits is judged by the oracle, not only by the
    validator that produced it: committed and replayed responses (with their
    receipts) and rejections, including the null revision of an unknown topic."""

    def test_commit_responses(self) -> None:
        self.to_queued()
        grant = self.started("inv_research01")
        env = self.envelope(grant, "op_final000001", empty_outcome("inv_research01"))
        self.ready(grant, env["payload_digest"])
        env["expected_state_revision"] = self.state_revision()
        responses = [self.router.commit_outcome({**env, "topic_id": "fleet-a:nowhere"}), self.router.commit_outcome({**env, "role": "router"}),
                     self.router.commit_outcome({**env, "expected_state_revision": 0}), self.router.commit_outcome(env), self.router.commit_outcome(env),
                     self.router.commit_outcome({**env, "payload_digest": h("0")})]
        self.assertEqual([r["status"] for r in responses], ["rejected", "rejected", "rejected", "committed", "replayed", "rejected"])
        results = verdicts(*((r, "commit-outcome.schema.json#/$defs/response") for r in responses),
                           (responses[3]["receipt"], "commit-outcome.schema.json#/$defs/receipt"))
        self.assertEqual(results, [{"oracle": True, "router": True}] * 7)


class FailClosedTest(unittest.TestCase):
    def test_a_schema_using_an_unimplemented_keyword_is_refused_at_load(self) -> None:
        for keyword, value in (("patternProperties", {"^a": {}}), ("unevaluatedProperties", False), ("prefixItems", [{}]),
                               ("dependentRequired", {"a": ["b"]}), ("$dynamicRef", "#x")):
            with self.subTest(keyword), self.assertRaises(router_schemas.SchemaError):
                router_schemas.SchemaSet(extra={"probe": {"$defs": {"x": {keyword: value}}}})

    def test_an_unknown_format_or_an_unresolvable_ref_is_refused(self) -> None:
        for bad in ({"format": "email"}, {"$ref": "common.schema.json#/$defs/nope"}, {"$ref": "nowhere.schema.json"}, {"type": "text"}):
            with self.subTest(bad), self.assertRaises(router_schemas.SchemaError):
                router_schemas.SchemaSet(extra={"probe": {"$defs": {"x": bad}}})

    def test_a_dollar_inside_a_pattern_is_refused(self) -> None:
        with self.assertRaises(router_schemas.SchemaError):
            router_schemas.SchemaSet(extra={"probe": {"$defs": {"x": {"pattern": "^a$|^b$"}}}})


class EqualityTest(unittest.TestCase):
    """const/enum/uniqueItems compare JSON values: 1 equals 1.0, true is not 1."""

    def test_json_equality(self) -> None:
        eq = router_schemas.json_equal
        self.assertTrue(eq(1, 1.0))
        self.assertFalse(eq(True, 1))
        self.assertFalse(eq(False, 0))
        self.assertTrue(eq({"a": [1, {"b": None}]}, {"a": [1.0, {"b": None}]}))
        self.assertFalse(eq({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(eq("1", 1))

    def test_contains_counts_items_by_json_value(self) -> None:
        """Enough items equal to the `contains` value by JSON value (1 and 1.0,
        not true) meet minContains (task 1c-repair-3: the accepted path of the
        minContains check)."""
        mine = router_schemas.SchemaSet(extra={"probe": {"$defs": {"c": {"type": "array", "contains": {"const": 1}, "minContains": 2}}}})
        self.assertEqual(mine.errors([1, 1.0, True], "probe#/$defs/c"), [])

    def test_unique_items_by_json_value(self) -> None:
        mine = router_schemas.SchemaSet(extra={"probe": {"$defs": {"u": {"type": "array", "uniqueItems": True}}}})
        self.assertTrue(mine.errors([1, 1.0], "probe#/$defs/u"))
        self.assertFalse(mine.errors([1, True], "probe#/$defs/u"))
        self.assertTrue(mine.errors([{"a": 1, "b": 2}, {"b": 2, "a": 1}], "probe#/$defs/u"))


if __name__ == "__main__":
    unittest.main()
