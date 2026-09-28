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

Beside the start that never happened (the job marked abandoned before it is
reconciled as never started), the accepted alternative its guard admits
(Astra 1c re-review 3, BLOCK 2): starts the OS refused leave no start, so
nothing to abandon; an outcome_unknown episode over them, recorded through
the router's own operation, is reconciled as never started with no
abandoned mark.

A delegate's replaced lease (Astra 1c re-review C5): a delegate runs under
its parent's lease, and a research pass's lease is not replaced while its
topic is active, so the per-kind fixture above (a delegate under a research
pass) cannot reach that case. DelegateReplacementFaults runs it under each
parent kind whose scope can be claimed again — discovery, verification,
checkpoint: the supervisor dies once the delegate's launch intent is
recorded, the parent's lease lapses and a new generation of its scope is
granted; the restarted supervisor starts no executor and the delegate ends
cancelled. Beside it, the unchanged-authority control: the same crash under
the same parent kind, its lease still held, starts the delegate once and
commits.

What this cannot show: power loss or a torn write (a killed process leaves
the page cache and every completed write), or a crash inside a router
transaction (test_router_crash.py).
"""
from __future__ import annotations

import unittest

from gen2.supervisor import jobs
from gen2.tests import children
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import DEADLINE, MAIN, PARENT, SupervisedTestCase, released, succeed

GATED = [{"op": "wait_for", "name": "gate", "seconds": 60}, *succeed()]
HANG = [{"op": "hang"}]
CLEAN = ["admitted", "launching", "running", "result_ready", "committed"]
CHILD_CLOCK = "2026-09-27T10:30:00Z"
SHORT_DEADLINE = "2026-09-27T10:30:00.300Z"
LAPSES = "2026-09-27T10:45:00Z"  # a lease expiring after the child's claim (10:30), before the restart (11:00)  # passes while the child polls its running job (its clock reads a millisecond at a time)


class CrashFaults:
    KIND: str

    def crash(self, point: str, steps: list[dict], *, deadline: str | None = None, clock: str = CHILD_CLOCK, prepare: bool = True,
              lease_expires: str | None = None) -> None:
        if prepare:
            self.prepare(self.KIND, lease_expires)
            self.supervisor.prepare(self.order(self.KIND, steps, lease_expires=lease_expires, **({"deadline": deadline} if deadline else {})))
        child = children.python(["-m", "gen2.tests.supervisor_child", str(self.root), MAIN, point, clock], capture_output=True, text=True, timeout=120)
        self.child_runs.append((point, child.returncode, child.stdout, child.stderr))
        self.assertEqual(child.returncode, 137, f"the child did not die at {point}: {child.stdout} {child.stderr}")

    def restart(self) -> dict:
        """A new supervisor in this process, holding nothing in memory."""
        self.clock.set("2026-09-27T11:00:00Z")
        self.supervisor = self.make_supervisor()
        return self.supervisor.recover()

    def committed(self, transitions=tuple(CLEAN), **extra) -> dict:
        base = {"state": "committed", "failure_class": None, "evidence": False, "descendants_confirmed": False, "episodes": 0, "transitions": list(transitions),
                "receipts": 1, "lease_release": released(self.KIND, "final_outcome"), "open_holds": 0, "cleared_holds": 0, "reconciliations": [],
                "other_tables": []}
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

    # -- a recorded launch intent is not renewed authority to start (L-7; Astra 1c review A1) ------------
    # Each: the supervisor dies once launch intent is recorded; the authority it had is withdrawn; the
    # restarted supervisor must start nothing (no start recorded in the job directory, no identity) and
    # the work ends cancelled by the supervisor. The positive control is the test above: the same crash,
    # authority unchanged, starts once and commits.
    def unlaunched(self, lease_release: str | None, by: str = "supervisor") -> None:
        self.assertEqual(self.ended(), {**self.committed(["admitted", "launching", "cancelled"]), "state": "cancelled", "receipts": 0, "evidence": True,
                                        "descendants_confirmed": True, "lease_release": lease_release})
        self.assertEqual(self.value("SELECT cancel_requested_by FROM invocations WHERE invocation_id = ?", MAIN), by)
        self.assertEqual((self.spawns(), self.job_file("identity.json")), (0, None))
        self.assertEqual(self.evidence_record()["output"]["detail"], "cancelled before the launcher started")

    def test_recovery_starts_nothing_in_a_topic_paused_meanwhile(self) -> None:
        self.crash("launch_recorded", succeed())
        self.x("UPDATE queue_entries SET paused_at = ? WHERE topic_id = ?", "2026-09-27T10:45:00Z", rf.TOPIC)
        outcomes = [self.restart()[MAIN]] + [self.supervisor.advance(MAIN) for _ in range(4)]
        self.assertEqual(outcomes, ["waiting_launch"] * 3 + ["cancelled"] * 2)  # the launch budget (3), then cancelled
        self.unlaunched(released(self.KIND, "cancelled"))

    def test_recovery_starts_nothing_once_the_lease_has_expired(self) -> None:
        self.crash("launch_recorded", succeed(), lease_expires=LAPSES)  # the restart's clock (11:00) is past it; the deadline (12:00) is not
        self.assertEqual(self.restart()[MAIN], "cancelled")
        self.unlaunched(released(self.KIND, "cancelled"))

    def test_recovery_starts_nothing_once_the_lease_is_released(self) -> None:
        self.crash("launch_recorded", succeed())
        lease = self.value("SELECT lease_id FROM invocations WHERE invocation_id = ?", PARENT if self.KIND == "delegate" else MAIN)
        self.x("UPDATE leases SET released_at = ?, release_reason = 'expired' WHERE lease_id = ?", "2026-09-27T10:45:00Z", lease)
        self.assertEqual(self.restart()[MAIN], "cancelled")
        self.unlaunched("expired")

    def test_recovery_starts_nothing_once_the_lease_is_replaced(self) -> None:
        if self.KIND == "research_pass":
            self.skipTest("a research lease is not replaced while its topic is active (the router admits no second research claim); "
                          "the released-lease case covers it")
        if self.KIND == "delegate":
            self.skipTest("this fixture's delegate runs under a research pass, whose lease is not replaced (as above); a delegate under "
                          "a parent whose lease can be replaced is DelegateReplacementFaults' (Astra 1c re-review C5)")
        self.crash("launch_recorded", succeed(), lease_expires=LAPSES)
        self.clock.set("2026-09-27T11:00:00Z")
        replacing = self.router.claim({"invocation_id": "inv_replace01", "kind": self.KIND, "topic_id": rf.TOPIC, "config_bundle_hash": rf.CONFIG,
                                       "deadline_at": DEADLINE, "station_id": "station-2", "lease_expires_at": DEADLINE})
        self.assertEqual(replacing["status"], "granted")  # a new generation of the scope; the lapsed lease is released as expired
        self.supervisor = self.make_supervisor()
        self.assertEqual(self.supervisor.recover()[MAIN], "cancelled")
        self.unlaunched("expired")

    def test_recovery_starts_nothing_once_cancellation_is_requested(self) -> None:
        self.crash("launch_recorded", succeed())
        self.assertEqual(self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})["status"], "recorded")
        self.assertEqual(self.restart()[MAIN], "cancelled")
        self.unlaunched(released(self.KIND, "cancelled"), by="operator")

    # -- cancellation after an uncertain spawn (L-4, L-7; Astra 1c review A2, Q5 ruling) --------------------
    # The supervisor dies at the spawn gap; the operator then cancels. The restarted supervisor enters
    # outcome_unknown and reconciles the episode through the owned group, sending its real request (no
    # failure class for a cancellation), and the invocation ends cancelled. The record holds what was
    # found: the observed exit as the launcher recorded it, and how many members were signalled (none,
    # for an empty group). A second restart replays nothing and changes nothing.
    def cancelled_after_the_gap(self) -> dict:
        self.assertEqual(self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})["status"], "recorded")
        self.assertEqual(self.restart()[MAIN], "cancelled")
        self.assertEqual(self.ended(), {**self.committed(["admitted", "launching", "outcome_unknown", "cancelled"]), "state": "cancelled", "receipts": 0,
                                        "evidence": True, "descendants_confirmed": True, "episodes": 1, "cleared_holds": 1,
                                        "lease_release": released(self.KIND, "cancelled"), "reconciliations": ["terminated_group"]})
        self.assertEqual(self.value("SELECT failure_class FROM invocations WHERE invocation_id = ?", MAIN), None)
        record = self.evidence_record()
        before = self.state(exclude=())
        self.supervisor = self.make_supervisor()
        self.assertEqual(self.supervisor.recover()[MAIN], "cancelled")
        self.assertEqual(self.state(exclude=()), before)
        return record

    def test_cancellation_after_an_uncertain_spawn_ends_the_live_group(self) -> None:
        self.crash("spawned", HANG)
        self.wait_for_file("identity.json")
        identity = self.job_file("identity.json")
        record = self.cancelled_after_the_gap()
        self.assertEqual((record["method"], record["termination"], record["descendants"]["handling"], record["findings"]),
                         ("execution_group_termination", {"reason": "cancellation"}, "terminated", []))
        self.assertGreaterEqual(record["descendants"]["count"], 2)  # the launcher and its executor, signalled
        self.assertEqual(jobs.members(identity), [])

    def test_cancellation_after_an_uncertain_spawn_of_work_that_already_exited(self) -> None:
        self.crash("spawned", succeed())
        self.wait_for_file("exit.json")
        record = self.cancelled_after_the_gap()
        self.assertEqual((record["exit"], record["termination"], record["descendants"], record["findings"]),
                         ({"code": 0, "signal": None}, {"reason": "cancellation"}, {"handling": "none_found", "count": 0}, []))
        self.assertIsNotNone(self.spool.read(record["output"]["content_hash"], topic_id=rf.TOPIC))  # the result stays retained, uncommitted

    def test_cancellation_after_a_start_that_never_happened(self) -> None:
        self.crash("spawning", succeed())
        record = self.cancelled_after_the_gap()
        self.assertEqual((record["process"], record["exit"], record["termination"], record["descendants"]),
                         (None, None, {"reason": "cancellation"}, {"handling": "none_found", "count": 0}))
        self.assertTrue((self.root / "jobs" / f"job-{MAIN}" / "abandoned").exists())
        self.assertIsNone(self.job_file("identity.json"))

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

    def test_an_unknown_episode_over_starts_the_os_refused_reconciles_as_never_started(self) -> None:
        """The accepted path beside the abandonment handshake (Astra 1c
        re-review 3, BLOCK 2): every start refused by the OS (the launcher's
        interpreter is missing) leaves the job not_started — no start
        happened, so there is nothing to abandon. An outcome_unknown episode
        is recorded for it through the router's own operation (this seeds
        that state; it does not say the supervisor enters it after an OS
        refusal), and the restarted supervisor reconciles it as never
        started, by lookup: the episode's hold cleared, the lease released,
        no identity and no abandoned mark."""
        self.prepare(self.KIND)
        refused = self.make_supervisor(launcher=(str(self.root / "missing-interpreter"),))
        self.assertEqual(refused.submit(self.order(self.KIND, succeed())), "launching")
        self.assertEqual(refused.job(MAIN).lookup()["verdict"], "not_started")
        grant = self.journal()["grant"]
        self.assertEqual(self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": MAIN, "to_state": "outcome_unknown",
                                                         "unknown_episode": 1, "unknown_cause": "spawn_uncertain"})["status"], "recorded")
        self.assertEqual(self.restart()[MAIN], "failed")
        self.assertEqual(self.ended(), {**self.committed(["admitted", "launching", "outcome_unknown", "failed"]), "state": "failed", "receipts": 0,
                                        "failure_class": "never_started", "evidence": True, "episodes": 1, "cleared_holds": 1,
                                        "lease_release": released(self.KIND, "failed"), "reconciliations": ["confirmed_failed"]})
        self.assertEqual(self.evidence_record()["output"]["detail"], "the launcher never started")
        self.assertIsNone(self.job_file("identity.json"))
        self.assertFalse((self.root / "jobs" / f"job-{MAIN}" / "abandoned").exists())

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


class DelegateReplacementFaults:
    """A delegate whose supervisor died once its launch intent was recorded,
    under a parent of PARENT_KIND (module docstring; Astra 1c re-review C5)."""
    KIND = "delegate"
    PARENT_KIND: str
    crash, restart, committed, unlaunched = CrashFaults.crash, CrashFaults.restart, CrashFaults.committed, CrashFaults.unlaunched

    def crashed_at_launch_intent(self, parent_lease_expires: str | None = None) -> None:
        self.assertEqual(self.supervisor.submit(self.order(self.PARENT_KIND, HANG, inv=PARENT, lease_expires=parent_lease_expires)), "running")
        self.supervisor.prepare(self.order("delegate", succeed()))
        self.crash("launch_recorded", succeed(), prepare=False)

    def test_recovery_starts_no_delegate_once_its_parents_lease_is_replaced(self) -> None:
        self.crashed_at_launch_intent(LAPSES)
        self.clock.set("2026-09-27T11:00:00Z")
        replacing = self.router.claim({"invocation_id": "inv_replace01", "kind": self.PARENT_KIND, "topic_id": rf.TOPIC, "config_bundle_hash": rf.CONFIG,
                                       "deadline_at": DEADLINE, "station_id": "station-2", "lease_expires_at": DEADLINE})
        self.assertEqual((replacing["status"], replacing["lease"]["generation"]), ("granted", 2))  # the parent's lapsed lease is released as expired
        self.supervisor = self.make_supervisor()
        self.assertEqual(self.supervisor.recover()[MAIN], "cancelled")
        self.unlaunched("expired")  # no start recorded, no identity: no executor started

    def test_recovery_starts_the_delegate_once_under_unchanged_authority(self) -> None:
        self.crashed_at_launch_intent()
        self.assertEqual(self.restart()[MAIN], "running")
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.committed())
        self.assertEqual(self.spawns(), 1)


class DelegateUnderDiscoveryReplacementTest(DelegateReplacementFaults, SupervisedTestCase):
    PARENT_KIND = "discovery"


class DelegateUnderVerificationReplacementTest(DelegateReplacementFaults, SupervisedTestCase):
    PARENT_KIND = "verification"


class DelegateUnderCheckpointReplacementTest(DelegateReplacementFaults, SupervisedTestCase):
    PARENT_KIND = "checkpoint"


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
