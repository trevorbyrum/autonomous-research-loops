"""The router's JSON Schema validator against an independent oracle.

Trace: task 1b ("validate every JSON document against gen2/schema/");
gen2/router/schemas.py; INVARIANTS C-2, A11 (timestamps are real instants).

Oracle: the pinned `jsonschema` 4.10.3 (gen2/requirements-dev.txt), an
independent implementation, with the same date-time format rule the schema
checker registers (tools/check_gen2_schemas.py). The router's validator must
give the same valid/invalid verdict on every committed fixture and on
systematic mutations of every valid fixture. The two places where the router
is deliberately stricter are asserted separately, with the oracle's own
(laxer) verdict shown beside it.

What this cannot show: agreement on inputs no fixture or mutation reaches,
or that the schemas themselves say the right thing (their fixtures' Gate C
review does that).
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

import jsonschema

from gen2.core.instants import is_utc_instant
from gen2.router import schemas as router_schemas

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_gen2_schemas as checker  # noqa: E402 (the fixture patch format lives there)

SCHEMA_DIR = ROOT / "gen2" / "schema"


def oracle():
    docs = {}
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        doc = checker.load_json(path)
        docs[doc["$id"]] = doc
    formats = jsonschema.FormatChecker(formats=())

    @formats.checks("date-time")
    def _instant(instance) -> bool:
        return not isinstance(instance, str) or is_utc_instant(instance)

    validators = {}

    def valid(instance, target: str) -> bool:
        if target not in validators:
            name, _, fragment = target.partition("#")
            sid = router_schemas.ID_BASE + name
            resolver = jsonschema.RefResolver(base_uri=sid, referrer=docs[sid], store=docs)
            schema = resolver.resolve(f"{sid}#{fragment}")[1] if fragment else docs[sid]
            validators[target] = jsonschema.Draft202012Validator(schema, resolver=resolver, format_checker=formats)
        return validators[target].is_valid(instance)

    return valid


def fixtures():
    for path in sorted((SCHEMA_DIR / "examples").rglob("*.json")):
        fixture = checker.load_json(path)
        meta = fixture["fixture"]
        if meta["expect"] == "valid":
            instance = fixture["instance"]
        else:
            base = checker.load_json(path.parent / meta["base"])
            instance = checker.apply_patch(base["instance"], meta["patch"])
        yield path.relative_to(SCHEMA_DIR).as_posix(), meta["schema"], meta["expect"], instance


def mutations(value, path=()):
    """Single-point mutations of a JSON value: drop each key, add an unknown
    key, and swap each leaf for values of other types and near-miss values."""
    if isinstance(value, dict):
        yield path + ("+",), {**value, "zz_unexpected": 1}
        for key in value:
            yield path + (key, "-"), {k: v for k, v in value.items() if k != key}
            for sub_path, sub in mutations(value[key], path + (key,)):
                yield sub_path, {**value, key: sub}
    elif isinstance(value, list):
        if value:
            yield path + ("dup",), value + [copy.deepcopy(value[0])]
            yield path + ("empty",), []
        for index, item in enumerate(value):
            for sub_path, sub in mutations(item, path + (index,)):
                yield sub_path, value[:index] + [sub] + value[index + 1:]
    else:
        for replacement in (None, True, 0, -1, 1.5, 2**53, "", "x", "2026-02-30T00:00:00Z", [], {}):
            if type(replacement) is not type(value) or replacement != value:
                yield path + (repr(replacement),), replacement
        if isinstance(value, str):
            yield path + ("suffix",), value + "!"
        if isinstance(value, int) and not isinstance(value, bool):
            yield path + ("+1",), value + 1
            yield path + ("float",), float(value)


class DifferentialTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mine = router_schemas.SchemaSet()
        self.oracle = oracle()

    def test_every_fixture_gets_the_oracles_verdict(self) -> None:
        count = 0
        for name, target, expect, instance in fixtures():
            count += 1
            with self.subTest(name):
                self.assertEqual(self.oracle(instance, target), expect == "valid")  # the fixture is what it says (oracle)
                self.assertEqual(not self.mine.errors(instance, target), expect == "valid")
        self.assertGreater(count, 240)

    def test_mutations_of_every_valid_fixture_get_the_oracles_verdict(self) -> None:
        """~tens of thousands of near-miss instances; the verdicts must agree
        except where a mutation reaches one of the documented stricter rules
        (none of these mutations adds a trailing newline or a non-ASCII
        digit, so none may disagree)."""
        compared = disagreements = 0
        for name, target, expect, instance in fixtures():
            if expect != "valid":
                continue
            for where, mutant in mutations(instance):
                compared += 1
                theirs, ours = self.oracle(mutant, target), not self.mine.errors(mutant, target)
                if theirs != ours:
                    disagreements += 1
                    self.fail(f"{name} at {where}: oracle says {'valid' if theirs else 'invalid'}, router says {'valid' if ours else 'invalid'}")
        self.assertGreater(compared, 10000)
        self.assertEqual(disagreements, 0)


class StricterThanOracleTest(unittest.TestCase):
    """The two deliberate differences (gen2/router/schemas.py docstring)."""

    def setUp(self) -> None:
        self.mine = router_schemas.SchemaSet()
        self.oracle = oracle()

    def test_a_trailing_newline_does_not_satisfy_an_anchored_pattern(self) -> None:
        target = "common.schema.json#/$defs/invocation_id"
        self.assertTrue(self.oracle("inv_abcdefgh\n", target))  # Python's `$` matches before a final newline
        self.assertTrue(self.mine.errors("inv_abcdefgh\n", target))
        self.assertFalse(self.mine.errors("inv_abcdefgh", target))

    def test_digit_classes_are_ascii(self) -> None:
        schema = {"pattern": "^\\d+$"}
        extra = router_schemas.SchemaSet(extra={"probe": {"$defs": {"d": schema}}})
        self.assertTrue(extra.errors("١٢٣", "probe#/$defs/d"))  # Arabic-Indic digits
        self.assertFalse(extra.errors("123", "probe#/$defs/d"))

    def test_date_time_is_a_real_instant(self) -> None:
        target = "common.schema.json#/$defs/timestamp"
        self.assertTrue(self.mine.errors("2026-02-29T00:00:00Z", target))  # 2026 is not a leap year
        self.assertFalse(self.mine.errors("2028-02-29T00:00:00Z", target))


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

    def test_unique_items_by_json_value(self) -> None:
        mine = router_schemas.SchemaSet(extra={"probe": {"$defs": {"u": {"type": "array", "uniqueItems": True}}}})
        self.assertTrue(mine.errors([1, 1.0], "probe#/$defs/u"))
        self.assertFalse(mine.errors([1, True], "probe#/$defs/u"))
        self.assertTrue(mine.errors([{"a": 1, "b": 2}, {"b": 2, "a": 1}], "probe#/$defs/u"))


if __name__ == "__main__":
    unittest.main()
