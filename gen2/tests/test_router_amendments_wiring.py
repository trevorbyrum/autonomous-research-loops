"""The Router's wiring to its Amendments collaborator (task 2q-b8, Astra's 2q-b3b rulings 3 and 4): what the replay cannot settle for the paths it leaves unresolved
(the supervisor scenarios that claim, commit and stage real work under pins). Independent of the replay and of every other test of amendments.

DelegateTest: each public route and each member the rest of the Router reads (`_open_topic` for scheduling, `_pin_status` for the status read and the evidence write,
`_brief_standing`, `_record_impact` and `_record_replacements` for the decisions, `_recorded_references` for the approval, `_require_current_pins` for the commit) is a
one-line delegate; a spy in the collaborator's place sees the call and its arguments, and its answer comes back unchanged.

TransactionTest: amendments' six write routes run in the core's `_guarded`, as they did as a mixin. Refusal: the store refuses the n-th write of a route, for each n: the
route answers `request_invalid` ("the store refused the write") and every table, audit included, is as it was; with no refusal the same request is recorded, with the
number of writes the request's own lists give. ClockTest: the router's clock is read once, while the write lock is held. ApprovalTest: the impact, the fence and the
cancellations they request (members the Router reaches through its delegates) are written in the approval's one transaction: a protocol-changing approval that fences
running and admitted work is refused whole whichever of its writes the store refuses, and run unrefused it fences both.

Oracles: expected values by hand; the store read back with raw SQL. Limits: the refusing store is a double that refuses by position, not by the DDL's own guards (those
have their own suites); the clock check shows when the clock is read, not the lock wait of a second connection (the lifecycle's wiring test shows that interleaving for
`_guarded` itself, which this slice does not touch).
"""
from __future__ import annotations

from gen2.router import service
from gen2.tests import test_router_amendments as amend
from gen2.tests.router_fixtures import OTHER, TOPIC
from gen2.tests.test_router_lifecycle_wiring import Refusing, Spy

DELEGATES = (  # name, arguments
    ("version_brief", ({"r": 1},)), ("open_brief", ({"r": 2},)), ("mark_brief_overdue", ({"r": 3},)), ("propose_amendment", ({"r": 4},)), ("draft_contract", ({"r": 5},)),
    ("close_brief", ({"r": 6},)), ("_open_topic", ("topic",)), ("_pin_status", ({"r": 7},)), ("_brief_standing", ("topic", "brief-1", 2)),
    ("_record_impact", ({"r": 8}, "contract", {"r": 9}, {"r": 10}, "2026-09-27T10:00:00Z")), ("_record_replacements", ({"r": 11}, {"r": 12}, "2026-09-27T10:00:00Z")),
    ("_recorded_references", ({"r": 13},)), ("_require_current_pins", ({"r": 14},)),
)
AUDIT = {"open_brief": "brief_versioned", "version_brief": "brief_versioned", "mark_brief_overdue": "brief_overdue", "close_brief": "brief_closed",
         "draft_contract": "contract_drafted", "propose_amendment": "amendment_proposed"}
DEADLINE = "2026-10-05T00:00:00Z"


class DelegateTest(amend.RouterTestCase):
    def test_each_delegate_forwards_its_call_to_the_collaborator_and_returns_its_answer(self) -> None:
        for name, args in DELEGATES:
            with self.subTest(name=name):
                spy = self.router._amendments = Spy()
                self.assertEqual(getattr(self.router, name)(*args), ("answered", name))
                self.assertEqual(spy.calls, [(name, args, {})])


