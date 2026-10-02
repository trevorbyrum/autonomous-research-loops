"""Task 2b-repair-11b, R10-1: every alternative a provider supplies is read before one is chosen, at every site, not only the ones the oracle names.

R10-1 (Astra, 2b-repair-10): `text(a) or text(b)` evaluates `text(b)` only when `a` is empty, so a present, malformed `b` beside a valid `a` was never read.
The independent oracle (tests/oracle/fallbacks.py) holds the pairs the provider documentation shows and the 2b-repair-11 brief names. The sweep of 2b-repair-11b
(evidence/2b-repair-11b/fallback-sites.md) found the same shape, a value chosen between two provider fields with the second read lazily, at the sites below;
each is stated here through the real adapter and router, on the harness's valid fixtures (tests/invariant_ops.py) with BOTH fields populated:

  control        both valid: the answer is read whole
  beside         the alternate of the wrong kind beside a valid preferred value: the answer is NOT read as if the alternate were not there
  mirror         the preferred value of the wrong kind beside a valid alternate (it was always read first; the case holds it so)
  alone          the alternate of the wrong kind with the preferred value left out (the isolation Astra used: the alternate IS a read field)

and the outcome of a malformed one is the contract's, by scope: a member of a list is dropped and counted (partial, the others stand); a lookup's record, a
single record or a whole catalogue is unreadable (provider_unavailable, payload_invalid, unobserved, no count).

2b-repair-12 (R11-1) removed the cause this file used to guard against with a source scan. Every alternative is a field the operation's schema declares, and the one
decoder (core/schema.py) decodes every declared field of an object, nested contents included, before an adapter sees any of it; an adapter chooses between decoded
values, so `a or b` cannot skip reading `b`. The syntactic scan this file used to hold (no `or`, `and` or conditional expression over two provider reads) was a guard
with a demonstrated ordinary-spelling bypass (Astra, 2b-repair-11), not a proof, and it is gone with the reads it watched; the evidence that nothing is skipped is
behavioural: the classes below, tests/test_schema_corruption.py (which corrupts every alternative the schemas declare, beside a valid preferred value and alone),
and tests/test_member_isolation.py (an adapter reads only decoded values: where it may leave the decoder is listed).
"""
from __future__ import annotations

import copy
import unittest
from dataclasses import dataclass

from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.harvest import registries

from tests import invariant_ops as ops
from tests.invariant_ops import corrupt_route
from tests.test_invariants import run

TEXT_WRONG = (False, 0, 0.0, [], {}, 7, 1.5, True, ["x"], {"a": 1})                 # for a field that is text
KEY_WRONG = (False, True, 1.5, [], {}, ["x"], {"a": 1})                              # for a member's identifier: text or a whole number is a key
INT_WRONG = (False, True, "x", "7", 1.5, [], {}, [1])                                # for a whole number
LIST_WRONG = (False, 0, "", {}, "x", 5, True)                                        # for a list that may be left out
ABSENT = object()


def put_at(body, path, value):
    holder = body
    for step in path[:-1]:
        if isinstance(holder, dict) and step not in holder:
            holder[step] = {}
        holder = holder[step]
    if value is ABSENT:
        holder.pop(path[-1], None)
    else:
        holder[path[-1]] = copy.deepcopy(value)


@dataclass(frozen=True)
class Site:
    name: str
    op: ops.Op
    scope: str              # member: a list member (dropped and counted) | single: the record the answer is (unreadable)
    record: tuple           # where the two fields sit: the first member of a list (member), or the record itself (single)
    p: tuple                # the preferred field, a path inside the record
    p_valid: object
    a: tuple                # the alternate
    a_valid: object
    wrong: tuple            # kinds that are wrong for the alternate
    p_wrong: tuple | None = None   # kinds that are wrong for the preferred field, when they are not the alternate's

    def body(self, p=..., a=...):
        body = copy.deepcopy(corrupt_route(self.op).body)
        record = body
        for step in self.record:
            record = record[step]
        put_at(record, self.p, self.p_valid if p is ... else p)
        put_at(record, self.a, self.a_valid if a is ... else a)
        return body


