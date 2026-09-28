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

import contextlib
import io
import json
import socket
import time
import unittest
from unittest import mock

from gen2.operator import auth
from gen2.operator.auth import REDACTED, Credentials, CredentialsRefused, Principal, Unwritable
from gen2.operator.service import OperatorService
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
        try:
            answered = backend.recover_incident({})  # the supervisor's, answering
        except AttributeError:
            self.fail("the station's recovery is not reachable through the backend")
        self.assertEqual(answered["reason"], "request_invalid")
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

    def test_a_connection_fault_is_one_line_naming_its_type(self) -> None:
        """What the server does with a fault outside the service (a client gone
        mid-answer): one log line naming the fault's type, and nothing written
        to stderr — no traceback, whose text may carry the request's."""
        stderr = io.StringIO()
        try:
            raise ConnectionResetError(f"reset while answering /v1/commands/{of.OPERATOR_TOKEN}")
        except ConnectionResetError:
            with contextlib.redirect_stderr(stderr):
                self.engine._server.handle_error(None, ("127.0.0.1", 1))
        self.assertEqual((self.logs, stderr.getvalue()), (["- ? ? -> connection ConnectionResetError"], ""))


def percent(text: str, upper: bool = False, every: int = 1) -> str:
    """`text` percent-encoded: every `every`-th character as %xx (lower-case hex unless `upper`), the rest as they are."""
    return "".join((f"%{ord(c):02X}" if upper else f"%{ord(c):02x}") if i % every == 0 else c for i, c in enumerate(text))


