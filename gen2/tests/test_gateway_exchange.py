"""One deadline over the whole exchange (task 2b-repair-13d; Astra R13B-1), against real loopback sockets.

The 13b review reproduced a poll taking 0.5 s under a 0.2 s deadline, and a `done` reply that completed after
the deadline persisted as `searched_empty/complete/exhausted`: the transport's timeout was a per-socket-operation
one, which a reply arriving a chunk at a time renews forever, and nothing checked the clock once a terminal reply
was in hand. A transport that already honours the timeout it is handed (every fake in test_gateway_client.PollDeadline)
cannot certify either, so these tests make the SERVER slow, in each blocking step of an exchange: the connect, the
request, the status line and headers, the body; the same reply is then timely, to show the bound is no refusal of
slow answers. Servers and their threads are test-owned, and a test ends with none left running (loopback.ThreadsJoined).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from gen2.gateway_client import observe
from gen2.gateway_client import client as gateway
from gen2.gateway_client.client import GatewayClient, http_transport
from gen2.tests.loopback import Loopback, ThreadsJoined
from gen2.tests.router_fixtures import RouterTestCase

INV = "inv_discover1"
STAMP = "2026-09-27T10:00:00Z"
CAPTURED = {"invocation_id": INV, "attempt": 1, "captured": True, "call_ref": 1}
DEADLINE = 0.5          # seconds; the bound under test
SLACK = 1.0             # what a loaded machine may add to it; the verdicts rest on the result (a timeout, not a reply), and a stall this long is not scheduling
FIND = {"request_type": "find", "query": "synthetic", "lanes": ["crossref"]}
EMPTY_LANE = {"source": "crossref", "coverage": "searched_empty", "completeness": "complete", "count": 0, "retrieved": [], "exhausted": True}
HEAD = ("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nX-Research-Gateway: result\r\n"
        "Content-Length: {}\r\nConnection: close\r\n\r\n")


def job(status: str, lanes=None) -> bytes:
    return json.dumps({"status": status, "observation": CAPTURED, "result": {"lanes": lanes if lanes is not None else [], "records": []}},
                      separators=(",", ":")).encode()


def reply(body: bytes) -> bytes:
    return HEAD.format(len(body)).encode() + body


def pieces(data: bytes, n: int) -> list[bytes]:
    return [data[i * len(data) // n:(i + 1) * len(data) // n] for i in range(n)]


def trickle(data: bytes, n: int, gap: float, first: float = 0.0) -> list[tuple[float, bytes]]:
    """`data` in n pieces, the first after `first` seconds and each other one `gap` seconds after the last: every wait is
    far inside any per-operation timeout the client was given, and the whole of it is not inside the deadline."""
    return [(first if i == 0 else gap, piece) for i, piece in enumerate(pieces(data, n))]


def answers(poll_schedule):
    """A script for the gateway's two doors: a POST is queued at once; a GET (a poll) is sent as `poll_schedule` says."""
    def script(server, conn, head, body):
        if head.startswith(b"POST"):
            server.send(conn, [(0, reply(json.dumps({"status": "queued", "job_id": 1, "observation": CAPTURED}).encode()))])
        else:
            server.send(conn, poll_schedule)
    return script


class ExchangeTest(ThreadsJoined):
    def timed(self, call):
        start = time.monotonic()
        result = call()
        return result, time.monotonic() - start

    def assertEndsAtTheDeadline(self, elapsed: float) -> None:
        self.assertGreaterEqual(elapsed, DEADLINE - 0.02, "it gave up before the deadline")
        self.assertLess(elapsed, DEADLINE + SLACK, "it ran on past the deadline")

    def exchange(self, server: Loopback, body: bytes | None = None, deadline: float = DEADLINE, method: str = "GET", scheme: str | None = None):
        url = server.url if scheme is None else f"{scheme}://127.0.0.1:{server.port}"
        return self.timed(lambda: http_transport(method, url + "/v1/jobs/1", {"Accept": "application/json"}, body, deadline))

    def poll(self, server: Loopback, deadline: float = DEADLINE):
        c = GatewayClient(server.url, "synthetic", deadline=deadline, timeout=130)
        return self.timed(lambda: c._poll(1, {"token": "synthetic", "invocation_id": INV, "attempt": 1}))


