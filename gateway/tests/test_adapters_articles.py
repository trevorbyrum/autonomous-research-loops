"""Contract tests for the first adapter batch, against recorded response shapes (no network)."""
import unittest

from research_gateway import adapters
from research_gateway.adapters import crossref, datacite, doaj, opencitations, unpaywall
from research_gateway.adapters.base import Client, FakeTransport, SourceUnavailable
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.registry import load

CROSSREF_WORK = {
    "DOI": "10.1234/ABC", "type": "journal-article", "title": ["Reranking for retrieval"],
    "author": [{"given": "Ada", "family": "Lovelace"}, {"name": "Consortium X"}],
    "issued": {"date-parts": [[2021, 3, 1]]}, "container-title": ["Journal of IR"], "ISSN": ["12345678"],
    "URL": "https://doi.org/10.1234/abc", "license": [{"URL": "http://creativecommons.org/licenses/by/4.0/"}],
    "publisher": "Example Press", "is-referenced-by-count": 12, "reference-count": 2,
    "reference": [{"DOI": "10.1000/ref1"}, {"unstructured": "no doi here"}],
}


def client(policy_ids=("crossref", "doaj", "datacite", "unpaywall", "opencitations")):
    t = FakeTransport()
    b = Broker({sid: RatePolicy(per_second=100) for sid in policy_ids})
    return Client(broker=b, transport=t, contact_email="t@example.org"), t


class SeedConsistency(unittest.TestCase):
    def test_capabilities_match_seed(self):
        """I-2: each adapter's declared capabilities equal its registry row."""
        seed = {s["id"]: s for s in load.read_seed()}
        for sid, mod in adapters.load_all().items():
            self.assertIn(sid, seed, f"adapter {sid} has no registry row")
            self.assertEqual(sorted(mod.CAPABILITIES), sorted(seed[sid]["capabilities"]), sid)
            for cap in mod.CAPABILITIES:
                self.assertTrue(callable(getattr(mod, cap, None)), f"{sid} declares {cap} but has no function")

    def test_adapters_never_import_urllib(self):
        """I-1: only base.py talks to the network."""
        import pathlib
        for path in pathlib.Path(adapters.__file__).parent.glob("*.py"):
            if path.name in ("base.py", "__init__.py"):
                continue
            self.assertNotIn("urllib", path.read_text(), path.name)


class Crossref(unittest.TestCase):
    def test_find(self):
        c, t = client()
        t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1, "next-cursor": "abc"}})
        out = crossref.find(c, "reranking", limit=5, year_from_=2020)
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["next_cursor"], "abc")
        r = out["records"][0]
        self.assertEqual(r["identity"], "doi:10.1234/abc")
        self.assertEqual(r["authors"], ["Ada Lovelace", "Consortium X"])
        self.assertEqual(r["year"], 2021)
        self.assertEqual(r["identifiers"], {"doi": "10.1234/abc", "issn": "1234-5678"})
        self.assertEqual(r["cited_by_count"], 12)
        self.assertIn("filter=from-pub-date%3A2020", t.calls[0][1])
        self.assertIn("mailto=t%40example.org", t.calls[0][1])

    def test_resolve_and_references(self):
        c, t = client()
        t.add("GET", "https://api.crossref.org/works/10.1234/abc", body={"message": CROSSREF_WORK})
        self.assertEqual(crossref.resolve(c, "https://doi.org/10.1234/ABC")["title"], "Reranking for retrieval")
        refs = crossref.enrich(c, "doi:10.1234/abc", "references")
        self.assertEqual([i["identity"] for i in refs["items"]], ["doi:10.1000/ref1"])
        self.assertIsNone(crossref.resolve(c, "not-a-doi"))

    def test_404_is_none_and_500_raises(self):
        c, t = client()
        t.add("GET", "https://api.crossref.org/works/10.1000/missing", status=404)
        t.add("GET", "https://api.crossref.org/works/10.1000/broken", status=503)
        self.assertIsNone(crossref.resolve(c, "10.1000/missing"))
        with self.assertRaises(SourceUnavailable):
            crossref.resolve(c, "10.1000/broken")


class Doaj(unittest.TestCase):
    ARTICLE = {"id": "d1", "bibjson": {"title": "Open article", "year": "2022",
                                        "journal": {"title": "Open J", "issns": ["2222-333X"], "license": [{"type": "CC BY"}]},
                                        "identifier": [{"type": "doi", "id": "10.5555/oa1"}, {"type": "eissn", "id": "2222-333X"}],
                                        "author": [{"name": "B. Author"}], "link": [{"url": "https://openj.example/1"}]}}

    def test_find_and_cap(self):
        c, t = client()
        t.add("GET", "https://doaj.org/api/search/articles/", body={"total": 1, "results": [self.ARTICLE]})
        out = doaj.find(c, "open access", limit=10)
        r = out["records"][0]
        self.assertEqual(r["identity"], "doi:10.5555/oa1")
        self.assertEqual(r["identifiers"]["issn"], "2222-333X")
        self.assertEqual(r["license"], "CC BY")
        self.assertTrue(r["open_access"])
        self.assertIsNone(out["next_page"])
        capped = doaj.find(c, "x", limit=100, page=11)
        self.assertIn("caps a query", capped["capability_fact"])

    def test_resolve(self):
        c, t = client()
        t.add("GET", "https://doaj.org/api/search/articles/doi%3A%2210.5555/oa1%22", body={"total": 1, "results": [self.ARTICLE]})
        self.assertEqual(doaj.resolve(c, "doi:10.5555/oa1")["title"], "Open article")


