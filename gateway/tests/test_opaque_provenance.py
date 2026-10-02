"""Task 2b-repair-13c (Astra R13A-2): provenance stays opaque THROUGH the canonical record, and becomes plain only where the gateway serializes or stores a result.

13a sealed what the decoder hands an adapter: a Response with no readable payload, a `Sealed` raw object, a `Passive` for every `any_()` field. Astra then wrote a source mutant of the OpenCitations
adapter that needed none of the spellings the source scans looked for:

    copied = make_record(identity="doi:10.1000/copy", kind="citation", source_id=SOURCE_ID, raw=row.raw)["raw"]
    if copied.get("timespan") == {"skip": True}:
        return OMIT

`make_record` returned `plain(record)`, so the dictionary it handed back held the provider's raw object in the clear. `timespan` is declared `any_()`: metadata, never read. The mutant read it, and the
adapter silently dropped the first of three citations while the lane reported `complete`, count 3 → 2. Every import, reflection and read-inventory check passed, and a 565-test run passed with it. The
source scan had been the guarantee. It was a convention: the exit it knew about (`.raw` outside a `raw=` argument) was closed, and the one beside it (the returned copy) was not.

The construction now: `make_record` returns a plain dict whose provenance is still opaque — `raw` is a `Sealed`, every `extra` value built from an `any_()` field is the `Passive` it was, and a
download's bytes are a `Sealed` — and the router turns the whole answer into plain data at one place, after every lane has run and every selection, coverage and licence decision is made
(`router.execute`), as the cache and the index do for what they store (`Cache.put_record`, `harvest/index.upsert`). 2b-repair-14 (Astra R13C-2) finished the constructors: nothing compares a
Sealed with another (`Rec.same_as` is the one comparison, of two decoded objects), a typed field takes its own domain and unwraps nothing, and `make_record` materializes nothing. This file
runs, for every exit the reviews listed:

  * TheCopyEscape          Astra's mutant (tests/test_astra_13a.py runs it as a regression that fails on 2d62753): the scan that cannot see it, and the variants
  * EveryExit              canonical-record construction (raw, extra, a typed field, the identity), `download()`, an unreadable member's raw, equality as a way to read, and `plain` itself
  * TheOneComparison       `Rec.same_as`, the sanctioned equality between two decoded objects
  * ConstructorCompositions  Astra's two R13C-2 mutants through the real adapter and router, each typed field against everything the decoder issues, and what `raw` takes
  * RawIsTheMemberAsSent   a record's raw is the member the fixture wrote, adapter by adapter and through the router
  * WhereItBecomesPlain    before the router's boundary every operation's records still hold `Sealed` raw (nothing between the builder and the router materialized it), after it every answer is plain
                           JSON; the index load writes plain data and never the object's repr
  * TheClientsOwnReads     the client's reads of a Response's bytes on a marker body (the inventory of those reads, with what each is for, is tests/inventory.py's: one owner)

TRUST MODEL B (INVARIANTS B-1; the operator's ruling of 2026-10-02). First-party adapters are trusted, reviewed code; these tests run the known compositions of the public API and the inventory
lists every site where adapter code goes past it. What neither shows, and nothing in Python can: that private storage is unreachable by a name (`Sealed._value`), that `x is None` on a Passive can
be intercepted, that `plain` and `Sealed` cannot be imported, or that a finite corpus proves a family closed. They are documented boundaries of the model, not debts, and no workaround is built
for them. A concrete counterexample within the supported input contract still blocks; a restatement of these boundaries does not.
"""
from __future__ import annotations

import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_gateway.adapters import opencitations as OC
from research_gateway.adapters.base import FakeTransport, Response
from research_gateway.core import router as R
from research_gateway.core import schema as S
from research_gateway.core.canonical import make_record
from research_gateway.core.payload import (MemberList, OMIT, Passive, PassiveRead, PayloadError, Rec, Sealed, SealedRead, Unreadable, UndeclaredRead, plain)
from research_gateway.harvest import index, registries
from tests import inventory as INV
from tests import test_member_isolation as M
from tests.invariant_ops import corrupt_route, oc_row
from tests.test_invariants import ALL, run
from tests.test_astra_13a import COPY_READ, OLD, SKIP_FIRST, lane_with, opencitations_with
from tests.test_openers import Fake, doaj_client, THREE

THREE_IDS = ["doi:10.9000/c1", "doi:10.9000/c2", "doi:10.9000/c3"]


class Judged(unittest.TestCase):
    """A read or a build that must be a programming error (UndeclaredRead): anything else — including the right result — is a FAILURE of the assertion, not an error of the test, so that a mutant that
    removes the construction is killed by an assertion (tools/gen2_gateway_mutations.py)."""

    def raises_exactly(self, error: type, call, label: str = "") -> None:
        """`call` must raise `error`; anything else — another exception, or no exception — is a FAILURE of the assertion, not an error of the test."""
        try:
            call()
        except error:
            return
        except Exception as e:
            self.fail(f"{label}raised {type(e).__name__} where {error.__name__} belongs: {str(e)[:80]}")
        self.fail(f"{label}was accepted")

    def programming_error(self, call, label: str = "") -> None:
        try:
            call()
        except UndeclaredRead:
            return
        except Exception as e:
            self.fail(f"{label}raised {type(e).__name__}, which is a malformed member's loss or a bug, not the programming error an opaque read is: {str(e)[:80]}")
        self.fail(f"{label}was read")


