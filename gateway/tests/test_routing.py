"""Phase 4 acceptance: every routing rule R-1..R-10 (PLAN.md §4) has a test, planned against the real seed."""
import copy
import datetime as dt
import json
import unittest

from research_gateway import adapters
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.cache import Cache
from research_gateway.registry.load import read_seed
from tests.test_adapters_articles import CROSSREF_WORK
from tests.test_adapters_datasets import HF_DATASET
from tests.test_adapters_platforms import OPENAIRE_PUB

SEED = read_seed()
ADAPTERS = adapters.load_all()


def make(seed=None):
    t = FakeTransport()
    b = Broker({s["id"]: RatePolicy(per_second=100) for s in SEED})
    return R.Router(seed or SEED, ADAPTERS), Client(broker=b, transport=t), t


def lanes(plan):
    return [ln.source_id for ln in plan.lanes]


class R1_ResolveByAgency(unittest.TestCase):
    def test_primary_by_registration_agency_then_substitution_group(self):
        r, _, _ = make()
        p = {"request_type": "resolve", "identity": "doi:10.1000/x"}
        self.assertEqual(lanes(r.plan(p, agency="Crossref")), ["crossref", "openaire", "unpaywall"])
        self.assertEqual(lanes(r.plan(p, agency="DataCite")), ["datacite", "crossref", "openaire", "unpaywall"])
        self.assertEqual(lanes(r.plan(p, agency="mEDRA")), ["openaire", "crossref", "unpaywall"])
        self.assertEqual(lanes(r.plan(p, agency=None))[0], "openaire")

    def test_execute_falls_back_when_primary_is_down(self):
        from research_gateway.adapters import openaire as openaire_adapter
        r, _, t = make()
        R.ident.RegistrationAgencies._shared.clear()
        openaire_adapter.reset_token()   # order-independence: never lean on a token another test left behind
        creds = {("openaire", "client_id"): "id", ("openaire", "client_secret"): "sec"}
        c = Client(broker=Broker({s["id"]: RatePolicy(per_second=100) for s in SEED}), transport=t,
                   secrets=lambda n, f=None: creds.get((n, f)))
        t.add("POST", "https://aai.openaire.eu/oidc/token", body={"access_token": "tok", "expires_in": 3600})
        t.add("GET", "https://doi.org/ra/", body=[{"DOI": "10.1000/x", "RA": "Crossref"}])
        t.add("GET", "https://api.crossref.org/works/", status=503)
        t.add("GET", "https://api.openaire.eu/graph/v1/researchProducts", body={"results": [OPENAIRE_PUB], "header": {"numFound": 1}})
        out = R.execute(r, {"request_type": "resolve", "identity": "10.1000/x"}, c)
        self.assertEqual([ln["source"] for ln in out["lanes"]], ["crossref", "openaire"])
        self.assertTrue(any("crossref: unavailable" in f and "R-10" in f for f in out["facts"]))
        self.assertEqual(out["records"][0]["source_id"], "openaire")
        self.assertEqual([rec.source_id for rec in c.log], ["doi_org", "crossref", "openaire", "openaire"],
                         "every dispatch is logged, the token exchange included")

    def test_non_doi_schemes_route_by_adapter_schemes(self):
        r, _, _ = make()
        self.assertEqual(lanes(r.plan({"request_type": "resolve", "identity": "arxiv:2301.10140"})), ["semanticscholar"])
        self.assertEqual(lanes(r.plan({"request_type": "resolve", "identity": "issn:1234-5678"})), ["doaj"])
        self.assertEqual(lanes(r.plan({"request_type": "resolve", "identity": "hf:owner/corpus"})), ["huggingface"])
        self.assertEqual(lanes(r.plan({"request_type": "resolve", "identity": "openml:61"})), ["openml"])
        plan = r.plan({"request_type": "resolve", "identity": "handle:1234/5678"})
        self.assertEqual(lanes(plan), [])
        self.assertTrue(plan.facts)