def lane_of(site: Site, body):
    return run(site.op, body)


def broken(site: Site, lane: dict) -> list:
    """What is wrong with the lane a malformed field produced: a member is dropped and counted; a single record is unreadable."""
    ids = list(site.op.ids)
    if site.scope == "member":
        want = ("searched_ok", "partial", "payload_invalid", len(ids) - 1, ids[1:])
        got = (lane.get("coverage"), lane.get("completeness"), lane.get("error_class"), lane.get("count"), lane.get("retrieved"))
    else:
        want = ("provider_unavailable", "unobserved", "payload_invalid", None, None)
        got = (lane.get("coverage"), lane.get("completeness"), lane.get("error_class"), lane.get("count"), lane.get("retrieved"))
    return [] if got == want else [f"{got} is not {want}"]


SITES = (
    # ---- Crossref: the given and family names, else `name`; the issue date, else the creation date
    Site("crossref.find: author given/family beside name", ops.CROSSREF_FIND_MORE, "member", ("message", "items", 0), ("author", 0, "given"), "A", ("author", 0, "name"), "An Organisation", TEXT_WRONG),
    Site("crossref.find: issued beside created", ops.CROSSREF_FIND_MORE, "member", ("message", "items", 0), ("issued", "date-parts"), [[2021, 3]], ("created", "date-time"),
         "2020-05-01T00:00:00Z", TEXT_WRONG, p_wrong=()),
    Site("crossref.resolve: author given/family beside name", ops.CROSSREF_RESOLVE, "single", ("message",), ("author", 0, "given"), "A", ("author", 0, "name"), "An Organisation", TEXT_WRONG),
    Site("crossref.resolve: issued beside created", ops.CROSSREF_RESOLVE, "single", ("message",), ("issued", "date-parts"), [[2021, 3]], ("created", "date-time"),
         "2020-05-01T00:00:00Z", TEXT_WRONG, p_wrong=()),
    # ---- DataCite: the DOI the record states, else the registry's own id (its DOI)
    Site("datacite.find: attributes.doi beside id", ops.DATACITE_FIND_MORE, "member", ("data", 0), ("attributes", "doi"), "10.1000/d1", ("id",), "10.1000/d1", TEXT_WRONG),
    Site("datacite.resolve: attributes.doi beside id", ops.DATACITE_RESOLVE, "single", ("data",), ("attributes", "doi"), "10.9101/d1", ("id",), "10.9101/d1", TEXT_WRONG),
    # ---- Harvard Dataverse: the DOI, else the entity id; the dataset's DOI, else its id; a file's label, else its file name
    Site("dataverse.find: global_id beside entity_id", ops.DV_FIND_MORE, "member", ("data", "items", 0), ("global_id",), "doi:10.7910/DVN/X1", ("entity_id",), 101, KEY_WRONG, p_wrong=TEXT_WRONG),
    Site("dataverse.fetch: identifier beside id", ops.DV_FETCH, "single", ("data",), ("identifier",), "DVN/X1", ("id",), 42, KEY_WRONG, p_wrong=TEXT_WRONG),
    Site("dataverse.fetch: a file's label beside its file name", ops.DV_FETCH, "member", ("data", "latestVersion", "files", 0), ("label",), "f1.csv", ("dataFile", "filename"), "f1.csv", TEXT_WRONG),
    # ---- DOAJ: the article's DOI, else its own id
    Site("doaj.find: DOI identifier beside id", ops.DOAJ_FIND_MORE, "member", ("results", 0), ("bibjson", "identifier", 0, "id"), "10.1000/j1", ("id",), "j1", KEY_WRONG, p_wrong=TEXT_WRONG),
    # ---- Europe PMC: the DOI, else the PMID, else its id
    Site("europepmc.find: doi beside id", ops.EPMC_FIND, "member", ("resultList", "result", 0), ("doi",), "10.1000/e1", ("id",), "1", TEXT_WRONG),
    Site("europepmc.find: pmid beside source", ops.EPMC_FIND, "member", ("resultList", "result", 0), ("pmid",), "1", ("source",), "MED", TEXT_WRONG),
    # ---- CORE: the DOI, else its id
    Site("core.enrich: doi beside id", ops.CORE_FULL_TEXT, "single", ("results", 0), ("doi",), "10.1000/a1", ("id",), 1, KEY_WRONG, p_wrong=TEXT_WRONG),
    # ---- OpenAIRE: the DOI among its identifiers, else its own id
    Site("openaire.find: doi identifier beside id", ops.OPENAIRE_FIND_MORE, "member", ("results", 0), ("instances", 0, "alternateIdentifiers", 0, "value"), "10.46298/abc1", ("id",), "oa::1",
         KEY_WRONG, p_wrong=TEXT_WRONG),
    # ---- Socrata: the permalink, else the link
    Site("socrata.find: permalink beside link", ops.SOCRATA_FIND_MORE, "member", ("results", 0), ("permalink",), "https://data.example.gov/d/abcd-1231", ("link",), "https://data.example.gov/d/x", TEXT_WRONG),
    # ---- Unpaywall: the PDF link, else the landing page
    Site("unpaywall.enrich: url_for_pdf beside url", ops.UNPAYWALL, "member", ("oa_locations", 0), ("url_for_pdf",), "https://example.org/1.pdf", ("url",), "https://example.org/1", TEXT_WRONG),
    # ---- Hugging Face: the modification date, else the creation date; the card's licence, else a licence tag
    Site("huggingface.find: lastModified beside createdAt", ops.HF_FIND_MORE, "member", (0,), ("lastModified",), "2026-02-01T00:00:00Z", ("createdAt",), "2025-01-01T00:00:00Z", TEXT_WRONG),
    Site("huggingface.find: card licence beside tags", ops.HF_FIND_MORE, "member", (0,), ("cardData", "license"), "cc-by-4.0", ("tags",), ["license:cc-by-4.0"],
         (False, 0, 0.0, {}, "", "x", 7, 1.5, True), p_wrong=(False, 0, 0.0, {}, 7, 1.5, True, [1], {"a": 1})),
    Site("huggingface.fetch: card licence beside tags", ops.HF_FETCH, "single", (), ("cardData", "license"), "cc-by-4.0", ("tags",), ["license:cc-by-4.0"],
         (False, 0, 0.0, {}, "", "x", 7, 1.5, True), p_wrong=(False, 0, 0.0, {}, 7, 1.5, True, [1], {"a": 1})),
    # ---- Kaggle: a file's total bytes, else its size
    Site("kaggle.fetch: totalBytes beside size", ops.KAGGLE_FETCH, "member", ("datasetFiles", 0), ("totalBytes",), 10, ("size",), 12, INT_WRONG),
    # ---- BEA: a table's name, else its line description; the value's key under any spelling the row carries
    Site("bea.data: TableName beside LineDescription", ops.BEA_GETDATA, "single", ("BEAAPI", "Results", "Data", 0), ("TableName",), "T10101", ("LineDescription",), "L1", TEXT_WRONG),
    Site("bea.catalog: the parameter's own spelling beside Key", ops.BEA_VALUES, "single", ("BEAAPI", "Results", "ParamValue", 0), ("Frequency",), "A", ("Key",), "A", KEY_WRONG, p_wrong=KEY_WRONG),
    Site("bea.catalog: the parameter's own spelling beside its upper-case spelling", ops.BEA_VALUES, "single", ("BEAAPI", "Results", "ParamValue", 0), ("Frequency",), "A", ("FREQUENCY",), "A", KEY_WRONG,
         p_wrong=KEY_WRONG),
)


