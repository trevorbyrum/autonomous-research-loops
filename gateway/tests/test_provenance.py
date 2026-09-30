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
    print(json.dumps({"members": {m["source_id"]: m["permissions"] for m in rec.get("provenance") or []}, "record": rec["permissions"],
                      "inputs": {m["source_id"]: {k: m[k] for k in ("redistributable", "third_party_restricted", "inferred_personal_use") if k in m}
                                 for m in rec.get("provenance") or []}}))
"""

# task 2b's own writer, run from its own commit: the last before 2b-repair (2b-repair-2 R1)
PRE_REPAIR = "e7856a9"
OLD_WRITER = """
import json, sys
from research_gateway import adapters
from research_gateway.core import db, dedup
from research_gateway.core import router as R
from research_gateway.core.cache import Cache
from research_gateway.core.canonical import make_record
from research_gateway.registry.load import read_seed
router = R.Router(read_seed(), adapters.load_all())
with db.connect() as conn:
    for identity, members in json.loads(sys.argv[1]).items():
        (rec,) = dedup.cluster([make_record(identity=identity, title="old", license="cc0", raw={"payload": identity}, **m) for m in members])
        router.annotate(rec)
        Cache(conn).put_record(rec, storable=router.storable_all(rec), persist_members=router.persistable_members(rec))
