"""Task 2b, acceptance item 5: licence, freshness and provenance, end to end.

DB-backed source loading keeps every registry field (the loader used to select a subset,
so a DB-backed gateway answered without licence, freshness, evidence or homepage — design
review §9). Every returned record, and each provenance member of a merged record, carries
its content licence, its source's metadata licence, its retrieval time and its source's
freshness lag, and four DISTINCT permission facts — availability, access, storage and
redistribution — which are never collapsed into one flag. The seed file is the
independent oracle for the loader; the permission table below is hand-written from
docs/LICENSING.md, not derived from the code. DB cases need RESEARCH_GATEWAY_DSN and
RESEARCH_GATEWAY_TEST_OK=1.
"""
from __future__ import annotations

import itertools
import os
import unittest

from research_gateway import adapters, app
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import db, licenses
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.cache import Cache
from research_gateway.registry.load import read_seed
from tests.test_adapters_articles import CROSSREF_WORK

HAVE_DB = db.configured() and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1"
SEED = read_seed()
BY_ID = {s["id"]: s for s in SEED}
FACTS = ("availability", "access", "storage", "redistribution")

# (label, source, member {license, redistributable?, third_party_restricted?}, kind, has_content) ->
#   (availability, access, storage, redistribution) — from docs/LICENSING.md's rules
TABLE = [
    ("allow source, no content licence", "crossref", {"license": None}, "article", False,
     ("metadata", "commercial_use", "persist", "unknown")),
    ("allow source, CC-BY content", "crossref", {"license": "https://creativecommons.org/licenses/by/4.0/"}, "article", False,
     ("metadata", "commercial_use", "persist", "permitted")),
    ("per-item source, CC-BY-NC content", "europepmc", {"license": "cc-by-nc"}, "article", False,
     ("metadata", "personal_use", "transient", "conditional")),
    ("per-item source, CC0, adapter forbids redistribution", "europepmc", {"license": "cc0", "redistributable": False}, "article", False,
     ("metadata", "commercial_use", "persist", "prohibited")),
    ("deny source, CC-BY content", "semanticscholar", {"license": "CC-BY"}, "article", False,
     ("metadata", "personal_use", "transient", "permitted")),
    ("allow source, full text, CC0", "core", {"license": "cc0"}, "full_text", True,
     ("content", "personal_use", "transient", "permitted")),
    ("allow source, series with third-party restrictions", "fred", {"license": None, "third_party_restricted": True}, "series", False,
     ("metadata", "personal_use", "persist", "unknown")),
    ("allow source, delivered rows, unidentifiable licence", "socrata", {"license": "see portal terms"}, "file", True,
     ("content", "personal_use", "transient", "unknown")),
    # 2b-repair A3: a file or full-text record that carries only links delivered a description, not content
    ("allow source, file listed by its link only", "socrata", {"license": "see portal terms"}, "file", False,
     ("metadata", "personal_use", "transient", "unknown")),
    ("allow source, full text located by its link only, CC0", "core", {"license": "cc0"}, "full_text", False,
     ("metadata", "personal_use", "transient", "permitted")),
]


class PermissionFacts(unittest.TestCase):
    def test_each_fact_follows_its_own_rule(self):
        for label, sid, member, kind, has_content, expected in TABLE:
            with self.subTest(label):
                got = licenses.permissions(BY_ID[sid], member, kind=kind, has_content=has_content)
                self.assertEqual(tuple(got[f] for f in FACTS), expected)

    def test_no_fact_is_a_function_of_another(self):
        """Over the facts the code COMPUTES for the table's inputs, for every ordered pair of
        facts two rows agree on the first and differ on the second: none of the four is
        derived from another (storage and redistribution were one flag, D-23)."""
        rows = [licenses.permissions(BY_ID[sid], member, kind=kind, has_content=has_content)
                for _, sid, member, kind, has_content, _ in TABLE]
        for x, y in itertools.permutations(FACTS, 2):
            with self.subTest(given=x, varies=y):
                self.assertTrue(any(a[x] == b[x] and a[y] != b[y] for a, b in itertools.combinations(rows, 2)),
                                f"{y} is determined by {x} in this table")

    def test_unknown_is_never_permitted(self):
        for text in (None, "", "see terms", "MIT plus restrictions", "https://example.org/licence"):
            with self.subTest(text):
                self.assertEqual(licenses.content_redistribution(text), "unknown")
        self.assertEqual(licenses.content_redistribution("cc0"), "permitted", "control: an identified allow-listed licence")

    def test_a_merged_record_takes_the_most_restrictive_of_its_members(self):
        a = {"availability": "metadata", "access": "commercial_use", "storage": "persist", "redistribution": "permitted"}
        b = {"availability": "metadata", "access": "personal_use", "storage": "transient", "redistribution": "unknown"}
        self.assertEqual(licenses.combined([a, b]), b)
        self.assertEqual(licenses.combined([a, a]), a)