class EveryBlockingStepIsBounded(ExchangeTest):
    """The same deadline, with the server slow in each step in turn (http_transport itself, whose timeout is 130 s
    in production: here the exchange's whole budget is 0.3)."""

    def test_a_server_that_never_answers_stops_at_the_deadline(self):
        server = self.serve(lambda s, conn, head, body: s.pause(30))
        (status, headers, raw, error), elapsed = self.exchange(server)
        self.assertEqual((status, raw, error), (None, b"", "timeout"))
        self.assertEndsAtTheDeadline(elapsed)

    def test_a_status_line_and_headers_that_come_a_few_bytes_at_a_time_stop_at_the_deadline(self):
        data = reply(job("done"))
        head = data[:data.index(b"\r\n\r\n") + 4]
        server = self.serve(lambda s, conn, h, b: s.send(conn, trickle(head, 24, 0.05) + [(0, data[len(head):])]))
        (status, headers, raw, error), elapsed = self.exchange(server)
        self.assertEqual((status, raw, error), (None, b"", "timeout"), "a reply whose head took 1.15 s is no answer to a 0.3 s exchange")
        self.assertEndsAtTheDeadline(elapsed)

    def test_a_body_that_comes_slowly_stops_at_the_deadline(self):
        data = reply(job("done"))
        head = data[:data.index(b"\r\n\r\n") + 4]
        server = self.serve(lambda s, conn, h, b: s.send(conn, [(0, head)] + trickle(data[len(head):], 6, 0.2)))
        (status, headers, raw, error), elapsed = self.exchange(server)
        self.assertEqual((status, raw, error), (None, b"", "timeout"), "the status was 200, and still there is no answer")
        self.assertEndsAtTheDeadline(elapsed)

    def test_a_reply_that_trickles_in_one_chunk_inside_each_timeout_stops_at_the_deadline(self):
        """Astra's reproduction: six chunks 0.1 s apart under a 0.2 s timeout took 0.5 s and was returned whole (here, twelve under 0.4 s)."""
        server = self.serve(lambda s, conn, h, b: s.send(conn, trickle(reply(job("done")), 12, 0.1)))
        (status, headers, raw, error), elapsed = self.exchange(server, deadline=0.4)
        self.assertEqual((status, raw, error), (None, b"", "timeout"))
        self.assertGreaterEqual(elapsed, 0.38)
        self.assertLess(elapsed, 0.4 + SLACK)

    def test_a_connect_that_never_completes_stops_at_the_deadline(self):
        """A listener whose accept queue is full drops further connection attempts: the connect hangs."""
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(0)
        held = []
        for _ in range(4):   # fill the queue; the next attempt waits for a place that never comes
            filler = socket.socket()
            filler.setblocking(False)
            filler.connect_ex(listener.getsockname())
            held.append(filler)
        self.addCleanup(lambda: [s.close() for s in held])
        probe = socket.socket()
        probe.settimeout(0.3)
        self.addCleanup(probe.close)
        with self.assertRaises(TimeoutError, msg="this machine completes a connect to a full queue: the case cannot be made"):
            probe.connect(listener.getsockname())
        (status, headers, raw, error), elapsed = self.timed(lambda: http_transport(
            "GET", f"http://127.0.0.1:{listener.getsockname()[1]}/v1/jobs/1", {}, None, DEADLINE))
        self.assertEqual((status, raw, error), (None, b"", "timeout"))
        self.assertEndsAtTheDeadline(elapsed)

    def test_a_request_the_server_never_reads_stops_at_the_deadline(self):
        """The send blocks when the socket buffers are full; a body larger than they are takes the whole of it."""
        server = self.serve(lambda s, conn, h, b: s.pause(30), read=False)
        (status, headers, raw, error), elapsed = self.exchange(server, body=b"x" * (64 * 1024 * 1024), method="POST")
        self.assertEqual((status, raw, error), (None, b"", "timeout"))
        self.assertEndsAtTheDeadline(elapsed)

    def test_control_the_same_reply_is_read_when_it_is_timely(self):
        """The bound refuses no slow answer that is inside it: the trickling reply, with room to arrive."""
        data = reply(job("done"))
        server = self.serve(lambda s, conn, h, b: s.send(conn, trickle(data, 8, 0.02)))
        (status, headers, raw, error), elapsed = self.exchange(server, deadline=5.0)
        self.assertEqual((status, error, json.loads(raw)["status"]), (200, None, "done"))
        self.assertLess(elapsed, 2.0)


