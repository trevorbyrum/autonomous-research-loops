"""Task 2b-repair-13a (Astra R12-1 doi.org, R12-5): the raw answer is SEALED at the public API, and the decoder is its only public reader — under trust model B (2b-repair-14).

Repair-12 kept the rule "an adapter reads a provider's answer through `decode(...)`" as a source scan: no `.json`, `.text` or `.body` outside a decoder's argument. Astra wrote `getattr(resp, "json")` in
a mutant of the OpenCitations adapter (a prefilter of the rows before the decoder ran), and every structural check passed: imports, reflection and the inventory of reads found nothing, because the scan knew
the spellings it looked for. The cause is that the payload was REACHABLE. Now:

  * the client's Response exposes no payload — no `json`, `text`, `body`, `json_or_none`; the bytes are opened by `decode` (core/schema.py), and `getattr(resp, "json")`, `resp.__dict__`, `vars(resp)`
    and every other public spelling find nothing, because there is nothing public to find (ResponseIsSealed);
  * what the decoder keeps of the answer for provenance is `Sealed`: it is stored, compared with no other Sealed, and read by nothing public, and it leaves only as a COPY (`plain`) — and, since
    2b-repair-13c, not even the canonical record an adapter builds makes it readable: a record's `raw` is a Sealed, and materializing is the sinks' act (tests/test_opaque_provenance.py;
    RawIsSealedAndLeavesAsACopy here);
  * a field a schema declares `any_()` is `Passive`: every listed way of reading it raises (PassiveIsOnlyStored);
  * and the source scans (tests/inventory.py, held by tests/test_inventory.py; GuardsStayBounded here) are the discipline that keeps the trusted adapter code honest: they catch the spellings that
    would have to be written to go past the public API, for review.

TRUST MODEL B (INVARIANTS B-1; the operator's ruling of 2026-10-02). Python offers ways round an object's private storage (`object.__getattribute__(x, "_body")`, the `gc` module, ...), and
`plain` and `Sealed` are importable. Those are documented boundaries of the model: first-party adapters are reviewed code, and the guards refuse to let an adapter be written with the spellings that need
them. Each test below claims only what it asserts; the claims that were wider (2b-repair-13a's review, Gate C) are narrowed in their names and docstrings, and the exits they left open are
tests/test_opaque_provenance.py's.
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from research_gateway.adapters.base import Client, FakeTransport, PayloadError, Response
from research_gateway.core import schema as S
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.canonical import make_record
from research_gateway.core.payload import MemberList, Passive, PassiveRead, Rec, Sealed, SealedRead, UndeclaredRead, Unreadable, plain
from tests import invariant_ops as ops
from tests import inventory as INV
from tests import test_member_isolation as M
from tests.invariant_ops import corrupt_route
from tests.test_invariants import ALL, run

MARKER = b'{"results": [{"secret_marker_7f3a": "payload-bytes-must-not-be-reachable"}]}'


class ResponseIsSealed(unittest.TestCase):
    def response(self) -> Response:
        return Response(200, {"content-type": "application/json"}, MARKER, "https://example.org/x")

    def test_the_responses_public_names_are_a_closed_list_none_of_them_a_payload_accessor_and_its_one_door_is_sealed(self):
        """What is asserted: the public names of a Response are exactly this list (a new one fails until it is added deliberately, with why); the names a payload used to be reached by
        (`json`, `text`, `body` ...) are not among them, by `hasattr` and `getattr`; and `download()`, the one name that is a way to the bytes, returns a `Sealed` that no read opens. That the
        decoder is the only OTHER reader of the bytes is the inventory's (tests/inventory.py, held by tests/test_inventory.py), not this test's."""
        resp = self.response()
        public = sorted(n for n in dir(resp) if not n.startswith("_"))
        self.assertEqual(public, ["download", "error", "headers", "ok", "retry_after_seconds", "status", "url"],
                         "a new public name on the client's Response is a way to the payload: add it here deliberately, with why it is not")
        for name in ("json", "json_or_none", "text", "body", "content", "parsed", "data", "raw", "read", "payload"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(resp, name))
                with self.assertRaises(AttributeError):
                    getattr(resp, name)
        door = resp.download()
        self.assertIsInstance(door, Sealed)
        for what in (lambda: len(door), lambda: bytes(door), lambda: door.decode(), lambda: door[0], lambda: list(door), lambda: b"secret" in door, lambda: str(door)):
            with self.assertRaises(SealedRead):
                what()

    def test_no_value_reachable_by_public_name_shows_the_marker_and_the_one_door_is_sealed(self):
        resp = self.response()
        found = []
        for name in dir(resp):
            if name.startswith("_") or name == "download":
                continue
            value = getattr(resp, name)
            value = value() if callable(value) and name == "retry_after_seconds" else value
            if b"secret_marker_7f3a" in repr(value).encode():
                found.append(name)
        self.assertEqual(found, [])
        self.assertEqual(repr(resp.download()), "<Sealed>", "the one other way to the bytes is the file a caller asked to download, and it shows nothing of them")
        self.assertEqual(plain(resp.download()), MARKER, "it is the trusted boundary that makes it bytes (core/payload.py)")

    def test_it_has_no_dictionary_to_reach_into(self):
        resp = self.response()
        with self.assertRaises(AttributeError):
            resp.__dict__
        with self.assertRaises(TypeError):
            vars(resp)

    def test_decode_reads_the_payload_through_its_declared_schema_and_the_responses_other_names_do_not_show_it(self):
        """What is asserted: `decode` reads the marker through a schema that declares it (the positive control), and the Response's other names — its public values, its repr, its one sealed door —
        show nothing of it. It is not a proof of exclusivity: the client reads the bytes in a few places of its own (tests/inventory.py lists them), and `plain` of the sealed door is bytes."""
        resp = self.response()
        rows = S.decode("x", S.obj({"results": S.members(S.obj({"secret_marker_7f3a": S.text()}))}), resp)["results"]
        self.assertEqual(rows.each(lambda r: r["secret_marker_7f3a"]), ["payload-bytes-must-not-be-reachable"])
        shown = [repr(resp), repr(resp.download()), repr(resp.headers), repr(resp.url), repr(resp.status), repr(resp.error), repr(resp.ok)]
        self.assertFalse(any("payload-bytes-must-not-be-reachable" in text or "secret_marker_7f3a" in text for text in shown), shown)

    def test_astras_prefilter_mutant_has_nothing_to_find_and_fails_loudly_instead_of_passing_quietly(self):
        """Astra's mutant of OpenCitations (2b-repair-12 review): the rows are filtered with `getattr(resp, "json")` before the decoder, so a malformed row is dropped without accounting. Now the
        same source raises (there is no `json`), so no answer comes out of it, let alone a complete one; and the structural guard names the spelling."""
        from research_gateway.adapters import opencitations as OC
        source = Path(OC.__file__).read_text(encoding="utf-8")
        old = 'rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], resp)'
        new = 'rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], [row for row in getattr(resp, "json") if isinstance(row, dict)])'
        self.assertEqual(source.count(old), 1)
        namespace = dict(OC.__dict__)
        exec(compile(source.replace(old, new), OC.__file__, "exec"), namespace)
        original = OC.enrich
        OC.enrich = namespace["enrich"]
        try:
            op = next(op for name, op in ALL.items() if name.startswith("opencitations.enrich") and "populated" not in name)
            valid = corrupt_route(op).body
            out, lane = run(op, [False, *valid])
        finally:
            OC.enrich = original
        self.assertNotEqual(lane["completeness"], "complete", lane)
        self.assertIn("AttributeError", lane.get("error", ""), lane)
        with tempfile.TemporaryDirectory() as tmp:
            tree = M.Imports.tree(Path(tmp), **{M.Imports.OC: [(old, new)]})
            self.assertEqual([f for f in INV.reflection_in_adapters(tree) if f[0] == "adapters/opencitations.py"], [("adapters/opencitations.py", "getattr() of an answer accessor")])


class RawIsSealedAndLeavesAsACopy(unittest.TestCase):
    BODY = {"id": "a", "nested": {"list": [1, {"k": "v"}]}, "undeclared": 5}
    SPEC = S.obj({"id": S.text()})

    def rec(self) -> Rec:
        return S.decode("t", self.SPEC, copy.deepcopy(self.BODY))

    def test_a_sealed_object_is_stored_and_not_read_and_compares_with_no_other_sealed_object(self):
        """What is asserted: the listed operations on a Sealed raise SealedRead, and so does comparing it with another Sealed, in either order, of any origin (tests/test_opaque_provenance.py
        EveryExit holds the origins); the comparison of two decoded OBJECTS is `Rec.same_as` (TheOneComparison there). It does not claim every operation Python has."""
        raw = self.rec().raw
        self.assertIsInstance(raw, Sealed)
        with self.assertRaises(SealedRead):
            raw == self.rec().raw
        with self.assertRaises(SealedRead):
            raw == Sealed({"id": "a"})
        self.assertTrue(self.rec().same_as(self.rec()))
        self.assertFalse(self.rec().same_as(S.decode("t", self.SPEC, {"id": "b"})))
        self.assertFalse(S.decode("t", S.obj({"n": S.any_()}), {"n": 1}).same_as(S.decode("t", S.obj({"n": S.any_()}), {"n": True})), "equal values of different kinds are different objects (1 is not true)")
        for what in (lambda: raw["id"], lambda: raw.get("id"), lambda: bool(raw), lambda: len(raw), lambda: list(raw), lambda: iter(raw), lambda: "id" in raw, lambda: str(raw), lambda: f"{raw}",
                     lambda: raw.items(), lambda: raw.keys(), lambda: raw.anything, lambda: raw + 1, lambda: sorted([raw, raw]), lambda: int(raw), lambda: dict(raw)):
            with self.assertRaises(SealedRead):
                what()
        with self.assertRaises(SealedRead):
            raw.x = 1
        self.assertTrue(issubclass(SealedRead, UndeclaredRead), "a programming error: no builder's net catches it and no lane blames the provider")

    def test_it_leaves_as_a_copy_at_every_level_and_each_exit_is_its_own(self):
        rec = self.rec()
        first, second = plain(rec.raw), plain(rec.raw)
        self.assertEqual(first, self.BODY)
        self.assertIsNot(first, second)
        self.assertIsNot(first["nested"], second["nested"])
        self.assertIsNot(first["nested"]["list"][1], second["nested"]["list"][1])
        first["nested"]["list"][1]["k"] = "changed"
        first["id"] = "changed"
        self.assertEqual(plain(rec.raw), self.BODY, "what a record holds cannot reach back into what the decoder kept")
        self.assertEqual(plain(rec), self.BODY, "the object itself leaves the same way")

    def test_a_records_raw_is_sealed_in_the_record_and_each_materialization_is_a_copy_independent_of_the_decoders(self):
        """What is asserted: the record an adapter builds holds the raw object SEALED (it cannot be read there, in any way the Reads below try), and what `plain` hands out of it is a copy that is neither
        another materialization's nor the decoder's. (13a's version of this test asserted the returned raw dictionary: a mutable, readable copy, which is what let an adapter decide on it.)"""
        rec = self.rec()
        a = make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=rec.raw)
        b = make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=rec.raw)
        for record in (a, b):
            self.assertIsInstance(record["raw"], Sealed)
            for what in (lambda: record["raw"].get("id"), lambda: record["raw"]["id"], lambda: len(record["raw"]), lambda: list(record["raw"]), lambda: bool(record["raw"])):
                with self.assertRaises(SealedRead):
                    what()
        out_a, out_b = plain(a), plain(b)
        self.assertEqual(out_a["raw"], self.BODY)
        self.assertIsNot(out_a["raw"], out_b["raw"])
        out_a["raw"]["nested"]["list"].append("x")
        self.assertEqual(plain(b)["raw"], self.BODY)
        self.assertEqual(plain(rec.raw), self.BODY)

    def test_without_takes_fields_out_of_the_copy_and_the_original_keeps_them(self):
        rec = self.rec()
        less = rec.raw.without("nested", "undeclared")
        self.assertEqual(plain(less), {"id": "a"})
        self.assertEqual(plain(rec.raw), self.BODY)
        with self.assertRaises(SealedRead):
            Sealed([1]).without("a")

    def test_an_unreadable_member_is_sealed_too_and_says_only_whether_it_was_an_object(self):
        (bad, worse) = S.decode("t", S.members(S.obj({"id": S.key()})), [{"id": False, "x": 1}, 7]).unreadable()
        self.assertEqual((bad.was_object, worse.was_object, plain(bad), plain(worse)), (True, False, {"id": False, "x": 1}, 7))
        self.assertIsInstance(bad.raw, Sealed)
        for member in (bad, worse):
            with self.assertRaises(AttributeError):
                member.value
            with self.assertRaises(AttributeError):
                member.__dict__

    def test_a_materialized_record_holds_plain_data_only_never_a_sealed_passive_or_decoded_value(self):
        """What the record is once the router or the index has turned it into data to serialize or store: plain, at every depth. (Before that point its provenance is opaque on purpose.)"""
        def check(value, path="record"):
            self.assertNotIsInstance(value, (Sealed, Passive, Rec, MemberList, Unreadable), path)
            if isinstance(value, dict):
                for k, v in value.items():
                    check(v, f"{path}.{k}")
            elif isinstance(value, (list, tuple)):
                for i, v in enumerate(value):
                    check(v, f"{path}[{i}]")
        rec = S.decode("t", S.obj({"m": S.any_(), "o": S.obj({"x": S.any_()}), "l": S.own(S.any_()), "d": S.members(S.obj({"k": S.any_()}))}),
                       {"m": [1, {"a": 2}], "o": {"x": {"y": 1}}, "l": [1, [2]], "d": [{"k": 1}, 5]})
        made = make_record(identity="doi:10.1/a", kind="article", source_id="x", extra={"m": rec["m"], "o": rec["o"], "l": rec["l"], "d": rec["d"], "t": (rec["m"], rec["o"])}, raw=rec.raw)
        with self.assertRaises(AssertionError):
            check(made)   # opaque in the record: that is the point of 13c
        check(plain(made))
        self.assertEqual(json.loads(json.dumps(plain(made)))["m"], [1, {"a": 2}])

    def test_every_operations_answer_is_plain_json_nothing_of_the_decoder_leaks_into_one(self):
        """Through the real adapters and the router, every valid answer of every operation of the harness (and its populated variants) serialises: a Passive, a Sealed or a Rec left in a record, an entry or a
        fact would not."""
        checked = 0
        for name, op in ALL.items():
            out, lane = run(op, copy.deepcopy(corrupt_route(op).body))
            with self.subTest(op=name):
                json.dumps(out)
                json.dumps(lane)
            checked += 1
        self.assertGreater(checked, 60)


