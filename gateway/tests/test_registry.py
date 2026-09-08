"""Phase 1 acceptance: the seed validates, mirrors the plan, and the docs match it."""
import os
import unittest
from pathlib import Path

from research_gateway.registry import docs, load
from research_gateway.registry.load import read_seed

ROOT = Path(__file__).resolve().parents[1]


class SeedValidation(unittest.TestCase):
    def setUp(self):
        self.sources = load.read_seed()

    def test_seed_is_valid(self):
        self.assertEqual(load.validate(self.sources), [])

    def test_ids_unique_and_slug_shaped(self):
        ids = [s["id"] for s in self.sources]
        self.assertEqual(len(ids), len(set(ids)))
        for sid in ids:
            self.assertRegex(sid, r"^[a-z][a-z0-9_]*$")

    def test_every_source_has_evidence_for_verdict_and_rate(self):
        for s in self.sources:
            self.assertTrue(s.get("use_evidence"), s["id"])
            self.assertTrue(s["rate"].get("evidence"), s["id"])

    def test_enabled_sources_have_verified_rates(self):
        for s in self.sources:
            if s.get("enabled"):
                self.assertTrue(s["rate"].get("verified"), f"{s['id']} enabled without verified rate")

    def test_openalex_is_snapshot_only(self):
        """D-2: no live OpenAlex source may exist."""
        for s in self.sources:
            if "openalex" in s["id"]:
                self.assertEqual(s["id"], "openalex_snapshot")
                self.assertEqual(s["capabilities"], ["find"])
                self.assertIn("never calls the OpenAlex API", s["key_instructions"])

    def test_base_lanes_match_plan(self):
        """PLAN §4: Crossref + OpenAlex snapshot + DOAJ base for articles; DataCite base for datasets."""
        base = {s["id"]: s.get("base_for", []) for s in self.sources}
        self.assertIn("article", base["crossref"])
        self.assertIn("article", base["doaj"])
        self.assertIn("article", base["openalex_snapshot"])
        self.assertIn("dataset", base["datacite"])
        self.assertEqual(base["openaire"], [], "OpenAIRE is not a discovery lane (PLAN R-2)")
        self.assertEqual(base["unpaywall"], ["oa-location"])

    def test_commercial_verdicts_match_decisions(self):
        """D-5 verdicts recorded 2026-09-07."""
        v = {s["id"]: s["use_commercial"] for s in self.sources}
        for sid in ("crossref", "datacite", "doaj", "openaire", "openalex_snapshot", "opencitations", "unpaywall",
                    "fred", "bea", "census", "bls", "bis", "ecb", "govinfo", "wms", "pew"):
            self.assertEqual(v[sid], "allow", sid)
        for sid in ("semanticscholar", "core", "kaggle", "qdr"):
            self.assertEqual(v[sid], "deny", sid)
        # harvard_dataverse: depositors choose the dataset licence, so platform-wide allow was wrong (D-23)
        for sid in ("europepmc", "socrata", "huggingface", "openml", "harvard_dataverse"):
            self.assertEqual(v[sid], "per-item", sid)
        self.assertEqual(v["globe"], "unknown")

    def test_manual_sources_are_never_schedulable(self):
        for s in self.sources:
            if s["kind"] == "manual":
                self.assertEqual(s["capabilities"], [])
                self.assertFalse(s.get("enabled"))


class AdapterConsistency(unittest.TestCase):
    def test_no_orphan_adapters(self):
        """I-2: an adapter without a registry row must not exist."""
        orphans, _missing = load.check_adapters(load.read_seed())
        self.assertEqual(orphans, [])


class DocsMirrorRegistry(unittest.TestCase):
    def test_committed_docs_match_seed(self):
        """I-9."""
        text = docs.render(load.read_seed())
        committed = (ROOT / "docs" / "SOURCES.md").read_text()
        self.assertEqual(committed, text, "docs/SOURCES.md is stale: run python -m research_gateway.registry.docs")

    def test_docs_state_unknowns_explicitly(self):
        text = docs.render(load.read_seed())
        self.assertIn("**unknown** — no reuse terms could be located", text)
        self.assertIn("GLOBE", text)


class CliDryRun(unittest.TestCase):
    def test_dry_run_exit_zero(self):
        self.assertEqual(load.main(["--dry-run"]), 0)

    def test_docs_check_exit_zero(self):
        self.assertEqual(docs.main(["--check"]), 0)


class Validation(unittest.TestCase):
    def test_rejects_malformed_rate_values(self):
        import copy
        good = copy.deepcopy(load.read_seed()[0])
        self.assertEqual(load.validate([good]), [])
        for field, value in (("per_second", -1), ("per_day", 0), ("per_hour", "fast"), ("per_minute", True),
                             ("burst", 2.5), ("verified", "yes")):
            bad = copy.deepcopy(good)
            bad["rate"][field] = value
            problems = load.validate([bad])
            self.assertTrue(any(field in p for p in problems), f"{field}={value!r} accepted: {problems}")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(os.environ.get("RESEARCH_GATEWAY_DSN") and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1",
                     "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1")
class ReloadPreservesDeployment(unittest.TestCase):
    """8f: a catalogue reload and a deployment decision are different acts — the deployed
    `enabled` switch and rate caps survive an ordinary reload; --seed-operational
    reasserts the seed. Exercised on THROWAWAY fixture rows only: this test never loads
    the real seed and never touches a deployed source's row (pass-1 finding 2)."""

    FIXTURE = {"id": "test-reload-probe", "name": "Reload probe", "kind": "article", "auth": "none",
               "capabilities": ["find"], "identifiers": [], "base_for": [], "domains": [],
               "use_commercial": "deny", "enabled": True, "notes": "test fixture — safe to delete",
               "rate": {"per_second": 1, "per_day": 100, "verified": True, "evidence": "test"}}

    def setUp(self):
        import psycopg
        self.dsn = os.environ["RESEARCH_GATEWAY_DSN"]
        self.psycopg = psycopg

    def tearDown(self):
        with self.psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.rate_policies WHERE source_id = %s", (self.FIXTURE["id"],))
            cur.execute("DELETE FROM gateway.sources WHERE id = %s", (self.FIXTURE["id"],))
            conn.commit()

    def _row(self):
        with self.psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT s.enabled, r.per_day, r.verified FROM gateway.sources s "
                        "JOIN gateway.rate_policies r ON r.source_id = s.id WHERE s.id = %s",
                        (self.FIXTURE["id"],))
            return cur.fetchone()

    def test_deployment_switches_survive_a_reload_unless_reasserted(self):
        from research_gateway.registry.load import load as load_seed
        fixture = [dict(self.FIXTURE, rate=dict(self.FIXTURE["rate"]))]
        load_seed(fixture, self.dsn, apply_schema=False)         # insert takes the seed values
        self.assertEqual(self._row(), (True, 100, True))
        with self.psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("UPDATE gateway.sources SET enabled = false WHERE id = %s", (self.FIXTURE["id"],))
            cur.execute("UPDATE gateway.rate_policies SET per_day = 7, verified = false WHERE source_id = %s",
                        (self.FIXTURE["id"],))
            conn.commit()
        load_seed(fixture, self.dsn, apply_schema=False)         # ordinary reload: deployment preserved
        self.assertEqual(self._row(), (False, 7, False),
                         "an ordinary reload preserves the deployed switch AND rate overrides")
        load_seed(fixture, self.dsn, apply_schema=False, seed_operational=True)
        self.assertEqual(self._row(), (True, 100, True), "--seed-operational reasserts the seed")
