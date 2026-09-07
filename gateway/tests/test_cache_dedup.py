"""Phase 4: licence allow-list, staged dedup, cache TTLs and the redistribution rule (§6, I-8)."""
import os
import unittest
import uuid

from research_gateway.core import cache as C, db, dedup, licenses
from research_gateway.core.canonical import make_record


class Licenses(unittest.TestCase):
    def test_allow_list(self):
        for ok in ("CC0 1.0", "cc-by-4.0", "Creative Commons Attribution 4.0", "Public Domain", "ODC-BY", "MIT", "Apache-2.0",
                   "U.S. federal public domain (17 U.S.C. 105)", "ISC License", "Zlib License", "Unlicense"):
            self.assertTrue(licenses.allow_listed(ok), ok)
        for bad in (None, "", "CC-BY-NC-4.0", "cc by nc sa", "CC-BY-ND-4.0", "CC-BY-SA-4.0", "Creative Commons Attribution-ShareAlike 4.0",
                    "GPL-3.0", "Proprietary", "restricted", "custom"):
            self.assertFalse(licenses.allow_listed(bad), bad)
        allow, per_item, deny = {"use_commercial": "allow"}, {"use_commercial": "per-item"}, {"use_commercial": "deny"}
        rec = {"license": "cc-by-4.0"}
        self.assertTrue(licenses.commercially_usable(deny, rec, {"commercial": False}), "personal baseline")
        self.assertFalse(licenses.commercially_usable(deny, rec, {"commercial": True}))
        self.assertFalse(licenses.commercially_usable(per_item, rec, {"commercial": True}))
        self.assertTrue(licenses.commercially_usable(per_item, rec, {"commercial": True, "accept_per_item": True}))
        self.assertFalse(licenses.commercially_usable(per_item, {"license": "CC-BY-NC"}, {"commercial": True, "accept_per_item": True}))
        self.assertTrue(licenses.commercially_usable(allow, {}, {"commercial": True}))

    def test_redistributable(self):
        allow, per_item, deny = {"use_commercial": "allow"}, {"use_commercial": "per-item"}, {"use_commercial": "deny"}
        rec = {"kind": "dataset", "license": "cc-by-4.0"}
        self.assertTrue(licenses.redistributable(allow, rec))
        self.assertTrue(licenses.redistributable(per_item, rec))
        self.assertFalse(licenses.redistributable(per_item, {"kind": "dataset", "license": None}))
        self.assertFalse(licenses.redistributable(deny, rec))
        self.assertFalse(licenses.redistributable(allow, {"kind": "full_text", "license": "cc0"}), "full text is never kept (I-7)")


def rec(identity, source, title, year=2021, authors=("Ada Lovelace",), kind="article", license=None, **extra):
    return make_record(identity=identity, kind=kind, source_id=source, title=title, year=year, authors=list(authors),
                       identifiers={"doi": identity[4:]} if identity.startswith("doi:") else {}, links=[f"https://{source}/{identity}"],
                       license=license, extra=extra, raw={"from": source})


