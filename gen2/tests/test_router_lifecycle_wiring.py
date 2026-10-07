"""The Router's wiring to its Lifecycle collaborator (task 2q-b6, Astra's 2q-b3b rulings 3 and 4): what the replay cannot settle for the paths it leaves unresolved
(the supervisor scenarios that start a real job process). Independent of the replay and of every other test of the lifecycle.

DelegateTest: each public route and each member the rest of the Router reads is a one-line delegate; a spy in the collaborator's place sees the call, with its arguments
and defaults, and its answer comes back unchanged.

TransactionTest: the lifecycle's two write routes run in the core's `_guarded`, as they did as a mixin. LockWait: this test's connection holds the write lock, a second
router with a clock the test sets is asked to act, and once it has issued BEGIN IMMEDIATE the clock moves from E-1ns to E: every instant the route records is E, the clock
read after the lock is won (the control, with the clock left alone, records E-1ns). Refusal: the store refuses the n-th write of a route, for each n: the route answers
`transition_not_allowed` ("the store refused the write") and every table, audit included, is as it was; with no refusal the same request is recorded.

Oracles: expected values by hand; the store read back with raw SQL. Limits: one interleaving, threads in one process; the refusing store is a double that refuses by
position, not by the DDL's own guards (those have their own suites).
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gen2.router import service
from gen2.store import api
from gen2.tests import router_crash_child  # not its World by name: the loader would collect it
from gen2.tests.router_fixtures import TOPIC, RouterTestCase

E = "2026-09-27T11:00:00Z"
E_MINUS = "2026-09-27T10:59:59.999999999Z"
IDENTITY = {"host_id": "host-1", "boot_id": "boot-1", "start_fingerprint": "ticks=1"}
DELEGATES = (  # name, arguments, keywords sent, keywords the collaborator must receive
    ("request_cancel", ({"r": 1},), {}, {}), ("reconcile", ({"r": 2},), {}, {}), ("invocation_status", ({"r": 3},), {}, {}),
    ("_evidence", ("inv", "hash"), {}, {}), ("_record_artifact", ("inv", "ev", "now"), {}, {}), ("_require_delegates_ended", ("inv",), {}, {}),
    ("_release_capacity", ("inv", "now", "why"), {}, {}), ("_open_unknown_hold", ("inv", 2, "cause", "now"), {}, {}), ("_cancel_in_transaction", ({"r": 4}, "now"), {}, {}),
    ("_bind_evidence", ("inv", "ev"), {}, {"failure_class": None, "terminal": True}),
    ("_bind_evidence", ("inv", "ev"), {"failure_class": "timeout", "terminal": False}, {"failure_class": "timeout", "terminal": False}),
)


class Spy:
    """In the collaborator's place: records every call and answers with the name it was called by."""

    def __init__(self) -> None:
        self.calls: list = []

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return ("answered", name)
        return call


class Refusing:
    """The router's store, refusing the write after `allowed` writes (an insert or an update); everything else is the real store's."""

    def __init__(self, store, allowed: int) -> None:
        self._store, self.allowed = store, allowed

    def __getattr__(self, name: str):
        member = getattr(self._store, name)
        if name not in ("insert", "update"):
            return member

        def write(*args, **kwargs):
            if self.allowed == 0:
                raise api.StoreWriteError("refused for the test")
            self.allowed -= 1
            return member(*args, **kwargs)
        return write


class DelegateTest(RouterTestCase):
    def test_each_delegate_forwards_its_call_to_the_collaborator_and_returns_its_answer(self) -> None:
        for name, args, sent, received in DELEGATES:
            with self.subTest(name=name, sent=sent):
                spy = self.router._lifecycle = Spy()
                self.assertEqual(getattr(self.router, name)(*args, **sent), ("answered", name))
                self.assertEqual(spy.calls, [(name, args, received)])