class TheCopyEscape(Judged):
    def test_the_source_scan_still_cannot_see_it_which_is_why_the_scan_is_a_backstop(self):
        """The inventory of reads and the import and reflection checks find nothing in the mutated tree (Astra's own finding). That is unchanged and no longer matters: what stops the mutant is the
        object it reads."""
        source, _ = opencitations_with(OLD, COPY_READ + OLD)
        with tempfile.TemporaryDirectory() as tmp:
            tree = M.Imports.tree(Path(tmp), **{M.Imports.OC: [(OLD, COPY_READ + OLD)]})
            self.assertEqual((INV.import_findings(tree), [f for f in INV.reflection_in_adapters(tree) if f[0] == "adapters/opencitations.py"]), ([], []))
            real = INV.door_sites()
            changed = {k: v for k, v in INV.door_sites(tree).items() if v != real.get(k)}
            self.assertEqual(changed, {}, "the mutant adds no use the inventory lists")

    def test_the_variants_each_fail_where_the_value_is_read(self):
        """The copy is not the only way a record's provenance could be read back: an `extra` value built from the passive field, a typed field built from it, a record's raw tested for truth."""
        row = S.decode("x", S.obj({"id": S.text(), "oci": S.any_(), "timespan": S.any_()}), {"id": "a", "oci": "1-1", "timespan": {"skip": True}})
        rec = make_record(identity="doi:10.1000/x", kind="citation", source_id="x", extra={"timespan": row["timespan"], "both": [row["oci"], row["timespan"]]}, raw=row.raw)
        for label, read in {"the extra, compared": lambda: rec["timespan"] == {"skip": True}, "the extra, tested for truth": lambda: bool(rec["timespan"]),
                            "the extra, inside a list": lambda: rec["both"][1] == {"skip": True}, "the extra, formatted": lambda: f"{rec['timespan']}",
                            "the raw, read as a mapping": lambda: rec["raw"].get("timespan"), "the raw, subscripted": lambda: rec["raw"]["timespan"],
                            "the raw, tested for truth": lambda: bool(rec["raw"]), "the raw, iterated": lambda: list(rec["raw"]), "the raw, its length": lambda: len(rec["raw"])}.items():
            with self.subTest(label):
                self.programming_error(read, "a read of provenance ")
        self.assertFalse(rec["raw"] == {"timespan": {"skip": True}}, "compared with a plain value it is not equal, and asking read nothing")
        for label, build in {"a title": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", title=row["timespan"]),
                             "a venue": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", venue=row["timespan"]),
                             "an authors list": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", authors=[row["timespan"]]),
                             "a links list": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", links=(row["oci"],)),
                             "identifiers": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", identifiers={"doi": row["oci"]}),
                             "a year": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", year=row["oci"]),
                             "a licence": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", license=row["oci"]),
                             "the identity": lambda: make_record(identity=row["oci"], kind="citation", source_id="x"),
                             "a title built from the raw": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", title=row.raw)}.items():
            with self.subTest(f"{label} is a typed field: it refuses an opaque value"):
                self.programming_error(build, "a record built from an opaque value ")

    def test_each_variant_run_through_the_real_adapter_and_router_is_never_a_complete_lane(self):
        variants = {"the extra, compared": ('    return make_record(identity=f"doi:{doi}", kind="citation", source_id=SOURCE_ID, year=year_from(row["creation"]),\n',
                                           '    if make_record(identity="doi:10.1000/x", kind="citation", source_id=SOURCE_ID, extra={"t": row["timespan"]})["t"] == "P1Y":\n        return OMIT\n'
                                           '    return make_record(identity=f"doi:{doi}", kind="citation", source_id=SOURCE_ID, year=year_from(row["creation"]),\n'),
                    "the raw, tested": (OLD, '    if make_record(identity="doi:10.1000/x", kind="citation", source_id=SOURCE_ID, raw=row.raw)["raw"]:\n        return OMIT\n' + OLD)}
        for label, (old, new) in variants.items():
            _, enrich = opencitations_with(old, new)
            out, lane = lane_with(enrich, [oc_row(i, "citing") for i in (1, 2, 3)])
            with self.subTest(label):
                self.assertNotEqual(lane["completeness"], "complete", lane)
                self.assertRegex(lane.get("error", ""), "SealedRead|PassiveRead")


class EveryExit(Judged):
    """The indirect exits of the review: canonical-record construction, `download()`, and the ones beside them."""

    def decoded(self):
        return S.decode("x", S.obj({"id": S.text(), "m": S.any_(), "inner": S.obj({"k": S.any_()}), "l": S.own(S.any_())}), {"id": "a", "m": [1, {"a": 2}], "inner": {"k": 5}, "l": [1, [2]]})

    def test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance(self):
        d = self.decoded()
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", title="T", authors=["A"], year=2020, venue="V", identifiers={"doi": "10.1/a"}, links=["u"], license="CC0",
                          extra={"m": d["m"], "inner": d["inner"], "l": d["l"], "pair": (d["m"], 1), "typed": [1, 2], "nested": {"deep": [d["m"]]}}, raw=d.raw)
        self.assertIs(type(rec), dict)
        self.assertEqual({k: v for k, v in rec.items() if k in ("title", "authors", "year", "venue", "identifiers", "links", "license")},
                         {"title": "T", "authors": ["A"], "year": 2020, "venue": "V", "identifiers": {"doi": "10.1/a"}, "links": ["u"], "license": "CC0"})
        self.assertIsInstance(rec["raw"], Sealed)
        self.assertIsInstance(rec["m"], Passive)
        self.assertIsInstance(rec["l"], list)   # an own list of Passives is a list of Passives: the structure is plain, each element opaque
        self.assertTrue(all(isinstance(x, Passive) for x in rec["l"]))
        self.assertIsInstance(rec["pair"][0], Passive)
        self.assertIsInstance(rec["nested"]["deep"][0], Passive)
        self.assertEqual((rec["typed"], plain(rec["typed"])), ([1, 2], [1, 2]), "an extra value that holds nothing opaque is just plain data")
        self.assertIsInstance(rec["inner"], Rec, "a decoded object kept in an extra stays the Rec: its declared fields read, its undeclared ones do not, its raw is sealed")
        self.programming_error(lambda: rec["inner"]["k"] == 5)

    def test_extra_is_a_copy_of_the_structure_and_never_an_alias_of_the_adapters_list(self):
        mine = [1, [2, 3]]
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", extra={"a": mine})
        mine[1].append(4)
        self.assertEqual(rec["a"], [1, [2, 3]])

    def test_the_materialized_record_is_what_the_old_constructor_returned(self):
        """`plain(record)` is the dictionary `make_record` used to return: same keys, same values, JSON-serializable, and a copy at every level."""
        d = self.decoded()
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", extra={"m": d["m"], "inner": d["inner"], "l": d["l"]}, raw=d.raw)
        out = plain(rec)
        self.assertEqual(json.loads(json.dumps(out))["m"], [1, {"a": 2}])
        self.assertEqual((out["raw"], out["l"], out["inner"]), ({"id": "a", "m": [1, {"a": 2}], "inner": {"k": 5}, "l": [1, [2]]}, [1, [2]], {"k": 5}),
                         "a Rec in an extra leaves as the object the provider sent for it")
        self.assertIsNot(plain(rec)["raw"], out["raw"], "each materialization is its own copy")
        out["raw"]["m"].append("changed")
        self.assertEqual(plain(rec)["raw"]["m"], [1, {"a": 2}], "what a materialized record holds cannot reach back into what the decoder kept")
        self.assertEqual(plain(d.raw)["m"], [1, {"a": 2}])

    def test_a_raw_that_is_a_plain_value_is_sealed_too(self):
        """The snapshot loader and tests hand `make_record` a plain dict: it is sealed here (as a copy), so a record's raw is opaque whoever made it."""
        mine = {"k": [1]}
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=mine)
        mine["k"].append(2)
        self.assertIsInstance(rec["raw"], Sealed)
        self.assertEqual(plain(rec["raw"]), {"k": [1]})
        self.assertIsNone(make_record(identity="doi:10.1/a", kind="article", source_id="x")["raw"], "a record with no raw says so")

    def test_a_download_is_sealed_and_only_the_router_boundary_makes_it_bytes(self):
        resp = Response(200, {"content-type": "application/octet-stream"}, b"secret-bytes-7f3a", "https://example.org/f")
        got = resp.download()
        self.assertIsInstance(got, Sealed)
        for label, read in {"len": lambda: len(got), "bytes": lambda: bytes(got), "decode": lambda: got.decode(), "index": lambda: got[0], "iterate": lambda: list(got), "startswith": lambda: got.startswith(b"s"),
                            "truth": lambda: bool(got), "in": lambda: b"s" in got, "str": lambda: str(got), "format": lambda: f"{got}", "hash": lambda: hash(got), "add": lambda: got + b"x",
                            "equal to bytes": lambda: got == b"secret-bytes-7f3a" or got.attribute}.items():
            with self.subTest(label):
                self.programming_error(read, "a read of a download ")
        self.assertEqual(repr(got), "<Sealed>")
        self.assertEqual(plain(got), b"secret-bytes-7f3a")

    def test_an_unreadable_members_raw_and_a_rec_raw_and_without_are_sealed(self):
        (bad,) = S.decode("x", S.members(S.obj({"id": S.key()})), [{"id": False, "x": 1}]).unreadable()
        rec = S.decode("x", S.obj({"id": S.text()}), {"id": "a", "extra": {"k": 1}})
        for raw in (bad.raw, rec.raw, rec.raw.without("extra")):
            self.assertIsInstance(raw, Sealed)
            self.programming_error(lambda: raw.get("id"))

    def test_no_two_sealed_objects_compare_whoever_made_them_and_a_sealed_equals_no_plain_value(self):
        """What is asserted: comparing two Sealed objects is a SealedRead whatever made them — a decoded object's raw, a record's raw built from a literal or a Passive (`make_record`), a download,
        `without()`, an adapter's own constructor call — in either order; and a Sealed is not equal to a plain value or to None, whatever it holds (asking reads nothing). Equality of Sealed objects
        was how a guess could read a raw object (Astra R13A-2, R13C-2), and it was permitted between objects 'the decoder issued' by a flag `make_record` set for any raw it was given: there is
        no such comparison now, so there is no flag. The one comparison of provider data is `Rec.same_as` (TheOneComparison below). This does not show that no other composition of the public
        API reads a raw object; the routed mutants of ConstructorCompositions are the known ones, and the inventory (tests/inventory.py) lists what may be written."""
        row = S.decode("x", S.obj({"id": S.text(), "m": S.any_()}), {"id": "a", "m": {"skip": True}})
        made = {"a decoded object's raw": row.raw, "a record's raw from a literal": make_record(identity="doi:10.1/a", kind="article", source_id="x", raw={"skip": True})["raw"],
                "a record's raw from a Passive": make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=row["m"])["raw"],
                "a record's raw from a decoded object": make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=row.raw)["raw"],
                "a download": Response(200, {}, b"bytes", "u").download(), "without()": row.raw.without("id"), "a constructor call": Sealed({"skip": True})}
        for (first, a), (second, b) in [(x, y) for x in made.items() for y in made.items()]:
            with self.subTest(f"{first} / {second}"):
                self.programming_error(lambda: a == b, "a comparison of two sealed objects ")
                self.programming_error(lambda: a != b, "a comparison of two sealed objects ")
        for label, a in made.items():
            with self.subTest(label):
                self.assertFalse(a == {"skip": True})
                self.assertFalse(a == None)   # noqa: E711
                self.assertFalse(a == b"bytes")
                self.assertTrue(a != {"id": "a"})

    def test_a_decoded_object_compares_with_nothing_and_is_not_hashable(self):
        a, b = (S.decode("x", S.obj({"id": S.text()}), {"id": "a"}) for _ in range(2))
        for label, compare in {"with another decoded object": lambda: a == b, "with a plain value": lambda: a == {"id": "a"}, "with None": lambda: a == None,   # noqa: E711
                               "with its own raw": lambda: a == a.raw, "inequality": lambda: a != b}.items():
            with self.subTest(label):
                self.programming_error(compare, "a comparison of a decoded object ")
        with self.assertRaises(TypeError):
            hash(a)


    def test_a_decoded_object_kept_in_a_record_is_not_a_way_to_its_raw(self):
        rec = S.decode("x", S.obj({"id": S.text()}), {"id": "a", "hidden": 1})
        self.programming_error(lambda: rec["hidden"])
        self.assertEqual(rec["id"], "a")
        self.assertIsInstance(rec.raw, Sealed)

    def test_constructing_a_sealed_a_passive_or_a_rec_in_a_provider_module_is_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "adapters").mkdir()
            (root / "core").mkdir()
            for name in ("schema", "sdmx", "identity"):
                (root / "core" / f"{name}.py").write_text("")
            (root / "adapters" / "new_lane.py").write_text(
                "from ..core.payload import Sealed, Passive, Rec\n\ndef guess(raw):\n    return raw == Sealed({'a': 1})\n\ndef issue():\n    return Sealed({'a': 1})\n\ndef make():\n    return Passive(1)\n\ndef rec():\n    return Rec({}, {'skip': True})\n")
            found = {fn: sorted(v) for (_, fn), v in INV.door_sites(root).items() if fn != "<module>"}
        self.assertEqual(found, {"guess": ["call Sealed"], "issue": ["call Sealed"], "make": ["call Passive"], "rec": ["call Rec"]})


