"""2d-4 part 1: literal Router hold effects; SQL tests cover hold constraints.

These fixtures establish routing and attribution, not semantic verification or
access truth. Re-access, tier admission and detailed checks remain later parts.
"""
import json
import sqlite3
from unittest.mock import patch

from gen2.tests.router_fixtures import TOPIC
from gen2.tests.store_fixtures import StoreTestCase, T
from gen2.tests.test_governed_quotes import QuotesCase

HOLD = "hold_6937eef24b17d742001c84e3a97f10290ae7ee206ea1a34b5f606ff2c4792dda"


class AttentionCase(QuotesCase):
    verifier_station = "verifier-station"
    verifier_deadline = "2026-09-27T10:30:00Z"

    def started(self, inv, kind="research_pass", tid=TOPIC, **extra):
        extra["deadline_at"] = "2026-09-27T11:00:00Z"
        if kind == "verification":
            extra.update(station_id=self.verifier_station, deadline_at=self.verifier_deadline)
        return super().started(inv, kind, tid, **extra)

    def document(self, verdict="does_not_support"):
        doc = self.receipt_document(verdict=verdict)
        doc["quote_check_id"] = None
        doc["checks"]["exact_quote"]["status"] = "not_applicable"
        return doc

    def commit(self, doc=None):
        out = self.send([], verification_receipts=[doc or self.document()])
        self.assertEqual(out["status"], "committed", out)
        return out

    def attention(self, verdict="does_not_support", missing=False):
        doc = self.document(verdict)
        if missing:
            doc["access_tier"] = "abstract"
            doc["checks"].update(numeric_units="not_checked", denominators="unavailable", negation="not_checked", qualifications="unavailable")
        out = self.commit(doc)
        self.assertEqual(self.rows("SELECT hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, "
            "owner, deadline_at, clears_when, created_at, created_by_operation_id, cleared_at FROM holds"), [(
            HOLD, TOPIC, "verification:ver_quote00001", "judgment",
            ("verification missing content: " if missing else "verification disagreement: ") + verdict,
            "needs_remediation" if missing else "needs_decision", "primary", "primary:station-1", "2026-09-27T11:00:00Z",
            "independent verification with the required content" if missing else "primary adjudication of this verification disagreement",
            out["receipt"]["committed_at"], self.env["operation_id"], None)])
        self.assertEqual(out["receipt"]["effects"]["holds_created"], [HOLD])
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", out["receipt"]["effects"]["audit_event_id"]))
        self.assertEqual(audit["verification_holds"], [HOLD])
        self.assertEqual(json.loads(self.value("SELECT receipt FROM verification_receipts")), doc)
        self.assertEqual(self.rows("SELECT status FROM claims"), [("provisional",)])
        self.assertEqual(self.rows("SELECT status FROM queue_entries WHERE topic_id = ?", TOPIC), [("active",)])
        holds = self.router.status({"topic_id": TOPIC})["topics"][0]["holds"]
        self.assertEqual([(h["hold_id"], h["subject_ref"], h["owner"], h["deadline_at"]) for h in holds],
            [(HOLD, "verification:ver_quote00001", "primary:station-1", "2026-09-27T11:00:00Z")])
        return out


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


class HoldDDLTest(StoreTestCase):
    def record(self, **changes):
        row = {"hold_id": HOLD, "topic_id": TOPIC, "subject_ref": "verification:ver_quote00001", "hold_class": "judgment",
            "cause": "verification disagreement: does_not_support", "recoverability": "needs_decision", "required_authority": "primary",
            "owner": "primary:station-1", "deadline_at": "2026-09-27T11:00:00Z", "clears_when": "primary adjudication",
            "created_at": T, **changes}
        self.x("INSERT INTO holds (" + ", ".join(row) + ") VALUES (" + ", ".join("?" for _ in row) + ")", *row.values())

    def test_open_control(self):
        self.record()
        self.assertEqual(self.rows("SELECT hold_class, owner, deadline_at, cleared_at FROM holds"),
            [("judgment", "primary:station-1", "2026-09-27T11:00:00Z", None)])

    def test_shape(self):
        for change in ({"owner": ""}, {"deadline_at": None}, {"hold_class": "agreement"}):
            with self.subTest(change=change), self.assertRaises(sqlite3.IntegrityError):
                self.record(**change)
            self.assertEqual(self.rows("SELECT * FROM holds"), [])
        self.record()

    def test_created_open(self):
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_clear0001")
        self.receipt("op_clear00001", "inv_clear0001", kind="interim_transition")
        # The clearance CHECK and foreign key are satisfied; only open creation refuses.
        with self.assertRaisesRegex(sqlite3.IntegrityError, "created open"):
            self.record(cleared_at=T, cleared_by_operation_id="op_clear00001")
        self.assertEqual(self.rows("SELECT * FROM holds"), [])

    def test_identity_and_clearance(self):
        self.record()
        for sql in ("UPDATE holds SET subject_ref = 'different'", "UPDATE holds SET hold_class = 'transient'",
                    "UPDATE holds SET cleared_at = '2026-09-27T10:00:00Z'", "DELETE FROM holds"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.x(sql)
        self.decision("opd_clear00001", "hold_clearance", ref=HOLD)
        self.x("UPDATE holds SET cleared_at = ?, cleared_by_decision_id = 'opd_clear00001' WHERE hold_id = ?", T, HOLD)
        self.assertEqual(self.rows("SELECT cleared_by_decision_id FROM holds"), [("opd_clear00001",)])