class AlternativesBesideEachOther(unittest.TestCase):
    def test_the_sites_name_operations_that_exist_and_hold_both_fields(self):
        names = [s.name for s in SITES]
        self.assertEqual(len(names), len(set(names)))
        for site in SITES:
            with self.subTest(site=site.name):
                out, lane = lane_of(site, site.body())
                self.assertEqual((lane.get("coverage"), lane.get("completeness"), lane.get("count")), ("searched_ok", "complete", len(site.op.ids)), f"{site.name}: {lane}")
                self.assertEqual(lane.get("retrieved"), list(site.op.ids), site.name)

    def test_an_alternate_of_the_wrong_kind_beside_a_valid_preferred_value_is_not_ignored(self):
        for site in SITES:
            for wrong in site.wrong:
                with self.subTest(site=site.name, alternate=repr(wrong)):
                    self.assertEqual(broken(site, lane_of(site, site.body(a=wrong))[1]), [], f"{site.a[-1]}={wrong!r} beside {site.p[-1]}={site.p_valid!r}")

    def test_a_preferred_value_of_the_wrong_kind_beside_a_valid_alternate_is_not_ignored(self):
        for site in SITES:
            for wrong in (site.wrong if site.p_wrong is None else site.p_wrong):
                with self.subTest(site=site.name, preferred=repr(wrong)):
                    self.assertEqual(broken(site, lane_of(site, site.body(p=wrong))[1]), [], f"{site.p[-1]}={wrong!r} beside {site.a[-1]}={site.a_valid!r}")

    def test_the_alternate_alone_is_read(self):
        for site in SITES:
            for wrong in site.wrong:
                with self.subTest(site=site.name, alternate=repr(wrong)):
                    self.assertEqual(broken(site, lane_of(site, site.body(p=ABSENT, a=wrong))[1]), [], f"{site.a[-1]}={wrong!r}, {site.p[-1]} left out")

    def test_the_valid_alternate_alone_and_the_valid_preferred_alone_are_read(self):
        for site in SITES:
            for label, kwargs in (("alternate alone", {"p": ABSENT}), ("preferred alone", {"a": ABSENT})):
                with self.subTest(site=site.name, which=label):
                    out, lane = lane_of(site, site.body(**kwargs))
                    self.assertEqual((lane.get("coverage"), lane.get("completeness"), lane.get("count")), ("searched_ok", "complete", len(site.op.ids)), f"{site.name} {label}: {lane}")


