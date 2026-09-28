"""Authentication and authorization on the engine's listener (task 1e).

Every request here is real HTTP over loopback to the engine
(operator_fixtures). Each negative changes exactly one thing from a request
that is applied — the token, the route or one field of the body — and is
paired with that applied request (the control), sent after it and shown to
succeed; "nothing changed" is read back as every table's rows, audit events
included, on the test's own connection.

What the tests cannot show: that the comparison takes constant time (a
timing property; auth.py compares SHA-256 digests with hmac.compare_digest
over every configured token, which review checks, not a test), and anything
about a listener exposed beyond loopback (deployment).
"""
from __future__ import annotations

import json
import socket
import time
import unittest
from unittest import mock

from gen2.operator.auth import Credentials, CredentialsRefused, Principal
from gen2.tests import operator_fixtures as of
from gen2.tests import router_fixtures as rf
from gen2.tests.router_fixtures import TOPIC

OPERATOR_COMMANDS = ("apply_operator_decision", "request_cancel", "requeue", "close_brief", "activate_config_bundle", "version_brief",
                     "mark_brief_overdue", "propose_amendment")
APPLIED = {"apply_operator_decision": "applied", "request_cancel": "recorded", "requeue": "requeued", "close_brief": "closed",
           "activate_config_bundle": "activated", "version_brief": "recorded", "mark_brief_overdue": "marked", "propose_amendment": "recorded"}
UNAUTHENTICATED = {"status": "refused", "reason": "unauthenticated"}


class HealthTest(of.OperatorTestCase):
    def test_health_needs_no_token_and_says_only_that_the_router_can_commit(self) -> None:
        for token in (None, "not-a-token-of-anyone-at-all"):
            with self.subTest(token=token):
                code, reply, headers = self.http("GET", "/v1/health", token=token)
                self.assertEqual((code, reply), (200, {"status": "ok"}))
                self.assertNotIn("www-authenticate", headers)

    def test_health_is_unavailable_when_the_router_cannot_commit(self) -> None:
        self.engine.call(lambda station: station.router.close())  # the store gone from under the router
        code, reply, _ = self.http("GET", "/v1/health", token=None)
        self.assertEqual((code, reply), (503, {"status": "unavailable"}))

    def test_health_is_a_read(self) -> None:
        before = self.state(exclude=())
        code, reply, _ = self.http("POST", "/v1/health", {"status": "down"}, token=None)
        self.assertEqual((code, reply.get("reason")), (405, "method_not_allowed"))
        self.assertEqual(self.http("GET", "/v1/health", token=None)[0], 200)
        self.assertEqual(self.state(exclude=()), before)


def raw_answer(engine, request: bytes) -> str:
    """Send `request` as it is and read the first answer; an answer that does
    not come within 5 s is the empty string (the assertion then fails)."""
    host, port = engine.address
    with socket.create_connection((host, port), timeout=5) as conn:
        conn.sendall(request)
        try:
            return conn.recv(4096).decode("latin-1")
        except TimeoutError:
            return ""


