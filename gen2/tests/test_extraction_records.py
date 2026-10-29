"""Isolated SQL 22 / Router guards; fixture execution only, no receipt changes."""
import sqlite3
from unittest.mock import patch

from gen2.router.boundary import Refusal

from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.router_fixtures import RAW, raw_acquisition
from gen2.tests.router_fixtures import RecordCase


class RecordTest(RecordCase):
    def test_control(self):
        self.basis()
        self.assertEqual(self.send(self.verifier, "op_validation1", extraction_validations=[self.validation()])["status"], "committed")
        self.assertEqual(self.value("SELECT method_succeeded FROM extraction_validation_results"), 1)
        self.assertEqual(self.rows("SELECT extracting_invocation_id FROM source_extractions ORDER BY rowid"),
            [(self.extractor["invocation_id"],), (self.verifier["invocation_id"],)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])

    def test_acquisition(self):
        for field, value in (("event_id", "absent"), ("source_version", "absent"), ("work_id", "wrk_absent001"),
                ("verifier_invocation_id", self.extractor["invocation_id"])):
            with self.subTest(field=field):
                record = self.extraction()
                record[field] = value
                self.refuse(source_extractions=[record])

    def test_tier(self):
        record = self.extraction()
        record["supported_tier"] = "full_text"
        before, refused = self.state(), []
        original = self.router._extractions.write
        def write(*args):
            try:
                return original(*args)
            except Refusal as exc:
                refused.append((exc.reason, exc.detail))
                raise
        with patch.object(self.router._extractions, "write", side_effect=write):
            out = self.send(source_extractions=[record])
        self.assertEqual((out["status"], out.get("reason"), out.get("detail")),
            ("rejected", "payload_invalid", "extraction tier exceeds recorded content"))
        self.assertEqual(refused, [("payload_invalid", "extraction tier exceeds recorded content")])
        self.assert_audited_state(before, 1)

    def test_extractor(self):
        self.basis(target_grant=self.verifier)
        self.refuse(extraction_validations=[self.validation()])

    def test_producer(self):
        # Isolate the producer predicate from the primary-kind admission guard:
        # this synthetic attribution cannot be created through SQL 10 admission.
        self.x("DROP TRIGGER source_artifacts_immutable_u")
        self.x("UPDATE source_artifacts SET invocation_id = ?", self.verifier["invocation_id"])
        self.basis()
        self.refuse(extraction_validations=[self.validation()])

    def test_same_identity(self):
        independent = self.extraction("independent")
        independent.update(extractor_identity="tool-a", extractor_version="2")
        self.basis(independent=independent)
        self.refuse(extraction_validations=[self.validation()])

    def test_missing_basis(self):
        self.basis()
        for field in ("target_extraction_id", "validator_extraction_id"):
            with self.subTest(field=field):
                self.refuse(extraction_validations=[self.validation(**{field: "absent"})])

    def test_foreign_basis(self):
        self.x("INSERT INTO source_artifacts SELECT topic_id, work_id, 'v2', content_hash, invocation_id, recorded_by_operation_id, created_at FROM source_artifacts")
        raw_acquisition(self, source_version="v2")
        self.basis(independent=self.extraction("independent", source_version="v2"))
        self.refuse(extraction_validations=[self.validation()])

    def test_failed(self):
        self.basis()
        failed = self.validation(outcome="failed", comparison="disagreement")
        self.assertEqual(self.send(self.verifier, "op_failed0001", extraction_validations=[failed])["status"], "committed")
        self.assertEqual(self.value("SELECT method_succeeded FROM extraction_validation_results"), 0)

    def test_outcome(self):
        self.basis()
        self.refuse(extraction_validations=[self.validation(outcome="succeeded", comparison="disagreement")])

    def test_byte_comparison(self):
        independent = self.extraction("independent")
        independent["output_ref"] = self.evidence
        self.basis(independent=independent)
        self.refuse(extraction_validations=[self.validation()])

    def test_semantic_control(self):
        independent = self.extraction("independent")
        independent["output_ref"] = self.evidence
        self.basis(independent=independent)
        self.assertEqual(self.send(self.verifier, "op_semantic001", extraction_validations=[self.validation(comparison="semantic_agreement")])["status"], "committed")
        self.assertEqual(self.value("SELECT method_succeeded FROM extraction_validation_results"), 1)

    def test_integrity_control(self):
        independent = self.extraction("independent")
        independent["extractor_identity"] = "tool-a"
        self.basis(independent=independent)
        self.assertEqual(self.send(self.verifier, "op_integrity01", extraction_validations=[self.validation(method="same_extractor_replay")])["status"], "committed")
        self.assertEqual(self.value("SELECT method_succeeded FROM extraction_validation_results"), 0)

    def test_integrity_version(self):
        self.basis(independent=self.extraction("independent", extractor_identity="tool-a", extractor_version="2"))
        self.refuse(extraction_validations=[self.validation(method="same_extractor_replay")])

    def test_artifact(self):
        ref = self.foreign_ref(b"unadmitted output")
        record = self.extraction()
        record["output_ref"] = ref
        self.refuse(source_extractions=[record])

    def test_evidence(self):
        self.basis()
        ref = self.foreign_ref(b"unadmitted comparison")
        self.refuse(extraction_validations=[self.validation(comparison_evidence_ref=ref)])

    def test_evidence_metadata(self):
        self.basis()
        for field, value in (("size_bytes", 999), ("media_type", "application/json")):
            with self.subTest(field=field):
                self.refuse(extraction_validations=[self.validation(comparison_evidence_ref={**self.evidence, field: value})])

    def test_metadata(self):
        for field, value in (("size_bytes", 999), ("media_type", "application/json")):
            with self.subTest(field=field):
                record = self.extraction()
                record["output_ref"] = {**self.output, field: value}
                self.refuse(source_extractions=[record])

    def test_immutable(self):
        self.test_control()
        for table in ("source_extractions", "extraction_validations"):
            for statement in (f"UPDATE {table} SET created_at = created_at", f"DELETE FROM {table}",
                    f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}", f"UPDATE OR REPLACE {table} SET created_at = created_at",
                    f"INSERT INTO {table} SELECT * FROM {table} WHERE true ON CONFLICT DO UPDATE SET created_at = excluded.created_at"):
                with self.subTest(statement=statement):
                    before = self.state(exclude=())
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.x(statement)
                    self.assertEqual(self.state(exclude=()), before)

    def test_record_conflict(self):
        self.basis()
        self.refuse(source_extractions=[self.extraction(extractor_identity="tool-b")])

    def test_rollback(self):
        self.basis()
        record = self.extraction("rollback-output")
        self.refuse(source_extractions=[record], extraction_validations=[self.validation(validator_extraction_id="absent")])

    def test_policy(self):
        self.basis()
        for changes in ({"method": "invented"}, {"policy_version": 2}):
            with self.subTest(changes=changes):
                self.refuse(extraction_validations=[self.validation(**changes)])

    def test_authentication_control(self):
        reads = []
        original = self.spool.read
        def read(*args, **kwargs):
            reads.append(self.db.in_transaction)
            return original(*args, **kwargs)
        self.spool.read = read
        self.test_control()
        self.assertTrue(reads)
        self.assertFalse(any(reads))

    def test_authentication(self):
        original = self.spool.read
        self.spool.read = lambda digest, **key: b"corrupted bytes" if digest == self.output["content_hash"] else original(digest, **key)
        self.refuse(source_extractions=[self.extraction()])

    def test_replay(self):
        record = self.extraction()
        payload = {**empty_outcome(self.extractor["invocation_id"], "interim_transition"), "source_extractions": [record]}
        env = self.envelope(self.extractor, "op_record0001", payload)
        first = self.router.commit_outcome(env)
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(first["status"], "committed")
        env = {**env, "expected_state_revision": env["expected_state_revision"] + 1}
        self.assertEqual(self.router.commit_outcome(env)["reason"], "operation_id_conflict")

    def test_empty_control(self):
        self.assertEqual(self.send()["status"], "committed")


class FullTextTest(RecordCase):
    RESPONSE = RAW.replace(b'"kind":"article"', b'"kind":"full_text","text":"Canonical full text"')

    def test_tiers(self):
        for tier in ("bibliographic", "abstract", "full_text"):
            with self.subTest(tier=tier):
                self.assertEqual(self.send(op="op_" + tier, source_extractions=[self.extraction(tier, supported_tier=tier)])["status"], "committed")


class AtomicTest(RecordCase):
    def test_fault_rollback(self):
        ref = self.artifact(b"new extraction bytes for atomic commit")
        payload = {**empty_outcome(self.extractor["invocation_id"], "interim_transition"),
            "source_extractions": [self.extraction(output_ref=ref)]}
        env = self.envelope(self.extractor, "op_fault00001", payload, refs=[ref])
        before = self.state(exclude=())
        self.faults["in_transaction:evidence"] = RuntimeError("after extraction write")
        with self.assertRaisesRegex(RuntimeError, "after extraction write"):
            self.router.commit_outcome(env)
        self.assertEqual(self.state(exclude=()), before)
