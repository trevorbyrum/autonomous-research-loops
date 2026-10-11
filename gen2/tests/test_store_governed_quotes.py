"""Raw DDL second-layer guards; literal documents are independent of Router."""
import json
import sqlite3

from gen2.tests.store_fixtures import TOPIC, T, StoreTestCase, h


class DDLTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()
        self.receipt("op_verify0001", "inv_vvvvvvvv", lease="lease_vvvvvvvv", gen=2, before=50)

    def raw(self, status="match", **changes):
        doc = {"expected_artifact_hash": h("7"), "artifact_hash": h("7"), "span_start": 0, "span_end": 5,
            "status": status, "normalization": ["quote-nfc-safe", "2+ucd15.0.0"], "protection": "quote-protection/5",
            "quoted_bytes_hex": "747269616c", "source_span_bytes_hex": "747269616c",
            "normalized_quote": "trial", "normalized_source": "trial", "reason": None, "diagnostic": None,
            "token_versions": ["decimal-expression/2", "english-negation/3", "si9-2022+clinical/2"]}
        row = {"check_id": "qck_governed001", "claim_id": "clm_00000001", "claim_revision": 1, "source_artifact_hash": h("7"),
            "span_start": 0, "span_end": 5, "normalization_version": "quote-nfc-safe/2+ucd15.0.0",
            "exact_match": "mismatch" if status == "mismatch" else "matched", "quote_quarantined": int(status == "mismatch"),
            "nli_signal": "not_run", "checked_at": T, "topic_id": TOPIC, "work_id": "wrk_00000001", "source_version": "v1",
            "verifier_invocation_id": "inv_vvvvvvvv", "recorded_by_operation_id": "op_verify0001", "match_result": json.dumps(doc), **changes}
        self.x(f"INSERT INTO quote_checks ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())

    def test_control(self):
        self.raw()
        self.verify("ver_governed001", quote=("matched", "qck_governed001"))
        self.assertEqual(self.rows("SELECT exact_match, quote_quarantined FROM quote_checks WHERE check_id = 'qck_governed001'"), [("matched", 0)])

    def test_binding(self):
        for changes in ({"source_version": "v2"}, {"topic_id": "fleet-a:t2"}, {"verifier_invocation_id": "inv_pppppppp"},
                        {"recorded_by_operation_id": "op_00000001"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, "governed quote needs"):
                self.raw(**changes)

    def test_result_summary(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw("mismatch", exact_match="matched")

    def test_missing_status(self):
        document = {"expected_artifact_hash": h("7"), "artifact_hash": h("7"), "span_start": 0, "span_end": 5,
            "normalization": ["quote-nfc-safe", "2+ucd15.0.0"]}
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw(match_result=json.dumps(document))

    def test_quarantine(self):
        self.raw("mismatch")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "governed quarantined quote"):
            self.verify("ver_governed001", quote=("mismatch", "qck_governed001"), verdict="partially_supports")

    def test_immutable(self):
        self.raw()
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("UPDATE quote_checks SET match_result = NULL WHERE check_id = 'qck_governed001'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("DELETE FROM quote_checks WHERE check_id = 'qck_governed001'")