class EachCallIsGivenWhatIsLeft(ExchangeTest):
    """The mechanism, one call at a time: after time has passed with nothing happening, a call that would block ends at the
    deadline, not a whole timeout after the last call. (Each case is idle for 0.5 s of a 0.6 s deadline: a call that kept
    the timeout it was last armed with would end at 1.1 s.)"""
    DEADLINE, IDLE = 0.6, 0.5

    def connected(self, server: Loopback) -> tuple:
        started = time.monotonic()
        deadline = gateway._Deadline(self.DEADLINE)
        sock = gateway._connect(("127.0.0.1", server.port), deadline)
        self.addCleanup(sock.close)
        time.sleep(self.IDLE)
        return sock, deadline, started

    def blocked(self, call, server_reads: bool) -> None:
        server = self.serve(lambda s, conn, h, b: s.pause(30), read=server_reads)
        sock, _, started = self.connected(server)
        with self.assertRaises(TimeoutError):
            call(sock)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, self.DEADLINE - 0.02)
        self.assertLess(elapsed, self.DEADLINE + 0.35, "it was given a fresh timeout, not what was left")

    def test_recv(self):
        self.blocked(lambda sock: sock.recv(10), False)

    def test_recv_into(self):
        self.blocked(lambda sock: sock.recv_into(bytearray(10)), False)

    def test_control_recv_returns_what_arrives_with_time_left(self):
        """The accepted path through `recv` (task 2b-repair-15; Astra's control for the recv-not-armed mutant, which she supplied by hand because no exchange calls it: http.client reads through
        recv_into): a peer that sends inside the deadline is read, whole, by a call armed with what is left."""
        server = self.serve(lambda s, conn, h, b: s.send(conn, [(0, b"OK")]), read=False)
        sock = gateway._connect(("127.0.0.1", server.port), gateway._Deadline(5.0))
        self.addCleanup(sock.close)
        self.assertEqual(sock.recv(2), b"OK")

    def test_send(self):
        def send_until_full(sock):
            while True:
                sock.send(b"x" * 65536)
        self.blocked(send_until_full, False)

    def test_sendall(self):
        self.blocked(lambda sock: sock.sendall(b"x" * (64 * 1024 * 1024)), False)

    def test_control_send_sends_with_time_left(self):
        """The accepted path through `send` (as for recv: no exchange calls it, http.client writes through sendall): a peer that reads inside the deadline is sent what it is given."""
        received, got = [], threading.Event()

        def read_two(s, conn, h, b):
            received.append(conn.recv(2))
            got.set()
        server = self.serve(read_two, read=False)
        sock = gateway._connect(("127.0.0.1", server.port), gateway._Deadline(5.0))
        self.addCleanup(sock.close)
        self.assertEqual(sock.send(b"OK"), 2)
        self.assertTrue(got.wait(5.0), "the peer never read it")
        self.assertEqual(received, [b"OK"])

    def test_the_time_a_connect_took_comes_out_of_what_a_handshake_may_take(self):
        """A connect that takes 0.2 s of 0.5 leaves the socket armed with the 0.3 s that are left, which is what the TLS
        handshake that follows runs under."""
        server = self.serve(lambda s, conn, h, b: s.pause(30), read=False)

        def slow_connect(sock, target, real=gateway._DeadlineSocket.connect):
            time.sleep(0.2)
            real(sock, target)
        with mock.patch.object(gateway._DeadlineSocket, "connect", slow_connect):
            sock = gateway._connect(("127.0.0.1", server.port), gateway._Deadline(0.5))
        self.addCleanup(sock.close)
        self.assertLess(sock.gettimeout(), 0.31)

    def test_no_step_starts_after_the_deadline(self):
        """Nothing is begun, name resolution included, once the budget is spent."""
        with mock.patch("socket.getaddrinfo", side_effect=AssertionError("a name was resolved after the deadline")):
            self.assertEqual(http_transport("GET", "http://gateway.invalid:8765/v1/jobs/1", {}, None, 0), (None, {}, b"", "timeout"))


class ALateReplyIsATimeout(ExchangeTest):
    """The client over the real transport, polling (Astra's slow-exchange and late-done probes): a terminal reply that
    completes after the deadline is the same timeout as one that never comes."""

    def test_a_late_terminal_reply_is_a_timeout(self):
        server = self.serve(answers(trickle(reply(job("done")), 20, 0.1)))   # 1.9 s of a 0.5 s deadline
        got, elapsed = self.poll(server, deadline=0.5)
        self.assertEqual(got, (None, None), "a `done` that arrived at 1.9 s is not a result of a poll that ended at 0.5")
        self.assertLess(elapsed, 0.5 + SLACK)

    def test_a_late_reply_that_is_not_terminal_is_a_timeout(self):
        server = self.serve(answers(trickle(reply(job("running")), 20, 0.1)))
        got, elapsed = self.poll(server, deadline=0.5)
        self.assertEqual(got, (None, None))
        self.assertLess(elapsed, 0.5 + SLACK)

    def test_a_reply_inside_the_deadline_is_read(self):
        server = self.serve(answers(trickle(reply(job("done")), 6, 0.01)))
        (finished, mine), elapsed = self.poll(server, deadline=5.0)
        self.assertEqual((finished["status"], mine["call_ref"]), ("done", 1))
        self.assertLess(elapsed, 2.0)

    def test_the_search_that_waits_for_a_late_terminal_reply_observes_a_timeout_and_nothing_else(self):
        server = self.serve(answers(trickle(reply(job("done", [EMPTY_LANE])), 20, 0.1)))
        c = GatewayClient(server.url, "synthetic", deadline=0.5, clock=lambda: STAMP)
        out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        [only] = out["observations"]
        o = only["observation"]
        self.assertEqual((o["coverage_state"], o["completeness"], o["result_count"], o["error_class"], o["page_outcome"], o["continuation"]),
                         ("unknown", "unobserved", None, "timeout", "failed", None))
        self.assertEqual(only["retrieval_events"], [])


