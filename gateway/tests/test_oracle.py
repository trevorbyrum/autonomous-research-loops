"""Task 2b-repair-10a: independent oracles, run beside the harness's metamorphic invariants (tests/test_invariants.py).

The metamorphic harness holds an answer to statements about how a CORRUPTION of a valid answer may differ from the valid answer. That cannot see a defect
the valid answer already has, and it shared its blind spots with the code under test (Astra's R9-1, R9-4, R9-5). These tests hold the gateway to statements
written from specifications, documentation and fixtures (tests/oracle/*), by an author who did not read the adapters, payload, SDMX or canonical code (a qualified, source-based
oracle: tests/oracle/__init__.py and evidence/2b-repair-11a/independence-statement.md say what that does and does not mean):

  LinkConformance          RFC 3986 / RFC 8288 vectors through the real adapter and router: a next URL, a known absence, or neither        (R9-1)
  ExpectedCanonicalFields  the identities and canonical fields every valid answer must produce, hand-written, for every operation and populated variant  (R9-4)
  PopulatedVariantsAreCorrupted  (the variants themselves run in test_invariants: tests/invariant_ops.py appends them)                      (R9-2)
  OpenMlLicence            a present wrong-kind `licence` is neither erased nor replaced by the other spelling                                (R9-2)
  Catalogues               BIS and ECB catalogue cases, executed, with the answers the SDMX messages say                                     (R9-5)
  RegistryLoaders          the venue and repository records the Tier 0 loaders must produce
  ExecutedCoverage         an operation is covered only if it executed (instrumented); what is not run is listed with its reason          (R9-5)
  OracleNoticesMutants     damage done to the router's answer is noticed by the expectations                                                (R9-4)
  FallbackAlternatives     a malformed alternative beside a valid preferred value is not ignored                                              (R10-1)
  FlowBinding              a BIS/ECB browse answers the flow asked for, in any position; one that is absent, ambiguous or unbound yields no template   (R10-2)
  UnnamedFlows             a listing in which no dataflow has an id is unobserved with no count                                              (R10-3)

These tests are EXPECTED to fail on the tree they were written against, wherever the gateway disagrees with the specifications; each failing case names the
vector or field, the document that decides it, and what the gateway did.
"""
from __future__ import annotations

import contextlib
import itertools
import json
import os
import re
import unittest
from dataclasses import replace
from pathlib import Path

from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.harvest import openalex_snapshot, registries

from tests import invariant_ops as ops
from tests import test_invariants as inv
from tests.invariant_ops import corrupt_route
from tests.oracle import coverage, fallbacks, flow_cases, loaders, mutants, variants, xml_ops
from tests.oracle import expected_records as ex
from tests.oracle import link_vectors as lv

# every operation the oracle holds: the harness's, and the populated variants the harness's seeded stream cannot take (see variants.build)
ALL_OPS = {**inv.ALL, **{op.name: op for op in ops._POPULATED["outside the harness"]}}
HF = ops.HF_FIND_MORE
HF_PAGE = corrupt_route(HF).body
XML = xml_ops.build(ops)
FLOW = flow_cases.build(ops)
# what the answer says about a record that is not a field of its own: provenance and raw copies hold every provider value
NOT_THE_RECORD = ("raw", "provenance", "sources", "retrieved_at", "metadata_license", "freshness_lag", "permissions", "download_request")


# ------------------------------------------------------------------ the reference grammar checks itself
class VectorsAreConsistent(unittest.TestCase):
    def test_hand_written_labels_agree_with_the_reference_grammar(self):
        """The reference reader is an independent transcription of the ABNF; where it and a hand-written label disagree, one of them has a typo."""
        for v in lv.VECTORS:
            if v.grade == "judgement":
                continue
            with self.subTest(vector=v.name):
                got, url = lv.interpret(v.header)
                self.assertEqual(got, v.expect, f"{v.header!r}: labelled {v.expect}, the grammar says {got} ({v.rfc})")
                if v.expect == lv.NEXT:
                    self.assertEqual(url, v.next_url)

    def test_every_class_of_the_brief_has_vectors(self):
        names = " ".join(v.name for v in lv.VECTORS)
        for needle in ("target-valid", "target-invalid", "cursor-invalid", "rel:", "param:", "empty-header", "follow:", "two-links", "same-next-twice",
                       "two-different-nexts", "comma-in-target"):
            self.assertIn(needle, names)
        text = " ".join(repr(v.header) for v in lv.VECTORS)
        for needle in ("%GG", "%\u0663", "[broken", "[::1]", "[v7", "\u00e9", "\u4e2d", '\\"', "\\\\", "u@v@"):
            self.assertIn(needle, text, needle)

    def test_the_vectors_cover_all_three_outcomes_in_quantity(self):
        for outcome in (lv.NEXT, lv.ABSENT, lv.UNKNOWN):
            self.assertGreater(sum(1 for v in lv.VECTORS if v.expect == outcome), 40, outcome)


# ------------------------------------------------------------------ R9-1: Link header vectors through the real adapter and router
def link_outcome(header):
    answer, lane = inv.run(HF, HF_PAGE, headers={} if header is None else {"Link": header})
    if lane.get("exhausted") is True:
        return lv.ABSENT, None, lane
    nxt = lane.get("next")
    if isinstance(nxt, str) and nxt and nxt != "exhausted":
        return lv.NEXT, nxt, lane
    return lv.UNKNOWN, None, lane


