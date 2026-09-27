"""The lifecycle fault set, the same for every invocation kind (task 1c;
release gates RG-2, RG-3).

Trace: INVARIANTS RG-2 ("for each kind in {research_pass, discovery,
delegate, verification, checkpoint}, the same fault set ... produces the
same state-machine outcomes ... one parametrized suite over all five kinds
with fake executors"), RG-3 (failure paths end in bounded, visible states),
L-1..L-9, C-9, C-10; BOUNDARIES.md Station supervisor; design review §5, §6.

LifecycleFaults holds every test once; the five classes below run it for one
kind each (a kind-specific lifecycle path would be a failure). Every job is a
real launcher process (jobshim.py) running a real fake executor
(fake_executor.py) with its script; the supervisor, router and store run in
this process on a durable store and the real spool. Oracles: the expected
end of each fault is written by hand below (`ended()` reads it back from
every table that records an end, by raw SQL: the invocation row, its
transitions, receipts, the lease, the episode holds and reconciliations);
process death is read from /proc; retained bytes from the spool.

Faults that need the supervisor itself to die (a crash between spawn and
identity record; a crash at each lifecycle boundary) are in
test_supervisor_crash.py.

What this cannot show: power loss (a killed process leaves the page cache),
a descendant that leaves the job's session (jobs.py), or that fencing undoes
an orphan's external effects (it does not, L-7).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.supervisor import jobs
from gen2.tests import children
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import AFTER_DEADLINE, DEADLINE, MAIN, PARENT, SupervisedTestCase, outcome_text, released, succeed

HANG_WITH_DESCENDANT = [{"op": "spawn_descendant", "marker": "descendant.pid"}, {"op": "hang"}]
GATED = [{"op": "wait_for", "name": "gate", "seconds": 60}]


def alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat[stat.rindex(")") + 2] != "Z"


class LifecycleFaults:
    KIND: str

    def submit(self, steps=None, **order) -> str:
        self.prepare(self.KIND, order.pop("parent_lease_expires", None))
        return self.supervisor.submit(self.order(self.KIND, steps, **order))

    def descendant_pid(self) -> int:
        self.wait_for_file("scratch/descendant.pid")
        return int((self.root / "jobs" / f"job-{MAIN}" / "scratch" / "descendant.pid").read_text())

    def expected(self, **fields) -> dict:
        base = {"state": None, "failure_class": None, "evidence": False, "descendants_confirmed": False, "episodes": 0, "transitions": [],
                "receipts": 0, "lease_release": None, "open_holds": 0, "cleared_holds": 0, "reconciliations": []}
        return {**base, **fields}

    def failed(self, failure_class: str, *, via=("admitted", "launching", "running", "failed")) -> dict:
        return self.expected(state="failed", failure_class=failure_class, evidence=True, transitions=list(via), lease_release=released(self.KIND, "failed"))

    # -- a clean end --------------------------------------------------------------
    def test_a_clean_end_commits_the_result_with_its_execution_record(self) -> None:
        self.assertEqual(self.submit(), "running")
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended(), self.expected(state="committed", transitions=["admitted", "launching", "running", "result_ready", "committed"],
                                                     receipts=1, lease_release=released(self.KIND, "final_outcome")))
        payload = self.value("SELECT result_payload_digest FROM invocations WHERE invocation_id = ?", MAIN)
        self.assertEqual(payload, canonical.bytes_digest(outcome_text(MAIN).encode()))
        refs = json.loads(self.value("SELECT receipt FROM operation_receipts WHERE invocation_id = ?", MAIN))["validation"]["validated_hashes"]
        record = json.loads(self.spool.read(refs[1], topic_id=rf.TOPIC))
        self.assertEqual((record["method"], record["exit"], record["descendants"], record["output"]["content_hash"], record["findings"]),
                         ("exit_observed", {"code": 0, "signal": None}, {"handling": "none_found", "count": 0}, payload, []))
        self.assertEqual(self.rows("SELECT count(*) FROM artifacts WHERE staged_by_invocation_id = ?", MAIN), [(2,)])  # the result and its record
        self.assertEqual(self.spawns(), 1)
        identity = self.job_file("identity.json")  # what the launcher recorded, verified, is what the router holds (L-3): never a pid alone
        self.assertEqual(self.rows("SELECT job_handle, host_id, container_id, boot_id, start_fingerprint FROM invocations WHERE invocation_id = ?", MAIN),
                         [(f"job-{MAIN}", "host-test", None, jobs.boot_id(),
                           f"pid={identity['pid']};starttime={identity['starttime']};session={identity['session']}")])
        self.assertEqual(identity["session"], identity["pid"])  # the launcher leads its own session: the job's execution group

    # -- structural checks decide (L-5, L-9) -----------------------------------------
    def test_empty_output_is_a_structural_failure_whatever_the_agent_says(self) -> None:
        for steps, self_report in (([], None), ([{"op": "write", "name": "outcome.json", "text": ""}], None), ([{"op": "claim_success"}], '{"status": "completed"}')):
            with self.subTest(steps=steps):
                self.tearDown()
                self.setUp()
                self.submit(steps)
                self.assertEqual(self.supervisor.run(MAIN), "failed")
                self.assertEqual(self.ended(), self.failed("empty_output"))
                record = self.evidence_record()
                self.assertEqual((record["output"]["status"] in ("absent", "empty"), record["self_report"], record["findings"]), (True, self_report, ["empty_output"]))
                self.assertEqual(self.rows("SELECT count(*) FROM audit_events WHERE invocation_id = ? AND kind = 'transition' AND detail LIKE '%failed%'", MAIN), [(1,)])

    def test_a_wrong_declared_digest_fails(self) -> None:
        self.submit([*succeed(), {"op": "declare_digest", "digest": rf.h("a")}])
        self.assertEqual(self.supervisor.run(MAIN), "failed")
        self.assertEqual(self.ended(), self.failed("output_digest_mismatch"))
        self.assertEqual(self.evidence_record()["output"]["declared_digest"], rf.h("a"))

    def test_a_correct_declared_digest_is_still_only_data(self) -> None:
        self.submit([*succeed(), {"op": "declare_digest", "digest": canonical.bytes_digest(outcome_text(MAIN).encode())}])
        self.assertEqual(self.supervisor.run(MAIN), "committed")

    def test_output_is_never_read_through_a_symlink_or_a_hard_link(self) -> None:
        outside = self.root / "outside.json"
        outside.write_text(outcome_text(MAIN))  # a valid outcome, but not the job's own file (C-9)
        for op in ("symlink", "link"):
            with self.subTest(op):
                self.tearDown()
                self.setUp()
                outside = self.root / "outside.json"
                outside.write_text(outcome_text(MAIN))
                self.submit([{"op": op, "name": "outcome.json", "target": str(outside)}])
                self.assertEqual(self.supervisor.run(MAIN), "failed")
                self.assertEqual(self.ended(), self.failed("output_refused"))
                self.assertIsNone(self.spool.read(canonical.bytes_digest(outside.read_bytes()), topic_id=rf.TOPIC))

    def test_an_exit_status_or_a_signal_fails(self) -> None:
        for steps, failure in (([*succeed(), {"op": "exit", "code": 3}], "exit_nonzero"), ([{"op": "kill_self", "signal": 9}], "killed")):
            with self.subTest(failure):
                self.tearDown()
                self.setUp()
                self.submit(steps)
                self.assertEqual(self.supervisor.run(MAIN), "failed")
                self.assertEqual(self.ended(), self.failed(failure))

    # -- descendants (L-7) -------------------------------------------------------------
    def test_a_primary_that_exits_leaving_a_descendant(self) -> None:
        self.submit([{"op": "spawn_descendant", "marker": "descendant.pid"}, *succeed()])
        pid = self.descendant_pid()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertFalse(alive(pid))
        self.assertEqual(self.ended()["transitions"], ["admitted", "launching", "running", "result_ready", "committed"])
        refs = json.loads(self.value("SELECT receipt FROM operation_receipts WHERE invocation_id = ?", MAIN))["validation"]["validated_hashes"]
        record = json.loads(self.spool.read(refs[1], topic_id=rf.TOPIC))
        self.assertEqual((record["descendants"], record["termination"]), ({"handling": "terminated", "count": 1}, {"reason": "descendants_after_exit"}))

    def test_timeout_terminates_the_whole_group(self) -> None:
        self.assertEqual(self.submit(HANG_WITH_DESCENDANT), "running")
        pid = self.descendant_pid()
        self.assertEqual(self.supervisor.advance(MAIN), "running")
        self.clock.set(AFTER_DEADLINE)
        self.assertEqual(self.supervisor.run(MAIN), "failed")
        self.assertEqual(self.ended(), self.failed("timeout"))
        self.assertFalse(alive(pid))
        record = self.evidence_record()
        self.assertEqual((record["method"], record["termination"], record["descendants"]["handling"]),
                         ("execution_group_termination", {"reason": "timeout"}, "terminated"))
        self.assertGreaterEqual(record["descendants"]["count"], 3)  # the launcher, the executor and its descendant

    # -- cancellation (L-7) --------------------------------------------------------------
    def test_cancellation_terminates_the_group_then_releases_capacity(self) -> None:
        self.assertEqual(self.submit(HANG_WITH_DESCENDANT), "running")
        pid = self.descendant_pid()
        self.assertEqual(self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})["status"], "recorded")
        self.assertEqual(self.ended()["lease_release"], None)  # nothing released before the group is confirmed gone
        self.assertEqual(self.supervisor.run(MAIN), "cancelled")
        self.assertFalse(alive(pid))
        self.assertEqual(self.ended(), self.expected(state="cancelled", evidence=True, descendants_confirmed=True,
                                                     transitions=["admitted", "launching", "running", "cancelled"],
                                                     lease_release=released(self.KIND, "cancelled")))
        self.assertEqual(self.evidence_record()["termination"], {"reason": "cancellation"})

    def test_a_cancellation_requested_before_the_result_wins(self) -> None:
        self.assertEqual(self.submit([*GATED, *succeed()]), "running")
        self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})
        self.gate()
        self.wait_for_file("exit.json")  # the executor finished its result before the supervisor looked again
        self.assertEqual(self.supervisor.run(MAIN), "cancelled")
        self.assertEqual(self.ended(), self.expected(state="cancelled", evidence=True, descendants_confirmed=True,
                                                     transitions=["admitted", "launching", "running", "cancelled"],
                                                     lease_release=released(self.KIND, "cancelled")))
        result = self.journal()["collected"]["result"]
        self.assertIsNotNone(self.spool.read(result["content_hash"], topic_id=rf.TOPIC))  # retained, not committed (C-10)

    def test_a_result_staged_before_the_cancellation_wins(self) -> None:
        self.submit()

        class Stop(Exception):
            pass

        def stop(point: str) -> None:
            if point == "result_ready_recorded":
                raise Stop(point)
        self.supervisor = self.make_supervisor(fault=stop)
        with self.assertRaises(Stop):
            self.supervisor.run(MAIN)
        before = self.state(exclude=())
        self.assertEqual(self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})["reason"], "not_cancellable")
        self.assertEqual(self.state(exclude=()), before)
        self.supervisor = self.make_supervisor()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended()["transitions"], ["admitted", "launching", "running", "result_ready", "committed"])

    def test_pause_holds_launch_within_its_budget_then_cancels(self) -> None:
        """The topic is paused after the claim: the final launch-admission
        check refuses (L-7), within the launch budget, then the supervisor
        cancels the admitted work (nothing was spawned, L-2)."""
        self.prepare(self.KIND)

        class Stop(Exception):
            pass

        def stop(point: str) -> None:
            if point == "claimed":
                raise Stop(point)
        with self.assertRaises(Stop):
            self.make_supervisor(fault=stop).submit(self.order(self.KIND))
        self.x("UPDATE queue_entries SET paused_at = ? WHERE topic_id = ?", "2026-09-27T10:00:00Z", rf.TOPIC)
        outcomes = [self.supervisor.advance(MAIN) for _ in range(5)]
        self.assertEqual(outcomes, ["waiting_launch"] * 3 + ["cancelled", "cancelled"])
        self.assertEqual(self.ended(), self.expected(state="cancelled", descendants_confirmed=True, transitions=["admitted", "cancelled"],
                                                     lease_release=released(self.KIND, "cancelled")))
        self.assertEqual(self.rows("SELECT cancel_requested_by FROM invocations WHERE invocation_id = ?", MAIN), [("supervisor",)])
        self.assertEqual(self.spawns(), 0)

    # -- stale results (C-10) -------------------------------------------------------------
    def test_a_result_after_its_lease_is_lost_is_retained_not_committed(self) -> None:
        lapse = "2026-09-27T11:00:00Z"
        self.assertEqual(self.submit([*GATED, *succeed()], lease_expires=lapse, parent_lease_expires=lapse), "running")
        self.clock.set("2026-09-27T11:00:01Z")
        self.gate()
        self.assertEqual(self.supervisor.run(MAIN), "failed")
        self.assertEqual(self.ended(), self.failed("result_rejected", via=("admitted", "launching", "running", "result_ready", "failed")))
        digest = self.value("SELECT result_payload_digest FROM invocations WHERE invocation_id = ?", MAIN)
        self.assertIsNotNone(self.spool.read(digest, topic_id=rf.TOPIC))
        self.assertEqual(self.rows("SELECT reason FROM (SELECT json_extract(detail, '$.reason') AS reason FROM audit_events WHERE kind = 'commit_rejected' "
                                   "AND invocation_id = ?)", MAIN), [("lease_not_current",)])

    # -- replay (C-5) -------------------------------------------------------------------------
    def test_a_delivered_result_replays_and_changes_nothing(self) -> None:
        self.submit()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        before = self.state(exclude=())
        envelope = self.journal()["envelope"]
        self.assertEqual(self.router.commit_outcome(envelope)["status"], "replayed")
        grant = self.journal()["grant"]
        digest = envelope["payload_digest"]
        self.assertEqual(self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": MAIN, "to_state": "result_ready",
                                                        "result_payload_digest": digest})["status"], "replayed")
        calls = self.control.calls
        restarted = self.make_supervisor()
        self.assertEqual(restarted.recover()[MAIN], "committed")
        self.assertEqual(self.control.calls, calls + (1 if self.KIND == "delegate" else 0))  # settled: nothing sent (the parent still runs)
        self.assertEqual(self.state(exclude=()), before)

    # -- router outage (C-10, L-6) -----------------------------------------------------------
    def test_an_unreachable_router_stalls_within_budget_and_delivery_resumes_by_replay(self) -> None:
        self.assertEqual(self.submit([*GATED, *succeed()]), "running")
        self.control.down = True
        before = self.state()
        self.gate()
        self.wait_for_file("exit.json")
        outcomes = [self.supervisor.advance(MAIN) for _ in range(8)]
        self.assertEqual(outcomes, ["router_unavailable"] * 5 + ["stalled"] * 3)
        self.assertEqual(self.control.refused, 6)  # the router budget (5), then the one that stalled; nothing after
        self.assertEqual(self.state(), before)  # no authoritative change while the router is away
        self.assertEqual(self.journal()["incident"]["kind"], "router_unreachable")
        result = self.journal()["collected"]["result"]
        self.assertIsNotNone(self.spool.read(result["content_hash"], topic_id=rf.TOPIC))  # the result is retained meanwhile
        self.control.down = False
        self.assertEqual(self.supervisor.advance(MAIN), "stalled")  # only recover() resumes a stalled job
        self.assertEqual(self.supervisor.recover()[MAIN], "committed")
        self.assertEqual(self.ended(), self.expected(state="committed", transitions=["admitted", "launching", "running", "result_ready", "committed"],
                                                     receipts=1, lease_release=released(self.KIND, "final_outcome")))
        self.assertEqual(self.journal()["budgets"].get("recovery"), 1)

    def test_the_deadline_still_ends_work_while_the_router_is_away(self) -> None:
        self.assertEqual(self.submit(HANG_WITH_DESCENDANT), "running")
        pid = self.descendant_pid()
        self.control.down = True
        self.clock.set(AFTER_DEADLINE)
        self.assertEqual(self.supervisor.advance(MAIN), "router_unavailable")
        self.assertFalse(alive(pid))  # terminated locally, at its deadline
        self.control.down = False
        self.assertEqual(self.supervisor.run(MAIN), "failed")
        self.assertEqual(self.ended(), self.failed("timeout"))

    # -- outcome_unknown (L-4) -----------------------------------------------------------------
    def test_a_launcher_gone_without_an_exit_is_reconciled_by_terminating_its_group(self) -> None:
        self.assertEqual(self.submit(HANG_WITH_DESCENDANT), "running")
        pid = self.descendant_pid()
        os.kill(self.job_file("identity.json")["pid"], signal.SIGKILL)  # the launcher dies; its executor and descendant are left in the group
        self.assertEqual(self.supervisor.run(MAIN), "failed")
        self.assertFalse(alive(pid))
        self.assertEqual(self.ended(), self.expected(state="failed", failure_class="no_exit_record", evidence=True, episodes=1, cleared_holds=1,
                                                     transitions=["admitted", "launching", "running", "outcome_unknown", "failed"],
                                                     lease_release=released(self.KIND, "failed"), reconciliations=["terminated_group"]))

    def test_a_group_gone_without_an_exit_is_reconciled_by_lookup(self) -> None:
        self.assertEqual(self.submit([{"op": "hang"}]), "running")
        identity = self.job_file("identity.json")
        for victims in ([identity["pid"]], None):  # the launcher first, so it records no exit; then the rest of the group
            for pid in victims or jobs.members(identity):
                os.kill(pid, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while any(alive(pid) for pid in (victims or jobs.members(identity))) and time.monotonic() < deadline:
                for popen in self.supervisor._children.values():
                    popen.poll()
                time.sleep(0.01)
        self.assertEqual(self.supervisor.run(MAIN), "failed")
        self.assertEqual(self.ended(), self.expected(state="failed", failure_class="no_exit_record", evidence=True, episodes=1, cleared_holds=1,
                                                     transitions=["admitted", "launching", "running", "outcome_unknown", "failed"],
                                                     lease_release=released(self.KIND, "failed"), reconciliations=["confirmed_failed"]))

    def stop_at(self, point: str) -> None:
        """Run the job with a supervisor that stops (an exception) at `point`."""
        class Stop(Exception):
            pass

        def stop(reached: str) -> None:
            if reached == point:
                raise Stop(reached)
        with self.assertRaises(Stop):
            self.make_supervisor(fault=stop).run(MAIN)

    def test_cancellation_before_any_start_starts_nothing(self) -> None:
        self.prepare(self.KIND)
        self.supervisor.prepare(self.order(self.KIND))
        self.stop_at("launch_recorded")
        self.assertEqual(self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})["status"], "recorded")
        self.assertEqual(self.make_supervisor().run(MAIN), "cancelled")
        self.assertEqual(self.ended(), self.expected(state="cancelled", evidence=True, descendants_confirmed=True,
                                                     transitions=["admitted", "launching", "cancelled"], lease_release=released(self.KIND, "cancelled")))
        self.assertEqual(self.spawns(), 0)

    def test_a_deadline_passed_before_any_start_starts_nothing(self) -> None:
        self.prepare(self.KIND)
        self.supervisor.prepare(self.order(self.KIND))
        self.stop_at("launch_recorded")
        self.clock.set(AFTER_DEADLINE)
        self.assertEqual(self.make_supervisor().run(MAIN), "failed")
        self.assertEqual(self.ended(), self.failed("never_started", via=("admitted", "launching", "failed")))
        self.assertEqual(self.spawns(), 0)

    def test_a_slow_start_found_after_a_restart_is_given_its_grace(self) -> None:
        """A start recorded by a supervisor that then died, whose launcher takes
        0.3 s to appear: the restarted supervisor waits its start grace (1 s
        here) for it instead of abandoning it, and finds it running."""
        self.prepare(self.KIND)
        self.supervisor.prepare(self.order(self.KIND, [*GATED, *succeed()]))
        self.stop_at("spawning")
        job = self.root / "jobs" / f"job-{MAIN}"
        late = subprocess.Popen(["sh", "-c", f'sleep 0.3; exec "{sys.executable}" "{children.path("gen2/supervisor/jobshim.py")}" "{job}"'],
                                start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(late.wait)
        self.supervisor = self.make_supervisor()
        self.assertEqual(self.supervisor.recover()[MAIN], "running")
        self.gate()
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual(self.ended()["reconciliations"], ["found_running"])
        self.assertFalse((job / "abandoned").exists())

    def test_a_commit_refused_while_paused_is_resent_within_its_budget(self) -> None:
        for resume, outcomes, end in ((True, ["result_ready", "committed"], "committed"), (False, ["result_ready"] * 3 + ["failed"], "failed")):
            with self.subTest(resume=resume):
                self.tearDown()
                self.setUp()
                self.submit()
                self.stop_at("result_ready_recorded")
                self.x("UPDATE queue_entries SET paused_at = ? WHERE topic_id = ?", "2026-09-27T10:00:00Z", rf.TOPIC)
                supervisor, seen = self.make_supervisor(), []
                for _ in outcomes:
                    seen.append(supervisor.advance(MAIN))
                    if resume:
                        self.x("UPDATE queue_entries SET paused_at = NULL WHERE topic_id = ?", rf.TOPIC)
                self.assertEqual(seen, outcomes)
                self.assertEqual(self.ended()["state"], end)
                self.assertEqual(self.ended()["failure_class"], None if resume else "result_rejected")

    # -- budgets (L-6) ---------------------------------------------------------------------------
    def test_a_launcher_that_cannot_start_fails_within_the_spawn_budget(self) -> None:
        self.prepare(self.KIND)
        self.supervisor = self.make_supervisor(launcher=(str(self.root / "no-such-interpreter"),))
        outcomes = [self.supervisor.submit(self.order(self.KIND))] + [self.supervisor.advance(MAIN) for _ in range(3)]
        self.assertEqual(outcomes, ["launching", "launching", "failed", "failed"])
        self.assertEqual(self.ended(), self.failed("spawn_failed", via=("admitted", "launching", "failed")))
        self.assertEqual(self.job_file("spawn.json"), {"attempts": 2, "failed": 2})


class ResearchPassLifecycleTest(LifecycleFaults, SupervisedTestCase):
    KIND = "research_pass"


class DiscoveryLifecycleTest(LifecycleFaults, SupervisedTestCase):
    KIND = "discovery"


class DelegateLifecycleTest(LifecycleFaults, SupervisedTestCase):
    KIND = "delegate"


class VerificationLifecycleTest(LifecycleFaults, SupervisedTestCase):
    KIND = "verification"


class CheckpointLifecycleTest(LifecycleFaults, SupervisedTestCase):
    KIND = "checkpoint"


if __name__ == "__main__":
    unittest.main()
