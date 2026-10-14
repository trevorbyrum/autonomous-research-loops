"""Independent raw-DDL identity substitutions and authoritative consumers."""
import json
import sqlite3
from unittest.mock import patch

from gen2.tests import store_fixtures
from gen2.tests.store_fixtures import TOPIC, T, h
from gen2.tests.test_store_governed_quotes import DDLTest


class CaptureDDLTest(DDLTest):
    def setUp(self):
        super().setUp()
        self.x("UPDATE claims SET status = 'contested' WHERE claim_id = 'clm_00000001'")

    def bound(self, status="matched", verdict="supports", check_id="qck_governed001", **changes):
        method = changes.pop("method", "canonical_bytes")
        exact = {"status": status, "normalization_version": "quote-nfc-safe/2+ucd15.0.0", "source_artifact_hash": h("7")}
        doc = {"checks": {**self.CHECKS_OK, "exact_quote": exact}, **changes}
        columns = {k: json.dumps(v) if isinstance(v, list) else v for k, v in changes.items() if k in ("cited_spans", "obtained_content_hash")}
        if "source" in changes:
            columns.update(work_id=changes["source"]["work_id"], source_version=changes["source"]["source_version"])
        self.canonical_verify("ver_bound00001", method=method, quote=(status, check_id), verdict=verdict, receipt_overrides=doc, column_overrides=columns)

    def canonical_verify(self, *args, **kwargs):
        method = kwargs.pop("method", "canonical_bytes")
        self.verify(*args, method=method, extraction="inv_vvvvvvvv" if method == "verifier_extraction" else "inv_pppppppp", gateway="gw-call:1", **kwargs)

    def snapshot(self):
        return {n: self.rows(f"SELECT * FROM {n} ORDER BY rowid") for n, in self.rows("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}

    def refused(self, action):
        before = self.snapshot()
        self.x("SAVEPOINT refusal")
        with self.assertRaises(sqlite3.IntegrityError):
            action()
        self.x("ROLLBACK TO refusal")
        self.x("RELEASE refusal")
        self.assertEqual(self.snapshot(), before)

    def promote(self):
        self.x("UPDATE claims SET status = 'accepted_support' WHERE claim_id = 'clm_00000001' AND revision = 1")

    def test_capture_control(self):
        self.raw()
        self.bound()
        self.promote()
        self.assertEqual(self.rows("SELECT status FROM claims"), [("accepted_support",)])

    def test_span(self):
        self.raw()
        self.refused(lambda: self.bound(cited_spans=[{"start": 5, "end": 10, "locator": {"kind": "page", "value": "3"}}]))
        self.refused(self.promote)

    def test_version(self):
        self.x("DROP TRIGGER verification_receipts_admitted_extraction")  # isolate capture selector
        self.raw()
        self.refused(lambda: self.bound(method="verifier_extraction", source={"work_id": "wrk_00000001", "source_version": "missing"}))

    def test_work(self):
        self.x("DROP TRIGGER verification_receipts_admitted_extraction")  # isolate capture selector
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000002', 'doi', '10.1/other', '2026-09-27T10:00:00Z')")
        self.raw()
        self.refused(lambda: self.bound(method="verifier_extraction", source={"work_id": "wrk_00000002", "source_version": "v1"}))

    def test_hash(self):
        self.x("DROP TRIGGER verification_receipts_admitted_extraction")  # isolate capture selector
        self.raw()
        self.refused(lambda: self.bound(method="verifier_extraction", obtained_content_hash=h("8")))

    def test_normalization(self):
        self.raw()
        self.refused(lambda: self.bound(checks={**self.CHECKS_OK, "exact_quote": {
            "status": "matched", "normalization_version": "other/1", "source_artifact_hash": h("7")}}))

    def test_null_reference(self):
        self.raw("mismatch")
        self.refused(lambda: self.canonical_verify("ver_null000001", quote=("not_applicable", None)))
        self.refused(self.promote)

    def test_partial_null(self):
        self.raw()
        self.refused(lambda: self.canonical_verify("ver_null000001", quote=("not_applicable", None), verdict="partially_supports"))

    def test_non_quote_control(self):
        self.canonical_verify("ver_nonquote01", quote=("not_applicable", None))
        self.promote()
        self.assertEqual(self.rows("SELECT status FROM claims"), [("accepted_support",)])

    def test_pending_cannot_borrow_historical_canonical(self):
        # The sweep's canonical receipt predates this governed capture. Its
        # old check/normalization cannot certify the newly checked capture.
        self.raw()
        self.verify("ver_pending01", gateway="gw-call:1", quote=("matched", "qck_governed001"), receipt_overrides={"checks": {
            **self.CHECKS_OK, "exact_quote": {"status": "matched", "normalization_version": "quote-nfc-safe/2+ucd15.0.0", "source_artifact_hash": h("7")}}})
        with self.assertRaisesRegex(sqlite3.IntegrityError, "unbound extraction|governed capture"):
            self.promote()
        self.assertEqual(self.rows("SELECT status FROM claims"), [("contested",)])

    def test_late_pending_cannot_preserve_support(self):
        self.promote()
        self.raw()
        self.verify("ver_pending01", gateway="gw-call:1", quote=("matched", "qck_governed001"), receipt_overrides={"checks": {
            **self.CHECKS_OK, "exact_quote": {"status": "matched", "normalization_version": "quote-nfc-safe/2+ucd15.0.0", "source_artifact_hash": h("7")}}})
        self.finish()
        self.assertEqual(self.rows("SELECT status FROM claims"), [("quarantined",)])

    def test_existing_receipt(self):
        self.canonical_verify("ver_nonquote01", quote=("not_applicable", None))
        self.raw("mismatch")
        self.refused(self.promote)

    def test_existing_receipt_matching(self):
        self.raw()
        self.refused(self.promote)

    def test_non_load_bearing(self):
        self.x("INSERT INTO claims SELECT claim_id, 2, topic_id, text_ref, producer_invocation_id, 0, NULL, 'provisional', created_at FROM claims")
        self.raw("mismatch", claim_revision=2)
        self.refused(lambda: self.canonical_verify("ver_null000002", claim=("clm_00000001", 2), use="sampled", quote=("not_applicable", None)))
        self.refused(lambda: self.x("UPDATE claims SET status = 'accepted_support' WHERE revision = 2"))

    def test_recapture(self):
        self.raw("mismatch")
        self.x("INSERT INTO claims SELECT claim_id, 2, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, 'provisional', created_at FROM claims")
        self.raw(check_id="qck_recapture01", claim_revision=2)
        self.canonical_verify("ver_recapture1", claim=("clm_00000001", 2), quote=("matched", "qck_recapture01"), receipt_overrides={"checks": {
            **self.CHECKS_OK, "exact_quote": {"status": "matched", "normalization_version": "quote-nfc-safe/2+ucd15.0.0", "source_artifact_hash": h("7")}}})
        self.x("UPDATE claims SET status = 'accepted_support' WHERE revision = 2")
        self.refused(self.promote)
        self.assertEqual(self.rows("SELECT revision, status FROM claims ORDER BY revision"), [(1, "contested"), (2, "accepted_support")])
        self.assertEqual(self.rows("SELECT claim_revision, quote_quarantined FROM quote_checks WHERE match_result IS NOT NULL ORDER BY claim_revision"), [(1, 1), (2, 0)])

    def test_multi_unchecked(self):
        self.raw()
        self.refused(lambda: self.bound(cited_spans=[{"start": 0, "end": 5, "locator": {"kind": "page", "value": "3"}},
            {"start": 5, "end": 10, "locator": {"kind": "page", "value": "3"}}]))

    def test_multi_control(self):
        self.raw()
        doc = {"expected_artifact_hash": h("7"), "artifact_hash": h("7"), "span_start": 5, "span_end": 10,
            "status": "match", "normalization": ["quote-nfc-safe", "2+ucd15.0.0"]}
        self.raw(check_id="qck_second0001", span_start=5, span_end=10, match_result=json.dumps(doc))
        self.bound(cited_spans=[{"start": 0, "end": 5, "locator": {"kind": "page", "value": "3"}},
            {"start": 5, "end": 10, "locator": {"kind": "page", "value": "3"}}])
        self.promote()

    def test_negative_control(self):
        self.raw("mismatch")
        self.bound("mismatch", "does_not_support")
        self.assertEqual(self.rows("SELECT verdict FROM verification_receipts WHERE verification_receipt_id = 'ver_bound00001'"), [("does_not_support",)])
        self.refused(self.promote)

    def test_late_check(self):
        self.promote()
        before = self.snapshot()
        self.raw("mismatch")
        self.assertEqual(self.rows("SELECT status FROM claims"), [("accepted_support",)])
        self.finish()
        self.assertEqual(self.rows("SELECT status FROM claims"), [("quarantined",)])
        self.late_store(before, "quarantined", receipts=0)

    def finish(self, operation="op_verify0001"):
        """The same last row as Router._commit_in_transaction; no Router executes."""
        self.x("INSERT INTO audit_events (audit_event_id, at, kind, topic_id, invocation_id, operation_id, detail) "
            "VALUES (?, ?, 'commit_outcome', ?, 'inv_vvvvvvvv', ?, '{}')", "aud_" + operation[3:], T, TOPIC, operation)

    def late_store(self, before, status, checks=1, receipts=1, revision=1):
        after = self.snapshot()
        for table, count in (("quote_checks", checks), ("verification_receipts", receipts), ("audit_events", 1)):
            self.assertEqual(after[table][:len(before[table])], before[table], table)
            self.assertEqual(len(after[table]), len(before[table]) + count, table)
            after[table] = before[table]
        self.assertEqual(after["claims"], [tuple(status if i == 7 and row[1] == revision else v for i, v in enumerate(row)) for row in before["claims"]])
        after["claims"] = before["claims"]
        self.assertEqual(after, before)

    def late_valid(self, multiple=False, accepted=True):
        if accepted:
            self.promote()
        else:
            self.x("UPDATE claims SET status = 'quarantined' WHERE claim_id = 'clm_00000001'")
            self.x("UPDATE claims SET status = 'provisional' WHERE claim_id = 'clm_00000001'")
        before = self.snapshot()
        self.x("SAVEPOINT late")
        self.raw()
        self.assertEqual(self.rows("SELECT status FROM claims"), [("accepted_support" if accepted else "provisional",)])
        spans = [{"start": 0, "end": 5, "locator": {"kind": "page", "value": "3"}}]
        if multiple:
            doc = {"expected_artifact_hash": h("7"), "artifact_hash": h("7"), "span_start": 5, "span_end": 10,
                "status": "match", "normalization": ["quote-nfc-safe", "2+ucd15.0.0"]}
            self.raw(check_id="qck_second0001", span_start=5, span_end=10, match_result=json.dumps(doc))
            spans.append({"start": 5, "end": 10, "locator": {"kind": "page", "value": "3"}})
        self.bound(cited_spans=spans)
        self.finish()
        self.x("RELEASE late")
        self.assertEqual(self.rows("SELECT * FROM governed_captures_blocked"), [])
        self.late_store(before, "accepted_support" if accepted else "provisional", checks=len(spans))
        if not accepted:
            self.promote()
            self.assertEqual(self.rows("SELECT status FROM claims"), [("accepted_support",)])

    def test_late_valid_control(self):
        self.late_valid()

    def test_late_multi_control(self):
        self.late_valid(multiple=True)

    def test_late_provisional_control(self):
        self.late_valid(multiple=True, accepted=False)

    def test_late_missing_receipt(self):
        self.promote()
        before = self.snapshot()
        self.raw()
        self.finish()
        self.assertEqual(self.rows("SELECT * FROM governed_captures_blocked"), [("clm_00000001", 1)])
        self.late_store(before, "quarantined", receipts=0)

    def test_late_invalid_receipt(self):
        self.promote()
        def invalid():
            self.raw()
            self.bound(cited_spans=[{"start": 5, "end": 10, "locator": {"kind": "page", "value": "3"}}])
            self.finish()
        self.refused(invalid)
        self.assertEqual(self.rows("SELECT status FROM claims"), [("accepted_support",)])

    def test_late_boundary_rollback(self):
        self.promote()
        before = self.snapshot()
        self.x("SAVEPOINT late")
        self.raw("mismatch")
        self.finish()
        self.assertEqual(self.rows("SELECT status FROM claims"), [("quarantined",)])
        self.x("ROLLBACK TO late")
        self.x("RELEASE late")
        self.assertEqual(self.snapshot(), before)

    def test_late_provisional_mismatch(self):
        self.x("INSERT INTO claims SELECT claim_id, 2, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, 'provisional', created_at FROM claims")
        before = self.snapshot()
        self.raw("mismatch", claim_revision=2)
        self.finish()
        self.late_store(before, "provisional", receipts=0, revision=2)
        self.refused(lambda: self.x("UPDATE claims SET status = 'accepted_support' WHERE revision = 2"))

    def test_late_unaffected_capture(self):
        # Two in-flight raw operations: finishing one must not settle the other.
        self.promote()
        self.x("INSERT INTO claims SELECT claim_id, 2, topic_id, text_ref, producer_invocation_id, 0, NULL, 'provisional', created_at FROM claims")
        self.x("UPDATE claims SET status = 'accepted_support' WHERE revision = 2")
        self.receipt("op_verify0002", "inv_vvvvvvvv", lease="lease_vvvvvvvv", gen=2, before=51, kind="interim_transition")
        self.raw("mismatch", check_id="qck_otherop001", claim_revision=2, recorded_by_operation_id="op_verify0002")
        before = self.snapshot()
        self.raw()
        self.bound()
        self.finish()
        self.late_store(before, "accepted_support")
        before = self.snapshot()
        self.finish("op_verify0002")
        self.late_store(before, "quarantined", checks=0, receipts=0, revision=2)

    def test_same_capture_cannot_clear(self):
        self.raw("mismatch")
        self.raw(check_id="qck_relabel001")
        self.refused(lambda: self.bound(check_id="qck_relabel001"))

    def upgrade(self, status):
        start = store_fixtures.DDL_TEXT.index("CREATE VIEW governed_receipt_checks AS")
        repair = store_fixtures.DDL_TEXT[start:]
        old = DDLTest()
        with patch.object(store_fixtures, "DDL_TEXT", store_fixtures.DDL_TEXT[:start]):
            old.setUp()
        try:
            old.raw(status)
            if status == "match":
                old.verify("ver_upgrade001", method="canonical_bytes", extraction="inv_pppppppp", gateway="gw-call:1", quote=("matched", "qck_governed001"), receipt_overrides={"checks": {
                    **self.CHECKS_OK, "exact_quote": {"status": "matched", "normalization_version": "quote-nfc-safe/2+ucd15.0.0", "source_artifact_hash": h("7")}}})
            self.assertEqual(old.rows("SELECT status FROM claims"), [("accepted_support",)])
            before = {n: old.rows(f"SELECT * FROM {n} ORDER BY rowid") for n, in old.rows(
                "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
            # SQL 24 adds two nullable retained-byte fields; every original
            # value/row must still match, and both added values must be NULL.
            if 'request_bytes' not in [r[1] for r in old.rows('PRAGMA table_info(search_observations)')]:
                before['search_observations'] = [(*row, None, None) for row in before['search_observations']]
            old.db.executescript(repair)  # disposable in-memory store only
            self.assertEqual({n: old.rows(f"SELECT * FROM {n} ORDER BY rowid") for n in before}, before)
            self.assertEqual(old.rows("PRAGMA foreign_key_check"), [])
            return old.rows("SELECT status FROM claims")
        finally:
            old.tearDown()

    def test_upgrade_control(self):
        self.assertEqual(self.upgrade("match"), [("accepted_support",)])

    def test_installation_no_dml(self):
        self.assertEqual(self.upgrade("mismatch"), [("accepted_support",)])