class TheOneComparison(Judged):
    """`Rec.same_as`: the sanctioned equality between two DECODED provider objects (did the provider repeat itself: Unpaywall's best location also listed). It tells a relation between two things
    the provider sent; there is nothing in the API that relates a provider's object to a value an adapter chose."""

    SPEC = S.obj({"id": S.text(), "n": S.any_()})

    def rec(self, body):
        return S.decode("x", self.SPEC, body)

    def test_the_same_object_twice_is_the_same_and_a_different_one_is_not(self):
        a = self.rec({"id": "a", "n": [1, {"k": 2}]})
        self.assertTrue(a.same_as(self.rec({"id": "a", "n": [1, {"k": 2}]})))
        self.assertTrue(a.same_as(a))
        for other in ({"id": "b", "n": [1, {"k": 2}]}, {"id": "a", "n": [1, {"k": 3}]}, {"id": "a", "n": [1, {"k": 2}], "extra": 0}, {"id": "a"}, {"id": "a", "n": [1, {"k": 2.0}]},
                      {"id": "a", "n": [True, {"k": 2}]}):
            with self.subTest(other=other):
                self.assertFalse(a.same_as(self.rec(other)))

    def test_it_takes_two_decoded_objects_and_nothing_else(self):
        a = self.rec({"id": "a"})
        for other in (a.raw, {"id": "a"}, None, "a", Sealed({"id": "a"}), make_record(identity="doi:10.1/a", kind="article", source_id="x", raw={"id": "a"})["raw"]):
            with self.subTest(other=repr(other)[:30]), self.assertRaises(TypeError):
                a.same_as(other)

    def test_it_reads_nothing_it_returns_one_bit_about_two_provider_objects(self):
        a, b = self.rec({"id": "a", "n": {"secret": 1}}), self.rec({"id": "a", "n": {"secret": 1}})
        self.assertIs(a.same_as(b), True)
        self.assertEqual(repr(a), "<Rec id, n>")
        self.programming_error(lambda: a["n"] == {"secret": 1})