class OtherFormsOfTheSameShape(unittest.TestCase):
    """The sites that are not one field beside another field of one record: a second list, a second place for an error, a second DOI, a second structure."""

    def test_europepmc_the_source_is_read_even_when_the_id_that_needs_it_is_missing(self):
        """`text(id) and text(source)` read `source` only when `id` was there."""
        site = SITES[[s.name for s in SITES].index("europepmc.find: doi beside id")]
        for wrong in TEXT_WRONG:
            with self.subTest(source=repr(wrong)):
                body = site.body(a=ABSENT)
                body["resultList"]["result"][0]["source"] = wrong
                self.assertEqual(broken(site, lane_of(site, body)[1]), [])

    def test_unpaywall_a_best_location_that_cannot_be_read_costs_completeness_and_not_the_listed_locations(self):
        site = Site("unpaywall.enrich: best location", ops.UNPAYWALL, "member", ("oa_locations", 0), ("url",), "https://example.org/1", ("url",), "https://example.org/1", ())
        for wrong in (False, 0, "", [], "x", 5, [1], True):
            with self.subTest(best=repr(wrong)):
                body = site.body()
                body["best_oa_location"] = wrong
                out, lane = lane_of(site, body)
                self.assertEqual((lane["completeness"], lane.get("error_class"), lane.get("count")), ("partial", "payload_invalid", 3), lane)
                self.assertEqual(lane["retrieved"], list(site.op.ids))

    def test_unpaywall_nothing_listed_and_a_best_location_that_cannot_be_read_is_unreadable(self):
        body = copy.deepcopy(corrupt_route(ops.UNPAYWALL).body)
        body["oa_locations"], body["best_oa_location"] = [], [1]
        out, lane = run(ops.UNPAYWALL, body)
        self.assertEqual((lane["coverage"], lane["completeness"], lane.get("count")), ("provider_unavailable", "unobserved", None))

    def test_unpaywall_control_the_best_location_stands_in_for_none_listed_and_is_otherwise_left_alone(self):
        for locations, best, want in (([], ops.unpaywall_location(1), 1), ([], None, 0), ([ops.unpaywall_location(1)], None, 1), ([ops.unpaywall_location(1)], {}, 1)):
            with self.subTest(locations=len(locations), best=bool(best)):
                body = copy.deepcopy(corrupt_route(ops.UNPAYWALL).body)
                body["oa_locations"], body["best_oa_location"] = locations, best
                out, lane = run(ops.UNPAYWALL, body)
                self.assertEqual((lane["completeness"], lane.get("count", 0)), ("complete", want), lane)

    def test_doaj_every_doi_an_article_lists_is_read(self):
        site = Site("doaj.find: second DOI", ops.DOAJ_FIND_MORE, "member", ("results", 0), ("id",), "j1", ("id",), "j1", ())
        for wrong in TEXT_WRONG:
            with self.subTest(second=repr(wrong)):
                body = site.body()
                body["results"][0]["bibjson"]["identifier"].append({"type": "doi", "id": wrong})
                self.assertEqual(broken(site, lane_of(site, body)[1]), [])
        body = site.body()
        body["results"][0]["bibjson"]["identifier"].append({"type": "doi", "id": "10.1000/other"})
        self.assertEqual(lane_of(site, body)[1]["retrieved"], list(site.op.ids), "the first DOI is the article's identifier")

    def test_openaire_every_doi_a_record_lists_is_read(self):
        site = Site("openaire.find: second DOI", ops.OPENAIRE_FIND_MORE, "member", ("results", 0), ("id",), "oa::1", ("id",), "oa::1", ())
        for wrong in TEXT_WRONG:
            with self.subTest(second=repr(wrong)):
                body = site.body()
                body["results"][0]["instances"][0]["alternateIdentifiers"].append({"scheme": "doi", "value": wrong})
                self.assertEqual(broken(site, lane_of(site, body)[1]), [])
        body = site.body()
        body["results"][0]["instances"][0]["alternateIdentifiers"].append({"scheme": "doi", "value": "10.46298/other"})
        self.assertEqual(lane_of(site, body)[1]["retrieved"], list(site.op.ids), "the first DOI is the record's identifier")

    def test_bea_every_listing_key_the_answer_carries_is_read_before_the_first_is_chosen(self):
        for key in ("ParamValue", "Parameter"):
            for wrong in (False, 0, "", "x", 7, True):
                with self.subTest(key=key, wrong=repr(wrong)):
                    body = copy.deepcopy(corrupt_route(ops.BEA_LIST).body)
                    body["BEAAPI"]["Results"][key] = wrong
                    out, lane = run(ops.BEA_LIST, body)
                    self.assertEqual((lane["coverage"], lane["completeness"], lane.get("count")), ("provider_unavailable", "unobserved", None), lane)
        body = copy.deepcopy(corrupt_route(ops.BEA_LIST).body)
        body["BEAAPI"]["Results"]["ParamValue"] = [{"Key": "A"}]
        self.assertEqual(run(ops.BEA_LIST, body)[1]["completeness"], "complete", "a second listing that is readable is not an error; the first is the table")

    def test_bea_an_error_stated_in_either_place_is_read_whichever_the_answer_chose(self):
        valid = {"APIErrorDescription": "bad key"}
        for place, other in ((("BEAAPI", "Results", "Error"), ("BEAAPI", "Error")), (("BEAAPI", "Error"), ("BEAAPI", "Results", "Error")), (("BEAAPI", "Error"), None)):
            for wrong in (False, 0, "", [], "x", 5):
                with self.subTest(place=place, beside=other, wrong=repr(wrong)):
                    body = copy.deepcopy(corrupt_route(ops.BEA_GETDATA).body)
                    for where, value in ((other, valid), (place, wrong)):
                        if where is None:
                            continue
                        holder = body
                        for step in where[:-1]:
                            holder = holder[step]
                        holder[where[-1]] = value
                    out, lane = run(ops.BEA_GETDATA, body)
                    self.assertEqual((lane["coverage"], lane["completeness"], lane.get("count")), ("provider_unavailable", "unobserved", None), lane)

    def test_bea_an_error_that_one_place_states_is_reported_whatever_the_other_holds(self):
        for body_error, other in (({"APIErrorDescription": "bad key"}, {"APIErrorDescription": "other"}), ({"APIErrorDescription": "bad key"}, None)):
            body = copy.deepcopy(corrupt_route(ops.BEA_GETDATA).body)
            body["BEAAPI"]["Results"]["Error"] = body_error
            if other:
                body["BEAAPI"]["Error"] = other
            out, lane = run(ops.BEA_GETDATA, body)
            self.assertIn("bad key", " ".join(out.get("capability_facts") or []) + " ".join(out.get("facts") or []))

    def test_sdmx_every_place_a_message_states_its_structure_is_read(self):
        for field, wrongs in (("structures", (False, 0, "", {}, "x", 5, True)), ("data", (False, 0, "", [], "x", 5, True))):
            for wrong in wrongs:
                with self.subTest(field=field, wrong=repr(wrong)):
                    body = copy.deepcopy(corrupt_route(ops.ECB_DATA).body)
                    body[field] = wrong
                    out, lane = run(ops.ECB_DATA, body)
                    self.assertEqual((lane["coverage"], lane["completeness"], lane.get("count")), ("provider_unavailable", "unobserved", None), lane)
        body = copy.deepcopy(corrupt_route(ops.ECB_DATA).body)
        body["structures"], body["data"] = [], None
        self.assertEqual(run(ops.ECB_DATA, body)[1]["completeness"], "complete", "empty or null places that are not the one in use say nothing")

    def test_sdmx_data_sets_are_read_beside_a_wrapper_that_cannot_be_read(self):
        body = copy.deepcopy(corrupt_route(ops.ECB_DATA).body)
        body["data"] = False
        out, lane = run(ops.ECB_DATA, body)
        self.assertEqual((lane["coverage"], lane["completeness"]), ("provider_unavailable", "unobserved"))


