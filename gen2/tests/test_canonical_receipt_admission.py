"""Canonical receipts consume literal trusted exchanges, inside Router commits."""
import json

from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks, historical_receipt
from gen2.tests.router_fixtures import AttributedReceiptCase


class ReceiptTest(AttributedReceiptCase):
    def test_control(self):
        self.admit()
        out = self.send()
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(json.loads(self.value("SELECT receipt FROM verification_receipts")), self.document())
        self.assertEqual(self.rows("SELECT source_version, access_tier, extraction_method, extraction_invocation_id, verifier_invocation_id FROM verification_receipts"),
            [("v1", "abstract", "canonical_bytes", self.ACQUIRER, "inv_verify0001")])
        self.assertEqual(self.rows("SELECT response_bytes FROM source_acquisitions"), [(self.raw,)])
        self.assertEqual(self.rows("SELECT * FROM holds"), [])
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(self.env), {"status": "replayed", "receipt": out["receipt"]})
        self.assertEqual(self.state(exclude=()), before)

    def test_missing_admission(self):
        # Artifact, source, call reference and valid canonical bytes already exist.
        self.rejected()
        self.admit()
        self.assertEqual(self.send()["status"], "committed")

    def test_lineage(self):
        self.admit()
        for section, key, value in (("source", "source_version", "v2"), ("acquisition", "route", "gateway:core"),
                ("acquisition", "gateway_call_ref", "gw-call:102"), ("acquisition", "retrieved_at", "2026-09-28T10:00:00Z"),
                ("extraction", "produced_by_invocation_id", "inv_verify0001")):
            with self.subTest(key=key):
                doc = self.document()
                doc[section][key] = value
                self.rejected(doc)
        self.assertEqual(self.send()["status"], "committed")

    def test_conflicting_replay(self):
        self.admit()
        self.assertEqual(self.send()["status"], "committed")
        before = self.state()
        doc = self.document()
        doc["acquisition"]["route"] = "gateway:core"
        out = self.send(doc)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "operation_id_conflict"), out)
        self.assert_audited_state(before, 1)

    def test_rollback(self):
        self.admit()
        before = self.state(exclude=())
        self.faults["in_transaction:end"] = RuntimeError("fixture after canonical receipt")
        with self.assertRaisesRegex(RuntimeError, "after canonical receipt"):
            self.send()
        self.assertEqual(self.state(exclude=()), before)
        self.faults.clear()
        self.assertEqual(self.send()["status"], "committed")


class OtherAcquirerReceiptTest(AttributedReceiptCase):
    ACQUIRER = "inv_other0001"
    EVENT_ID = "rev_other0001"
    test_control = ReceiptTest.test_control
