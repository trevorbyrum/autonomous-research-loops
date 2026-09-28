"""Each operator command, applied and refused, over HTTP against a real store
(task 1e). The command is the router's own operation: what these tests show
is that the surface reaches it, with who acts supplied from the token, and
that its refusal comes back unchanged and writes nothing. What the router's
own rules are (G-13 subject binding, L-4 episode holds, G-4 closure, L-6
re-queues, P-2 watermarks) is its suites'; each is exercised here once, on
the path through the surface. Read-backs are raw SQL.
"""
from __future__ import annotations

import unittest

from gen2.tests import operator_fixtures as of
from gen2.tests import router_fixtures as rf
from gen2.tests.router_fixtures import OTHER, TOPIC


class DecisionCommandTest(of.CommandWorld):
    def test_a_decision_is_applied_under_the_principal_and_replays(self) -> None:
        body = self.bodies()["apply_operator_decision"]
        code, reply = self.command("apply_operator_decision", body)
        self.assertEqual((code, reply["status"], reply["effects"]["queue_transition"]), (200, "applied", {"from": "awaiting_brief_confirmation", "to": "scoping"}))
        self.assertEqual(self.rows("SELECT operator_id, kind, disposition, subject_ref, subject_revision FROM operator_decisions WHERE decision_id = 'opd_brief_other'"),
                         [("alice", "brief_confirmation", "approved", "brief-1", 1)])
        self.assertEqual((self.status(OTHER), self.value("SELECT status FROM intake_briefs WHERE topic_id = ? AND version = 1 AND brief_id = 'brief-1'", OTHER)),
                         ("scoping", "confirmed"))
        before = self.state(exclude=())
        self.assertEqual(self.command("apply_operator_decision", body)[1]["status"], "replayed")
        code, reply = self.command("apply_operator_decision", body, token=of.OTHER_OPERATOR_TOKEN)  # the same id from another operator is other content
        self.assertEqual((code, reply["status"], reply["reason"]), (200, "rejected", "decision_id_conflict"))
        self.assertEqual(self.state(exclude=()), before)

    def test_a_decision_the_router_refuses_writes_nothing(self) -> None:
        body = self.bodies()["apply_operator_decision"]
        before = self.state(exclude=())
        code, reply = self.command("apply_operator_decision", {**body, "subject": {**body["subject"], "hash": rf.h("0")}})
        self.assertEqual((code, reply["status"], reply["reason"]), (200, "rejected", "decision_refused"))
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.command("apply_operator_decision", body)[1]["status"], "applied")


class HoldCommandTest(of.CommandWorld):
    def clearance(self, hold_id: str, did: str) -> dict:
        return self.decision(did, "hold_clearance", {"kind": "hold", "ref": hold_id})

    def test_an_operator_hold_is_cleared_by_its_decision(self) -> None:
        self.hold(self.checkpoint, "hold_judgment01")
        code, reply = self.command("apply_operator_decision", self.clearance("hold_judgment01", "opd_clear0001"))
        self.assertEqual((code, reply["status"], reply["effects"]), (200, "applied", {"hold_cleared": "hold_judgment01"}))
        self.assertEqual(self.rows("SELECT cleared_by_decision_id FROM holds WHERE hold_id = 'hold_judgment01'"), [("opd_clear0001",)])

    def test_an_episode_hold_clears_only_through_its_reconciliation(self) -> None:
        grant = self.started("inv_unknown0001", kind="verification")
        out = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"],
                                             "to_state": "outcome_unknown", "unknown_episode": 1, "unknown_cause": "contact_lost"})
        self.assertEqual(out["status"], "recorded")
        hold = self.value("SELECT hold_id FROM holds WHERE subject_ref = 'invocation:inv_unknown0001#unknown:1'")
        before = self.state(exclude=())
        code, reply = self.command("apply_operator_decision", self.clearance(hold, "opd_clear0002"))
        self.assertEqual((code, reply["status"], reply["reason"]), (200, "rejected", "decision_refused"))
        self.assertEqual(self.state(exclude=()), before)


class CancelCommandTest(of.CommandWorld):
    def test_running_work_is_marked_and_admitted_work_cancelled(self) -> None:
        code, reply = self.command("request_cancel", self.bodies()["request_cancel"])
        self.assertEqual((code, reply), (200, {"status": "recorded", "invocation_id": of.RUNNING, "state": "running"}))
        self.assertEqual(self.rows("SELECT state, cancel_requested_by FROM invocations WHERE invocation_id = ?", of.RUNNING), [("running", "operator")])
        self.assertEqual(self.command("request_cancel", self.bodies()["request_cancel"])[1]["status"], "replayed")
        self.assertEqual(self.claim("inv_admitted001", kind="verification")["status"], "granted")
        code, reply = self.command("request_cancel", {"invocation_id": "inv_admitted001", "reason": "not needed"})
        self.assertEqual((code, reply["status"], reply["state"]), (200, "cancelled", "cancelled"))
        self.assertEqual(self.rows("SELECT i.state, l.release_reason FROM invocations i JOIN leases l USING (lease_id) WHERE invocation_id = 'inv_admitted001'"),
                         [("cancelled", "cancelled")])

    def test_ended_work_and_a_supervisors_request_are_refused(self) -> None:
        own = self.router.request_cancel({"invocation_id": of.RUNNING, "requested_by": "supervisor", "reason": "deadline",
                                          "capability_id": self.run_grant["capability_id"]})
        self.assertEqual(own["status"], "recorded")
        before = self.state(exclude=())
        for invocation, reason in ((of.FAILED, "not_cancellable"), (of.RUNNING, "cancel_conflict"), ("inv_nosuch00001", "unknown_invocation")):
            with self.subTest(invocation=invocation):
                code, reply = self.command("request_cancel", {"invocation_id": invocation, "reason": "stop"})
                self.assertEqual((code, reply["status"], reply["reason"]), (200, "refused", reason))
        self.assertEqual(self.state(exclude=()), before)