def make(seed=None):
    t = FakeTransport()
    b = Broker({s["id"]: RatePolicy(per_second=100) for s in SEED})
    return R.Router(seed or SEED, adapters.load_all()), Client(broker=b, transport=t), t


class ReturnedRecords(unittest.TestCase):
    def test_a_merged_find_record_carries_each_members_provenance_and_facts(self):
        seed = [dict(s, enabled=False) if s["id"] == "openalex_snapshot" else s for s in SEED]
        r, c, t = make(seed)
        work = dict(CROSSREF_WORK, license=[{"URL": "https://creativecommons.org/licenses/by/4.0/"}])
        t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [work], "total-results": 1}})
        doaj_hit = {"id": "abc", "bibjson": {"title": CROSSREF_WORK["title"][0], "year": "2021",
                                             "identifier": [{"type": "doi", "id": "10.1234/abc"}], "author": [{"name": "Ada Lovelace"}],
                                             "journal": {"title": "J", "license": [{"type": "CC BY-NC"}]}}}
        t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [doaj_hit], "total": 1})
        out = R.execute(r, {"request_type": "find", "kind": "article", "query": "q", "domain": "finance"}, c)
        (rec,) = out["records"]
        members = {m["source_id"]: m for m in rec["provenance"]}
        self.assertEqual(set(members), {"crossref", "doaj"})
        for sid, m in members.items():
            with self.subTest(sid):
                self.assertEqual(m["metadata_license"], BY_ID[sid]["license"], "the source's metadata licence, from the registry")
                self.assertEqual(m["freshness_lag"], BY_ID[sid]["freshness_lag"])
                self.assertTrue(m["retrieved_at"])
                self.assertEqual(set(m["permissions"]), set(FACTS))
        self.assertEqual(members["crossref"]["permissions"]["redistribution"], "permitted")
        self.assertEqual(members["doaj"]["permissions"]["redistribution"], "conditional")
        self.assertEqual(rec["permissions"]["redistribution"], "conditional", "the record is capped by its most restricted member")
        stored = R.redact_for_storage(out, r.sources)["records"][0]["provenance"]
        kept = {m["source_id"]: m for m in stored}
        self.assertEqual(kept["doaj"].get("permissions"), members["doaj"]["permissions"], "a stored job result keeps the four facts")
        self.assertEqual((kept["crossref"]["metadata_license"], kept["crossref"]["freshness_lag"]),
                         (BY_ID["crossref"]["license"], BY_ID["crossref"]["freshness_lag"]))

    def test_a_resolved_record_and_its_cached_copy_carry_the_facts(self):
        r, c, t = make()
        t.add("GET", "https://doi.org/ra/", body=[{"DOI": "10.1234/abc", "RA": "Crossref"}])
        t.add("GET", "https://api.crossref.org/works/10.1234/abc", body={"message": CROSSREF_WORK})
        cache = Cache(None)
        first = R.execute(r, {"request_type": "resolve", "identity": "doi:10.1234/abc"}, c, cache)
        again = R.execute(r, {"request_type": "resolve", "identity": "doi:10.1234/abc"}, c, cache)
        self.assertTrue(again["cache_hit"])
        for out in (first, again):
            rec = out["records"][0]
            self.assertEqual((rec["metadata_license"], rec["freshness_lag"]), (BY_ID["crossref"]["license"], BY_ID["crossref"]["freshness_lag"]))
            self.assertEqual(rec["permissions"]["storage"], "persist")

    def test_a_link_only_listing_is_metadata_not_content(self):
        """A3: a real Globe file listing — a file record with its link, no bytes fetched — is a
        description of the file; the download control below is the content."""
        seed = [dict(s, enabled=True, rate={**s["rate"], "verified": True}) if s["id"] == "globe" else s for s in SEED]
        r, c, t = make(seed)
        out = R.execute(r, {"request_type": "fetch", "target": "https://globeproject.com/data/x.xls"}, c)
        (rec,) = out["records"]
        self.assertEqual((rec["kind"], rec["links"], out.get("content")), ("file", ["https://globeproject.com/data/x.xls"], None))
        self.assertEqual(rec["permissions"]["availability"], "metadata")
        self.assertEqual(t.calls, [], "nothing was downloaded")

    def test_a_download_carries_its_own_facts(self):
        seed = [dict(s, enabled=True, rate={**s["rate"], "verified": True}) if s["id"] == "globe" else s for s in SEED]
        r, c, t = make(seed)
        t.add("GET", "https://globeproject.com/data/x.xls", body=b"\xd0\xcf\x11", headers={"Content-Type": "application/vnd.ms-excel"})
        out = R.execute(r, {"request_type": "fetch", "target": "https://globeproject.com/data/x.xls", "params": {"download": True}}, c)
        self.assertEqual(out["content"], b"\xd0\xcf\x11")
        self.assertEqual(out["content_permissions"]["availability"], "content")
        self.assertEqual(out["content_permissions"]["storage"], "transient", "a download is delivered, never kept")