class Dedup(unittest.TestCase):
    def test_exact_identity_merges_across_case_and_prefix(self):
        out = dedup.cluster([rec("doi:10.1000/ABC", "crossref", "A study"), rec("https://doi.org/10.1000/abc", "doaj", "A study", license="CC BY 4.0")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["identity"], "doi:10.1000/abc")
        self.assertEqual(out[0]["sources"], ["crossref", "doaj"])
        self.assertEqual(out[0]["license"], "CC BY 4.0", "missing fields are filled from later members")
        self.assertEqual([p["source_id"] for p in out[0]["provenance"]], ["crossref", "doaj"])
        self.assertEqual(len(out[0]["links"]), 2)
        self.assertNotIn("raw", out[0])

    def test_fuzzy_title_year_author(self):
        a = rec("doi:10.1000/x", "crossref", "Reranking with large language models: a survey")
        b = rec("title:reranking", "openaire", "Reranking with Large Language Models — A Survey", authors=("Lovelace, Ada",))
        c = rec("title:other", "openaire", "Reranking with large language models: a survey", year=2019)
        d = rec("title:other2", "openaire", "Reranking with large language models: a survey", authors=("Grace Hopper",))
        e = rec("title:noyear", "openaire", "Reranking with large language models: a survey", year=None)
        f = rec("title:noauthor", "openaire", "Reranking with large language models: a survey", authors=())
        out = dedup.cluster([a, b, c, d, e, f])
        self.assertEqual(len(out), 5, "same title+year+author merges; a different or missing year/author never does")
        self.assertEqual(out[0]["sources"], ["crossref", "openaire"])

    def test_sources_only_records_expand_to_all_members(self):
        """D-26: a record carrying only a `sources` list contributes one member per source in a
        re-merge, aligned with the router's member view — the denied source is never lost."""
        a = rec("doi:10.1000/so", "crossref", "Sources only")
        b = {**rec("doi:10.1000/so", "semanticscholar", "Sources only"), "sources": ["semanticscholar", "europepmc"]}
        out = dedup.cluster([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual([m["source_id"] for m in out[0]["provenance"]], ["crossref", "semanticscholar", "europepmc"])
        self.assertIsNone(out[0]["provenance"][2]["raw"], "only the record's own source carries its raw")
        self.assertEqual(out[0]["sources"], ["crossref", "semanticscholar", "europepmc"])

    def test_different_kinds_never_merge(self):
        out = dedup.cluster([rec("title:t", "crossref", "Panel data"), rec("title:t2", "datacite", "Panel data", kind="dataset")])
        self.assertEqual(len(out), 2)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class MemoryCache(unittest.TestCase):
    def test_ttls_and_policy(self):
        clock = FakeClock()
        c = C.Cache(None, clock=clock, memory_ttl=3600, metadata_ttl=7 * 86400)
        c.put_record(rec("doi:10.1000/keep", "crossref", "K"), redistributable=True)
        c.put_record(rec("doi:10.1000/mem", "semanticscholar", "M"), redistributable=False)
        self.assertIsNotNone(c.get_record("10.1000/KEEP"))
        self.assertIsNotNone(c.get_record("doi:10.1000/mem"))
        clock.t += 3601
        self.assertIsNone(c.get_record("doi:10.1000/mem"), "non-redistributable records live at most an hour")
        self.assertIsNotNone(c.get_record("doi:10.1000/keep"))
        clock.t += 7 * 86400
        self.assertIsNone(c.get_record("doi:10.1000/keep"))
        key = c.search_key("find", {"query": "q", "domain": "finance"})
        self.assertEqual(key, c.search_key("find", {"domain": "finance", "query": "q"}))
        c.put_search(key, {"records": []})
        self.assertEqual(c.get_search(key), {"records": []})
        clock.t += 3601
        self.assertIsNone(c.get_search(key))
        self.assertEqual(c.persisted, 0)

    def test_memory_is_bounded(self):
        c = C.Cache(None, max_records=3, max_searches=2)
        for i in range(10):
            c.put_record(rec(f"doi:10.1000/{i}", "crossref", str(i)), redistributable=True)
            c.put_search(f"k{i}", {"i": i})
        self.assertLess(c.stats()["records_in_memory"], 4)
        self.assertLess(c.stats()["searches_in_memory"], 3)
        self.assertIsNotNone(c.get_record("doi:10.1000/9"), "the newest survives")
        self.assertIsNone(c.get_record("doi:10.1000/0"), "the oldest was evicted")
        self.assertGreater(c.stats()["evicted"], 0)


@unittest.skipUnless(db.configured() and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1",
                     "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (DB tests exercise the real queue)")
class PersistentCache(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.tag = uuid.uuid4().hex[:8]

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.records WHERE identity LIKE %s", (f"doi:10.1000/{self.tag}%",))
        self.conn.commit()
        self.conn.close()

    def test_only_redistributable_records_reach_the_database(self):
        c = C.Cache(self.conn)
        keep = rec(f"doi:10.1000/{self.tag}-keep", "crossref", "Kept")
        keep["provenance"] = [{"source_id": "crossref", "identity": keep["identity"], "raw": {"a": 1}},
                              {"source_id": "doaj", "identity": keep["identity"], "raw": {"b": 2}},
                              {"source_id": "semanticscholar", "identity": keep["identity"], "raw": {"never": "persisted"}}]
        c.put_record(keep, redistributable=True, persist_members=[0, 1])
        c.put_record(rec(f"doi:10.1000/{self.tag}-mem", "semanticscholar", "Memory only"), redistributable=False)
        with self.conn.cursor() as cur:
            cur.execute("SELECT identity, kind FROM gateway.records WHERE identity LIKE %s ORDER BY identity", (f"doi:10.1000/{self.tag}%",))
            self.assertEqual(cur.fetchall(), [(f"doi:10.1000/{self.tag}-keep", "article")])
            cur.execute("SELECT source_id, redistributable, raw FROM gateway.record_sources WHERE identity = %s ORDER BY source_id", (keep["identity"],))
            self.assertEqual(cur.fetchall(), [("crossref", True, {"a": 1}), ("doaj", True, {"b": 2})],
                             "the non-redistributable member's raw payload never reaches record_sources (§6)")
        fresh = C.Cache(self.conn)
        served = fresh.get_record(keep["identity"])
        self.assertEqual(served["title"], "Kept", "served from the database after a restart")
        self.assertEqual(served["sources"], ["crossref", "doaj"])
        self.assertIsNone(fresh.get_record(f"doi:10.1000/{self.tag}-mem"))

    def test_sources_only_persistence_indexes_align_with_the_router(self):
        """D-26: the cache's synthesized member list mirrors the router's, so an index authorized
        for the crossref member never persists the Semantic Scholar lead's raw payload."""
        c = C.Cache(self.conn)
        s2_lead = {**rec(f"doi:10.1000/{self.tag}-lead", "semanticscholar", "S2 lead"),
                   "sources": ["crossref", "semanticscholar"]}
        # the router authorizes index 0 (crossref, allow); index 0 in the synthesized list is
        # crossref with raw=None — nothing persists, instead of the S2 raw slipping through
        c.put_record(s2_lead, redistributable=False, persist_members=[0])
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM gateway.record_sources WHERE identity = %s", (s2_lead["identity"].lower(),))
            self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
