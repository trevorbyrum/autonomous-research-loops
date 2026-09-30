"""Task 2b, acceptance item 3: response-shape validation at the adapter boundary.

An unreadable successful answer — truncated JSON, an empty body, a parsed body without
the container the results live in — is never zero results (INVARIANTS H-5, RG-4;
design review §9). Every adapter parse path below is driven with those bodies and must
raise (PayloadError, or SourceUnavailable where the transport-level check already
refuses it); each one's paired control is the API's own answer for "nothing matched",
which must stay a successful empty result. The lane-level mapping of those outcomes
(coverage, completeness, error_class, count) is tests/test_lane_outcomes.py.

The empty-answer controls are the shapes each API documents for a query that matched
nothing (Crossref message.items, DOAJ results, Europe PMC resultList.result, Semantic
Scholar total 0 without data, DataCite data, Dataverse data.items, Socrata results,
Kaggle/Hugging Face bare lists, OpenML's HTTP 412 code 372, the Census API's 204, ...).
They are what the adapters were written against; no live API was called to re-derive
them, so a provider that changed its empty shape would surface as an unreadable answer
(a visible outage), never as a silent zero.
"""
from __future__ import annotations

import json
import unittest

from research_gateway.adapters import (bea, bis, bls, census, core, crossref, datacite, doaj, ecb, europepmc, fred, govinfo,
                                       harvard_dataverse, huggingface, kaggle, opencitations, openml, qdr, semanticscholar,
                                       socrata, unpaywall)
from research_gateway.adapters.base import Client, FakeTransport, PayloadError, Response, SourceUnavailable
from research_gateway.core.identity import RegistrationAgencies
from research_gateway.core.broker import Broker, RatePolicy

KEYS = {("kaggle", "username"): "u", ("kaggle", "key"): "k", ("api_data_gov", None): "g", ("core", None): "c",
        ("fred", None): "f", ("bea", None): "b", ("census", None): "cs", ("bls", None): "l"}
SIDS = ("doi_org", "crossref", "doaj", "europepmc", "semanticscholar", "datacite", "harvard_dataverse", "qdr", "socrata", "kaggle",
        "huggingface", "openml", "govinfo", "unpaywall", "opencitations", "core", "fred", "bea", "census", "bls", "bis", "ecb")
SOCRATA_VOUCH = ("GET", "https://api.us.socrata.com/api/catalog/v1?domains=data.example.gov",
                 {"results": [{"metadata": {"domain": "data.example.gov"}}]})
BIS_EMPTY = ('<message:StructureSpecificData xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message">'
             '<message:Header><message:ID>x</message:ID></message:Header></message:StructureSpecificData>')


def client() -> tuple[Client, FakeTransport]:
    t = FakeTransport()
    socrata.reset_known_domains()
    b = Broker({sid: RatePolicy(per_second=1000) for sid in SIDS})
    return Client(broker=b, transport=t, secrets=lambda n, f=None: KEYS.get((n, f))), t


