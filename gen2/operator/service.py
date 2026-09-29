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
(core.control.OperatorBackend) — but two, the station's: recover_incident,
the recovery of a job stalled on an incident (task 1e-repair; Supervisor.
recover_incident), which reaches the router only through the invocation's own
capability-bearing operations; and probe_capability, a probe of one
provider's auth home with its pinned runner (task 1f; gen2/supervisor/
probe.py), whose observation the router records. This module holds no store, imports no router
and has no write path of its own (gen2/boundaries.toml: operator imports core
only and is granted no capability).

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
     object (400 otherwise). Status's query is no query or exactly one topic
     (400 otherwise); over MCP, the whole envelope first (_mcp).
  5. Authority is the principal's, never the request's: the fields that name
     who acts (a decision's operator_id, the requester of a cancellation,
     re-queue or recovery, a brief closure's closed_by) and capability_id are
     refused if the body names them (400 authority_in_request), and the
     others are then set from the principal.
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
and the reply's status — and nothing else: never a header, a token, a query
or a body. The method and route are the service's own labels (label()): a
route it serves by its name, anything else "?" — never the request's own
text, which may carry a credential (Astra 1e review finding 3). And every
reply and log line passes through Credentials.redact() before it leaves, so
no configured token a request carries — in its path, its query or its body,
echoed by a refusal — is written back or logged; a tool's reply over MCP
passes through it before it is nested as text, and an MCP id carrying one is
refused (_mcp; Astra 1e-repair re-review finding 2). Serialization can
re-form a token no value holds, so each JSON text is checked as the text it
is — a tool's nested text as it is nested (_mcp), every answer as the
transport writes it (encode()) — and an id whose answer would be written
with one is refused before anything is dispatched (Credentials.dumps and
writes; Astra 1e-repair-2 re-review finding 1). No later pass changes what an
earlier one let through: an id taken is echoed as it came, and a tool's text
stays the JSON it was nested as, or the answer is the fixed fault (_mcp;
Astra 1e-repair-3 re-review finding 1).
"""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import parse_qs

from gen2.core import canonical
from gen2.operator import status as status_view
from gen2.operator.auth import Credentials, Principal, Unwritable

MAX_BODY = 1024 * 1024
LENGTH = re.compile(r"[0-9]{1,12}")
COMMAND_PREFIX = "/v1/commands/"
ROUTES = ("/v1/health", "/v1/status", "/mcp")
METHODS = ("GET", "POST")
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
    "recover_incident": ("operator", {"requested_by": _NAME}),  # the station's (core.control.OperatorBackend), not the router's
    "probe_capability": ("operator", {"requested_by": _NAME}),  # the station's too (task 1f)
    "ack_delivery": ("exporter", {}),
}


def label(method: str, target: str) -> tuple[str, str]:
    """What a log line may say of a request: its method and its route as the
    service names them, "?" for any it does not serve — never the request's
    own text (the engine's diagnostics use it too)."""
    route = target.partition("?")[0]
    if route.startswith(COMMAND_PREFIX):
        route = route if route[len(COMMAND_PREFIX):] in COMMANDS else COMMAND_PREFIX + "?"
    elif route not in ROUTES:
        route = "?"
    return (method if method in METHODS else "?"), route


JSONRPC_MEMBERS = frozenset({"jsonrpc", "id", "method", "params"})
# method -> (the members its params may carry, with each one's type; those it must carry)
MCP_PARAMS: dict[str, tuple[dict[str, type], set[str]]] = {
    "initialize": ({"protocolVersion": str, "capabilities": dict, "clientInfo": dict, "_meta": dict}, {"protocolVersion"}),
    "ping": ({"_meta": dict}, set()),
    "tools/list": ({"cursor": str, "_meta": dict}, set()),
    "tools/call": ({"name": str, "arguments": dict, "_meta": dict}, {"name"}),
}
MCP_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # the first is answered to a client asking for any other
MAX_ID = 2**53 - 1


def _request_id(ident: object) -> bool:
    """A JSON-RPC id as MCP allows it: a string, or an integer (never a
    boolean, a float, null or a structure), bounded."""
    return (isinstance(ident, str) and 0 < len(ident) <= 200) or (type(ident) is int and -MAX_ID <= ident <= MAX_ID)


def _status_query(query: str) -> dict | None:
    """A status query as status arguments: none, or exactly one topic; None
    for anything else (a repeated or unknown key, a malformed query)."""
    if not query:
        return {}
    try:
        parsed = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    return {"topic": parsed["topic"][0]} if set(parsed) == {"topic"} and len(parsed["topic"]) == 1 else None


class OperatorService:
    def __init__(self, backend, credentials: Credentials, *, incidents: Callable[[], list[dict]] = lambda: [],
                 log: Callable[[str], None] = lambda line: None) -> None:
        self._backend = backend
        self._credentials = credentials
        self._incidents = incidents
        self._log = log

    def handle(self, method: str, target: str, authorization: str | None, length: str | None, read: Callable[[int], bytes]) -> tuple[int, dict]:
        path, _, query = target.partition("?")
        method_label, route = label(method, target)
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
            return self._answer(None, method_label, route, 401, {"status": "refused", "reason": "unauthenticated"})
        if path == "/v1/status" and method == "GET":
            return self._answer(principal, method_label, route, *self._status(principal, _status_query(query)))
        if path == "/mcp" and method == "POST":
            body, error = self._body(length, read)
            if error is not None:
                return self._answer(principal, method_label, route, error[0], {"status": "refused", "reason": error[1]})
            code, reply, route = self._mcp(principal, body)
            return self._answer(principal, method_label, route, code, reply)
        name = path[len(COMMAND_PREFIX):] if path.startswith(COMMAND_PREFIX) and method == "POST" else None
        if name not in COMMANDS:
            return self._answer(principal, method_label, route, 404, {"status": "refused", "reason": "no_such_route"})
        if principal.role != COMMANDS[name][0]:
            return self._answer(principal, method_label, route, 403, {"status": "refused", "reason": "forbidden"})
        body, error = self._body(length, read)
        if error is not None:
            return self._answer(principal, method_label, route, error[0], {"status": "refused", "reason": error[1]})
        return self._answer(principal, method_label, route, *self._command(principal, name, body))

    def _status(self, principal: Principal, arguments: dict | None) -> tuple[int, dict]:
        """Status, the same for every transport: the operator's, and its
        arguments ({} or {"topic": <topic_id>}; None: a query that was not
        one) exactly, like a command's body."""
        if principal.role != "operator":
            return 403, {"status": "refused", "reason": "forbidden"}
        if arguments is None or set(arguments) - {"topic"} or not isinstance(arguments.get("topic", ""), str):
            return 400, {"status": "refused", "reason": "request_invalid"}
        facts = self._backend.status({} if "topic" not in arguments else {"topic_id": arguments["topic"]})
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
        _command as the routes, so MCP is a transport, not a second path.

        The envelope is checked whole before anything is dispatched, as
        strictly as a command's body (Astra 1e review finding 4; JSON-RPC 2.0,
        MCP): members only jsonrpc, id, method and params; jsonrpc exactly
        "2.0"; method a string; id, where present, a string or an integer
        (never null, a float, a boolean or a structure); params, where
        present, an object (-32600 Invalid Request otherwise). An id that
        carries a configured token, in any form redaction takes out (auth.py
        Credentials.redact: as it is, JSON-escaped, percent-decoded or
        JSON-unescaped, an integer's digits), or that is written with one —
        its answer's text showing one the id alone does not, where the id
        stands after `"id": ` and before `, "jsonrpc"` (Credentials.writes:
        the quote written before an id `abc...` completes a token `"abc...`)
        — is refused the same way, before anything is dispatched, and
        answered with a null id: echoing it
        would repeat the credential, and replacing it would answer another
        request's id (Astra 1e-repair re-review finding 2, 1e-repair-2
        re-review finding 1). Both are checked, redaction's (whose pass the
        answer then takes, and must leave the id as it came) and the written
        text's: the quote written after an id can end the escape a decoding
        of it leaves, keeping from its text a token the id shows (Astra
        1e-repair-3 re-review finding 1). A message
        without an id is a notification: a notifications/ method is accepted
        (202) and does nothing; any other method needs an id (-32600). Each
        method's params carry only its members, each of its type, the
        required ones present (MCP_PARAMS; -32602 Invalid params otherwise):
        a tool call's arguments, omitted, are {}; given, they are an object —
        [] or null is refused, never taken as {}. Both errors are HTTP 400
        with the command path's own refusal ({"status": "refused", "reason":
        "request_invalid"}) as their data, and nothing is dispatched. A
        well-formed call's refusal, at any later step — the role, who acts
        named, an unknown or capability-bearing tool, the arguments, the
        router's own — is an in-band tool error carrying its reply, redacted
        before it is serialized into the tool's text (redaction after would
        see the token JSON-escaped, and miss it), and that text checked as it
        is nested (Credentials.dumps). The answer is then checked as the
        transport writes it: a token the text shows only beside the quote
        MCP writes before or after it would have the whole text replaced
        there, leaving no JSON in it — that answer is Unwritable, the fixed
        fault (Astra 1e-repair-3 re-review finding 1)."""
        has_id, ident = "id" in message, message.get("id")
        usable = has_id and _request_id(ident) and self._credentials.redact(ident) == ident and self._credentials.writes({"id": ident, "jsonrpc": "2.0"})
        if set(message) - JSONRPC_MEMBERS or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str) \
                or (has_id and not usable) or ("params" in message and not isinstance(message["params"], dict)):
            return self._rpc_refusal(ident if usable else None, -32600, "invalid request")
        method, params = message["method"], message.get("params", {})
        if not has_id:
            if method.startswith("notifications/"):
                return 202, {}, "/mcp"  # a notification: nothing to answer
            return self._rpc_refusal(None, -32600, "invalid request")  # a request needs its id
        if method not in MCP_PARAMS:
            return 200, {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "method not found"}}, "/mcp"
        members, required = MCP_PARAMS[method]
        if set(params) - set(members) or not required <= set(params) or not all(isinstance(params[k], members[k]) for k in params):
            return self._rpc_refusal(ident, -32602, "invalid params")
        answer = lambda result: {"jsonrpc": "2.0", "id": ident, "result": result}  # noqa: E731
        if method == "initialize":
            version = params["protocolVersion"] if params["protocolVersion"] in MCP_VERSIONS else MCP_VERSIONS[0]
            return 200, answer({"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": {"name": "gen2-engine", "version": "1e"}}), "/mcp"
        if method == "ping":
            return 200, answer({}), "/mcp"
        if method == "tools/list":
            names = ["status"] * (principal.role == "operator") + [name for name, (role, _) in COMMANDS.items() if role == principal.role]
            return 200, answer({"tools": [{"name": name, "description": f"POST /v1/commands/{name}" if name in COMMANDS else "GET /v1/status",
                                           "inputSchema": {"type": "object"}} for name in names]}), "/mcp"
        tool, arguments = params["name"], params.get("arguments", {})
        if tool == "status":
            code, reply = self._status(principal, arguments)
        elif tool in COMMANDS:
            code, reply = self._command(principal, tool, arguments)
        else:
            code, reply = 404, {"status": "refused", "reason": "no_such_route"}
        failed = code != 200 or reply.get("status") in ("refused", "rejected")
        nested = answer({"content": [{"type": "text", "text": self._credentials.dumps(self._credentials.redact(reply), nested=True)}], "isError": failed})
        if not self._credentials.writes(nested):
            raise Unwritable("the tool's text is written in MCP's answer with a configured token")
        return 200, nested, f"/mcp:{tool if tool in (*COMMANDS, 'status') else '?'}"

    @staticmethod
    def _rpc_refusal(ident, code: int, message: str) -> tuple[int, dict, str]:
        return 400, {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message, "data": {"status": "refused", "reason": "request_invalid"}}}, "/mcp"

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

    def _answer(self, principal: Principal | None, method: str, route: str, code: int, reply: dict) -> tuple[int, dict]:
        """Log the request's line (labels only: label()) and answer; both with
        every configured token redacted."""
        who = "-" if principal is None else f"{principal.role}:{principal.name}"
        outcome = reply.get("status") if isinstance(reply, dict) else None
        self._log(self._credentials.redact(f"{who} {method} {route} -> {code} {outcome}"))
        return code, self._credentials.redact(reply)

    def encode(self, reply: dict) -> bytes:
        """An answer as the transport writes it: its JSON text, checked as
        that text (Credentials.dumps: a value its serialization would make
        a token of is replaced whole), in UTF-8."""
        return self._credentials.dumps(reply).encode("utf-8")
