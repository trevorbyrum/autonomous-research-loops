"""Pending declarations are retained but never qualify load-bearing support."""
import unittest
from contextlib import contextmanager

from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_canonical_content_tiers import IDENTITY, FULL, attributed_fixture, document
from gen2.tests.test_canonical_receipt_admission import AttributedReceiptCase, ReceiptCase
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks

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
        load_claim(case, tier)
        doc = ReceiptCase.document(case)
        doc['claim']['claim_id'] = 'clm_loadbear1'
        # Ordinary extraction outputs equal these canonical bytes. The
        # distinct-output regression separately checks artifact selection.
        seed_checks(case, doc)
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
