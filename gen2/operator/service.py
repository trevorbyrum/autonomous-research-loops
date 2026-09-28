"""The operator command service (task 1e): one service behind the engine's
listener and the CLI.

Trace: design review §10 ("CLI/MCP/API operations behind one command
service"); BOUNDARIES.md Operator (the human authority; interface
guarantees: typed holds with owners and deadlines, status that answers why
every waiting item waits, dated capability facts) and Router (the single
writer; never accepts a caller-supplied role label); DEPLOYMENT-CONTRACT.md
§1.1–1.2 (bearer auth on every route but GET /v1/health; the exporter's token
is accepted only for its own calls, never as operator authority; health
leaks no state); INVARIANTS C-1, G-4, G-13, H-2, H-3, RG-9; the carried
obligations: 1b (authenticate principals; authorize privileged commands as
well as capability-bearing calls), 1c (the operator cancel command,
authenticated; the collected-end incident in status), 1d (authenticated brief
closure; the versioning and config-bundle operations; status for re-queues,
reservations and holds).

What it is: a function from one HTTP request — method, target, the
Authorization header, the body's declared length and a reader for the body —
to one answer, a status code and a JSON document. The transport
(gen2/app/engine.py) only moves bytes; the CLI (gen2/app/cli.py) is a client
of the same routes. Every command is one of the router's existing operations,
called on the backend the composition root hands over
(core.control.OperatorBackend); this module holds no store, imports no
router and has no write path of its own (gen2/boundaries.toml: operator
imports core only and is granted no capability).

Routes: GET /v1/health; GET /v1/status[?topic=<topic_id>]; POST
/v1/commands/<operation>, where <operation> is the router operation's own
name (COMMANDS); POST /mcp, stateless MCP over HTTP whose tools are the same
status and commands (_mcp). Checks, in order — a missing or invalid token is
refused before anything but the route is read:
  1. GET /v1/health needs no token and answers {"status": "ok"}, or 503
     {"status": "unavailable"}: nothing else (no state leak).
  2. The bearer token names a principal (auth.py), or 401. The body is not
     read, whatever it declares.
  3. The route is a command or status (404 otherwise), and the principal's
     role is the one it needs (403 otherwise): status and every command but
     one need the operator; ack_delivery needs the exporter. (Over MCP the
     tool is named in the body, so this is checked once it is parsed.)
  4. The body: a declared length (411 without one, 413 over MAX_BODY), strict
     JSON (C-13: duplicate keys and non-finite numbers refused) holding an
     object (400 otherwise).
  5. Authority is the principal's, never the request's: the fields that name
     who acts (a decision's operator_id, the requester of a cancellation or
     re-queue, a brief closure's closed_by) and capability_id are refused if
     the body names them (400 authority_in_request), and the first three are
     then set from the principal.
  6. The router's operation answers (200): its reply is the answer, whatever
     it decided — its `status` says what happened, a refusal included.

Capability-bearing calls (claim, record_transition, record_observation,
commit_outcome, reconcile, invocation_status, a supervisor's cancellation)
are not routes of this surface. The supervisor makes them in the engine's
own process under the invocation's capability, and no principal the
deployment contract defines holds invocation authority: so an operator's
token cannot drive an invocation, and a capability, which is never a bearer
token here nor accepted in a command body, cannot issue an operator command.
A principal or a capability never substitutes for the other. (Phase 3's
exporter, which will run under an invocation, adds its capability-bearing
calls needing both its token and that capability.)

Every request is logged as one line — principal, method, route, HTTP status
and the reply's status — and nothing else: never a header, a token or a
body.
"""
from __future__ import annotations

import json
import re
from typing import Callable
from urllib.parse import parse_qs

from gen2.core import canonical
from gen2.operator import status as status_view
from gen2.operator.auth import Credentials, Principal

MAX_BODY = 1024 * 1024
LENGTH = re.compile(r"[0-9]{1,12}")
COMMAND_PREFIX = "/v1/commands/"
_NAME = lambda principal: principal.name  # noqa: E731
_OPERATOR = lambda principal: "operator"  # noqa: E731
# route name (the router operation called) -> (the role it needs, the fields the principal supplies)
COMMANDS: dict[str, tuple[str, dict[str, Callable[[Principal], str]]]] = {
    "apply_operator_decision": ("operator", {"operator_id": _NAME}),
    "request_cancel": ("operator", {"requested_by": _OPERATOR}),
    "requeue": ("operator", {"requested_by": _OPERATOR}),
    "close_brief": ("operator", {"closed_by": _NAME}),
    "activate_config_bundle": ("operator", {}),
    "version_brief": ("operator", {}),
    "mark_brief_overdue": ("operator", {}),
    "propose_amendment": ("operator", {}),
    "ack_delivery": ("exporter", {}),
}