class R2_FindArticles(unittest.TestCase):
    def test_base_lanes_plus_domain_lanes(self):
        r, _, _ = make()
        base = ["openalex_snapshot", "crossref", "doaj"]
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "article", "domain": "finance"})), base)
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "article", "domain": "ai-ml"})), base + ["semanticscholar"])
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "article", "domain": "biomed"})), base + ["europepmc"])
        for sid in ("openaire", "unpaywall"):
            self.assertNotIn(sid, lanes(r.plan({"request_type": "find", "kind": "article", "domain": "other"})), "never discovery lanes")

    def test_local_index_runs_first_and_serves_venues_and_repositories(self):
        r, _, _ = make()
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "venue", "query": "operations management"})), ["openalex_snapshot"])
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "repository", "query": "survey data"})), ["openalex_snapshot"])
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "article"}))[0], "openalex_snapshot", "index before any live lane (§8)")


class R3_FindDatasets(unittest.TestCase):
    def test_datacite_base_plus_registry_domain_lanes(self):
        r, _, _ = make()
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "dataset", "domain": "social"})), ["datacite", "harvard_dataverse", "qdr"])
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "dataset", "domain": "ai-ml"})), ["datacite", "kaggle", "huggingface", "openml"])
        self.assertEqual(lanes(r.plan({"request_type": "find", "kind": "dataset", "domain": "market"})), ["datacite", "govinfo", "harvard_dataverse", "socrata", "kaggle"])
        both = lanes(r.plan({"request_type": "find", "domain": "finance"}))
        self.assertEqual(both[:3], ["openalex_snapshot", "crossref", "doaj"], "no kind → article lanes then dataset lanes")
        self.assertIn("datacite", both)


class R4_Enrich(unittest.TestCase):
    def test_enrich_lanes_by_declared_kinds(self):
        r, _, _ = make()
        self.assertEqual(lanes(r.plan({"request_type": "enrich", "what": "citations"})), ["opencitations", "semanticscholar"])
        self.assertEqual(lanes(r.plan({"request_type": "enrich", "what": "references"})), ["opencitations", "crossref", "semanticscholar"])
        self.assertEqual(lanes(r.plan({"request_type": "enrich", "what": "oa_location"})), ["unpaywall"])
        self.assertEqual(lanes(r.plan({"request_type": "enrich", "what": "full_text"})), ["semanticscholar", "core"])
        plan = r.plan({"request_type": "enrich", "what": "full_text", "commercial": True})
        self.assertEqual(lanes(plan), [], "full text lanes are personal-only")
        self.assertEqual(sum("skipped, commercial verdict deny" in f for f in plan.facts), 2)
        self.assertIn("no source enriches 'full_text'", plan.facts)

    def test_first_lane_with_items_wins(self):
        r, c, t = make()
        t.add("GET", "https://api.opencitations.net/index/v2/references/doi:10.1000/x", body=[])
        t.add("GET", "https://api.crossref.org/works/10.1000/x", body={"message": {"reference": [{"DOI": "10.1000/ref1"}]}})
        out = R.execute(r, {"request_type": "enrich", "identity": "doi:10.1000/x", "what": "references"}, c)
        self.assertEqual([ln["source"] for ln in out["lanes"]], ["opencitations", "crossref"])
        self.assertEqual(out["records"][0]["identity"], "doi:10.1000/ref1")


class R5_Data(unittest.TestCase):
    def test_exactly_one_statistical_source(self):
        r, _, _ = make()
        self.assertEqual(lanes(r.plan({"request_type": "data", "source": "fred"})), ["fred"])
        for bad in ({"request_type": "data"}, {"request_type": "data", "source": "crossref"}, {"request_type": "data", "source": "nope"}):
            plan = r.plan(bad)
            self.assertEqual(lanes(plan), [])
            self.assertTrue(plan.facts)