class ConstructorCompositions(Judged):
    """Astra's R13C-2: two public constructor compositions a source mutant of the OpenCitations adapter used to let provenance decide which of three citations were kept — each without a private
    name, `plain`, `Sealed` or `_issued`, so that every source scan passed — and both returned a COMPLETE lane of two. They fail safely now: the lane is not complete, names the read, and has no
    count; the valid adapter keeps all three. These are the known compositions of the typed fields and `raw` (the trust model's reviewed-code boundary, INVARIANTS B-1, keeps the rest to review
    and the inventory); the unit cases below are the typed domain of each field and the one thing `raw` takes."""

    THREE = [oc_row(i, "citing") for i in (1, 2, 3)]
    BODY = [{**oc_row(1, "citing"), "timespan": "P999Y"}, oc_row(2, "citing"), oc_row(3, "citing")]
    EQUALITY = ('    copied = make_record(identity="doi:10.1000/copy", kind="citation", source_id=SOURCE_ID, raw=row["timespan"])["raw"]\n'
                '    guessed = make_record(identity="doi:10.1000/guess", kind="citation", source_id=SOURCE_ID, raw={"skip": True})["raw"]\n'
                '    if copied == guessed:\n        return OMIT\n')
    CONTAINER = '    if make_record(identity="doi:10.1000/x", kind="citation", source_id=SOURCE_ID, identifiers=row)["identifiers"].get("timespan") == "P999Y":\n        return OMIT\n'

    def assert_fails_safely(self, new: str, body, error: str):
        _, enrich = opencitations_with(OLD, new + OLD)
        _, lane = lane_with(enrich, body)
        self.assertNotEqual(lane["completeness"], "complete", lane)
        self.assertEqual((lane["coverage"], "count" in lane), ("provider_unavailable", False), lane)
        self.assertIn(error, lane.get("error", ""), lane)

    def test_control_the_valid_adapter_keeps_all_three(self):
        _, lane = lane_with(OC.enrich, self.BODY)
        self.assertEqual((lane["coverage"], lane["completeness"], lane["count"], lane["retrieved"]), ("searched_ok", "complete", 3, THREE_IDS))

    def test_a_literal_passed_as_raw_has_no_comparison_with_a_decoded_object(self):
        self.assert_fails_safely(self.EQUALITY, self.BODY, "SealedRead")
        self.assert_fails_safely(self.EQUALITY, self.THREE, "SealedRead")   # it fails on the comparison, not on the data

    def test_a_decoded_object_passed_as_a_typed_container_is_not_unwrapped_into_its_original(self):
        self.assert_fails_safely(self.CONTAINER, self.BODY, "SealedRead")
        self.assert_fails_safely(self.CONTAINER, self.THREE, "SealedRead")

    def test_the_original_copy_escape_still_fails_safely(self):
        _, enrich = opencitations_with(OLD, COPY_READ + OLD)
        _, lane = lane_with(enrich, SKIP_FIRST)
        self.assertNotEqual(lane["completeness"], "complete", lane)
        self.assertIn("SealedRead", lane.get("error", ""), lane)

    def test_the_scans_see_neither_composition_which_is_why_the_constructors_are_what_stops_them(self):
        for new in (self.EQUALITY, self.CONTAINER):
            with tempfile.TemporaryDirectory() as tmp:
                tree = M.Imports.tree(Path(tmp), **{M.Imports.OC: [(OLD, new + OLD)]})
                real = INV.door_sites()
                self.assertEqual((INV.import_findings(tree), [f for f in INV.reflection_in_adapters(tree) if f[0] == "adapters/opencitations.py"],
                                  {k: v for k, v in INV.door_sites(tree).items() if v != real.get(k)}), ([], [], {}))

    def test_each_typed_field_takes_its_own_domain_and_never_unwraps_what_the_decoder_issued(self):
        row = S.decode("x", S.obj({"id": S.text(), "m": S.any_(), "tags": S.own(S.text()), "rows": S.members(S.obj({"id": S.text()}))}), {"id": "a", "m": 1, "tags": ["t"], "rows": [{"id": "b"}]})
        (unreadable,) = S.decode("x", S.members(S.obj({"id": S.key()})), [{"id": False}]).unreadable()
        fields = ("title", "venue", "license", "attribution", "authors", "links", "identifiers", "year")
        decoder_issued = {"a decoded object": (row, SealedRead), "a passive value": (row["m"], PassiveRead), "a sealed raw": (row.raw, SealedRead), "a list of members": (row["rows"], UndeclaredRead),
                          "an unreadable member": (unreadable, PayloadError)}
        for field in fields:
            for label, (value, error) in decoder_issued.items():
                for shape, wrap in (("bare", lambda v: v), ("in a list", lambda v: [v]), ("in a map", lambda v: {"k": v})):
                    with self.subTest(field=field, value=label, shape=shape):
                        self.raises_exactly(error, lambda: make_record(identity="doi:10.1/a", kind="article", source_id="x", **{field: wrap(value)}))

    def test_the_identity_takes_text_not_what_the_decoder_issued(self):
        row = S.decode("x", S.obj({"id": S.text(), "m": S.any_()}), {"id": "a", "m": "x"})
        for label, value, error in (("a decoded object", row, SealedRead), ("a passive value", row["m"], PassiveRead), ("a sealed raw", row.raw, SealedRead)):
            with self.subTest(label):
                self.raises_exactly(error, lambda: make_record(identity=value, kind="article", source_id="x"))

    def test_control_the_typed_domains_are_taken_whole(self):
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", title="T", venue="V", license="CC0", attribution="A", authors=["a", None, "b"], links=("u", "v"),
                          identifiers={"doi": "10.1/a", "pmid": None}, year="2020")
        self.assertEqual((rec["title"], rec["venue"], rec["license"], rec["attribution"], rec["authors"], rec["links"], rec["identifiers"], rec["year"]),
                         ("T", "V", "CC0", "A", ["a", "b"], ["u", "v"], {"doi": "10.1/a"}, 2020))
        for field, wrong in (("title", 5), ("venue", False), ("license", ["x"]), ("authors", "ab"), ("authors", [1]), ("links", {"k": "v"}), ("identifiers", ["x"]), ("identifiers", {"k": 1}), ("year", "x"),
                             ("year", True)):
            with self.subTest(field=field, wrong=repr(wrong)), self.assertRaises(PayloadError):
                make_record(identity="doi:10.1/a", kind="article", source_id="x", **{field: wrong})

    def test_a_raw_is_sealed_as_it_is_without_being_materialized_or_read(self):
        """`make_record` is not a materializer: the raw it is given — a literal, a decoded object, a Passive, a list of them — is carried inside a Sealed that nothing in the record's reach reads."""
        row = S.decode("x", S.obj({"id": S.text(), "m": S.any_()}), {"id": "a", "m": {"deep": [1]}})
        for label, raw in {"a literal": {"skip": True}, "a decoded object": row, "a passive value": row["m"], "a list holding one": [row["m"], {"k": row["m"]}], "bytes": b"x"}.items():
            with self.subTest(label):
                rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=raw)
                self.assertIsInstance(rec["raw"], Sealed)
                self.programming_error(lambda: rec["raw"].get("skip"))
                self.programming_error(lambda: rec["raw"]["skip"])
                self.programming_error(lambda: bool(rec["raw"]))
        self.assertEqual(plain(make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=row)["raw"]), {"id": "a", "m": {"deep": [1]}})
        self.assertEqual(plain(make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=[row["m"], {"k": row["m"]}])["raw"]), [{"deep": [1]}, {"k": {"deep": [1]}}])


