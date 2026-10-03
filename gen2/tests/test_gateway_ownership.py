"""One owner of the gateway client's endpoint; a serial client; separate clients that run concurrently (task 2b-repair-17; Gate D #3 checklist 1 and 3; the operator's client model, 2026-10-03).

Gate D #3 found that whether the client may do I/O was several facts that could disagree: a mapping of cached addresses, a stale flag, the address list a connection already running
held on to, and urllib's proxy choice. Astra's R16-1 paused one search just before its socket was created, let a second caller's failing exchange withdraw the endpoint and an unrelated
listener take the old address, and the first search then connected to it and sent the bearer token. The operator's ruling is that an INSTANCE is serial and separate instances are not:
one operation at a time on a client, an overlapping or re-entrant call refused before any I/O, and clients of separate stations and jobs fully concurrent.

Each test here makes a loopback listener, or a hook at the exact step it names, the witness: what the listener was sent, which addresses the sockets were asked to connect to, which lookups
the resolver was asked for. The refused call is never trusted to say it did nothing. A kill must come as an assertion, so a call a mutant lets through is caught and failed, not left to raise.
"""
from __future__ import annotations

import socket
import threading
import time
import unittest
from unittest import mock

from gen2.gateway_client import client as gateway
from gen2.gateway_client.client import ClientBusy, GatewayClient, GrantRefused
from gen2.tests.gateway_wire import (EMPTY_AND_EXHAUSTED, EMPTY_LANE, FIND, INV, STAMP, TOKEN, Recorder, gateway_answer, gateway_script, job, lookup, observed, queued_answer,
                                     reply, unobserved)
from gen2.tests.loopback import ThreadsJoined

SEARCH = dict(invocation_id=INV, attempt=1, policy_version="gw-policy/1")
GRANT = dict(topic_id="topic_1", commercial=False, accept_per_item=False, invocation_id=INV)
FAST = dict(clock=lambda: STAMP, sleep=lambda s: time.sleep(min(s, 0.01)))   # a poll waits a hundredth of the half second it would


class Hold:
    """A point at which the operation under test waits for the test: the first arrival (after `after` others) sets `reached` and waits for `release`; every other call goes straight through."""

    def __init__(self, after: int = 0) -> None:
        self.reached, self.release, self._after, self._arrivals, self._lock = threading.Event(), threading.Event(), after, 0, threading.Lock()

    def __call__(self) -> None:
        with self._lock:
            self._arrivals += 1
            mine = self._arrivals == self._after + 1
        if mine:
            self.reached.set()
            self.release.wait(10)


class OwnershipTest(ThreadsJoined):
    def setUp(self) -> None:
        super().setUp()
        self._patches: list = []
        self.addCleanup(self.unwatch)

    def unwatch(self) -> None:
        """End what `watch` set up (a test with several schedules ends each one)."""
        while self._patches:
            self._patches.pop().stop()

    def watch(self, point: str | None = None, after: int = 0):
        """(what reached the network, the Hold): every address a client's socket was asked to connect to and every send, from every client; with `point` ("connect" or "send"), the operation
        that gets there is held until the test releases it."""
        hold, seen = Hold(after), {"connects": [], "sends": 0}

        def wrap(name):
            real = getattr(gateway._DeadlineSocket, name)   # the class's own method, so the deadline arming it does stays

            def watched(sock, *args):
                if name == "connect":
                    seen["connects"].append(args[0])
                else:
                    seen["sends"] += 1
                if point == {"connect": "connect", "sendall": "send"}[name]:
                    hold()
                return real(sock, *args)
            return watched
        for name in ("connect", "sendall"):
            patch = mock.patch.object(gateway._DeadlineSocket, name, wrap(name))
            patch.start()
            self._patches.append(patch)
        return seen, hold

    def running(self, call, release: threading.Event | None = None):
        """Run `call` in its own thread: (the thread, a dict that gets its `result` or its `error`). `release` is set when the test ends, so that nothing is left waiting on it."""
        box: dict = {}

        def body():
            try:
                box["result"] = call()
            except BaseException as e:   # the test reads it; a thread that dies silently would only read as a timeout
                box["error"] = e
        thread = threading.Thread(target=body, name="operation under test")
        thread.start()
        self.addCleanup(lambda: ((release.set() if release else None), thread.join(10)))
        return thread, box

    def refused(self, call):
        """The ClientBusy `call` raises. Anything else is a failure of the test, and so is a call that runs: a mutant that lets it through must be caught here, by assertion."""
        try:
            call()
        except ClientBusy as busy:
            return busy
        except BaseException as other:
            self.fail(f"the overlapping call was not refused with ClientBusy; it raised {other!r}")
        self.fail("the overlapping call ran")

    def gateway(self, *, then_nothing: bool = False, **kw) -> tuple:
        """(a client of a gateway that is a NAME, the listener behind it, its resolver): the lookup is made at construction, as the deployment's `http://gateway:8765` is. With `then_nothing`
        every lookup after that one finds nothing, so that a `resolve` which ran would withdraw the endpoint."""
        listener = Recorder(self, gateway_script(**kw))
        found = lookup("127.0.0.1", port=listener.port)

        def resolver(host, port, *rest):
            answer = found(host, port)
            return answer if len(found.calls) == 1 or not then_nothing else []
        resolver.calls = found.calls
        return GatewayClient(f"http://gateway.test:{listener.port}", TOKEN, resolver=resolver, **FAST), listener, resolver


