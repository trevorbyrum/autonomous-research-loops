"""V-6 owner attention and adjudication through Router; raw DDL is independent.

NLI checks are literal historical fixtures, never executed by a provider.
"""
import json

from gen2.tests.router_fixtures import TOPIC
from gen2.tests.detailed_receipt_fixtures import unreferenced_checks
from gen2.tests.router_fixtures import CaptureCase

ADJ = {"adjudication_ref": "adj-quote", "resolved_at": "2026-09-27T10:00:00Z", "resolution": "entailment confirmed on re-read"}
HOLD = "hold_quote_qck_quote00001"


class AttentionCase(CaptureCase):
    verifier_station = "verifier-station"
    verifier_deadline = "2026-09-27T10:30:00Z"

    def started(self, inv, kind="research_pass", tid=TOPIC, **extra):
        extra["deadline_at"] = "2026-09-27T11:00:00Z"
        if kind == "verification":
            extra.update(station_id=self.verifier_station, deadline_at=self.verifier_deadline)
        return super().started(inv, kind, tid, **extra)

    def near(self):
        source = self.artifact(b"a" * 99 + b"c")
        self.assertEqual(self.send([], grant=self.capture_grant, refs=[source], source_artifacts=[{
            "work_id": self.work, "source_version": "v2", "artifact_ref": source}])["status"], "committed")
        return self.record(artifact_ref=source, source_version="v2", quoted_text="a" * 99 + "b", span_start=0, span_end=100)

    def alarm(self, signal="alarm"):
        self.x("INSERT INTO quote_checks (check_id, claim_id, claim_revision, source_artifact_hash, span_start, span_end, "
            "normalization_version, exact_match, nli_checker, nli_checker_version, nli_signal, quote_quarantined, checked_at) "
            "VALUES ('qck_quote00001', 'clm_quote00001', 1, ?, 1, 16, 'quote-nfc-safe/2+ucd15.0.0', "
            "'matched', 'fixture-nli', '1', ?, 1, '2026-09-27T10:00:00Z')", self.source["content_hash"], signal)

    def held_alarm(self, signal="alarm"):
        self.alarm(signal)
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, "
            "deadline_at, clears_when, created_at) VALUES (?, ?, 'quote:qck_quote00001', 'judgment', 'NLI alarm', 'needs_decision', "
            "'primary', 'primary:station-1', '2026-09-27T11:00:00Z', 'NLI adjudication', '2026-09-27T10:00:00Z')", HOLD, TOPIC)

    def attention(self, out, cause):
        self.assertEqual(self.rows("SELECT hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, "
            "owner, deadline_at, created_at, created_by_operation_id, cleared_at FROM holds"), [(
            HOLD, TOPIC, "quote:qck_quote00001", "judgment", "quote quarantine: " + cause, "needs_remediation", "primary",
            "primary:station-1", "2026-09-27T11:00:00Z", out["receipt"]["committed_at"], self.env["operation_id"], None)])
        self.assertEqual(out["receipt"]["effects"]["holds_created"], [HOLD])
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", out["receipt"]["effects"]["audit_event_id"]))
        self.assertEqual(audit["quote_holds"], [HOLD])
        status = self.router.status({"topic_id": TOPIC})
        self.assertEqual([(h["hold_id"], h["owner"]) for h in status["topics"][0]["holds"]], [(HOLD, "primary:station-1")])
        self.assertEqual(self.rows("SELECT * FROM source_lifecycle"), [])