class WhereItBecomesPlain(Judged):
    def test_before_the_routers_boundary_every_operations_records_still_hold_a_sealed_raw(self):
        """Nothing between the builder and the router materialized provenance: with the boundary's `plain` turned off, every record of every operation of the harness (and its populated variants)
        carries a Sealed raw (or none), and the answer is not JSON — it is the boundary that makes it so."""
        checked = sealed = 0
        for name, op in ALL.items():
            with mock.patch.object(R, "plain", lambda x: x):
                out, _ = run(op, copy.deepcopy(corrupt_route(op).body))
            for rec in out.get("records") or []:
                checked += 1
                with self.subTest(op=name, identity=rec.get("identity")):
                    self.assertTrue(rec.get("raw") is None or isinstance(rec["raw"], Sealed), type(rec.get("raw")))
                    sealed += isinstance(rec.get("raw"), Sealed)
            if out.get("records") and any(isinstance(r.get("raw"), Sealed) for r in out["records"]):
                with self.assertRaises((TypeError, PassiveRead, SealedRead)):
                    json.dumps(out)   # the answer is not JSON until the boundary makes it so
        self.assertGreater(checked, 80)
        self.assertGreater(sealed, 60)

    def test_after_it_every_operations_answer_is_plain_json_with_no_sealed_passive_or_decoded_object_left(self):
        """What is asserted: the router's answer to every operation of the harness (and its populated variants) round-trips through JSON, no record's `raw` is a Sealed or a Passive, no top-level
        value of a record is a decoder-issued object, and a record survives the round trip. It does NOT say a `raw` is what the provider sent: that is RawIsTheMemberAsSent's, which compares it
        with the fixture's own object at record boundaries the fixture defines."""
        for name, op in ALL.items():
            out, _ = run(op, copy.deepcopy(corrupt_route(op).body))
            with self.subTest(op=name):
                try:
                    again = json.loads(json.dumps(out))
                except Exception as e:
                    self.fail(f"the answer is not plain JSON: {type(e).__name__}: {str(e)[:80]}")
                for rec in out.get("records") or []:
                    self.assertFalse(isinstance(rec.get("raw"), (Sealed, Passive)))
                    for k, v in rec.items():
                        self.assertNotIsInstance(v, (Sealed, Passive, Rec, MemberList, Unreadable), k)
                self.assertEqual(len(again.get("records") or []), len(out.get("records") or []))

    def test_a_downloads_bytes_are_sealed_until_the_router_boundary_and_bytes_after_it(self):
        from tests.test_routing import ADAPTERS, SEED
        from research_gateway.adapters.base import Client
        from research_gateway.core.broker import Broker, RatePolicy
        seed = copy.deepcopy(SEED)
        for entry in seed:
            if entry["id"] in ("huggingface", "globe"):
                entry["enabled"] = True
        router = R.Router(seed, ADAPTERS)
        transport = FakeTransport()
        transport.add("GET", "https://huggingface.co/api/datasets/owner/corpus", body={"id": "owner/corpus", "cardData": {"license": "cc0-1.0"}, "siblings": [{"rfilename": "data.csv"}], "gated": False})
        transport.add("GET", "https://huggingface.co/datasets/owner/corpus/resolve/main/data.csv", body="a,b\n1,2\n")
        client = Client(broker=Broker({"huggingface": RatePolicy(per_second=100)}), transport=transport, sleep=lambda s: None)
        request = {"request_type": "fetch", "target": "hf:owner/corpus", "params": {"path": "data.csv", "download": True}}
        with mock.patch.object(R, "plain", lambda x: x):
            before = R.execute(router, request, client)
        self.assertIsInstance(before["content"], Sealed, "nothing before the boundary made the bytes readable")
        after = R.execute(router, request, client)
        self.assertEqual(after["content"], b"a,b\n1,2\n")

    def load(self, stream, source: str, **kw):
        """(count, the fake database) of an index load; a load that raises is a FAILURE of the assertion that it writes plain data, not an error of the test's setup."""
        db = Fake()
        try:
            return index.load(db, stream, source, **kw), db
        except Exception as e:
            self.fail(f"the load raised {type(e).__name__}: {str(e)[:100]}")

    def test_the_index_load_writes_plain_data_never_the_object_it_holds(self):
        """The loaders yield records whose provenance is sealed; `index.upsert` is the storage boundary. The statements it executes hold the provider's row and the metadata as JSON, and no repr."""
        n, db = self.load(lambda: registries.doaj_journals(doaj_client(THREE.encode())), "doaj", metadata_license="CC0")
        self.assertEqual(n, 3)
        arguments = [json.dumps(args, default=str) for sql, args in db.statements if args and "record_sources" in sql]
        self.assertEqual(len(arguments), 3)
        for text in arguments:
            self.assertNotIn("<Sealed>", text)
            self.assertNotIn("<Passive>", text)
        self.assertIn("Journal ISSN (print version)", arguments[0], "the stored raw is the provider's row")
        canonical = [json.loads(args[2]) for sql, args in db.statements if args and "gateway.records" in sql and "INSERT" in sql]
        self.assertEqual([c["in_doaj"] for c in canonical], [True, True, True])

    def test_the_cache_is_a_storage_boundary_too_in_memory_and_in_the_database(self):
        """`Cache.put_record` persists a record's raw: a record built straight from an adapter or a loader, with its provenance still sealed, is made plain there (the router's answer already is)."""
        from research_gateway.core.cache import Cache
        d = S.decode("x", S.obj({"id": S.text(), "m": S.any_()}), {"id": "a", "m": [1, {"a": 2}]})
        record = make_record(identity="doi:10.1/a", kind="article", source_id="crossref", title="T", license="CC0", extra={"m": d["m"]}, raw=d.raw)
        self.assertIsInstance(record["raw"], Sealed)
        db = Fake()
        cache = Cache()
        cache.conn = db   # a database that records what it is asked (the constructor's own check of the stored rows is not what is tested)
        try:
            cache.put_record(record, storable=True, persist_members=[0])
        except Exception as e:
            self.fail(f"the cache raised {type(e).__name__}: {str(e)[:100]}")
        written = [json.dumps(args, default=str) for sql, args in db.statements if args]
        self.assertTrue(written and not any("<Sealed>" in text or "<Passive>" in text for text in written), written)
        (stored_raw,) = [json.loads(args[2]) for sql, args in db.statements if args and "record_sources" in sql]
        self.assertEqual(stored_raw, {"id": "a", "m": [1, {"a": 2}]}, "the stored raw is the provider's object")
        kept = cache.get_record("doi:10.1/a")
        self.assertEqual(kept["m"], [1, {"a": 2}])
        self.assertEqual(kept["raw"], {"id": "a", "m": [1, {"a": 2}]})
        self.assertIsNot(kept, record, "the cache keeps its own copy")

    def test_the_index_load_of_a_crossref_page_stores_the_passive_counts_as_plain_numbers(self):
        from tests.test_harvest import CROSSREF_PAGE, client
        c, t = client()
        t.add("GET", "https://api.crossref.org/journals?", body=CROSSREF_PAGE)
        _, db = self.load(lambda: registries.crossref_journals(c), "crossref", metadata_license="x")
        canonical = [json.loads(args[2]) for sql, args in db.statements if args and "gateway.records" in sql and "INSERT" in sql]
        self.assertEqual(canonical[0]["works_count"], 1234, "an `any_()` count, stored as the number the provider sent")


