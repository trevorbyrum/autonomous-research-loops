"""Task 2b-repair-10b, R9-2: a present value is read as what it is before a fallback chooses between spellings, and before its truth decides anything.

R9-2 (Astra, 2b-repair-9): `license=d.get("licence") or d.get("license")` made a present `false`, `0`, `[]` or `{}` licence into no licence, because
`or` looks at truth and the corrupt value never reached the validator that would have refused it. The cause is one pattern, a truthiness test or an
`or` over provider data, and 2b-repair-9's sweep found only the sites its reproductions named. This file states, by hand, each site the sweep of
2b-repair-10b found, through the real adapter and router, on the harness's valid fixtures (tests/invariant_ops.py) with a documented optional field
populated and then corrupted: the field is read as text (or a flag, or an object) first, a member that carries one of the wrong kind is dropped and
counted, and the valid forms beside it still read.

The sweep (every `or`, `if x`, `x if x else y` over a provider value in the adapters, the SDMX reader and the harvest loaders): sites changed are the
tests below; sites left as they are, and why, are in gateway/docs/STATION-CONTRACT.md (the paragraph "A present value is read as what it is") and the 2b-repair-10b report.
"""
from __future__ import annotations

import copy
import unittest

from research_gateway.adapters import bea, harvard_dataverse as dv
from research_gateway.adapters.base import PayloadError, boolean
from research_gateway.core import sdmx
from research_gateway.core.payload import view

from tests import invariant_ops as ops
from tests.invariant_ops import corrupt_route
from tests.test_invariants import run

WRONG = (False, 0, 0.0, [], {}, 7, 1.5, True, [1], ["x"], {"a": 1})   # for a field that is text: every kind that is not, the falsy ones first


def body_of(op):
    return copy.deepcopy(corrupt_route(op).body)


def populated(op, edit):
    body = body_of(op)
    edit(body)
    return run(op, body)


def unreadable(lane: dict) -> bool:
    return (lane["coverage"], lane.get("error_class")) == ("provider_unavailable", "payload_invalid") and "count" not in lane


class OpenMlSpellings(unittest.TestCase):
    """OpenML's listing carries `licence` (its own spelling) and, in some answers, `license`: each is read as text before either is chosen."""

    def listing(self, **fields):
        return populated(ops.OPENML_FIND_MORE, lambda b: b["data"]["dataset"][0].update(fields))

    def first(self, out):
        return next(r for r in out["records"] if r["identity"] == "openml:61")

    def test_each_spelling_of_the_wrong_kind_costs_its_member_and_nothing_else(self):
        for spelling in ("licence", "license"):
            for wrong in WRONG:
                for beside in ({}, {"license" if spelling == "licence" else "licence": "CC0-1.0"}):
                    with self.subTest(spelling=spelling, wrong=repr(wrong), beside=beside):
                        out, lane = self.listing(**{spelling: wrong}, **beside)
                        self.assertEqual((lane["completeness"], lane.get("error_class"), lane.get("count"), lane["retrieved"]),
                                         ("partial", "payload_invalid", 2, ["openml:62", "openml:63"]))

    def test_control_the_spellings_that_are_right_are_read_and_the_documented_one_wins(self):
        for fields, want in (({"licence": "Public"}, "Public"), ({"license": "CC0-1.0"}, "CC0-1.0"), ({"licence": "Public", "license": "CC0-1.0"}, "Public"),
                             ({"licence": None, "license": "CC0-1.0"}, "CC0-1.0"), ({"licence": "", "license": "CC0-1.0"}, "CC0-1.0"),
                             ({"licence": None, "license": None}, None)):
            with self.subTest(fields=fields):
                out, lane = self.listing(**fields)
                self.assertEqual((lane["completeness"], lane.get("count"), self.first(out)["license"]), ("complete", 3, want))