class AuthenticationTest(of.CommandWorld):
    BAD = {"no header": None, "a wrong token": "Bearer op-token-mallory-0123456789abcdef", "a token's prefix": f"Bearer {of.OPERATOR_TOKEN[:-1]}",
           "a token with a suffix": f"Bearer {of.OPERATOR_TOKEN}x", "another scheme": f"Basic {of.OPERATOR_TOKEN}", "another scheme, as long as Bearer": f"Digest {of.OPERATOR_TOKEN}", "an empty bearer": "Bearer ",
           "the token alone": of.OPERATOR_TOKEN}

    def send(self, method: str, path: str, authorization: str | None, raw: bytes | None = None, headers: dict | None = None):
        sent = dict(headers or {})
        if authorization is not None:
            sent["Authorization"] = authorization
        return self.http(method, path, token=None, raw=raw, headers=sent)

    def test_a_missing_or_invalid_token_is_refused_before_the_body_is_read(self) -> None:
        """Every route but health, each bad credential, and a body that is not
        even JSON: 401 with the same reply every time (no oracle), nothing
        written. A body the service parsed would have been a 400."""
        before = self.state(exclude=())
        routes = [("GET", "/v1/status")] + [("POST", f"/v1/commands/{name}") for name in (*OPERATOR_COMMANDS, "ack_delivery", "no_such_operation")]
        for label, header in self.BAD.items():
            for method, path in routes:
                with self.subTest(label=label, path=path):
                    code, reply, headers = self.send(method, path, header, raw=b"{not json" if method == "POST" else None)
                    self.assertEqual((code, reply), (401, UNAUTHENTICATED))
                    self.assertEqual(headers.get("www-authenticate"), 'Bearer realm="gen2-engine"')
        self.assertEqual(self.state(exclude=()), before)
        code, reply = self.command("request_cancel", self.bodies()["request_cancel"])  # the control: the same route, the right token
        self.assertEqual((code, reply["status"]), (200, "recorded"))

    def test_an_unread_body_is_never_waited_for(self) -> None:
        """A wrong token declaring a large body it never sends is answered at
        once: the service does not read what an unauthenticated caller says it
        will send."""
        answer = raw_answer(self.engine, b"POST /v1/commands/request_cancel HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer op-token-mallory-0123456789abcdef\r\n"
                                         b"Content-Length: 900000\r\n\r\n")
        self.assertTrue(answer.startswith("HTTP/1.0 401"), answer)

    def test_the_bearer_scheme_is_matched_without_case_and_the_token_exactly(self) -> None:
        code, reply, _ = self.send("GET", "/v1/status", f"bearer {of.OPERATOR_TOKEN}")
        self.assertEqual((code, reply["status"]), (200, "ok"))
        self.assertEqual(self.send("GET", "/v1/status", f"Bearer {of.OPERATOR_TOKEN} ")[0], 401)


UNAUTHENTICATED_ANSWER = b'{"reason": "unauthenticated", "status": "refused"}'