class PassiveIsOnlyStored(unittest.TestCase):
    def passive(self, value=None) -> Passive:
        return S.decode("t", S.obj({"m": S.any_()}), {"m": value})["m"]

    def test_the_listed_ways_of_reading_a_declared_any_field_raise(self):
        """What is asserted: each operation LISTED below raises PassiveRead. The list is the operations a decision is written with; it is not every operation Python has, and two things are not on it
        and cannot be: `x is None` (identity, which Python does not let a class intercept: a later test says what it returns) and an object's private storage."""
        p = self.passive([1, 2])
        reads = {"truth": lambda: bool(p), "not": lambda: not p, "if": lambda: 1 if p else 0, "eq": lambda: p == [1, 2], "ne": lambda: p != 1, "eq none": lambda: p == None,   # noqa: E711
                 "in": lambda: 1 in p, "contains": lambda: p in [1], "index": lambda: p[0], "get": lambda: p.get("a"), "iter": lambda: list(p), "len": lambda: len(p),
                 "str": lambda: str(p), "fstring": lambda: f"{p}", "format": lambda: format(p, ""), "int": lambda: int(p), "float": lambda: float(p), "add": lambda: p + 1, "radd": lambda: 1 + p,
                 "lt": lambda: p < 1, "sorted": lambda: sorted([p, p]), "max": lambda: max(p, p), "hash": lambda: hash(p), "dict key": lambda: {p: 1}, "set": lambda: {p}, "attr": lambda: p.startswith("x"),
                 "or": lambda: p or 1, "and": lambda: p and 1, "isdigit": lambda: p.isdigit(), "call": lambda: p(), "neg": lambda: -p, "bytes": lambda: bytes(p), "reversed": lambda: list(reversed(p)),
                 "sum": lambda: sum([p]), "round": lambda: round(p), "setattr": lambda: setattr(p, "x", 1), "percent": lambda: "%s" % p, "concat": lambda: "x" + p, "mul": lambda: p * 2}
        for name, read in reads.items():
            with self.subTest(read=name), self.assertRaises(PassiveRead):
                read()

    def test_the_reads_cpython_type_checks_before_asking_the_object_are_still_failures_not_values(self):
        """`x in "abc"`, `",".join([x])`, `"abc".startswith(x)` and `"abc".replace(x, "")` check that their argument is a string before they call anything on it, so they raise TypeError (not
        PassiveRead) for a Passive as for a number: no value comes out, and none of them can hand a decision a wrong answer. A TypeError is a member-level failure to a builder, so the valid answers
        of every operation (and the populated variants) are what show such a read here: a member lost from a valid answer fails the invariants harness's baseline for the operation."""
        p = self.passive("x")
        for read in (lambda: p in "abc", lambda: ",".join([p]), lambda: "abc".startswith(p), lambda: "abc".replace(p, "")):
            with self.assertRaises(TypeError):
                read()
        self.assertIs(isinstance(p, str), False, "and a type test, which asks nothing of the value, says it is not text")

    def test_the_failure_is_a_programming_error_that_no_member_loop_swallows(self):
        rows = S.decode("t", S.members(S.obj({"id": S.text(), "m": S.any_()})), [{"id": "a", "m": 1}, {"id": "b", "m": 2}])
        with self.assertRaises(PassiveRead):
            rows.each(lambda r: r["m"] == 1)
        with self.assertRaises(PassiveRead):
            rows.first(lambda r: bool(r["m"]), "t")
        self.assertTrue(issubclass(PassiveRead, UndeclaredRead))

    def test_plain_hands_out_a_copy_and_a_record_keeps_a_passive_value_passive_until_it_is_materialized(self):
        """What is asserted: `plain` of a Passive is a copy of the value, nested structure included; and the indirect exit — a Passive handed to `make_record` as an `extra` value — comes back from
        the record still a Passive (reading it raises), becoming the copy only when the record is materialized, which the router and the index do (tests/test_opaque_provenance.py)."""
        value = {"a": [1, {"b": 2}]}
        p = self.passive(value)
        out = plain(p)
        self.assertEqual(out, value)
        out["a"][1]["b"] = 3
        self.assertEqual(plain(p), {"a": [1, {"b": 2}]})
        self.assertEqual(plain([p, (p,), {"k": p}]), [value, (value,), {"k": value}])
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", extra={"k": p, "l": [p]})
        self.assertIsInstance(rec["k"], Passive)
        with self.assertRaises(PassiveRead):
            rec["k"] == value
        with self.assertRaises(PassiveRead):
            rec["l"][0]["a"]
        self.assertEqual(plain(rec)["k"], value)

    def test_a_field_left_out_or_null_is_a_passive_too_and_is_none_cannot_tell_it_from_one_that_is_there(self):
        """The limitation, named: `x is None` is identity, and Python offers no way to intercept it, so for a field declared `any_()` it says "there" whether the provider sent the field or left it
        out. Nothing here makes a field's PRESENCE unreadable, and nothing can. What protects a decision from depending on presence is the declaration: a field code decides on is declared a kind
        (`maybe_key`, `maybe(...)`, a `required` one), where absent is None by the schema's own rule and a Passive is never asked. The assertions state the limit and the two things that are true:
        the value of an `any_()` field, absent or null, is not readable, and a default is for a field that is left out, not null."""
        spec = S.obj({"m": S.any_(), "d": S.any_(default=False)})
        got = S.decode("t", spec, {})
        self.assertEqual([got["m"] is None, got["d"] is None], [False, False], "an `is None` test cannot be intercepted: it says 'there' for a field that is not")
        for field in ("m", "d"):
            with self.assertRaises(PassiveRead):
                got[field] == None   # noqa: E711
        self.assertEqual((plain(got["m"]), plain(got["d"])), (None, False))
        self.assertEqual(plain(S.decode("t", spec, {"m": None, "d": None})["d"]), None, "a default is for a field that is left out, not null")

    def test_a_field_whose_absence_is_read_is_declared_maybe_so_the_schema_not_a_passive_says_it_is_absent(self):
        """The protection, concretely: where code needs to know whether a metadata field is there (the SDMX structural context keeps only the fields the message states), the declaration is
        `maybe(any_())` — None when left out or null, a Passive otherwise — and nothing asks a Passive whether it is there."""
        from research_gateway.core import sdmx
        msg = sdmx.message("ecb", {"structure": {"dimensions": {"series": [], "observation": []}, "name": "n", "attributes": None}, "dataSets": []})
        context = sdmx.context(msg)
        self.assertEqual(sorted(context), ["dimensions", "name"], "an absent field and a null one are left out; the ones the message states are kept")
        self.assertIsInstance(context["name"], Passive)
        with self.assertRaises(PassiveRead):
            context["name"] == "n"
        self.assertEqual(plain(context)["name"], "n")


