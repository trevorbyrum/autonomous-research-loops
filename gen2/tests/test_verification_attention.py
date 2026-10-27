"""2d-4 part 1: literal Router hold effects; SQL tests cover hold constraints.

These fixtures establish routing and attribution, not semantic verification or
access truth. Re-access, tier admission and detailed checks remain later parts.
"""
import json
import sqlite3
from unittest.mock import patch

from gen2.tests.router_fixtures import TOPIC
from gen2.tests.router_fixtures import HOLD, AttentionCase


class AttentionTest(AttentionCase):
    def test_disagreement(self):
        self.attention()

    def test_partial_disagreement(self):
        self.attention("partially_supports")

    def test_missing_content(self):
        self.attention("cannot_assess_at_required_tier", missing=True)

    def test_support_control(self):
        out = self.commit(self.document("supports"))
        self.assertEqual(self.rows("SELECT * FROM holds"), [])
        self.assertEqual(out["receipt"]["effects"]["holds_created"], [])
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", out["receipt"]["effects"]["audit_event_id"]))
        self.assertEqual(audit["verification_holds"], [])

    def test_replay(self):
        out = self.attention()
        before = self.state(exclude=())
        replay = self.router.commit_outcome(self.env)
        self.assertEqual((replay["status"], replay["receipt"]), ("replayed", out["receipt"]))
        self.assertEqual(self.state(exclude=()), before)

    def test_competing_receipt_preserves_hold(self):
        self.attention()
        held = self.rows("SELECT * FROM holds")
        doc = {**self.document("supports"), "verification_receipt_id": "ver_support001"}
        out = self.commit(doc)
        self.assertEqual(out["receipt"]["effects"]["holds_created"], [])
        self.assertEqual(self.rows("SELECT * FROM holds"), held)
        self.assertEqual(self.rows("SELECT verdict FROM verification_receipts ORDER BY rowid"), [("does_not_support",), ("supports",)])

    def test_long_receipt_id(self):
        doc = {**self.document(), "verification_receipt_id": "ver_" + "a" * 64}
        out = self.commit(doc)
        expected = "hold_91267b2af7f763e30934417ab03dc266de6963d576d396697f950febf2f1511a"
        self.assertEqual(out["receipt"]["effects"]["holds_created"], [expected])
        self.assertEqual(self.rows("SELECT hold_id, subject_ref FROM holds"), [(expected, "verification:ver_" + "a" * 64)])

    def test_quote_and_disagreement(self):
        doc = self.receipt_document("mismatch", "does_not_support")
        out = self.send([self.record(quoted_text="effect NOT observed")], verification_receipts=[doc])
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(out["receipt"]["effects"]["holds_created"], ["hold_quote_qck_quote00001", HOLD])
        self.assertEqual(self.rows("SELECT subject_ref FROM holds ORDER BY rowid"),
            [("quote:qck_quote00001",), ("verification:ver_quote00001",)])

    def test_final_boundary_rollback(self):
        before = self.state(exclude=())
        self.faults["in_transaction:end"] = RuntimeError("fixture after verification attention")
        with self.assertRaisesRegex(RuntimeError, "after verification attention"):
            self.send([], verification_receipts=[self.document()])
        self.assertEqual(self.state(exclude=()), before)

    def rolled_back(self, before):
        after = self.state(exclude=())
        audit, old_audit = after.pop("audit_events"), before.pop("audit_events")
        self.assert_generation_delta(before, after, 1)
        self.assertEqual(after, before)
        self.assertEqual(audit[:-1], old_audit)
        self.assertEqual(len(audit), len(old_audit) + 1)
        self.assertEqual(self.value("SELECT kind FROM audit_events ORDER BY rowid DESC LIMIT 1"), "commit_rejected")

    def test_conflicting_hold_rolls_back(self):
        self.hold(self.capture_grant, HOLD)
        before = self.state(exclude=())
        out = self.send([], verification_receipts=[self.document()])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.rolled_back(before)

    def test_failed_hold_write_rolls_back(self):
        before = self.state(exclude=())
        insert = self.store.insert
        def fail(table, row):
            if table == "holds":
                raise sqlite3.IntegrityError("fixture failed hold persistence")
            insert(table, row)
        with patch.object(self.store, "insert", side_effect=fail):
            out = self.send([], verification_receipts=[self.document()])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.rolled_back(before)

    def test_failed_receipt_leaves_no_hold(self):
        before = self.state(exclude=())
        doc = self.document()
        doc["source"]["work_id"] = "wrk_absent0001"
        out = self.send([], verification_receipts=[doc])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.rolled_back(before)


class SharedOwnerTest(AttentionCase):
    verifier_station = "station-1"
    verifier_deadline = "2026-09-27T11:00:00Z"

    def test_control(self):
        self.attention()