@unittest.skipUnless(HAVE_DB, "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database)")
class DatabaseBackedSources(unittest.TestCase):
    def test_the_loader_returns_every_registry_field_of_every_source(self):
        with db.connect() as conn:
            rows = {r["id"]: r for r in app.sources_from_db(conn)}
        self.assertEqual(set(rows), set(BY_ID))
        for sid, seed_row in BY_ID.items():
            with self.subTest(sid):
                self.assertEqual({k: rows[sid].get(k) for k in seed_row}, seed_row)

    def test_a_db_backed_gateway_answers_with_licence_and_freshness(self):
        gw = app.Gateway(app.Settings(tokens={"t": "t"}, workers=1), use_db=True, transport=FakeTransport())
        try:
            for sid in ("crossref", "semanticscholar", "fred"):
                with self.subTest(sid):
                    described = gw.source_descriptions(sid)
                    for key in ("license", "freshness_lag", "homepage", "use_commercial"):
                        self.assertEqual(described[key], BY_ID[sid][key])
                    self.assertIsNotNone(described["license"])
        finally:
            gw.stop()

    def test_control_the_database_is_what_is_read(self):
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE gateway.sources SET notes = 'probe-note' WHERE id = 'doaj'")
            conn.commit()
            try:
                self.assertEqual({r["id"]: r for r in app.sources_from_db(conn)}["doaj"]["notes"], "probe-note")
            finally:
                with conn.cursor() as cur:
                    cur.execute("UPDATE gateway.sources SET notes = %s WHERE id = 'doaj'", (BY_ID["doaj"].get("notes"),))
                conn.commit()


if __name__ == "__main__":
    unittest.main()


RELOAD = """
import copy, json, sys
from research_gateway import adapters
from research_gateway.core import db
from research_gateway.core import router as R
from research_gateway.core.cache import Cache
from research_gateway.registry.load import read_seed
router = R.Router(read_seed(), adapters.load_all())
with db.connect() as conn:
    rec = Cache(conn).get_record(sys.argv[1])
    rec = router.annotate(copy.deepcopy(rec))
    print(json.dumps({"members": {m["source_id"]: m["permissions"] for m in rec.get("provenance") or []}, "record": rec["permissions"]}))
"""


