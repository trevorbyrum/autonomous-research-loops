"""Reuse canonical predicate pairs against each pending extraction consumer.

Inherited cases cover shapes, Unicode, kind, record selection, coverage, each
obtainable tier and reproduction. Raw operands establish SQL relationships,
not transport authentication; every negative has its own fixture/savepoint.
"""
import json
import sqlite3

from gen2.tests import test_store_content_tiers as content
from gen2.tests.store_fixtures import T, h


class ExtractionContentDDLTest(content.ContentDDLTest):
    METHOD = "verifier_extraction"

    def content_receipt(self, tier, **changes):
        super().content_receipt(tier, method=self.METHOD,
            extraction="inv_vvvvvvvv" if self.METHOD == "verifier_extraction" else "inv_pppppppp",
            validation="validation_unrecorded" if self.METHOD == "validated_extraction" else None, **changes)

    def test_lineage(self):
        # The extractor is independent of the acquiring invocation; omit the
        # canonical-only acquirer selector while keeping each SQL 18 operand.
        for name in ("work", "version", "verifier", "call", "time", "route"):
            with self.subTest(selector=name):
                self.x("SAVEPOINT lineage")
                try:
                    self.acquired({"identity": "rec-1"})
                    changes = self.distractor(name)
                    self.acquired({**content.FULL, "identity": "rec-2"}, event_id="e2", provider_record_id="rec-2", **changes)
                    self.refusal("full_text")
                    self.content_receipt("bibliographic")
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
                finally:
                    self.x("ROLLBACK TO lineage")
                    self.x("RELEASE lineage")

    def test_links(self):
        for tier in ("abstract", "full_text"):
            with self.subTest(tier=tier):
                self.x("SAVEPOINT links")
                try:
                    self.acquired({"identity": "rec-1", "kind": "full_text", "links": ["https://fixture.invalid/paper"],
                        "has_full_text": True, "raw": {"text": "Metadata"}})
                    self.refusal(tier)
                    self.content_receipt("bibliographic")
                finally:
                    self.x("ROLLBACK TO links")
                    self.x("RELEASE links")

    def test_verdicts(self):
        for verdict in ("supports", "partially_supports", "does_not_support", "cannot_assess_at_required_tier"):
            with self.subTest(verdict=verdict):
                self.x("SAVEPOINT verdict")
                try:
                    self.acquired({"identity": "rec-1", "abstract": "Fixture abstract"})
                    self.refusal("full_text", verdict=verdict)
                    self.content_receipt("abstract")
                finally:
                    self.x("ROLLBACK TO verdict")
                    self.x("RELEASE verdict")

    def test_record_identity(self):
        # Both works consume exactly the same response/hash, selecting their
        # own provider records. Neither acquisition can lend the other's text.
        self.other_work()
        self.source(work="wrk_other001", version="v4")
        record, others = {"identity": "rec-1"}, [{**content.FULL, "identity": "rec-2"}]
        self.acquired(record, others)
        self.acquired(record, others, work_id="wrk_other001", event_id="e2", provider_record_id="rec-2")
        self.refusal("full_text")
        self.content_receipt("bibliographic")

    def test_missing_diagnostic(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "extraction receipt must consume its admitted acquisition"):
            self.content_receipt("full_text")
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])
        self.acquired(content.FULL)
        self.content_receipt("full_text")

    def test_hash_diagnostic(self):
        self.acquired(content.FULL)
        acq = {"route": "gateway:crossref", "retrieved_at": T, "gateway_call_ref": "gw-call:1", "cache_reuse": False}
        with self.assertRaisesRegex(sqlite3.IntegrityError, "extraction receipt must consume its admitted acquisition"):
            self.verify("ver_wronghash1", tier="reproduced", required="reproduced", use="sampled", method=self.METHOD,
                extraction="inv_vvvvvvvv" if self.METHOD == "verifier_extraction" else "inv_pppppppp", validation="validation_unrecorded",
                obtained=h("7"), gateway="gw-call:1", quote=("not_applicable", None),
                receipt_overrides={"source": {"work_id": "wrk_00000001", "source_version": "v4"}, "acquisition": acq},
                column_overrides={"source_version": "v4", "acquisition": json.dumps(acq)})
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])
        self.content_receipt("full_text")

    def test_readback_conflict_rollback(self):
        self.acquired(content.FULL)
        before = self.rows("SELECT * FROM verification_receipts")
        self.x("SAVEPOINT retention")
        self.content_receipt("full_text")
        row = self.rows("SELECT receipt, access_tier, extraction_method FROM verification_receipts")[0]
        self.assertEqual((json.loads(row[0])["access_tier"], *row[1:]), ("full_text", "full_text", self.METHOD))
        retained = self.rows("SELECT * FROM verification_receipts")
        # Raw DDL has uniqueness, while operation replay is exercised through Router.
        for tier in ("full_text", "bibliographic"):
            with self.subTest(tier=tier), self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE constraint"):
                self.content_receipt(tier)
            self.assertEqual(self.rows("SELECT * FROM verification_receipts"), retained)
        self.x("ROLLBACK TO retention")
        self.x("RELEASE retention")
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), before)
        self.content_receipt("full_text")


class ValidatedContentDDLTest(ExtractionContentDDLTest):
    METHOD = "validated_extraction"
