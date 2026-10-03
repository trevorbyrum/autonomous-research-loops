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
from gen2.tests.gateway_wire import CAPTURED, EMPTY_LANE, FIND, INV, STAMP, admitted, gateway_answer, job, lookup, reply
from gen2.tests.loopback import Loopback, ThreadsJoined
from gen2.tests.router_fixtures import RouterTestCase

DEADLINE = 0.5          # seconds; the bound under test
SLACK = 1.0             # what a loaded machine may add to it; the verdicts rest on the result (a timeout, not a reply), and a stall this long is not scheduling


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
        return self.timed(lambda: http_transport(method, url + "/v1/jobs/1", {"Accept": "application/json"}, body, deadline, admitted=admitted(server.port)))

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
            "GET", f"http://127.0.0.1:{listener.getsockname()[1]}/v1/jobs/1", {}, None, DEADLINE, admitted=admitted(listener.getsockname()[1])))
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
        sock = gateway._connect(deadline, admitted(server.port))
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
        sock = gateway._connect(gateway._Deadline(5.0), admitted(server.port))
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
        sock = gateway._connect(gateway._Deadline(5.0), admitted(server.port))
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
            sock = gateway._connect(gateway._Deadline(0.5), admitted(server.port))
        self.addCleanup(sock.close)
        self.assertLess(sock.gettimeout(), 0.31)

    def test_no_step_starts_after_the_deadline(self):
        """Nothing is begun once the budget is spent (and no exchange resolves a name at all: `NoExchangeResolvesAName`)."""
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


