"""Raw DDL second-layer guards; literal documents are independent of Router."""
import json
import re
import sqlite3

from gen2.tests.store_fixtures import TOPIC, T, StoreTestCase, h

# SQLite prints the one match_result CHECK across lines; this is its contiguous first clause.
MATCH_RESULT = "match_result IS NULL OR ("


class DDLTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()
        self.receipt("op_verify0001", "inv_vvvvvvvv", lease="lease_vvvvvvvv", gen=2, before=50)

    def raw(self, status="match", **changes):
        doc = {"expected_artifact_hash": self.source_hash, "artifact_hash": self.source_hash, "span_start": 0, "span_end": 5,
            "status": status, "normalization": ["quote-nfc-safe", "2+ucd15.0.0"], "protection": "quote-protection/5",
            "quoted_bytes_hex": "747269616c", "source_span_bytes_hex": "747269616c",
            "normalized_quote": "trial", "normalized_source": "trial", "reason": None, "diagnostic": None,
            "token_versions": ["decimal-expression/2", "english-negation/3", "si9-2022+clinical/2"]}
        row = {"check_id": "qck_governed001", "claim_id": "clm_00000001", "claim_revision": 1, "source_artifact_hash": self.source_hash,
            "span_start": 0, "span_end": 5, "normalization_version": "quote-nfc-safe/2+ucd15.0.0",
            "exact_match": "mismatch" if status == "mismatch" else "matched", "quote_quarantined": int(status == "mismatch"),
            "nli_signal": "not_run", "checked_at": T, "topic_id": TOPIC, "work_id": "wrk_00000001", "source_version": "v1",
            "verifier_invocation_id": "inv_vvvvvvvv", "recorded_by_operation_id": "op_verify0001", "match_result": json.dumps(doc), **changes}
        self.x(f"INSERT INTO quote_checks ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())

    def test_control(self):
        self.raw()
        self.verify("ver_governed001", gateway="gw-call:1", quote=("matched", "qck_governed001"), receipt_overrides={"checks": {
            **self.CHECKS_OK, "exact_quote": {"status": "matched", "normalization_version": "quote-nfc-safe/2+ucd15.0.0", "source_artifact_hash": self.source_hash}}})
        self.assertEqual(self.rows("SELECT exact_match, quote_quarantined FROM quote_checks WHERE check_id = 'qck_governed001'"), [("matched", 0)])

    def test_binding(self):
        for changes in ({"source_version": "v2"}, {"topic_id": "fleet-a:t2"}, {"verifier_invocation_id": "inv_pppppppp"},
                        {"recorded_by_operation_id": "op_00000001"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, "governed quote needs"):
                self.raw(**changes)

    def test_result_summary(self):
        before = self.snapshot("quote_checks")
        with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(MATCH_RESULT)):
            self.raw("mismatch", exact_match="matched")
        self.assertEqual(self.snapshot("quote_checks"), before)

    def test_missing_status(self):
        document = {"expected_artifact_hash": self.source_hash, "artifact_hash": self.source_hash, "span_start": 0, "span_end": 5,
            "normalization": ["quote-nfc-safe", "2+ucd15.0.0"]}
        self.x("SAVEPOINT counterpart")  # admitted: this exact document plus its status
        self.raw(match_result=json.dumps({**document, "status": "match"}))
        self.assertEqual(self.rows("SELECT exact_match FROM quote_checks WHERE check_id = 'qck_governed001'"), [("matched",)])
        self.x("ROLLBACK TO counterpart")
        self.x("RELEASE counterpart")
        before = self.snapshot("quote_checks")
        with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(MATCH_RESULT)):
            self.raw(match_result=json.dumps(document))
        self.assertEqual(self.snapshot("quote_checks"), before)

    def test_quarantine(self):
        self.raw("mismatch")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "governed quarantined quote"):
            self.verify("ver_governed001", gateway="gw-call:1", quote=("mismatch", "qck_governed001"), verdict="partially_supports")

    def test_immutable(self):
        self.raw()
        before = self.snapshot("quote_checks")
        self.rejects("quote checks are immutable; re-capture writes a new check", "UPDATE quote_checks SET match_result = NULL WHERE check_id = 'qck_governed001'")
        self.assertEqual(self.snapshot("quote_checks"), before)
        self.rejects("quote checks are never deleted; a quarantine stays on record (C-11)", "DELETE FROM quote_checks WHERE check_id = 'qck_governed001'")
        self.assertEqual(self.snapshot("quote_checks"), before)