class EuropePmcFlags(unittest.TestCase):
    """Europe PMC says "Y" or "N": a flag of another kind is not an N, and `has_full_text` reads both of its flags before either decides."""

    def find(self, **flags):
        return populated(ops.EPMC_FIND, lambda b: b["resultList"]["result"][0].update(flags))

    def test_a_flag_that_is_not_text_is_unreadable_not_no(self):
        for name in ("isOpenAccess", "inEPMC", "hasTextMinedTerms"):
            for wrong in (False, 0, [], {}, 5, True, ["Y"]):
                with self.subTest(flag=name, wrong=repr(wrong)):
                    out, lane = self.find(**{name: wrong})
                    self.assertEqual((lane["completeness"], lane.get("error_class"), lane.get("count")), ("partial", "payload_invalid", 2))
                    self.assertNotIn("doi:10.1000/e1", lane["retrieved"])

    def test_one_flag_that_says_yes_does_not_hide_another_that_is_unreadable(self):
        out, lane = self.find(hasTextMinedTerms="Y", inEPMC=[])
        self.assertEqual((lane["completeness"], lane.get("count")), ("partial", 2))

    def test_control_y_and_n_and_nothing_are_read(self):
        for flags, want in (({"isOpenAccess": "Y", "inEPMC": "N"}, (True, False)), ({"isOpenAccess": "N", "hasTextMinedTerms": "Y"}, (False, True)),
                            ({"isOpenAccess": None}, (False, False)), ({}, (False, False))):
            with self.subTest(flags=flags):
                out, lane = self.find(**flags)
                first = next(r for r in out["records"] if r["identity"] == "doi:10.1000/e1")
                self.assertEqual((lane["completeness"], first["open_access"], first["has_full_text"]), ("complete", *want))


class DoajJournalRef(unittest.TestCase):
    """A journal's `ref` URLs: text, or the object an earlier reading of the schema had (`{"url": ...}`); an object that names no url is a URL that is not there."""

    def journal(self, ref):
        return populated(ops.DOAJ_RESOLVE, lambda b: b["results"][0]["bibjson"].update({"ref": ref}))

    def test_a_ref_that_is_the_wrong_kind_is_unreadable_not_a_journal_without_it(self):
        for wrong in ({"journal": {}}, {"journal": []}, {"journal": False}, {"journal": 0}, {"journal": 5}, {"journal": {"url": 5}}, {"journal": {"x": "https://e.org"}},
                      {"aims_scope": "https://e.org/a", "oa_statement": {}}):
            with self.subTest(ref=wrong):
                out, lane = self.journal(wrong)
                self.assertTrue(unreadable(lane), lane)

    def test_control_a_ref_that_is_text_or_an_object_with_a_url_or_nothing_is_read(self):
        for ref, links in (({"journal": "https://e.org/j", "aims_scope": "https://e.org/a"}, ["https://e.org/j", "https://e.org/a"]),
                           ({"journal": {"url": "https://e.org/j"}}, ["https://e.org/j"]), ({"journal": None}, []), ({}, []), (None, [])):
            with self.subTest(ref=ref):
                out, lane = self.journal(ref)
                self.assertEqual((lane["completeness"], out["records"][0]["links"]), ("complete", links))


class RestrictionsAreReadAsWhatTheyAre(unittest.TestCase):
    """What decides whether a file or a series may be handed over commercially is a flag or a note: read by its truth, a falsy wrong kind says 'not restricted'."""

    def test_fred_notes_that_are_not_text_make_the_series_unreadable(self):
        for wrong in WRONG:
            with self.subTest(notes=repr(wrong)):
                body = copy.deepcopy(ops.FRED_SERIES.body)
                body["seriess"][0]["notes"] = wrong
                out, lane = run(ops.FRED_META, body)
                self.assertTrue(unreadable(lane), lane)

    def test_fred_control_notes_that_say_restricted_or_nothing(self):
        for notes, want in (("Copyright, restricted use", True), ("n", False), (None, False), ("", False)):
            with self.subTest(notes=notes):
                body = copy.deepcopy(ops.FRED_SERIES.body)
                body["seriess"][0]["notes"] = notes
                out, lane = run(ops.FRED_META, body)
                self.assertEqual((lane["completeness"], out["records"][0]["third_party_restricted"]), ("complete", want))

    def test_a_dataverse_files_restricted_flag_is_a_flag(self):
        for wrong in (0, "", [], {}, "false", "no", 1, [True]):
            with self.subTest(restricted=repr(wrong)):
                out, lane = populated(ops.DV_FETCH, lambda b: b["data"]["latestVersion"]["files"][0].update({"restricted": wrong}))
                self.assertEqual((lane["completeness"], lane.get("error_class"), lane.get("count"), lane["retrieved"][0]),
                                 ("partial", "payload_invalid", 2, "doi:10.7910/dvn/x1#902"))
        for ok, want in ((True, True), (False, False), (None, False)):
            with self.subTest(restricted=ok):
                out, lane = populated(ops.DV_FETCH, lambda b: b["data"]["latestVersion"]["files"][0].update({"restricted": ok}))
                self.assertEqual((lane["completeness"], out["records"][0]["restricted"]), ("complete", want))

    def test_boolean_reads_a_flag_as_one(self):
        for value, want in ((True, True), (False, False), (None, False)):
            self.assertIs(boolean("x", value), want)
        for wrong in (0, 1, "", "no", [], {}, 0.0):
            with self.assertRaises(PayloadError):
                boolean("x", wrong)

    def test_a_dataverse_dataset_whose_identifier_is_not_text_is_unreadable_not_a_dataset_with_no_doi(self):
        for wrong in (False, 0, [], {}, 5):
            with self.subTest(identifier=repr(wrong)):
                out, lane = populated(ops.DV_FETCH, lambda b: b["data"].update({"identifier": wrong}))
                self.assertTrue(unreadable(lane), lane)
        for missing, identity in ((None, "harvard_dataverse:42"), ("", "harvard_dataverse:42")):
            out, lane = populated(ops.DV_FETCH, lambda b: b["data"].update({"identifier": missing}))
            self.assertEqual((lane["completeness"], lane["retrieved"][0].startswith(identity)), ("complete", True))