class WriteRoutes(amend.ContractWorld):
    """The contract world (revision 2 approved on TOPIC), and each of the six write routes in the order the world allows: on OTHER a brief is opened (its row, then the
    audit event), versioned (its row, the superseded version's update, the audit event), marked overdue once the clock passes the deadline (an update, the audit event),
    confirmed through the router (by decision), its first contract drafted (the revision, each facet, each obligation, the audit event) and closed (an update, the audit
    event); on TOPIC an amendment is proposed. `step(route, request, writes)` is called for each, with the writes the request's own lists give."""

    def sequence(self, step) -> None:
        brief = lambda v: {"document": self.brief_document(OTHER, v), "owner_operator_id": "user", "review_deadline": DEADLINE}  # noqa: E731
        key = {"topic_id": OTHER, "brief_id": "brief-1"}
        step("open_brief", brief(1), 2)
        step("version_brief", brief(2), 3)
        self.clock.set("2026-10-06T00:00:00Z")
        step("mark_brief_overdue", {**key, "version": 2}, 2)
        self.assertEqual(self.decide("opd_brieft202", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 2, "hash": brief(2)["document"]["content_hash"]},
                                     OTHER)["status"], "applied")
        draft = amend.contract_doc(1, None, rated=False, edit=lambda d: (d.update(topic_id=OTHER), d["decision_record"]["objective"].update(
            confirmed_brief={"brief_id": "brief-1", "version": 2, "confirmed_by": "opd_brieft202"})))
        step("draft_contract", {"document": draft}, 2 + len(draft["facet_map"]["facets"]) + len(draft["obligations"]))
        step("close_brief", {**key, "version": 2, "closure": "archived", "closed_by": "user", "reason": "intake done"}, 2)
        r3 = amend.contract_doc(3, 2, edit=amend.compatible)
        step("propose_amendment", {"document": r3}, 2 + len(r3["facet_map"]["facets"]) + len(r3["obligations"]))


class TransactionTest(WriteRoutes):
    def refused_at_every_write(self, route: str, request: dict) -> tuple[int, dict]:
        """The route with the store refusing its first write, then its second, and so on until a run is not refused: each refusal is `request_invalid` and leaves every table
        as it was. Returns how many writes the route made and the answer of the run that was allowed all of them."""
        before = self.state(exclude=())
        for position in range(60):
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
        def step(route: str, request: dict, expected: int) -> None:
            with self.subTest(route=route):
                writes, out = self.refused_at_every_write(route, request)
                self.assertEqual(writes, expected)
                self.assertIn(out["status"], ("recorded", "marked", "closed"), out)  # allowed every write, the route is recorded
                self.assertEqual(self.value("SELECT COUNT(*) FROM audit_events WHERE kind = ?", AUDIT[route]), 1 if route != "version_brief" else 2)  # open_brief's is the first
        self.sequence(step)


class ClockTest(WriteRoutes):
    def test_every_route_reads_the_clock_only_while_it_holds_the_write_lock(self) -> None:
        reads: list[bool] = []
        self.router = service.Router(self.store, self.spool, clock=lambda: (reads.append(self.db.in_transaction), self.clock())[1], new_id=self.ids, fault=self.fault)

        def step(route: str, request: dict, expected: int) -> None:
            with self.subTest(route=route):
                reads.clear()
                out = getattr(self.router, route)(request)
                self.assertNotEqual(out["status"], "refused", out)
                self.assertEqual(reads, [True])  # one reading, inside BEGIN IMMEDIATE
        self.sequence(step)

    def test_control_a_reading_outside_a_route_sees_no_lock(self) -> None:
        reads: list[bool] = []
        router = service.Router(self.store, self.spool, clock=lambda: (reads.append(self.db.in_transaction), self.clock())[1], new_id=self.ids, fault=self.fault)
        router._now()
        self.assertEqual(reads, [False])


class ApprovalTest(amend.ContractWorld):
    def test_an_approval_that_fences_work_is_refused_whole_whichever_write_the_store_refuses(self) -> None:
        self.research()  # running under revision 2
        self.claim("inv_checkpt01", "checkpoint")  # admitted, never launched
        r3 = self.propose(3, amend.protocol_changed)
        before = self.state(exclude=())
        for position in range(200):
            self.router = service.Router(Refusing(self.store, position), self.spool, clock=self.clock, new_id=self.ids, fault=self.fault)
            try:
                out = self.approve(r3)
            except Exception as exc:  # a write the store refused must come back as a refusal, not escape
                self.fail(f"write {position} refused: {type(exc).__name__} escaped the approval: {exc}")
            if out["status"] == "applied":
                break
            self.assertTrue(out["detail"].startswith("the store refused the write"), out)
            self.assertEqual(self.state(exclude=()), before, f"write {position} refused")
        else:
            self.fail("every run was refused")
        self.assertGreater(position, 10)  # the decision, the approval, the impact, the cancellations: many writes, each one refused in turn
        self.assertEqual({w["invocation_id"]: (w["disposition"], w["cancel_requested"]) for w in self.impact("opd_amend0003")["work"]},
                         {"inv_research01": ("fenced", True), "inv_checkpt01": ("fenced", True)})
        self.assertEqual(self.rows("SELECT invocation_id, state, cancel_requested_by FROM invocations ORDER BY invocation_id"),
                         [("inv_checkpt01", "cancelled", "router"), ("inv_research01", "running", "router")])