class ConfigBundleCommandTest(of.CommandWorld):
    def test_a_bundle_is_activated_and_running_work_keeps_its_pin(self) -> None:
        code, reply = self.command("activate_config_bundle", self.bodies()["activate_config_bundle"])
        self.assertEqual((code, reply["status"], reply["version"], reply["superseded"]), (200, "activated", 2, rf.CONFIG))
        self.assertEqual(self.rows("SELECT version, status FROM config_bundles ORDER BY version"), [(1, "superseded"), (2, "active")])
        self.assertEqual(self.value("SELECT config_bundle_hash FROM invocations WHERE invocation_id = ?", of.RUNNING), rf.CONFIG)

    def test_a_refused_bundle_leaves_the_active_one_with_a_dated_fact(self) -> None:
        code, reply = self.command("activate_config_bundle", {**rf.BUNDLE, "version": 2, "policy": {"router": {"hold_window_s": -1}}})
        self.assertEqual((code, reply["status"]), (200, "refused"))
        self.assertEqual(self.rows("SELECT version, status FROM config_bundles"), [(1, "active")])
        self.assertEqual(self.rows("SELECT state FROM capability_facts WHERE capability = 'config-bundle' AND superseded_by_fact_id IS NULL"), [("failing",)])


class BriefCommandTest(of.CommandWorld):
    def key(self, tid: str, brief: str, version: int) -> tuple:
        return self.rows("SELECT status, closed_by, close_reason, overdue_since IS NOT NULL FROM intake_briefs WHERE topic_id = ? AND brief_id = ? AND version = ?",
                         tid, brief, version)[0]

    def test_a_brief_is_versioned_marked_overdue_cancelled_and_archived(self) -> None:
        self.assertEqual(self.command("version_brief", self.bodies()["version_brief"])[1]["status"], "recorded")
        self.assertEqual(self.rows("SELECT version, status, owner_operator_id FROM intake_briefs WHERE topic_id = ? AND brief_id = 'brief-1' ORDER BY version", OTHER),
                         [(1, "superseded", "user"), (2, "awaiting_confirmation", "bob")])
        self.assertEqual(self.command("mark_brief_overdue", self.bodies()["mark_brief_overdue"])[1]["status"], "marked")
        self.assertEqual(self.key(OTHER, "brief-2", 1), ("awaiting_confirmation", None, None, 1))
        code, reply = self.command("close_brief", {"topic_id": OTHER, "brief_id": "brief-2", "version": 1, "closure": "cancelled", "reason": "a duplicate"})
        self.assertEqual((code, reply["status"], reply["closure"]), (200, "closed", "cancelled"))
        self.assertEqual(self.key(OTHER, "brief-2", 1), ("cancelled", "alice", "a duplicate", 1))
        self.assertEqual(self.command("close_brief", self.bodies()["close_brief"], token=of.OTHER_OPERATOR_TOKEN)[1]["status"], "closed")
        self.assertEqual(self.key(TOPIC, "brief-1", 1), ("archived", "bob", "the contract is approved", 0))

    def test_a_closure_is_explicit_and_written_once(self) -> None:
        """Cancellation of a confirmed version, archival of one awaiting
        confirmation, either of a superseded or an unknown version: refused,
        nothing written (the valid archival, the control, then closes it).
        Then the identical closure replays, and another one — another reason,
        or another operator — is a conflict, nothing written."""
        archive = self.bodies()["close_brief"]
        self.assertEqual(self.command("version_brief", self.bodies()["version_brief"])[1]["status"], "recorded")  # supersedes OTHER's brief-1 v1
        before = self.state(exclude=())
        for label, body, reason in (
                ("cancel confirmed", {**archive, "closure": "cancelled"}, "brief_not_closable"),
                ("archive awaiting", {"topic_id": OTHER, "brief_id": "brief-2", "version": 1, "closure": "archived", "reason": "x"}, "brief_not_closable"),
                ("cancel superseded", {**archive, "topic_id": OTHER, "closure": "cancelled"}, "brief_not_closable"),
                ("archive superseded", {**archive, "topic_id": OTHER}, "brief_not_closable"),
                ("unknown", {**archive, "version": 9}, "unknown_brief")):
            with self.subTest(label=label):
                code, reply = self.command("close_brief", body)
                self.assertEqual((code, reply["status"], reply["reason"]), (200, "refused", reason))
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.command("close_brief", archive)[1]["status"], "closed")
        before = self.state(exclude=())
        self.assertEqual(self.command("close_brief", archive)[1]["status"], "replayed")
        for label, body, token in (("another reason", {**archive, "reason": "another reason"}, of.OPERATOR_TOKEN),
                                   ("another operator", archive, of.OTHER_OPERATOR_TOKEN)):
            with self.subTest(label=label):
                code, reply = self.command("close_brief", body, token=token)
                self.assertEqual((code, reply["status"], reply["reason"]), (200, "refused", "brief_close_conflict"))
        self.assertEqual(self.state(exclude=()), before)

    def test_a_version_or_marking_the_router_refuses_writes_nothing(self) -> None:
        before = self.state(exclude=())
        for operation, body, reason in (("version_brief", {**self.bodies()["version_brief"], "document": self.brief_document(OTHER, 3)}, "request_invalid"),
                                        ("mark_brief_overdue", {"topic_id": OTHER, "brief_id": "brief-1", "version": 1}, "not_overdue")):
            with self.subTest(operation=operation):
                code, reply = self.command(operation, body)
                self.assertEqual((code, reply["status"], reply["reason"]), (200, "refused", reason))
        self.assertEqual(self.state(exclude=()), before)