class ALateReplyReachesNoDurableEnd(RouterTestCase):
    """Astra's late-done probe through the real router: before, the reply that arrived at 0.5 s of a 0.2 s deadline was
    recorded as `searched_empty/complete/exhausted`."""

    def setUp(self) -> None:
        super().setUp()
        self.to_scoping()
        self.grant = self.started(INV, "discovery")

    def test_a_late_done_is_a_recorded_timeout_never_an_empty_exhausted_search(self):
        with ThreadsJoinedServer(answers(trickle(reply(job("done", [EMPTY_LANE])), 20, 0.1))) as server:
            c = GatewayClient(server.url, "synthetic", deadline=0.5, clock=lambda: STAMP)
            out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        replies = [getattr(self.router, name)(request) for name, request in
                   observe.router_requests(out, capability_id=self.grant["capability_id"], invocation_id=INV)]
        self.assertEqual([r["status"] for r in replies], ["recorded"])
        self.assertEqual(self.rows("SELECT coverage_state, completeness, result_count, error_class, page_outcome, continuation FROM search_observations"),
                         [("unknown", "unobserved", None, "timeout", "failed", None)])


class ThreadsJoinedServer:
    """A server as a context manager, for a test that is not a ThreadsJoined one."""

    def __init__(self, script) -> None:
        self.server = Loopback(script)

    def __enter__(self) -> Loopback:
        return self.server

    def __exit__(self, *exc) -> None:
        self.server.stop()


@unittest.skipUnless(shutil.which("openssl"), "a TLS server needs a certificate, which the openssl command line makes")
class TlsExchangeIsBoundedToo(ExchangeTest):
    """The same bound over TLS: the handshake runs under the time that was left, and a TLS socket's reads and writes are
    armed with what is left of it, one call at a time, as the plain socket's are."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = Path(tempfile.mkdtemp(prefix="gen2-tls-"))
        cls.cert, cls.key = str(cls.dir / "cert.pem"), str(cls.dir / "key.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", cls.key, "-out", cls.cert],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.dir, ignore_errors=True)

    def trusting(self):
        patch = mock.patch.dict(os.environ, {"SSL_CERT_FILE": self.cert})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_handshake_that_never_completes_stops_at_the_deadline(self):
        server = self.serve(lambda s, conn, h, b: s.pause(30), read=False)   # plain TCP: it accepts and never says a word of TLS
        (status, headers, raw, error), elapsed = self.exchange(server, scheme="https")
        self.assertEqual((status, raw, error), (None, b"", "timeout"))
        self.assertEndsAtTheDeadline(elapsed)

    def test_a_tls_reply_that_trickles_stops_at_the_deadline(self):
        self.trusting()
        server = self.serve(lambda s, conn, h, b: s.send(conn, trickle(reply(job("done")), 12, 0.1)), tls=(self.cert, self.key))
        (status, headers, raw, error), elapsed = self.exchange(server, deadline=0.4)
        self.assertEqual((status, raw, error), (None, b"", "timeout"))
        self.assertGreaterEqual(elapsed, 0.38)
        self.assertLess(elapsed, 0.4 + SLACK)

    def test_a_tls_request_the_server_never_reads_stops_at_the_deadline_after_a_slow_handshake(self):
        """The handshake takes 1.0 s of a 1.5 s deadline, and then the request, larger than the buffers, blocks: a send that
        kept the timeout the handshake ran under would end at 2.5 s."""
        self.trusting()
        server = self.serve(lambda s, conn, h, b: s.pause(30), read=False, tls=(self.cert, self.key), handshake_after=1.0)
        (status, headers, raw, error), elapsed = self.exchange(server, body=b"x" * (64 * 1024 * 1024), method="POST", deadline=1.5)
        self.assertEqual((status, raw, error), (None, b"", "timeout"))
        self.assertGreaterEqual(elapsed, 1.48)
        self.assertLess(elapsed, 1.5 + 0.5)

    def test_control_a_timely_tls_reply_is_read(self):
        self.trusting()
        server = self.serve(lambda s, conn, h, b: s.send(conn, trickle(reply(job("done")), 8, 0.02)), tls=(self.cert, self.key))
        (status, headers, raw, error), elapsed = self.exchange(server, deadline=5.0)
        self.assertEqual((status, error, json.loads(raw)["status"]), (200, None, "done"))
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
