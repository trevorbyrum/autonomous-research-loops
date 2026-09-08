"""Contract tests: OpenAIRE, Semantic Scholar, CORE, Europe PMC, OpenAlex local index."""
import json
import os
import unittest
import uuid

from research_gateway.adapters import core as core_adapter, europepmc, openaire, openalex_snapshot, semanticscholar
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import db
from research_gateway.core.broker import Broker, RatePolicy


def client(secrets=None):
    t = FakeTransport()
    b = Broker({sid: RatePolicy(per_second=100) for sid in ("openaire", "semanticscholar", "core", "europepmc", "openalex_snapshot")})
    store = secrets or {}
    return Client(broker=b, transport=t, contact_email="t@example.org",
                  secrets=lambda name, field=None: store.get((name, field)) or store.get((name, None)) if field else store.get((name, None))), t


OPENAIRE_PUB = {"id": "oa::1", "mainTitle": "Repository paper", "type": "publication", "publicationDate": "2024-05-01",
                "pids": None, "authors": [{"fullName": "Ada Lovelace"}],
                "instances": [{"alternateIdentifiers": [{"scheme": "doi", "value": "10.46298/abc"}], "license": "CC BY",
                               "urls": ["https://doi.org/10.46298/abc"]}]}
OPENAIRE_NODOI = {"id": "oa::2", "mainTitle": "Thesis without DOI", "type": "publication", "publicationDate": "2019",
                  "pids": [{"scheme": "handle", "value": "1234/5678"}], "instances": [{"urls": ["https://repo.example/5678"]}]}


class OpenAire(unittest.TestCase):
    def setUp(self):
        openaire.reset_token()

    def test_token_exchange_then_find(self):
        c, t = client({("openaire", "client_id"): "id", ("openaire", "client_secret"): "sec"})
        t.add("POST", "https://aai.openaire.eu/oidc/token", body={"access_token": "tok", "expires_in": 3600})
        t.add("GET", "https://api.openaire.eu/graph/v1/researchProducts?",
              body={"header": {"numFound": 2, "nextCursor": "c2"}, "results": [OPENAIRE_PUB, OPENAIRE_NODOI]})
        out = openaire.find(c, "repository", kind="article")
        self.assertEqual(t.calls[0][0], "POST")
        self.assertTrue(t.calls[0][2]["Authorization"].startswith("Basic "))
        self.assertEqual(t.calls[1][2]["Authorization"], "Bearer tok")
        self.assertIn("type=publication", t.calls[1][1])
        recs = out["records"]
        self.assertEqual(recs[0]["identity"], "doi:10.46298/abc")
        self.assertEqual(recs[0]["license"], "CC BY")
        self.assertEqual(recs[1]["identity"], "openaire:oa::2")
        self.assertEqual(recs[1]["identifiers"], {"handle": "1234/5678"})
        self.assertFalse(recs[1]["has_doi"])
        self.assertEqual(out["next_cursor"], "c2")
        openaire.find(c, "again")
        self.assertEqual(sum(1 for m, *_ in t.calls if m == "POST"), 1, "token reused within its lifetime")

    def test_no_credentials_refuses_instead_of_running_keyless(self):
        """The enabled policy is the registered 7,200/h tier; keyless would be 60/h (D-23)."""
        c, t = client()
        self.assertIsNone(openaire.resolve(c, "10.46298/abc"))
        out = openaire.find(c, "anything")
        self.assertIn("no OpenAIRE client credentials", out["capability_fact"])
        self.assertEqual(t.calls, [], "no keyless call ever leaves")


class SemanticScholar(unittest.TestCase):
    PAPER = {"paperId": "p1", "externalIds": {"DOI": "10.1234/abc", "ArXiv": "2301.10140"}, "title": "S2 paper", "year": 2023,
             "venue": "NeurIPS", "authors": [{"name": "A. Author"}], "openAccessPdf": {"url": "https://arxiv.org/pdf/2301.10140", "license": "CCBY"},
             "citationCount": 40, "referenceCount": 30}

    def test_find_resolve_with_key(self):
        c, t = client({("semantic_scholar", None): "KEY"})
        t.add("GET", "https://api.semanticscholar.org/graph/v1/paper/search?", body={"total": 1, "data": [self.PAPER], "next": 1})
        t.add("GET", "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234/abc", body=self.PAPER)
        t.add("GET", "https://api.semanticscholar.org/graph/v1/paper/ARXIV:2301.10140", body=self.PAPER)
        out = semanticscholar.find(c, "reranking", year_from_=2020)
        self.assertEqual(t.calls[0][2]["x-api-key"], "KEY")
        self.assertIn("year=2020-", t.calls[0][1])
        r = out["records"][0]
        self.assertEqual(r["identifiers"], {"doi": "10.1234/abc", "arxiv": "2301.10140", "s2": "p1"})
        self.assertFalse(r["redistributable"])
        self.assertEqual(semanticscholar.resolve(c, "arXiv:2301.10140v2")["title"], "S2 paper")
        self.assertIn("paper/ARXIV:2301.10140", t.calls[-1][1])

    def test_citations_and_full_text_link(self):
        c, t = client()
        t.add("GET", "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234/abc/citations",
              body={"data": [{"citingPaper": {"paperId": "c1", "externalIds": {"DOI": "10.9000/cit"}, "title": "Citer", "year": 2024}}]})
        t.add("GET", "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234/abc?", body=self.PAPER)
        cites = semanticscholar.enrich(c, "doi:10.1234/abc", "citations")
        self.assertEqual(cites["items"][0]["identity"], "doi:10.9000/cit")
        self.assertEqual(cites["items"][0]["kind"], "citation")
        ft = semanticscholar.enrich(c, "doi:10.1234/abc", "full_text")
        self.assertEqual(ft["items"][0]["kind"], "full_text")
        self.assertEqual(ft["items"][0]["links"], ["https://arxiv.org/pdf/2301.10140"])
        self.assertNotIn("text", ft["items"][0], "S2 returns links to full text, never text")