class DataCite(unittest.TestCase):
    DOI = {"id": "10.5281/zenodo.99", "attributes": {"doi": "10.5281/zenodo.99", "titles": [{"title": "A dataset"}],
                                                     "creators": [{"name": "Curie, Marie"}], "publicationYear": 2020,
                                                     "publisher": "Zenodo", "types": {"resourceTypeGeneral": "Dataset"},
                                                     "url": "https://zenodo.org/record/99", "rightsList": [{"rightsIdentifier": "cc0-1.0"}]},
           "relationships": {"client": {"data": {"id": "cern.zenodo"}}}}

    def test_find_and_resolve(self):
        c, t = client()
        t.add("GET", "https://api.datacite.org/dois?", body={"data": [self.DOI], "meta": {"total": 150}})
        out = datacite.find(c, "climate", limit=100, page=1)
        r = out["records"][0]
        self.assertEqual(r["kind"], "dataset")
        self.assertEqual(r["identity"], "doi:10.5281/zenodo.99")
        self.assertEqual(r["license"], "cc0-1.0")
        self.assertEqual(r["client_id"], "cern.zenodo")
        self.assertEqual(out["next_page"], 2)
        t.add("GET", "https://api.datacite.org/dois/10.5281/zenodo.99", body={"data": self.DOI})
        self.assertEqual(datacite.resolve(c, "10.5281/zenodo.99")["venue"], "Zenodo")


class Unpaywall(unittest.TestCase):
    def test_oa_location(self):
        c, t = client()
        best = {"url": "https://pub.example/a", "url_for_pdf": "https://pub.example/a.pdf", "license": "cc-by", "host_type": "publisher", "version": "publishedVersion"}
        t.add("GET", "https://api.unpaywall.org/v2/10.1234/abc", body={"doi": "10.1234/abc", "is_oa": True, "oa_status": "gold",
                                                                        "title": "T", "year": 2021, "journal_name": "J",
                                                                        "best_oa_location": best, "oa_locations": [best]})
        out = unpaywall.enrich(c, "doi:10.1234/abc")
        self.assertEqual(out["oa_status"], "gold")
        self.assertEqual(out["items"][0]["links"], ["https://pub.example/a.pdf"])
        self.assertEqual(out["items"][0]["kind"], "oa_location")
        self.assertIn("email=t%40example.org", t.calls[0][1])

    def test_not_found(self):
        c, t = client()
        t.add("GET", "https://api.unpaywall.org/v2/10.1000/nope", status=404)
        self.assertEqual(unpaywall.enrich(c, "10.1000/nope")["items"], [])


class OpenCitations(unittest.TestCase):
    def test_citations_references_metadata(self):
        c, t = client()
        t.add("GET", "https://api.opencitations.net/index/v2/citations/doi:10.1234/abc",
              body=[{"oci": "1-2", "citing": "doi:10.9000/citer omid:br/1", "cited": "doi:10.1234/abc", "creation": "2022-01", "timespan": "P1Y"}])
        t.add("GET", "https://api.opencitations.net/index/v2/references/doi:10.1234/abc",
              body=[{"oci": "2-3", "citing": "doi:10.1234/abc", "cited": "doi:10.8000/cited", "creation": "2021"}])
        t.add("GET", "https://api.opencitations.net/meta/v1/metadata/doi:10.1234/abc",
              body=[{"id": "doi:10.1234/abc", "title": "T", "author": "Lovelace, Ada; Babbage, Charles", "pub_date": "2021-03", "venue": "Journal of IR [issn:1234-5678]"}])
        cites = opencitations.enrich(c, "doi:10.1234/abc", "citations")
        self.assertEqual(cites["items"][0]["identity"], "doi:10.9000/citer")
        self.assertEqual(cites["items"][0]["year"], 2022)
        refs = opencitations.enrich(c, "doi:10.1234/abc", "references")
        self.assertEqual(refs["items"][0]["identity"], "doi:10.8000/cited")
        meta = opencitations.enrich(c, "doi:10.1234/abc", "metadata")
        self.assertEqual(meta["items"][0]["authors"], ["Lovelace, Ada", "Babbage, Charles"])
        self.assertEqual(meta["items"][0]["venue"], "Journal of IR")


if __name__ == "__main__":
    unittest.main()
