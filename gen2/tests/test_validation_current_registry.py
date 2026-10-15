"""Current-at-admission policy; retained interpretation and SQL 17 stay intact."""
from unittest.mock import patch

from gen2.tests.router_fixtures import empty_outcome
from gen2.tests import test_extraction_records as records, test_extraction_validations_v2 as v2


class CurrentCases:
    registry, result = v2.V2Case.registry, v2.V2Case.result

    def validation(self, **changes):
        return {**records.RecordCase.validation(self), "policy_version": 2, **changes}

    def merge(self):
        self.registry(7, [("tool-a", "family-a"), ("tool-b", "family-a"), ("tool-c", "family-c")])

    def current_basis(self):
        self.merge()
        self.basis(independent=self.extraction("independent", extractor_identity="tool-c", extractor_registry_version=7))

    def test_current_control(self):
        self.current_basis()
        self.assertEqual(self.send(self.verifier, "op_current001", extraction_validations=[self.validation()])["status"], "committed")
        self.assertEqual(self.result(), 1)
        self.assertEqual(self.store.select("source_extractions", {"extraction_id": "target"})[0]["extractor_registry_version"], 1)
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_initial_control(self):
        self.basis()
        self.assertEqual(self.send(self.verifier, "op_initial001", extraction_validations=[self.validation()])["status"], "committed")
        self.assertEqual(self.result(), 1)

    def test_stale_after_merge(self):
        self.basis()
        self.merge()
        self.refuse(extraction_validations=[self.validation()])

    def test_current_target_stale_validator(self):
        self.merge()
        self.basis(target=self.extraction(extractor_registry_version=7))
        self.refuse(extraction_validations=[self.validation()])

    def test_unrelated_current_extraction(self):
        self.basis()
        self.merge()
        self.assertEqual(self.send(self.verifier, "op_unrelated1", source_extractions=[
            self.extraction("unrelated", extractor_identity="tool-c", extractor_registry_version=7)])["status"], "committed")
        self.refuse(extraction_validations=[self.validation()])

    def test_current_merge_refuses_independence(self):
        self.merge()
        self.basis(independent=self.extraction("independent", extractor_registry_version=7))
        self.refuse(extraction_validations=[self.validation()])

    def test_current_integrity_control(self):
        self.merge()
        self.basis(independent=self.extraction("independent", extractor_registry_version=7))
        self.assertEqual(self.send(self.verifier, "op_integrity01", extraction_validations=[
            self.validation(method="same_family_replay")])["status"], "committed")
        self.assertEqual(self.result(), 0)

    def test_stale_integrity(self):
        self.basis(independent=self.extraction("independent", extractor_identity="tool-a"))
        self.merge()
        self.refuse(extraction_validations=[self.validation(method="same_family_replay")])

    def test_stale_failed(self):
        self.basis()
        self.merge()
        self.refuse(extraction_validations=[self.validation(outcome="failed", comparison="disagreement")])

    def test_retained_interpretation(self):
        self.basis()
        self.assertEqual(self.send(self.verifier, "op_retained01", extraction_validations=[self.validation()])["status"], "committed")
        before = self.store.select("extraction_validations_v2")
        self.merge()
        self.assertEqual(self.store.select("extraction_validations_v2"), before)
        self.assertEqual(self.result(), 1)
        self.refuse(extraction_validations=[self.validation(validation_id="new-validation")])


class RouterCurrentRegistryTest(CurrentCases, records.RecordCase):
    # Delegate explicitly: V2Case.send uses zero-argument super().
    def send(self, grant=None, op="op_record0001", **sections):
        if "extraction_validations" in sections:
            sections["extraction_validations_v2"] = sections.pop("extraction_validations")
        return super().send(grant, op, **sections)

    def test_stale_router_guard(self):
        # Only the redundant DDL current guard is removed, in disposable memory,
        # to prove the independent Router check. Every other binding stays on.
        self.x("DROP TRIGGER extraction_validations_v2_current_registry")
        self.test_stale_after_merge()

    def test_target_current_router_guard(self):
        self.x("DROP TRIGGER extraction_validations_v2_current_registry")
        self.test_current_target_stale_validator()

    def test_registry_changes_after_authentication(self):
        self.basis()
        states = []
        original = self.router._extractions.authenticate
        def authenticate(*args):
            original(*args)
            self.assertFalse(self.db.in_transaction)
            self.merge()
            states.append(self.state())
        with patch.object(self.router._extractions, "authenticate", authenticate):
            out = self.send(self.verifier, "op_race000001", extraction_validations=[self.validation()])
        self.assertEqual(out["status"], "rejected", out)
        self.assertEqual(self.state(), states[0])
        self.assertEqual(self.store.select("extraction_validations_v2"), [])
        self.assertEqual(self.store.select("operation_receipts", {"operation_id": "op_race000001"}), [])
        self.assertEqual(max(r["registry_version"] for r in self.store.select("extractor_registry_revisions")), 7)

    def test_same_outcome_control(self):
        self.merge()
        self.assertEqual(self.send(source_extractions=[self.extraction()])["status"], "committed")
        self.assertEqual(self.send(self.verifier, "op_together01", source_extractions=[
            self.extraction("independent", extractor_identity="tool-c", extractor_registry_version=7)],
            extraction_validations=[self.validation()])["status"], "committed")
        self.assertEqual(self.result(), 1)

    def test_replay_after_merge(self):
        self.basis()
        payload = {**empty_outcome(self.verifier["invocation_id"], "interim_transition"),
            "extraction_validations_v2": [self.validation()]}
        env = self.envelope(self.verifier, "op_replay0001", payload)
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
        self.merge()
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.router.commit_outcome({**env, "expected_state_revision": 999})["reason"], "operation_id_conflict")
        self.assertEqual(self.result(), 1)

    def test_current_rollback(self):
        self.current_basis()
        before = self.state(exclude=())
        self.faults["in_transaction:evidence"] = RuntimeError("after current admission")
        with self.assertRaisesRegex(RuntimeError, "after current admission"):
            self.send(self.verifier, "op_rollback01", extraction_validations=[self.validation()])
        self.assertEqual(self.state(exclude=()), before)

    def test_legacy_after_merge_control(self):
        self.basis()
        self.merge()
        self.assertEqual(records.RecordCase.send(self, self.verifier, "op_legacy0001",
            extraction_validations=[self.validation(policy_version=1)])["status"], "committed")
        self.assertEqual(self.store.select("extraction_validations")[0]["policy_version"], 1)
        self.assertEqual(self.store.select("extraction_validations_v2"), [])