def operations(c: GatewayClient) -> dict:
    """Every way a second caller can come at an instance: the three public operations, and the private exchange Astra's R16-1 probe called."""
    return {"search": lambda: c.search(FIND, **{**SEARCH, "attempt": 2}), "grant": lambda: c.grant(**GRANT), "resolve": c.resolve,
            "exchange": lambda: c._exchange("GET", "/v1/jobs/9", None, TOKEN)}


class OneOperationAtATime(OwnershipTest):
    """The instance is serial: while one operation runs, any other call on it, from another thread or from inside the operation, is refused before a lookup, a connection or a byte."""

    FIRST = {"search": lambda c: c.search(FIND, **SEARCH), "grant": lambda c: c.grant(**GRANT)}

    def overlap(self, point: str, first: str, second: str, *, poll: bool = False):
        """One schedule: `first` is held at `point`; `second` is attempted from this thread; what the refusal changed, and how `first` ends."""
        c, listener, resolver = self.gateway(poll=poll, then_nothing=True)   # a `resolve` that ran would find nothing and withdraw the endpoint, under the exchange about to use it
        seen, hold = self.watch(point, after=1 if poll else 0)
        thread, box = self.running(lambda: self.FIRST[first](c), hold.release)
        self.assertTrue(hold.reached.wait(5), f"{first} did not reach {point}")

        def state():
            return (list(seen["connects"]), seen["sends"], listener.count, len(resolver.calls), c.last_resolution, c.endpoint_stale)
        before = state()
        busy = self.refused(operations(c)[second])
        self.assertEqual(state(), before, f"{second} was refused, and still changed something: connections, sends, requests the listener got, lookups, the last resolution, the endpoint")
        hold.release.set()
        thread.join(10)
        self.assertNotIn("error", box, f"{first} did not end normally")
        self.unwatch()
        return busy, box["result"], seen, listener, c

    def test_an_overlapping_call_is_refused_before_connect_and_before_send_whatever_the_operation_and_whatever_it_would_have_done(self):
        """R16-1's schedules: the running operation is held just before its connect (the point Astra's trace paused at) and after its connect, before its send, and a second call comes from
        every door. Each is refused (the message names what is running); none is sent a byte; the lookup the refused `resolve` would have made, which finds nothing and would withdraw the
        endpoint under the exchange about to use it, is never made; and the first operation ends as it does alone."""
        for point in ("connect", "send"):
            for first in ("search", "grant"):
                for second in ("search", "grant", "resolve", "exchange"):
                    with self.subTest(point=point, first=first, second=second):
                        busy, result, seen, listener, c = self.overlap(point, first, second)
                        self.assertIn(f"running {first}", str(busy))
                        self.assertEqual(listener.count, 1, "the listener was sent the first operation's one request and nothing else")
                        self.assertEqual(len(seen["connects"]), 1)
                        self.assertFalse(c.endpoint_stale)
                        if first == "search":
                            self.assertEqual(observed(result), EMPTY_AND_EXHAUSTED)
                        else:
                            self.assertEqual(result["token"], "gwg1.synthetic")

    def test_a_call_during_a_poll_is_refused_too(self):
        """A search owns the client across its pages and its polls: held at the connect of its poll (its second connection), a second call is refused with nothing sent, and the poll is answered."""
        for second in ("search", "grant", "resolve", "exchange"):
            with self.subTest(second=second):
                busy, result, seen, listener, c = self.overlap("connect", "search", second, poll=True)
                self.assertIn("running search", str(busy))
                self.assertEqual((listener.request_lines, len(seen["connects"])), (["POST /v1/find HTTP/1.1", "GET /v1/jobs/1 HTTP/1.1"], 2))
                self.assertEqual(observed(result), EMPTY_AND_EXHAUSTED)

    def test_control_the_same_operations_run_alone_and_a_search_then_a_grant_then_a_resolve_follow_each_other(self):
        """The control the refusals are measured against: no overlap, each operation one request (a resolve none), all of them accepted one after another by one client."""
        c, listener, resolver = self.gateway()
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
        self.assertEqual(c.grant(**GRANT)["token"], "gwg1.synthetic")
        self.assertEqual((c.resolve().addresses, c.endpoint_stale), (("127.0.0.1",), False))
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
        self.assertEqual((listener.count, len(resolver.calls)), (3, 2), "three requests, and the lookups were the construction's and the one resolve")

    def test_a_call_during_a_resolution_is_refused_before_any_lookup_or_byte(self):
        """The third schedule: a `resolve` is running, held inside the resolver. Every other call is refused: no second lookup, no connection, no request. When the lookup returns its addresses are
        published and the client works."""
        listener = Recorder(self, gateway_script())
        inside, release, calls = threading.Event(), threading.Event(), []

        def resolver(host, port, *rest):
            calls.append((host, port))
            if len(calls) == 2:   # the construction's was the first
                inside.set()
                release.wait(10)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", listener.port))]
        c = GatewayClient(f"http://gateway.test:{listener.port}", TOKEN, resolver=resolver, **FAST)
        seen, _ = self.watch()
        thread, box = self.running(c.resolve, release)
        self.assertTrue(inside.wait(5))
        before = (len(calls), listener.count, list(seen["connects"]), seen["sends"], c.last_resolution)
        for second, call in operations(c).items():
            with self.subTest(second=second):
                self.assertIn("running resolve", str(self.refused(call)))
        self.assertEqual((len(calls), listener.count, list(seen["connects"]), seen["sends"], c.last_resolution), before, "the refused calls looked nothing up and sent nothing")
        release.set()
        thread.join(10)
        self.assertEqual((box["result"].addresses, box["result"].error, c.endpoint_stale), (("127.0.0.1",), None, False))
        self.assertEqual((observed(c.search(FIND, **SEARCH)), listener.count, len(calls)), (EMPTY_AND_EXHAUSTED, 1, 2))

    def test_a_call_from_inside_an_operation_is_refused_too(self):
        """Re-entry: a hook the operation calls (the clock, the sleep between polls, the resolver) calls back into the client. Each re-entrant call is refused and the operation that was
        running finishes, with nothing sent for the re-entrant call."""
        outcomes, holder = [], []

        def call_back(what):
            if holder:
                try:
                    (holder[0].search(FIND, **SEARCH) if what != "resolve" else holder[0].resolve())
                    outcomes.append((what, "ran"))
                except ClientBusy:
                    outcomes.append((what, "refused"))
        answers = iter([reply(job("running")), reply(job("done", [EMPTY_LANE]))])

        def script(server, conn, head, body, index):
            server.send(conn, [(0, queued_answer() if head.startswith(b"POST") else next(answers))])
        listener = Recorder(self, script)
        c = GatewayClient(f"http://gateway.test:{listener.port}", TOKEN, resolver=lookup("127.0.0.1", port=listener.port),
                          clock=lambda: (call_back("clock"), STAMP)[1], sleep=lambda s: call_back("sleep"))
        holder.append(c)
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
        self.assertEqual(listener.request_lines, ["POST /v1/find HTTP/1.1", "GET /v1/jobs/1 HTTP/1.1", "GET /v1/jobs/1 HTTP/1.1"], "the search's own POST and two polls: the re-entrant calls added none")
        self.assertTrue(outcomes and all(how == "refused" for _, how in outcomes), outcomes)
        self.assertEqual({what for what, _ in outcomes}, {"clock", "sleep"})
        outcomes.clear()
        self.assertEqual(listener.count, 3)
        holder.clear()
        resolving = lookup("127.0.0.1", port=listener.port)

        def reentrant_resolver(host, port, *rest):
            call_back("resolve")
            return resolving(host, port)
        d = GatewayClient(f"http://gateway.test:{listener.port}", TOKEN, resolver=reentrant_resolver, **FAST)
        holder.append(d)
        d.resolve()
        self.assertEqual(outcomes, [("resolve", "refused")], "a lookup that calls back into its own client is refused: the resolve that was running ends, and nothing else looked anything up")
        self.assertEqual(resolving.calls, [("gateway.test", listener.port)] * 2, "the construction's lookup (made before the client could be re-entered) and the resolve's")

    def test_an_operation_that_ended_in_an_error_leaves_the_client_usable(self):
        """Ownership is released however the operation ends: a request that is not one (ValueError, before anything was sent), a grant the gateway refused, an operation a hook broke."""
        c, listener, _ = self.gateway()
        with self.assertRaises(ValueError):
            c.search({"request_type": "bogus"}, **SEARCH)
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED, "after a ValueError")
        broken = GatewayClient(f"http://gateway.test:{listener.port}", TOKEN, resolver=lookup("127.0.0.1", port=listener.port), clock=mock.Mock(side_effect=[STAMP, RuntimeError("a hook broke")]))
        with self.assertRaises(RuntimeError):
            broken.search(FIND, **SEARCH)
        broken._clock = lambda: STAMP
        self.assertEqual(observed(broken.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED, "after an operation a hook broke")
        refusing = Recorder(self, lambda server, conn, head, body, index: server.send(conn, [(0, reply(b'{"error": "not a grantor"}', "403 Forbidden"))]))
        g = GatewayClient(f"http://127.0.0.1:{refusing.port}", TOKEN, **FAST)
        with self.assertRaises(GrantRefused):
            g.grant(**GRANT)
        with self.assertRaises(GrantRefused):
            g.grant(**GRANT)   # not ClientBusy: the second grant ran, and was refused by the gateway
        self.assertEqual(refusing.count, 2)

    def test_the_refusal_is_the_callers_error_and_never_an_observation(self):
        """A refused search must not become a durable `transport_failure` observation of a gateway that was never asked: it raises, and the instance's own search ends as it would have."""
        self.assertTrue(issubclass(ClientBusy, RuntimeError))
        c, listener, _ = self.gateway()
        seen, hold = self.watch("connect")
        thread, box = self.running(lambda: c.search(FIND, **SEARCH), hold.release)
        self.assertTrue(hold.reached.wait(5))
        with self.assertRaises(ClientBusy) as why:
            c.search(FIND, **SEARCH)
        self.assertIn("one operation at a time", str(why.exception))
        hold.release.set()
        thread.join(10)
        self.assertEqual((observed(box["result"]), listener.count), (EMPTY_AND_EXHAUSTED, 1))


class TheEndpointIsOneFact(OwnershipTest):
    """R15-1, R16-1 and R16-2 are one defect: authority was kept in several places. These are Astra's reproductions, as maintained regressions, over the schedules that remain possible."""

    def withdrawn_by_its_own_failure(self, poll: bool):
        """R16-1's schedule with the second caller refused: A is held before its (first, or for a poll, second) connect, the gateway goes away, a second caller is refused, and A resumes to find nothing
        there. A's failure withdraws the endpoint; an unrelated listener then takes the old address, and no later call sends it anything, nor a token."""
        original = Recorder(self, gateway_script(poll=poll))
        port = original.port
        found = [("127.0.0.1", port)]

        def resolver(host, called_port, *rest):
            if not found:
                raise socket.gaierror(socket.EAI_NONAME, "synthetic NXDOMAIN")
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", found[0])]
        c = GatewayClient(f"http://gateway.test:{port}", TOKEN, resolver=resolver, deadline=0.3, **FAST)
        seen, hold = self.watch("connect", after=1 if poll else 0)
        thread, box = self.running(lambda: c.search(FIND, **SEARCH), hold.release)
        self.assertTrue(hold.reached.wait(5))
        original.server.stop()   # the gateway is gone while the operation is between choosing its address and connecting to it
        connections = list(seen["connects"])
        for second, call in operations(c).items():
            with self.subTest(second=second):
                self.refused(call)
        self.assertEqual((c.endpoint_stale, list(seen["connects"])), (False, connections), "a second caller could not withdraw the endpoint, nor connect")
        hold.release.set()
        thread.join(10)
        self.assertNotIn("error", box)
        self.assertTrue(c.endpoint_stale, "the operation's own failed connection withdrew the endpoint")
        replacement = Recorder(self, gateway_script(), port=port)   # an unrelated listener at the old address
        used = len(seen["connects"])
        found.clear()
        self.assertTrue(c.resolve().error.startswith("gaierror"), "the owner's lookup finds nothing: NXDOMAIN")
        for _ in range(2):
            self.assertEqual(observed(c.search(FIND, **SEARCH)), unobserved("transport_failure"))
        self.assertEqual((replacement.count, replacement.carrying(), len(seen["connects"]) - used), (0, 0, 0), "no connection, no request and no token reached the unrelated listener")
        return c, found, box["result"], seen, port

    def test_astras_r16_1_probe_a_search_held_before_its_connect_cannot_be_overtaken_by_a_withdrawal(self):
        c, found, result, seen, port = self.withdrawn_by_its_own_failure(poll=False)
        self.assertEqual(observed(result), unobserved("transport_failure"))
        moved = Recorder(self, gateway_script())   # the move-to-B control: the owner finds the name at a new address and the client goes there
        found[:] = [("127.0.0.1", moved.port)]
        self.assertEqual((c.resolve().error, c.endpoint_stale), (None, False))
        self.assertEqual((observed(c.search(FIND, **SEARCH)), moved.count), (EMPTY_AND_EXHAUSTED, 1))

    def test_astras_r16_1_probe_the_same_for_a_poll(self):
        """The queued variant: the submission reached the gateway, the poll is the held operation. After it the unrelated listener gets nothing; and the poll that failed is the last connection made."""
        c, found, result, seen, port = self.withdrawn_by_its_own_failure(poll=True)
        self.assertEqual(observed(result), unobserved("timeout"), "the job never finished by the deadline: nothing observed, never empty")
        self.assertEqual(len(seen["connects"]), 2, "the submission and the one poll that failed to connect; every later poll sent nothing")

    def test_control_a_search_held_at_the_same_points_with_the_gateway_there_ends_as_it_does_alone(self):
        """No withdrawal in the schedule: the original listener answers the held search, its one request carries the token, and the endpoint was never stale. (R16-1's no-withdrawal controls.)"""
        for point, poll in (("connect", False), ("send", False), ("connect", True)):
            with self.subTest(point=point, poll=poll):
                c, listener, _ = self.gateway(poll=poll)
                seen, hold = self.watch(point, after=1 if poll else 0)
                thread, box = self.running(lambda: c.search(FIND, **SEARCH), hold.release)
                self.assertTrue(hold.reached.wait(5))
                hold.release.set()
                thread.join(10)
                self.unwatch()
                self.assertEqual((observed(box["result"]), listener.count, listener.carrying(), c.endpoint_stale), (EMPTY_AND_EXHAUSTED, 2 if poll else 1, 2 if poll else 1, False))

    def test_astras_r16_2_probe_an_ambient_proxy_does_not_carry_a_search_to_a_withdrawn_origin(self):
        """R16-2 in Astra's order, the proxy configuration constant throughout: a search succeeds, the origin fails to connect, the owner's lookup finds nothing, an unrelated listener takes the old
        address, and a search is made again. The environment names a proxy the whole time; the proxy is sent nothing, ever, the unrelated listener is sent nothing, and the later search is refused as
        it is with `no_proxy` naming the host, the direct control (R16-2: on 6b44bb2 the proxy forwarded it and the answer was accepted as `searched_empty/complete/0/exhausted`)."""
        proxy = Recorder(self)
        environment = {"http_proxy": f"http://127.0.0.1:{proxy.port}", "no_proxy": ""}
        with mock.patch.dict("os.environ", environment):
            original = Recorder(self, gateway_script())
            port, found = original.port, [("127.0.0.1", original.port)]

            def resolver(host, called_port, *rest):
                if not found:
                    raise socket.gaierror(socket.EAI_NONAME, "synthetic NXDOMAIN")
                return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", found[0])]
            c = GatewayClient(f"http://gateway.test:{port}", TOKEN, resolver=resolver, timeout=1, **FAST)
            seen, _ = self.watch()
            self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED, "the origin answers directly: the proxy named in the environment is no route")
            original.server.stop()
            self.assertEqual(observed(c.search(FIND, **SEARCH)), unobserved("transport_failure"))
            found.clear()
            self.assertTrue(c.resolve().error.startswith("gaierror"))
            replacement = Recorder(self, gateway_script(), port=port)
            used = len(seen["connects"])
            self.assertEqual(observed(c.search(FIND, **SEARCH)), unobserved("transport_failure"))
            with mock.patch.dict("os.environ", {"no_proxy": "gateway.test"}):
                self.assertEqual(observed(c.search(FIND, **SEARCH)), unobserved("transport_failure"), "the direct control")
        self.assertEqual((proxy.count, replacement.count, replacement.carrying(), len(seen["connects"]) - used, c.endpoint_stale), (0, 0, 0, 0, True))