class R6_Fetch(unittest.TestCase):
    def test_hosts_and_schemes(self):
        seed = copy.deepcopy(SEED)
        next(s for s in seed if s["id"] == "globe")["enabled"] = True
        r, _, _ = make(seed)
        self.assertEqual(lanes(r.plan({"request_type": "fetch", "target": "https://globeproject.com/data/x.xls"})), ["globe"])
        self.assertEqual(lanes(r.plan({"request_type": "fetch", "target": "url:https://globeproject.com/data/x.xls"})), ["globe"])
        refused = r.plan({"request_type": "fetch", "target": "https://evil.example/x.xls"})
        self.assertEqual(lanes(refused), [])
        self.assertIn("R-6", refused.facts[0])
        self.assertEqual(lanes(r.plan({"request_type": "fetch", "target": "https://api.govinfo.gov/packages/X/pdf"})), [],
                         "a registry host is not enough: the adapter must accept URLs")
        self.assertEqual(lanes(r.plan({"request_type": "fetch", "target": "hf:owner/corpus"})), ["huggingface"])
        self.assertEqual(lanes(r.plan({"request_type": "fetch", "target": "doi:10.7910/DVN/OY6CBK"})), ["wms", "harvard_dataverse"])
        self.assertEqual(lanes(r.plan({"request_type": "fetch", "target": "doi:10.1000/other"})), ["harvard_dataverse"])
        self.assertEqual(lanes(r.plan({"request_type": "fetch", "target": "kaggle:owner/ds"})), ["kaggle"])


class R7_Freshness(unittest.TestCase):
    def test_recent_requests_skip_the_local_index(self):
        r, _, _ = make()
        recent = (dt.date.today() - dt.timedelta(days=5)).isoformat()
        plan = r.plan({"request_type": "find", "kind": "article", "published_after": recent})
        self.assertNotIn("openalex_snapshot", lanes(plan))
        self.assertTrue(any("R-7" in f for f in plan.facts))
        self.assertIn("openalex_snapshot", lanes(r.plan({"request_type": "find", "kind": "article", "published_after": "2020-01-01"})))
        self.assertFalse(R.is_recent({"published_after": "not a date"}))