class TransactionTest(RouterTestCase):
    def refused_at_every_write(self, route: str, request: dict) -> tuple[int, dict]:
        """The route with the store refusing its first write, then its second, and so on until a run is not refused: each refusal is `transition_not_allowed` and leaves every
        table as it was. Returns how many writes the route made and the answer of the run that was allowed all of them."""
        before = self.state(exclude=())
        for position in range(50):
            router = service.Router(Refusing(self.store, position), self.spool, clock=self.clock, new_id=self.ids, fault=self.fault)
            try:
                out = getattr(router, route)(request)
            except Exception as exc:  # a write the store refused must come back as a refusal, not escape
                self.fail(f"write {position} refused: {type(exc).__name__} escaped the route: {exc}")
            if out["status"] != "refused":
                return position, out
            self.assertEqual(out["reason"], "transition_not_allowed", out)
            self.assertTrue(out["detail"].startswith("the store refused the write"), out)
            self.assertEqual(self.state(exclude=()), before, f"write {position} refused")
        self.fail("every run was refused")

    def test_a_cancellation_is_refused_whole_whichever_write_the_store_refuses(self) -> None:
        self.to_queued()
        self.claim("inv_research01")  # admitted: a cancellation ends it at once, releasing its lease and re-queueing its topic
        writes, out = self.refused_at_every_write("request_cancel", {"invocation_id": "inv_research01", "requested_by": "operator", "reason": "stop"})
        self.assertEqual((writes, out["status"]), (5, "cancelled"))  # the invocation, its transition row, its lease, its topic, the audit event
        self.assertEqual(self.value("SELECT state FROM invocations"), "cancelled")

    def test_a_reconciliation_is_refused_whole_whichever_write_the_store_refuses(self) -> None:
        self.to_queued()
        grant = self.started("inv_research01")
        self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": "inv_research01", "to_state": "outcome_unknown", "unknown_episode": 1,
                                       "unknown_cause": "contact_lost"})
        request = {"capability_id": grant["capability_id"], "invocation_id": "inv_research01", "unknown_episode": 1, "resolution": "confirmed_failed", "method": "job_handle_lookup",
                   "failure_class": "exit_nonzero", "evidence_ref": self.evidence(grant, ("exit_nonzero",), method="job_handle_lookup", exit=None)}
        writes, out = self.refused_at_every_write("reconcile", request)
        self.assertEqual((writes, out["status"]), (9, "recorded"))  # the artifact and its topic, the reconciliation, the invocation, its transition row, the hold, the lease, the topic, the audit event
        self.assertEqual(self.value("SELECT state FROM invocations"), "failed")


class LockWaitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.world = router_crash_child.World(Path(self.tmp.name))
        self.world.setUp()
        self.world.to_queued()
        self.grant = self.world.claim("inv_research01")

    def tearDown(self) -> None:
        self.world.router.close()
        self.world.db.close()
        self.tmp.cleanup()

    def waiting(self, operation: str, request: dict, *, cross: bool) -> dict:
        """`operation` on a second router while this test's connection holds the write lock; with `cross` the clock moves from E-1ns to E while the router waits for it."""
        clock = {"now": E_MINUS}
        issued = threading.Event()

        def act() -> dict:  # a connection is used on the thread that opened it
            store = api.open_store(self.world.directory / "store.sqlite3")
            store._conn.set_trace_callback(lambda sql: issued.set() if sql == "BEGIN IMMEDIATE" else None)
            router = service.Router(store, self.world.spool, clock=lambda: clock["now"])
            try:
                return getattr(router, operation)(request)
            finally:
                router.close()

        self.world.db.execute("BEGIN IMMEDIATE")
        try:
            with ThreadPoolExecutor(1) as pool:
                pending = pool.submit(act)
                if not issued.wait(10):
                    pending.result(timeout=0)  # an error before the lock is the failure to report
                    self.fail("the router never asked for the write lock")
                if cross:
                    clock["now"] = E
                self.world.db.execute("ROLLBACK")
                return pending.result(timeout=10)
        finally:
            if self.world.db.in_transaction:
                self.world.db.execute("ROLLBACK")

    def instants(self) -> set:
        """Every instant the cancellation wrote: the request and the end, the transition, the lease's release, the topic's update and the audit event."""
        w = self.world
        return {w.value("SELECT cancel_requested_at FROM invocations"), w.value("SELECT state_changed_at FROM invocations"), w.value("SELECT descendants_confirmed_at FROM invocations"),
                w.value("SELECT at FROM invocation_transitions WHERE to_state = 'cancelled'"), w.value("SELECT released_at FROM leases"),
                w.value("SELECT updated_at FROM queue_entries WHERE topic_id = ?", TOPIC), w.value("SELECT at FROM audit_events WHERE kind = 'cancel_requested'")}

    def cancel(self, *, cross: bool) -> None:
        out = self.waiting("request_cancel", {"invocation_id": "inv_research01", "requested_by": "operator", "reason": "stop"}, cross=cross)
        self.assertEqual((out["status"], out["state"]), ("cancelled", "cancelled"), out)

    def test_a_cancellation_is_dated_by_the_clock_read_after_the_lock_is_won(self) -> None:
        self.cancel(cross=True)
        self.assertEqual(self.instants(), {E})

    def test_control_the_same_cancellation_without_the_clock_moving_is_dated_before(self) -> None:
        self.cancel(cross=False)
        self.assertEqual(self.instants(), {E_MINUS})


if __name__ == "__main__":
    unittest.main()
