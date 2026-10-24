"""Successor records only: registered families, retained comparisons, SQL 17 fence."""
import sqlite3

from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_extraction_records import RecordCase


class V2Case(RecordCase):
    def validation(self, **changes):
        return {**super().validation(), "policy_version": 2, **changes}

    def send(self, grant=None, op="op_record0001", **sections):
        if "extraction_validations" in sections:
            sections["extraction_validations_v2"] = sections.pop("extraction_validations")
        return super().send(grant, op, **sections)

    def result(self):
        return self.value("SELECT method_succeeded FROM extraction_validation_results_v2")

    def test_control(self):
        self.basis()
        self.assertEqual(self.send(self.verifier, "op_validation1", extraction_validations=[self.validation()])["status"], "committed")
        rows = self.store.select("extraction_validations_v2")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["validator_invocation_id"], self.verifier["invocation_id"])
        self.assertEqual(row["comparison_evidence_ref"], self.evidence)
        self.assertEqual(row["policy_version"], 2)
        self.assertEqual(self.result(), 1)
        self.assertEqual(self.rows("SELECT * FROM extraction_validations"), [])
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_integrity_control(self):
        self.basis(independent=self.extraction("independent", extractor_identity="tool-a", extractor_version="2"))
        self.assertEqual(self.send(self.verifier, "op_integrity01", extraction_validations=[self.validation(method="same_family_replay")])["status"], "committed")
        self.assertEqual(self.result(), 0)

    def test_failed_control(self):
        self.basis()
        self.assertEqual(self.send(self.verifier, "op_failed0001", extraction_validations=[self.validation(outcome="failed", comparison="disagreement")])["status"], "committed")
        self.assertEqual(self.result(), 0)

    def test_semantic_control(self):
        self.basis(independent=self.extraction("independent", output_ref=self.evidence))
        self.assertEqual(self.send(self.verifier, "op_semantic001", extraction_validations=[self.validation(comparison="semantic_agreement")])["status"], "committed")
        self.assertEqual(self.result(), 1)

    def test_same_family(self):
        self.assertEqual(self.router.register_extractor_registry({"registry_version": 2, "operator_id": "fixture-operator",
            "reason": "same codebase", "tools": [{"extractor_identity": i, "family": "family-a"}
                for i in ("tool-a", "tool-b")]})["status"], "registered")
        self.basis(independent=self.extraction("independent", extractor_registry_version=2))
        self.refuse(extraction_validations=[self.validation()])

    def registry(self, version, tools):
        self.assertEqual(self.router.register_extractor_registry({"registry_version": version, "operator_id": "fixture-operator",
            "reason": "approve comparison classification", "tools": [{"extractor_identity": i, "family": f}
                for i, f in tools]})["status"], "registered")

    def test_same_identity_renamed(self):
        self.registry(2, [("tool-a", "family-c")])
        self.basis(independent=self.extraction("independent", extractor_identity="tool-a", extractor_registry_version=2))
        self.refuse(extraction_validations=[self.validation()])

    def test_two_identities_renamed(self):
        self.registry(2, [(i, "family-a") for i in ("tool-a", "tool-c")])
        self.registry(3, [(i, "family-c") for i in ("tool-a", "tool-c")])
        self.basis(target=self.extraction(extractor_registry_version=2),
            independent=self.extraction("independent", extractor_identity="tool-c", extractor_registry_version=3))
        self.refuse(extraction_validations=[self.validation()])

    def test_comparison_target_absent(self):
        # Both historical pins are valid; only target membership in the common
        # interpretation is absent. No fallback to the target's old mapping.
        self.registry(2, [("tool-b", "family-b")])
        self.basis(independent=self.extraction("independent", extractor_registry_version=2))
        self.refuse(extraction_validations=[self.validation()])

    def test_cross_revision_control(self):
        self.registry(2, [("tool-a", "family-a"), ("tool-b", "family-b")])
        self.basis(independent=self.extraction("independent", extractor_registry_version=2))
        self.assertEqual(self.send(self.verifier, "op_snapshot01", extraction_validations=[self.validation()])["status"], "committed")
        self.assertEqual(self.result(), 1)
        self.assertEqual(self.rows("SELECT extraction_id,extractor_registry_version FROM source_extractions ORDER BY extraction_id"),
            [("independent", 2), ("target", 1)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_older_comparison_refused(self):
        self.registry(2, [("tool-a", "family-a"), ("tool-b", "family-b")])
        self.basis(target=self.extraction(extractor_registry_version=2))
        self.refuse(extraction_validations=[self.validation()])

    def test_renamed_integrity_control(self):
        self.registry(2, [("tool-a", "family-c")])
        self.basis(independent=self.extraction("independent", extractor_identity="tool-a", extractor_registry_version=2))
        self.assertEqual(self.send(self.verifier, "op_integrity01", extraction_validations=[self.validation(method="same_family_replay")])["status"], "committed")
        self.assertEqual(self.result(), 0)

    def test_two_identities_integrity_control(self):
        self.registry(2, [(i, "family-a") for i in ("tool-a", "tool-c")])
        self.registry(3, [(i, "family-c") for i in ("tool-a", "tool-c")])
        self.basis(target=self.extraction(extractor_registry_version=2),
            independent=self.extraction("independent", extractor_identity="tool-c", extractor_registry_version=3))
        self.assertEqual(self.send(self.verifier, "op_integrity01", extraction_validations=[self.validation(method="same_family_replay")])["status"], "committed")
        self.assertEqual(self.result(), 0)

    def test_comparison_replay_target_absent(self):
        self.registry(2, [("tool-b", "family-a")])
        self.basis(independent=self.extraction("independent", extractor_registry_version=2))
        self.refuse(extraction_validations=[self.validation(method="same_family_replay")])

    def test_method(self):
        self.basis()
        for change in ({"method": "same_family_replay"}, {"method": "same_extractor_replay"},
                {"method": "invented"}, {"policy_version": 1}, {"outcome": "invented", "comparison": "disagreement"},
                {"comparison": "invented", "outcome": "failed"},
                {"outcome": "succeeded", "comparison": "disagreement"}):
            with self.subTest(change=change):
                self.refuse(extraction_validations=[self.validation(**change)])

    def test_replay_semantic(self):
        self.basis(independent=self.extraction("independent", extractor_identity="tool-a"))
        self.refuse(extraction_validations=[self.validation(method="same_family_replay", comparison="semantic_agreement")])

    def test_byte_comparison(self):
        self.basis(independent=self.extraction("independent", output_ref=self.evidence))
        self.refuse(extraction_validations=[self.validation()])

    def test_missing_basis(self):
        self.basis()
        for field in ("target_extraction_id", "validator_extraction_id"):
            with self.subTest(field=field):
                self.refuse(extraction_validations=[self.validation(**{field: "absent"})])

    def test_historical_pin(self):
        self.basis()
        # Historical rows are readable but cannot enter /2. Isolate one operand at a time.
        self.x("DROP TRIGGER source_extractions_immutable_u")
        for identity in ("target", "independent"):
            with self.subTest(identity=identity):
                self.x("UPDATE source_extractions SET extractor_registry_version=NULL WHERE extraction_id=?", identity)
                self.assertIsNone(self.store.select("source_extractions", {"extraction_id": identity})[0]["extractor_registry_version"])
                self.refuse(extraction_validations=[self.validation()])
                self.x("UPDATE source_extractions SET extractor_registry_version=1 WHERE extraction_id=?", identity)

    def test_evidence(self):
        self.basis()
        self.refuse(extraction_validations=[self.validation(comparison_evidence_ref=self.foreign_ref(b"foreign rationale"))])

    def test_evidence_metadata(self):
        self.basis()
        for field, value in (("content_hash", self.output["content_hash"]), ("size_bytes", 999), ("media_type", "application/json")):
            with self.subTest(field=field):
                # A known hash with matching metadata is admissible; missing hash is isolated below.
                if field == "content_hash":
                    value = "0" * 64
                self.refuse(extraction_validations=[self.validation(comparison_evidence_ref={**self.evidence, field: value})])

    def test_immutable(self):
        self.test_control()
        for statement in ("UPDATE extraction_validations_v2 SET created_at=created_at", "DELETE FROM extraction_validations_v2",
                "INSERT OR REPLACE INTO extraction_validations_v2 SELECT * FROM extraction_validations_v2",
                "INSERT INTO extraction_validations_v2 SELECT * FROM extraction_validations_v2 WHERE true ON CONFLICT DO UPDATE SET created_at=excluded.created_at"):
            before = self.state(exclude=())
            with self.assertRaises(sqlite3.IntegrityError):
                self.x(statement)
            self.assertEqual(self.state(exclude=()), before)


class RouterV2Test(V2Case):
    def test_replay_conflict(self):
        self.basis()
        payload = {**empty_outcome(self.verifier["invocation_id"], "interim_transition"), "extraction_validations_v2": [self.validation()]}
        env = self.envelope(self.verifier, "op_replay0001", payload)
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        env = {**env, "expected_state_revision": env["expected_state_revision"] + 1}
        self.assertEqual(self.router.commit_outcome(env)["reason"], "operation_id_conflict")
        self.refuse(extraction_validations=[self.validation(comparison="semantic_agreement")])

    def test_authentication(self):
        self.basis()
        original = self.spool.read
        self.spool.read = lambda digest, **kw: b"corrupt comparison evidence" if digest == self.evidence["content_hash"] else original(digest, **kw)
        self.refuse(extraction_validations=[self.validation()])

    def test_authentication_control(self):
        transactions, original = [], self.spool.read
        def read(*a, **kw):
            transactions.append(self.db.in_transaction)
            return original(*a, **kw)
        self.spool.read = read
        self.test_control()
        self.assertTrue(transactions)
        self.assertFalse(any(transactions))

    def test_validator_kind(self):
        self.basis()
        before = self.state()
        self.assertEqual(self.send(self.extractor, "op_wrongkind1", extraction_validations=[self.validation()])["status"], "rejected")
        self.assert_audited_state(before, 1)

    def test_rollback(self):
        self.basis()
        ref = self.artifact(b"new /2 rationale")
        payload = {**empty_outcome(self.verifier["invocation_id"], "interim_transition"),
            "extraction_validations_v2": [self.validation(comparison_evidence_ref=ref)]}
        env = self.envelope(self.verifier, "op_fault00001", payload, refs=[ref])
        before = self.state(exclude=())
        self.faults["in_transaction:evidence"] = RuntimeError("after successor write")
        with self.assertRaisesRegex(RuntimeError, "after successor write"):
            self.router.commit_outcome(env)
        self.assertEqual(self.state(exclude=()), before)

    def test_legacy_control(self):
        self.basis()
        self.assertEqual(RecordCase.send(self, self.verifier, "op_legacy0001", extraction_validations=[super().validation(policy_version=1)])["status"], "committed")
        self.assertEqual(self.store.select("extraction_validations")[0]["policy_version"], 1)
        self.assertEqual(self.store.select("extraction_validations_v2"), [])