def read_answer(conn: socket.socket) -> tuple[bytes, bytes]:
    """One whole HTTP answer from `conn`: (its head, its body of the declared length)."""
    received = b""
    while b"\r\n\r\n" not in received:
        chunk = conn.recv(4096)
        if not chunk:
            break
        received += chunk
    head, _, body = received.partition(b"\r\n\r\n")
    declared = next(int(line.split(b":")[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length:"))
    while len(body) < declared:
        body += conn.recv(declared - len(body))
    return head, body


def send_after_the_answer(engine, declared: int, *, fragment: int = 8192, pause: float = 0.015, limit_s: float = 8.0) -> dict:
    """The review's client (Astra 1e review finding 8): an unauthenticated POST
    declaring `declared` bytes and sending none; its whole answer read; then
    0.3 s to see whether the engine closes (its FIN); then the body in
    `fragment`-byte pieces `pause` apart, for at most `limit_s`; then the end
    of the connection read. The listener discards a small unread body after
    its answer, so this client's sends succeed and the connection ends
    cleanly; closing without that makes the kernel reset it at the client's
    next fragment."""
    host, port = engine.address
    with socket.create_connection((host, port), timeout=5) as conn:
        conn.sendall(f"POST /v1/commands/request_cancel HTTP/1.1\r\nHost: x\r\nContent-Length: {declared}\r\n\r\n".encode())
        head, body = read_answer(conn)
        answered = time.monotonic()
        conn.settimeout(0.3)
        try:
            closed_at_once = conn.recv(1) == b""
        except TimeoutError:
            closed_at_once = False
        except ConnectionResetError:
            closed_at_once = True
        sent, error = 0, None
        try:
            while sent < declared and time.monotonic() - answered < limit_s:
                time.sleep(pause)
                piece = b"x" * min(fragment, declared - sent)
                conn.sendall(piece)
                sent += len(piece)
                if fragment == 1:  # a slow client: it notices the engine closing between its bytes
                    try:
                        if conn.recv(1) == b"":
                            break
                    except TimeoutError:
                        pass
        except OSError as failure:
            error = type(failure).__name__
        conn.settimeout(5)
        try:
            end = "eof" if conn.recv(1) == b"" else "more"
        except OSError as failure:
            end = type(failure).__name__
        return {"status": head.split(b"\r\n")[0], "body": body, "closed_at_once": closed_at_once, "sent": sent, "error": error, "end": end,
                "held_s": time.monotonic() - answered}


class UnreadBodyTest(of.CommandWorld):
    """What the listener does with a body it answered without reading (Astra
    1e review finding 8). The service refuses before parsing; after its
    answer the listener reads and throws away at most DRAIN_MAX (64 KiB) of
    it, while each next byte comes within 1 s and the whole within 2 s, so a
    client still sending a small body completes its send and the connection
    closes cleanly. Over the ceiling, or past the time bound, it is not
    waited for: the connection closes, and a client still sending sees its
    send fail — after the whole answer was sent."""

    def assert_answered(self, found: dict) -> None:
        self.assertEqual((found["status"], found["body"]), (b"HTTP/1.0 401 Unauthorized", UNAUTHENTICATED_ANSWER))

    def test_a_small_body_sent_after_the_answer_is_discarded_and_the_connection_ends_cleanly(self) -> None:
        before = self.state(exclude=())
        found = send_after_the_answer(self.engine, 64 * 1024)
        self.assert_answered(found)
        self.assertEqual({k: found[k] for k in ("closed_at_once", "sent", "error", "end")},
                         {"closed_at_once": False, "sent": 64 * 1024, "error": None, "end": "eof"})
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.command("request_cancel", self.bodies()["request_cancel"])[1]["status"], "recorded")

    def test_a_body_over_the_ceiling_is_not_waited_for(self) -> None:
        found = send_after_the_answer(self.engine, 64 * 1024 + 1)
        self.assert_answered(found)
        self.assertTrue(found["closed_at_once"])
        self.assertLess(found["sent"], 64 * 1024 + 1)
        self.assertIn(found["error"], ("BrokenPipeError", "ConnectionResetError"))

    def test_a_client_too_slow_is_not_waited_for(self) -> None:
        """One byte every 0.3 s — never idle for the 1 s the discard allows,
        so only its 2 s in all ends it: the engine closes about 2 s after its
        answer, having been sent a few of the 100 bytes declared."""
        found = send_after_the_answer(self.engine, 100, fragment=1, pause=0.3)
        self.assert_answered(found)
        self.assertFalse(found["closed_at_once"])
        self.assertLess(found["sent"], 100)
        self.assertTrue(1.5 < found["held_s"] < 5.0, found)

    def test_a_refusal_with_no_body_closes_cleanly(self) -> None:
        for declared in ("0", None):
            with self.subTest(declared=declared):
                host, port = self.engine.address
                with socket.create_connection((host, port), timeout=5) as conn:
                    conn.sendall(("POST /v1/commands/request_cancel HTTP/1.1\r\nHost: x\r\n" + ("" if declared is None else f"Content-Length: {declared}\r\n")
                                  + "\r\n").encode())
                    head, body = read_answer(conn)
                    self.assertEqual((head.split(b"\r\n")[0], body, conn.recv(1)), (b"HTTP/1.0 401 Unauthorized", UNAUTHENTICATED_ANSWER, b""))


class ExpiredTokenTest(of.CommandWorld):
    def test_a_token_rotated_out_of_the_mount_is_refused_after_the_restart(self) -> None:
        """An env-backend token expires by rotation: the mount changes and the
        engine restarts (DEPLOYMENT-CONTRACT.md §2). The old token is refused;
        the rotated one authenticates the same principal, whose earlier
        decision stays attributed to it."""
        body = self.bodies()["apply_operator_decision"]
        self.assertEqual(self.command("apply_operator_decision", body)[1]["status"], "applied")
        rotated = "op-token-alice-rotated-0123456789"
        self.restart(of.credentials({"alice": rotated, "bob": of.OTHER_OPERATOR_TOKEN}))
        before = self.state(exclude=())
        self.assertEqual(self.http("GET", "/v1/status")[0:2], (401, UNAUTHENTICATED))
        self.assertEqual(self.command("close_brief", self.bodies()["close_brief"]), (401, UNAUTHENTICATED))
        self.assertEqual(self.state(exclude=()), before)
        code, reply = self.command("close_brief", self.bodies()["close_brief"], token=rotated)
        self.assertEqual((code, reply["status"]), (200, "closed"))
        self.assertEqual(self.rows("SELECT operator_id FROM operator_decisions WHERE decision_id = 'opd_brief_other'"), [("alice",)])
        self.assertEqual(self.rows("SELECT closed_by FROM intake_briefs WHERE topic_id = ? AND brief_id = 'brief-1' AND version = 1", rf.TOPIC), [("alice",)])


class AuthorizationTest(of.CommandWorld):
    def test_the_exporter_token_authorizes_no_operator_command(self) -> None:
        """Each operator command with a body the operator's token gets applied
        (the controls, sent after): 403 for the exporter, nothing written. Its
        token never carries operator authority (DEPLOYMENT-CONTRACT.md §1.1),
        status included."""
        bodies = self.bodies()
        before = self.state(exclude=())
        self.assertEqual(self.http("GET", "/v1/status", token=of.EXPORTER_TOKEN)[0:2], (403, {"status": "refused", "reason": "forbidden"}))
        for name in OPERATOR_COMMANDS:
            with self.subTest(command=name):
                self.assertEqual(self.command(name, bodies[name], token=of.EXPORTER_TOKEN), (403, {"status": "refused", "reason": "forbidden"}))
                code, reply, _ = self.http("POST", f"/v1/commands/{name}", raw=b"{not json", token=of.EXPORTER_TOKEN)  # refused before its body is parsed
                self.assertEqual((code, reply.get("reason")), (403, "forbidden"))
        self.assertEqual(self.state(exclude=()), before)
        for name in OPERATOR_COMMANDS:
            with self.subTest(control=name):
                code, reply = self.command(name, bodies[name])
                self.assertEqual((code, reply["status"]), (200, APPLIED[name]), reply)

    def test_only_the_exporter_token_acknowledges_a_delivery(self) -> None:
        receipt = self.bodies()["ack_delivery"]
        before = self.state(exclude=())
        for token in (of.OPERATOR_TOKEN, of.OTHER_OPERATOR_TOKEN):
            with self.subTest(token=token[:8]):
                self.assertEqual(self.command("ack_delivery", receipt, token=token), (403, {"status": "refused", "reason": "forbidden"}))
        self.assertEqual(self.state(exclude=()), before)
        code, reply = self.command("ack_delivery", receipt, token=of.EXPORTER_TOKEN)
        self.assertEqual((code, reply["status"]), (200, "recorded"))
        self.assertEqual(self.rows("SELECT status FROM export_delivery_receipts WHERE export_receipt_id = 'exr_000000000001'"), [("delivered",)])

    def test_a_capability_is_never_a_bearer_token(self) -> None:
        capability = self.run_grant["capability_id"]
        before = self.state(exclude=())
        self.assertEqual(self.http("GET", "/v1/status", token=capability)[0:2], (401, UNAUTHENTICATED))
        self.assertEqual(self.command("request_cancel", self.bodies()["request_cancel"], token=capability), (401, UNAUTHENTICATED))
        self.assertEqual(self.state(exclude=()), before)

    def test_a_capability_in_a_command_body_is_refused(self) -> None:
        """A capability never stands in for the principal: a body carrying
        one is refused before the router, for the cancellation it would make
        a supervisor's, and for a command whose schema has no such field."""
        bodies = self.bodies()
        before = self.state(exclude=())
        for name, extra in (("request_cancel", {"capability_id": self.run_grant["capability_id"]}),
                            ("apply_operator_decision", {"capability_id": self.run_grant["capability_id"]})):
            with self.subTest(command=name):
                code, reply = self.command(name, {**bodies[name], **extra})
                self.assertEqual((code, reply.get("reason")), (400, "authority_in_request"))
        self.assertEqual(self.state(exclude=()), before)
        for name in ("request_cancel", "apply_operator_decision"):
            self.assertEqual(self.command(name, bodies[name])[1]["status"], APPLIED[name])

    def test_the_operator_token_drives_no_invocation(self) -> None:
        """The capability-bearing calls are not routes of this surface: the
        operator's token with a request naming a real capability, which the
        supervisor's in-process call gets recorded (the control), is 404 and
        records nothing."""
        grant = self.claim("inv_newpass0001", kind="verification")
        self.assertEqual(grant["status"], "granted", grant)
        launch = {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "to_state": "launching", "job_handle": "job-new"}
        calls = {"record_transition": launch, "invocation_status": {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"]},
                 "claim": {"invocation_id": "inv_other000001", "kind": "verification", "topic_id": rf.TOPIC, "config_bundle_hash": rf.CONFIG,
                           "deadline_at": rf.DEADLINE, "station_id": "station-1", "lease_expires_at": rf.EXPIRES},
                 "reconcile": {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "unknown_episode": 1,
                               "resolution": "terminated_group", "method": "execution_group_termination", "evidence_ref": rf.h("1")},
                 "record_observation": {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "observation": {}, "retrieval_events": []},
                 "commit_outcome": {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"]}}
        before = self.state(exclude=())
        for name, body in calls.items():
            with self.subTest(call=name):
                self.assertEqual(self.command(name, body), (404, {"status": "refused", "reason": "no_such_route"}))
                self.assertEqual(self.command(name, body, token=of.EXPORTER_TOKEN)[0], 404)
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.router.record_transition(launch)["status"], "recorded")  # the supervisor's own path


class BackendSurfaceTest(of.OperatorTestCase):
    def test_the_service_reaches_only_the_operator_operations(self) -> None:
        """What the composition root hands the service (gen2/app/engine.py
        _Owned) answers the operations its routes call and nothing else of the
        router or the supervisor: not the store, not a capability-bearing call,
        not a trusted command no route names, not the supervisor's own driving
        (the station's recovery of one stalled job is the one route there)."""
        backend = self.engine.service._backend
        self.assertIs(backend.healthy(), True)
        self.assertEqual(backend.status({"topic_id": TOPIC})["status"], "ok")
        self.assertEqual(backend.recover_incident({})["reason"], "request_invalid")  # the supervisor's, answering
        for name in ("_store", "claim", "record_transition", "commit_outcome", "reconcile", "invocation_status", "record_observation",
                     "record_qualification", "open_reservation", "open_review", "restore_config_bundle", "close",
                     "recover", "advance", "submit", "prepare", "run", "incidents", "job", "control"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    getattr(backend, name)


class AuthorityFieldTest(of.CommandWorld):
    def test_who_acts_is_never_taken_from_the_request(self) -> None:
        """Each field naming who acts, in the one command it belongs to: refused
        (400) with nothing written; without it, the command is applied and the
        principal is what the router records."""
        bodies = self.bodies()
        cases = (("apply_operator_decision", "operator_id", "mallory"), ("request_cancel", "requested_by", "supervisor"),
                 ("requeue", "requested_by", "policy"), ("close_brief", "closed_by", "mallory"))
        before = self.state(exclude=())
        for name, field, value in cases:
            with self.subTest(command=name, field=field):
                code, reply = self.command(name, {**bodies[name], field: value})
                self.assertEqual((code, reply.get("reason")), (400, "authority_in_request"))
                self.assertIn(field, reply["detail"])
        self.assertEqual(self.state(exclude=()), before)
        for name, _, _ in cases:
            self.assertEqual(self.command(name, bodies[name], token=of.OTHER_OPERATOR_TOKEN)[1]["status"], APPLIED[name])
        self.assertEqual(self.rows("SELECT operator_id FROM operator_decisions WHERE decision_id = 'opd_brief_other'"), [("bob",)])
        self.assertEqual(self.rows("SELECT cancel_requested_by FROM invocations WHERE invocation_id = ?", of.RUNNING), [("operator",)])
        self.assertEqual(self.rows("SELECT requested_by FROM retries WHERE invocation_id = ?", of.FAILED), [("operator",)])
        self.assertEqual(self.rows("SELECT closed_by, status FROM intake_briefs WHERE topic_id = ? AND brief_id = 'brief-1' AND version = 1", rf.TOPIC),
                         [("bob", "archived")])


class BodyTest(of.CommandWorld):
    def test_a_body_is_strict_json_of_a_declared_length(self) -> None:
        body = self.bodies()["request_cancel"]
        text = json.dumps(body)
        before = self.state(exclude=())
        for label, raw, headers, expected in (
                ("duplicate keys", text[:-1].encode() + b', "reason": "again"}', None, (400, "request_invalid")),
                ("not an object", b"[1]", None, (400, "request_invalid")),
                ("a non-finite number", text[:-1].encode() + b', "n": NaN}', None, (400, "request_invalid"))):
            with self.subTest(label=label):
                code, reply, _ = self.http("POST", "/v1/commands/request_cancel", raw=raw, headers=headers)
                self.assertEqual((code, reply.get("reason")), expected)
        answer = raw_answer(self.engine, f"POST /v1/commands/request_cancel HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {of.OPERATOR_TOKEN}\r\n"
                                         f"Content-Length: {1024 * 1024 + 1}\r\n\r\n".encode())  # declared, never sent: refused unread
        self.assertTrue(answer.startswith("HTTP/1.0 413"), answer)
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.command("request_cancel", body)[1]["status"], "recorded")

    def test_a_body_without_a_length_is_refused(self) -> None:
        answer = raw_answer(self.engine, f"POST /v1/commands/request_cancel HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {of.OPERATOR_TOKEN}\r\n"
                                         "Transfer-Encoding: chunked\r\n\r\n".encode())  # no chunk sent: the answer comes without reading one
        self.assertTrue(answer.startswith("HTTP/1.0 411"), answer)


class SecrecyTest(of.CommandWorld):
    def test_no_token_reaches_a_log_a_reply_or_a_header(self) -> None:
        """Every route, with every configured token, a wrong one, and bodies
        that fail at each check: no configured or presented token appears in
        any log line, reply or response header."""
        presented = "op-token-mallory-0123456789abcdef"
        seen = []
        bodies = self.bodies()
        for token in (*of.TOKENS, presented, None):
            for method, path, body in (("GET", "/v1/status", None), ("GET", "/v1/health", None), ("POST", "/v1/commands/no_such", {}),
                                       ("POST", "/v1/commands/request_cancel", {**bodies["request_cancel"], "requested_by": "x"}),
                                       ("POST", "/v1/commands/ack_delivery", bodies["ack_delivery"]),
                                       ("POST", "/v1/commands/apply_operator_decision", {"decision_id": 1})):
                code, reply, headers = self.http(method, path, body, token=token)
                seen.append(json.dumps([code, reply, headers]))
        seen += self.logs
        self.assertTrue(any("-> 401" in line for line in self.logs) and any("-> 403" in line for line in self.logs))
        for token in (*of.TOKENS, presented):
            self.assertFalse([s for s in seen if token in s], f"a token ({token[:6]}...) appeared")


def raw_exchange(engine, request: bytes) -> bytes:
    """Send `request` as it is; every byte of the answer (status line, headers,
    body) until the engine closes the connection, or 5 s pass."""
    host, port = engine.address
    answer = b""
    with socket.create_connection((host, port), timeout=5) as conn:
        conn.sendall(request)
        try:
            while chunk := conn.recv(65536):
                answer += chunk
        except (TimeoutError, ConnectionResetError):
            pass
    return answer


class DiagnosticSecrecyTest(of.CommandWorld):
    """A credential a request carries — in its path, query, method, version,
    a header or its body — reaches no log line, reply or header, through each
    diagnostic path of the listener: the service's route labels, the parser's
    refusals, the handler's fault path, a refusal that would echo a body's
    key (Astra 1e review finding 3). Each carried as a configured
    operator's token, the exporter's and an unknown one. An unknown string in
    an authenticated operator's own body is not a credential the engine can
    know, so the refusal that echoes a body's key is sent with the
    configured tokens only (Credentials.redact takes those out).
    A request line the parser cannot read is answered as HTTP/0.9, a body
    with no status line or headers (http.server)."""
    UNKNOWN = "op-token-mallory-0123456789abcdef"
    PARSER = b'{"reason": "bad_request", "status": "refused"}'
    ECHOED = "a body key the router refuses"

    def requests(self, token: str) -> list[tuple[str, bytes, str]]:
        """(what, the raw request, the line the engine logs for it)."""
        auth = f"Authorization: Bearer {of.OPERATOR_TOKEN}\r\n"
        body = json.dumps({"invocation_id": of.RUNNING, "reason": "stop", token: 1}).encode()
        post = lambda path, extra="": (f"POST {path} HTTP/1.1\r\nHost: x\r\n{extra}Content-Length: {len(body)}\r\n\r\n".encode() + body)  # noqa: E731
        return [
            ("an unauthenticated command path", post(f"/v1/commands/{token}"), "- POST /v1/commands/? -> 401 refused"),
            ("an authenticated unknown command", post(f"/v1/commands/{token}", auth), "operator:alice POST /v1/commands/? -> 404 refused"),
            ("an unknown path", f"GET /{token}/x HTTP/1.1\r\nHost: x\r\n{auth}\r\n".encode(), "operator:alice GET ? -> 404 refused"),
            ("a status query", f"GET /v1/status?topic={token} HTTP/1.1\r\nHost: x\r\n{auth}\r\n".encode(), "operator:alice GET /v1/status -> 200 refused"),
            ("a body key the router refuses", post("/v1/commands/request_cancel", auth), "operator:alice POST /v1/commands/request_cancel -> 200 refused"),
            ("an unsupported method", f"{token} /v1/status HTTP/1.1\r\nHost: x\r\n{auth}\r\n".encode(), "- ? ? -> 501 refused"),
            ("an unsupported method's path", f"PUT /v1/commands/{token} HTTP/1.1\r\nHost: x\r\n\r\n".encode(), "- ? ? -> 501 refused"),
            ("a bad version", f"GET /v1/status HTTP/{token}\r\nHost: x\r\n\r\n".encode(), "- ? ? -> 400 refused"),
            ("a bad request line", f"{token}\r\n\r\n".encode(), "- ? ? -> 400 refused"),
            ("a request line too long", f"GET /{token}{'a' * 70000} HTTP/1.1\r\n\r\n".encode(), "- ? ? -> 414 refused"),
            ("a header too long", f"GET /v1/status HTTP/1.1\r\nX-Pad: {token}{'a' * 70000}\r\n\r\n".encode(), "- ? ? -> 431 refused"),
        ]

    def test_no_carried_token_reaches_a_log_a_reply_or_a_header(self) -> None:
        for token in (of.OPERATOR_TOKEN, of.EXPORTER_TOKEN, self.UNKNOWN):
            for what, request, line in self.requests(token):
                if token == self.UNKNOWN and what == self.ECHOED:
                    continue
                with self.subTest(token=token[:9], what=what):
                    self.logs.clear()
                    answer = raw_exchange(self.engine, request)
                    if what in ("a bad version", "a bad request line"):
                        self.assertEqual(answer, self.PARSER)
                    else:
                        self.assertTrue(answer.startswith(f"HTTP/1.0 {line.split(' -> ')[1][:3]} ".encode()), answer[:80])
                    self.assertNotIn(token.encode(), answer)
                    self.assertEqual(self.logs, [line])
        refused = raw_exchange(self.engine, self.requests(of.EXPORTER_TOKEN)[4][1])  # the router's refusal names the key; the key is redacted
        self.assertIn(b"[credential]", refused)
        answer = raw_exchange(self.engine, f"GET /v1/status HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {of.OPERATOR_TOKEN}\r\n\r\n".encode())
        self.assertIn(b'"status": "ok"', answer)  # the control: an authenticated request is answered

    def test_a_fault_behind_the_service_is_logged_by_type_and_label(self) -> None:
        """The handler's fault path: the service raises with the carried token
        in its message; the answer is the fixed 500 and the log line names
        the fault's type and the service's labels, nothing of the request."""
        for token in (of.OPERATOR_TOKEN, self.UNKNOWN):
            for path, line in ((f"/v1/commands/{token}", "- POST /v1/commands/? -> 500 RuntimeError"),
                               ("/v1/commands/request_cancel", "- POST /v1/commands/request_cancel -> 500 RuntimeError"),
                               (f"/{token}", "- POST ? -> 500 RuntimeError")):
                with self.subTest(token=token[:9], path=path[:14]):
                    self.logs.clear()
                    body = json.dumps({"reason": token}).encode()
                    with mock.patch.object(self.engine.service, "handle", side_effect=RuntimeError(f"failed on {path} with {token}")):
                        answer = raw_exchange(self.engine, f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
                    self.assertTrue(answer.startswith(b"HTTP/1.0 500 "), answer[:80])
                    self.assertTrue(answer.endswith(b'{"reason": "internal", "status": "error"}'), answer[-80:])
                    self.assertNotIn(token.encode(), answer)
                    self.assertEqual(self.logs, [line])
        self.assertEqual(self.command("request_cancel", self.bodies()["request_cancel"])[1]["status"], "recorded")  # the control, unpatched


class CredentialsTest(unittest.TestCase):
    ENV = {"GEN2_SECRETS": "env", "GEN2_OPERATOR_TOKENS": f"alice={of.OPERATOR_TOKEN}, bob={of.OTHER_OPERATOR_TOKEN}",
           "GEN2_SECRET_EXPORTER_TOKEN": of.EXPORTER_TOKEN}

    def test_the_mounted_names_configure_the_principals(self) -> None:
        creds = Credentials.from_environ(self.ENV)
        self.assertEqual(creds.principals, [Principal("alice", "operator"), Principal("bob", "operator"), Principal("exporter", "exporter")])
        self.assertEqual(creds.authenticate(f"Bearer {of.OTHER_OPERATOR_TOKEN}"), Principal("bob", "operator"))
        self.assertEqual(creds.authenticate(f"Bearer {of.EXPORTER_TOKEN}"), Principal("exporter", "exporter"))
        self.assertIsNone(Credentials.from_environ({**self.ENV, "GEN2_SECRET_EXPORTER_TOKEN": ""}).authenticate(f"Bearer {of.EXPORTER_TOKEN}"))

    def test_unusable_secrets_refuse_the_start(self) -> None:
        """Each defect alone, beside ENV, which starts (the control); no
        refusal names a token."""
        self.assertEqual(len(Credentials.from_environ(self.ENV).principals), 3)
        short = "short-token-15ch"[:15]
        cases = {"no operator token": {"GEN2_OPERATOR_TOKENS": ""}, "the variable absent": {"GEN2_OPERATOR_TOKENS": None},
                 "vault is not admissible": {"GEN2_SECRETS": "vault"}, "an entry that is not name=token": {"GEN2_OPERATOR_TOKENS": of.OPERATOR_TOKEN},
                 "a name twice": {"GEN2_OPERATOR_TOKENS": f"alice={of.OPERATOR_TOKEN},alice={of.OTHER_OPERATOR_TOKEN}"},
                 "two principals, one token": {"GEN2_SECRET_EXPORTER_TOKEN": of.OPERATOR_TOKEN},
                 "a short token": {"GEN2_OPERATOR_TOKENS": f"alice={short}"},
                 "a token with a space": {"GEN2_OPERATOR_TOKENS": "alice=op token with a space in it"},
                 "a short exporter token": {"GEN2_SECRET_EXPORTER_TOKEN": short},
                 "a name that is not one": {"GEN2_OPERATOR_TOKENS": f"al ice={of.OPERATOR_TOKEN}"}}
        for label, change in cases.items():
            with self.subTest(label=label):
                env = {k: v for k, v in {**self.ENV, **change}.items() if v is not None}
                with self.assertRaises(CredentialsRefused) as refused:
                    Credentials.from_environ(env)
                for token in (*of.TOKENS, short, "op token with a space in it"):
                    self.assertNotIn(token, str(refused.exception))


if __name__ == "__main__":
    unittest.main()