"""
# gen-1's writer at the commit the live gen-1 gateway runs — read from this repository's history, never
# from a running checkout (2b-repair-4 F2): before task 2b a member summary kept citation fields only,
# and the lead's own statements are the record's fields
LIVE = "f4a7a5c"
LIVE_WRITER = OLD_WRITER.replace("        router.annotate(rec)\n", "").replace(
    "storable=router.storable_all(rec)", "redistributable=router.redistributable_all(rec)")
GATEWAY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(HAVE_DB, "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database)")
class RestrictionsSurviveReload(unittest.TestCase):
    """2b-repair A3: a source's own restriction on a member (its terms forbid redistribution;
    third-party terms) is persisted with the member and re-derived by a FRESH PROCESS that
    reloads the record from the database and annotates it again — never widened back to what
    the licence alone would allow. 2b-repair-4 F2: rows earlier writers stored are converted
    once by registry/migrate.py, and no gateway opens a database holding one unconverted.
    Oracle: the facts stated here by hand."""

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

    def run_gateway(self, *argv) -> tuple[int, str, str]:
        import subprocess
        import sys
        done = subprocess.run([sys.executable, *argv], capture_output=True, text=True, timeout=120, cwd=GATEWAY_DIR)
        return done.returncode, done.stdout, done.stderr

    def reload(self, identity: str) -> dict:
        import json
        code, out, err = self.run_gateway("-c", RELOAD, identity)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def migrate(self, *argv) -> str:
        code, out, err = self.run_gateway("-m", "research_gateway.registry.migrate", *argv)
        self.assertEqual(code, 0, out + err)
        return out

    def stored(self, identity: str) -> dict:
        with self.conn.cursor() as cur:
            cur.execute("SELECT restriction_inputs, canonical FROM gateway.records WHERE identity = %s", (identity,))
            marker, canonical = cur.fetchone()
        self.conn.commit()
        return {"marker": marker, "members": {m["source_id"]: {k: m[k] for k in ("redistributable", "third_party_restricted", "inferred_personal_use")
                                                               if k in m} for m in canonical.get("provenance") or []},
                "canonical": canonical}

    def persist(self, name: str, source_id: str, kind: str, also: tuple = (), cache=None, **extra) -> str:
        """The current writer; `also` names sources merged in after the lead, unrestricted."""
        from research_gateway.core import dedup
        from research_gateway.core.canonical import make_record
        raw = [make_record(identity=f"doi:10.1000/{self.tag}-{name}", kind=kind, source_id=sid, title=name, license="cc0",
                           extra=extra if sid == source_id else None, raw={"payload": name}) for sid in (source_id, *also)]
        (rec,) = dedup.cluster(raw)
        self.router.annotate(rec)
        (cache or Cache(self.conn)).put_record(rec, storable=self.router.storable_all(rec), persist_members=self.router.persistable_members(rec))
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

    def legacy(self, name: str, stored: str, **lead) -> str:
        """A row stored before the canonical carried its members: record_sources holds them; `lead`,
        the lead record's own statements among its fields."""
        import json
        identity = f"doi:10.1000/{self.tag}-{name}"
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO gateway.records (identity, kind, canonical) VALUES (%s, 'article', %s)",
                        (identity, json.dumps({"identity": identity, "kind": "article", "source_id": "crossref", "title": "old", **lead})))
            cur.execute("INSERT INTO gateway.record_sources (identity, source_id, raw, license, redistributable, redistribution) "
                        "VALUES (%s, 'crossref', '{}', 'cc0', %s, %s)", (identity, stored == "permitted", stored))
        self.conn.commit()
        return identity

    def test_a_legacy_row_keeps_its_stored_prohibition(self):
        identity = self.legacy("legacy-no", "prohibited")
        self.migrate()
        self.assertEqual(self.reload(identity)["members"]["crossref"]["redistribution"], "prohibited")

    def test_a_legacy_rows_lead_statement_survives_the_migration(self):
        """Its lead's own prohibition, among the record's fields, becomes its lead member's — added
        from the record's own identity when record_sources kept none for it, never another's."""
        kept = self.legacy("legacy-lead", "permitted", redistributable=False)
        unkept = self.legacy("legacy-lead-unkept", "permitted", source_id="semanticscholar", redistributable=False)
        self.migrate()
        members = [[(m["source_id"], m.get("license"), m.get("redistributable")) for m in self.stored(i)["canonical"]["provenance"]]
                   for i in (kept, unkept)]
        self.assertEqual(members, [[("crossref", "cc0", False)], [("semanticscholar", None, False), ("crossref", "cc0", None)]])
        self.assertEqual([self.reload(i)["record"]["redistribution"] for i in (kept, unkept)], ["prohibited", "prohibited"])
        self.assertEqual(self.reload(unkept)["members"]["crossref"]["redistribution"], "permitted", "the lead's prohibition never spreads")

    def test_control_a_legacy_permitted_row_reloads_permitted(self):
        identity = self.legacy("legacy-ok", "permitted")
        self.migrate()
        stored = self.stored(identity)
        self.assertEqual((stored["marker"], "provenance" in stored["canonical"]), (True, False), "only marked: record_sources holds its members")
        self.assertEqual(self.reload(identity)["members"]["crossref"]["redistribution"], "permitted")

    def written_by(self, commit: str, writer: str, records: dict) -> list[str]:
        """Rows an earlier writer stored — commit `commit`'s real dedup and put_record, in a fresh
        process on this database — then the current schema applied over them (the upgrade).
        `records`: name -> each member's make_record arguments."""
        import io
        import json
        import subprocess
        import sys
        import tarfile
        import tempfile
        from pathlib import Path
        from research_gateway.registry.load import SCHEMA
        # the repository holding the commit: this checkout, or the one a mutation run copied gateway/ from
        root = os.environ.get("GATEWAY_SOURCE_REPOSITORY") or str(Path(__file__).resolve().parents[2])
        archive = subprocess.run(["git", "-C", root, "archive", commit, "gateway"], capture_output=True, timeout=60)
        self.assertEqual(archive.returncode, 0, f"the earlier writer is read from commit {commit}: {archive.stderr.decode()}")
        ids = {name: f"doi:10.1000/{self.tag}-old-{name}" for name in records}
        with tempfile.TemporaryDirectory() as tmp:
            tarfile.open(fileobj=io.BytesIO(archive.stdout)).extractall(tmp, filter="data")
            old = os.path.join(tmp, "gateway")
            done = subprocess.run([sys.executable, "-c", writer, json.dumps({ids[n]: m for n, m in records.items()})], cwd=old,
                                  env={**os.environ, "PYTHONPATH": old}, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA.read_text())
        self.conn.commit()
        self.assertEqual([self.stored(ids[n])["marker"] for n in records], [False] * len(records))
        return [ids[name] for name in records]

    def pre_repair(self, records: dict) -> list[str]:
        """2b-repair-2 R1: rows written by task 2b's OWN writer (commit PRE_REPAIR)."""
        identities = self.written_by(PRE_REPAIR, OLD_WRITER, records)
        stored = [m for i in identities for m in self.stored(i)["canonical"]["provenance"]]
        self.assertEqual((len(stored), [m for m in stored if {"redistributable", "third_party_restricted"} & set(m) or "permissions" not in m]),
                         (sum(map(len, records.values())), []), "task 2b's summaries: each member's facts, none of the inputs behind them")
        return identities

    def test_a_pre_repair_rows_prohibition_survives_the_migration(self):
        forbidden, merged = self.pre_repair({"forbidden": [{"source_id": "crossref", "kind": "article", "extra": {"redistributable": False}}],
                                             "merged": [{"source_id": "crossref", "kind": "article"},
                                                        {"source_id": "semanticscholar", "kind": "article", "extra": {"redistributable": False}}]})
        self.migrate()
        self.assertEqual(self.stored(forbidden)["members"], {"crossref": {"redistributable": False}})
        got = self.reload(forbidden)
        self.assertEqual((got["members"]["crossref"]["redistribution"], got["record"]["redistribution"]), ("prohibited", "prohibited"))
        got = self.reload(merged)   # the restricted member is not the lead: each member keeps its own facts, none spreads
        self.assertEqual((got["members"]["semanticscholar"]["redistribution"], got["record"]["redistribution"]), ("prohibited", "prohibited"))
        self.assertEqual((got["members"]["crossref"]["redistribution"], got["members"]["crossref"]["access"]), ("permitted", "commercial_use"))
        self.assertEqual(self.stored(merged)["members"], {"crossref": {}, "semanticscholar": {"redistributable": False, "inferred_personal_use": True}},
                         "its personal use (its source's verdict then, the row cannot say) is kept as inferred, never as third-party terms")

    def test_a_pre_repair_rows_personal_use_survives_the_migration_as_inferred(self):
        """A lead's third-party terms are among the record's fields: stated. A non-lead member's
        personal use is all the old row shows, not why: kept, inferred from legacy data, never as
        the source's third-party statement."""
        lead, merged = self.pre_repair({"thirdparty": [{"source_id": "fred", "kind": "series", "extra": {"third_party_restricted": True}}],
                                        "merged": [{"source_id": "crossref", "kind": "series"},
                                                   {"source_id": "fred", "kind": "series", "extra": {"third_party_restricted": True}}]})
        self.migrate()
        self.assertEqual(self.stored(lead)["members"], {"fred": {"third_party_restricted": True}})
        self.assertEqual(self.stored(merged)["members"], {"crossref": {}, "fred": {"inferred_personal_use": True}})
        got = self.reload(lead)
        self.assertEqual((got["members"]["fred"]["access"], got["record"]["access"]), ("personal_use", "personal_use"))
        got = self.reload(merged)
        self.assertEqual((got["members"]["fred"]["access"], got["record"]["access"], got["members"]["crossref"]["access"]),
                         ("personal_use", "personal_use", "commercial_use"))

    def test_control_a_pre_repair_unrestricted_row_reloads_permitted(self):
        free, series = self.pre_repair({"free": [{"source_id": "crossref", "kind": "article"}], "series": [{"source_id": "fred", "kind": "series"}]})
        self.migrate()
        got = self.reload(free)
        self.assertEqual((got["members"]["crossref"]["redistribution"], got["record"]["access"], got["inputs"]), ("permitted", "commercial_use", {"crossref": {}}))
        self.assertEqual((self.reload(series)["record"]["access"], self.reload(series)["inputs"]), ("commercial_use", {"fred": {}}))

    def test_the_migration_runs_once_and_says_when_it_is_done(self):
        """Bounded and idempotent, with a verifiable end: `--check` fails while a row is left; a
        rerun converts nothing and changes nothing; a current writer's row is never rewritten."""
        current = self.persist("current", "crossref", "article", also=("semanticscholar",))
        (identity,) = self.pre_repair({"once": [{"source_id": "crossref", "kind": "article"},
                                                {"source_id": "semanticscholar", "kind": "article", "extra": {"redistributable": False}}]})
        code, out, _ = self.run_gateway("-m", "research_gateway.registry.migrate", "--check")
        self.assertEqual((code, out.strip()), (1, "converted 0 stored records; 1 left to convert"))
        self.assertEqual(self.migrate().strip(), "converted 1 stored records; 0 left to convert")
        first = self.stored(identity)
        self.assertEqual(self.migrate().strip(), "converted 0 stored records; 0 left to convert")
        self.assertEqual(self.stored(identity), first)
        self.assertEqual(self.migrate("--check").strip(), "converted 0 stored records; 0 left to convert")
        self.assertEqual(self.stored(current)["members"], {"crossref": {}, "semanticscholar": {}})

    def test_no_gateway_opens_a_database_holding_an_unconverted_row(self):
        """Refuse, then migrate, then serve: the gateway never reads an earlier writer's row."""
        (identity,) = self.pre_repair({"refused": [{"source_id": "crossref", "kind": "article", "extra": {"redistributable": False}}]})
        code, _, err = self.run_gateway("-c", RELOAD, identity)
        self.assertNotEqual(code, 0)
        self.assertIn("1 stored records are in an earlier writer's representation", err)
        with self.assertRaisesRegex(RuntimeError, "convert them first"):
            app.Gateway(app.Settings(tokens={"t": "t"}, workers=1), use_db=True, transport=FakeTransport())
        self.migrate()
        gw = app.Gateway(app.Settings(tokens={"t": "t"}, workers=1), use_db=True, transport=FakeTransport())
        gw.stop()
        self.assertEqual(self.reload(identity)["record"]["redistribution"], "prohibited")

    def test_a_row_an_older_gateway_writes_later_is_never_served(self):
        reader, writer = Cache(self.conn), Cache(self.conn)   # both opened on a database with none left
        (old,) = self.pre_repair({"late": [{"source_id": "crossref", "kind": "article"}]})
        current = self.persist("current", "crossref", "article", cache=writer)
        self.assertEqual(reader.get_record(current)["identity"], current, "control: the reader's database path serves a current row")
        self.assertIsNone(reader.get_record(old))

    def test_a_pre_repair_row_written_again_is_the_current_writers(self):
        cache = Cache(self.conn)
        (identity,) = self.pre_repair({"rewritten": [{"source_id": "crossref", "kind": "article"}, {"source_id": "semanticscholar", "kind": "article"}]})
        self.assertEqual(self.persist("old-rewritten", "crossref", "article", also=("semanticscholar",), cache=cache), identity)
        self.assertTrue(self.stored(identity)["marker"])
        got = self.reload(identity)
        self.assertEqual((got["members"]["semanticscholar"]["access"], got["inputs"]), ("personal_use", {"crossref": {}, "semanticscholar": {}}))

    def test_control_a_row_written_with_its_inputs_is_derived_from_them_alone(self):
        """The current writer's rows are never rebuilt: a member of a deny-verdict source is personal use
        by its source's verdict, and its summary claims no restriction its source never stated."""
        got = self.reload(self.persist("denied", "crossref", "article", also=("semanticscholar",)))
        self.assertEqual((got["members"]["semanticscholar"]["access"], got["inputs"]), ("personal_use", {"crossref": {}, "semanticscholar": {}}))

    def test_the_live_gateways_rows_keep_their_leads_statements(self):
        """Rows gen-1's writer stored (the commit the live gateway runs; read from history): the lead's
        prohibition and third-party terms are the record's own fields. Today's reader, before this
        migration, served both widened (permitted, commercial use) — 2b-repair-4's own probe."""
        forbidden, thirdparty, free = self.written_by(LIVE, LIVE_WRITER, {
            "forbidden": [{"source_id": "crossref", "kind": "article", "extra": {"redistributable": False}}],
            "thirdparty": [{"source_id": "fred", "kind": "series", "extra": {"third_party_restricted": True}}],
            "free": [{"source_id": "crossref", "kind": "article"}, {"source_id": "semanticscholar", "kind": "article"}]})
        self.assertEqual([self.stored(i)["members"] for i in (forbidden, thirdparty)], [{"crossref": {}}, {"fred": {}}],
                         "gen-1's summaries keep citation fields only")
        self.migrate()
        self.assertEqual([self.stored(i)["members"] for i in (forbidden, thirdparty, free)],
                         [{"crossref": {"redistributable": False}}, {"fred": {"third_party_restricted": True}}, {"crossref": {}, "semanticscholar": {}}])
        self.assertEqual(self.reload(forbidden)["record"]["redistribution"], "prohibited")
        self.assertEqual(self.reload(thirdparty)["record"]["access"], "personal_use")
        got = self.reload(free)
        self.assertEqual((got["members"]["crossref"]["redistribution"], got["members"]["crossref"]["access"]), ("permitted", "commercial_use"))

    def test_the_harvests_rows_are_current_and_read_from_record_sources(self):
        from research_gateway.core.canonical import make_record
        from research_gateway.harvest import index
        identity, old = f"doi:10.1000/{self.tag}-harvested", f"doi:10.1000/{self.tag}-harvested-old"
        with self.conn.cursor() as cur:
            index.upsert(cur, make_record(identity=identity, kind="venue", source_id="doaj", title="t", license="CC BY", raw={}), "doaj")
            cur.execute("INSERT INTO gateway.records (identity, kind, canonical) VALUES (%s, 'venue', '{}')", (old,))
            index.upsert(cur, make_record(identity=old, kind="venue", source_id="doaj", title="t", license="CC BY", raw={}), "doaj")
            cur.execute("DELETE FROM gateway.index_docs WHERE identity IN (%s, %s)", (identity, old))
        self.conn.commit()
        self.assertEqual((self.stored(identity)["marker"], self.stored(old)["marker"]), (True, False),
                         "a row an earlier writer left is still the migration's")
        self.migrate()
        got = Cache(self.conn).get_record(identity)
        self.assertEqual([(m["source_id"], m["license"]) for m in got["provenance"]], [("doaj", "CC BY")])