class ConnectionLifetimes(OwnershipTest):
    """Bounded lifetimes: one connection per exchange, closed with it, never kept past the authority that opened it; every address of an endpoint tried inside the one exchange's deadline."""

    @staticmethod
    def dead_ports(n: int = 1) -> list:
        """n different ports nothing listens on: the connect to each is refused."""
        held = [socket.socket() for _ in range(n)]
        for sock in held:
            sock.bind(("127.0.0.1", 0))
        ports = [sock.getsockname()[1] for sock in held]
        for sock in held:
            sock.close()
        return ports

    def multi(self, *ports: int, port: int | None = None, **kw):
        """A client of the name `gateway.test` whose lookup finds these loopback sockets, in this order."""
        def resolver(host, called_port, *rest):
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", p)) for p in ports]
        return GatewayClient(f"http://gateway.test:{port or ports[0]}", TOKEN, resolver=resolver, **FAST, **kw)

    def test_a_later_address_is_tried_when_an_earlier_one_refuses_and_the_endpoint_stays_authorized(self):
        live, [dead] = Recorder(self, gateway_script()), self.dead_ports()
        seen, _ = self.watch()
        c = self.multi(dead, live.port)
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
        self.assertEqual([port for _, port in seen["connects"]], [dead, live.port], "the refusing address first, then the one that answers")
        self.assertEqual((live.count, c.endpoint_stale), (1, False), "failing over is not a failed exchange: nothing withdrawn")
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)

    def test_control_the_first_address_answering_leaves_the_others_untried(self):
        live, [dead] = Recorder(self, gateway_script()), self.dead_ports()
        seen, _ = self.watch()
        c = self.multi(live.port, dead)
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
        self.assertEqual([port for _, port in seen["connects"]], [live.port])

    def test_every_address_refusing_is_one_failed_exchange_which_withdraws_the_endpoint(self):
        first, second = self.dead_ports(2)
        seen, _ = self.watch()
        c = self.multi(first, second)
        self.assertEqual(observed(c.search(FIND, **SEARCH)), unobserved("transport_failure"))
        self.assertEqual([port for _, port in seen["connects"]], [first, second], "each address once, in order")
        self.assertTrue(c.endpoint_stale)
        self.assertEqual(observed(c.search(FIND, **SEARCH)), unobserved("transport_failure"))
        self.assertEqual(len(seen["connects"]), 2, "withdrawn: the next search connected to nothing")

    def test_an_ip_literal_endpoint_is_never_looked_up_and_never_withdrawn(self):
        """The literal's address is its own (Gate D #3: no mapping to revoke): a failed connection leaves it usable, a listener that appears at it is contacted, and no lookup is ever made."""
        first = Recorder(self, gateway_script())
        port = first.port
        refuse = mock.Mock(side_effect=AssertionError("a literal was looked up"))
        c = GatewayClient(f"http://127.0.0.1:{port}", TOKEN, resolver=refuse, **FAST)
        seen, _ = self.watch()
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
        first.server.stop()
        self.assertEqual(observed(c.search(FIND, **SEARCH)), unobserved("transport_failure"))
        self.assertFalse(c.endpoint_stale)
        second = Recorder(self, gateway_script(), port=port)
        self.assertEqual((observed(c.search(FIND, **SEARCH)), second.count, second.carrying()), (EMPTY_AND_EXHAUSTED, 1, 1), "the literal address is the endpoint: whatever listens there is contacted")
        self.assertEqual(c.resolve().addresses, ("127.0.0.1",))
        refuse.assert_not_called()
        self.assertEqual(len(seen["connects"]), 3)

    def test_a_timeout_does_not_withdraw_and_a_timely_reply_follows(self):
        """A slow answer is not a gone gateway (the accepted policy, Astra's repair-16 review): the first reply takes longer than the exchange's budget, the next is prompt, and the client goes on without a lookup."""
        def script(server, conn, head, body, index):
            if index == 1:
                server.pause(3)
            else:
                server.send(conn, [(0, gateway_answer())])
        listener = Recorder(self, script)
        resolver = lookup("127.0.0.1", port=listener.port)
        c = GatewayClient(f"http://gateway.test:{listener.port}", TOKEN, resolver=resolver, timeout=0.3, **FAST)
        self.assertEqual(observed(c.search(FIND, **SEARCH)), unobserved("timeout"))
        self.assertEqual((c.endpoint_stale, len(resolver.calls)), (False, 1))
        self.assertEqual(observed(c.search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
        self.assertEqual((listener.count, len(resolver.calls)), (2, 1), "recovered on its own: no lookup, one request each")

    def test_no_socket_outlives_its_exchange(self):
        """Every socket a client creates is closed when its exchange ends, whichever way: an answer, a refused connection, a timeout, every address failing; and nothing is left running (ThreadsJoined)."""
        made: list = []

        class Spy(gateway._DeadlineSocket):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                made.append(self)
        live, [dead], [dead_a, dead_b] = Recorder(self, gateway_script()), self.dead_ports(), self.dead_ports(2)
        slow = Recorder(self, lambda server, conn, head, body, index: server.pause(3))
        with mock.patch.object(gateway, "_DeadlineSocket", Spy):
            self.assertEqual(observed(self.multi(live.port).search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
            self.assertEqual(observed(self.multi(dead, live.port).search(FIND, **SEARCH)), EMPTY_AND_EXHAUSTED)
            self.assertEqual(observed(self.multi(dead_a, dead_b).search(FIND, **SEARCH)), unobserved("transport_failure"))
            self.assertEqual(observed(self.multi(slow.port, timeout=0.2).search(FIND, **SEARCH)), unobserved("timeout"))
        self.assertEqual(len(made), 6, "one for each address tried: 1, 2, 2 and the one that timed out")
        self.assertEqual([s.fileno() for s in made], [-1] * 6, "every socket closed")


class SeparateClientsRunConcurrently(OwnershipTest):
    """The operator's condition: "as long as concurrent connections can run". Many stations and jobs each have their own client and talk to the gateway at once; nothing serializes them: no lock shared
    between instances, no global opener, no module state. The witness is the SERVER: it holds every reply until it has seen all N requests in flight together, so a client that waited for another
    (or was refused because of another) could not have been there."""

    N = 8

    def gateway_seeing_overlap(self, *, polls: bool):
        flight = {"now": 0, "most": 0, "polls": 0}
        lock, all_in = threading.Lock(), threading.Event()

        def script(server, conn, head, body):
            held = head.startswith(b"GET") if polls else True
            if polls and head.startswith(b"POST"):
                server.send(conn, [(0, queued_answer())])
                return
            if held:
                with lock:
                    flight["now"] += 1
                    flight["most"] = max(flight["most"], flight["now"])
                    if flight["now"] >= self.N:
                        all_in.set()
                all_in.wait(5)
            server.send(conn, [(0, reply(job("done", [EMPTY_LANE])) if polls else gateway_answer())])
            if held:
                with lock:
                    flight["now"] -= 1
        return self.serve(script), flight, all_in

    def test_clients_against_one_gateway_have_requests_in_flight_together(self):
        for polls in (False, True):
            with self.subTest(polls=polls):
                server, flight, all_in = self.gateway_seeing_overlap(polls=polls)
                start, results = threading.Barrier(self.N, timeout=5), {}

                def client(i: int):
                    # half of them a name (each its own lookup), half a literal: separate instances either way
                    url = f"http://127.0.0.1:{server.port}" if i % 2 else f"http://gateway.test:{server.port}"
                    c = GatewayClient(url, TOKEN, resolver=lookup("127.0.0.1", port=server.port), **FAST)
                    start.wait()
                    try:
                        results[i] = observed(c.search(FIND, **SEARCH))
                    except BaseException as e:
                        results[i] = repr(e)
                threads = [threading.Thread(target=client, args=(i,), name=f"client {i}") for i in range(self.N)]
                began = time.monotonic()
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(15)
                self.assertTrue(all_in.is_set(), f"the server never had all {self.N} requests in flight at once (most: {flight['most']})")
                self.assertEqual((flight["most"], time.monotonic() - began < 5), (self.N, True))
                self.assertEqual(results, {i: EMPTY_AND_EXHAUSTED for i in range(self.N)}, "every client's search completed: none was refused, none waited")

    def test_clients_resolve_at_the_same_time(self):
        """The lookups of separate clients overlap too: every resolver waits at a barrier for the others, which a lookup that waited for another client's could not pass."""
        barrier, results = threading.Barrier(self.N, timeout=5), {}

        def resolver(host, port, *rest):
            if resolver.armed:
                barrier.wait()
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port))]
        resolver.armed = False
        clients = [GatewayClient("http://gateway.test:1", TOKEN, resolver=resolver, **FAST) for _ in range(self.N)]
        resolver.armed = True

        def run(i):
            try:
                results[i] = clients[i].resolve().addresses
            except BaseException as e:
                results[i] = repr(e)
        threads = [threading.Thread(target=run, args=(i,), name=f"resolve {i}") for i in range(self.N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(results, {i: ("127.0.0.1",) for i in range(self.N)})

    def test_an_operation_running_on_one_client_does_not_refuse_another_client(self):
        """The ruling's other half, as one schedule: A is held mid-operation; a second client of the very same URL runs a whole search, a grant and a resolve meanwhile."""
        a, listener, _ = self.gateway()
        b = GatewayClient(a.base_url, TOKEN, resolver=lookup("127.0.0.1", port=listener.port), **FAST)
        seen, hold = self.watch("connect")
        thread, box = self.running(lambda: a.search(FIND, **SEARCH), hold.release)
        self.assertTrue(hold.reached.wait(5))
        self.assertEqual((observed(b.search(FIND, **SEARCH)), b.grant(**GRANT)["token"], b.resolve().addresses), (EMPTY_AND_EXHAUSTED, "gwg1.synthetic", ("127.0.0.1",)))
        hold.release.set()
        thread.join(10)
        self.assertEqual((observed(box["result"]), listener.count), (EMPTY_AND_EXHAUSTED, 3), "A's search, and B's search and grant")

    def test_one_clients_withdrawal_reaches_no_other_client(self):
        """Two clients of one name (one URL, one port) whose lookups found different addresses: A's connection fails and withdraws A's endpoint; B's is untouched and B's search is answered."""
        live = Recorder(self, gateway_script())
        [dead] = ConnectionLifetimes.dead_ports()
        url = f"http://gateway.test:{live.port}"
        a = GatewayClient(url, TOKEN, resolver=lookup("127.0.0.1", port=dead), **FAST)
        b = GatewayClient(url, TOKEN, resolver=lookup("127.0.0.1", port=live.port), **FAST)
        self.assertEqual(observed(a.search(FIND, **SEARCH)), unobserved("transport_failure"))
        self.assertEqual((a.endpoint_stale, b.endpoint_stale), (True, False))
        self.assertEqual((observed(b.search(FIND, **SEARCH)), live.count), (EMPTY_AND_EXHAUSTED, 1))
        self.assertEqual(b.resolve().addresses, ("127.0.0.1",))
        self.assertTrue(a.endpoint_stale, "and B's resolve changed nothing of A's")

    def test_operations_write_no_module_state(self):
        """What the module holds, fingerprinted before and after a client's whole life (a search, a grant, a failed connection, a resolve, a refused overlap): unchanged. No global is a place
        for one client to leave something another reads."""
        def fingerprint():
            return {name: repr(value) for name, value in vars(gateway).items()
                    if not name.startswith("__") and not callable(value) and not isinstance(value, type(gateway))}
        before = fingerprint()
        c, listener, _ = self.gateway()
        c.search(FIND, **SEARCH)
        c.grant(**GRANT)
        listener.server.stop()
        c.search(FIND, **SEARCH)
        c.resolve()
        self.assertEqual(fingerprint(), before)
        self.assertGreater(len(before), 3, "the fingerprint looked at something")


if __name__ == "__main__":
    unittest.main()