def loader_client(url: str, body):
    t = FakeTransport()
    t.add("GET", url, 200, body)
    return Client(broker=Broker({sid: RatePolicy(per_second=100000) for sid in ("crossref", "datacite")}), transport=t, secrets=lambda n, f=None: "k", sleep=lambda s: None)


class LoaderAlternatives(unittest.TestCase):
    CROSSREF = {"message": {"items": [{"title": "J", "publisher": "P", "ISSN": ["9999-9991"], "issn-type": [{"value": "9999-9991", "type": "print"}]}]}}
    DATACITE = {"data": [{"id": "harvest.test", "attributes": {"name": "N", "symbol": "HARVEST.TEST", "url": "https://r.example.org"}}], "meta": {"totalPages": 1}}

    def crossref(self, **fields):
        body = copy.deepcopy(self.CROSSREF)
        body["message"]["items"][0].update(fields)
        skipped: list = []
        recs = list(registries.crossref_journals(loader_client("https://api.crossref.org/journals?", body), skipped=skipped))
        return recs, skipped

    def test_crossref_journals_read_both_issn_lists_before_choosing_one(self):
        for wrong in (False, 0, "", {}, "x", 5):
            with self.subTest(ISSN=repr(wrong)):
                recs, skipped = self.crossref(ISSN=wrong)
                self.assertEqual((recs, len(skipped)), ([], 1), "a journal whose ISSN list cannot be read is skipped and reported, whatever its issn-type says")
        recs, skipped = self.crossref(ISSN=["9999-9983"])
        self.assertEqual((recs[0]["identity"], skipped), ("issn:9999-9991", []), "the typed list is the one used; both are read")
        recs, skipped = self.crossref(**{"issn-type": []})
        self.assertEqual((recs[0]["identity"], skipped), ("issn:9999-9991", []), "an empty typed list falls back to the plain one")

    def datacite(self, **fields):
        body = copy.deepcopy(self.DATACITE)
        body["data"][0]["attributes"].update(fields.pop("attributes", {}))
        body["data"][0].update(fields)
        return list(registries.datacite_repositories(loader_client("https://api.datacite.org/repositories?", body)))

    def test_datacite_repositories_read_the_symbol_and_the_id_before_choosing(self):
        self.assertEqual(self.datacite()[0]["identity"], "repository:datacite:harvest.test")
        for wrong in (False, 0, [], {}, "", 7, ["x"]):
            with self.subTest(id=repr(wrong)):
                if wrong == "":
                    self.assertEqual(len(self.datacite(id=wrong)), 1, "an empty id names nothing, and the symbol is there")
                else:
                    self.assertEqual(self.datacite(id=wrong), [], "a repository whose id cannot be read is skipped, whatever its symbol says")
        self.assertEqual(self.datacite(attributes={"symbol": None})[0]["identity"], "repository:datacite:harvest.test")