class LinkConformance(unittest.TestCase):
    def test_every_vector_is_read_as_the_specifications_say(self):
        """A next URL, a known absence, or neither (PROVIDER-PAGINATION.md, Hugging Face). An absence is concluded only from a header read whole."""
        for v in lv.VECTORS:
            with self.subTest(vector=v.name, grade=v.grade):
                got, url, lane = link_outcome(v.header)
                shown = f"{v.header!r}" if v.header is not None else "no Link header"
                self.assertIn(got, v.allowed, f"{shown}: a conformant reader reaches {sorted(v.allowed)}, the gateway reached {got} [{v.grade}: {v.rfc}] {v.note}")
                if got == lv.NEXT and v.next_url is not None:
                    self.assertEqual(url, v.next_url, f"{shown}: the continuation is the target as written (resolved, for a relative reference)")
                if got == lv.UNKNOWN:
                    self.assertEqual((lane.get("completeness"), lane.get("error_class")), ("partial", "partial_pagination"),
                                     f"{shown}: neither an end nor a continuation is a lower bound (STATION-CONTRACT.md §2)")
                    self.assertEqual(lane.get("count"), 3, f"{shown}: the records read are kept, as a lower bound")
                if got == lv.ABSENT:
                    self.assertEqual((lane.get("coverage"), lane.get("completeness")), ("searched_ok", "complete"))

    def test_a_malformed_header_never_ends_the_listing(self):
        """The safety property alone, over every vector the grammar says cannot be read: never `exhausted`, whatever else it does."""
        for v in lv.VECTORS:
            if v.expect != lv.UNKNOWN or lv.ABSENT in v.allowed:
                continue
            with self.subTest(vector=v.name):
                got, _, _ = link_outcome(v.header)
                self.assertNotEqual(got, lv.ABSENT, f"{v.header!r} cannot be read as an RFC 8288 Link header ({v.rfc}), and the gateway concluded the listing ended")


# ------------------------------------------------------------------ R9-4: hand-written expected canonical fields
def matches(actual, want) -> bool:
    if isinstance(want, ex.CI):
        return isinstance(actual, str) and actual.lower() == str(want).lower()
    if isinstance(want, ex.Has):
        if isinstance(want.items, dict):
            return isinstance(actual, dict) and all(k in actual and matches(actual[k], v) for k, v in want.items.items())
        return isinstance(actual, list) and all(i in actual for i in want.items)
    if isinstance(want, (bool, int, float, str)):
        return type(actual) is type(want) and actual == want
    return actual == want


def anywhere(record: dict, text: str) -> bool:
    def walk(v):
        if isinstance(v, str):
            return text in v
        if isinstance(v, dict):
            return any(walk(x) for x in v.values())
        if isinstance(v, (list, tuple)):
            return any(walk(x) for x in v)
        return False
    return walk({k: v for k, v in record.items() if k not in NOT_THE_RECORD})


def expected_for(name: str):
    """(expected records, catalogue entries) of an operation, or of the operation a populated variant populates (plus what an added field documents)."""
    base = variants.BASE_OF.get(name, name)
    recs = ex.EXPECTED.get(base)
    if recs is not None and name in variants.NOT_INHERITED:
        drop = variants.NOT_INHERITED[name]
        recs = tuple(ex.Rec(r.identity, {k: f for k, f in r.fields.items() if k not in drop.get(r.identity, ())}) for r in recs)
    if recs is not None and name in variants.EXTRA_EXPECTED:
        extra = variants.EXTRA_EXPECTED[name]
        recs = tuple(ex.Rec(r.identity, {**r.fields, **{k: ex.F(ex.CI(v[0]), v[1]) for k, v in extra.get(r.identity, {}).items()}}) for r in recs)
    return recs, ex.CATALOG_ENTRIES.get(base)


def problems_of(name: str, op, body=None) -> list:
    """[(key, what is wrong, source of the expectation)] for the valid answer of `op`."""
    recs, entries = expected_for(name)
    out, lane = inv.run(op, corrupt_route(op).body if body is None else body)
    found = []
    if entries is not None:
        got = [e.get("id") for e in out.get("entries") or []]
        if got != list(entries):
            found.append(("entries", f"the catalogue lists {got}, the fixture names {list(entries)}", "PLAN.md D-32: entries are the provider's own identifiers, in its order"))
        return found
    want_ids = [r.identity for r in recs]
    if lane.get("coverage") != "searched_ok":
        found.append(("lane", f"coverage is {lane.get('coverage')!r}, not 'searched_ok'", "STATION-CONTRACT.md §2"))
    if lane.get("retrieved") != want_ids:
        found.append(("retrieved", f"the lane retrieved {lane.get('retrieved')}, the fixture names {want_ids}", "STATION-CONTRACT.md §2: `retrieved` lists the identities in rank order"))
    by_id = {}
    for r in out.get("records") or []:
        by_id.setdefault(r.get("identity"), r)
    for extra in sorted(i for i in by_id if i not in set(want_ids)):
        found.append((f"{extra}", "a record the fixture does not hold", "fabricated or mis-identified"))
    for want in {r.identity: r for r in recs}.values():
        got = by_id.get(want.identity)
        if got is None:
            found.append((want.identity, "no such record in the answer", "rule/harness: the identity the fixture names"))
            continue
        for field, f in want.fields.items():
            actual = got.get(field, "<missing>")
            if not matches(actual, f.value):
                shown = f.value.items if isinstance(f.value, ex.Has) else f.value
                found.append((f"{want.identity}.{field}", f"expected {shown!r}, the record says {actual!r}", f.src))
    return found


class ExpectedCanonicalFields(unittest.TestCase):
    def test_every_operation_has_expectations(self):
        """No operation is left to the metamorphic baseline: each is in EXPECTED or CATALOG_ENTRIES, or is a variant of one that is."""
        for name in ALL_OPS:
            base = variants.BASE_OF.get(name, name)
            with self.subTest(op=name):
                self.assertTrue(base in ex.EXPECTED or base in ex.CATALOG_ENTRIES, f"{name} has no hand-written expectation")

    def test_every_expectation_belongs_to_an_operation(self):
        for name in (*ex.EXPECTED, *ex.CATALOG_ENTRIES):
            self.assertIn(name, inv.ALL, f"expectations for {name}, which is no operation of the harness")

    def test_every_expected_field_names_a_documented_source(self):
        known = {"pair", "schema", "contract", "rule", "harness"}
        for name, recs in ex.EXPECTED.items():
            for r in recs:
                for field, f in r.fields.items():
                    self.assertIn(f.src.split(":")[0], known, f"{name} {r.identity}.{field}")

    def test_the_valid_answer_of_every_operation_says_what_the_fixture_says(self):
        for name, op in ALL_OPS.items():
            for key, what, src in problems_of(name, op):
                with self.subTest(op=name, field=key):
                    self.fail(f"{what}  [source: {src}]")


# ------------------------------------------------------------------ R9-2: OpenML licence
WRONG_KINDS = (False, 0, 0.0, [], {}, 7, 1.5, True, [1], ["x"], {"a": 1})


