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


class McpClient:
    def rpc(self, method: str, params: dict | None = None, *, token: str | None = of.OPERATOR_TOKEN, ident: object = 1) -> tuple[int, dict]:
        message = {"jsonrpc": "2.0", "method": method, **({} if params is None else {"params": params}), **({} if ident is None else {"id": ident})}
        code, reply, _ = self.http("POST", "/mcp", message, token=token)
        return code, reply

    def call(self, tool: str, arguments: dict, *, token: str = of.OPERATOR_TOKEN) -> tuple[bool, dict]:
        code, reply = self.rpc("tools/call", {"name": tool, "arguments": arguments}, token=token)
        self.assertEqual(code, 200, reply)
        result = reply["result"]
        return result["isError"], json.loads(result["content"][0]["text"])


class McpTest(McpClient, of.CommandWorld):
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
                ("another's secret as a tool name", "op-token-mallory-0123456789abcdef", {}, of.OPERATOR_TOKEN, "no_such_route"),
                ("the router's refusal", "request_cancel", {"invocation_id": of.FAILED, "reason": "stop"}, of.OPERATOR_TOKEN, "not_cancellable")):
            with self.subTest(label=label):
                failed, reply = self.call(tool, arguments, token=token)
                self.assertEqual((failed, reply.get("reason")), (True, reason))
        self.assertEqual(self.state(exclude=()), before)
        # an unknown tool's name is not logged — not a configured token, which redaction would also take out, nor any other text
        self.assertFalse([line for line in self.logs if any(token in line for token in (*of.TOKENS, "op-token-mallory-0123456789abcdef"))])
        self.assertIn("operator:alice POST /mcp:? -> 200 None", self.logs)
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


REFUSED = {"status": "refused", "reason": "request_invalid"}


def without(message: dict, key: str) -> dict:
    return {k: v for k, v in message.items() if k != key}


