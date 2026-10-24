"""Capture-bound receipt admission and promotion, using literal Router operands."""
import json
from unittest.mock import patch

from gen2.store import db
from gen2.tests.canonical_quotes_fixtures import CanonicalQuotesCase
from gen2.tests.ddl_fixtures import TRIGGERS, restore_triggers
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks, historical_receipt, historical_admission


class CaptureCase(CanonicalQuotesCase):
    def setUp(self):
        super().setUp()
        self.new_capture(2, b"effect observed")

    def new_capture(self, revision, text):
        ref = self.artifact(text)
        out = self.send([], grant=self.capture_grant, refs=[ref], claims=[{"claim_id": "clm_quote00001", "revision": revision,
            "text_ref": ref, "load_bearing": True, "required_access_tier": "full_text"}])
        self.assertEqual(out["status"], "committed", out)
        # Retain subject-local drops as well as the requested mutations/order.
        requested = self.rows(TRIGGERS)
        restore_triggers(self, db.schema_text())
        try:
            doc = self.receipt_document(detailed=False)
            doc['claim']['claim_revision'] = revision
            single = doc['cited_spans']
            for spans in (single, [*single, dict(start=0, end=1, locator=dict(kind='section', value='Results'))]):
                doc['cited_spans'] = spans
                seed_checks(self, doc)
        finally:
            ddl = db.schema_text() + '\n' + '\n'.join('DROP TRIGGER "' + n + '";' for n, _ in self.rows(TRIGGERS))
            ddl += '\n' + '\n'.join(sql + ';' for _, sql in requested)
            restore_triggers(self, ddl)

    def operands(self, revision=2):
        doc = self.receipt_document()
        doc["claim"]["claim_revision"] = revision
        doc["requested_for"]["use"] = "load_bearing"
        attach_checks(self, doc)
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
        historical_receipt(doc)  # Explicit /1 capture-guard refusal isolation.
        before = self.state(exclude=())
        with historical_admission(self):
            out = self.send(records, verification_receipts=[doc])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.rolled_back(before)
        if revision is not None:
            self.promote(revision, accepted=False)

    def rolled_back(self, before):
        after = self.state(exclude=())
        audit = after.pop("audit_events")
        old_audit = before.pop("audit_events")
        self.assert_generation_delta(before, after, 1)  # committed rejection audit only
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

    def substitution(self, change, pending=False):
        record, doc = self.operands()
        if pending:
            # Isolate capture predicates from canonical acquisition selectors;
            # the pending declaration still must bind its cited capture.
            doc["extraction"].update(method="verifier_extraction", produced_by_invocation_id="inv_verify0001")
        change(doc)
        self.refuse([record], doc)

    def test_span(self):
        self.substitution(lambda d: d["cited_spans"][0].update(start=0, end=1))

    def test_version(self):
        self.substitution(lambda d: d["source"].update(source_version="not-recorded"), pending=True)

    def test_work(self):
        events = self.observe(self.capture_grant, "obs_other00001", ("other-record",))
        work = self.register(self.capture_grant, [("doi", "10.1/other", events)])["works"][0]["work_id"]
        self.substitution(lambda d: d["source"].update(work_id=work), pending=True)

    def test_hash(self):
        other = self.artifact(b"other bytes")
        self.send([], grant=self.capture_grant, refs=[other])
        self.substitution(lambda d: d.update(obtained_content_hash=other["content_hash"]), pending=True)

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

    def test_pending_cannot_borrow_historical_canonical(self):
        _, doc = self.operands()
        doc["quote_check_id"] = None
        doc["checks"]["exact_quote"]["status"] = "not_applicable"
        self.assertEqual(self.send([], verification_receipts=[doc])["status"], "committed")
        record, doc = self.operands()
        doc["verification_receipt_id"] = "ver_pending01"
        doc["extraction"].update(method="verifier_extraction", produced_by_invocation_id="inv_verify0001")
        from gen2.tests.extraction_receipt_fixtures import attach
        attach(self, doc)
        attach_checks(self, doc)
        self.accepted(record, verification_receipts=[doc])
        self.promote(accepted=False)

    def test_late_pending_cannot_preserve_support(self):
        self.test_non_quote_control()
        record, doc = self.operands()
        doc["verification_receipt_id"] = "ver_pending01"
        doc["extraction"].update(method="verifier_extraction", produced_by_invocation_id="inv_verify0001")
        from gen2.tests.extraction_receipt_fixtures import attach
        attach(self, doc)
        attach_checks(self, doc)
        before = self.state(exclude=())
        self.accepted(record, verification_receipts=[doc])
        # The bound basis avoids remediation; governed capture still quarantines.
        self.late_store(before, "quarantined", holds=0)

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
        second = self.record(claim_revision=2, check_id="qck_second0001", quoted_text="{", span_start=0, span_end=1)
        doc["cited_spans"].append({"start": 0, "end": 1, "locator": {"kind": "section", "value": "Results"}})
        attach_checks(self, doc)
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
        before = self.state(exclude=())
        phases = []
        def observe(point):
            if point in ("in_transaction:receipt", "in_transaction:evidence", "in_transaction:end"):
                phases.append((point, self.value("SELECT status FROM claims WHERE revision = 2")))
        with patch.object(self.router, "_fault", side_effect=observe):
            self.accepted(self.record(claim_revision=2, quoted_text="effect NOT observed"))
        self.assertEqual(phases, [("in_transaction:receipt", "accepted_support"),
            ("in_transaction:evidence", "accepted_support"), ("in_transaction:end", "quarantined")])
        self.assertEqual(self.value("SELECT status FROM claims WHERE revision = 2"), "quarantined")
        self.late_store(before, "quarantined", checks=1, receipts=0, holds=1)

    def late_store(self, before, status, checks=1, receipts=1, holds=0):
        """Every table: only the disposition, topic revision and commit appends change."""
        after = self.state(exclude=())
        for table, count in (("quote_checks", checks), ("verification_receipts", receipts),
                ("holds", holds),
                ("artifacts", 1), ("artifact_topics", 1), ("operation_receipts", 1), ("audit_events", 1)):
            self.assertEqual(after[table][:len(before[table])], before[table], table)
            self.assertEqual(len(after[table]), len(before[table]) + count, table)
            after[table] = before[table]
        expected_claims = [tuple(status if i == 7 and row[1] == 2 else v for i, v in enumerate(row)) for row in before["claims"]]
        self.assertEqual(after["claims"], expected_claims)
        after["claims"] = before["claims"]
        at = self.value("SELECT committed_at FROM operation_receipts WHERE operation_id = ?", self.env["operation_id"])
        expected_topics = [tuple((v + 1 if i == 5 else at if i == 9 else v) if row[0] == self.grant["topic_id"] else v
            for i, v in enumerate(row)) for row in before["queue_entries"]]
        self.assertEqual(after["queue_entries"], expected_topics)
        after["queue_entries"] = before["queue_entries"]
        # All covered effects commit in one Store transaction.
        self.assert_generation_delta(before, after, 1)
        self.assertEqual(after, before)

    def late_valid(self, multiple=False, accepted=True):
        if accepted:
            self.test_non_quote_control()
        record, doc = self.operands()
        doc["verification_receipt_id"] = "ver_latebound01"
        records = [record]
        if multiple:
            records.append(self.record(claim_revision=2, check_id="qck_second0001", quoted_text="{", span_start=0, span_end=1))
            doc["cited_spans"].append({"start": 0, "end": 1, "locator": {"kind": "section", "value": "Results"}})
        attach_checks(self, doc)
        before = self.state(exclude=())
        self.assertEqual(self.send(records, verification_receipts=[doc])["status"], "committed")
        self.assertEqual(self.rows("SELECT * FROM governed_captures_blocked"), [])
        self.assertEqual(self.rows("SELECT exact_match, quote_quarantined FROM quote_checks"), [("matched", 0)] * len(records))
        self.late_store(before, "accepted_support" if accepted else "provisional", checks=len(records))
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        if not accepted:
            self.promote()

    def test_late_valid_control(self):
        self.late_valid()

    def test_late_multi_control(self):
        self.late_valid(multiple=True)

    def test_late_provisional_control(self):
        self.late_valid(multiple=True, accepted=False)

    def test_late_missing_receipt(self):
        self.test_non_quote_control()
        before = self.state(exclude=())
        self.accepted(self.record(claim_revision=2))
        self.assertEqual(self.rows("SELECT * FROM governed_captures_blocked"), [("clm_quote00001", 2)])
        self.late_store(before, "quarantined", receipts=0)

    def test_late_invalid_receipt(self):
        self.test_non_quote_control()
        record, doc = self.operands()
        doc["verification_receipt_id"] = "ver_latebound01"
        doc["cited_spans"][0].update(start=0, end=1)
        self.refuse([record], doc, revision=None)
        self.assertEqual(self.value("SELECT status FROM claims WHERE revision = 2"), "accepted_support")

    def test_late_boundary_rollback(self):
        self.test_non_quote_control()
        before = self.state(exclude=())
        self.faults["in_transaction:end"] = RuntimeError("after reconciliation")
        with self.assertRaisesRegex(RuntimeError, "after reconciliation"):
            self.send([self.record(claim_revision=2, quoted_text="effect NOT observed")])
        self.assertEqual(self.state(exclude=()), before)


class RouterGuardTest(CaptureTest):
    """Exercise collaborator guards with the independent SQL consumers removed."""
    def setUp(self):
        super().setUp()
        self.x("DROP TRIGGER verification_receipts_capture_binding")
        self.x("DROP TRIGGER claims_accepted_support_needs_capture")
        self.x("DROP TRIGGER verification_receipts_admitted_extraction")

    def substitution(self, change, pending=False):
        # Isolate the capture predicate from the independent receipt consumer.
        with patch.object(self.router._evidence_writer, '_require_own_extraction', return_value=None):
            super().substitution(change, pending)