class OpenMlLicence(unittest.TestCase):
    """OpenML documents `licence` (Api_data.php). A PRESENT value of the wrong kind is unreadable: it is not an absent licence (the record would say less than the
    provider said), and it is not licence-less beside a second spelling (the record would say what another key said). The member is dropped and counted: for a
    lookup that is an unreadable answer (STATION-CONTRACT.md §2: `payload_invalid`, never a record, never `searched_ok`); for a listing the readable members beside
    it survive, as a partial lower bound (INVARIANTS.md RG-4; STATION-CONTRACT.md §2). R9-2 lived in the LISTING: its fixture carried no `licence`."""

    def lookup(self, op, desc, shown):
        out, lane = inv.run(op, {"data_set_description": desc})
        kept = [r for r in out.get("records") or [] if r.get("identity", "").startswith("openml:61")]
        if kept:
            self.fail(f"{shown}: the record was kept, with license {kept[0].get('license')!r} (lane {lane.get('coverage')}/{lane.get('completeness')}); "
                      "a present wrong-kind licence is unreadable, so the member is dropped and counted")
        self.assertEqual((lane.get("coverage"), lane.get("error_class")), ("provider_unavailable", "payload_invalid"), f"{shown}: {lane}")
        self.assertNotIn("count", lane, f"{shown}: an unreadable answer has no count, never a zero")

    def listing(self, first_item: dict):
        import copy
        body = copy.deepcopy(corrupt_route(ops.OPENML_FIND_MORE).body)
        body["data"]["dataset"][0].update(first_item)
        return inv.run(ops.OPENML_FIND_MORE, body)

    def check_listing(self, first_item: dict, shown: str):
        out, lane = self.listing(first_item)
        kept = {r["identity"]: r for r in out.get("records") or []}
        if "openml:61" in kept:
            self.fail(f"{shown}: the record was kept, with license {kept['openml:61'].get('license')!r} (lane {lane.get('coverage')}/{lane.get('completeness')}/"
                      f"{lane.get('error_class')}); a present wrong-kind licence is unreadable, so the member is dropped and counted, never erased or replaced")
        self.assertEqual((lane.get("completeness"), lane.get("error_class"), lane.get("count")), ("partial", "payload_invalid", 2), f"{shown}: {lane}")
        self.assertEqual(lane.get("retrieved"), ["openml:62", "openml:63"], f"{shown}: the readable members beside it survive, in order")

    def test_a_listing_item_with_a_wrong_kind_licence_is_dropped_and_counted(self):
        for w in WRONG_KINDS:
            with self.subTest(licence=repr(w)):
                self.check_listing({"licence": w}, f"listing item licence={w!r}")

    def test_a_listing_item_with_a_wrong_kind_licence_is_not_replaced_by_the_other_spelling(self):
        for w in WRONG_KINDS:
            with self.subTest(licence=repr(w)):
                self.check_listing({"licence": w, "license": "CC0-1.0"}, f"listing item licence={w!r}, license='CC0-1.0'")

    def test_a_valid_listing_licence_is_read_and_the_documented_spelling_wins(self):
        out, lane = self.listing({"licence": "Public", "license": "CC0-1.0"})
        first = next(r for r in out["records"] if r["identity"] == "openml:61")
        self.assertTrue(matches(first.get("license"), ex.CI("Public")), f"licence 'Public' (documented) beside license 'CC0-1.0': the record says {first.get('license')!r}")

    def test_a_wrong_kind_licence_in_a_description_is_unreadable_not_absent(self):
        for w in WRONG_KINDS:
            with self.subTest(licence=repr(w)):
                self.lookup(ops.OPENML_RESOLVE, {**ops.OPENML_DESC["data_set_description"], "licence": w}, f"resolve licence={w!r}")

    def test_a_wrong_kind_licence_in_a_description_is_not_replaced_by_the_other_spelling(self):
        for op in (ops.OPENML_RESOLVE, ops.OPENML_FETCH):
            for w in WRONG_KINDS:
                with self.subTest(op=op.name, licence=repr(w)):
                    self.lookup(op, {**ops.OPENML_DESC["data_set_description"], "licence": w, "license": "CC0-1.0"}, f"{op.name} licence={w!r}, license='CC0-1.0'")

    def test_the_variants_that_carry_the_licence_are_in_the_corruption_domain(self):
        names = {op.name for op in ALL_OPS.values()}
        for needle in ("openml.find (a full page) (populated)", "openml.find (a full page) (licence and license)", "openml.find (a full page) (license only)",
                       "openml.resolve (licence and license)", "openml.resolve (license only)", "openml.fetch (a dataset's file links) (licence and license)",
                       "openml.fetch (a dataset's file links) (license only)", "doaj.resolve (a journal by its ISSN) (populated)", "kaggle.find (populated)",
                       "europepmc.find (populated)"):
            self.assertIn(needle, names)


# ------------------------------------------------------------------ R9-5: BIS and ECB catalogues, executed
def string_lists(value):
    """Every list of strings anywhere inside `value` (the NAME of the field that holds a flow's dimensions is not documented; their order and content are)."""
    if isinstance(value, list):
        if value and all(isinstance(x, str) for x in value):
            yield value
        for x in value:
            yield from string_lists(x)
    elif isinstance(value, dict):
        for x in value.values():
            yield from string_lists(x)