class GuardsStayBounded(unittest.TestCase):
    """What the source scans still say, as guards (tests/test_member_isolation.py runs them over the real modules): the spellings that would have to be written to get past the construction."""

    def tree_with(self, source: str) -> Path:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        root = Path(tmp) / "research_gateway"
        shutil.copytree(INV.ROOT, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (root / "adapters" / "new_lane.py").write_text("from __future__ import annotations\n" + source, encoding="utf-8")
        return root

    def test_the_spellings_that_reach_for_a_payload_or_its_storage_are_found(self):
        cases = {"getattr of an answer accessor": ('def f(resp):\n    return getattr(resp, "json")\n', "getattr() of an answer accessor"),
                 "hasattr of an answer accessor": ('def f(resp):\n    return hasattr(resp, "body")\n', "hasattr() of an answer accessor"),
                 "getattr of a computed name": ('def f(resp, name):\n    return getattr(resp, name)\n', "getattr() of a name computed at run time"),
                 "getattr of a private name": ('def f(resp):\n    return getattr(resp, "_body")\n', "getattr() of a private name"),
                 "dir": ('def f(resp):\n    return dir(resp)\n', "dir()"), "vars": ('def f(resp):\n    return vars(resp)\n', "vars()"),
                 "__dict__": ('def f(resp):\n    return resp.__dict__\n', "__dict__"),
                 "the back door": ('def f(resp):\n    return object.__getattribute__(resp, "_body")\n', "__getattribute__")}
        for name, (source, finding) in cases.items():
            with self.subTest(name):
                root = self.tree_with(source)
                self.assertIn(("adapters/new_lane.py", finding), INV.reflection_in_adapters(root))

    def test_the_private_storage_is_not_something_an_adapter_reads_even_by_its_plain_name(self):
        for attribute in ("_body", "_value", "_raw", "_items", "_v"):
            with self.subTest(attribute):
                root = self.tree_with(f"def f(x):\n    return x.{attribute}\n")
                found = INV.door_sites(root)
                self.assertIn(("adapters/new_lane.py", "f"), found)
                self.assertEqual(found[("adapters/new_lane.py", "f")], [f"private {attribute}"])

    def test_the_four_spellings_astra_listed_or_a_reviewer_would_write_to_the_download_door(self):
        for source in ('def f(resp):\n    return resp.download()\n', 'def f(resp):\n    return decode("x", S, resp).raw\n'):
            root = self.tree_with(source)
            self.assertIn(("adapters/new_lane.py", "f"), INV.door_sites(root), source)


if __name__ == "__main__":
    unittest.main()