class CatalogueEntries(unittest.TestCase):
    """A catalogue entry's label and flags are read as text and flags: one that is not is an unreadable catalogue, not an entry without them."""

    def test_census_a_variable_whose_label_or_flag_is_the_wrong_kind_makes_the_catalogue_unreadable(self):
        for field, wrongs in (("label", WRONG), ("predicateOnly", (0, "", [], {}, "false", 1))):
            for wrong in wrongs:
                with self.subTest(field=field, wrong=repr(wrong)):
                    out, lane = populated(ops.CENSUS_VARIABLES, lambda b: b["variables"]["B01001_002E"].update({field: wrong}))
                    self.assertTrue(unreadable(lane), lane)

    def test_census_control_a_predicate_variable_and_a_variable_with_no_label(self):
        out, lane = populated(ops.CENSUS_VARIABLES, lambda b: b["variables"]["B01001_002E"].update({"predicateOnly": True}))
        self.assertEqual({e["id"]: e["kind"] for e in out["entries"]}, {"B01001_001E": "variable", "B01001_002E": "predicate", "B01001_003E": "variable"})
        out, lane = populated(ops.CENSUS_VARIABLES, lambda b: b["variables"]["B01001_002E"].pop("label"))
        self.assertEqual(len(out["entries"]), 3)

    def test_bea_a_value_whose_description_is_the_wrong_kind_is_not_replaced_by_the_other_spelling(self):
        for spelling, other in (("Desc", "Description"), ("Description", None)):
            for wrong in WRONG:
                with self.subTest(spelling=spelling, wrong=repr(wrong)):
                    def edit(b):
                        b["BEAAPI"]["Results"]["ParamValue"][0].pop("Desc")
                        b["BEAAPI"]["Results"]["ParamValue"][0][spelling] = wrong
                        if other:
                            b["BEAAPI"]["Results"]["ParamValue"][0][other] = "elsewhere"
                    out, lane = populated(ops.BEA_VALUES, edit)
                    self.assertTrue(unreadable(lane), lane)

    def test_bea_control_the_description_that_is_there_is_the_label(self):
        out, lane = populated(ops.BEA_VALUES, lambda b: b["BEAAPI"]["Results"]["ParamValue"][0].update({"Description": "other"}))
        self.assertEqual(out["entries"][0]["label"], "d A")
        out, lane = populated(ops.BEA_VALUES, lambda b: b["BEAAPI"]["Results"]["ParamValue"][0].update({"Desc": None, "Description": "other"}))
        self.assertEqual(out["entries"][0]["label"], "other")

    def test_bea_an_envelope_that_is_not_an_object_is_unreadable_and_reports_no_error(self):
        for wrong in (False, 0, [], "", "x", 5):
            with self.subTest(envelope=repr(wrong)):
                with self.assertRaises(PayloadError):
                    bea._error(view({"BEAAPI": wrong}))
                out, lane = populated(ops.BEA_VALUES, lambda b: b.update({"BEAAPI": wrong}))
                self.assertTrue(unreadable(lane), lane)
        for ok in ({}, {"Results": {}}, {"Results": {"Error": None}, "Error": None}):
            self.assertIsNone(bea._error(view({"BEAAPI": ok})))
        self.assertEqual(bea._error(view({"BEAAPI": {"Results": {"Error": {"APIErrorDescription": "bad key"}}}})), "bad key")
        self.assertEqual(bea._error(view({"BEAAPI": {"Error": {"APIErrorDescription": "bad key"}}})), "bad key")