class Catalogues(unittest.TestCase):
    def test_a_listing_names_the_dataflows_of_the_message_in_its_order(self):
        for name, case in XML.items():
            if case["entries"] is None:
                continue
            with self.subTest(case=name):
                out, lane = inv.run(case["op"], None)
                got = [e.get("id") for e in out.get("entries") or []]
                self.assertEqual(got, list(case["entries"]), f"{name}: {lane}")

    def test_a_browse_names_the_dimensions_of_the_flows_own_data_structure_in_key_order(self):
        """PLAN.md D-32: 'the flow's DIMENSION IDS IN KEY ORDER via its datastructure'. SDMX: the dataflow's `Structure` reference names the data structure; a key is
        the values of its dimensions other than the time dimension, in order. Where the answer keeps the list is not documented, so any list of ids in the flow's
        entry may be it; one of them must be exactly the flow's dimensions: none missing, none repeated, none from another structure, no time dimension."""
        for name, case in XML.items():
            if case["browse"] is None:
                continue
            with self.subTest(case=name):
                out, lane = inv.run(case["op"], None)
                lists = [lst for entry in out.get("entries") or [] for lst in string_lists(entry)]
                self.assertIn(list(case["browse"]), lists, f"{name}: the dimensions of the flow's structure are {list(case['browse'])}; the answer's lists of ids are {lists}")

    def test_an_answer_that_is_not_a_catalogue_is_never_a_successful_empty_one(self):
        """PLAN.md D-32a: HTML challenges, unparseable structures and a data structure with no dimensions 'surface as capability facts or raise, never as a
        successful empty catalogue', and a datastructure with no parsed dimensions 'REFUSES to invent an empty key template'."""
        for name, case in XML.items():
            if case["entries"] is not None or case["browse"] is not None or name.startswith("bis.data"):
                continue
            with self.subTest(case=name):
                try:
                    out, lane = inv.run(case["op"], None)
                except Exception as e:  # noqa: BLE001  a raise is one of the documented outcomes
                    self.assertTrue(str(e), name)
                    continue
                entries = out.get("entries") or []
                self.assertFalse(lane.get("coverage") in ("searched_ok", "searched_empty") and not entries,
                                 f"{name}: a successful empty catalogue ({lane.get('coverage')}, no entries)")
                keyed = [lst for entry in entries for lst in string_lists(entry)]
                self.assertFalse(keyed, f"{name}: dimensions or entries invented from an answer that names none: {keyed}")

    def test_the_bis_data_message_is_read(self):
        out, lane = inv.run(XML["bis.data (two series)"]["op"], None)
        self.assertEqual((lane.get("coverage"), lane.get("count"), len(lane.get("retrieved") or [])), ("searched_ok", 2, 2), str(lane))



# ------------------------------------------------------------------ R10-1: a malformed alternative beside a valid preferred value
def lane_of(op, body):
    return inv.run(op, body)


def unreadable_problems(pair, out, lane, shown) -> list:
    """What the contract requires of a present malformed supported field, by the pair's scope; the list of what the answer did instead."""
    found = []
    base = pair.op
    if pair.scope == "member":
        ids = [r.identity for r in ex.EXPECTED[base]]
        kept = [r.get("identity") for r in out.get("records") or []]
        if ids[0] in kept:
            found.append(f"{shown}: the member {ids[0]} was kept (lane {lane.get('coverage')}/{lane.get('completeness')}/{lane.get('error_class')}, count {lane.get('count')})")
        got = (lane.get("completeness"), lane.get("error_class"), lane.get("count"))
        if got != ("partial", "payload_invalid", len(ids) - 1):
            found.append(f"{shown}: the lane is {got}, not a partial lower bound of {len(ids) - 1} (payload_invalid)")
        if lane.get("retrieved") != ids[1:]:
            found.append(f"{shown}: the lane retrieved {lane.get('retrieved')}, the readable members are {ids[1:]}")
    else:
        if (lane.get("coverage"), lane.get("error_class"), lane.get("completeness")) != ("provider_unavailable", "payload_invalid", "unobserved"):
            found.append(f"{shown}: the answer was {lane.get('coverage')}/{lane.get('completeness')}/{lane.get('error_class')}, not an unreadable one (provider_unavailable, "
                         "payload_invalid, unobserved)")
        if "count" in lane:
            found.append(f"{shown}: an unreadable answer has no count, and this one counts {lane.get('count')}")
        if out.get("records"):
            found.append(f"{shown}: records came back: {[r.get('identity') for r in out['records']]}")
        if pair.scope == "whole" and out.get("entries"):
            found.append(f"{shown}: the catalogue kept {len(out['entries'])} entries")
    return found


class FallbackAlternatives(unittest.TestCase):
    """R10-1. See tests/oracle/fallbacks.py: both fields populated; A alone malformed (the alternate is read); A malformed beside a valid P; P malformed beside a valid A."""

    def op_body(self, pair):
        op = ALL_OPS[pair.op]
        return op, corrupt_route(op).body

    def test_the_pairs_are_documented_and_their_operations_exist(self):
        self.assertGreaterEqual(len(fallbacks.NAMED), 4)
        for pair in fallbacks.PAIRS:
            with self.subTest(pair=pair.name):
                self.assertIn(pair.op, ALL_OPS)
                self.assertTrue(pair.doc.strip())
                self.assertTrue(pair.op in ex.EXPECTED or pair.op in ex.CATALOG_ENTRIES)

    def test_with_both_populated_and_valid_the_answer_is_read_whole(self):
        """The control: nothing is wrong with the answer, so nothing is dropped."""
        for pair in fallbacks.PAIRS:
            op, body = self.op_body(pair)
            with self.subTest(pair=pair.name):
                out, lane = lane_of(op, pair.both_valid(body))
                self.assertEqual(lane.get("coverage"), "searched_ok", f"{pair.name}: {lane}")
                self.assertNotEqual(lane.get("error_class"), "payload_invalid", f"{pair.name}: {lane}")
                if pair.scope == "whole":
                    self.assertEqual([e.get("id") for e in out.get("entries") or []], list(ex.CATALOG_ENTRIES[pair.op]))
                else:
                    self.assertEqual(lane.get("retrieved"), [r.identity for r in ex.EXPECTED[pair.op]])

    def test_the_alternate_alone_is_read_when_it_is_malformed(self):
        """Astra's isolation: with the preferred field absent, a malformed alternate IS rejected; so the gateway reads it, and a pair that fails the next test fails it
        because of the short circuit and not because the field is unsupported."""
        for pair in fallbacks.PAIRS:
            op, body = self.op_body(pair)
            for wrong in pair.wrong:
                with self.subTest(pair=pair.name, alternate=repr(wrong)):
                    problems = unreadable_problems(pair, *lane_of(op, pair.with_(body, p=fallbacks.ABSENT, a=wrong)), f"{pair.a[-1]}={wrong!r} (alone)")
                    self.assertEqual(problems, [], problems)

    def test_a_malformed_alternate_beside_a_valid_preferred_value_is_not_ignored(self):
        for pair in fallbacks.PAIRS:
            op, body = self.op_body(pair)
            for wrong in pair.wrong:
                with self.subTest(pair=pair.name, alternate=repr(wrong)):
                    problems = unreadable_problems(pair, *lane_of(op, pair.with_(body, a=wrong)),
                                                   f"{pair.p[-1]}={pair.p_valid!r} valid, {pair.a[-1]}={wrong!r}")
                    self.assertEqual(problems, [], f"[{pair.doc}] " + "; ".join(problems))

    def test_a_malformed_preferred_value_beside_a_valid_alternate_is_not_ignored(self):
        for pair in fallbacks.PAIRS:
            op, body = self.op_body(pair)
            for wrong in pair.wrong_for_p:
                with self.subTest(pair=pair.name, preferred=repr(wrong)):
                    problems = unreadable_problems(pair, *lane_of(op, pair.with_(body, p=wrong)),
                                                   f"{pair.p[-1]}={wrong!r}, {pair.a[-1]}={pair.a_valid!r} valid")
                    self.assertEqual(problems, [], f"[{pair.doc}] " + "; ".join(problems))


