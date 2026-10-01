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
single record or a whole catalogue is unreadable (provider_unavailable, payload_invalid, unobserved, no count). The structural half is `AlternativesAreAllRead`
below: no `or`, `and` or conditional expression reads two provider values lazily, apart from the listed reasons.
"""
from __future__ import annotations

import ast
import copy
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

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


# ------------------------------------------------------------------ the structural half: no site reads two provider values lazily
GATEWAY = Path(__file__).resolve().parent.parent / "research_gateway"
SCANNED = ([p for p in sorted((GATEWAY / "adapters").glob("*.py")) if p.name != "base.py"] + [GATEWAY / "core" / "sdmx.py", GATEWAY / "core" / "identity.py", GATEWAY / "core" / "canonical.py"]
           + sorted((GATEWAY / "harvest").glob("*.py")))
READERS = frozenset({"text", "key", "maybe_key", "boolean", "listed", "optional", "nested", "need", "field", "plain", "normalize_doi", "normalize_issn", "normalize_arxiv",
                     "year_from", "first_member", "member_key", "_named", "_held", "_yes", "_identifier", "token", "total", "offset_after", "counts_nothing", "_bytes"})


def reads(node: ast.AST) -> bool:
    """Whether evaluating `node` reads provider data: a `.get`, a subscript or a call of one of the readers every provider value passes through."""
    for n in ast.walk(node):
        if isinstance(n, ast.Subscript):
            return True
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr in ("get", "pop", "first", "each", "entries"):
                return True
            if (f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None) in READERS:
                return True
    return False


def lazy_sites(path: Path):
    """(line, kind, source) of every `or`, `and` and conditional expression with TWO OR MORE operands that read provider data inside the expression: the later
    operand is not evaluated when an earlier one decides, so a present malformed value there is never read."""
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.BoolOp):
            if sum(1 for v in n.values if reads(v)) >= 2:
                yield n.lineno, "or" if isinstance(n.op, ast.Or) else "and", ast.unparse(n)
        elif isinstance(n, ast.IfExp):
            if reads(n.body) and reads(n.orelse):
                yield n.lineno, "ifexp", ast.unparse(n)


# What the scan does not call a defect, with the reason; every entry is a site the scan finds and the sweep (evidence/2b-repair-11b/fallback-sites.md) classified.
# adapters/base.py is the metered client (HTTP headers, request parameters), not a reader of a provider's payload. A key is (file, the expression as `ast.unparse` writes it). The reasons: QUERY a search predicate over our own catalogue entries; GUARD a type or presence guard of
# one value, whose second operand is the same value read again; OWN our own canonical record or request, not a provider's answer; DISPATCH one field read once, by its kind;
# CONDITION a condition that decides whether to read, never which of two fields is chosen; FILE the operator's local snapshot, read tolerantly by design (test_harvest).
EXEMPT = {
    ("adapters/bea.py", "q in str(e.get('id', '')).lower() or q in str(e.get('label', '')).lower()"): "QUERY",
    ("adapters/bis.py", "not q or q in str(f['id']).lower() or q in str(f['label']).lower()"): "QUERY",
    ("adapters/ecb.py", "not q or q in str(f['id']).lower() or q in str(f['label']).lower()"): "QUERY",
    ("adapters/bls.py", "s.get('survey_abbreviation') and (not q or q in str(s.get('survey_name', '')).lower() or q in str(s.get('survey_abbreviation', '')).lower())"): "QUERY",
    ("adapters/bls.py", "not q or q in str(s.get('survey_name', '')).lower() or q in str(s.get('survey_abbreviation', '')).lower()"): "QUERY",
    ("adapters/census.py", "not all((isinstance(r, list) for r in j[1:])) or not all((isinstance(h, str) for h in j[0]))"): "GUARD",
    ("adapters/fred.py", "not s.get('id') and (not s.get('title'))"): "CONDITION",
    ("adapters/govinfo.py", "j.get('results') is not None or not counts_nothing(j.get('count'))"): "CONDITION",
    ("adapters/govinfo.py", "record.get('format') or (record.get('extra') or {}).get('format')"): "OWN",
    ("adapters/harvard_dataverse.py", "not allow_listed(ds.get('license')) or ds.get('terms_of_use') or file_restricted"): "CONDITION",
    ("adapters/huggingface.py", "record.get('path') or (record.get('extra') or {}).get('path')"): "OWN",
    ("adapters/huggingface.py", "record.get('revision') or (record.get('extra') or {}).get('revision') or 'main'"): "OWN",
    ("adapters/openaire.py", "_TOKEN.get('value') and float(_TOKEN.get('exp', 0)) > time.time() + 60"): "OWN",
    ("adapters/openaire.py", "j.get('results') is not None or not counts_nothing(field(j, 'header', 'numFound'))"): "CONDITION",
    ("adapters/openml.py", "[d.get('creator')] if isinstance(d.get('creator'), str) else listed(SOURCE_ID, d, 'creator')"): "DISPATCH",
    ("adapters/openml.py", "not files or files[0] is None or (not files[0]['links'][0].startswith(HOSTS))"): "CONDITION",
    ("adapters/semanticscholar.py", "text(SOURCE_ID, paper.get('paperId')) or text(SOURCE_ID, nested(SOURCE_ID, paper, 'externalIds').get('DOI'))"): "CONDITION",
    ("adapters/socrata.py", "len(parts) != 3 or parts[0] != 'socrata' or (not parts[1]) or (not parts[2])"): "GUARD",
    ("adapters/socrata.py", "r and isinstance(r.get('venue'), str) and r['venue']"): "GUARD",
    ("core/canonical.py", "isinstance(member.get(k), str) and member[k]"): "GUARD",
    ("core/sdmx.py", "_local(el.tag) == 'Dimension' and el.attrib.get('id') and all((el.attrib['id'] != d for _, d in dims))"): "GUARD",
    ("core/sdmx.py", "f['id'] == wanted and f['agency'] in (None, agency)"): "CONDITION",
    ("harvest/openalex_snapshot.py", "normalize_issn(s.get('issn_l')) or (issns[0] if issns else None)"): "FILE",
    ("harvest/registries.py", "s.get('name') if isinstance(s, dict) else text('datacite', s)"): "DISPATCH",
}


class AlternativesAreAllRead(unittest.TestCase):
    def test_no_site_chooses_between_two_provider_values_it_reads_lazily(self):
        found, seen = [], set()
        for path in SCANNED:
            rel = str(path.relative_to(GATEWAY))
            for line, kind, source in lazy_sites(path):
                seen.add((rel, source))
                if (rel, source) not in EXEMPT:
                    found.append(f"{rel}:{line} [{kind}] {source[:150]}")
        self.assertEqual(found, [], "read every operand first and choose after (base.preferred, base.identity_from), or list the site in EXEMPT with its reason: " + "; ".join(found))
        self.assertEqual(sorted(set(EXEMPT) - seen), [], "an exemption for a site that is no longer there")

    def test_the_scan_sees_the_shape_it_is_about(self):
        """Mutation check of the scan itself: the shapes the sweep replaced are found when written again."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.py"
            for source in ("def f(r, SOURCE_ID):\n    return text(SOURCE_ID, r.get('a')) or text(SOURCE_ID, r.get('b'))\n",
                           "def f(r, S):\n    return text(S, r.get('a')) and text(S, r.get('b'))\n",
                           "def f(a, S):\n    return normalize_doi(a.get('id')) if a.get('doi') in (None, '') else normalize_doi(a.get('doi'))\n"):
                path.write_text(source)
                self.assertEqual(len(list(lazy_sites(path))), 1, source)
            for source in ("def f(r, S):\n    a, b = text(S, r.get('a')), text(S, r.get('b'))\n    return a or b\n",
                           "def f(r, S):\n    return preferred(text(S, r.get('a')), text(S, r.get('b')))\n",
                           "def f(r, S):\n    return text(S, r.get('a')) or ''\n"):
                path.write_text(source)
                self.assertEqual(list(lazy_sites(path)), [], source)


if __name__ == "__main__":
    unittest.main()