@unittest.skipUnless(HAVE_DB, "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database)")
class RestrictionsSurviveReload(unittest.TestCase):
    """2b-repair A3: a source's own restriction on a member (its terms forbid redistribution;
    third-party terms) is persisted with the member and re-derived by a FRESH PROCESS that
    reloads the record from the database and annotates it again — never widened back to what
    the licence alone would allow. Oracle: the facts stated here by hand."""

    def setUp(self):
        import uuid
        self.conn = db.connect()
        self.tag = uuid.uuid4().hex[:8]
        self.router = R.Router(SEED, adapters.load_all())

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.records WHERE identity LIKE %s", (f"%10.1000/{self.tag}%",))
        self.conn.commit()
        self.conn.close()

    def reload(self, identity: str) -> dict:
        import json
        import subprocess
        import sys
        done = subprocess.run([sys.executable, "-c", RELOAD, identity], capture_output=True, text=True, timeout=120,
                              cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def persist(self, name: str, source_id: str, kind: str, **extra) -> str:
        from research_gateway.core import dedup
        from research_gateway.core.canonical import make_record
        raw = make_record(identity=f"doi:10.1000/{self.tag}-{name}", kind=kind, source_id=source_id, title=name, license="cc0",
                          extra=extra, raw={"payload": name})
        (rec,) = dedup.cluster([raw])
        self.router.annotate(rec)
        Cache(self.conn).put_record(rec, storable=self.router.storable_all(rec), persist_members=self.router.persistable_members(rec))
        return rec["identity"]

    def test_a_prohibition_survives_a_fresh_process_reload(self):
        identity = self.persist("forbidden", "crossref", "article", redistributable=False)
        with self.conn.cursor() as cur:
            cur.execute("SELECT license, redistributable, redistribution FROM gateway.record_sources WHERE identity = %s", (identity,))
            self.assertEqual(cur.fetchall(), [("cc0", False, "prohibited")])
        self.conn.commit()
        got = self.reload(identity)
        self.assertEqual((got["members"]["crossref"]["redistribution"], got["record"]["redistribution"]), ("prohibited", "prohibited"))

    def test_third_party_terms_survive_a_fresh_process_reload(self):
        identity = self.persist("thirdparty", "fred", "series", third_party_restricted=True)
        got = self.reload(identity)
        self.assertEqual((got["members"]["fred"]["access"], got["record"]["access"]), ("personal_use", "personal_use"))

    def test_control_an_unrestricted_cc0_record_reloads_permitted(self):
        got = self.reload(self.persist("free", "crossref", "article"))
        self.assertEqual((got["members"]["crossref"]["redistribution"], got["record"]["redistribution"]), ("permitted", "permitted"))
        got = self.reload(self.persist("freeseries", "fred", "series"))
        self.assertEqual(got["record"]["access"], "commercial_use")

    def legacy(self, name: str, stored: str) -> str:
        """A row stored before the canonical carried its members: the reload rebuilds them from record_sources."""
        identity = f"doi:10.1000/{self.tag}-{name}"
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO gateway.records (identity, kind, canonical) VALUES (%s, 'article', %s)",
                        (identity, '{"identity": "%s", "kind": "article", "source_id": "crossref", "title": "old"}' % identity))
            cur.execute("INSERT INTO gateway.record_sources (identity, source_id, raw, license, redistributable, redistribution) "
                        "VALUES (%s, 'crossref', '{}', 'cc0', %s, %s)", (identity, stored == "permitted", stored))
        self.conn.commit()
        return identity

    def test_a_legacy_row_keeps_its_stored_prohibition(self):
        self.assertEqual(self.reload(self.legacy("legacy-no", "prohibited"))["members"]["crossref"]["redistribution"], "prohibited")

    def test_control_a_legacy_permitted_row_reloads_permitted(self):
        self.assertEqual(self.reload(self.legacy("legacy-ok", "permitted"))["members"]["crossref"]["redistribution"], "permitted")
