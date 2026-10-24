"""Pending declarations are retained but never qualify load-bearing support."""
import sqlite3
import unittest
from contextlib import contextmanager

from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_canonical_content_tiers import IDENTITY, FULL, attributed_fixture, document
from gen2.tests.test_canonical_receipt_admission import AttributedReceiptCase, ReceiptCase
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks
from gen2.tests.ddl_fixtures import restore_triggers
from gen2.tests.detailed_support_fixtures import prior_consumption
from gen2.tests import store_fixtures as sf
from gen2.store import db
from gen2.tests.test_store_content_tiers import ContentDDLTest

METHODS = ("verifier_extraction", "validated_extraction")


def load_claim(case, tier):
    ref = case.artifact(b"Independent load-bearing claim")
    out = case.router.commit_outcome(case.envelope(case.producer, "op_loadclaim1",
        {**empty_outcome("inv_capture001", "interim_transition"), "claims": [{"claim_id": "clm_loadbear1", "revision": 1,
            "text_ref": ref, "load_bearing": True, "required_access_tier": tier}]}, refs=[ref]))
    case.assertEqual(out["status"], "committed", out)


def support_document(case, method, tier):
    doc = document(case, tier)
    doc["claim"]["claim_id"] = "clm_loadbear1"
    doc["requested_for"]["use"] = "load_bearing"
    doc["extraction"].update(method=method)
    if method == "verifier_extraction":
        doc["extraction"]["produced_by_invocation_id"] = "inv_verify0001"
    if method == "validated_extraction":
        doc["extraction"]["validation_ref"] = "validation_unrecorded"
    from gen2.tests.extraction_receipt_fixtures import attach
    attach(case, doc)
    if isinstance(case, AttributedReceiptCase):
        attach_checks(case, doc)
    return doc


@contextmanager
def bound_fixture(record, tier='full_text'):
    with attributed_fixture(record) as case:
        restore_triggers(case, db.schema_text())
        try:
            load_claim(case, tier)
            doc = ReceiptCase.document(case)
            doc['claim']['claim_id'] = 'clm_loadbear1'
            # Ordinary extraction outputs equal these canonical bytes. The
            # distinct-output regression separately checks artifact selection.
            seed_checks(case, doc)
        finally:
            restore_triggers(case, sf.DDL_TEXT)
        yield case


class PendingRouterTest(unittest.TestCase):
    def promote(self, case, expected):
        before = case.state()
        out = case.router.commit_outcome(case.envelope(case.producer, "op_promote001",
            {**empty_outcome("inv_capture001", "interim_transition"), "claim_promotions": [{"claim_id": "clm_loadbear1", "revision": 1}]}))
        self.assertEqual(out["status"], expected, out)
        if expected == "rejected":
            self.assertIn("unbound extraction", out["detail"])
            case.assert_audited_state(before, 1)

    def test_pending_methods(self):
        for method in METHODS:
            for tier in ("abstract", "full_text"):
                with self.subTest(method=method, tier=tier), bound_fixture({**FULL, "abstract": "Recorded abstract"}, tier) as case:
                    doc = support_document(case, method, tier)
                    out = case.send(doc)
                    self.assertEqual(out["status"], "committed", out)
                    self.assertEqual(case.rows("SELECT access_tier, extraction_method, verdict FROM verification_receipts"), [(tier, method, "supports")])
                    self.assertEqual(case.rows("SELECT * FROM holds"), [])
                    held = case.rows("SELECT hold_id FROM holds")
                    self.assertEqual(out["receipt"]["effects"]["holds_created"], [h[0] for h in held])
                    before = case.state(exclude=())
                    self.assertEqual(case.router.commit_outcome(case.env)["status"], "replayed")
                    self.assertEqual(case.state(exclude=()), before)
                    self.promote(case, "committed")

    def test_canonical_support_control(self):
        with bound_fixture(FULL) as case:
            self.assertEqual(case.send(support_document(case, "validated_extraction", "full_text"))["status"], "committed")
            held = case.rows("SELECT * FROM holds")
            doc = support_document(case, "canonical_bytes", "full_text")
            doc["verification_receipt_id"] = "ver_canonical1"
            self.assertEqual(case.send(doc, op="op_canonical1")["status"], "committed")
            self.promote(case, "committed")
            self.assertEqual(case.rows("SELECT * FROM holds"), held)

    def test_hold_rollback(self):
        with bound_fixture(FULL) as case:
            before = case.state(exclude=())
            case.faults["in_transaction:end"] = RuntimeError("after pending extraction hold")
            with self.assertRaisesRegex(RuntimeError, "after pending extraction hold"):
                case.send(support_document(case, "verifier_extraction", "full_text"))
            self.assertEqual(case.state(exclude=()), before)

    def test_blank_cannot_promote(self):
        with bound_fixture({**FULL, "text": "\f\u00a0\u2029"}) as case:
            self.assertEqual(case.send(support_document(case, "canonical_bytes", "full_text"))["status"], "rejected")
            out = case.router.commit_outcome(case.envelope(case.producer, "op_promote001",
                {**empty_outcome("inv_capture001", "interim_transition"), "claim_promotions": [{"claim_id": "clm_loadbear1", "revision": 1}]}))
            self.assertEqual(out["status"], "rejected", out)
            self.assertEqual(case.rows("SELECT status FROM claims WHERE claim_id = 'clm_loadbear1'"), [("provisional",)])


