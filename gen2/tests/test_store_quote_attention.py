"""Raw integrity guards for quote attention; in-memory fixtures only."""
import re
import sqlite3

from gen2.tests.store_fixtures import TOPIC
from gen2.tests import test_store_governed_quotes as raw

ADJ = {"adjudication_ref": "adj-quote", "resolved_at": "2026-09-27T10:00:00Z", "resolution": "entailment confirmed on re-read"}
HOLD = "hold_quote_qck_quote00001"
BYTE_QUARANTINE = "byte-mismatch quarantine cannot be adjudicated (V-6)"


class AdjudicationDDLTest(raw.DDLTest):
    def bound(self, status="matched", verdict="supports", check_id="qck_governed001", **changes):
        exact = {"status": status, "normalization_version": "quote-nfc-safe/2+ucd15.0.0", "source_artifact_hash": self.source_hash}
        self.verify("ver_bound00001", method="canonical_bytes", extraction="inv_pppppppp", gateway="gw-call:1",
            quote=(status, check_id), verdict=verdict, receipt_overrides={"checks": {**self.CHECKS_OK, "exact_quote": exact}, **changes})

    def refused(self, action, fragment):
        before = {n: self.rows("SELECT * FROM " + n) for n in self.tables()}
        self.x("SAVEPOINT refusal")
        with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
            action()
        # Builder prerequisites may be written before the refused statement.
        # Check every refusal target before cleanup can conceal a write.
        targets = ("verification_receipts", "operator_decisions", "holds")
        self.assertEqual({n: self.rows("SELECT * FROM " + n) for n in targets},
            {n: before[n] for n in targets})
        self.x("ROLLBACK TO refusal")
        self.x("RELEASE refusal")
        self.assertEqual({n: self.rows("SELECT * FROM " + n) for n in self.tables()}, before)

    def test_byte_adjudication(self):
        self.raw("mismatch")
        self.x("SAVEPOINT control")
        self.bound(status="mismatch", verdict="does_not_support")
        self.x("ROLLBACK TO control")
        self.x("RELEASE control")
        self.refused(lambda: self.bound(status="mismatch", verdict="does_not_support", adjudication=ADJ), BYTE_QUARANTINE)

    def test_declared_mismatch_adjudication(self):
        self.quote_check("qc-alarm", nli="alarm")
        self.x("DROP TRIGGER verification_receipts_bindings")  # isolate DDL 13's declared-byte guard
        self.x("SAVEPOINT control")
        self.verify("ver_mismatch01", gateway="gw-call:1", verdict="does_not_support", quote=("matched", "qc-alarm"), adjudication=ADJ)
        self.x("ROLLBACK TO control")
        self.x("RELEASE control")
        self.refused(lambda: self.verify("ver_mismatch01", gateway="gw-call:1", verdict="does_not_support", quote=("mismatch", "qc-alarm"), adjudication=ADJ), BYTE_QUARANTINE)

    def test_capture_adjudication(self):
        self.raw("mismatch")
        self.raw(check_id="qck_matching001")
        self.x("SAVEPOINT control")
        self.bound(check_id="qck_matching001", verdict="does_not_support")
        self.x("ROLLBACK TO control")
        self.x("RELEASE control")
        self.refused(lambda: self.bound(check_id="qck_matching001", verdict="does_not_support", adjudication=ADJ), BYTE_QUARANTINE)

    def test_nli_control(self):
        self.quote_check("qc-alarm", nli="alarm")
        self.verify("ver_alarm00001", gateway="gw-call:1", quote=("matched", "qc-alarm"), adjudication=ADJ)
        self.assertEqual(self.rows("SELECT verdict FROM verification_receipts WHERE verification_receipt_id = 'ver_alarm00001'"), [("supports",)])

    def test_non_nli_quarantine(self):
        self.quote_check("qc-held", quarantined=1)
        self.x("SAVEPOINT control")
        self.verify("ver_held000001", gateway="gw-call:1", verdict="does_not_support", quote=("matched", "qc-held"))
        self.x("ROLLBACK TO control")
        self.x("RELEASE control")
        self.refused(lambda: self.verify("ver_held000001", gateway="gw-call:1", verdict="does_not_support", quote=("matched", "qc-held"), adjudication=ADJ), BYTE_QUARANTINE)

    def quote_hold(self, check="qck_governed001"):
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, "
            "deadline_at, clears_when, created_at) VALUES (?, ?, ?, 'judgment', 'quote quarantine', 'needs_remediation', 'primary', "
            "'primary:station-1', '2026-09-27T11:00:00Z', 'matching re-capture', '2026-09-27T10:00:00Z')", HOLD, TOPIC, "quote:" + check)

    def test_byte_clearance_decision(self):
        self.x("SAVEPOINT control")
        self.raw()
        self.quote_hold()
        self.decision("opd_clear00001", "hold_clearance", ref=HOLD)
        self.x("ROLLBACK TO control")
        self.x("RELEASE control")
        self.raw("mismatch")
        self.quote_hold()
        self.refused(lambda: self.decision("opd_clear00001", "hold_clearance", ref=HOLD), BYTE_QUARANTINE)

    def test_direct_clearance(self):
        self.x("SAVEPOINT control")
        self.raw()
        self.quote_hold()
        self.x("UPDATE holds SET cleared_at = '2026-09-27T10:00:00Z', cleared_by_operation_id = 'op_verify0001' WHERE hold_id = ?", HOLD)
        self.x("ROLLBACK TO control")
        self.x("RELEASE control")
        self.raw("mismatch")
        self.quote_hold()
        self.refused(lambda: self.x("UPDATE holds SET cleared_at = '2026-09-27T10:00:00Z', cleared_by_operation_id = 'op_verify0001' WHERE hold_id = ?", HOLD), BYTE_QUARANTINE)

    def test_non_nli_clearance(self):
        self.x("SAVEPOINT control")
        self.quote_check("qc-held", nli="alarm", quarantined=1)
        self.quote_hold("qc-held")
        self.decision("opd_clear00001", "hold_clearance", ref=HOLD)
        self.x("UPDATE holds SET cleared_at = '2026-09-27T10:00:00Z', cleared_by_operation_id = 'op_verify0001' WHERE hold_id = ?", HOLD)
        self.x("ROLLBACK TO control")
        self.x("RELEASE control")
        self.quote_check("qc-held", quarantined=1)
        self.quote_hold("qc-held")
        self.refused(lambda: self.decision("opd_clear00001", "hold_clearance", ref=HOLD), BYTE_QUARANTINE)
        self.refused(lambda: self.x("UPDATE holds SET cleared_at = '2026-09-27T10:00:00Z', cleared_by_operation_id = 'op_verify0001' WHERE hold_id = ?", HOLD), BYTE_QUARANTINE)

    def test_nli_clearance_control(self):
        self.quote_check("qc-alarm", nli="alarm")
        self.quote_hold("qc-alarm")
        self.decision("opd_clear00001", "hold_clearance", ref=HOLD)
        self.x("UPDATE holds SET cleared_at = '2026-09-27T10:00:00Z', cleared_by_decision_id = 'opd_clear00001' WHERE hold_id = ?", HOLD)
        self.assertEqual(self.rows("SELECT cleared_by_decision_id FROM holds WHERE hold_id = ?", HOLD), [("opd_clear00001",)])