class AmendmentCommandTest(of.CommandWorld):
    def test_an_amendment_is_proposed_then_approved_by_decision(self) -> None:
        doc = self.bodies()["propose_amendment"]["document"]
        code, reply = self.command("propose_amendment", {"document": doc})
        self.assertEqual((code, reply["status"], reply["against_approved"]), (200, "recorded", "compatible"))
        code, reply = self.command("apply_operator_decision", self.decision("opd_amend0003", "amendment_approval",
                                                                            {"kind": "contract_revision", "revision": 3, "hash": doc["content_hash"]}))
        self.assertEqual((code, reply["status"]), (200, "applied"))
        self.assertEqual(self.rows("SELECT revision, status FROM contract_revisions WHERE topic_id = ? AND revision >= 2 ORDER BY revision", TOPIC),
                         [(2, "superseded"), (3, "approved")])
        self.assertEqual(self.rows("SELECT classification FROM amendment_impacts WHERE decision_id = 'opd_amend0003'"), [("compatible",)])

    def test_an_amendment_the_router_refuses_writes_nothing(self) -> None:
        before = self.state(exclude=())
        code, reply = self.command("propose_amendment", {"document": self.amend.contract_doc(5, 2, edit=self.amend.compatible)})
        self.assertEqual((code, reply["status"], reply["reason"]), (200, "refused", "request_invalid"))
        self.assertEqual(self.state(exclude=()), before)


class RequeueCommandTest(of.CommandWorld):
    def test_failed_work_is_requeued_by_the_operator(self) -> None:
        code, reply = self.command("requeue", self.bodies()["requeue"])
        self.assertEqual((code, reply), (200, {"status": "requeued", "invocation_id": of.FAILED, "attempt": 2}))
        self.assertEqual(self.rows("SELECT attempt, requested_by, reason FROM retries WHERE invocation_id = ?", of.FAILED),
                         [(2, "operator", "diagnosed: a transient fault")])
        self.assertEqual(self.command("requeue", self.bodies()["requeue"])[1]["status"], "replayed")

    def test_work_that_has_not_ended_is_not_requeued(self) -> None:
        before = self.state(exclude=())
        code, reply = self.command("requeue", {"invocation_id": of.RUNNING, "reason": "again"})
        self.assertEqual((code, reply["status"], reply["reason"]), (200, "refused", "not_requeueable"))
        self.assertEqual(self.state(exclude=()), before)


class DeliveryCommandTest(of.CommandWorld):
    def test_the_exporter_acknowledges_a_delivery(self) -> None:
        code, reply = self.command("ack_delivery", self.bodies()["ack_delivery"], token=of.EXPORTER_TOKEN)
        self.assertEqual((code, reply), (200, {"status": "recorded", "export_receipt_id": "exr_000000000001"}))
        self.assertEqual(self.rows("SELECT generation, options_revision FROM connector_watermarks WHERE topic_id = ? AND connector_id = 'warehouse'", TOPIC), [(1, 1)])

    def test_a_receipt_of_no_manifest_writes_nothing(self) -> None:
        before = self.state(exclude=())
        code, reply = self.command("ack_delivery", {**self.bodies()["ack_delivery"], "manifest_id": "man_nosuch0001"}, token=of.EXPORTER_TOKEN)
        self.assertEqual((code, reply["status"], reply["reason"]), (200, "rejected", "unknown_manifest"))
        self.assertEqual(self.state(exclude=()), before)


if __name__ == "__main__":
    unittest.main()
