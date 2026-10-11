"""Capture-bound receipt admission and promotion, using literal Router operands."""
import json

from gen2.tests.test_governed_quotes import QuotesCase


class CaptureCase(QuotesCase):
    def setUp(self):
        super().setUp()
        self.new_capture(2, b"effect observed")

    def new_capture(self, revision, text):
        ref = self.artifact(text)
        out = self.send([], grant=self.capture_grant, refs=[ref], claims=[{"claim_id": "clm_quote00001", "revision": revision,
            "text_ref": ref, "load_bearing": True, "required_access_tier": "full_text"}])
        self.assertEqual(out["status"], "committed", out)

    def operands(self, revision=2):
        doc = self.receipt_document()
        doc["claim"]["claim_revision"] = revision
        doc["requested_for"]["use"] = "load_bearing"
        return self.record(claim_revision=revision), doc

    def promote(self, revision=2, accepted=True):
        before = self.state(exclude=())
        out = self.send([], grant=self.capture_grant, claim_promotions=[{"claim_id": "clm_quote00001", "revision": revision}])
        self.assertEqual(out["status"], "committed" if accepted else "rejected", out)
        if not accepted:
            self.rolled_back(before)
        self.assertEqual(self.value("SELECT status FROM claims WHERE claim_id = 'clm_quote00001' AND revision = ?", revision),
            "accepted_support" if accepted else "provisional")

    def refuse(self, records, doc, revision=2):
        before = self.state(exclude=())
        out = self.send(records, verification_receipts=[doc])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.rolled_back(before)
        if revision is not None:
            self.promote(revision, accepted=False)

    def rolled_back(self, before):
        after = self.state(exclude=())
        audit = after.pop("audit_events")
        old_audit = before.pop("audit_events")
        self.assertEqual(after, before)
        self.assertEqual(audit[:-1], old_audit)
        self.assertEqual(len(audit), len(old_audit) + 1)
        self.assertEqual(self.value("SELECT kind FROM audit_events ORDER BY rowid DESC LIMIT 1"), "commit_rejected")
        self.assertEqual(json.loads(self.value("SELECT detail FROM audit_events ORDER BY rowid DESC LIMIT 1"))["reason"], "payload_invalid")


class CaptureTest(CaptureCase):
    def test_control(self):
        record, doc = self.operands()
        self.accepted(record, verification_receipts=[doc])
        self.promote()

    def substitution(self, change):
        record, doc = self.operands()
        change(doc)
        self.refuse([record], doc)

    def test_span(self):
        self.substitution(lambda d: d["cited_spans"][0].update(start=0, end=1))

    def test_version(self):
        self.substitution(lambda d: d["source"].update(source_version="not-recorded"))

    def test_work(self):
        events = self.observe(self.capture_grant, "obs_other00001", ("other-record",))
        work = self.register(self.capture_grant, [("doi", "10.1/other", events)])["works"][0]["work_id"]
        self.substitution(lambda d: d["source"].update(work_id=work))

    def test_hash(self):
        other = self.artifact(b"other bytes")
        self.send([], grant=self.capture_grant, refs=[other])
        self.substitution(lambda d: d.update(obtained_content_hash=other["content_hash"]))

    def test_normalization(self):
        self.substitution(lambda d: d["checks"]["exact_quote"].update(normalization_version="other/1"))

    def test_null_reference(self):
        record, doc = self.operands()
        record["quoted_text"] = "effect NOT observed"
        doc["quote_check_id"] = None
        doc["checks"]["exact_quote"]["status"] = "not_applicable"
        self.refuse([record], doc)

    def test_partial_null(self):
        record, doc = self.operands()
        doc.update(quote_check_id=None, verdict="partially_supports")
        doc["checks"]["exact_quote"]["status"] = "not_applicable"
        self.refuse([record], doc)

    def test_non_quote_control(self):
        _, doc = self.operands()
        doc["quote_check_id"] = None
        doc["checks"]["exact_quote"]["status"] = "not_applicable"
        self.assertEqual(self.send([], verification_receipts=[doc])["status"], "committed")
        self.promote()

    def test_non_load_bearing(self):
        doc = self.receipt_document()
        doc["quote_check_id"] = None
        doc["checks"]["exact_quote"]["status"] = "not_applicable"
        self.refuse([self.record(quoted_text="effect NOT observed")], doc, revision=None)
        self.accepted(self.record(quoted_text="effect NOT observed"))
        self.promote(1, accepted=False)

    def test_existing_receipt(self):
        _, doc = self.operands()
        doc["quote_check_id"] = None
        doc["checks"]["exact_quote"]["status"] = "not_applicable"
        self.assertEqual(self.send([], verification_receipts=[doc])["status"], "committed")
        self.accepted(self.record(claim_revision=2, quoted_text="effect NOT observed"))
        self.promote(accepted=False)

    def test_existing_receipt_matching_check(self):
        _, doc = self.operands()
        doc["quote_check_id"] = None
        doc["checks"]["exact_quote"]["status"] = "not_applicable"
        self.assertEqual(self.send([], verification_receipts=[doc])["status"], "committed")
        self.accepted(self.record(claim_revision=2))
        self.promote(accepted=False)

    def test_recapture(self):
        self.accepted(self.record(claim_revision=2, quoted_text="effect NOT observed"))
        self.new_capture(3, b"effect observed")
        record, doc = self.operands(3)
        record["check_id"] = doc["quote_check_id"] = "qck_recapture01"
        self.accepted(record, verification_receipts=[doc])
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        self.promote(3)
        self.promote(2, accepted=False)
        self.assertEqual(self.rows("SELECT claim_revision, exact_match, quote_quarantined FROM quote_checks ORDER BY claim_revision"),
            [(2, "mismatch", 1), (3, "matched", 0)])

    def test_multi_control(self):
        record, doc = self.operands()
        second = self.record(claim_revision=2, check_id="qck_second0001", quoted_text="<", span_start=0, span_end=1)
        doc["cited_spans"].append({"start": 0, "end": 1, "locator": {"kind": "section", "value": "Results"}})
        self.assertEqual(self.send([record, second], verification_receipts=[doc])["status"], "committed")
        self.promote()

    def test_multi_unchecked(self):
        record, doc = self.operands()
        doc["cited_spans"].append({"start": 0, "end": 1, "locator": {"kind": "section", "value": "Results"}})
        self.refuse([record], doc)

    def test_same_capture_cannot_clear(self):
        self.accepted(self.record(claim_revision=2, quoted_text="effect NOT observed"))
        record, doc = self.operands()
        record["check_id"] = doc["quote_check_id"] = "qck_relabel001"
        self.refuse([record], doc)

    def test_negative_control(self):
        record, doc = self.operands()
        record["quoted_text"] = "effect NOT observed"
        doc["checks"]["exact_quote"]["status"] = "mismatch"
        doc["verdict"] = "does_not_support"
        self.accepted(record, verification_receipts=[doc])
        self.promote(accepted=False)

    def test_late_check(self):
        self.test_non_quote_control()
        self.accepted(self.record(claim_revision=2, quoted_text="effect NOT observed"))
        self.assertEqual(self.value("SELECT status FROM claims WHERE revision = 2"), "quarantined")


class RouterGuardTest(CaptureTest):
    """Exercise collaborator guards with the independent SQL consumers removed."""
    def setUp(self):
        super().setUp()
        self.x("DROP TRIGGER verification_receipts_capture_binding")
        self.x("DROP TRIGGER claims_accepted_support_needs_capture")
