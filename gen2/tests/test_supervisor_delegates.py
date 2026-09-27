"""A parent's capacity and its delegates (task 1c-repair; Astra 1c review A3;
INVARIANTS L-7, L-8).

Trace: L-8 (a delegate runs under its launching/running non-delegate
parent's lease and holds none of its own), L-7 (capacity is released only
after confirmed descendant handling); design review §6 (delegates run as
supervisor-owned jobs outside any harness's child lifetime).

A delegate runs in its own supervisor-owned session, so the parent's own
descendant check (its session) cannot see it. Each test starts a parent of
one of the four kinds that may have delegates and, under it, a delegate that
hangs with a descendant; the parent then ends — by completing, failing, being
cancelled, or after its supervisor died and restarted. Oracles: at every
router call that could release the parent's lease (its final commit, a
failed or cancelled transition, a terminal reconciliation), a watching
ControlBackend reads /proc for the delegate's execution group, and none of
it may be alive; the delegate's end, the lease and their order are read back
by raw SQL. Expected ends are written by hand.

A delegate stalled on a router incident (Astra 1c re-review A5-R): the
parent has ended, and one of the delegate's calls (its status read, or its
cancellation) cannot reach the router while the parent's can — a partial
outage — until the delegate's outage budget is spent. Then, from a
restarted supervisor that has not run recover(), the parent's advances make
none of the delegate's calls, the delegate's incident (its deadline
included) stays as raised and the store is unchanged; its deadline is still
observed locally. Oracles: the failing calls counted at the ControlBackend,
the journal's incident compared whole, the store read back whole. The
control: once the router is reachable, recover() and the parent's run end
the delegate and then the parent, as above.

The router-call chokepoint (task 1c-repair-3; Astra 1c re-review 2, L-6):
a parent stalled on its claim through an outage is claimed again by no
caller — its own advance, its delegate's advance needing its capability (the
recursive grant, Astra's reproduction), a caller holding another job and a
stale copy of its journal, for every control method, or recover() once no
recovery attempt is left — and the same holds for a delegate stalled under
an ended parent, with its parent ending it among the callers. Oracles: the
calls counted at the ControlBackend, the incident and budgets compared
whole, the store read back whole; a stale caller of the incident writer
renews nothing. The control: the router back, recover() starts the parent
and then its delegate. A parent that ended not_admitted is never claimed
again for its delegate (a later claim could admit work no job will run): the
delegate is not admitted either, and nothing is sent.

What this cannot show: a delegate that left its own session (jobs.py), or
delegates held by another supervisor (a delegate is always a job of its
parent's supervisor, WorkOrder).
"""
from __future__ import annotations

import os
import signal
import unittest

from gen2.core.control import ControlUnavailable
from gen2.core.instants import utc_instant_ns
from gen2.supervisor import jobs
from gen2.supervisor.supervisor import Held, Waiting
from gen2.tests import children
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import AFTER_DEADLINE, MAIN, PARENT, SupervisedTestCase, Unreachable, succeed

HANG_WITH_DESCENDANT = [{"op": "spawn_descendant", "marker": "descendant.pid"}, {"op": "hang"}]
GATED = [{"op": "wait_for", "name": "gate", "seconds": 60}]
RUN_S = 10.0  # a parent's end with its delegate takes well under a second; a mutant that never ends it costs this per test
METHODS = ("invocation_status", "claim", "record_transition", "request_cancel", "reconcile", "commit_outcome")  # every control call


class Watch(Unreachable):
    """Records, at each call that could release the parent's capacity, the
    live members of the delegate's execution group."""

    def __init__(self, router, delegate_identity) -> None:
        super().__init__(router)
        self.identity, self.seen = delegate_identity, []

    def __getattr__(self, name):
        call = super().__getattr__(name)

        def watched(request):
            releasing = name == "commit_outcome" or (name == "record_transition" and request.get("to_state") in ("failed", "cancelled")) \
                or (name == "reconcile" and request.get("resolution") in ("confirmed_failed", "terminated_group"))
            if releasing and request.get("invocation_id") == PARENT:
                self.seen.append((name, jobs.members(self.identity())))
            return call(request)
        return watched


