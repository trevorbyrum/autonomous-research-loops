"""DEBT-053: operator approval binds retained rejection and reviewed pins; fixture evidence, no real qualification."""
import json
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.operator.service import OperatorService
from gen2.tests import operator_fixtures as of, router_fixtures as rf, test_dispatch as d


class RemediationTests(unittest.TestCase):
    def setUp(self):
        self.c = d.DispatchTests()
        self.c.setUp()
        self.addCleanup(self.c.tearDown)

    def retain(self, refs, operation):
        c = self.c
        payload = rf.empty_outcome(self.proof["invocation_id"], "interim_transition")
        out = c.router.commit_outcome(c.envelope(self.proof, operation, payload, refs=refs))
        self.assertEqual(out["status"], "committed", out)

    def request(self, unknown=False):
        c = self.c
        c.clock.set("2026-10-31T12:00:00Z")
        c.real_route()
        result = c.rejection(c.authorize())
        if unknown:
            c.authority.evidence["actual_minor_units"] = None
        self.assertEqual(c.router.record_dispatch_result(result)["status"], "recorded")
        row = c.store.select("audit_events", {"kind": "dispatch_result"})[0]
        refs = [c.artifact(text) for text in (b"reviewed procedure", b"independent review", b"new qualification")]
        self.evidence = {"remediation_version": "provider-auth-remediation/1", "rejection_ref": row["audit_event_id"],
            "rejection_hash": canonical.logical_hash(row), "deployment_id": "station-live", "provider_route": "codex:responses",
            "credential_ref": "reviewed-seed-2", "manifest_ref": row["detail"]["evidence"]["origin"]["manifest_ref"],
            **dict(zip(("procedure_ref", "review_ref", "qualification_ref"), (r["content_hash"] for r in refs)))}
        proof_ref = c.artifact(rf.jcs(self.evidence), "application/json")
        self.proof = c.started("inv_remedproof1", "checkpoint")
        self.retain([*refs, proof_ref], "op_remedproof1")
        c.clock.set("2026-10-31T12:00:03Z")
        self.other = c.prepare("inv_dispatch02", rf.OTHER)
        c.real_route(self.other)
        c.authority.admissions[self.other["invocation_id"]]["origin"].update(
            credential_ref="reviewed-seed-2", qualification_ref=self.evidence["qualification_ref"])
        c.authority.admissions[self.other["invocation_id"]]["artifacts"].append(refs[2])
        return {"decision_id": "opd_remediate01", "topic_id": rf.TOPIC, "kind": "provider_auth_remediation",
            "disposition": "approved", "subject": {"kind": "provider_rejection", "ref": row["audit_event_id"], "revision": None,
                "hash": canonical.logical_hash(row)}, "operator_id": "alice", "decided_at": "2026-10-31T12:00:02Z",
            "notes": None, "payload": {"evidence_ref": proof_ref["content_hash"]}}

    def test_operator_role_approval_and_replay(self):
        """Operator role is transport-authenticated; audit/SQL and no-table-write oracles, no HTTP daemon."""
        req = self.request()
        c = self.c
        service = OperatorService(c.router, of.credentials())
        raw = rf.jcs({k: v for k, v in req.items() if k != "operator_id"})
        def call(token):
            return service.handle("POST", "/v1/commands/apply_operator_decision", "Bearer " + token, str(len(raw)), lambda size: raw)
        before = c.state()
        self.assertEqual(call(of.EXPORTER_TOKEN)[0], 403)
        self.assertEqual(c.state(), before)
        self.assertEqual(call(of.OPERATOR_TOKEN)[1]["status"], "applied")
        self.assertEqual(c.value("SELECT count(*) FROM operator_decisions WHERE decision_id=?", req["decision_id"]), 0)
        audit = json.loads(c.value("SELECT detail FROM audit_events WHERE kind='provider_auth_remediation'"))
        self.assertEqual(audit["request"], req)
        before = c.state()
        self.assertEqual(call(of.OPERATOR_TOKEN)[1]["status"], "replayed")
        self.assertEqual(c.state(), before)
        with patch.object(c.authority, "current", False):
            c.refused("authorize_dispatch", self.other, "spend_unbounded")
        c.authorize(self.other)

    def test_subject_evidence_refusals_and_atomic_failure(self):
        """One invalid subject/review operand refuses with every table equal; retained local bytes only."""
        req = self.request()
        c = self.c
        for subject in ({**req["subject"], "hash": rf.h("0")}, {**req["subject"], "ref": "aud_missing"},
                        {**req["subject"], "kind": "hold"}, {**req["subject"], "revision": 1}):
            c.refused("apply_operator_decision", {**req, "subject": subject}, "remediation_subject_invalid", status="rejected")
        c.refused("apply_operator_decision", {**req, "payload": {"evidence_ref": rf.h("0")}}, "remediation_evidence_invalid", status="rejected")
        for date in (rf.STAMP, "2027-01-01T00:00:00Z"):
            c.refused("apply_operator_decision", {**req, "decided_at": date}, "remediation_evidence_invalid", status="rejected")
        used = c.value("SELECT decision_id FROM operator_decisions LIMIT 1")
        c.refused("apply_operator_decision", {**req, "decision_id": used}, "decision_id_conflict", status="rejected")
        wrong = c.artifact(rf.jcs({**self.evidence, "provider_route": "codex:wrong"}), "application/json")
        self.retain([wrong], "op_remedwrong1")
        c.refused("apply_operator_decision", {**req, "payload": {"evidence_ref": wrong["content_hash"]}}, "remediation_evidence_invalid", status="rejected")
        missing = c.artifact(rf.jcs({**self.evidence, "review_ref": rf.h("0")}), "application/json")
        self.retain([missing], "op_missingreview")
        c.refused("apply_operator_decision", {**req, "payload": {"evidence_ref": missing["content_hash"]}}, "remediation_evidence_invalid", status="rejected")
        with patch.object(c.router, "_store", rf.Refusing(c.store, 0)):
            c.refused("apply_operator_decision", req, "decision_refused", status="rejected")
        c.refused("authorize_dispatch", self.other, "provider_rejection_stopped")
        self.assertEqual(c.router.apply_operator_decision(req)["status"], "applied")
        c.refused("apply_operator_decision", {**req, "operator_id": "bob"}, "decision_id_conflict", status="rejected")
        c.refused("apply_operator_decision", {**req, "kind": "retirement", "subject": {"kind": "topic", "ref": rf.TOPIC, "revision": 1, "hash": None}}, "decision_id_conflict", status="rejected")

    def test_approval_is_specific_to_replacement_pins_and_each_rejection(self):
        """Approved pins release one rejection; other credentials and a new rejection stay blocked. No real sends."""
        req = self.request()
        c = self.c
        self.assertEqual(c.router.apply_operator_decision(req)["status"], "applied")
        origin = c.authority.admissions[self.other["invocation_id"]]["origin"]
        for key in ("credential_ref", "qualification_ref"):
            with patch.dict(origin, {key: "other"}):
                c.refused("authorize_dispatch", self.other, "provider_rejection_stopped")
        changed = c.artifact(b'{"profile":"other"}', "application/json")
        c.authority.admissions[self.other["invocation_id"]]["artifacts"].append(changed)
        with patch.dict(origin, {"manifest_ref": changed["content_hash"]}):
            c.refused("authorize_dispatch", self.other, "provider_rejection_stopped")
        c.req = self.other
        ref = c.authorize()
        result = c.rejection(ref, observed_at="2026-10-31T12:00:05Z")
        c.authority.evidence["rejection"].update(started_at="2026-10-31T12:00:04Z", observed_at="2026-10-31T12:00:05Z")
        c.clock.set("2026-10-31T12:00:06Z")
        out = c.router.record_dispatch_result(result)
        self.assertEqual(out["status"], "recorded", out)
        self.assertEqual(len(c.router._dispatch._unremediated(origin)), 1)

    def test_unknown_spend_still_stops_after_auth_remediation(self):
        """DEBT-052 is independent: approved auth remediation cannot settle U or resume unknown spending."""
        req = self.request(unknown=True)
        c = self.c
        self.assertEqual(c.router.apply_operator_decision(req)["status"], "applied")
        c.refused("authorize_dispatch", self.other, "dispatch_trial_stopped")
        self.assertEqual(json.loads(c.value("SELECT detail FROM audit_events WHERE kind='dispatch_result'"))["charge_minor_units"], 6)