# ------------------------------------------------------------------ R10-2 and R10-3: which flow a browse answers; a listing that names no flow
def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from strings(k)
            yield from strings(v)
    elif isinstance(value, (list, tuple)):
        for x in value:
            yield from strings(x)


def templates(value):
    """Every `research_data` parameter map in the value: the documented parameters of an SDMX data request are `dataflow` and `key` (the harness's `ecb.data` request)."""
    if isinstance(value, dict):
        if "dataflow" in value and "key" in value:
            yield value
        for v in value.values():
            yield from templates(v)
    elif isinstance(value, (list, tuple)):
        for x in value:
            yield from templates(x)


def flow_outcome(case):
    try:
        return inv.run(case.op, None)
    except Exception as e:  # noqa: BLE001  a raise is not a successful answer either
        return {"entries": [], "records": []}, {"coverage": "provider_unavailable", "completeness": "unobserved", "raised": str(e)}


class FlowBinding(unittest.TestCase):
    """R10-2. See tests/oracle/flow_cases.py."""

    def test_the_answer_is_about_the_flow_asked_for_wherever_it_stands(self):
        for case in FLOW.values():
            if case.kind not in ("bind", "versions"):
                continue
            with self.subTest(case=case.name):
                out, lane = flow_outcome(case)
                entries = out.get("entries") or []
                problems = []
                if [e.get("id") for e in entries] != [case.requested]:
                    problems.append(f"the entries are {[e.get('id') for e in entries]}, not [{case.requested!r}] ({lane})")
                for entry in entries[:1]:
                    text = list(strings(entry))
                    if not any(case.flow_name in t for t in text):
                        problems.append(f"the entry does not carry the name {case.flow_name!r}: its text is {[t for t in text if ' ' in t]}")
                    for oid, oname, _ in case.others:
                        if oname and any(oname in t for t in text):
                            problems.append(f"the entry carries the name of another flow, {oname!r}")
                        if oid in text:
                            problems.append(f"the entry names another flow, {oid}")
                    lists = list(string_lists(entry))
                    if list(case.dims) not in lists:
                        problems.append(f"the dimensions of {case.requested}'s own structure are {list(case.dims)}; the entry's lists are {lists}")
                    for oid, _, odims in case.others:
                        if list(odims) in lists:
                            problems.append(f"the entry holds the dimensions of {oid} ({list(odims)})")
                    found = list(templates(entry))
                    if not found:
                        problems.append("the entry carries no research_data request template")
                    for t in found:
                        if t["dataflow"] != case.requested:
                            problems.append(f"a request template for {t['dataflow']!r} under {case.requested!r}")
                        if len(str(t["key"]).split(".")) != len(case.dims):
                            problems.append(f"the template's key {t['key']!r} has {len(str(t['key']).split('.'))} components for {len(case.dims)} dimensions")
                self.assertEqual(problems, [], f"{case.name} ({case.why})")

    def test_a_flow_that_cannot_be_bound_yields_no_entry_and_no_template(self):
        for case in FLOW.values():
            if not case.fails_closed or case.kind in ("unnamed", "unnamed-empty"):
                continue
            with self.subTest(case=case.name):
                out, lane = flow_outcome(case)
                problems = []
                if out.get("entries"):
                    problems.append(f"entries {[(e.get('id'), e.get('label')) for e in out.get('entries')]}")
                if list(templates(out)):
                    problems.append("a research_data request template for a flow that is not there: " + str([t["dataflow"] for t in templates(out)]))
                if lane.get("completeness") == "complete" or lane.get("coverage") in ("searched_ok", "searched_empty"):
                    problems.append(f"the lane is {lane.get('coverage')}/{lane.get('completeness')}, not unobserved or unavailable")
                if not (lane.get("completeness") == "unobserved" or lane.get("coverage") == "provider_unavailable"):
                    problems.append(f"neither unobserved nor provider_unavailable: {lane}")
                if "count" in lane:
                    problems.append(f"an answer that observed nothing has a count ({lane.get('count')})")
                self.assertEqual(problems, [], f"{case.name} ({case.why})")


class FlowCasesAreConsistent(unittest.TestCase):
    """The cases' expected answers, derived a second time from the message itself by a reference reader of the SDMX information model (flow_cases.reference_browse)."""

    def test_every_case_expects_what_the_message_says(self):
        for case in FLOW.values():
            if case.requested is None:
                continue
            with self.subTest(case=case.name):
                agency = case.sid.upper()
                state, dims, name = flow_cases.reference_browse(case.op.routes[0].body, agency, case.requested)
                if case.fails_closed:
                    self.assertNotEqual(state, "ok", case.name)
                else:
                    self.assertEqual((state, dims, name), ("ok", tuple(case.dims), case.flow_name), case.name)

    def test_every_position_of_the_message_is_asked(self):
        for sid in ("bis", "ecb"):
            where = {c.why for c in FLOW.values() if c.sid == sid and c.kind == "bind"}
            self.assertEqual(where, {"requested flow is first", "requested flow is middle", "requested flow is last"})
            orders = {c.name.split(" of ")[1].split(",")[0] for c in FLOW.values() if c.sid == sid and c.kind == "bind"}
            self.assertEqual(len(orders), 3, orders)