class SdmxEntries(unittest.TestCase):
    """An SDMX-JSON dimension or value is known by its `id`, else its `name`: both are text, and are read before either is chosen."""

    def test_an_id_or_a_name_that_is_not_text_is_unreadable_not_a_missing_one(self):
        for wrong in (False, 0, [], {}, 5, True):
            with self.subTest(wrong=repr(wrong)):
                for entry in ({"id": wrong, "name": "N"}, {"id": "I", "name": wrong}, {"name": wrong}):
                    with self.assertRaises(PayloadError):
                        sdmx._named(entry)

    def test_control_the_id_wins_and_the_name_stands_in(self):
        for entry, want in (({"id": "I", "name": "N"}, "I"), ({"id": None, "name": "N"}, "N"), ({"id": "", "name": "N"}, "N"), ({"name": "N"}, "N"), ({}, None)):
            self.assertEqual(sdmx._named(entry), want)


class Publisher(unittest.TestCase):
    """`publisher` is a field of the canonical record (the sample the engine's contract fixtures ship carries it beside `venue`): mapped wherever the provider
    states it for a work, a dataset or a venue, read as text (a publisher that is not text costs its member), and `venue` still says what it said."""

    def test_the_record_carries_what_the_provider_states(self):
        for op in (ops.DATACITE_RESOLVE, ops.DOAJ_RESOLVE, ops.CORE_FULL_TEXT):
            with self.subTest(op=op.name):
                out, lane = run(op, body_of(op))
                self.assertEqual((out["records"][0].get("publisher"), out["records"][0].get("venue")), ("P", "P"))
        out, lane = run(ops.DATACITE_FIND_MORE, body_of(ops.DATACITE_FIND_MORE))
        self.assertEqual([r.get("publisher") for r in out["records"]], ["P", "P", "P"])
        out, lane = run(ops.OPENAIRE_RESOLVE, populated_openaire({"publisher": "P"}))
        self.assertEqual(out["records"][0].get("publisher"), "P")

    def test_a_publisher_that_is_not_text_costs_its_member(self):
        edits = ((ops.DATACITE_RESOLVE, lambda b, w: b["data"]["attributes"].update({"publisher": w})),
                 (ops.DOAJ_RESOLVE, lambda b, w: b["results"][0]["bibjson"]["publisher"].update({"name": w})),
                 (ops.CORE_FULL_TEXT, lambda b, w: b["results"][0].update({"publisher": w})),
                 (ops.OPENAIRE_RESOLVE, lambda b, w: b["results"][0].update({"publisher": w})),
                 (ops.CROSSREF_FIND_END, lambda b, w: b["message"]["items"][0].update({"publisher": w})))
        for op, edit in edits:
            for wrong in WRONG:
                with self.subTest(op=op.name, wrong=repr(wrong)):
                    body = body_of(op)
                    edit(body, wrong)
                    out, lane = run(op, body)
                    self.assertEqual(lane.get("error_class"), "payload_invalid", lane)

    def test_dataverse_the_datasets_own_and_a_hits(self):
        """No route reaches `dataset_record` (a DOI goes to its registration agency's resolver), so it is stated directly, as test_present_means_typed does."""
        dataset = ops.DV_DATASET["data"]
        record = dv.dataset_record(dv.BASE, "harvard_dataverse", view(copy.deepcopy(dataset)))
        self.assertEqual((record.get("publisher"), record.get("venue")), ("Harvard Dataverse", "Harvard Dataverse"))
        hit = dv.search_record(dv.BASE, "harvard_dataverse", {"global_id": "doi:10.7910/DVN/X1", "name": "N", "publisher": "Harvard Dataverse"})
        self.assertEqual(hit.get("publisher"), "Harvard Dataverse")
        for wrong in WRONG:
            with self.subTest(publisher=repr(wrong)):
                with self.assertRaises(PayloadError):
                    dv.dataset_record(dv.BASE, "harvard_dataverse", view({**copy.deepcopy(dataset), "publisher": wrong}))
                with self.assertRaises(PayloadError):
                    dv.search_record(dv.BASE, "harvard_dataverse", {"global_id": "doi:10.7910/DVN/X1", "name": "N", "publisher": wrong})


def populated_openaire(fields: dict):
    body = body_of(ops.OPENAIRE_RESOLVE)
    body["results"][0].update(fields)
    return body


if __name__ == "__main__":
    unittest.main()