class DelegateDown(Watch):
    """A partial outage: the delegate's `method` calls do not reach the
    router; every other call does. `failing` counts the ones that did not."""

    def __init__(self, router, delegate_identity, method: str) -> None:
        super().__init__(router, delegate_identity)
        self.method, self.failing = method, 0

    def __getattr__(self, name):
        call = super().__getattr__(name)

        def partial(request):
            if name == self.method and request.get("invocation_id") == MAIN:
                self.failing += 1
                raise ControlUnavailable(name)
            return call(request)
        return partial


class ParentEnds:
    KIND: str  # the parent's kind (never a delegate: no delegate chains, L-8)

    def start(self, parent_steps: list[dict]) -> None:
        self.assertEqual(self.supervisor.submit(self.order(self.KIND, parent_steps, inv=PARENT, deadline=rf.DEADLINE)), "running")
        self.assertEqual(self.supervisor.submit(self.order("delegate", HANG_WITH_DESCENDANT)), "running")
        self.wait_for_file("scratch/descendant.pid")
        self.assertGreaterEqual(len(jobs.members(self.job_file("identity.json"))), 3)  # its launcher, executor and descendant
        self.watching()

    def watching(self) -> None:
        self.watch = Watch(self.router, lambda: self.job_file("identity.json"))
        self.supervisor = self.make_supervisor(control=self.watch)

    def ended_after_its_delegate(self, parent_end: str, release: str) -> None:
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", PARENT), parent_end)
        self.assertTrue(self.watch.seen)
        self.assertEqual([(name, alive) for name, alive in self.watch.seen if alive], [])  # nothing of the delegate alive at any releasing call
        self.assertEqual(self.ended(MAIN), {"state": "cancelled", "failure_class": None, "evidence": True, "descendants_confirmed": True, "episodes": 0,
                                            "transitions": ["admitted", "launching", "running", "cancelled"], "receipts": 0, "lease_release": release,
                                            "open_holds": 0, "cleared_holds": 0, "reconciliations": [], "other_tables": []})
        self.assertEqual(self.value("SELECT cancel_requested_by FROM invocations WHERE invocation_id = ?", MAIN), "supervisor")
        self.assertEqual(self.evidence_record(MAIN)["termination"], {"reason": "cancellation"})
        self.assertEqual(jobs.members(self.job_file("identity.json")), [])
        delegate_end = self.value("SELECT at FROM invocation_transitions WHERE invocation_id = ? AND to_state = 'cancelled'", MAIN)
        released = self.value("SELECT released_at FROM leases WHERE lease_id = (SELECT lease_id FROM invocations WHERE invocation_id = ?)", PARENT)
        self.assertLess(utc_instant_ns(delegate_end), utc_instant_ns(released))  # the delegate's end was recorded first

    def test_a_parent_that_completes(self) -> None:
        self.start([*GATED, *succeed(PARENT)])
        self.gate(PARENT)
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "committed")
        self.ended_after_its_delegate("committed", "final_outcome")

    def test_a_parent_that_fails(self) -> None:
        self.start([*GATED, {"op": "exit", "code": 3}])
        self.gate(PARENT)
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "failed")
        self.ended_after_its_delegate("failed", "failed")

    def test_a_parent_that_is_cancelled(self) -> None:
        self.start([{"op": "hang"}])
        self.assertEqual(self.router.request_cancel({"invocation_id": PARENT, "requested_by": "operator", "reason": "stop"})["status"], "recorded")
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "cancelled")
        self.ended_after_its_delegate("cancelled", "cancelled")

    def test_a_parent_whose_supervisor_restarts(self) -> None:
        """The parent's end is collected, then its supervisor dies before
        sending it; the restarted supervisor (nothing in memory) ends the
        delegate before the parent's commit releases the lease."""
        self.start([*GATED, *succeed(PARENT)])
        self.gate(PARENT)
        self.wait_for_file("exit.json", PARENT)
        child = children.python(["-m", "gen2.tests.supervisor_child", str(self.root), PARENT, "collected", "2026-09-27T10:30:00Z"],
                                capture_output=True, text=True, timeout=120)
        self.child_runs.append(("collected", child.returncode, child.stdout, child.stderr))
        self.assertEqual(child.returncode, 137, f"the child did not die at collected: {child.stdout} {child.stderr}")
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "running")
        self.clock.set("2026-09-27T11:00:00Z")
        self.watching()
        self.assertEqual(self.supervisor.recover()[PARENT], "committed")
        self.ended_after_its_delegate("committed", "final_outcome")

    def test_a_parent_reconciled_after_its_launcher_vanished(self) -> None:
        """The parent's launcher dies; its group is terminated and the episode
        reconciled as a failure — a terminal reconciliation releases the
        lease, so the delegate is ended first."""
        self.start([{"op": "hang"}])
        os.kill(self.job_file("identity.json", PARENT)["pid"], signal.SIGKILL)
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "failed")
        self.assertEqual(self.watch.seen[-1][0], "reconcile")
        self.ended_after_its_delegate("failed", "failed")

    def test_a_parent_that_never_started(self) -> None:
        """A delegate admitted while its parent was launching; the parent's
        launcher then cannot start, and the parent fails within its spawn
        budget — after its delegate has ended."""
        self.watching()
        broken = self.make_supervisor(launcher=(str(self.root / "no-such-interpreter"),), control=self.watch)
        self.assertEqual(broken.submit(self.order(self.KIND, succeed(PARENT), inv=PARENT, deadline=rf.DEADLINE)), "launching")
        self.assertEqual(self.make_supervisor().submit(self.order("delegate", HANG_WITH_DESCENDANT)), "running")
        self.wait_for_file("scratch/descendant.pid")
        self.assertEqual([broken.advance(PARENT) for _ in range(2)], ["launching", "failed"])
        self.assertEqual(self.value("SELECT failure_class FROM invocations WHERE invocation_id = ?", PARENT), "spawn_failed")
        self.ended_after_its_delegate("failed", "failed")

    def test_the_parent_waits_while_its_delegate_cannot_be_ended(self) -> None:
        """Control: the delegate's cancellation cannot be recorded (the
        router refuses the delegate's cancelled transition); the parent then
        does not end and its lease stays held, whatever it asks. The refused
        end is sent within the delegate's refusal budget (3), then the
        delegate stalls with its incident (task 1c-repair-2); once the
        refusal lifts, recover() resumes it."""
        self.start([*GATED, *succeed(PARENT)])
        refuse = self.watch

        class RefusingDelegateEnd(Watch):
            def __getattr__(self, name):
                call = super().__getattr__(name)

                def maybe(request):
                    if name == "record_transition" and request.get("invocation_id") == MAIN and request.get("to_state") == "cancelled":
                        return {"status": "refused", "reason": "test_refuses", "detail": "held for the test"}
                    return call(request)
                return maybe
        self.watch = RefusingDelegateEnd(self.router, refuse.identity)
        self.supervisor = self.make_supervisor(control=self.watch)
        self.gate(PARENT)
        self.wait_for_file("exit.json", PARENT)  # the parent has ended (without this, a loaded host still shows it running)
        outcomes = [self.supervisor.advance(PARENT) for _ in range(5)]
        self.assertEqual(set(outcomes), {"delegates_pending"}, outcomes)
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", PARENT), "result_ready")
        self.assertEqual(self.rows("SELECT released_at FROM leases WHERE lease_id = (SELECT lease_id FROM invocations WHERE invocation_id = ?)", PARENT), [(None,)])
        self.assertEqual(self.watch.seen, [])  # no releasing call was made for the parent
        incident = self.journal()["incident"]
        self.assertEqual((incident["kind"], incident["write"], incident["last_refusal"]["reason"], incident["final"]),
                         ("lifecycle_write_refused", "end", "test_refuses", False))
        self.watching()  # the refusal lifts: recovery resumes the delegate, and the same parent ends after it
        self.assertEqual(self.supervisor.recover(), {PARENT: "delegates_pending", MAIN: "cancelled"})
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "committed")
        self.ended_after_its_delegate("committed", "final_outcome")


    # -- a delegate stalled on an incident (Astra 1c re-review A5-R) -----------------------------------
    def stalled_delegate(self, method: str) -> dict:
        """The parent has ended; its delegate's `method` calls cannot reach the
        router. The parent's advances spend the delegate's outage budget, then
        the delegate stalls with an incident; its parent waits."""
        self.start([*GATED, *succeed(PARENT)])
        self.gate(PARENT)
        self.wait_for_file("exit.json", PARENT)
        self.down = DelegateDown(self.router, self.watch.identity, method)
        supervisor = self.make_supervisor(control=self.down)
        self.assertEqual({supervisor.advance(PARENT) for _ in range(6)}, {"delegates_pending"})
        self.assertEqual(self.down.failing, 6)  # the budget (5), then the call that stalled the delegate; none after
        incident = self.journal()["incident"]
        self.assertEqual((incident["kind"], incident["method"], incident["owner"]), ("router_unreachable", method, "supervisor:station-1"))
        return incident

    def parent_waits(self, supervisor, advances: int, incident: dict) -> None:
        """The parent's advances make none of the stalled delegate's calls:
        its incident stays as raised, deadline included; nothing changes."""
        before = self.state(exclude=())
        self.assertEqual({supervisor.advance(PARENT) for _ in range(advances)}, {"delegates_pending"})
        self.assertEqual(self.down.failing, 6)
        self.assertEqual(self.journal()["incident"], incident)
        self.assertEqual(self.journal()["budgets"].get("recovery"), None)
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", PARENT), "result_ready")
        self.assertEqual(self.rows("SELECT released_at FROM leases WHERE lease_id = (SELECT lease_id FROM invocations WHERE invocation_id = ?)", PARENT), [(None,)])

    def restarted_without_recovery(self, incident: dict) -> None:
        """A restarted supervisor, recover() not run, half an hour later."""
        self.clock.set("2026-09-27T10:30:00Z")
        self.parent_waits(self.make_supervisor(control=self.down), 12, incident)
        self.assertNotEqual(jobs.members(self.job_file("identity.json")), [])  # the delegate runs on: its deadline has not come

    def recovered(self) -> None:
        """Control: the router reachable again, recover() resumes the delegate
        (one recovery attempt); the parent then ends it, and ends."""
        self.watching()
        self.assertEqual(self.supervisor.recover(), {PARENT: "delegates_pending", MAIN: "running"})
        self.assertEqual(self.journal()["budgets"]["recovery"], 1)
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "committed")

    def test_a_delegate_stalled_on_its_status_read_holds_its_parent_without_calls(self) -> None:
        self.restarted_without_recovery(self.stalled_delegate("invocation_status"))
        self.recovered()
        self.ended_after_its_delegate("committed", "final_outcome")

    def test_a_delegate_stalled_on_its_cancellation_holds_its_parent_without_calls(self) -> None:
        self.restarted_without_recovery(self.stalled_delegate("request_cancel"))
        self.recovered()
        self.ended_after_its_delegate("committed", "final_outcome")

    def test_a_refused_delegate_cancellation_is_budgeted(self) -> None:
        """The router refuses the cancellation the parent asks for its
        delegate (task 1c-repair-2): it is asked again within the delegate's
        refusal budget (3), then the delegate stalls with its incident and the
        parent's advances ask nothing more, a restart included; once the
        refusal lifts, recover() resumes the delegate and the parent ends it."""
        self.start([*GATED, *succeed(PARENT)])
        self.gate(PARENT)
        self.wait_for_file("exit.json", PARENT)
        refused = []

        class RefusingCancel(Watch):
            def __getattr__(self, name):
                call = super().__getattr__(name)

                def maybe(request):
                    if name == "request_cancel" and request.get("invocation_id") == MAIN:
                        refused.append(request)
                        return {"status": "refused", "reason": "transition_not_allowed", "detail": "refused by the test"}
                    return call(request)
                return maybe
        refusing = RefusingCancel(self.router, self.watch.identity)
        self.assertEqual({self.make_supervisor(control=refusing).advance(PARENT) for _ in range(6)}, {"delegates_pending"})
        self.assertEqual(len(refused), 4)  # the budget (3), then the one that stalled the delegate; none after
        incident = self.journal()["incident"]
        self.assertEqual((incident["kind"], incident["write"], incident["last_refusal"]["reason"]), ("lifecycle_write_refused", "cancel", "transition_not_allowed"))
        self.clock.set("2026-09-27T10:30:00Z")
        before = self.state(exclude=())
        self.assertEqual({self.make_supervisor(control=refusing).advance(PARENT) for _ in range(6)}, {"delegates_pending"})
        self.assertEqual((len(refused), self.journal()["incident"], self.state(exclude=())), (4, incident, before))
        self.watching()
        self.assertEqual(self.supervisor.recover(), {PARENT: "delegates_pending", MAIN: "running"})
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "committed")
        self.ended_after_its_delegate("committed", "final_outcome")

    def test_a_stalled_delegate_is_still_ended_at_its_deadline(self) -> None:
        """Local deadline observation goes on while the delegate is stalled
        (C-10): its group is ended with no router call, and the termination is
        delivered once it is recovered."""
        incident = self.stalled_delegate("invocation_status")
        identity = self.job_file("identity.json")
        self.clock.set(AFTER_DEADLINE)  # the delegate's deadline; the parent's is later
        self.parent_waits(self.make_supervisor(control=self.down), 1, incident)
        self.assertEqual(jobs.members(identity), [])
        self.assertEqual(self.journal()["collected"]["terminated"], "timeout")
        self.recovered_after_timeout()

    def recovered_after_timeout(self) -> None:
        self.watching()
        self.assertEqual(self.supervisor.recover(), {PARENT: "delegates_pending", MAIN: "failed"})
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "committed")
        self.assertEqual([(name, alive) for name, alive in self.watch.seen if alive], [])
        self.assertEqual(self.ended(MAIN), {"state": "failed", "failure_class": "timeout", "evidence": True, "descendants_confirmed": False, "episodes": 0,
                                            "transitions": ["admitted", "launching", "running", "failed"], "receipts": 0, "lease_release": "final_outcome",
                                            "open_holds": 0, "cleared_holds": 0, "reconciliations": [], "other_tables": []})
        record = self.evidence_record(MAIN)
        self.assertEqual((record["termination"], record["descendants"]["handling"]), ({"reason": "timeout"}, "terminated"))


    # -- the router-call chokepoint (task 1c-repair-3; Astra 1c re-review 2, L-6) ------------------------
    def stalled_parent(self) -> dict:
        """The parent's claim cannot reach the router: its advances spend its
        outage budget (5), then it stalls on an incident; its delegate's order
        is prepared, needing the parent's capability to be claimed."""
        self.control.down = True
        self.supervisor.prepare(self.order(self.KIND, [{"op": "hang"}], inv=PARENT, deadline=rf.DEADLINE))
        self.assertEqual([self.supervisor.advance(PARENT) for _ in range(6)], ["router_unavailable"] * 5 + ["stalled"])
        incident = self.journal(PARENT)["incident"]
        self.assertEqual((incident["kind"], incident["method"], self.control.refused), ("router_unreachable", "claim", 6))
        self.supervisor.prepare(self.order("delegate", HANG_WITH_DESCENDANT))
        return incident

    def nothing_sent(self, inv: str, calls: int, incident: dict, budgets: dict, before: dict) -> None:
        """No control call made, the stalled job's incident (its since and
        deadline included) and budgets as they were, the store unchanged."""
        self.assertEqual(self.control.calls, calls)
        self.assertEqual((self.journal(inv)["incident"], self.journal(inv)["budgets"]), (incident, budgets))
        self.assertEqual(self.state(exclude=()), before)

    def refused_at_the_chokepoint(self, supervisor, caller: str, inv: str) -> None:
        """Every control method for `inv`, called as another job holding a
        stale copy of the journal: refused (Held), whatever the caller holds."""
        for method in METHODS:
            with self.assertRaises(Waiting) as raised:
                supervisor._call(supervisor.job(caller), {"budgets": {}}, method, {"invocation_id": inv})
            self.assertIsInstance(raised.exception, Held, method)
        supervisor._incident(supervisor.job(inv), {"budgets": {}}, "router_unreachable")  # nor is it renewed by a stale caller of the writer

    def test_a_delegate_does_not_retry_its_stalled_parents_claim(self) -> None:
        """Astra's reproduction (1c re-review 2, BLOCK 1): a restarted
        supervisor, recover() not run, half an hour later. Each of the
        delegate's advances needs its parent's capability, and the parent's
        claim is refused at the chokepoint: no call, the parent's incident
        (deadline included) and budgets as they were, the delegate spending
        nothing, the store unchanged. Control: the router back, recover()
        starts the parent, then the delegate."""
        incident = self.stalled_parent()
        calls, budgets, before = self.control.calls, self.journal(PARENT)["budgets"], self.state(exclude=())
        self.clock.set("2026-09-27T10:30:00Z")
        supervisor = self.make_supervisor()
        self.assertEqual({supervisor.advance(MAIN) for _ in range(12)}, {"parent_stalled"})
        self.nothing_sent(PARENT, calls, incident, budgets, before)
        self.assertIsNone(self.job_file("journal.json"))  # the delegate kept nothing: it spent no budget, it holds no incident
        self.control.down = False
        self.assertEqual(self.make_supervisor().recover(), {PARENT: "running", MAIN: "running"})
        self.assertEqual(self.journal(PARENT)["budgets"]["recovery"], 1)
        self.wait_for_file("scratch/descendant.pid")

    def test_no_caller_makes_a_stalled_parents_control_call(self) -> None:
        """Whoever calls for the parent stalled on its claim — its own advance,
        its delegate's advance (the recursive grant), another job holding a
        stale copy of its journal, recover() with no recovery attempt left —
        nothing is sent and its incident stays as raised."""
        incident = self.stalled_parent()
        calls, budgets, before = self.control.calls, self.journal(PARENT)["budgets"], self.state(exclude=())
        self.clock.set("2026-09-27T10:30:00Z")
        supervisor = self.make_supervisor()
        with self.subTest(caller="its own advance"):
            self.assertEqual({supervisor.advance(PARENT) for _ in range(3)}, {"stalled"})
            self.nothing_sent(PARENT, calls, incident, budgets, before)
        with self.subTest(caller="its delegate's advance: the recursive grant"):
            self.assertEqual({supervisor.advance(MAIN) for _ in range(3)}, {"parent_stalled"})
            self.nothing_sent(PARENT, calls, incident, budgets, before)
        with self.subTest(caller="another job, holding a stale copy of its journal"):
            self.refused_at_the_chokepoint(supervisor, MAIN, PARENT)
            self.nothing_sent(PARENT, calls, incident, budgets, before)
        with self.subTest(caller="recover(), with no recovery attempt left"):
            for attempt in (1, 2, 3):  # still down: each resumption makes its claim once and stalls again at once
                self.assertEqual(supervisor.recover(), {PARENT: "stalled", MAIN: "parent_stalled"})
                self.assertEqual((self.control.calls, self.journal(PARENT)["budgets"]["recovery"]), (calls + attempt, attempt))
            incident, budgets, before = self.journal(PARENT)["incident"], self.journal(PARENT)["budgets"], self.state(exclude=())
            self.assertEqual(supervisor.recover(), {PARENT: "stalled", MAIN: "parent_stalled"})
            self.nothing_sent(PARENT, calls + 3, incident, budgets, before)

    def test_no_caller_makes_a_stalled_delegates_control_call(self) -> None:
        """The same for a delegate stalled on its status read under an ended
        parent: its parent ending it (A5-R), its own advance, another job
        holding a stale copy of its journal, recover() with no recovery
        attempt left."""
        incident = self.stalled_delegate("invocation_status")
        self.clock.set("2026-09-27T10:30:00Z")
        supervisor = self.make_supervisor(control=self.down)
        budgets, before = self.journal()["budgets"], self.state(exclude=())

        def nothing_sent(failing: int) -> None:
            self.assertEqual((self.down.failing, self.journal()["incident"], self.journal()["budgets"]), (failing, incident, budgets))
            self.assertEqual(self.state(exclude=()), before)
        with self.subTest(caller="its parent ending it"):
            self.assertEqual({supervisor.advance(PARENT) for _ in range(3)}, {"delegates_pending"})
            nothing_sent(6)
        with self.subTest(caller="its own advance"):
            self.assertEqual({supervisor.advance(MAIN) for _ in range(3)}, {"stalled"})
            nothing_sent(6)
        with self.subTest(caller="another job, holding a stale copy of its journal"):
            self.refused_at_the_chokepoint(supervisor, PARENT, MAIN)
            nothing_sent(6)
        with self.subTest(caller="recover(), with no recovery attempt left"):
            for attempt in (1, 2, 3):  # its status read still fails: each resumption makes it once and stalls again at once
                self.assertEqual(supervisor.recover(), {PARENT: "delegates_pending", MAIN: "stalled"})
                self.assertEqual((self.down.failing, self.journal()["budgets"]["recovery"]), (6 + attempt, attempt))
            incident, budgets, before = self.journal()["incident"], self.journal()["budgets"], self.state(exclude=())
            self.assertEqual(supervisor.recover(), {PARENT: "delegates_pending", MAIN: "stalled"})
            nothing_sent(9)

    def test_a_parent_not_admitted_is_never_claimed_again_for_its_delegate(self) -> None:
        """The parent's claim is refused (its topic paused) and it ends
        not_admitted. The pause lifts; its delegate needs its capability, and
        the chokepoint sends nothing for a settled job: a second claim would
        admit work that no job will ever run, holding a lease. The delegate is
        not admitted either, with the reason, and nothing is sent for it."""
        self.x("UPDATE queue_entries SET paused_at = ? WHERE topic_id = ?", "2026-09-27T10:00:00Z", rf.TOPIC)
        self.assertEqual(self.supervisor.submit(self.order(self.KIND, [{"op": "hang"}], inv=PARENT, deadline=rf.DEADLINE)), "not_admitted")
        self.x("UPDATE queue_entries SET paused_at = NULL WHERE topic_id = ?", rf.TOPIC)
        calls, before = self.control.calls, self.state(exclude=())
        self.assertEqual([self.make_supervisor().submit(self.order("delegate", HANG_WITH_DESCENDANT)), self.supervisor.advance(MAIN)], ["not_admitted"] * 2)
        self.assertEqual((self.control.calls, self.state(exclude=())), (calls, before))
        self.assertEqual(self.rows("SELECT invocation_id FROM invocations"), [])
        self.assertEqual((self.journal()["settled"], self.journal()["refused"]["reason"]), ("not_admitted", "parent_not_admitted"))
        self.assertIsNone(self.journal().get("grant"))


class ResearchPassParentTest(ParentEnds, SupervisedTestCase):
    KIND = "research_pass"


class DiscoveryParentTest(ParentEnds, SupervisedTestCase):
    KIND = "discovery"


class VerificationParentTest(ParentEnds, SupervisedTestCase):
    KIND = "verification"


class CheckpointParentTest(ParentEnds, SupervisedTestCase):
    KIND = "checkpoint"


if __name__ == "__main__":
    unittest.main()