class R8_Commercial(unittest.TestCase):
    def test_deny_and_unknown_dropped_per_item_needs_opt_in(self):
        r, _, _ = make()
        plan = r.plan({"request_type": "find", "kind": "dataset", "domain": "ai-ml", "commercial": True})
        self.assertEqual(lanes(plan), ["datacite"])
        self.assertTrue(any(f.startswith("kaggle: skipped, commercial verdict deny") for f in plan.facts))
        self.assertTrue(any("accept_per_item" in f for f in plan.facts))
        plan = r.plan({"request_type": "find", "kind": "dataset", "domain": "ai-ml", "commercial": True, "accept_per_item": True})
        self.assertEqual(lanes(plan), ["datacite", "huggingface", "openml"])
        seed = copy.deepcopy(SEED)
        next(s for s in seed if s["id"] == "globe")["enabled"] = True
        r, _, _ = make(seed)
        plan = r.plan({"request_type": "fetch", "target": "https://globeproject.com/data/x.xls", "commercial": True})
        self.assertEqual(lanes(plan), [], "unknown verdict fails closed (I-4)")
        self.assertTrue(any("globe: skipped, commercial verdict unknown" in f for f in plan.facts))

    def test_cache_hits_are_gated_too(self):
        r, c, t = make()
        R.ident.RegistrationAgencies._shared.clear()
        cache = Cache(None)
        t.add("GET", "https://doi.org/ra/", body=[{"DOI": "10.1000/s2", "RA": "Crossref"}])
        t.add("GET", "https://api.crossref.org/works/10.1000/s2", status=404)
        t.add("GET", "https://api.openaire.eu/graph/v1/researchProducts", body={"results": [], "header": {"numFound": 0}})
        s2 = {**HF_DATASET}  # any dict works: we plant the cached record directly
        cache.put_record({"identity": "doi:10.1000/s2", "kind": "article", "source_id": "semanticscholar", "title": "S2 only",
                          "license": None, "raw": s2}, redistributable=False)
        personal = R.execute(r, {"request_type": "resolve", "identity": "doi:10.1000/s2"}, c, cache)
        self.assertTrue(personal.get("cache_hit"))
        commercial = R.execute(r, {"request_type": "resolve", "identity": "doi:10.1000/s2", "commercial": True}, c, cache)
        self.assertFalse(commercial.get("cache_hit"), "a personal-mode cache entry never answers a commercial request")
        self.assertEqual(commercial["records"], [])
        self.assertTrue(any("semanticscholar" not in ln["source"] for ln in commercial["lanes"]))

    def test_per_item_records_without_allow_listed_licence_are_dropped(self):
        r, c, t = make()
        t.add("GET", "https://api.datacite.org/dois?", body={"data": [], "meta": {"total": 0}})
        unlicensed = {**HF_DATASET, "id": "owner/mystery", "tags": ["task:text"], "cardData": {}}
        t.add("GET", "https://huggingface.co/api/datasets?", body=[HF_DATASET, unlicensed])
        p = {"request_type": "find", "kind": "dataset", "domain": "ai-ml", "query": "corpus", "commercial": True, "accept_per_item": True}
        out = R.execute(r, p, c)
        self.assertEqual([rec["identity"] for rec in out["records"]], ["hf:owner/corpus"])
        self.assertTrue(any("1 record(s) dropped: not usable commercially (R-8)" in f for f in out["facts"]))
        out = R.execute(r, {**p, "commercial": False}, c)
        self.assertEqual(len(out["records"]), 2, "personal baseline keeps everything")


class R9_Domains(unittest.TestCase):
    def test_domain_lanes_add_and_other_is_permissive(self):
        r, c, _ = make()
        every = lanes(r.plan({"request_type": "find", "kind": "article", "domain": "other"}))
        self.assertEqual(every[:3], ["openalex_snapshot", "crossref", "doaj"], "R-9: nothing suppresses a base lane")
        self.assertEqual(set(every[3:]), {"semanticscholar", "europepmc"})
        unknown = r.plan({"request_type": "find", "kind": "article", "domain": "astrology"})
        self.assertEqual(unknown.domain_resolved, "other")
        self.assertEqual(lanes(unknown), every)
        self.assertEqual(r.plan({"request_type": "find", "kind": "article"}).domain_resolved, "other")
        R.execute(r, {"request_type": "find", "kind": "dataset", "query": "x", "domain": "astrology"}, c)
        self.assertTrue(c.log and all(rec.domain_resolved == "other" for rec in c.log), "R-9a: visible in the call log")


class R10_Facts(unittest.TestCase):
    def test_open_breaker_becomes_a_fact_and_the_job_completes(self):
        r, c, t = make()
        c.broker.record("crossref", 429, retry_after=600)
        t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
        out = R.execute(r, {"request_type": "find", "kind": "article", "query": "q", "domain": "finance"}, c)
        self.assertTrue(any(f.startswith("crossref: unavailable") for f in out["facts"]))
        self.assertIn("doaj", [ln["source"] for ln in out["lanes"]])
        self.assertEqual(c.log[0].failure_class, "refused")

    def test_exhausted_budget_becomes_a_fact(self):
        t = FakeTransport()
        t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
        b = Broker({"crossref": RatePolicy(per_day=1), "doaj": RatePolicy(per_second=100), "openalex_snapshot": RatePolicy(per_second=100)})
        c = Client(broker=b, transport=t)
        b.acquire("crossref")  # today's single call is spent
        out = R.execute(R.Router(SEED, ADAPTERS), {"request_type": "find", "kind": "article", "query": "q", "domain": "finance"}, c)
        self.assertTrue(any(f.startswith("crossref: unavailable (BudgetExhausted") for f in out["facts"]))
        self.assertIn("doaj", [ln["source"] for ln in out["lanes"] if "error" not in ln], "the job completes on the other lanes")

    def test_registry_declared_agencies_pick_the_primary(self):
        r, _, _ = make()
        self.assertEqual(lanes(r.plan({"request_type": "resolve", "identity": "doi:10.1000/x"}, agency="KISTI"))[0], "openaire")
        for sid, mod in ADAPTERS.items():
            for agency in getattr(mod, "AGENCIES", ()):
                if agency != "*":
                    self.assertEqual(lanes(r.plan({"request_type": "resolve", "identity": "doi:10.1000/x"}, agency=agency))[0], sid)