class AttentionTest(AttentionCase):
    def test_mismatch_notification(self):
        self.attention(self.accepted(self.record(quoted_text="effect NOT observed")), "protected_negation")

    def test_near_notification(self):
        self.attention(self.accepted(self.near()), "near_match")

    def test_match_control(self):
        out = self.accepted()
        self.assertEqual(self.rows("SELECT * FROM holds"), [])
        self.assertEqual(out["receipt"]["effects"]["holds_created"], [])

    def test_notification_replay(self):
        out = self.accepted(self.record(quoted_text="effect NOT observed"))
        before = self.state(exclude=())
        replay = self.router.commit_outcome(self.env)
        self.assertEqual((replay["status"], replay["receipt"]), ("replayed", out["receipt"]))
        self.assertEqual(self.state(exclude=()), before)

    def test_recapture(self):
        self.accepted(self.record(quoted_text="effect NOT observed"))
        old_hold = self.rows("SELECT * FROM holds")
        old_check = self.rows("SELECT * FROM quote_checks")
        record, doc = self.operands(2)
        record["check_id"] = doc["quote_check_id"] = "qck_recapture01"
        self.accepted(record, verification_receipts=[doc])
        self.promote(2)
        self.assertEqual(self.rows("SELECT * FROM holds"), old_hold)
        self.assertEqual(self.rows("SELECT * FROM quote_checks WHERE check_id = 'qck_quote00001'"), old_check)
        self.assertEqual(self.rows("SELECT claim_revision, exact_match, quote_quarantined FROM quote_checks"), [(1, "mismatch", 1), (2, "matched", 0)])

    def test_nli_adjudication_control(self):
        self.alarm()
        doc = {**self.receipt_document(), "adjudication": ADJ}
        out = self.send([], verification_receipts=[doc])
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT verdict FROM verification_receipts"), [("supports",)])
        self.assertEqual(json.loads(self.value("SELECT receipt FROM verification_receipts"))["adjudication"], ADJ)
        self.assertEqual(self.value("SELECT quote_quarantined FROM quote_checks"), 1)
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)

    def test_non_quote_clearance_control(self):
        self.hold(self.capture_grant, "hold_ordinary01")
        out = self.decide("opd_clear00001", "hold_clearance", {"kind": "hold", "ref": "hold_ordinary01"})
        self.assertEqual(out["status"], "applied", out)
        self.assertEqual(self.value("SELECT cleared_by_decision_id FROM holds"), "opd_clear00001")

    def test_nli_clearance_control(self):
        self.held_alarm()
        out = self.decide("opd_clear00001", "hold_clearance", {"kind": "hold", "ref": HOLD})
        self.assertEqual(out["status"], "applied", out)
        self.assertEqual(self.value("SELECT cleared_by_decision_id FROM holds"), "opd_clear00001")


class SharedOwnerTest(AttentionCase):
    verifier_station = "station-1"
    verifier_deadline = "2026-09-27T11:00:00Z"

    def test_control(self):
        self.attention(self.accepted(self.record(quoted_text="effect NOT observed")), "protected_negation")


class RouterGuardTest(AttentionCase):
    def setUp(self):
        super().setUp()
        for trigger in ("verification_receipts_no_byte_adjudication", "operator_decisions_no_byte_clearance", "holds_no_byte_clearance"):
            self.x("DROP TRIGGER " + trigger)  # isolate Router guards from DDL

    def refuse_adjudication(self, doc):
        unreferenced_checks(doc)  # Unreferenced /2 isolation of the byte-adjudication guard.
        before = self.state(exclude=())
        out = self.send([], verification_receipts=[{**doc, "adjudication": ADJ}])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertIn("byte-mismatch quarantine cannot be adjudicated", out.get("detail", ""))
        self.rolled_back(before)

    def test_mismatch_adjudication(self):
        self.accepted(self.record(quoted_text="effect NOT observed"))
        self.refuse_adjudication(self.receipt_document("mismatch", "does_not_support"))

    def test_near_adjudication(self):
        record = self.near()
        self.accepted(record)
        doc = self.receipt_document("mismatch", "does_not_support")
        doc["source"]["source_version"] = "v2"
        doc["obtained_content_hash"] = doc["checks"]["exact_quote"]["source_artifact_hash"] = record["artifact_ref"]["content_hash"]
        doc["cited_spans"][0].update(start=0, end=100)
        self.refuse_adjudication(doc)

    def test_declared_mismatch(self):
        self.alarm()
        self.x("DROP TRIGGER verification_receipts_bindings")  # isolate the declared-byte guard
        doc = self.receipt_document("mismatch", "does_not_support")
        self.refuse_adjudication(doc)

    def test_capture_mismatch(self):
        self.accepted(self.record(quoted_text="effect NOT observed"))
        self.accepted(self.record(check_id="qck_matching001"))
        doc = self.receipt_document(verdict="does_not_support")
        doc["quote_check_id"] = "qck_matching001"
        self.refuse_adjudication(doc)

    def test_non_nli_quarantine(self):
        self.alarm("not_run")
        self.refuse_adjudication(self.receipt_document(verdict="does_not_support"))

    def test_clearance(self):
        self.accepted(self.record(quoted_text="effect NOT observed"))
        self.refuse_clearance()

    def test_non_nli_clearance(self):
        self.held_alarm("not_run")
        self.refuse_clearance()

    def refuse_clearance(self):
        before = self.state(exclude=())
        out = self.decide("opd_clear00001", "hold_clearance", {"kind": "hold", "ref": HOLD})
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"), out)
        self.assertIn("byte-mismatch quarantine cannot be adjudicated", out.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)
