"""Predicate-isolated canonical consumption; SQL proves recorded lineage only."""
import json
import sqlite3

from gen2.tests.store_fixtures import TOPIC, T, h
from gen2.tests import test_store_acquisition_relationships as relationships


class CanonicalDDLTest(relationships.RelationshipTest):
    # Use operand builders, without inheriting the prior slice's test inventory.
    test_binding = test_verifier = test_immutable = test_control = None
    test_relationships = test_relationship_controls = test_natural_key = None

    def raw(self, **changes):
        super().raw(**changes)
        from gen2.tests.extraction_receipt_fixtures import seed
        seed(self)

    def canonical_receipt(self, **changes):
        acq = {"route": "gateway:crossref", "retrieved_at": T, "gateway_call_ref": "gw-call:1", "cache_reuse": True}
        acq.update(changes.pop("acquisition", {}))
        version = changes.pop("version", "v2")
        self.verify("ver_canonical1", tier="bibliographic", required="bibliographic", method="canonical_bytes", extraction=changes.pop("extraction", "inv_pppppppp"), use="sampled", quote=("not_applicable", None),
            gateway=acq["gateway_call_ref"], receipt_overrides={"source": {"work_id": changes.get("work", "wrk_00000001"), "source_version": version}, "acquisition": acq},
            column_overrides={"source_version": version, "acquisition": json.dumps(acq)}, **changes)

    def test_canonical_control(self):
        self.raw()
        self.canonical_receipt()
        self.assertEqual(self.rows("SELECT source_version, extraction_method, extraction_invocation_id FROM verification_receipts WHERE verification_receipt_id = 'ver_canonical1'"),
            [("v2", "canonical_bytes", "inv_pppppppp")])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_missing_admission(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "must consume its admitted acquisition"):
            self.canonical_receipt()

    def test_predicates(self):
        for name in ("work", "version", "verifier", "hash", "acquirer", "call", "time", "route"):
            with self.subTest(predicate=name):
                self.x("SAVEPOINT canonical")
                try:
                    acquisition, negative, control = self.operands(name)
                    self.raw(**acquisition)
                    before = self.rows("SELECT * FROM verification_receipts")
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "must consume its admitted acquisition"):
                        self.canonical_receipt(**negative)
                    self.assertEqual(self.rows("SELECT * FROM verification_receipts"), before)
                    self.canonical_receipt(**control)
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
                finally:
                    self.x("ROLLBACK TO canonical")
                    self.x("RELEASE canonical")

    def operands(self, name):
        if name == "work":
            self.other_work()
            return {"work_id": "wrk_other001", "event_id": "e2", "provider_record_id": "rec-2"}, {}, {"work": "wrk_other001"}
        if name == "version":
            return {}, {"version": "v3"}, {}
        if name == "hash":
            self.artifact()
            return {}, {"obtained": h("e")}, {}
        if name == "verifier":
            self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_vvvvvvvv'", T)
            self.lease("lease_newver1", 99, scope="verification")
            self.invocation("inv_newver01", kind="verification", lease="lease_newver1")
            return {"verifier_invocation_id": "inv_newver01"}, {}, {"verifier": "inv_newver01"}
        if name == "acquirer":
            self.lease("lease_newacq1", 99, scope="checkpoint")
            self.invocation("inv_newacq01", kind="checkpoint", lease="lease_newacq1")
            self.observation(invocation="inv_newacq01")
            self.event(observation="o2")
            return {"acquired_by_invocation_id": "inv_newacq01", "observation_id": "o2", "event_id": "e2", "provider_record_id": "rec-2", "attempt": 2}, {}, {"extraction": "inv_newacq01"}
        field, value = {"call": ("gateway_call_ref", "gw-call:2"), "time": ("retrieved_at", "2026-09-28T00:00:00Z"), "route": ("route", "gateway:core")}[name]
        return {}, {"acquisition": {field: value}}, {}
