"""Literal confidence oracles; explicit fixtures, no approval/admission claim."""
import copy
import json
import unittest
from dataclasses import asdict, replace

from gen2 import accounting as a
from gen2.accounting import reconciliation as r
from gen2.core import canonical
from gen2.tests.router_fixtures import EXAMPLES

SCHEME = {"scheme_id": "plan-corroboration", "version": 1, "labels": {
    "corroborated": "Independent retained evidence agrees within the declared scope.",
    "tentative": "Retained evidence is relevant but material limitations remain."}}
REF = a.EvidenceReference("sha256:" + "1" * 64, 19, "text/plain")
UNKNOWN = r.UnknownConfidence("unknown", "  Confidence judgment pending adjudication.  ")
RECORDED = r.RecordedConfidence("recorded_assessment", r.SchemePin("plan-corroboration", 1),
                                "tentative", "inv_assess001")


class ConfidenceOperandTest(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((EXAMPLES / "contract-v2" / "valid-two-obligations.json").read_text())["instance"]
        self.contract["confidence_scheme"] = copy.deepcopy(SCHEME)
        self.contract["content_hash"] = canonical.content_hash(self.contract)
        self.fields = dict(record_id="oba_fixture001", topic_id=self.contract["topic_id"], obligation_id="OB-01",
            subject="Effect under the approved framing", contract_revision=self.contract["revision"],
            contract_content_hash=self.contract["content_hash"],
            eligibility_protocol_version=self.contract["eligibility_protocol"]["protocol_version"],
            framing_version=self.contract["facet_map"]["framing_version"], evidence_refs=(REF,), actor_kind="primary",
            invocation_id="inv_assess001", recorded_by_operation_id="op_assess0001",
            created_at="2026-10-10T00:00:00Z", reason="Opposing estimates remain unadjudicated.", supersedes_id=None)
        self.assessment = r.ObligationAssessment(**self.fields, disposition="unresolved", confidence=RECORDED)

    def test_control_recorded(self):
        before = copy.deepcopy(self.contract)
        for label in ("tentative", "corroborated"):
            record = replace(self.assessment, confidence=replace(RECORDED, label=label))
            self.assertIs(r.check_confidence(record, self.contract), record.confidence)
            self.assertEqual(record.evidence_refs, (REF,))
            self.assertEqual(record.reason, "Opposing estimates remain unadjudicated.")
        self.assertEqual(self.contract, before)

    def test_control_unknown(self):
        record = replace(self.assessment, confidence=UNKNOWN)
        self.assertIs(r.check_confidence(record, self.contract), UNKNOWN)
        self.assertEqual(asdict(r.check_confidence(record, self.contract)),
                         {"basis": "unknown", "reason": "  Confidence judgment pending adjudication.  "})
        del self.contract["confidence_scheme"]
        self.assertIs(r.check_confidence(record, self.contract), UNKNOWN)

    def test_off_scheme_refused(self):
        for confidence in (replace(RECORDED, scheme=r.SchemePin("borrowed-scale", 1)),
                           replace(RECORDED, scheme=r.SchemePin("plan-corroboration", 2)),
                           replace(RECORDED, label="high"), replace(RECORDED, label="Tentative"),
                           replace(RECORDED, scheme=r.SchemePin("plan-corroboration", True))):
            with self.subTest(confidence=confidence), self.assertRaisesRegex(ValueError, "contract scheme"):
                r.check_confidence(replace(self.assessment, confidence=confidence), self.contract)

    def test_missing_scheme_refused(self):
        del self.contract["confidence_scheme"]
        with self.assertRaisesRegex(ValueError, "no confidence scheme"):
            r.check_confidence(self.assessment, self.contract)

    def test_exact_pins_required(self):
        for field, value in (("topic_id", "other-topic"), ("contract_revision", 99),
                             ("contract_content_hash", "sha256:" + "2" * 64),
                             ("eligibility_protocol_version", 99), ("framing_version", 99)):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "contract pins"):
                r.check_confidence(replace(self.assessment, **{field: value}), self.contract)

    def test_historical_scheme_uses_own_contract(self):
        current = copy.deepcopy(self.contract)
        current["revision"] += 1
        current["confidence_scheme"] = {"scheme_id": "revised-plan", "version": 2,
                                         "labels": {"reassessed": "Assessment under the revised rubric."}}
        current["content_hash"] = canonical.content_hash(current)
        self.assertIs(r.check_confidence(self.assessment, self.contract), RECORDED)
        with self.assertRaisesRegex(ValueError, "contract pins"):
            r.check_confidence(self.assessment, current)
        new_record = replace(self.assessment, contract_revision=current["revision"],
                             contract_content_hash=current["content_hash"])
        with self.assertRaisesRegex(ValueError, "contract scheme"):
            r.check_confidence(new_record, current)

    def test_unknown_requires_reason(self):
        for reason in ("", " \t\n"):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "requires its reason"):
                r.check_confidence(replace(self.assessment, confidence=r.UnknownConfidence("unknown", reason)), self.contract)
        with self.assertRaises(TypeError):
            r.UnknownConfidence(basis="unknown")

    def test_explicit_basis_required(self):
        for confidence in (replace(RECORDED, basis="unknown"), object()):
            with self.subTest(confidence=confidence), self.assertRaisesRegex(ValueError, "explicit confidence basis"):
                r.check_confidence(replace(self.assessment, confidence=confidence), self.contract)
        with self.assertRaisesRegex(ValueError, "requires its reason"):
            r.check_confidence(replace(self.assessment, confidence=replace(UNKNOWN, basis="recorded_assessment")), self.contract)

    def test_control_open(self):
        record = r.OpenObligation(**self.fields, state="open", confidence=UNKNOWN)
        self.assertIs(r.check_confidence(record, self.contract), UNKNOWN)
        self.assertEqual((record.state, record.record_id, record.invocation_id),
                         ("open", "oba_fixture001", "inv_assess001"))

    def test_open_cannot_have_recorded_confidence(self):
        record = r.OpenObligation(**self.fields, state="open", confidence=RECORDED)
        with self.assertRaisesRegex(ValueError, "open obligation"):
            r.check_confidence(record, self.contract)

    def test_all_dispositions_and_deferral_history_are_supplied(self):
        records = tuple(replace(self.assessment, record_id=f"oba_fixture00{i}", disposition=label, confidence=UNKNOWN,
            supersedes_id="oba_fixture001" if i == 4 else None)
            for i, label in enumerate(("supported", "contradicted", "unresolved", "deferred"), 1))
        contradiction = a.RegistryDisposition("rdp_history00", "contradiction", "C-1", "Opposing retained estimates",
            "unresolved", 1, 1, 1, None, "conflicting_estimates", (REF,), "primary", "inv_assess001",
            "op_assess0001", "2026-10-10T00:00:00Z")
        operands = r.ReconciliationOperands(self.contract["topic_id"], records, (), (), (), (contradiction,), 1, ())
        for record in operands.obligations:
            self.assertIs(r.check_confidence(record, self.contract), UNKNOWN)
        self.assertEqual(tuple(record.disposition for record in operands.obligations),
                         ("supported", "contradicted", "unresolved", "deferred"))
        self.assertEqual(operands.obligations[-1].supersedes_id, "oba_fixture001")
        self.assertEqual(operands.registry_dispositions, (contradiction,))


if __name__ == "__main__":
    unittest.main()