class RawIsTheMemberAsSent(Judged):
    """A record's `raw` is the provider's member exactly as it was sent (I-8). Each case compares it, after the sink that materializes it, with the object the FIXTURE wrote — the member boundary
    is the fixture's, not the adapter's — through the adapter alone and through the router. Raw-storage fidelity is a property worth its own assertion, since the constructors seal a raw and
    materialize nothing (ConstructorCompositions) and the sinks do the unwrapping."""

    def test_crossref_a_works_raw_is_the_item(self):
        from tests.test_adapters_articles import CROSSREF_WORK, client
        c, t = client()
        t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
        from research_gateway.adapters import crossref
        (record,) = crossref.find(c, "reranking", limit=1)["records"]
        self.assertEqual(plain(record)["raw"], CROSSREF_WORK)
        self.assertIsNot(plain(record)["raw"], CROSSREF_WORK, "a copy, not the fixture's own object")

    def test_opencitations_each_citations_raw_is_its_row_both_through_the_adapter_and_the_router(self):
        rows = [oc_row(i, "citing") for i in (1, 2, 3)]
        from tests.test_adapters_articles import client
        c, t = client()
        t.add("GET", "https://api.opencitations.net/index/v2/citations/", body=rows)
        items = OC.enrich(c, "doi:10.1000/a1", "citations")["items"]
        self.assertEqual([plain(r)["raw"] for r in items], rows)
        out, lane = run(ALL["opencitations.enrich citations"], copy.deepcopy(rows))
        self.assertEqual((lane["completeness"], [r["raw"] for r in out["records"]]), ("complete", rows))

    def test_a_doaj_dumps_raw_is_each_row_by_its_columns(self):
        header = ["Journal title", "Journal ISSN (print version)", "Publisher", "Journal license"]
        want = [dict(zip(header, cells)) for cells in (["First", "9999-9991", "P", "CC-BY"], ["Second", "9999-9983", "Q", "CC-BY"], ["Third", "9999-9975", "R", "CC-BY"])]
        self.assertEqual([plain(r)["raw"] for r in registries.doaj_journals(doaj_client(THREE.encode()))], want)

    def test_a_snapshot_lines_raw_is_the_source_object(self):
        from tests.test_harvest import OPENALEX_SOURCES
        from research_gateway.harvest import openalex_snapshot as snap
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "part_000.jsonl").write_text("".join(json.dumps(o) + "\n" for o in OPENALEX_SOURCES[:2]), encoding="utf-8")
            got = [plain(r)["raw"] for r in snap.read_snapshot(Path(tmp), report=snap.LineReport())]
        self.assertEqual(got, OPENALEX_SOURCES[:2])

    def test_unpaywall_each_locations_raw_is_the_location_object(self):
        from tests.test_adapters_articles import client
        from research_gateway.adapters import unpaywall
        locations = [{"url_for_pdf": "https://a.example/x.pdf", "url": "https://a.example/x", "host_type": "publisher", "version": "publishedVersion", "license": "cc-by"},
                     {"url_for_pdf": None, "url": "https://b.example/y", "host_type": "repository", "version": "acceptedVersion", "license": None}]
        c, t = client()
        t.add("GET", "https://api.unpaywall.org/v2/", body={"oa_locations": locations, "best_oa_location": locations[0], "title": "T", "year": 2020, "journal_name": "J", "is_oa": True, "oa_status": "gold"})
        items = unpaywall.enrich(c, "doi:10.1000/a1")["items"]
        self.assertEqual([plain(r)["raw"] for r in items], locations)
        self.assertEqual([plain(r)["is_best"] for r in items], [True, False], "the best location is the one the provider repeated: Rec.same_as, between two decoded objects")


