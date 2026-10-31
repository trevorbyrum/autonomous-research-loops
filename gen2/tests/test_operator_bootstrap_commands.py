"""Four bootstrap rows over real REST/MCP, with durable refusal oracles."""
import copy
import json

from gen2.tests import operator_fixtures as of
from gen2.tests import router_fixtures as rf


class BootstrapCommands(of.OperatorTestCase):
    def invoke(self, transport, name, body, token=of.OPERATOR_TOKEN):
        if transport in ("REST",):
            return self.command(name, body, token=token)
        code, reply, _ = self.http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": body}}, token=token)
        if code in (401,):
            return code, reply
        self.assertEqual(code, 200, reply)
        result = reply["result"]
        parsed = json.loads(result["content"][0]["text"])
        self.assertEqual(result["isError"], parsed.get("status") in ("refused", "rejected"))
        return code, parsed

    def refuses(self, transport, name, body, reason, token=of.OPERATOR_TOKEN, code=200):
        before = self.state(exclude=())
        status, reply = self.invoke(transport, name, body, token)
        self.assertEqual((status, reply.get("status"), reply.get("reason")), (code, "refused", reason), name)
        self.assertEqual(self.state(exclude=()), before, name)

    def guarded(self, transport, name, body):
        forbidden = {"REST": 403, "MCP": 200}[transport]
        self.refuses(transport, name, body, "forbidden", of.EXPORTER_TOKEN, forbidden)
        self.refuses(transport, name, body, "unauthenticated", None, 401)
        self.refuses(transport, name, {**body, "capability_id": "cap_bootstrap0001"}, "authority_in_request",
                     code={"REST": 400, "MCP": 200}[transport])

    def test_literal_bootstrap_for_each_transport(self):
        for transport, tid, eid in (("REST", "fleet-a:bootstrap01", "rev_bootstrap01"), ("MCP", "fleet-a:bootstrap02", "rev_bootstrap02")):
            with self.subTest(transport=transport):
                topic = {"topic_id": tid, "priority": 3}
                self.guarded(transport, "create_topic", topic)
                self.refuses(transport, "create_topic", {**topic, "priority": -1}, "request_invalid")
                self.assertEqual(self.invoke(transport, "create_topic", topic), (200, {"status": "created", "topic_id": tid}))
                self.refuses(transport, "create_topic", {**topic, "priority": 4}, "topic_conflict")
                self.assertEqual(self.rows("SELECT priority, status, state_revision FROM queue_entries WHERE topic_id = ?", tid),
                                 [(3, "awaiting_brief_confirmation", 0)])
                doc = self.brief_document(tid)
                brief = {"document": doc, "owner_operator_id": "bob", "review_deadline": rf.REVIEW_BY}
                self.guarded(transport, "open_brief", brief)
                bad = copy.deepcopy(brief)
                bad["document"]["content_hash"] = rf.h("0")
                self.refuses(transport, "open_brief", bad, "request_invalid")
                self.assertEqual(self.invoke(transport, "open_brief", brief), (200,
                    {"status": "recorded", "topic_id": tid, "brief_id": "brief-1", "version": 1, "superseded": None}))
                self.assertEqual(self.rows("SELECT owner_operator_id, status, version FROM intake_briefs WHERE topic_id = ?", tid),
                                 [("bob", "awaiting_confirmation", 1)])  # Alice acts; Bob owns the assignment.
                self.refuses(transport, "open_brief", {**brief, "owner_operator_id": "alice"}, "brief_version_conflict")
                draft = {"document": rf.contract(1, None, topic=tid, rated=False)}
                self.guarded(transport, "draft_contract", draft)
                self.refuses(transport, "draft_contract", draft, "brief_unconfirmed")
                decision = self.decision(f"opd_brief{tid[-2:]}01", "brief_confirmation",
                    {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": doc["content_hash"]}, tid)
                self.assertEqual(self.command("apply_operator_decision", decision)[1]["status"], "applied")
                self.assertEqual(self.invoke(transport, "draft_contract", draft), (200,
                    {"status": "recorded", "topic_id": tid, "revision": 1, "against_approved": None}))
                self.assertEqual(self.rows("SELECT revision, status FROM contract_revisions WHERE topic_id = ?", tid), [(1, "draft")])
                review = {"episode_id": eid, "topic_id": tid, "kind": "fixed_cadence"}
                self.guarded(transport, "open_review", review)
                self.refuses(transport, "open_review", {**review, "kind": "method_fit"}, "no_pending_signal")
                self.assertEqual(self.invoke(transport, "open_review", review), (200, {"status": "opened", "episode_id": eid, "triggers": []}))
                self.assertEqual(self.rows("SELECT kind, topic_id FROM review_episodes WHERE episode_id = ?", eid), [("fixed_cadence", tid)])
                self.assertEqual(self.rows("SELECT * FROM scoping_reports WHERE topic_id = ?", tid), [])
                scope = self.decision(f"opd_scope{tid[-2:]}01", "scope_approval",
                    {"kind": "scoping_report", "ref": "scp_missing0001", "revision": 1, "hash": rf.h("0")}, tid)
                before = self.state(exclude=())
                code, refusal = self.invoke(transport, "apply_operator_decision", scope)
                self.assertEqual((code, refusal["status"], refusal["reason"]), (200, "rejected", "decision_refused"))
                self.assertEqual(self.state(exclude=()), before)  # C-12 remains closed.

    def test_no_dispatch_result_or_report_submission_surface(self):
        for transport in ("REST", "MCP"):
            for name in ("authorize_dispatch", "record_dispatch_result", "record_dossier", "commit_outcome"):
                self.refuses(transport, name, {}, "no_such_route", code={"REST": 404, "MCP": 200}[transport])