class PendingDDLTest(ContentDDLTest):
    def prepare_pending(self, tier="full_text", *, other=False):
        # Admit exact claim/revision operands before the subject savepoints.
        requested = sf.DDL_TEXT
        full = db.schema_text()
        self.restore_views(full)
        restore_triggers(self, full)
        try:
            self.x("INSERT INTO claims SELECT claim_id, 2, topic_id, text_ref, producer_invocation_id, 1, ?, 'provisional', created_at FROM claims WHERE revision = 1", tier)
            claims = ["clm_00000001"]
            if other:
                self.x("INSERT INTO claims SELECT 'clm_other001', revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at FROM claims WHERE revision = 2")
                claims.append("clm_other001")
            for claim in claims:
                seed_checks(self.assessments, dict(topic_id=sf.TOPIC,
                    claim=dict(claim_id=claim, claim_revision=2),
                    source=dict(work_id="wrk_00000001", source_version="v4"),
                    cited_spans=[dict(start=0, end=5, locator=dict(kind="page", value="3"))],
                    obtained_content_hash=self.assessments.source["content_hash"],
                    extraction=dict(method="canonical_bytes"),
                    verifier_invocation_id="inv_vvvvvvvv", checks=self.CHECKS_OK))
        finally:
            self.restore_views(requested)
            restore_triggers(self, requested)

    def pending(self, method="validated_extraction", tier="full_text"):
        from unittest.mock import patch
        from gen2.tests.test_bound_extraction_support import historical
        with historical(self), patch("gen2.tests.extraction_receipt_fixtures.attach", side_effect=lambda c, d: d):
            self.content_receipt(tier, method=method, claim=("clm_00000001", 2), use="load_bearing",
                extraction="inv_vvvvvvvv" if method == "verifier_extraction" else "inv_pppppppp", validation="validation_unrecorded",
                historical=True)  # Existing pre-consumer unbound declaration, never support authority.

    def promote(self):
        self.x("UPDATE claims SET status = 'accepted_support' WHERE claim_id = 'clm_00000001' AND revision = 2")

    def test_pending_methods(self):
        for method in METHODS:
            for tier in ("abstract", "full_text"):
                with self.subTest(method=method, tier=tier):
                    # Router transactions cannot nest inside the raw savepoint.
                    self.tearDown()
                    self.setUp()
                    self.prepare_pending(tier)
                    self.acquired({"identity": "rec-1", "kind": "full_text", "text": "Recorded text", "abstract": "Recorded abstract"})
                    self.x("SAVEPOINT pending")
                    try:
                        self.pending(method, tier)
                        self.assertEqual(self.rows("SELECT access_tier, extraction_method FROM verification_receipts WHERE verification_receipt_id = 'ver_content1'"), [(tier, method)])
                        before = self.rows("SELECT * FROM claims")
                        with prior_consumption(self), self.assertRaisesRegex(sqlite3.IntegrityError, "unbound extraction"):
                            self.promote()
                        self.assertEqual(self.rows("SELECT * FROM claims"), before)
                    finally:
                        self.x("ROLLBACK TO pending")
                        self.x("RELEASE pending")

    def test_canonical_support_control(self):
        self.prepare_pending()
        self.acquired({"identity": "rec-1", "kind": "full_text", "text": "Recorded full text"})
        self.pending()
        self.content_receipt("full_text", rid="ver_canonical1", claim=("clm_00000001", 2), use="load_bearing")
        self.promote()
        self.assertEqual(self.rows("SELECT status FROM claims WHERE revision = 2"), [("accepted_support",)])

    def test_canonical_distractors(self):
        self.prepare_pending(other=True)
        self.acquired({"identity": "rec-1", "kind": "full_text", "text": "Recorded full text"})
        self.pending()
        for change in ({"claim": ("clm_00000001", 1)}, {"claim": ("clm_other001", 2)}, {"use": "sampled"}, {"verdict": "does_not_support"}):
            with self.subTest(change=change):
                self.x("SAVEPOINT distractor")
                try:
                    args = {"claim": ("clm_00000001", 2), "use": "load_bearing", **change}
                    self.content_receipt("full_text", rid="ver_distractor1", **args)
                    with prior_consumption(self), self.assertRaisesRegex(sqlite3.IntegrityError, "unbound extraction"):
                        self.promote()
                finally:
                    self.x("ROLLBACK TO distractor")
                    self.x("RELEASE distractor")
