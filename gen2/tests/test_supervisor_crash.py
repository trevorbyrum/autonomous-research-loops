"""The supervisor killed at each lifecycle boundary, then restarted, for every
invocation kind (task 1c; release gate RG-2; INVARIANTS L-2, L-3, L-4, L-8,
C-10; design review §5 "Crash fencing").

Trace: RG-2's fault set names "spawn/receipt uncertainty (crash between spawn
and identity record)"; the task brief adds "supervisor crash at each
lifecycle boundary, then restart". Design review §5: "A crash between spawn
and PID recording cannot be made atomic with SQLite. Resolve it through
idempotent supervisor job lookup or terminate/reconcile the owned execution
group before replacement."

How: the test prepares the world and stores the order; a child process
(supervisor_child.py) opens the same store, spool and jobs directory
through the composition root and runs the job with a fault hook that ends
it with os._exit(137) at the boundary — no exception, no cleanup. Then a new
supervisor in this process, holding nothing in memory, runs recover() and
drives the job to its end. The job's launcher is in its own session, so it
survives the supervisor's death as a real job would.

Oracles: the expected end is written by hand per boundary (`ended()` reads
the invocation, its transitions, receipts, lease, episode holds and
reconciliations back by raw SQL); how many times the job was started is
read from its job directory; that no process outlives the test is checked
by tearDown.

Boundaries, in lifecycle order: claimed (claim answered, grant not yet
kept), launch_recorded (launch intent recorded, nothing started), spawning
(a start recorded in the job directory, the launcher not yet started),
spawned (the launcher started, its identity not yet recorded with the
router: the spawn/receipt uncertainty), running_recorded, collected (the
end observed and retained, not yet sent), result_ready_recorded,
commit_replied (committed, the supervisor's journal not yet told),
terminated (the group ended at its deadline, the failure not yet recorded)
and unknown_recorded (outcome_unknown entered by a restarted supervisor,
not yet reconciled: a second crash).

What this cannot show: power loss or a torn write (a killed process leaves
the page cache and every completed write), or a crash inside a router
transaction (test_router_crash.py).
"""
from __future__ import annotations

import unittest

from gen2.tests import children
from gen2.tests.supervisor_fixtures import MAIN, SupervisedTestCase, released, succeed

GATED = [{"op": "wait_for", "name": "gate", "seconds": 60}, *succeed()]
HANG = [{"op": "hang"}]
CLEAN = ["admitted", "launching", "running", "result_ready", "committed"]
CHILD_CLOCK = "2026-09-27T10:30:00Z"
SHORT_DEADLINE = "2026-09-27T10:30:00.300Z"  # passes while the child polls its running job (its clock reads a millisecond at a time)


