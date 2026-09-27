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

What this cannot show: a delegate that left its own session (jobs.py), or
delegates held by another supervisor (a delegate is always a job of its
parent's supervisor, WorkOrder).
"""
from __future__ import annotations

import os
import signal
import unittest

from gen2.core.instants import utc_instant_ns
from gen2.supervisor import jobs
from gen2.tests import children
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import MAIN, PARENT, SupervisedTestCase, Unreachable, succeed

HANG_WITH_DESCENDANT = [{"op": "spawn_descendant", "marker": "descendant.pid"}, {"op": "hang"}]
GATED = [{"op": "wait_for", "name": "gate", "seconds": 60}]
RUN_S = 10.0  # a parent's end with its delegate takes well under a second; a mutant that never ends it costs this per test


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
        does not end and its lease stays held, whatever it asks."""
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
        self.watching()  # the refusal lifts: the same parent ends, after its delegate
        self.assertEqual(self.supervisor.run(PARENT, timeout_s=RUN_S), "committed")
        self.ended_after_its_delegate("committed", "final_outcome")


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
