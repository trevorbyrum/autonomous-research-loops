"""The Router's wiring to its Scheduling collaborator (task 2q-b7, Astra's 2q-b3b rulings 3 and 4): what the replay cannot settle for the paths it leaves unresolved
(the supervisor scenarios that claim, fail and re-queue real work). Independent of the replay and of every other test of scheduling.

DelegateTest: each public route and each member the rest of the Router reads (`_lane_last` for the status read, `_admit_lane` and `_draw` for `claim`) is a one-line
delegate; a spy in the collaborator's place sees the call and its arguments, and its answer comes back unchanged.

TransactionTest: scheduling's five write routes run in the core's `_guarded`, as they did as a mixin. Refusal: the store refuses the n-th write of a route, for each n: the
route answers `request_invalid` ("the store refused the write") and every table, audit included, is as it was; with no refusal the same request is recorded. ClockTest: the
router's clock is read only while the write lock is held (the store's connection is inside BEGIN IMMEDIATE at every reading), so a route dates what it writes by the clock
read after the lock is won; the control reads the clock outside any route.

Oracles: expected values by hand; the store read back with raw SQL. Limits: the refusing store is a double that refuses by position, not by the DDL's own guards (those have
their own suites); the clock check shows when the clock is read, not the lock wait of a second connection (the lifecycle's wiring test shows that interleaving for `_guarded`
itself, which this slice does not touch).
"""
from __future__ import annotations

from gen2.router import service
from gen2.tests import test_router_scheduling as sched
from gen2.tests.router_fixtures import TOPIC, RouterTestCase
from gen2.tests.test_router_lifecycle_wiring import Refusing, Spy

DELEGATES = (  # name, arguments
    ("requeue", ({"r": 1},)), ("open_reservation", ({"r": 2},)), ("open_review", ({"r": 3},)), ("create_topic", ({"r": 4},)), ("raise_signal", ({"r": 5},)),
    ("_lane_last", ("topic", "research")), ("_admit_lane", ({"r": 6}, "topic", "research")), ("_draw", ({"r": 7}, "inv", "topic", "2026-09-27T10:00:00Z")),
)


class DelegateTest(RouterTestCase):
    def test_each_delegate_forwards_its_call_to_the_collaborator_and_returns_its_answer(self) -> None:
        for name, args in DELEGATES:
            with self.subTest(name=name):
                spy = self.router._scheduling = Spy()
                self.assertEqual(getattr(self.router, name)(*args), ("answered", name))
                self.assertEqual(spy.calls, [(name, args, {})])


class WriteRoutes(sched.PolicyCase):
    """A world with one failed lane, an approved contract and a topic, and a request for each write route that writes twice (its row, then the audit event)."""

    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.fail_work(self.started("inv_research01"))

    def requests(self) -> dict[str, dict]:
        return {"requeue": {"invocation_id": "inv_research01", "requested_by": "operator", "reason": "retry"},
                "open_reservation": {"reservation_id": "rsv_explore001", "topic_id": TOPIC, "purpose": "protected_exploration"},
                "open_review": {"episode_id": "rev_episode0001", "topic_id": TOPIC, "kind": "fixed_cadence"},
                "create_topic": {"topic_id": "fleet-a:t9", "priority": 3},
                "raise_signal": {"topic_id": TOPIC, "reason_code": "retraction", "signal_source": "operator", "cause_ref": "c1", "source_revision": 1,
                                 "observed_at": "2026-09-27T09:00:00Z"}}


class TransactionTest(WriteRoutes):
    def refused_at_every_write(self, route: str, request: dict) -> tuple[int, dict]:
        """The route with the store refusing its first write, then its second, and so on until a run is not refused: each refusal is `request_invalid` and leaves every table
        as it was. Returns how many writes the route made and the answer of the run that was allowed all of them."""
        before = self.state(exclude=())
        for position in range(50):
            router = service.Router(Refusing(self.store, position), self.spool, clock=self.clock, new_id=self.ids, fault=self.fault)
            try:
                out = getattr(router, route)(request)
            except Exception as exc:  # a write the store refused must come back as a refusal, not escape
                self.fail(f"{route}: write {position} refused: {type(exc).__name__} escaped the route: {exc}")
            if out["status"] != "refused":
                return position, out
            self.assertEqual(out["reason"], "request_invalid", out)
            self.assertTrue(out["detail"].startswith("the store refused the write"), out)
            self.assertEqual(self.state(exclude=()), before, f"{route}: write {position} refused")
        self.fail(f"{route}: every run was refused")

    def test_each_write_route_is_refused_whole_whichever_write_the_store_refuses(self) -> None:
        for route, request in self.requests().items():
            with self.subTest(route=route):
                writes, out = self.refused_at_every_write(route, request)
                self.assertEqual(writes, 2)  # its row and the audit event
                self.assertNotEqual(out["status"], "refused")  # allowed both, the route is recorded
                self.assertEqual(self.value("SELECT COUNT(*) FROM audit_events WHERE kind = ?", {"requeue": "requeued", "open_reservation": "reservation_opened", "open_review": "review_opened",
                                                                                                  "create_topic": "topic_created", "raise_signal": "signal_raised"}[route]), 1)


class ClockTest(WriteRoutes):
    def test_every_route_reads_the_clock_only_while_it_holds_the_write_lock(self) -> None:
        reads: list[bool] = []
        router = service.Router(self.store, self.spool, clock=lambda: (reads.append(self.db.in_transaction), self.clock())[1], new_id=self.ids, fault=self.fault)
        for route, request in self.requests().items():
            with self.subTest(route=route):
                reads.clear()
                out = getattr(router, route)(request)
                self.assertNotEqual(out["status"], "refused", out)
                self.assertEqual(reads, [True])  # one reading, inside BEGIN IMMEDIATE

    def test_control_a_reading_outside_a_route_sees_no_lock(self) -> None:
        reads: list[bool] = []
        router = service.Router(self.store, self.spool, clock=lambda: (reads.append(self.db.in_transaction), self.clock())[1], new_id=self.ids, fault=self.fault)
        router._now()
        self.assertEqual(reads, [False])