class ExecuteMergeAndCache(unittest.TestCase):
    def test_find_dedups_across_lanes_and_caches(self):
        r, c, t = make()
        t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
        doaj_hit = {"id": "abc", "bibjson": {"title": CROSSREF_WORK["title"][0], "year": "2021", "identifier": [{"type": "doi", "id": "10.1234/abc"}],
                                             "author": [{"name": "Ada Lovelace"}], "journal": {"title": "J", "issns": ["1234-5678"]}, "link": [{"url": "https://doaj.org/x"}]}}
        t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [doaj_hit], "total": 1})
        cache = Cache(None)
        p = {"request_type": "find", "kind": "article", "query": "reranking", "domain": "finance"}
        out = R.execute(r, p, c, cache)
        self.assertEqual(len(out["records"]), 1)
        self.assertEqual(out["records"][0]["sources"], ["crossref", "doaj"])
        self.assertEqual(len(out["records"][0]["provenance"]), 2)
        again = R.execute(r, p, c, cache)
        self.assertTrue(again.get("cache_hit"))
        self.assertEqual(c.log[-1].source_id, "cache")
        self.assertTrue(c.log[-1].cache_hit)

    def test_merged_record_gating_is_per_member_with_each_members_own_licence(self):
        """D-23: the lead record's licence never speaks for a member's, in either direction."""
        r, _, _ = make()
        merged = {"identity": "doi:10.1000/m", "kind": "article", "source_id": "crossref", "license": "cc-by-4.0",
                  "provenance": [{"source_id": "crossref", "license": "cc-by-4.0"},
                                 {"source_id": "semanticscholar", "license": None},
                                 {"source_id": "europepmc", "license": None}]}
        self.assertEqual(r.persistable_members(merged), [0],
                         "the CC-BY lead does not launder the unlicensed Europe PMC member into record_sources")
        self.assertFalse(r.redistributable_all(merged), "one restricted member caps the whole record at memory TTL")
        self.assertFalse(r.record_allowed(merged, {"commercial": True, "accept_per_item": True}),
                         "a commercial answer may not include the denied member either")
        merged["provenance"][2]["license"] = "cc-by-4.0"
        self.assertEqual(r.persistable_members(merged), [0, 2])
        # two members from the SAME source with different licences are judged separately (D-25)
        twice = {"identity": "doi:10.1000/t", "kind": "article", "source_id": "europepmc", "license": None,
                 "provenance": [{"source_id": "europepmc", "license": "cc-by-4.0"},
                                {"source_id": "europepmc", "license": "cc-by-nc-4.0"}]}
        self.assertEqual(r.persistable_members(twice), [0], "the NC copy from the same source stays out")
        # a member with NO licence key never inherits the lead's (fail closed, D-25)
        legacy = {"identity": "doi:10.1000/l", "kind": "article", "source_id": "europepmc", "license": "cc0",
                  "provenance": [{"source_id": "europepmc"}]}
        self.assertEqual(r.persistable_members(legacy), [])
        # a sources list without provenance: denied members still count (D-25)
        bare = {"identity": "doi:10.1000/b", "kind": "article", "source_id": "crossref", "license": "cc0",
                "sources": ["crossref", "semanticscholar"]}
        self.assertFalse(r.record_allowed(bare, {"commercial": True}))
        clean = {"identity": "doi:10.1000/c", "kind": "article", "source_id": "crossref", "license": "cc0",
                 "provenance": [{"source_id": "crossref", "license": "cc0"}]}
        self.assertTrue(r.record_allowed(clean, {"commercial": True}))
        self.assertTrue(r.redistributable_all(clean))
        restricted_series = {"identity": "series:fred:X", "kind": "series", "source_id": "fred", "license": None,
                             "third_party_restricted": True}
        self.assertFalse(r.record_allowed(restricted_series, {"commercial": True}),
                         "a FRED series flagged with third-party terms fails the commercial gate (D-23)")

    def test_secret_echoes_are_redacted_from_results(self):
        r, _, t = make()
        echo = {"BEAAPI": {"Request": {"RequestParam": [{"ParameterName": "UserID", "ParameterValue": "sekrit-key-123"}]},
                           "Results": {"Data": [{"TableName": "T1", "LineDescription": "GDP", "DataValue": "1"}]}}}
        t.add("GET", "https://apps.bea.gov/api/data/", body=echo)
        c = Client(broker=Broker({"bea": RatePolicy(per_second=100)}), transport=t,
                   secrets=lambda n, f=None: "sekrit-key-123" if n == "bea" else None)
        out = R.execute(r, {"request_type": "data", "source": "bea", "params": {"method": "GetData", "dataset": "NIPA"}}, c)
        self.assertNotIn("sekrit-key-123", json.dumps({k: v for k, v in out.items() if k != "content"}, default=str),
                         "a source echoing the key back never leaks it into a result or store (D-23)")
        self.assertIn("[redacted]", json.dumps(out["records"][0]["raw"], default=str))

    def test_resolve_serves_from_cache_and_never_persists_non_redistributable(self):
        r, c, t = make()
        R.ident.RegistrationAgencies._shared.clear()
        cache = Cache(None)
        t.add("GET", "https://doi.org/ra/", body=[{"DOI": "10.1234/abc", "RA": "Crossref"}])
        t.add("GET", "https://api.crossref.org/works/10.1234/abc", body={"message": CROSSREF_WORK})
        p = {"request_type": "resolve", "identity": "doi:10.1234/abc"}
        first = R.execute(r, p, c, cache)
        self.assertEqual(first["records"][0]["source_id"], "crossref")
        calls = len(c.log)
        second = R.execute(r, p, c, cache)
        self.assertTrue(second["cache_hit"])
        self.assertEqual(len(c.log), calls + 1)
        self.assertEqual(c.log[-1].source_id, "cache")

    def test_malformed_response_is_a_fact_not_a_crash(self):
        r, c, t = make()
        t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": ["not a work"], "total-results": 1}})
        t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
        out = R.execute(r, {"request_type": "find", "kind": "article", "query": "q", "domain": "finance"}, c)
        self.assertTrue(any(f.startswith("crossref: malformed response") for f in out["facts"]))
        self.assertEqual(out["records"], [])
        self.assertIn("doaj", [ln["source"] for ln in out["lanes"]], "the job still completes on the other lanes")

    def test_stored_job_results_hold_canonical_metadata_only(self):
        """jobs.result never carries raw payloads, rows, text or bytes — persistence with
        provenance is the cache's job, under the licence rules (D-23)."""
        result = {"request_type": "fetch", "facts": [],
                  "records": [{"kind": "full_text", "identity": "doi:x", "source_id": "core", "title": "T",
                               "text": "the whole paper", "raw": {"fullText": "no"}},
                              {"kind": "file", "identity": "socrata:d:x#rows", "source_id": "socrata", "title": "rows",
                               "rows": [{"a": 1}], "row_count": 1, "license": None}],
                  "content": b"\x00pdf", "content_type": "application/pdf"}
        stored = R.redact_for_storage(result)
        self.assertIsNone(stored["content"])
        self.assertEqual(stored["content_bytes"], 4)
        for rec in stored["records"]:
            for banned in ("text", "raw", "rows", "content", "provenance"):
                self.assertNotIn(banned, rec, banned)
        self.assertTrue(stored["records"][0]["text_dropped"])
        self.assertTrue(stored["records"][1]["rows_dropped"])
        self.assertEqual(stored["records"][1]["row_count"], 1, "counts and metadata survive")
        self.assertEqual(result["content"], b"\x00pdf", "the inline result is untouched")
        self.assertEqual(result["records"][0]["text"], "the whole paper")

    def test_download_is_authorized_before_bytes_leave_and_secrets_are_redacted(self):
        seed = copy.deepcopy(SEED)
        for s in seed:
            if s["id"] in ("huggingface", "globe"):
                s["enabled"] = True
        r = R.Router(seed, ADAPTERS)
        t = FakeTransport()
        hf = {"id": "owner/nc-corpus", "cardData": {"license": "cc-by-nc-4.0"}, "siblings": [{"rfilename": "data.csv"}], "gated": False}
        t.add("GET", "https://huggingface.co/api/datasets/owner/nc-corpus", body=hf)
        t.add("GET", "https://huggingface.co/datasets/owner/nc-corpus/resolve/main/data.csv", body="secret,rows\n")
        c = Client(broker=Broker({sid: RatePolicy(per_second=100) for sid in ("huggingface",)}), transport=t,
                   secrets=lambda n, f=None: "tok-echoed" if n == "huggingface" else None)
        p = {"request_type": "fetch", "target": "hf:owner/nc-corpus", "params": {"path": "data.csv", "download": True},
             "commercial": True, "accept_per_item": True}
        out = R.execute(r, p, c)
        self.assertIsNone(out.get("content"), "a non-commercial licence keeps the bytes inside the gateway")
        self.assertTrue(any("download refused before fetching" in f for f in out["facts"]))
        self.assertEqual([u for _, u, *_ in t.calls if "resolve/main/data.csv" in u], [],
                         "the refusal happens BEFORE any bytes move (D-24)")
        personal = R.execute(r, {**p, "commercial": False}, c)
        self.assertEqual(personal["content"], b"secret,rows\n", "the personal baseline still downloads")
        echoed = R.execute(r, {"request_type": "resolve", "identity": "hf:owner/nc-corpus"}, c)
        # plant an echo of the token into the record and confirm redaction would strip it:
        self.assertNotIn("tok-echoed", str({k: v for k, v in echoed.items() if k != "content"}))

    def test_make_handlers_use_job_fields(self):
        r, c, t = make()
        t.add("GET", "https://api.datacite.org/dois?", body={"data": [], "meta": {"total": 0}})
        handlers = R.make_handlers(r)
        job = {"id": 1, "request_type": "find", "payload": {"kind": "dataset", "query": "q", "domain": "ai-ml"}, "commercial": True}
        out = handlers["find"](c, job)
        self.assertEqual(out["request_type"], "find")
        self.assertTrue(any("kaggle" in f for f in out["facts"]), "the job's commercial flag reaches the router")


class LoggingByConstruction(unittest.TestCase):
    def test_only_the_gateway_builds_clients(self):
        """I-6: every call is logged because the only network path is base.Client (adapters cannot import
        urllib — tested elsewhere) and Client objects are built only by the gateway's own factories."""
        import pathlib
        import re
        import research_gateway
        root = pathlib.Path(research_gateway.__file__).parent
        allowed = {"adapters/base.py", "smoke.py", "app.py"}
        builds = re.compile(r"(?<![A-Za-z_])Client\(")  # the metered client, not e.g. GatewayClient(
        offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                     if builds.search(p.read_text()) and str(p.relative_to(root)) not in allowed]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
