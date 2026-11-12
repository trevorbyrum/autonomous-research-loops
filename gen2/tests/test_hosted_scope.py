"""P1-1: scope content and exact subject come only from CLI/listener status; fixed refusals protect identity and stale subjects.

Oracle: independent read-only persisted records after the hosted decisions. No provider, Docker or native endpoint.
"""
import unittest
from unittest import mock

from gen2.app import cli
from gen2.core import canonical
from gen2.tests import operator_fixtures as of
from gen2.tests.offline_run import Offline, Operator
from gen2.tests.router_fixtures import TOPIC, RouterTestCase


class HostedScope(unittest.TestCase):
    def test_scope_readback_is_authenticated_exact_and_read_only_and_changed_subjects_refuse(self):
        run = Offline()
        self.addCleanup(run.close)
        run.intake()
        self.assertIsNone(run.topic()["scoping_report"])
        self.assertIn("scope_approval", run.walk(until="scope_approval"))
        before = run.records("audit_events")
        shown = run.topic()["scoping_report"]
        self.assertEqual(shown["content_hash"], canonical.content_hash(shown["document"]))
        self.assertTrue(shown["document"]["traditions"])
        self.assertEqual(run.records("audit_events"), before)
        path = "/v1/status?topic=" + TOPIC
        for token, code in ((None, 401), (of.EXPORTER_TOKEN, 403)):
            self.assertEqual(cli.request(run.environ["GEN2_OPERATOR_URL"], token, "GET", path)[0], code)
        subject = {"kind": "scoping_report", "ref": shown["report_id"], "revision": shown["version"], "hash": shown["content_hash"]}
        body = {"decision_id": "opd_scopewrong1", "topic_id": TOPIC, "kind": "scope_approval", "disposition": "approved", "subject": subject,
                "decided_at": "2026-11-12T00:00:00Z", "notes": None, "payload": None}
        for edit in ({"revision": shown["version"] + 1}, {"hash": "sha256:" + "0" * 64}, {"ref": "scope-missing"}):
            code, reply = run.cli(["call", "apply_operator_decision"], {**body, "subject": {**subject, **edit}})
            self.assertEqual((code, reply["status"], reply["reason"]), (1, "rejected", "decision_refused"))
        code, reply = run.cli(["call", "apply_operator_decision"], {**body, "operator_id": "spoofed"})
        self.assertEqual((code, reply["reason"]), (2, "authority_in_request"))
        # Version and confirm a new brief through the same listener, making the original report stale.
        brief = RouterTestCase.brief_document(TOPIC, 2, objective_in_operator_words="which sleep interventions improve attention")
        run.command("version_brief", {"document": brief, "owner_operator_id": "alice", "review_deadline": "2099-01-01T00:00:00Z"})
        run.decide("opd_briefnew01", "brief_confirmation", {"kind": "intake_brief", "ref": brief["brief_id"], "revision": 2, "hash": brief["content_hash"]})
        self.assertIn("scope_approval", run.walk(until="scope_approval"))
        current = run.topic()["scoping_report"]
        self.assertNotEqual((current["report_id"], current["version"]), (shown["report_id"], shown["version"]))
        code, reply = run.cli(["call", "apply_operator_decision"], body)
        self.assertEqual((code, reply["status"], reply["reason"]), (1, "rejected", "decision_refused"))
        self.assertEqual(run.topic()["scoping_report"], current)
        run.approve_scope()
        self.assertEqual(run.topic()["status"], "awaiting_contract_approval")
        self.assertEqual(run.records("operator_decisions")[-1]["operator_id"], "alice")

    def test_dedicated_interface_never_automatically_answers_a_scientific_wait(self):
        run = Operator({})   # no connection: this tests the endpoint's client policy only
        with mock.patch.object(run, "intake"), mock.patch.object(run, "tick", return_value={"status": "ok", "action": "wait", "command": "apply_operator_decision kind=scope_approval"}), \
             mock.patch.object(run, "approve_scope", side_effect=AssertionError("automatic native approval")):
            self.assertIn("scope_approval", run.walk())
        with self.assertRaisesRegex(AssertionError, "authorized staged sentinel"):
            run.approve_contract()