class NoExchangeResolvesAName(ExchangeTest):
    """Task 2b-repair-15 (Astra's final 2b review, F2). `_connect` called a synchronous getaddrinfo, which cannot be interrupted: a substituted resolver that took 0.4 s made a 0.05 s exchange
    take 0.423 s, and the client-level probe 0.418 s. An exchange now resolves no name at all: an IP literal is its own address, a name was looked up beforehand by the client's owner (at
    construction, or `resolve()` between operations), and a name that was not is a transport failure at once. No resolver here touches the network: each is a stand-in.

    Task 2b-repair-16 (Astra's 2b-repair-15 review, R15-1): an endpoint known to be stale is not connected to. A connection failure, and a lookup that found nothing, withdraw the addresses the
    last good lookup found; until the owner's `resolve()` finds some, an exchange makes no connection and sends no request, so no bearer token reaches whatever now answers at the old address."""

    def connections(self) -> tuple:
        """(the targets the client's sockets were asked to connect to, the patch that records them): what a stale endpoint must leave empty."""
        made, real = [], socket.socket.connect

        def spy(sock, target):
            made.append(target)
            return real(sock, target)
        return made, mock.patch.object(gateway._DeadlineSocket, "connect", spy)

    @staticmethod
    def slow(delay: float):
        def resolve(*args):
            resolve.calls.append(args)
            time.sleep(delay)
            return []
        resolve.calls = []
        return resolve

    def test_astras_probe_a_slow_resolver_no_longer_extends_the_transports_exchange(self):
        resolve = self.slow(0.4)
        with mock.patch.object(gateway.socket, "getaddrinfo", side_effect=resolve):
            (result, elapsed) = self.timed(lambda: http_transport("GET", "http://synthetic.invalid/v1/jobs/1", {}, None, 0.05))
        self.assertEqual(result, (None, {}, b"", "transport_failure"))
        self.assertLess(elapsed, 0.2, "on c0d963d this took 0.423 s")
        self.assertEqual(resolve.calls, [], "no name was resolved")

    def test_astras_probe_a_slow_resolver_no_longer_extends_the_clients_exchange(self):
        """The client-level probe: the lookup the client's construction made (outside any exchange, and as slow as its resolver) is not repeated by an exchange."""
        resolve = self.slow(0.4)
        with mock.patch.object(gateway.socket, "getaddrinfo", side_effect=resolve):
            c, built = self.timed(lambda: GatewayClient("http://synthetic.invalid", "synthetic", timeout=0.05))
            looked_up = len(resolve.calls)
            answer, elapsed = self.timed(lambda: c._exchange("GET", "/v1/jobs/1", None, "synthetic"))
        self.assertEqual(answer, (None, None, "transport_failure"))
        self.assertLess(elapsed, 0.2, "on c0d963d this took 0.418 s")
        self.assertEqual(len(resolve.calls), looked_up, "the exchange resolved nothing")
        self.assertEqual((looked_up, built >= 0.38), (1, True), "the construction made the one lookup and waited for it: that time is the constructor's, before any exchange")

    def test_an_ip_literal_is_never_resolved(self):
        server = self.serve(lambda s, conn, h, b: s.send(conn, [(0, reply(job("done")))]))
        refuse = mock.Mock(side_effect=AssertionError("a name was resolved for an IP literal"))
        with mock.patch.object(gateway.socket, "getaddrinfo", refuse):
            c = GatewayClient(server.url, "synthetic", resolver=refuse)
            status, doc, error = c._exchange("GET", "/v1/jobs/1", None, "synthetic")
            self.assertEqual((status, error, doc["status"]), (200, None, "done"))
            self.assertEqual(c.resolve().addresses, ("127.0.0.1",), "and the owner's resolve() of an address is no lookup either")
        self.assertIsNone(c.last_resolution.error)
        refuse.assert_not_called()
        self.assertFalse(c.endpoint_stale)

    def test_both_kinds_of_ip_literal_are_their_own_address(self):
        self.assertEqual(gateway._literal("127.0.0.1", 80), [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 80))])
        self.assertEqual(gateway._literal("::1", 80), [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("::1", 80, 0, 0))])
        for name in ("gateway", "gateway.test", "localhost", "1.2.3", "300.1.1.1", ""):
            with self.subTest(name):
                self.assertIsNone(gateway._literal(name, 80), "a name is not an address")

    def test_a_name_that_was_looked_up_beforehand_is_connected_to_and_stays_the_hosts_name(self):
        seen = []
        server = self.serve(lambda s, conn, h, b: (seen.append(h), s.send(conn, [(0, reply(job("done")))])))
        resolve = lookup("127.0.0.1", port=server.port)
        c = GatewayClient(f"http://Gateway.Test:{server.port}", "synthetic", resolver=resolve)
        self.assertEqual(resolve.calls, [("gateway.test", server.port)], "looked up once, at construction, under the name it was given in its canonical (lower-case) form")
        for _ in range(3):
            status, doc, error = c._exchange("GET", "/v1/jobs/1", None, "synthetic")
            self.assertEqual((status, error, doc["status"]), (200, None, "done"))
        self.assertEqual(len(resolve.calls), 1, "three exchanges made no lookup")
        self.assertTrue(all(f"Host: gateway.test:{server.port}".encode() in head for head in seen), "the request still names the host (as the canonical origin spells it), not the address")
        self.assertEqual((c.last_resolution.host, c.last_resolution.addresses, c.last_resolution.error), ("gateway.test", ("127.0.0.1",), None))

    def test_the_deployment_contracts_gateway_url_is_looked_up_once_at_construction_and_a_given_transport_is_not_the_clients_to_resolve_for(self):
        resolve = lookup("10.0.0.5")
        c = GatewayClient("http://gateway:8765", "synthetic", resolver=resolve)
        self.assertEqual(resolve.calls, [("gateway", 8765)])
        self.assertEqual(c.last_resolution.addresses, ("10.0.0.5",))
        self.assertFalse(c.endpoint_stale)
        other = lookup("10.0.0.5")
        GatewayClient("http://gateway:8765", "synthetic", resolver=other, transport=lambda *a: (None, {}, b"", "timeout"))
        self.assertEqual(other.calls, [], "a test's transport has no use for an address")

    def test_a_name_that_was_never_looked_up_is_a_failed_exchange_at_once_and_nothing_is_resolved(self):
        resolve = self.slow(0.4)
        with mock.patch.object(gateway.socket, "getaddrinfo", side_effect=resolve):
            result, elapsed = self.timed(lambda: http_transport("GET", "http://gateway:8765/v1/jobs/1", {}, None, 5.0))
        self.assertEqual(result, (None, {}, b"", "transport_failure"))
        self.assertLess(elapsed, 0.2)
        self.assertEqual(resolve.calls, [])

    def test_a_connection_failure_marks_the_endpoint_stale_and_only_the_owners_resolve_looks_again(self):
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        dead_port = dead.getsockname()[1]
        dead.close()   # a port nothing listens on: the connect is refused
        server = self.serve(lambda s, conn, h, b: s.send(conn, [(0, reply(job("done")))]))
        in_flight, answers_ = [], [("127.0.0.1", dead_port)]
        real = gateway.http_transport

        def wrapped(*args, **kwargs):
            in_flight.append(True)
            try:
                return real(*args, **kwargs)
            finally:
                in_flight.pop()
        calls = []

        def resolve(host, port, *rest):
            calls.append(("resolved", host, port, "inside an exchange" if in_flight else "outside"))
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", answers_[0])]
        with mock.patch.object(gateway, "http_transport", wrapped):
            c = GatewayClient(f"http://gateway:{dead_port}", "synthetic", resolver=resolve)
            self.assertFalse(c.endpoint_stale)
            self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic"), (None, None, "transport_failure"))
            self.assertTrue(c.endpoint_stale, "a connection that failed invites a new lookup")
            c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1", pages=2)   # a whole search over the dead endpoint: every exchange fails
            self.assertEqual(calls, [("resolved", "gateway", dead_port, "outside")], "nothing looked up again: not by the exchanges, not by the search that retried them")
            answers_[0] = ("127.0.0.1", server.port)   # the gateway's service moved: the name now has another address (and port) to find; the configured endpoint is fixed (2b-repair-17)
            record = c.resolve()
            self.assertEqual(calls[1:], [("resolved", "gateway", dead_port, "outside")], "the owner's call, between operations, for the configured name")
            self.assertEqual((record.addresses, record.error, c.endpoint_stale), (("127.0.0.1",), None, False))
            self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic")[0], 200)
        self.assertEqual(len(calls), 2)

    def test_a_failed_lookup_leaves_the_client_built_and_stale_and_every_exchange_a_failure_at_once(self):
        def gone(*args):
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        c = GatewayClient("http://gateway:8765", "synthetic", resolver=gone)
        self.assertTrue(c.endpoint_stale)
        self.assertEqual((c.last_resolution.addresses, c.last_resolution.error.split(":")[0]), ((), "gaierror"))
        answer, elapsed = self.timed(lambda: c._exchange("GET", "/v1/jobs/1", None, "synthetic"))
        self.assertEqual(answer, (None, None, "transport_failure"))
        self.assertLess(elapsed, 0.2)
        self.assertTrue(c.endpoint_stale)

    def test_a_lookup_that_finds_nothing_withdraws_the_addresses_and_no_request_reaches_the_old_one(self):
        """Reversed in 2b-repair-16 (this test required the old addresses to stay in use, which sent the bearer token to whatever answered at the last good address): a lookup that finds nothing
        leaves the endpoint stale and without addresses, the old listener is not connected to, and the search is unobserved with no count."""
        seen = []
        server = self.serve(lambda s, conn, h, b: (seen.append(h), s.send(conn, [(0, gateway_answer())])))
        found = [server.port]
        c = GatewayClient("http://gateway:8765", "synthetic-token", clock=lambda: STAMP,
                          resolver=lambda host, port, *rest: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", p)) for p in found])
        self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic-token")[0], 200)
        self.assertIn(b"Authorization: Bearer synthetic-token", seen[0], "the first exchange did carry the token: the listener would have seen it")
        found.clear()
        record = c.resolve()
        self.assertEqual((record.addresses, c.endpoint_stale), ((), True))
        self.assertIn("resolved to no address", record.error)
        made, spying = self.connections()
        with spying:
            out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        [only] = out["observations"]
        o = only["observation"]
        self.assertEqual((o["coverage_state"], o["completeness"], o["result_count"], o["error_class"], o["page_outcome"]), ("unknown", "unobserved", None, "transport_failure", "failed"))
        self.assertEqual((made, len(seen)), ([], 1), "the old address got no connection and no request: where the last good lookup found the gateway is no longer known to be the gateway")

    def test_astras_probe_an_unrelated_listener_at_the_old_address_receives_no_request_after_a_failed_lookup(self):
        """Astra's R15-1 probe, as a regression (on 0d53bfc the last search connected to the old address, sent it the bearer token, and recorded its answer as `searched_empty/complete/0/exhausted`):
        a gateway answers at an address and goes away (a connection failure), the owner's `resolve()` then finds nothing (NXDOMAIN), and a service that is not the gateway answers at that address.
        It receives no request; and when a lookup finds the name at a new address, that is where the client goes."""
        phase, seen = ["gateway"], []

        def script(s, conn, head, body):
            seen.append((phase[0], head))
            if phase[0] != "gone":   # the gateway that was here has gone away: its address accepts, reads and closes, saying nothing
                s.send(conn, [(0, gateway_answer())])
        old = self.serve(script)
        moved = self.serve(lambda s, conn, h, b: s.send(conn, [(0, gateway_answer())]))
        found = [old.port]

        def resolve(host, port, *rest):
            if not found:
                raise socket.gaierror(socket.EAI_NONAME, "synthetic NXDOMAIN")
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", found[0]))]
        c = GatewayClient("http://gateway.test:8765", "synthetic-token", clock=lambda: STAMP, resolver=resolve)
        self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic-token")[0], 200)
        phase[0] = "gone"
        self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic-token"), (None, None, "transport_failure"))
        self.assertTrue(c.endpoint_stale)
        found.clear()
        self.assertTrue(c.resolve().error.startswith("gaierror"))
        phase[0] = "unrelated"
        made, spying = self.connections()
        with spying:
            out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        [only] = out["observations"]
        o = only["observation"]
        self.assertEqual((o["coverage_state"], o["completeness"], o["result_count"], o["error_class"], o["page_outcome"], o["continuation"]),
                         ("unknown", "unobserved", None, "transport_failure", "failed", None))
        self.assertEqual((only["retrieval_events"], out["pages"][0]["call_ref"]), ([], None), "no capture reference: nothing answered")
        self.assertEqual(made, [], "no connection was made")
        self.assertEqual([who for who, head in seen if who == "unrelated"], [], "and the unrelated listener received no request, and no token")
        found[:] = [moved.port]
        self.assertEqual((c.resolve().error, c.endpoint_stale), (None, False))
        [again] = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")["observations"]
        o = again["observation"]
        self.assertEqual((o["coverage_state"], o["completeness"], o["result_count"], o["page_outcome"]), ("searched_empty", "complete", 0, "exhausted"), "the move to a new address works")
        self.assertEqual([who for who, head in seen if who == "unrelated"], [])

    def test_a_connection_failure_withdraws_the_addresses_until_the_owners_resolve_succeeds(self):
        """No failed lookup is needed: the connection that failed is enough. Until the owner's `resolve()` finds the name again (the same address here: still the gateway, now answering),
        every exchange fails at once with no connection, and nothing looked the name up on its own."""
        served = []

        def script(s, conn, head, body):
            served.append(head)
            if len(served) > 1:   # the first connection is dropped without an answer; every later one is answered
                s.send(conn, [(0, gateway_answer())])
        server = self.serve(script)
        resolve = lookup("127.0.0.1", port=server.port)
        c = GatewayClient("http://gateway.test:8765", "synthetic-token", resolver=resolve)
        self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic-token"), (None, None, "transport_failure"))
        self.assertTrue(c.endpoint_stale)
        made, spying = self.connections()
        with spying:
            for _ in range(3):
                self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic-token"), (None, None, "transport_failure"))
        self.assertEqual((made, len(served), len(resolve.calls)), ([], 1, 1), "no connection and no request while stale, and no lookup made by an exchange")
        self.assertEqual((c.resolve().error, c.endpoint_stale), (None, False))
        self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic-token")[0], 200)
        self.assertEqual(len(served), 2)


@unittest.skipUnless(shutil.which("openssl"), "a TLS server needs a certificate, which the openssl command line makes")
class TlsNamesAreChecked(ExchangeTest):
    """A name that was looked up beforehand is still the name TLS uses: the server name it sends (SNI) and the name its certificate is checked against are the host's, never the address
    the lookup found (2b-repair-15, Astra F2: keep TLS server-name checking correct)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = Path(tempfile.mkdtemp(prefix="gen2-tls-names-"))

        def certificate(name: str, san: str) -> tuple:
            cert, key = str(cls.dir / f"{name}-cert.pem"), str(cls.dir / f"{name}-key.pem")
            subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1", "-subj", "/CN=" + name,
                            "-addext", "subjectAltName=" + san, "-keyout", key, "-out", cert], check=True, capture_output=True)
            return cert, key
        cls.named, cls.addressed = certificate("gateway.test", "DNS:gateway.test"), certificate("addressed", "IP:127.0.0.1")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.dir, ignore_errors=True)

    def over_tls(self, certificate: tuple):
        """(the client, the server names the server was sent): a client of https://gateway.test whose lookup found 127.0.0.1, against a server holding `certificate`."""
        patch = mock.patch.dict(os.environ, {"SSL_CERT_FILE": certificate[0]})
        patch.start()
        self.addCleanup(patch.stop)
        server = self.serve(lambda s, conn, h, b: s.send(conn, [(0, reply(job("done")))]), tls=certificate)
        names = []
        server._tls.sni_callback = lambda sock, name, context: names.append(name)
        c = GatewayClient(f"https://gateway.test:{server.port}", "synthetic", resolver=lookup("127.0.0.1", port=server.port))
        return c, names

    def test_the_certificate_is_checked_against_the_hostname_and_the_server_name_sent_is_the_hostname(self):
        c, names = self.over_tls(self.named)
        status, doc, error = c._exchange("GET", "/v1/jobs/1", None, "synthetic")
        self.assertEqual((status, error, doc["status"]), (200, None, "done"))
        self.assertEqual(names, ["gateway.test"], "SNI is the name, not 127.0.0.1")

    def test_a_certificate_for_the_address_alone_is_refused_for_the_name(self):
        """The control that shows the check runs against the hostname: the same server, the same address, a certificate valid for 127.0.0.1 and not for gateway.test."""
        c, names = self.over_tls(self.addressed)
        self.assertEqual(c._exchange("GET", "/v1/jobs/1", None, "synthetic"), (None, None, "transport_failure"))
        self.assertEqual(names, ["gateway.test"])


if __name__ == "__main__":
    unittest.main()
