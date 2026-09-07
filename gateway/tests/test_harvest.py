"""Phase 6: registry loaders (recorded shapes, metered client), the OpenAlex snapshot reader,
and the Tier 0 index they feed — index writes need the database, shape tests do not."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from research_gateway.adapters import openalex_snapshot as local_index
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import db
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.harvest import index, openalex_snapshot, registries

TAG = "harvest-test"


def client():
    t = FakeTransport()
    b = Broker({sid: RatePolicy(per_second=100) for sid in ("crossref", "doaj", "datacite", "openalex_snapshot")})
    return Client(broker=b, transport=t, contact_email="t@example.org"), t


CROSSREF_PAGE = {"message": {"items": [
    {"title": "Journal of Harvest Testing", "publisher": "Test Press", "ISSN": ["9999-9991"],
     "issn-type": [{"value": "9999-9991", "type": "print"}], "subjects": [{"name": "Management"}],
     "counts": {"total-dois": 1234, "current-dois": 100}},
    {"title": "No ISSN Newsletter", "publisher": "P", "ISSN": [], "issn-type": [], "counts": {"total-dois": 3}}],
    "next-cursor": "abc"}}
DOAJ_CSV = ('Journal title,Journal URL,Journal ISSN (print version),Journal EISSN (online version),Publisher,Country of publisher,'
            'Journal license,Subjects,APC,Languages in which the journal accepts manuscripts\n'
            'Journal of Harvest Testing,https://example.org/jht,9999-9991,,Test Press,Norway,CC BY,Business | Management,No,English\n'
            'Open Data Quarterly,https://example.org/odq,,9999-9983,ODQ Press,Kenya,CC BY-NC,Statistics,Yes,English\n')
DATACITE_PAGE = {"data": [{"id": "harvest.test", "type": "repositories", "attributes": {
    "name": "Harvestology Test Repository", "symbol": "HARVEST.TEST", "re3data": "r3d100000001", "url": "https://repo.example.org",
    "description": "A repository for testing", "clientType": "repository", "isActive": True, "subjects": [{"name": "Social sciences"}]}}],
    "meta": {"totalPages": 1, "total": 1}}
OPENALEX_SOURCES = [
    {"id": "https://openalex.org/S999999901", "display_name": "Journal of Harvest Testing", "issn_l": "9999-9991", "issn": ["9999-9991"],
     "host_organization_name": "Test Press", "works_count": 1500, "cited_by_count": 9000, "is_oa": True, "is_in_doaj": True,
     "homepage_url": "https://example.org/jht", "type": "journal", "country_code": "NO", "topics": [{"display_name": "Harvestology Operations"}]},
    {"id": "https://openalex.org/S999999902", "display_name": "Harvestology Data Archive", "issn_l": None, "issn": [], "type": "repository",
     "works_count": 20, "is_oa": True, "homepage_url": "https://archive.example.org", "country_code": "US"},
    {"display_name": "no id, skipped"},
]


class Shapes(unittest.TestCase):
    def test_crossref_journals(self):
        c, t = client()
        t.add("GET", "https://api.crossref.org/journals?", body=CROSSREF_PAGE)
        recs = list(registries.crossref_journals(c, limit=5))
        self.assertEqual([r["identity"] for r in recs], ["issn:9999-9991", "venue:crossref:no issn newsletter"])
        self.assertEqual(recs[0]["kind"], "venue")
        self.assertEqual(recs[0]["works_count"], 1234)
        self.assertEqual(recs[0]["subjects"], ["Management"])
        self.assertEqual(recs[0]["raw"], CROSSREF_PAGE["message"]["items"][0])
        self.assertEqual(len(t.calls), 1, "a short page ends the walk")
        self.assertIn("mailto=t%40example.org", t.calls[0][1])

    def test_doaj_csv(self):
        c, t = client()
        t.add("GET", "https://doaj.org/csv", body=DOAJ_CSV, headers={"Content-Type": "text/csv"})
        recs = list(registries.doaj_journals(c))
        self.assertEqual([r["identity"] for r in recs], ["issn:9999-9991", "issn:9999-9983"])
        self.assertEqual(recs[0]["subjects"], ["Business", "Management"])
        self.assertEqual(recs[0]["license"], "CC BY")
        self.assertEqual(recs[1]["country"], "Kenya")
        self.assertTrue(recs[0]["in_doaj"])

    def test_datacite_repositories(self):
        c, t = client()
        t.add("GET", "https://api.datacite.org/repositories?", body=DATACITE_PAGE)
        recs = list(registries.datacite_repositories(c))
        self.assertEqual(recs[0]["identity"], "repository:datacite:harvest.test")
        self.assertEqual(recs[0]["kind"], "repository")
        self.assertEqual(recs[0]["identifiers"], {"datacite_client": "harvest.test", "re3data": "r3d100000001"})
        self.assertEqual(recs[0]["subjects"], ["Social sciences"])
        self.assertEqual(len(t.calls), 1)

    def test_openalex_records_and_snapshot_reader(self):
        recs = [openalex_snapshot.record_from(s) for s in OPENALEX_SOURCES]
        self.assertEqual(recs[0]["identity"], "issn:9999-9991")
        self.assertEqual(recs[0]["identifiers"], {"openalex": "S999999901", "issn": "9999-9991"})
        self.assertEqual(recs[0]["subjects"], ["Harvestology Operations"])
        self.assertEqual(recs[1]["identity"], "repository:openalex:s999999902")
        self.assertEqual(recs[1]["kind"], "repository")
        self.assertIsNone(recs[2])
        with tempfile.TemporaryDirectory() as d:
            part = Path(d) / "updated_date=2026-09-01" / "part_000.gz"
            part.parent.mkdir()
            with gzip.open(part, "wt") as f:
                for s in OPENALEX_SOURCES:
                    f.write(json.dumps(s) + "\n")
                f.write("not json\n")
            got = list(openalex_snapshot.read_snapshot(Path(d)))
            self.assertEqual([r["identity"] for r in got], ["issn:9999-9991", "repository:openalex:s999999902"])
            self.assertEqual(len(list(openalex_snapshot.read_snapshot(Path(d), limit=1))), 1)

    def test_index_text(self):
        rec = openalex_snapshot.record_from(OPENALEX_SOURCES[0])
        text = index.text_for(rec)
        for needle in ("Journal of Harvest Testing", "Test Press", "9999-9991", "Harvestology Operations", "NO"):
            self.assertIn(needle, text)


@unittest.skipUnless(db.configured(), "RESEARCH_GATEWAY_DSN not set")
class IndexRoundTrip(unittest.TestCase):
    IDS = ("issn:9999-9991", "issn:9999-9983", "repository:datacite:harvest.test", "repository:openalex:s999999902",
           "venue:crossref:no issn newsletter")

    def setUp(self):
        self.conn = db.connect()
        self._clean()

    def tearDown(self):
        self._clean()
        self.conn.close()

    def _clean(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.records WHERE identity = ANY(%s)", (list(self.IDS),))
            cur.execute("DELETE FROM gateway.index_docs WHERE identity = ANY(%s)", (list(self.IDS),))
        self.conn.commit()

    def test_loaders_merge_into_one_record_per_venue_and_the_index_answers_first(self):
        c, t = client()
        t.add("GET", "https://api.crossref.org/journals?", body=CROSSREF_PAGE)
        t.add("GET", "https://doaj.org/csv", body=DOAJ_CSV, headers={"Content-Type": "text/csv"})
        t.add("GET", "https://api.datacite.org/repositories?", body=DATACITE_PAGE)
        self.assertEqual(registries.run(self.conn, c, "crossref"), 2)
        self.assertEqual(registries.run(self.conn, c, "doaj"), 2)
        self.assertEqual(registries.run(self.conn, c, "datacite"), 1)
        with tempfile.TemporaryDirectory() as d:
            with gzip.open(Path(d) / "part_000.gz", "wt") as f:
                for s in OPENALEX_SOURCES:
                    f.write(json.dumps(s) + "\n")
            self.assertEqual(openalex_snapshot.run(self.conn, Path(d)), 2)
        with self.conn.cursor() as cur:
            cur.execute("SELECT canonical FROM gateway.records WHERE identity = %s", ("issn:9999-9991",))
            merged = cur.fetchone()[0]
            cur.execute("SELECT source_id FROM gateway.record_sources WHERE identity = %s ORDER BY source_id", ("issn:9999-9991",))
            provenance = [r[0] for r in cur.fetchall()]
        self.conn.commit()
        self.assertEqual(provenance, ["crossref", "doaj", "openalex_snapshot"], "one record, three registries as provenance")
        self.assertEqual(merged["title"], "Journal of Harvest Testing")
        self.assertTrue(merged["in_doaj"])
        self.assertEqual(merged["works_count"], 1500, "later loaders fill in and refresh fields")
        self.assertEqual(merged["license"], "CC BY")
        # the local index adapter finds it, by name and by subject, with no network at all
        lc = Client(broker=Broker({"openalex_snapshot": RatePolicy(per_second=100)}), transport=FakeTransport(), conn=self.conn)
        out = local_index.find(lc, "harvest testing journal", kind="venue")
        self.assertEqual(out["records"][0]["identity"], "issn:9999-9991")
        self.assertEqual(out["records"][0]["source_id"], "openalex_snapshot")
        self.assertEqual(local_index.find(lc, "harvestology operations", kind="venue")["records"][0]["identity"], "issn:9999-9991")
        self.assertEqual([r["identity"] for r in local_index.find(lc, "harvestology", kind="repository")["records"]],
                         ["repository:openalex:s999999902", "repository:datacite:harvest.test"])
        self.assertEqual(lc.transport.calls, [], "index lookups never touch the network")
        self.assertEqual({(r.source_id, r.status, r.failure_class) for r in lc.log}, {("openalex_snapshot", 200, "ok")},
                         "but they are in the call log, so the log shows the index answering first (§8)")
        counts = index.counts(self.conn)
        self.assertGreaterEqual(counts["index_by_kind"].get("venue", 0), 3)
        self.assertEqual(index.reindex(self.conn, list(self.IDS)), 5)


if __name__ == "__main__":
    unittest.main()