class CrashFaults:
    KIND: str

    def crash(self, point: str, steps: list[dict], *, deadline: str | None = None, clock: str = CHILD_CLOCK, prepare: bool = True) -> None:
        if prepare:
            self.prepare(self.KIND)
            self.supervisor.prepare(self.order(self.KIND, steps, **({"deadline": deadline} if deadline else {})))
        child = children.python(["-m", "gen2.tests.supervisor_child", str(self.root), MAIN, point, clock], capture_output=True, text=True, timeout=120)
        self.assertEqual(child.returncode, 137, f"the child did not die at {point}: {child.stdout} {child.stderr}")

    def restart(self) -> dict:
        """A new supervisor in this process, holding nothing in memory."""
        self.clock.set("2026-09-27T11:00:00Z")
        self.supervisor = self.make_supervisor()
        return self.supervisor.recover()

    def committed(self, transitions=tuple(CLEAN), **extra) -> dict:
        base = {"state": "committed", "failure_class": None, "evidence": False, "descendants_confirmed": False, "episodes": 0, "transitions": list(transitions),
                "receipts": 1, "lease_release": released(self.KIND, "final_outcome"), "open_holds": 0, "cleared_holds": 0, "reconciliations": []}
        return {**base, **extra}

    def test_crash_before_the_grant_is_kept(self) -> None:
        self.crash("claimed", succeed())
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed())
        self.assertEqual(self.spawns(), 1)

    def test_crash_after_launch_intent_before_any_start(self) -> None:
        self.crash("launch_recorded", succeed())
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed())
        self.assertEqual(self.spawns(), 1)

    def test_crash_after_recording_a_start_that_never_happened(self) -> None:
        """The start is recorded, the launcher never ran: the lookup finds no
        identity and a free lock, marks the job abandoned (so a late launcher
        would not start it), and reconciles it as never started."""
        self.crash("spawning", succeed())
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "failed")
        self.assertEqual(self.ended(), {**self.committed(["admitted", "launching", "outcome_unknown", "failed"]), "state": "failed", "receipts": 0,
                                        "failure_class": "never_started", "evidence": True, "episodes": 1, "cleared_holds": 1,
                                        "lease_release": released(self.KIND, "failed"), "reconciliations": ["confirmed_failed"]})
        self.assertIsNone(self.job_file("identity.json"))
        self.assertTrue((self.root / "jobs" / f"job-{MAIN}" / "abandoned").exists())

    def test_crash_between_spawn_and_identity_record_finds_the_job_running(self) -> None:
        """RG-2's spawn/receipt uncertainty: the launcher is running, its
        identity unknown to the router. The restarted supervisor enters
        outcome_unknown, finds the job by its handle, verifies its identity
        and reconciles it as running — it never starts a second copy."""
        self.crash("spawned", GATED)
        self.wait_for_file("identity.json")  # the orphaned launcher runs on; this makes the lookup's finding deterministic
        self.assertEqual(self.restart()[MAIN], "running")
        self.gate()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed(["admitted", "launching", "outcome_unknown", "running", "result_ready", "committed"],
                                                      episodes=1, cleared_holds=1, reconciliations=["found_running"]))
        self.assertEqual(self.spawns(), 1)

    def test_crash_between_spawn_and_identity_record_finds_the_result(self) -> None:
        self.crash("spawned", succeed())
        self.wait_for_file("exit.json")
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed(["admitted", "launching", "outcome_unknown", "result_ready", "committed"],
                                                      episodes=1, cleared_holds=1, reconciliations=["found_result"]))
        self.assertEqual(self.spawns(), 1)

    def test_crash_after_the_identity_is_recorded(self) -> None:
        self.crash("running_recorded", succeed())
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed())
        self.assertEqual(self.spawns(), 1)

    def test_crash_after_the_end_is_retained_before_it_is_sent(self) -> None:
        self.crash("collected", succeed())
        collected = self.journal()["collected"]
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed())
        self.assertEqual(self.journal()["collected"], collected)  # observed once; the retained end is what is sent

    def test_crash_after_result_ready_before_the_commit(self) -> None:
        self.crash("result_ready_recorded", succeed())
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed())

    def test_crash_after_the_commit_before_the_journal_knows(self) -> None:
        self.crash("commit_replied", succeed())
        before = self.state(exclude=())
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed())
        self.assertEqual(self.state(exclude=()), before)  # the commit is found, not repeated: every table as the crash left it

    def test_crash_after_the_deadline_terminated_the_group(self) -> None:
        self.crash("terminated", HANG, deadline=SHORT_DEADLINE)
        self.restart()
        self.assertEqual(self.supervisor.run(MAIN), "failed")
        self.assertEqual(self.ended(), {**self.committed(["admitted", "launching", "running", "failed"]), "state": "failed", "receipts": 0,
                                        "failure_class": "timeout", "evidence": True, "lease_release": released(self.KIND, "failed")})

    def test_a_second_crash_after_entering_outcome_unknown(self) -> None:
        self.crash("spawned", GATED)
        self.wait_for_file("identity.json")
        self.crash("unknown_recorded", GATED, clock="2026-09-27T10:40:00Z", prepare=False)
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "outcome_unknown")
        self.assertEqual(self.restart()[MAIN], "running")
        self.gate()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed(["admitted", "launching", "outcome_unknown", "running", "result_ready", "committed"],
                                                      episodes=1, cleared_holds=1, reconciliations=["found_running"]))
        self.assertEqual(self.spawns(), 1)


class ResearchPassCrashTest(CrashFaults, SupervisedTestCase):
    KIND = "research_pass"


class DiscoveryCrashTest(CrashFaults, SupervisedTestCase):
    KIND = "discovery"


class DelegateCrashTest(CrashFaults, SupervisedTestCase):
    KIND = "delegate"


class VerificationCrashTest(CrashFaults, SupervisedTestCase):
    KIND = "verification"


class CheckpointCrashTest(CrashFaults, SupervisedTestCase):
    KIND = "checkpoint"


if __name__ == "__main__":
    unittest.main()