class McpEnvelopeTest(McpClient, of.CommandWorld):
    """The envelope is as strict as a command's body (Astra 1e review finding
    4): every malformed member is refused before anything is dispatched, with
    nothing written, and each HTTP negative has its MCP twin refused with the
    same reply. The message each negative changes is a tool call of
    request_cancel that is applied (the control, sent after)."""

    def valid(self, arguments=None, **params) -> dict:
        return {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {"name": "request_cancel", "arguments": self.bodies()["request_cancel"] if arguments is None else arguments, **params}}

    def mcp(self, message=None, *, raw: bytes | None = None, headers: dict | None = None) -> tuple[int, object]:
        code, reply, _ = self.http("POST", "/mcp", message, raw=raw, headers=headers)
        return code, reply

    def refusal(self, ident, code: int) -> dict:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": {-32600: "invalid request", -32602: "invalid params"}[code], "data": REFUSED}}

    def test_each_malformed_member_is_refused_before_dispatch(self) -> None:
        base = self.valid()
        params = base["params"]
        cases = (("jsonrpc absent", without(base, "jsonrpc"), -32600, 7), ("jsonrpc 1.0", {**base, "jsonrpc": "1.0"}, -32600, 7),
                 ("jsonrpc a number", {**base, "jsonrpc": 2.0}, -32600, 7), ("a member too many", {**base, "session": "x"}, -32600, 7),
                 ("method absent", without(base, "method"), -32600, 7), ("method not a string", {**base, "method": ["tools/call"]}, -32600, 7),
                 ("id an object", {**base, "id": {"n": 7}}, -32600, None), ("id a list", {**base, "id": [7]}, -32600, None),
                 ("id null", {**base, "id": None}, -32600, None), ("id a boolean", {**base, "id": True}, -32600, None),
                 ("id a float", {**base, "id": 7.5}, -32600, None), ("id empty", {**base, "id": ""}, -32600, None),
                 ("params a list", {**base, "params": [1]}, -32600, 7), ("params null", {**base, "params": None}, -32600, 7),
                 ("params absent", without(base, "params"), -32602, 7), ("params a member too many", {**base, "params": {**params, "extra": 1}}, -32602, 7),
                 ("tool name absent", {**base, "params": without(params, "name")}, -32602, 7),
                 ("tool name a list", {**base, "params": {**params, "name": ["request_cancel"]}}, -32602, 7),
                 ("arguments a list", self.valid([]), -32602, 7), ("arguments null", {**base, "params": {**params, "arguments": None}}, -32602, 7),
                 ("arguments a string", self.valid("stop"), -32602, 7),
                 ("a request without its id", without(base, "id"), -32600, None))
        before = self.state(exclude=())
        for label, message, code, ident in cases:
            with self.subTest(label=label):
                self.assertEqual(self.mcp(message), (400, self.refusal(ident, code)))
        self.assertEqual(self.state(exclude=()), before)
        code, reply = self.mcp(base)
        self.assertEqual((code, reply["id"], reply["result"]["isError"], json.loads(reply["result"]["content"][0]["text"])["status"]), (200, 7, False, "recorded"))

    def test_initialize_answers_a_version_it_supports(self) -> None:
        """The version asked for when the server supports it, its newest
        otherwise (never the request's text); a protocolVersion is required."""
        for asked, answered in (("2025-06-18", "2025-06-18"), ("2024-11-05", "2024-11-05"), ("1999-01-01", "2025-11-25"), (of.OPERATOR_TOKEN, "2025-11-25")):
            with self.subTest(asked=asked[:10]):
                code, reply = self.rpc("initialize", {"protocolVersion": asked, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
                self.assertEqual((code, reply["result"]["protocolVersion"]), (200, answered))
        self.assertEqual(self.mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}}), (400, self.refusal(1, -32602)))

    def test_notifications_are_checked_and_do_nothing(self) -> None:
        before = self.state(exclude=())
        for label, message in (("jsonrpc 1.0", {"jsonrpc": "1.0", "method": "notifications/initialized"}),
                               ("a member too many", {"jsonrpc": "2.0", "method": "notifications/initialized", "x": 1}),
                               ("params a list", {"jsonrpc": "2.0", "method": "notifications/initialized", "params": []}),
                               ("a tool call as a notification", without(self.valid(), "id"))):
            with self.subTest(label=label):
                self.assertEqual(self.mcp(message), (400, self.refusal(None, -32600)))
        for method in ("notifications/initialized", "notifications/cancelled"):
            self.assertEqual(self.mcp({"jsonrpc": "2.0", "method": method, "params": {}}), (202, {}))
        self.assertEqual(self.state(exclude=()), before)

    def test_each_http_negative_has_its_mcp_twin(self) -> None:
        """The same defect in a command's body and in a tool call's
        arguments: the same reply (the HTTP reply, and the MCP error's data or
        tool result), nothing written. Where the defect makes the whole
        message unparseable, both are the same plain refusal."""
        body = self.bodies()["request_cancel"]
        text = json.dumps(body)
        http_raw = lambda raw: self.http("POST", "/v1/commands/request_cancel", raw=raw)[:2]  # noqa: E731
        mcp_raw = lambda args: self.mcp(raw=b'{"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "request_cancel", "arguments": '  # noqa: E731
                                        + args + b"}}")
        before = self.state(exclude=())
        for label, http_side, mcp_side in (
                ("not an object: a list", http_raw(b"[]"), self.mcp(self.valid([]))),
                ("not an object: null", http_raw(b"null"), self.mcp({**self.valid(), "params": {"name": "request_cancel", "arguments": None}})),
                ("duplicate keys", http_raw(text[:-1].encode() + b', "reason": "again"}'), mcp_raw(text[:-1].encode() + b', "reason": "again"}')),
                ("a non-finite number", http_raw(text[:-1].encode() + b', "n": NaN}'), mcp_raw(text[:-1].encode() + b', "n": NaN}')),
                ("a field too many", self.command("request_cancel", {**body, "extra": 1}), self.mcp(self.valid({**body, "extra": 1}))),
                ("a field of the wrong type", self.command("request_cancel", {**body, "invocation_id": 5}), self.mcp(self.valid({**body, "invocation_id": 5}))),
                ("empty", self.command("request_cancel", {}), self.mcp(self.valid({}))),
                ("empty, as arguments omitted", self.command("request_cancel", {}), self.mcp({**self.valid(), "params": {"name": "request_cancel"}})),
                ("who acts named", self.command("request_cancel", {**body, "requested_by": "x"}), self.mcp(self.valid({**body, "requested_by": "x"}))),
                ("a capability", self.command("request_cancel", {**body, "capability_id": "cap_0123456789ab"}),
                 self.mcp(self.valid({**body, "capability_id": "cap_0123456789ab"}))),
                ("a declared length over the bound", http_raw_declared(self, "/v1/commands/request_cancel"), http_raw_declared(self, "/mcp")),
                ("no declared length", http_chunked(self, "/v1/commands/request_cancel"), http_chunked(self, "/mcp"))):
            with self.subTest(label=label):
                self.assertEqual(self.as_reply(mcp_side), self.as_reply(http_side))
                self.assertIn(http_side[0], (200, 400, 411, 413))
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.command("request_cancel", body)[1]["status"], "recorded")

    def test_status_arguments_are_as_strict_as_its_query(self) -> None:
        before = self.state(exclude=())
        for label, query, arguments in (("a topic twice", f"topic={OTHER}&topic={OTHER}", {"topic": [OTHER, OTHER]}), ("an unknown key", "x=1", {"x": 1}),
                                        ("a topic beside an unknown key", f"topic={OTHER}&x=1", {"topic": OTHER, "x": 1}),
                                        ("a topic not a string", "topic", {"topic": 5}), ("a topic not a topic", "topic=nope", {"topic": "nope"})):
            with self.subTest(label=label):
                code, reply, _ = self.http("GET", f"/v1/status?{query}")
                failed, tool_reply = self.call("status", arguments)
                self.assertEqual((failed, tool_reply), (True, reply))
                self.assertEqual(reply["reason"], "request_invalid")
                self.assertIn(code, (200, 400))
        self.assertEqual(self.state(exclude=()), before)
        omitted = self.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "status"}})[1]
        empty = self.call("status", {})[1]
        self.assertEqual([t["topic_id"] for t in json.loads(omitted["result"]["content"][0]["text"])["topics"]], [t["topic_id"] for t in empty["topics"]])
        self.assertEqual(self.call("status", {"topic": OTHER})[1]["topics"][0]["topic_id"], OTHER)

    @staticmethod
    def as_reply(answer: tuple[int, object]) -> object:
        """An answer's reply as the command path's: a tool result's carried
        reply, an MCP error's data (the command path's refusal), or the plain
        reply."""
        reply = answer[1]
        if isinstance(reply, dict) and "result" in reply:
            return json.loads(reply["result"]["content"][0]["text"])
        if isinstance(reply, dict) and "error" in reply:
            return reply["error"]["data"]
        return reply


def http_raw_declared(test, path: str) -> tuple[int, object]:
    """A body declared over the bound and never sent (refused unread)."""
    return _exchange(test, f"POST {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {of.OPERATOR_TOKEN}\r\nContent-Length: {1024 * 1024 + 1}\r\n\r\n")


def http_chunked(test, path: str) -> tuple[int, object]:
    """A body with no declared length (refused before a chunk is read)."""
    return _exchange(test, f"POST {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {of.OPERATOR_TOKEN}\r\nTransfer-Encoding: chunked\r\n\r\n")


def _exchange(test, request: str) -> tuple[int, object]:
    from gen2.tests.test_operator_auth import raw_exchange
    head, _, body = raw_exchange(test.engine, request.encode()).partition(b"\r\n\r\n")
    return int(head.split()[1]), json.loads(body)


if __name__ == "__main__":
    unittest.main()