class Core(unittest.TestCase):
    WORK = {"id": 77, "doi": "10.1234/abc", "title": "Repo copy", "yearPublished": 2021, "downloadUrl": "https://core.ac.uk/download/77.pdf",
            "sourceFulltextUrls": ["https://repo.example/77.pdf"], "authors": [{"name": "A"}], "fullText": "Lorem full text body"}

    def test_resolve_excludes_text_and_enrich_returns_it(self):
        c, t = client({("core", None): "K"})
        t.add("GET", "https://api.core.ac.uk/v3/search/works?", body={"totalHits": 1, "results": [self.WORK]})
        rec = core_adapter.resolve(c, "doi:10.1234/abc")
        self.assertIn("exclude=fullText", t.calls[0][1])
        self.assertEqual(t.calls[0][2]["Authorization"], "Bearer K")
        self.assertEqual(rec["kind"], "article")
        self.assertNotIn("text", rec)
        ft = core_adapter.enrich(c, "doi:10.1234/abc", "full_text")
        self.assertNotIn("exclude=", t.calls[1][1])
        self.assertEqual(ft["items"][0]["kind"], "full_text")
        self.assertEqual(ft["items"][0]["text"], "Lorem full text body")
        self.assertFalse(ft["items"][0]["redistributable"])


class EuropePmc(unittest.TestCase):
    RESULT = {"id": "PMC1", "source": "PMC", "doi": "10.1234/bio", "pmid": "111", "pmcid": "PMC1", "title": "Bio paper",
              "authorString": "Smith J, Doe A.", "pubYear": "2020", "journalTitle": "Bio J", "isOpenAccess": "Y", "inEPMC": "Y"}

    def test_find_and_resolve(self):
        c, t = client()
        t.add("GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search?", body={"hitCount": 1, "nextCursorMark": "AoI", "resultList": {"result": [self.RESULT]}})
        out = europepmc.find(c, "crispr")
        r = out["records"][0]
        self.assertEqual(r["identity"], "doi:10.1234/bio")
        self.assertEqual(r["authors"], ["Smith J", "Doe A"])
        self.assertEqual(r["identifiers"]["pmid"], "111")
        self.assertTrue(r["open_access"])
        self.assertEqual(out["next_cursor"], "AoI")
        self.assertEqual(europepmc.resolve(c, "pmid:111")["title"], "Bio paper")
        self.assertIn("query=EXT_ID%3A111", t.calls[-1][1])


@unittest.skipUnless(db.configured() and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1",
                     "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (DB tests exercise the real store)")
class OpenAlexLocalIndex(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.identity = f"doi:10.9999/test-{uuid.uuid4().hex[:8]}"
        with self.conn.cursor() as cur:
            # the index holds venues/repositories only (D-19/D-25); an article row planted here must NOT surface
            cur.execute("INSERT INTO gateway.records (identity, kind, canonical) VALUES (%s, 'venue', %s)",
                        (self.identity, json.dumps({"identity": self.identity, "kind": "venue", "title": "Journal of Cross-Encoder Reranking", "year": 2024})))
            cur.execute("INSERT INTO gateway.index_docs (identity, kind, domain, year, tsv) VALUES (%s, 'venue', 'ai-ml', 2024, to_tsvector('english', %s))",
                        (self.identity, "Journal of Cross-Encoder Reranking retrieval"))
            self.article = self.identity + "-art"
            cur.execute("INSERT INTO gateway.records (identity, kind, canonical) VALUES (%s, 'article', %s)",
                        (self.article, json.dumps({"identity": self.article, "kind": "article", "title": "Cross-encoder reranking survey"})))
            cur.execute("INSERT INTO gateway.index_docs (identity, kind, domain, year, tsv) VALUES (%s, 'article', 'ai-ml', 2024, to_tsvector('english', %s))",
                        (self.article, "cross-encoder reranking article that must never surface"))
        self.conn.commit()

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.index_docs WHERE identity IN (%s, %s)", (self.identity, self.article))
            cur.execute("DELETE FROM gateway.records WHERE identity IN (%s, %s)", (self.identity, self.article))
        self.conn.commit()
        self.conn.close()

    def test_find_hits_local_index_without_network(self):
        t = FakeTransport()
        c = Client(broker=Broker({"openalex_snapshot": RatePolicy(per_second=100)}), transport=t, conn=self.conn)
        out = openalex_snapshot.find(c, "cross-encoder reranking", domain="ai-ml", year_from_=2020)
        self.assertEqual(t.calls, [], "no network call (D-2)")
        self.assertTrue(any(r["identity"] == self.identity for r in out["records"]))
        self.assertFalse(any(r["identity"] == self.article for r in out["records"]),
                         "a wrong-kind row left in the index can never surface under this source's identity (D-25)")
        self.assertEqual(out["records"][0]["source_id"], "openalex_snapshot")
        self.assertEqual(openalex_snapshot.find(c, "zzz-no-such-term-qq")["records"], [])

    def test_without_connection_is_a_capability_fact(self):
        c = Client(broker=Broker({"openalex_snapshot": RatePolicy(per_second=100)}), transport=FakeTransport())
        self.assertIn("capability_fact", openalex_snapshot.find(c, "x"))


if __name__ == "__main__":
    unittest.main()