class TheClientsOwnReads(unittest.TestCase):
    """The client reads a Response's bytes in the places tests/inventory.py lists as kind `body` (the decoder's two, and the client's: a count for the call log, an HTML refusal, a failure's text, a
    diagnostic, the sealed download, the test transport's copy), each classified there. That listing — held by tests/test_inventory.py — is what says which reads exist and what each is FOR.
    This test is the behaviour of the client's reads on a marker body, and claims no more."""

    def test_the_count_and_the_html_check_are_the_clients_bookkeeping_and_its_diagnostics_and_failure_class_show_no_payload(self):
        """What is asserted, for a body that holds a marker: `_count_of` returns the number of results (3) and `check` returns True — a count and a boolean, which the call log and the lane's
        availability use and which are decision-usable by design (they are the client's accounting of the CALL, classified BOOKKEEPING and CLIENT-READ in the inventory); neither
        `repr(Response)` nor the failure class `calllog.classify` derives from a 403 body (through `_text_of`) shows the marker. What it does not assert is that the count or the boolean
        cannot influence an adapter: nothing here, and nothing in Python, shows that; the inventory shows that no provider-data module reads `_body` at all."""
        from research_gateway.adapters import base
        from research_gateway.core import calllog
        body = b'{"results": [{"secret_marker_7f3a": 1}, 2, 3]}'
        resp = Response(200, {"content-type": "application/json"}, body, "https://example.org/x")
        self.assertEqual(base._count_of(resp), 3)
        self.assertIs(base.check("x", resp), True)
        self.assertNotIn("secret_marker_7f3a", repr(resp))
        refused = Response(403, {}, b"Forbidden secret_marker_7f3a", "https://example.org/x")
        self.assertNotIn("secret_marker_7f3a", repr(refused))
        failure = calllog.classify(refused.status, network_error=False, body=base._text_of(refused)[:2000])
        self.assertIsInstance(failure, str)
        self.assertNotIn("secret_marker_7f3a", failure)
        self.assertEqual(base._text_of(refused), "Forbidden secret_marker_7f3a", "the text the client reads is the body, for the failure's class and nothing else (it never leaves the client: the inventory lists its one reader)")


if __name__ == "__main__":
    unittest.main()