class NestedAlternatives(unittest.TestCase):
    """R11-1 (Astra, 2b-repair-11): an alternative is decoded completely — its nested supported contents included — before one is chosen. A well-typed outer
    container whose supported fallback leaf is malformed hid behind a valid preferred value; each case has its readable control and its alternate-only control."""

    def test_unpaywall_the_best_location_is_decoded_as_a_location_beside_readable_listed_ones(self):
        for listed in (True, False):
            for bad in ("https://example.org/best", False, 0, [], {}):
                with self.subTest(listed=listed, best_url=repr(bad)):
                    body = copy.deepcopy(corrupt_route(ops.UNPAYWALL).body)
                    body["best_oa_location"] = {"url": bad}
                    if not listed:
                        body["oa_locations"] = []
                    out, lane = run(ops.UNPAYWALL, body)
                    expected = "complete" if isinstance(bad, str) else ("partial" if listed else "unobserved")
                    self.assertEqual(lane["completeness"], expected, lane)
                    if listed:
                        self.assertEqual(lane["retrieved"], list(ops.UNPAYWALL.ids), "the readable listed locations are all kept")
                    if not isinstance(bad, str) and listed:
                        self.assertEqual(lane.get("error_class"), "payload_invalid")

    def test_sdmx_json_every_place_a_structure_is_stated_is_decoded_beside_a_valid_one(self):
        for place in ("structures_first", "data_structure", "data_structures_first"):
            for preferred in (True, False):
                for bad in (False, 0, [], "bad", "CONTROL"):
                    with self.subTest(place=place, preferred_present=preferred, value=repr(bad)):
                        body = copy.deepcopy(corrupt_route(ops.ECB_DATA).body)
                        value = copy.deepcopy(body["structure"]) if bad == "CONTROL" else bad
                        if place == "structures_first":
                            body["structures"] = [value]
                        elif place == "data_structure":
                            body["data"] = {"structure": value}
                        else:
                            body["data"] = {"structures": [value]}
                        if not preferred:
                            del body["structure"]
                        out, lane = run(ops.ECB_DATA, body)
                        self.assertEqual(lane["completeness"], "complete" if bad == "CONTROL" else "unobserved", lane)
                        if bad != "CONTROL":
                            self.assertNotIn("count", lane, "an unreadable message has no count")

    def test_crossref_journals_a_plain_issn_list_is_decoded_beside_a_typed_one(self):
        probe = LoaderAlternatives()
        for preferred in (True, False):
            for bad in ("9999-9983", False, 0, [], {}):
                with self.subTest(typed_list_present=preferred, issn=repr(bad)):
                    fields = {"ISSN": [bad]}
                    if not preferred:
                        fields["issn-type"] = []
                    recs, skipped = probe.crossref(**fields)
                    want = (1, 0) if isinstance(bad, str) else (0, 1)
                    self.assertEqual((len(recs), len(skipped)), want)


if __name__ == "__main__":
    unittest.main()