class OperatorService:
    def __init__(self, backend, credentials: Credentials, *, incidents: Callable[[], list[dict]] = lambda: [],
                 log: Callable[[str], None] = lambda line: None) -> None:
        self._backend = backend
        self._credentials = credentials
        self._incidents = incidents
        self._log = log

    def handle(self, method: str, target: str, authorization: str | None, length: str | None, read: Callable[[int], bytes]) -> tuple[int, dict]:
        path, _, query = target.partition("?")
        if path == "/v1/health":
            if method != "GET":
                return 405, {"status": "refused", "reason": "method_not_allowed"}
            try:
                healthy = self._backend.healthy()
            except Exception:  # the router did not answer: unavailable, never an error page
                healthy = False
            return (200, {"status": "ok"}) if healthy else (503, {"status": "unavailable"})
        principal = self._credentials.authenticate(authorization)
        if principal is None:
            return self._answer(None, method, path, 401, {"status": "refused", "reason": "unauthenticated"})
        if path == "/v1/status" and method == "GET":
            topics = parse_qs(query).get("topic", [])
            return self._answer(principal, method, path, *self._status(principal, topics[0] if topics else None))
        if path == "/mcp" and method == "POST":
            body, error = self._body(length, read)
            if error is not None:
                return self._answer(principal, method, path, error[0], {"status": "refused", "reason": error[1]})
            code, reply, route = self._mcp(principal, body)
            return self._answer(principal, method, route, code, reply)
        name = path[len(COMMAND_PREFIX):] if path.startswith(COMMAND_PREFIX) and method == "POST" else None
        if name not in COMMANDS:
            return self._answer(principal, method, path, 404, {"status": "refused", "reason": "no_such_route"})
        if principal.role != COMMANDS[name][0]:
            return self._answer(principal, method, path, 403, {"status": "refused", "reason": "forbidden"})
        body, error = self._body(length, read)
        if error is not None:
            return self._answer(principal, method, path, error[0], {"status": "refused", "reason": error[1]})
        return self._answer(principal, method, path, *self._command(principal, name, body))

    def _status(self, principal: Principal, topic: str | None) -> tuple[int, dict]:
        if principal.role != "operator":
            return 403, {"status": "refused", "reason": "forbidden"}
        facts = self._backend.status({} if topic is None else {"topic_id": topic})
        return 200, status_view.compose(facts, self._incidents()) if facts.get("status") == "ok" else facts

    def _command(self, principal: Principal, name: str, body: dict) -> tuple[int, dict]:
        """One command, the same for every transport: the role it needs, who
        acts from the principal, then the router's operation."""
        role, supplied = COMMANDS[name]
        if principal.role != role:
            return 403, {"status": "refused", "reason": "forbidden"}
        named = sorted(field for field in (*supplied, "capability_id") if field in body)
        if named:
            return 400, {"status": "refused", "reason": "authority_in_request",
                         "detail": f"{', '.join(named)}: who acts is the authenticated principal, never the request"}
        request = {**body, **{field: value(principal) for field, value in supplied.items()}}
        return 200, getattr(self._backend, name)(request)

    def _mcp(self, principal: Principal, message: dict) -> tuple[int, dict, str]:
        """Stateless MCP over HTTP (DEPLOYMENT-CONTRACT.md §1.1: one JSON-RPC
        message per request, the gateway's shape): tools/list names the tools
        the principal's role may call; tools/call runs the same _status and
        _command as the routes, so MCP is a transport, not a second path. A
        refusal, at any step, is an in-band tool error carrying its reply."""
        method, params = message.get("method"), message.get("params") or {}
        if "id" not in message:
            return 202, {}, "/mcp"  # a notification: nothing to answer
        answer = lambda result: {"jsonrpc": "2.0", "id": message["id"], "result": result}  # noqa: E731
        if method == "initialize":
            return 200, answer({"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                                "serverInfo": {"name": "gen2-engine", "version": "1e"}}), "/mcp"
        if method == "ping":
            return 200, answer({}), "/mcp"
        if method == "tools/list":
            names = ["status"] * (principal.role == "operator") + [name for name, (role, _) in COMMANDS.items() if role == principal.role]
            return 200, answer({"tools": [{"name": name, "description": f"POST /v1/commands/{name}" if name in COMMANDS else "GET /v1/status",
                                           "inputSchema": {"type": "object"}} for name in names]}), "/mcp"
        if method == "tools/call":
            tool, arguments = params.get("name"), params.get("arguments") or {}
            if not isinstance(arguments, dict):
                code, reply = 400, {"status": "refused", "reason": "request_invalid"}
            elif tool == "status":
                code, reply = self._status(principal, arguments.get("topic"))
            elif tool in COMMANDS:
                code, reply = self._command(principal, tool, arguments)
            else:
                code, reply = 404, {"status": "refused", "reason": "no_such_route"}
            failed = code != 200 or reply.get("status") in ("refused", "rejected")
            return 200, answer({"content": [{"type": "text", "text": json.dumps(reply, sort_keys=True)}], "isError": failed}), f"/mcp:{tool}"
        return 200, {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "method not found"}}, "/mcp"

    def _body(self, length: str | None, read: Callable[[int], bytes]) -> tuple[dict | None, tuple[int, str] | None]:
        if length is None:
            return None, (411, "length_required")
        if not LENGTH.fullmatch(length):
            return None, (400, "request_invalid")
        if int(length) > MAX_BODY:
            return None, (413, "body_too_large")
        try:
            body = canonical.parse_json_strict(read(int(length)))
        except (ValueError, TypeError):  # CanonicalizationError is a ValueError
            return None, (400, "request_invalid")
        return (body, None) if isinstance(body, dict) else (None, (400, "request_invalid"))

    def _answer(self, principal: Principal | None, method: str, path: str, code: int, reply: dict) -> tuple[int, dict]:
        who = "-" if principal is None else f"{principal.role}:{principal.name}"
        outcome = reply.get("status") if isinstance(reply, dict) else None
        self._log(f"{who} {method} {path} -> {code} {outcome}")
        return code, reply
