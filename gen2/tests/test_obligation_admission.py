"""2d-1: literal judgment oracles, raw SQL history and atomic refusals.

Only disposable fixture stores; this tests admission, not scientific truth.
"""
import json
from pathlib import Path

from gen2.router.schemas import SchemaSet
from gen2.tests.router_fixtures import TOPIC, OTHER, empty_outcome
from gen2.tests.test_confidence_contract import declare, SCHEME
from gen2.tests.router_fixtures import Workflow, contract

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema/obligation-assessment.schema.json"


class AdmissionTest(Workflow):
    def setUp(self):
        super().setUp()
        self.open_brief()
        self.confirm()
        self.doc = contract(2, 1, edit=declare)
        self.assertEqual(self.draft(contract(1, None, rated=False, edit=declare))["status"], "recorded")
        self.assertEqual(self.rate(self.doc)["status"], "applied")
        self.assertEqual(self.draft(self.doc)["status"], "recorded")
        self.scope_approved()
        self.assertEqual(self.approve(self.doc)["status"], "applied")
        self.grant = self.started("inv_obligation01")
        self.ref = self.artifact(b"independent retained assessment evidence")

    def record(self, **changes):
        return {"record_id": "oa-first", "obligation_id": "O-1", "subject": "Effect on omissions", "contract_revision": 2,
            "contract_content_hash": self.doc["content_hash"], "eligibility_protocol_version": 1, "framing_version": 1,
            "evidence_refs": [self.ref], "reason": "Independent evidence within the declared scope", "supersedes_id": None,
            "disposition": "supported", "confidence": {"basis": "recorded_assessment", "scheme": {"scheme_id": SCHEME["scheme_id"], "version": 1}, "label": "corroborated"}, **changes}

    def send(self, records, grant=None, refs=None):
        grant = grant or self.grant
        outcome = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "obligation_assessments": records}
        self.env = self.envelope(grant, self.ids("op_"), outcome, refs=[self.ref] if refs is None else refs)
        return self.router.commit_outcome(self.env)

    def reject(self, record, reason="payload_invalid", detail=None, **kwargs):
        before = self.state()
        out = self.send([record], **kwargs)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        if detail is not None:
            self.assertIn(detail, out["detail"])
        self.assert_audited_state(before, 1)

    def test_control(self):
        out = self.send([self.record()])
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT actor_kind, invocation_id, recorded_by_operation_id, contract_revision, disposition FROM obligation_assessments"),
            [("primary", "inv_obligation01", self.env["operation_id"], 2, "supported")])
        confidence = json.loads(self.value("SELECT confidence FROM obligation_assessments"))
        self.assertEqual(confidence, {"basis": "recorded_assessment", "scheme": {"scheme_id": "plan-corroboration", "version": 1},
            "label": "corroborated", "assessed_by_invocation_id": "inv_obligation01"})
        self.assertEqual(json.loads(self.value("SELECT evidence_refs FROM obligation_assessments")), [self.ref])
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)

    def test_scheme_and_pins(self):
        self.x("DROP TRIGGER obligation_assessments_bound")  # isolate admission from its DDL mirror
        self.x("DROP TRIGGER obligation_assessments_scheme")
        for change in ({"label": "off-scheme"}, {"scheme": {"scheme_id": "foreign", "version": 1}}, {"scheme": {"scheme_id": SCHEME["scheme_id"], "version": 2}}):
            self.reject(self.record(confidence={**self.record()["confidence"], **change}))
        for change in ({"contract_revision": 1}, {"contract_content_hash": "sha256:" + "1" * 64}, {"framing_version": 2}, {"eligibility_protocol_version": 2}, {"obligation_id": "missing"}):
            self.reject(self.record(**change), detail="obligation does not exist" if "obligation_id" in change else "exact contract pins")

    def test_evidence(self):
        self.reject(self.record(), "payload_missing", refs=[])
        self.reject(self.record(evidence_refs=[{**self.ref, "size_bytes": self.ref["size_bytes"] + 1}]))
        foreign = self.artifact(b"other topic's evidence")
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, topic_id, staged_at) VALUES (?, ?, ?, ?, '2026-09-27T09:00:00Z')",
            foreign["content_hash"], foreign["size_bytes"], foreign["media_type"], OTHER)
        self.reject(self.record(evidence_refs=[foreign]), "payload_missing", refs=[])

    def test_roles_and_attribution(self):
        delegate = self.claim("inv_obl_delegate", "delegate", parent=self.grant)
        self.reject(self.record(), "kind_not_permitted", grant=delegate)
        self.to_scoping(OTHER)
        scoping = self.started("inv_obl_scoping", tid=OTHER)
        self.reject(self.record(), "kind_not_permitted", grant=scoping)
        for field, value in (("actor_kind", "operator"), ("invocation_id", "inv_foreign001"), ("created_at", "2026-10-10T00:00:00Z")):
            self.reject(self.record(**{field: value}))
        self.reject(self.record(confidence={**self.record()["confidence"], "assessed_by_invocation_id": "inv_foreign001"}))

    def test_histories_and_conflicts(self):
        self.x("DROP TRIGGER obligation_assessments_predecessor")  # isolate the Router chain check
        self.assertEqual(self.send([self.record()])["status"], "committed")
        unknown = {"basis": "unknown", "reason": "Access is unavailable"}
        open_record = self.record(record_id="oa-open", confidence=unknown, state="open")
        del open_record["disposition"]
        self.assertEqual(self.send([self.record(record_id="oa-defer", disposition="deferred", confidence=unknown, supersedes_id="oa-first"),
            self.record(record_id="oa-competing", disposition="contradicted", supersedes_id="oa-first"), open_record])["status"], "committed")
        self.assertEqual(self.rows("SELECT record_id, disposition, state, supersedes_id FROM obligation_assessments ORDER BY record_id"),
            [("oa-competing", "contradicted", None, "oa-first"), ("oa-defer", "deferred", None, "oa-first"), ("oa-first", "supported", None, None), ("oa-open", None, "open", None)])
        self.assertEqual(json.loads(self.value("SELECT confidence FROM obligation_assessments WHERE record_id = 'oa-defer'")), unknown)
        self.reject(self.record(disposition="unresolved"))  # identity conflict rolls back
        self.reject(self.record(record_id="oa-new", supersedes_id="missing"))
        self.reject(self.record(record_id="oa-new", obligation_id="O-2", supersedes_id="oa-first"))

    def test_predecessor_time(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        self.router._clock = lambda: self.value("SELECT created_at FROM obligation_assessments WHERE record_id = 'oa-first'")
        self.reject(self.record(record_id="oa-new", supersedes_id="oa-first"))

    def test_schema(self):
        target = "obligation-assessment.schema.json"
        schemas = SchemaSet(extra={target: json.loads(SCHEMA_PATH.read_text())})
        self.assertEqual(schemas.errors(self.record(), target), [])
        for field in self.record():
            self.assertTrue(schemas.errors({k: v for k, v in self.record().items() if k != field}, target), field)
        for changes in ({"actor_kind": "operator"}, {"state": "open"}, {"evidence_refs": []}):
            self.assertTrue(schemas.errors(self.record(**changes), target), changes)
        for changes in ({"confidence": {"basis": "unknown", "reason": ""}}, {"confidence": {"basis": "unknown", "reason": " "}},
                        {"state": "open"}, {"evidence_refs": []}, {"disposition": "invented"}, {"confidence": {"probability": 0.9}}):
            self.reject(self.record(**changes), detail="unknown confidence requires its reason" if changes == {"confidence": {"basis": "unknown", "reason": " "}} else None)

    def test_schema_control(self):
        self.assertEqual(SchemaSet(extra={"obligation-assessment.schema.json": json.loads(SCHEMA_PATH.read_text())}).errors(self.record(), "obligation-assessment.schema.json"), [])

    def test_noop_control(self):
        self.assertEqual(self.send([])["status"], "committed")
        self.assertEqual(self.rows("SELECT * FROM obligation_assessments"), [])

    def test_historical_scheme_and_standing(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        before = self.rows("SELECT * FROM obligation_assessments")
        def change(doc):
            declare(doc)
            doc["protocol_revision"] = 3
            doc["confidence_scheme"]["version"] = 2
            doc["confidence_scheme"]["labels"] = {"new-label": "A newly approved rubric"}
        new = contract(3, 2, edit=change)
        self.assertEqual(self.router.propose_amendment({"document": new})["status"], "recorded")
        self.assertEqual(self.approve(new)["status"], "applied")
        self.assertEqual(self.rows("SELECT * FROM obligation_assessments"), before)
        self.assertEqual(json.loads(self.value("SELECT document FROM contract_revisions WHERE topic_id = ? AND revision = 2", TOPIC))["confidence_scheme"], SCHEME)
        self.assertEqual(json.loads(self.value("SELECT document FROM amendment_impacts WHERE topic_id = ? AND kind = 'contract' ORDER BY rowid DESC", TOPIC))["classification"], "protocol_changed")
        self.reject(self.record(record_id="oa-stale"), "amendment_pending")

    def admit_after_approval(self, kind):
        """Fresh checkpoint work uses the operator's actual revision-3 decision."""
        def change(doc):
            declare(doc)
            doc["protocol_revision"] = 3
            doc["confidence_scheme"]["version"] = 2
            doc["confidence_scheme"]["labels"] = {"revised": "Evidence meets the amended rubric"}
            if kind == "reframe_approval":
                doc["facet_map"]["framing_version"] = 2
                doc["facet_map"]["analytic_framework"]["links"][0]["key_question"] = "Does revised coverage prevent omissions?"
        new = contract(3, 2, edit=change)
        self.assertEqual(self.router.propose_amendment({"document": new})["status"], "recorded")
        subject = {"kind": "contract_revision", "revision": 3, "hash": new["content_hash"]}
        if kind == "reframe_approval":
            before = self.state()
            refused = self.decide("opd_not_reframe", "amendment_approval", subject)
            self.assertEqual((refused["status"], refused.get("reason")), ("rejected", "decision_refused"))
            self.assertEqual(self.state(), before)
        out = self.decide("opd_current_approval", kind, subject)
        self.assertEqual(out["status"], "applied", out)
        self.assertEqual(out["effects"]["impact"]["classification"], "reframed" if kind == "reframe_approval" else "protocol_changed")
        self.assertEqual(self.rows("SELECT d.kind, d.disposition, d.subject_revision, d.subject_hash FROM contract_revisions c "
            "JOIN operator_decisions d ON d.decision_id = c.approved_by_decision_id WHERE c.topic_id = ? AND c.revision = 3", TOPIC),
            [(kind, "approved", 3, new["content_hash"])])
        self.reject(self.record(record_id="oa-old-work"), "amendment_pending")
        grant = self.started("inv_current_pins", kind="checkpoint")
        self.assertEqual(grant["admission"]["contract"]["revision"], 3)
        record = self.record(record_id="oa-current", contract_revision=3, contract_content_hash=new["content_hash"],
            framing_version=2 if kind == "reframe_approval" else 1,
            confidence={"basis": "recorded_assessment", "scheme": {"scheme_id": "plan-corroboration", "version": 2}, "label": "revised"})
        for changes in ({"confidence": self.record()["confidence"]}, {"contract_content_hash": self.doc["content_hash"]},
                        {"topic_id": OTHER}, {"obligation_id": "foreign-subject"}, {"actor_kind": "operator"}):
            self.reject({**record, **changes}, grant=grant)
        committed = self.send([record], grant=grant)
        self.assertEqual(committed["status"], "committed", committed)
        self.assertEqual(self.rows("SELECT topic_id, obligation_id, contract_revision, contract_content_hash, framing_version, "
            "eligibility_protocol_version, invocation_id, recorded_by_operation_id FROM obligation_assessments"),
            [(TOPIC, "O-1", 3, new["content_hash"], 2 if kind == "reframe_approval" else 1, 1, "inv_current_pins", self.env["operation_id"])])
        self.assertEqual(json.loads(self.value("SELECT confidence FROM obligation_assessments")),
            {**record["confidence"], "assessed_by_invocation_id": "inv_current_pins"})

    def test_contract_approval_admission_control(self):
        self.admit_after_approval("contract_approval")

    def test_amendment_approval_admission(self):
        self.admit_after_approval("amendment_approval")

    def test_reframe_approval_admission(self):
        self.admit_after_approval("reframe_approval")