def unnamed_problems(case) -> list:
    out, lane = flow_outcome(case)
    found = []
    if (lane.get("coverage"), lane.get("error_class"), lane.get("completeness")) != ("provider_unavailable", "payload_invalid", "unobserved"):
        found.append(f"the listing ended {lane.get('coverage')}/{lane.get('completeness')}/{lane.get('error_class')}, not provider_unavailable/unobserved/payload_invalid")
    if "count" in lane:
        found.append(f"an unreadable listing has no count, and this one counts {lane.get('count')} (retrieved {lane.get('retrieved')})")
    if out.get("entries"):
        found.append(f"entries {out.get('entries')}")
    if out.get("records"):
        found.append(f"records {out.get('records')}")
    return found


class UnnamedFlows(unittest.TestCase):
    """R10-3: a listing in which no dataflow has an id is unreadable whole; the same listing with its ids is read."""

    def test_a_listing_that_names_no_flow_is_unobserved_with_no_count(self):
        for case in FLOW.values():
            if case.kind not in ("unnamed", "unnamed-empty"):
                continue
            with self.subTest(case=case.name):
                self.assertEqual(unnamed_problems(case), [], case.name)

    def test_the_readable_control_is_read(self):
        for case in FLOW.values():
            if case.kind != "control":
                continue
            with self.subTest(case=case.name):
                out, lane = flow_outcome(case)
                self.assertEqual((lane.get("coverage"), lane.get("completeness")), ("searched_ok", "complete"), f"{case.name}: {lane}")
                self.assertEqual([e.get("id") for e in out.get("entries") or []], list(case.entries))
                self.assertEqual(lane.get("count"), len(case.entries))

    def test_the_unnamed_cases_differ_from_the_control_only_in_the_ids(self):
        for sid in ("bis", "ecb"):
            unnamed = FLOW[f"{sid}.catalog (a listing whose every dataflow has no id)"].op.routes[0].body
            control = FLOW[f"{sid}.catalog (the same listing with its ids: the control)"].op.routes[0].body
            self.assertEqual(unnamed, re.sub(r'(<structure:Dataflow) id="[^"]*"', r"\1", control), sid)


# ------------------------------------------------------------------ the Tier 0 registry loaders
def loader_client(sid: str, url: str, body):
    t = FakeTransport()
    t.add("GET", url, 200, body)
    return Client(broker=Broker({sid: RatePolicy(per_second=100000)}), transport=t, secrets=lambda n, f=None: "k", sleep=lambda s: None)


def loader_records(which: str) -> list:
    if which == "crossref journals":
        return list(registries.crossref_journals(loader_client("crossref", loaders.CROSSREF_FIRST_URL, loaders.CROSSREF_JOURNALS)))
    if which == "datacite repositories":
        return list(registries.datacite_repositories(loader_client("datacite", loaders.DATACITE_FIRST_URL, loaders.DATACITE_REPOSITORIES)))
    return [r for r in (openalex_snapshot.record_from(dict(s)) for s in loaders.OPENALEX_SOURCES) if r is not None]


class RegistryLoaders(unittest.TestCase):
    def test_each_loader_yields_the_venues_and_repositories_its_rows_describe(self):
        for which, venues in loaders.EXPECTED.items():
            records = loader_records(which)
            with self.subTest(loader=which):
                self.assertEqual(len(records), len(venues), f"{which}: {len(venues)} rows in, {len(records)} records out")
            for want in venues:
                with self.subTest(loader=which, record=want.name):
                    named = [r for r in records if anywhere(r, want.name)]
                    self.assertEqual(len(named), 1, f"{which}: no record (or more than one) carries the name {want.name!r}")
                    (got,) = named
                    self.assertEqual(got.get("kind"), want.kind, f"kind [{want.src}]")
                    if want.identity is not None:
                        self.assertEqual(got.get("identity"), want.identity, f"identity [{want.src}]")
                    if want.identity_prefix is not None:
                        self.assertTrue(str(got.get("identity")).startswith(want.identity_prefix), f"identity {got.get('identity')!r} [{want.src}]")
                    for field, value in want.fields.items():
                        if isinstance(value, ex.Somewhere):
                            self.assertTrue(anywhere(got, str(value)), f"{str(value)!r} appears nowhere in the record [{want.src}]")
                        else:
                            self.assertEqual(got.get(field), value, f"{field} [{want.src}]")


# ------------------------------------------------------------------ R9-5: coverage by execution
# the failure modes of the first catalogue cases (tests/oracle/xml_ops.py), by the words of their names; the new ones are flow_cases.FAILURE_MODES
XML_MODES = {"an HTML challenge page": "an HTML challenge page", "not XML at all": "not XML at all", "an empty body": "an empty body",
             "a dataflow whose data structure has no dimensions": "a structure with no dimensions"}
FRESH_PREFIXES = itertools.count(91001)
LOADER_WATCH = ((registries, "crossref_journals"), (registries, "datacite_repositories"), (openalex_snapshot, "record_from"), (registries, "doaj_journals"))