class CarriedFormsTest(of.CommandWorld):
    """A configured token a request carries reaches no reply, log or header
    in any form a reply can carry it (Astra 1e-repair re-review finding 2):
    JSON-escaped inside the tool text MCP nests in its reply, as the digits
    of a numeric JSON-RPC id, percent-encoded in an id; nor any its answer's
    text would be written with, though no value holds it (Astra 1e-repair-2
    re-review finding 1): an escape or a quote that serialization writes, a
    JSON escape an id carries, percent-encoded or not. Each answer is read
    off the wire — status line, headers, body — and both JSON layers are
    decoded, each of which must parse: every one must be free of the token
    as it is and escaped, and so must the engine's log. The tokens here are
    synthetic ones the visible-ASCII policy accepts; each set is configured
    afresh (a restart with the same store)."""
    # every visible-ASCII mark that JSON escapes (" and \) or that percent-encoding and JSON pointers treat specially
    ESCAPING = ('credential-with-quote-"-12345', "credential-with-backslash-\\-12345", "credential-every-mark-!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
    NUMERIC = "1234567890123456"

    def exchange(self, path: str, message: dict | None = None, *, raw_body: bytes | None = None) -> tuple[str, dict]:
        """One authenticated POST, as it goes on the wire: (the whole answer as text, its JSON body)."""
        body = raw_body if raw_body is not None else json.dumps(message).encode()
        answer = raw_exchange(self.engine, f"POST {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {of.OPERATOR_TOKEN}\r\n"
                                           f"Content-Length: {len(body)}\r\n\r\n".encode() + body).decode("latin-1")
        return answer, self.decoded(answer.partition("\r\n\r\n")[2])

    def decoded(self, text: str):
        """text parsed as JSON: a failure, not an error, if it is not JSON."""
        try:
            return json.loads(text)
        except ValueError:
            self.fail(f"not JSON: {text[:200]!r}")

    def assert_absent(self, token: str, answer: str, *documents) -> None:
        """Neither the token nor its JSON-escaped form in the wire answer, in
        any decoded document (written back out unescaped) or in the log."""
        for text in (answer, *(json.dumps(doc, ensure_ascii=False) for doc in documents), *self.logs):
            for form in {token, json.dumps(token)[1:-1]}:
                self.assertNotIn(form, text)

    def tool_call(self, arguments: dict, ident: object = 1, tool: str = "request_cancel") -> dict:
        return {"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}

    def test_a_token_in_a_tool_reply_is_taken_out_before_the_reply_is_nested(self) -> None:
        """The operator's cancellation carries the exporter's token as a key
        the router refuses: the REST refusal and the MCP tool's (its text
        decoded) are the same refusal, the key redacted, for each token."""
        cancel = self.bodies()["request_cancel"]
        for token in self.ESCAPING:
            with self.subTest(token=token):
                self.restart(Credentials({"alice": of.OPERATOR_TOKEN}, token))
                before = self.state(exclude=())
                self.logs.clear()
                rest_answer, rest = self.exchange("/v1/commands/request_cancel", {**cancel, token: 1})
                mcp_answer, mcp = self.exchange("/mcp", self.tool_call({**cancel, token: 1}))
                inner = json.loads(mcp["result"]["content"][0]["text"])
                self.assertEqual((rest, inner, mcp["result"]["isError"]), ({"status": "refused", "reason": "request_invalid",
                                                                            "detail": "router-commands#/$defs/cancel: /[credential]: no value is allowed here"},
                                                                           rest, True))
                self.assert_absent(token, rest_answer, rest)
                self.assert_absent(token, mcp_answer, mcp, inner)
                self.assertEqual(self.state(exclude=()), before)
        control_answer, control = self.exchange("/mcp", self.tool_call(cancel))  # the control: the same call without the key is applied
        self.assertEqual(json.loads(control["result"]["content"][0]["text"])["status"], "recorded", control_answer)

    def test_an_id_carrying_a_token_is_refused_and_never_echoed(self) -> None:
        """An MCP id carrying a configured token — the numeric token as an
        integer, negative or as a string, JSON-escaped in the body, and an
        operator's token percent-encoded (lower and upper case, in part,
        twice, inside other text) — is refused as an invalid request with a
        null id, and the call it names is not made. Ordinary ids beside
        them — a token's prefix, an encoded non-token, a long integer that
        is not a token — are echoed exactly, and the same call is made."""
        self.restart(Credentials({"alice": of.OPERATOR_TOKEN, "bob": of.OTHER_OPERATOR_TOKEN}, self.NUMERIC))
        cancel = self.bodies()["request_cancel"]
        message = json.dumps(self.tool_call(cancel, ident="ID")).encode()
        refused = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request", "data": {"status": "refused", "reason": "request_invalid"}}}
        before = self.state(exclude=())
        for label, ident, token in (
                ("an integer", self.NUMERIC, self.NUMERIC), ("a negative integer", "-" + self.NUMERIC, self.NUMERIC),
                ("a string of digits", json.dumps(self.NUMERIC), self.NUMERIC), ("JSON-escaped", '"\\u0031\\u0032' + self.NUMERIC[2:] + '"', self.NUMERIC),
                ("the token", json.dumps(of.OPERATOR_TOKEN), of.OPERATOR_TOKEN),
                ("percent-encoded", json.dumps(percent(of.OPERATOR_TOKEN)), of.OPERATOR_TOKEN),
                ("upper-case percent", json.dumps(percent(of.OPERATOR_TOKEN, upper=True)), of.OPERATOR_TOKEN),
                ("partly percent-encoded", json.dumps(percent(of.OPERATOR_TOKEN, every=3)), of.OPERATOR_TOKEN),
                ("percent-encoded twice", json.dumps(percent(percent(of.OPERATOR_TOKEN[:2])) + of.OPERATOR_TOKEN[2:]), of.OPERATOR_TOKEN),  # within the id's 200
                ("encoded inside other text", json.dumps("req-" + percent(of.OTHER_OPERATOR_TOKEN) + "-7"), of.OTHER_OPERATOR_TOKEN)):
            with self.subTest(label=label):
                self.logs.clear()
                answer, reply = self.exchange("/mcp", raw_body=message.replace(b'"ID"', ident.encode()))
                self.assertTrue(answer.startswith("HTTP/1.0 400 "), answer[:80])
                self.assertEqual(reply, refused)
                self.assert_absent(token, answer, reply)
                self.assertNotIn(json.loads(ident) if ident.startswith('"') and "\\" not in ident else ident, answer)  # nor the id as sent
                self.assertEqual(self.logs, ["operator:alice POST /mcp -> 400 None"])
        self.assertEqual(self.state(exclude=()), before)
        for ident in (7, "req-7", of.OPERATOR_TOKEN[:12], percent("request-seven"), int(self.NUMERIC[:-1])):
            with self.subTest(ident=ident):
                answer, reply = self.exchange("/mcp", {"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": {"name": "status", "arguments": {}}})
                self.assertEqual((reply["id"], reply["result"]["isError"]), (ident, False), answer[:200])
        answer, reply = self.exchange("/mcp", self.tool_call(cancel, ident="req-8"))
        self.assertEqual((reply["id"], json.loads(reply["result"]["content"][0]["text"])["status"]), ("req-8", "recorded"))

    def test_the_tool_text_is_redacted_before_it_is_nested_whatever_the_boundary_does(self) -> None:
        """The layer on its own, before the reply's own pass at the boundary
        (which also takes out a JSON-escaped token): the service's MCP answer
        as _mcp builds it, for a backend whose reply names the token, holds
        the token in no form in the nested text, and the text decodes to the
        redacted reply."""
        token = self.ESCAPING[0]
        creds = Credentials({"alice": of.OPERATOR_TOKEN}, token)
        backend = mock.Mock()
        backend.request_cancel.return_value = {"status": "refused", "reason": "request_invalid", "detail": f"/{token}: no value is allowed here"}
        service = OperatorService(backend, creds)
        code, answer, route = service._mcp(Principal("alice", "operator"), self.tool_call({"invocation_id": of.RUNNING, "reason": "stop"}))
        text = answer["result"]["content"][0]["text"]
        self.assertEqual((code, route, json.loads(text)), (200, "/mcp:request_cancel",
                                                           {"status": "refused", "reason": "request_invalid", "detail": "/[credential]: no value is allowed here"}))
        self.assert_absent(token, text)

    def test_an_id_whose_answer_would_be_written_with_a_token_is_refused_before_dispatch(self) -> None:
        """An MCP id that holds no configured token, but whose answer would
        be written with one — completed by the escape serialization writes
        before a quote, a backslash, a newline or a non-ASCII character, or
        by the quote it writes before the id or the quote and comma after —
        or that shows one only once a JSON escape it carries is decoded (the
        escape percent-encoded, as it is, percent-encoding inside it,
        escaped twice): each is refused as an invalid request with a null
        id, the call it names not made, and no byte of the answer nor the
        log holds the token. Beside each, the same call with an id one
        character off is made and its id echoed exactly. At the id's bound,
        an encoded one is refused at 199, 200 and 201 characters, an
        ordinary one echoed at 199 and 200 and refused at 201."""
        esc, quoted = "\\", 'credential-with-quote-"-12345'
        cancel = self.bodies()["request_cancel"]
        refused = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request", "data": {"status": "refused", "reason": "request_invalid"}}}
        for label, token, ident in (
                ("the escape before a quote", "credential-" + esc + '"-12345', 'credential-"-12345'),
                ("the escape before a backslash", "credential-" + esc * 2 + "-12345", "credential-" + esc + "-12345"),
                ("a newline's escape", "credential-" + esc + "n-12345", "credential-\n-12345"),
                ("a non-ASCII character's escape", "credential-" + esc + "u00e9-1234", "credential-" + chr(0xE9) + "-1234"),
                ("the quote before the id", '"abcdefghijklmnop', "abcdefghijklmnop"),
                ("the quote and comma after it", 'abcdefghijklmnop",', "abcdefghijklmnop"),
                ("a JSON escape, percent-encoded", quoted, quoted.replace('"', "%5Cu0022")),
                ("a JSON escape", quoted, quoted.replace('"', esc + "u0022")),
                ("percent-encoding inside a JSON escape", quoted, quoted.replace('"', esc + "u00%32%32")),
                ("a JSON escape, escaped", quoted, quoted.replace('"', esc * 2 + "u0022"))):
            with self.subTest(label=label):
                self.restart(Credentials({"alice": of.OPERATOR_TOKEN}, token))
                before = self.state(exclude=())
                self.logs.clear()
                answer, reply = self.exchange("/mcp", self.tool_call(cancel, ident=ident))
                self.assertTrue(answer.startswith("HTTP/1.0 400 "), answer[:80])
                self.assertEqual(reply, refused)
                self.assert_absent(token, answer, reply)
                self.assertEqual((self.logs, self.state(exclude=())), (["operator:alice POST /mcp -> 400 None"], before))
                control = ident[:-1] + ("6" if ident.endswith("5") else "q")
                answer, reply = self.exchange("/mcp", self.tool_call(cancel, ident=control))
                inner = self.decoded(reply["result"]["content"][0]["text"])
                self.assertEqual((reply["id"], inner["status"] in ("recorded", "replayed")), (control, True), answer[:200])
                self.assert_absent(token, answer, reply, inner)
        self.assertEqual(self.value("SELECT cancel_requested_by FROM invocations WHERE invocation_id = ?", of.RUNNING), "operator")  # a control's
        self.restart(Credentials({"alice": of.OPERATOR_TOKEN}, quoted))
        encoded = quoted.replace('"', "%5Cu0022")
        for n in (199, 200, 201):
            with self.subTest(length=n):
                self.assertEqual(self.exchange("/mcp", self.tool_call(cancel, ident="x" * (n - len(encoded)) + encoded))[1], refused)
                self.assertEqual(self.exchange("/mcp", self.tool_call(cancel, ident="x" * n))[1]["id"], "x" * n if n <= 200 else None)

    def test_a_value_its_answer_would_write_as_a_token_is_replaced_whole_the_answer_still_json(self) -> None:
        """Refusals echoing what the request carried — an unknown topic,
        whole; a body key the router refuses, inside its detail — where no
        value holds a configured token but the answer's text would: the
        quote written before the topic, or the quote and comma after it; the
        escape written before a quote in the key. Over REST and over MCP
        that value is replaced whole by [credential], never the text's bytes:
        both JSON layers still parse, to the refusal expected; no byte of the
        answer, neither decoded layer and not the log holds the token; and
        nothing changes. Escaped once more, as MCP nests the tool's text, an
        escape before an escaped quote makes a token only there: the tool's
        text replaces the value, while REST, whose text holds none, keeps it
        exactly. The control: the same calls without the echo are answered."""
        esc, topic = "\\", "x:abcdefghijklmnop"
        cancel = self.bodies()["request_cancel"]
        key = 'credential-"-12345'
        unknown = {"status": "refused", "reason": "unknown_topic", "detail": REDACTED}
        detail = f"router-commands#/$defs/cancel: /{key}: no value is allowed here"
        before = self.state(exclude=())
        for label, token, rest_call, tool, arguments, rest_expected, tool_expected in (
                ("the quote before a topic", '"' + topic, ("GET", f"/v1/status?topic={topic}"), "status", {"topic": topic}, unknown, unknown),
                ("the quote and comma after it", topic + '",', ("GET", f"/v1/status?topic={topic}"), "status", {"topic": topic}, unknown, unknown),
                ("the escape before a quote", "credential-" + esc + '"-12345', ("POST", "/v1/commands/request_cancel"), "request_cancel", {**cancel, key: 1},
                 {"status": "refused", "reason": "request_invalid", "detail": REDACTED}, {"status": "refused", "reason": "request_invalid", "detail": REDACTED}),
                ("the escape before an escaped quote, nested", "credential-" + esc * 3 + '"-12345', ("POST", "/v1/commands/request_cancel"), "request_cancel",
                 {**cancel, key: 1}, {"status": "refused", "reason": "request_invalid", "detail": detail},
                 {"status": "refused", "reason": "request_invalid", "detail": REDACTED})):
            with self.subTest(label=label):
                self.restart(Credentials({"alice": of.OPERATOR_TOKEN}, token))
                self.logs.clear()
                method, path = rest_call
                body = json.dumps(arguments).encode() if method == "POST" else b""
                rest_answer = raw_exchange(self.engine, f"{method} {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {of.OPERATOR_TOKEN}\r\n"
                                                        f"Content-Length: {len(body)}\r\n\r\n".encode() + body).decode("latin-1")
                rest = self.decoded(rest_answer.partition("\r\n\r\n")[2])
                mcp_answer, mcp = self.exchange("/mcp", self.tool_call(arguments, tool=tool))
                inner = self.decoded(mcp["result"]["content"][0]["text"])
                self.assertEqual((rest_answer[:13], rest, mcp["id"], inner, mcp["result"]["isError"]), ("HTTP/1.0 200 ", rest_expected, 1, tool_expected, True))
                self.assert_absent(token, rest_answer, rest)
                self.assert_absent(token, mcp_answer, mcp, inner)
                self.assertEqual(self.logs, [f"operator:alice {method} {path.partition('?')[0]} -> 200 refused", f"operator:alice POST /mcp:{tool} -> 200 None"])
                self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.http("GET", f"/v1/status?topic={rf.TOPIC}")[1]["status"], "ok")  # the controls
        control_answer, control = self.exchange("/mcp", self.tool_call(cancel))
        self.assertEqual(self.decoded(control["result"]["content"][0]["text"])["status"], "recorded", control_answer)

    def test_an_answer_no_redaction_of_its_values_writes_is_the_fixed_fault(self) -> None:
        """A token made of JSON's punctuation and the placeholder itself
        (`"[credential]"},`), which a reply whose redacted value closes an
        object before another member shows whatever is replaced: that
        answer is not written, over REST or MCP; the fixed fault is, 500,
        its line naming Unwritable. The same reply under another token is
        written, redacted (the control)."""
        reply = {"status": "refused", "reason": "request_invalid", "detail": {"key": of.OPERATOR_TOKEN}}
        cancel = self.bodies()["request_cancel"]
        for token in ('"[credential]"},', of.EXPORTER_TOKEN):
            with self.subTest(token=token):
                self.restart(Credentials({"alice": of.OPERATOR_TOKEN}, token))
                self.logs.clear()
                with mock.patch.object(self.engine.station.router, "request_cancel", return_value=reply):
                    rest_answer, rest = self.exchange("/v1/commands/request_cancel", cancel)
                    mcp_answer, mcp = self.exchange("/mcp", self.tool_call(cancel))
                if token == of.EXPORTER_TOKEN:
                    self.assertEqual((rest_answer[:13], rest), ("HTTP/1.0 200 ", {**reply, "detail": {"key": REDACTED}}))
                    self.assertEqual(self.decoded(mcp["result"]["content"][0]["text"]), rest)
                    continue
                fault = {"status": "error", "reason": "internal"}
                self.assertEqual((rest_answer[:13], rest, mcp_answer[:13], mcp), ("HTTP/1.0 500 ", fault, "HTTP/1.0 500 ", fault))
                self.assertEqual(self.logs, ["operator:alice POST /v1/commands/request_cancel -> 200 refused", "- POST /v1/commands/request_cancel -> 500 Unwritable",
                                             "- POST /mcp -> 500 Unwritable"])
                self.assert_absent(token, rest_answer + mcp_answer, rest, mcp)


class CredentialsTest(unittest.TestCase):
    ENV = {"GEN2_SECRETS": "env", "GEN2_OPERATOR_TOKENS": f"alice={of.OPERATOR_TOKEN}, bob={of.OTHER_OPERATOR_TOKEN}",
           "GEN2_SECRET_EXPORTER_TOKEN": of.EXPORTER_TOKEN}

    def test_the_mounted_names_configure_the_principals(self) -> None:
        creds = Credentials.from_environ(self.ENV)
        self.assertEqual(creds.principals, [Principal("alice", "operator"), Principal("bob", "operator"), Principal("exporter", "exporter")])
        self.assertEqual(creds.authenticate(f"Bearer {of.OTHER_OPERATOR_TOKEN}"), Principal("bob", "operator"))
        self.assertEqual(creds.authenticate(f"Bearer {of.EXPORTER_TOKEN}"), Principal("exporter", "exporter"))
        self.assertIsNone(Credentials.from_environ({**self.ENV, "GEN2_SECRET_EXPORTER_TOKEN": ""}).authenticate(f"Bearer {of.EXPORTER_TOKEN}"))

    def test_redact_takes_every_configured_token_out(self) -> None:
        """Wherever a configured token stands in a reply — a string, a key, a
        list, nested — it is replaced; a token that is another's prefix does
        not leave the longer one half-redacted; other text is kept."""
        long_token = of.OPERATOR_TOKEN + "-and-more"
        creds = Credentials({"alice": of.OPERATOR_TOKEN, "carol": long_token}, of.EXPORTER_TOKEN)
        reply = {"detail": f"/{long_token}: no value is allowed here", of.EXPORTER_TOKEN: [f"x{of.OPERATOR_TOKEN}y", {"k": of.EXPORTER_TOKEN}], "n": 5,
                 "kept": "op-token-mallory-0123456789abcdef"}
        self.assertEqual(creds.redact(reply), {"detail": "/[credential]: no value is allowed here", "[credential]": ["x[credential]y", {"k": "[credential]"}],
                                              "n": 5, "kept": "op-token-mallory-0123456789abcdef"})
        self.assertEqual(creds.redact(f"- POST {of.EXPORTER_TOKEN}"), "- POST [credential]")

    def test_redact_takes_out_each_form_a_reply_can_carry(self) -> None:
        """A token JSON-escaped inside JSON text is replaced where it stands;
        a string that shows one only percent-decoded (in any case, in part,
        twice) or JSON-unescaped (a `\\u0022` escape as it is, percent-encoded,
        percent-encoding inside it, escaped twice), one whose replacement
        makes another token, and a number whose digits hold one are replaced
        whole. What carries none — a prefix, other encoded or escaped text,
        another number, a boolean — is kept exactly (Astra 1e-repair
        re-review finding 2; 1e-repair-2 re-review finding 1)."""
        quoted, numeric = 'credential-with-quote-"-12345', "1234567890123456"
        creds = Credentials({"alice": of.OPERATOR_TOKEN, "carol": numeric}, quoted)
        nested = json.dumps({"detail": f"/{quoted}: no value is allowed here"})
        self.assertEqual(creds.redact(nested), json.dumps({"detail": "/[credential]: no value is allowed here"}))
        esc = "\\"
        carried = [percent(of.OPERATOR_TOKEN), percent(of.OPERATOR_TOKEN, upper=True), percent(of.OPERATOR_TOKEN, every=4),
                   percent(percent(of.OPERATOR_TOKEN)), f"id-{percent(quoted)}-1", percent(json.dumps(quoted)[1:-1]),
                   quoted.replace('"', esc + "u0022"), quoted.replace('"', "%5Cu0022"), quoted.replace('"', esc + "u00%32%32"),
                   quoted.replace('"', esc * 2 + "u0022"), int(numeric), -int(numeric), float(numeric)]
        self.assertEqual(creds.redact(carried), ["[credential]"] * len(carried))
        kept = [of.OPERATOR_TOKEN[:12], percent("request-seven"), "100%", "C:" + esc + "new", quoted.replace('"', esc + "u0027"),
                quoted.replace('"', "%5Cu0027"), int(numeric[:-1]), 5, 2.5, True, None]
        self.assertEqual(creds.redact(kept), kept)
        self.assertEqual([type(value) for value in creds.redact(kept)], [type(value) for value in kept])
        reformed = Credentials({"alice": of.OPERATOR_TOKEN, "carol": "x" + REDACTED + "yyy"})  # a token the replacement itself makes
        self.assertEqual(reformed.redact(["x" + of.OPERATOR_TOKEN + "yyy", "x" + of.OPERATOR_TOKEN + "yy"]), [REDACTED, "x[credential]yy"])

    def test_dumps_writes_no_token_its_serialization_would_make(self) -> None:
        """dumps() writes json.dumps's text, keys sorted, where that text
        shows no configured token (the control: every kind of value, near
        misses among them, written exactly). Where it would — the escape it
        writes before a quote or a non-ASCII character, a quote, brace or
        bracket it joins to a string, a key or a number — that value alone
        is replaced by [credential], and the text is still JSON. Nested, a
        text that shows one only once escaped into other JSON is checked so
        too, and written as it is when not nested."""
        esc = "\\"
        kept = {"a": ["bcdefghijklmnop", 5, 2.5, True, None, [], {}], "credential-'-12345": "credential-" + esc + "-12346", "x:abcdefghijklmnoq": chr(0xE9)}
        for token, value, written in (
                ("credential-" + esc + '"-12345', {"detail": 'credential-"-12345', "n": 1}, {"detail": REDACTED, "n": 1}),
                ("credential-" + esc + "u00e9-1234", {"detail": "credential-" + chr(0xE9) + "-1234"}, {"detail": REDACTED}),
                ('"abcdefghijklmnop', {"detail": "abcdefghijklmnop", "n": 1}, {"detail": REDACTED, "n": 1}),
                ('abcdefghijklmnop"}', {"n": 1, "z": "abcdefghijklmnop"}, {"n": 1, "z": REDACTED}),
                ('{"abcdefghijklmnop', {"abcdefghijklmnop": 1, "b": 2}, {REDACTED: 1, "b": 2}),
                ("[[1234567890123456", {"n": [[1234567890123456, 1]]}, {"n": [[REDACTED, 1]]})):
            with self.subTest(token=token):
                creds = Credentials({"alice": of.OPERATOR_TOKEN}, token)
                self.assertEqual(creds.redact(value), value)  # no value holds it
                self.assertEqual(creds.dumps(value), json.dumps(written, sort_keys=True))
                self.assertEqual(creds.dumps(kept), json.dumps(kept, sort_keys=True))
        creds = Credentials({"alice": of.OPERATOR_TOKEN}, "credential-" + esc * 3 + '"-12345')
        value = {"detail": 'credential-"-12345'}
        self.assertEqual((creds.dumps(value), creds.dumps(value, nested=True)), (json.dumps(value), json.dumps({"detail": REDACTED})))

    def test_an_answer_left_showing_a_token_is_unwritable(self) -> None:
        """A token that REDACTED and the punctuation joined to it make
        (`"[credential]"},`) stands in the text whatever values are replaced:
        dumps() refuses to write it. The same value closed differently
        (`"[credential]"}}`) is written (the control)."""
        creds = Credentials({"alice": of.OPERATOR_TOKEN}, '"[credential]"},')
        with self.assertRaises(Unwritable):
            creds.dumps(creds.redact({"detail": {"key": of.OPERATOR_TOKEN}, "status": "refused"}))
        self.assertEqual(creds.dumps(creds.redact({"detail": {"key": of.OPERATOR_TOKEN}})), '{"detail": {"key": "[credential]"}}')

    def test_past_the_decoding_bound_a_text_counts_as_carrying_a_token(self) -> None:
        """A text with more decodings than MAX_DECODINGS is read no further
        and counts as carrying a token: redacted whole. With the bound at
        its decodings' number, it is read to the end and kept (the
        control). `%252525` has four: itself, `%2525`, `%25` and `%`."""
        creds = Credentials({"alice": of.OPERATOR_TOKEN})
        for bound, redacted in ((3, REDACTED), (4, "%252525")):
            with self.subTest(bound=bound), mock.patch.object(auth, "MAX_DECODINGS", bound):
                self.assertEqual(creds.redact("%252525"), redacted)

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
