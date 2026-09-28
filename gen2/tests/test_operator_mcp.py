"""The MCP transport (task 1e; DEPLOYMENT-CONTRACT.md §1.1: stateless MCP over
HTTP, one JSON-RPC message per POST /mcp): the same token, the same checks
and the same command path as the HTTP routes, over real HTTP on loopback.
Each negative is paired with the call that is applied; read-backs are raw
SQL.
"""
from __future__ import annotations

import json
import unittest

from gen2.tests import operator_fixtures as of
from gen2.tests.router_fixtures import OTHER

OPERATOR_TOOLS = ["status", "apply_operator_decision", "request_cancel", "requeue", "close_brief", "activate_config_bundle", "version_brief",
                  "mark_brief_overdue", "propose_amendment", "recover_incident"]


class McpTest(of.CommandWorld):
    def rpc(self, method: str, params: dict | None = None, *, token: str | None = of.OPERATOR_TOKEN, ident: object = 1) -> tuple[int, dict]:
        message = {"jsonrpc": "2.0", "method": method, **({} if params is None else {"params": params}), **({} if ident is None else {"id": ident})}
        code, reply, _ = self.http("POST", "/mcp", message, token=token)
        return code, reply

    def call(self, tool: str, arguments: dict, *, token: str = of.OPERATOR_TOKEN) -> tuple[bool, dict]:
        code, reply = self.rpc("tools/call", {"name": tool, "arguments": arguments}, token=token)
        self.assertEqual(code, 200, reply)
        result = reply["result"]
        return result["isError"], json.loads(result["content"][0]["text"])

    def test_mcp_needs_a_token_and_lists_only_the_roles_tools(self) -> None:
        code, reply, _ = self.http("POST", "/mcp", raw=b"{not json", token=None)
        self.assertEqual((code, reply), (401, {"status": "refused", "reason": "unauthenticated"}))
        code, reply = self.rpc("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual((code, reply["result"]["serverInfo"]["name"], reply["result"]["protocolVersion"]), (200, "gen2-engine", "2024-11-05"))
        self.assertEqual([t["name"] for t in self.rpc("tools/list")[1]["result"]["tools"]], OPERATOR_TOOLS)
        self.assertEqual([t["name"] for t in self.rpc("tools/list", token=of.EXPORTER_TOKEN)[1]["result"]["tools"]], ["ack_delivery"])

    def test_a_tool_call_is_the_routes_own_command(self) -> None:
        bodies = self.bodies()
        before = self.state(exclude=())
        for label, tool, arguments, token, reason in (
                ("who acts named", "apply_operator_decision", {**bodies["apply_operator_decision"], "operator_id": "mallory"}, of.OTHER_OPERATOR_TOKEN, "authority_in_request"),
                ("the exporter's token", "request_cancel", bodies["request_cancel"], of.EXPORTER_TOKEN, "forbidden"),
                ("an operator's delivery", "ack_delivery", bodies["ack_delivery"], of.OPERATOR_TOKEN, "forbidden"),
                ("a capability-bearing call", "record_transition", {"capability_id": self.run_grant["capability_id"]}, of.OPERATOR_TOKEN, "no_such_route"),
                ("a token as a tool name", of.EXPORTER_TOKEN, {}, of.OPERATOR_TOKEN, "no_such_route"),
                ("the router's refusal", "request_cancel", {"invocation_id": of.FAILED, "reason": "stop"}, of.OPERATOR_TOKEN, "not_cancellable")):
            with self.subTest(label=label):
                failed, reply = self.call(tool, arguments, token=token)
                self.assertEqual((failed, reply.get("reason")), (True, reason))
        self.assertEqual(self.state(exclude=()), before)
        self.assertFalse([line for line in self.logs if any(token in line for token in of.TOKENS)])  # an unknown tool's name is not logged
        failed, reply = self.call("apply_operator_decision", bodies["apply_operator_decision"], token=of.OTHER_OPERATOR_TOKEN)
        self.assertEqual((failed, reply["status"]), (False, "applied"))
        self.assertEqual(self.rows("SELECT operator_id FROM operator_decisions WHERE decision_id = 'opd_brief_other'"), [("bob",)])
        self.assertEqual(self.call("ack_delivery", bodies["ack_delivery"], token=of.EXPORTER_TOKEN)[1]["status"], "recorded")

    def test_status_is_a_tool_of_the_operators(self) -> None:
        failed, reply = self.call("status", {"topic": OTHER})
        self.assertEqual((failed, [t["topic_id"] for t in reply["topics"]]), (False, [OTHER]))
        self.assertEqual(reply["topics"][0]["waiting"][0]["reason"], "brief_confirmation")
        self.assertEqual(self.call("status", {}, token=of.EXPORTER_TOKEN), (True, {"status": "refused", "reason": "forbidden"}))

    def test_an_unknown_method_is_an_error_and_a_notification_has_no_answer(self) -> None:
        code, reply = self.rpc("resources/list")
        self.assertEqual((code, reply["error"]["code"]), (200, -32601))
        self.assertEqual(self.rpc("notifications/initialized", ident=None), (202, {}))


if __name__ == "__main__":
    unittest.main()