# (label, call, method, url prefix of the answer under test, the API's "nothing matched" answer
#  as (status, body), how the adapter reports nothing, extra routes needed first)
CASES = [
    ("crossref find", lambda c: crossref.find(c, "q"), "GET", "https://api.crossref.org/works?",
     (200, {"message": {"items": [], "total-results": 0}}), lambda o: o["records"] == [], ()),
    ("crossref resolve", lambda c: crossref.resolve(c, "doi:10.1234/x"), "GET", "https://api.crossref.org/works/10.1234/x",
     (404, b""), lambda o: o is None, ()),
    ("crossref references", lambda c: crossref.enrich(c, "doi:10.1234/x", "references"), "GET", "https://api.crossref.org/works/10.1234/x",
     (200, {"message": {"DOI": "10.1234/x"}}), lambda o: o["items"] == [], ()),
    ("doaj find", lambda c: doaj.find(c, "q"), "GET", "https://doaj.org/api/search/articles/",
     (200, {"results": [], "total": 0}), lambda o: o["records"] == [], ()),
    ("doaj resolve", lambda c: doaj.resolve(c, "doi:10.1234/x"), "GET", "https://doaj.org/api/search/articles/",
     (200, {"results": [], "total": 0}), lambda o: o is None, ()),
    ("europepmc find", lambda c: europepmc.find(c, "q"), "GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search?",
     (200, {"hitCount": 0, "resultList": {"result": []}}), lambda o: o["records"] == [], ()),
    ("semanticscholar find", lambda c: semanticscholar.find(c, "q"), "GET", "https://api.semanticscholar.org/graph/v1/paper/search?",
     (200, {"total": 0, "offset": 0}), lambda o: o["records"] == [], ()),
    ("semanticscholar resolve", lambda c: semanticscholar.resolve(c, "doi:10.1234/x"), "GET", "https://api.semanticscholar.org/graph/v1/paper/",
     (404, b""), lambda o: o is None, ()),
    ("semanticscholar citations", lambda c: semanticscholar.enrich(c, "doi:10.1234/x", "citations"), "GET",
     "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234/x/citations", (200, {"data": []}), lambda o: o["items"] == [], ()),
    ("datacite find", lambda c: datacite.find(c, "q"), "GET", "https://api.datacite.org/dois?",
     (200, {"data": [], "meta": {"total": 0}}), lambda o: o["records"] == [], ()),
    ("datacite resolve", lambda c: datacite.resolve(c, "doi:10.1234/x"), "GET", "https://api.datacite.org/dois/10.1234/x",
     (404, b""), lambda o: o is None, ()),
    ("harvard_dataverse find", lambda c: harvard_dataverse.find(c, "q"), "GET", "https://dataverse.harvard.edu/api/search?",
     (200, {"status": "OK", "data": {"total_count": 0, "items": []}}), lambda o: o["records"] == [], ()),
    ("qdr find", lambda c: qdr.find(c, "q"), "GET", "https://data.qdr.syr.edu/api/search?",
     (200, {"status": "OK", "data": {"total_count": 0, "items": []}}), lambda o: o["records"] == [], ()),
    ("harvard_dataverse resolve", lambda c: harvard_dataverse.resolve(c, "doi:10.1234/x"), "GET",
     "https://dataverse.harvard.edu/api/datasets/:persistentId/", (404, b""), lambda o: o is None, ()),
    ("socrata find", lambda c: socrata.find(c, "q"), "GET", "https://api.us.socrata.com/api/catalog/v1?q=",
     (200, {"results": [], "resultSetSize": 0}), lambda o: o["records"] == [], ()),
    ("socrata resolve", lambda c: socrata.resolve(c, "socrata:data.example.gov:abcd-1234"), "GET",
     "https://data.example.gov/api/views/abcd-1234.json", (404, b""), lambda o: o is None, (SOCRATA_VOUCH,)),
    ("kaggle find", lambda c: kaggle.find(c, "q"), "GET", "https://www.kaggle.com/api/v1/datasets/list?",
     (200, []), lambda o: o["records"] == [], ()),
    ("huggingface find", lambda c: huggingface.find(c, "q"), "GET", "https://huggingface.co/api/datasets?",
     (200, []), lambda o: o["records"] == [], ()),
    ("huggingface resolve", lambda c: huggingface.resolve(c, "hf:a/b"), "GET", "https://huggingface.co/api/datasets/a/b",
     (404, b""), lambda o: o is None, ()),
    ("openml find", lambda c: openml.find(c, "q"), "GET", "https://www.openml.org/api/v1/json/data/list/",
     (412, {"error": {"code": "372", "message": "No results"}}), lambda o: o["records"] == [], ()),
    ("openml resolve", lambda c: openml.resolve(c, "openml:1"), "GET", "https://www.openml.org/api/v1/json/data/1",
     (404, b""), lambda o: o is None, ()),
    ("govinfo find", lambda c: govinfo.find(c, "q"), "POST", "https://api.govinfo.gov/search",
     (200, {"count": 0, "results": []}), lambda o: o["records"] == [], ()),
    ("govinfo resolve", lambda c: govinfo.resolve(c, "govinfo:X"), "GET", "https://api.govinfo.gov/packages/X/summary",
     (404, b""), lambda o: o is None, ()),
    ("unpaywall oa_location", lambda c: unpaywall.enrich(c, "doi:10.1234/x"), "GET", "https://api.unpaywall.org/v2/10.1234/x",
     (200, {"doi": "10.1234/x", "is_oa": False, "best_oa_location": None, "oa_locations": []}), lambda o: o["items"] == [], ()),
    ("opencitations citations", lambda c: opencitations.enrich(c, "doi:10.1234/x", "citations"), "GET",
     "https://api.opencitations.net/index/v2/citations/", (200, []), lambda o: o["items"] == [], ()),
    ("opencitations metadata", lambda c: opencitations.enrich(c, "doi:10.1234/x", "metadata"), "GET",
     "https://api.opencitations.net/meta/v1/metadata/", (200, []), lambda o: o["items"] == [], ()),
    ("core full_text", lambda c: core.enrich(c, "doi:10.1234/x"), "GET", "https://api.core.ac.uk/v3/search/works",
     (200, {"totalHits": 0, "results": []}), lambda o: o["items"] == [], ()),
    ("fred data", lambda c: fred.data(c, {"series": "GDP"}), "GET", "https://api.stlouisfed.org/fred/series/observations",
     (200, {"observations": []}), lambda o: o["records"][0]["observations"] == [],
     (("GET", "https://api.stlouisfed.org/fred/series?", {"seriess": [{"id": "GDP", "title": "GDP", "notes": "."}]}),)),
    ("fred catalog", lambda c: fred.catalog(c, query="gdp"), "GET", "https://api.stlouisfed.org/fred/series/search",
     (200, {"seriess": []}), lambda o: o["entries"] == [], ()),
    ("bea data", lambda c: bea.data(c, {"dataset": "NIPA", "table": "T1", "frequency": "A", "year": "2024"}), "GET",
     "https://apps.bea.gov/api/data/", (200, {"BEAAPI": {"Results": {"Data": []}}}), lambda o: o["records"][0]["row_count"] == 0, ()),
    ("bea catalog", lambda c: bea.catalog(c), "GET", "https://apps.bea.gov/api/data/",
     (200, {"BEAAPI": {"Results": {"Dataset": []}}}), lambda o: o["entries"] == [], ()),
    ("census data", lambda c: census.data(c, {"dataset": "2022/acs/acs1", "get": "NAME"}), "GET",
     "https://api.census.gov/data/2022/acs/acs1?", (204, b""), lambda o: o["records"] == [], ()),
    ("census catalog", lambda c: census.catalog(c), "GET", "https://api.census.gov/data.json",
     (200, {"dataset": []}), lambda o: o["entries"] == [], ()),
    ("bls data", lambda c: bls.data(c, {"series": "X"}), "POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/",
     (200, {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": []}}), lambda o: o["records"] == [], ()),
    ("bls catalog", lambda c: bls.catalog(c), "GET", "https://api.bls.gov/publicAPI/v2/surveys",
     (200, {"Results": {"survey": []}}), lambda o: o["entries"] == [], ()),
    ("bis data", lambda c: bis.data(c, {"dataflow": "WS_EER", "key": "M"}), "GET", "https://stats.bis.org/api/v2/data/dataflow/BIS/",
     (200, BIS_EMPTY), lambda o: o["records"] == [], ()),
    ("ecb data", lambda c: ecb.data(c, {"dataflow": "EXR", "key": "D.USD"}), "GET", "https://data-api.ecb.europa.eu/service/data/",
     (200, {"structure": {"dimensions": {"series": [], "observation": []}}, "dataSets": []}), lambda o: o["records"] == [], ()),
]


XML_ANSWERS = ("bis data",)
LIST_ANSWERS = ("kaggle find", "huggingface find", "opencitations citations", "opencitations metadata", "census data")


def unreadable_bodies(label: str) -> list[tuple[str, bytes]]:
    """A truncated JSON document, an empty body, and a body of the wrong shape for this answer
    (JSON of the other container type, a JSON object without the answer's fields, or — for an
    SDMX-ML answer — well-formed XML that is not an SDMX data message)."""
    bodies = [("truncated JSON", b'{"results": [{"id": "1", "tit'), ("empty body", b"")]
    if label in XML_ANSWERS:
        return bodies + [("not SDMX-ML", b"<Envelope><Fault/></Envelope>")]
    wrong = [{"unexpected": True}] if label in LIST_ANSWERS else [[], {"unexpected": True}]
    return bodies + [(f"wrong shape {json.dumps(w)}", json.dumps(w).encode()) for w in wrong]


class AdapterBoundary(unittest.TestCase):
    def run_case(self, case, status, body):
        label, call, method, prefix, _control, _is_empty, extra = case
        c, t = client()
        for m, url, answer in extra:
            t.add(m, url, body=answer)
        t.add(method, prefix, status=status, body=body)
        self.transport = t
        return call(c)

    def test_an_unreadable_success_is_never_an_empty_answer(self):
        for case in CASES:
            label = case[0]
            for what, body in unreadable_bodies(label):
                with self.subTest(label, body=what):
                    with self.assertRaises((PayloadError, SourceUnavailable)):
                        out = self.run_case(case, 200, body)
                        self.fail(f"{label} read {what} as {out!r}")

    def test_control_the_apis_own_empty_answer_stays_empty(self):
        for case in CASES:
            label, _call, _m, _p, (status, body), is_empty, _extra = case
            with self.subTest(label):
                self.assertTrue(is_empty(self.run_case(case, status, body)), label)
                self.assertTrue(any(m == case[2] and url.startswith(case[3]) for m, url, *_ in self.transport.calls),
                                f"{label}: the answer under test was actually asked for")

    def test_a_search_endpoints_404_is_an_outage_not_no_results(self):
        finds = [c for c in CASES if c[0].endswith(" find")]
        self.assertGreaterEqual(len(finds), 12)
        for case in finds:
            with self.subTest(case[0]):
                with self.assertRaises(SourceUnavailable):
                    self.run_case(case, 404, b"")

    def test_the_json_reader_refuses_what_it_cannot_read(self):
        # the boundary's own reader, before any adapter's shape check: an empty or unparseable
        # success is an error, never None standing in for "nothing" (H-5)
        for body in (b"", b'{"results": [', b"<html>x</html>", b"\xff\xfe"):
            with self.subTest(body=body):
                with self.assertRaises(PayloadError):
                    Response(200, {}, body, "u").json
        self.assertEqual(Response(200, {}, b'{"results": []}', "u").json, {"results": []}, "control")
        self.assertIsNone(Response(200, {}, b"", "u").json_or_none(), "bookkeeping (the call-log count) reads leniently")

    def test_a_garbled_registration_agency_answer_is_not_remembered(self):
        c, t = client()
        t.add("GET", "https://doi.org/ra/10.1234/x", body=b'[{"DOI": "10.1234/x", "RA": "Cross')
        cache: dict = {}
        with self.assertRaises(PayloadError):
            RegistrationAgencies(c, cache).agency("10.1234/x")
        self.assertEqual(cache, {}, "an unreadable answer is not cached as the prefix's agency")
        t.routes.clear()
        t.add("GET", "https://doi.org/ra/10.1234/x", body=[{"DOI": "10.1234/x", "RA": "Crossref"}])
        self.assertEqual((RegistrationAgencies(c, cache).agency("10.1234/x"), cache), ("Crossref", {"10.1234": "Crossref"}), "control")

    def test_openml_412_means_no_results_only_with_code_372(self):
        case = next(c for c in CASES if c[0] == "openml find")
        with self.assertRaises(SourceUnavailable):
            self.run_case(case, 412, {"error": {"code": "999", "message": "something else"}})


if __name__ == "__main__":
    unittest.main()