class ExecutedCoverage(unittest.TestCase):
    """An operation counts as covered only if it ran: the recorder wraps the client and the router, and everything below is computed from what it saw."""

    @classmethod
    def setUpClass(cls):
        cls.rec = coverage.Recorder().install()
        for module, name in LOADER_WATCH:
            cls.rec.watch_loader(module, name) if name != "record_from" else cls.rec.watch_function(module, name)
        for op in ALL_OPS.values():                                    # every operation of the oracle, as its valid answer
            inv.run(op, corrupt_route(op).body)
        cls.mode_outcomes = {}
        for name, case in XML.items():                                 # the BIS and ECB cases
            mode = XML_MODES.get(name.split(" (", 1)[1].rstrip(")")) if " (" in name else None
            cls.execute(case["op"], (name.split(".")[0], mode) if mode else None)
        for case in FLOW.values():                                     # the flow cases: binding, absent, ambiguous, unnamed
            cls.execute(case.op, (case.sid, case.kind) if case.kind in flow_cases.FAILURE_MODES else None)
        for which in loaders.EXPECTED:
            loader_records(which)
        # the registration-agency lookup is cached per DOI prefix for the life of the process, so a prefix an earlier test used is not asked again: a DOI under a
        # prefix nobody has used makes the lookup (`doi_org`) actually run, wherever in the suite this class happens to run
        base = ops.DATACITE_RESOLVE
        doi = f"10.{next(FRESH_PREFIXES)}/oracle"
        body = json.loads(json.dumps(corrupt_route(base).body).replace("10.9101/d1", doi))
        fresh = replace(base, name=f"datacite.resolve ({doi})", request=ops.request("resolve", identity=f"doi:{doi}"),
                        routes=(ops.Route("GET", f"https://api.datacite.org/dois/{doi}", body, corrupt=True),))
        inv.run(fresh, body)

    @classmethod
    def execute(cls, op, mode):
        """Run one case under the recorder and keep what the execution ENDED as, by failure mode: an executed case says the operation ran; the outcome says the mode was exercised."""
        before = len(cls.rec.executions)
        try:
            inv.run(op, None)
        except Exception:  # noqa: BLE001  a case that raises still executed (the catalogue tests judge its outcome)
            pass
        if mode and len(cls.rec.executions) > before:
            cls.mode_outcomes.setdefault(mode, []).append((op.name, cls.rec.executions[before]))

    @classmethod
    def tearDownClass(cls):
        cls.rec.uninstall()

    def test_every_operation_that_exists_is_executed_or_listed_with_its_reason(self):
        for (sid, kind, sel), reason in sorted(coverage.universe().items()):
            ran = self.rec.covered(sid, kind, sel)
            with self.subTest(operation=f"{sid}.{kind}" + (f" [{sel}]" if sel else "")):
                if reason is None:
                    self.assertGreater(ran, 0, f"{sid}.{kind} [{sel}] is credited by no execution: no request of that kind went through the router and reached the source")
                else:
                    self.assertEqual(ran, 0, f"{sid}.{kind} [{sel}] is excluded ({reason}) but executed {ran} times: a stale exclusion")

    def test_every_failure_mode_of_a_catalogue_was_exercised_and_ended_unobserved_or_unavailable(self):
        """Execution accounting says an operation ran (above). It does not say a way for its input to be wrong was tried: R10-3's mutant, the deleted `identified(...)`
        validation, left every executed operation executed. A failure MODE counts only if a case of that mode ran and the lane ended as an unreadable answer."""
        for sid in ("bis", "ecb"):
            for mode in sorted({*XML_MODES.values(), *flow_cases.FAILURE_MODES}):
                with self.subTest(source=sid, mode=mode):
                    ran = self.mode_outcomes.get((sid, mode), [])
                    self.assertTrue(ran, f"{sid}.catalog: no case of the failure mode {mode!r} ran")
                    for name, execution in ran:
                        coverage_state, completeness, _count, _error = execution.lanes.get(sid, (None, None, False, None))
                        self.assertTrue(execution.raised or coverage_state == "provider_unavailable" or completeness == "unobserved",
                                        f"{name}: ended {coverage_state}/{completeness}, so the mode {mode!r} was not exercised as a failure")
                        self.assertNotEqual(completeness, "complete", name)

    def test_the_modes_are_named_for_every_case_that_claims_one(self):
        for case in FLOW.values():
            if case.fails_closed:
                self.assertIn(case.kind, flow_cases.FAILURE_MODES, case.name)

    def test_bis_and_ecb_catalogues_executed(self):
        for sid in ("bis", "ecb"):
            for sel in ("top", "within:1"):
                with self.subTest(source=sid, selector=sel):
                    self.assertGreater(self.rec.covered(sid, "catalog", sel), 0)

    def test_dimension_browsing_is_listed_not_covered(self):
        for sid in ("bis", "ecb"):
            self.assertEqual(self.rec.covered(sid, "catalog", "within:2"), 0)
            self.assertIn((sid, "catalog", "within:2"), coverage.EXCLUDED)
            self.assertIn("deferred", coverage.EXCLUDED[(sid, "catalog", "within:2")])

    def test_the_registry_loaders_executed_or_are_listed_with_their_reason(self):
        for _, name in LOADER_WATCH:
            with self.subTest(loader=name):
                if name in loaders.NOT_RUN:
                    self.assertEqual(self.rec.loaders[name], 0, f"{name} is listed as not run ({loaders.NOT_RUN[name]}) but ran: a stale exclusion")
                else:
                    self.assertGreater(self.rec.loaders[name], 0, f"{name} never yielded a record")

    def test_the_seed_is_the_source_of_what_exists(self):
        uni = {(s, k) for s, k, _ in coverage.universe()}
        for pair in coverage.seed_operations():
            self.assertIn(pair, uni, f"{pair} is in the registry seed and in neither the universe nor the exclusions")

    def test_a_listed_operation_that_never_ran_is_not_credited(self):
        """The failure of R9-5 in miniature: nothing in the recorder credits a (source, kind) that no execution reached."""
        self.assertEqual(self.rec.covered("no_such_source", "catalog", "top"), 0)
        self.assertEqual(self.rec.covered("bis", "catalog", "within:3"), 0)


# ------------------------------------------------------------------ R9-4: the expectations notice damage to the answer
@contextlib.contextmanager
def damaged(mutate):
    original = R.execute

    def execute(*args, **kwargs):
        out = original(*args, **kwargs)
        mutate(out)
        return out
    R.execute = execute
    try:
        yield
    finally:
        R.execute = original


def all_problems() -> int:
    return sum(len(problems_of(name, op)) for name, op in ALL_OPS.items())


UNNAMED_FLOW = re.compile(r'<structure:Dataflow(?=[\s>])(?![^>]*\sid="[^"])')


def has_unnamed_flow(op) -> bool:
    return any(isinstance(r.body, str) and UNNAMED_FLOW.search(r.body) for r in op.routes)


class FailureModesAreKilled(unittest.TestCase):
    """R10-3: Astra's mutant deleted BIS's validation of a flow's id; every readable listing stayed complete, every older unreadable-catalogue case (HTML, text, empty,
    no dimensions) still ended unreadable through another check, and all 30 oracle tests passed. Reproduced here at the router's boundary with a mutant that does what the
    review says it did, but ONLY for a listing that holds an unnamed dataflow: an unreadable answer becomes a complete one-entry answer named None."""

    def run_all(self, mutate):
        current = []

        def when(out):
            if current and has_unnamed_flow(current[0]):
                mutate(out)
        with damaged(when):
            for name, case in XML.items():
                if case["entries"] is None and case["browse"] is None and not name.startswith("bis.data"):
                    current[:] = [case["op"]]
                    yield "older", name, inv.run(case["op"], None)
            for case in FLOW.values():
                if case.kind in ("unnamed", "unnamed-empty"):
                    current[:] = [case.op]
                    yield "new", case.name, case

    def test_the_older_cases_cannot_see_the_mutant_and_the_unnamed_flow_cases_kill_it(self):
        older = new = 0
        for group, name, what in self.run_all(mutants.launder_unreadable_catalog):
            if group == "older":
                out, lane = what
                older += 1
                self.assertNotEqual(lane.get("coverage"), "searched_ok", f"{name}: this case holds no unnamed flow, so the mutant leaves it alone")
            else:
                new += 1
                with self.subTest(case=name):
                    self.assertNotEqual(unnamed_problems(what), [], f"{name}: the laundering of an unreadable listing went unnoticed")
        self.assertGreaterEqual((older, new), (8, 4))

    def test_the_unnamed_cases_pass_on_the_gateway_as_it_is(self):
        """R10-3 is about the mutant, not a present defect: without it the unnamed-flow cases pass."""
        for case in FLOW.values():
            if case.kind in ("unnamed", "unnamed-empty"):
                self.assertEqual(unnamed_problems(case), [], case.name)


class OracleNoticesMutants(unittest.TestCase):
    def test_each_kind_of_damage_to_the_answer_is_noticed(self):
        """R9-4: a mutant that erased every title passed all 261 harness tests. Each of these damages the router's answer, knowing nothing of the gateway, and the
        hand-written expectations must find more wrong than they do of the answer as it is."""
        baseline = all_problems()
        for name, mutate in mutants.MUTANTS.items():
            with self.subTest(mutant=name):
                with damaged(mutate):
                    self.assertGreater(all_problems(), baseline, f"{name} went unnoticed")

    def test_the_catalogue_cases_notice_a_fabricated_or_missing_entry(self):
        cases = [c for c in XML.values() if c["entries"] is not None]
        for name in ("fabricate_entry", "drop_first_entry"):
            with self.subTest(mutant=name), damaged(mutants.MUTANTS[name]):
                for case in cases:
                    out, _ = inv.run(case["op"], None)
                    self.assertNotEqual([e["id"] for e in out["entries"]], list(case["entries"]))


# ------------------------------------------------------------------ the harness's randomised case, at more than one seed
class MixedMembersOtherSeeds(unittest.TestCase):
    """The harness draws its mixed members from a stream seeded with one constant, and passes at it. At other seeds its own `MixedMembers` case fails for
    `openml.fetch` (the explicit `url` and `parquet_url` links), so what the committed seed shows is that one draw does not meet the disagreement, not that
    there is none. Either the harness's operation table or the gateway is wrong about some value of those two fields; the cause is inside the harness's
    generator, which this task may not read, so it is not established here which side is wrong. A ruling is needed; until then this fails."""

    SEEDS = (1, 2, 5, 8, 13, 21, 34, 55, 89, 144)

    def test_the_mixed_members_hold_at_other_seeds(self):
        original = inv.SEED
        try:
            for seed in self.SEEDS:
                inv.SEED = seed
                result = unittest.TestResult()
                inv.MixedMembers("test_the_members_that_are_readable_are_exactly_the_ones_kept").run(result)
                wrong = sorted({name for _, msg in result.failures + result.errors for name in re.findall(r'\("([^"]+)", \[', msg)})
                with self.subTest(seed=seed):
                    self.assertEqual([], wrong, f"seed {seed}: the harness's own mixed-member case fails for {wrong}")
        finally:
            inv.SEED = original


# ------------------------------------------------------------------ the evidence: what each expectation rests on
class Evidence(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("ORACLE_EVIDENCE"), "ORACLE_EVIDENCE names the directory the expectation sources are written to")
    def test_write_the_expectation_sources(self):
        out = Path(os.environ["ORACLE_EVIDENCE"])
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for name, recs in ex.EXPECTED.items():
            for r in recs:
                rows.append({"operation": name, "identity": r.identity, "identity_source": "rule or harness fixture ids",
                             "fields": {k: {"expected": repr(f.value.items if isinstance(f.value, ex.Has) else f.value), "source": f.src} for k, f in r.fields.items()}})
        (out / "expected-sources.json").write_text(json.dumps({"expected_records": rows, "catalogue_entries": ex.CATALOG_ENTRIES, "undocumented": ex.UNDOCUMENTED}, indent=1))
        (out / "link-vectors.json").write_text(json.dumps([{"name": v.name, "header": v.header, "expect": v.expect, "also": list(v.also), "grade": v.grade, "rfc": v.rfc,
                                                            "next_url": v.next_url} for v in lv.VECTORS], indent=1, ensure_ascii=True))
        (out / "fallback-pairs.json").write_text(json.dumps([{"pair": p.name, "operation": p.op, "scope": p.scope, "preferred": list(map(str, p.p)), "alternate": list(map(str, p.a)),
                                                               "named_by_brief": p.named, "asserted": p.named or bool(p.supported), "read_by_probe": p.supported,
                                                               "documentation": p.doc, "wrong_values_for_alternate": [repr(w) for w in p.wrong]}
                                                              for p in (*fallbacks.NAMED, *fallbacks.CANDIDATES)], indent=1))
        (out / "flow-cases.json").write_text(json.dumps([{"case": c.name, "source": c.sid, "kind": c.kind, "requested": c.requested, "expected_dimensions": list(c.dims),
                                                           "expected_name": c.flow_name, "fails_closed": c.fails_closed, "why": c.why,
                                                           "reference_reader": list(flow_cases.reference_browse(c.op.routes[0].body, c.sid.upper(), c.requested)[:1]) if c.requested else None}
                                                          for c in FLOW.values()], indent=1))
        uni = coverage.universe()
        (out / "coverage-universe.json").write_text(json.dumps({f"{s}.{k}[{sel}]": reason for (s, k, sel), reason in sorted(uni.items())}, indent=1))


if __name__ == "__main__":
    unittest.main()
