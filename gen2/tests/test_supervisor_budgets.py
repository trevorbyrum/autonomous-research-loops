"""Bounded, visible failure of the supervisor's own infrastructure, for every
invocation kind (task 1c-repair; Astra 1c review A4, A5; INVARIANTS C-10,
L-6, RG-3).

Trace: C-10 ("a full spool or failed durable result write is an
infrastructure failure, never a completion"), L-6 (every retry path consumes
a declared attempt/time budget), RG-3 (exhausted retries and failed hold
persistence end in a typed hold or control incident with an owner and a
deadline; none loops unbounded, none is swallowed).

Durable writes (A4): a write the supervisor cannot make — an execution
record over the spool quota, ENOSPC from the spool, a termination or
reconciliation record, the journal itself — is retried on later advances
within the write budget, keeping what was already observed (the collected
bytes, a termination's facts) so a retry never observes again; exhausted,
the job stalls with an owned, deadlined incident; when even the journal
(where that incident lives) cannot be written, advance() raises
ControlFailure out of band. Nothing reaches the router meanwhile. Recovery
controls: once the write succeeds, recover() delivers the retained end.

Router budget (A5): an outage episode is budgeted from its first failed call
until a write the router answers; a successful status read refunds nothing,
so a write that keeps failing while reads succeed stalls within its budget,
by attempts or by time; recover() resumes a stalled job without refilling an
exhausted budget.

Refused lifecycle writes and unresolved outcome_unknown (task 1c-repair-2;
L-6, RG-3, L-4): a write the router refuses — here a failure's end — is sent
afresh within the refusal budget, then the job stalls with an owned,
deadlined incident naming the budget, the write and the last refusal; a
refusal no retry can change (a conflict) stalls at once. An outcome_unknown
episode that cannot be reconciled — here a vanished launcher's group whose
termination is never confirmed — is looked at again within the unknown
budget, by attempts and by time, then stalls the same way while its hold
stays open. For each: further advances and a restarted supervisor (no
recover()) send and terminate nothing more and leave the incident, its
deadline and the store as they were; controls: a refusal or an unresolved
episode that clears within budget refunds it, and recover() resumes a
stalled job once the router accepts or the group ends.

Oracles: expected outcomes written by hand; the store read back by raw SQL
(unchanged while the supervisor cannot deliver); the journal and spool read
from disk; process death read from /proc; the calls and terminations counted
where they are made.
"""
from __future__ import annotations

import errno
import json
import os
import signal
import time
import unittest
from pathlib import Path
from unittest import mock

from gen2.core import canonical
from gen2.core.control import ControlUnavailable
from gen2.core.instants import utc_instant_ns
from gen2.supervisor import jobs, spool as spool_module
from gen2.supervisor.supervisor import ControlFailure
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import AFTER_DEADLINE, MAIN, SupervisedTestCase, Unreachable, released

HANG_WITH_DESCENDANT = [{"op": "spawn_descendant", "marker": "descendant.pid"}, {"op": "hang"}]
CLEAN = ["admitted", "launching", "running", "result_ready", "committed"]


def alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat[stat.rindex(")") + 2] != "Z"


class WritesDown(Unreachable):
    """Partial availability: status reads reach the router, record_transition does not."""

    def __init__(self, router, down=("record_transition",)) -> None:
        super().__init__(router)
        self.methods, self.attempts = set(down), 0

    def __getattr__(self, name):
        call = super().__getattr__(name)

        def partial(request):
            if name in self.methods:
                self.attempts += 1
                raise ControlUnavailable(name)
            return call(request)
        return partial


class Refusing(Unreachable):
    """The router refuses the job's `to_state` transition (or, with `method`,
    that call) with `reason`: the next `times` sends, or every one while
    `times` is None. `refusals` counts the refused sends. Nests: the inner
    one may refuse another write."""

    def __init__(self, router, to_state: str | None, reason: str, times: int | None = None, method: str = "record_transition") -> None:
        super().__init__(router)
        self.to_state, self.reason, self.times, self.method, self.refusals = to_state, reason, times, method, 0

    def __getattr__(self, name):
        call = super().__getattr__(name)

        def maybe(request):
            if name == self.method and request.get("invocation_id") == MAIN and (self.to_state is None or request.get("to_state") == self.to_state) \
                    and (self.times is None or self.refusals < self.times):
                self.refusals += 1
                return {"status": "refused", "reason": self.reason, "detail": "refused by the test"}
            return call(request)
        return maybe


class Unconfirmed:
    """jobs.Job.terminate for a group that will not end: nothing is signalled
    and the group is never confirmed empty. `calls` counts the attempts."""

    def __init__(self) -> None:
        self.calls = 0

    def terminate(self, job, identity, **kwargs) -> dict:
        self.calls += 1
        return {"found": len(jobs.members(identity)), "confirmed": False}

    def patched(self):
        return mock.patch.object(jobs.Job, "terminate", lambda job, identity, **kwargs: self.terminate(job, identity, **kwargs))


class BudgetFaults:
    KIND: str

    def submit(self, steps=None, **order) -> str:
        self.prepare(self.KIND)
        return self.supervisor.submit(self.order(self.KIND, steps, **order))

    def ended_clean(self) -> dict:
        return {"state": "committed", "failure_class": None, "evidence": False, "descendants_confirmed": False, "episodes": 0, "transitions": CLEAN,
                "receipts": 1, "lease_release": released(self.KIND, "final_outcome"), "open_holds": 0, "cleared_holds": 0, "reconciliations": [],
                "other_tables": []}

    def incident(self, kind: str) -> dict:
        found = self.journal().get("incident")
        self.assertIsNotNone(found, f"no {kind} incident")
        self.assertEqual((found["kind"], found["owner"]), (kind, "supervisor:station-1"))
        self.assertGreater(utc_instant_ns(found["deadline_at"]), utc_instant_ns(found["since"]))  # owned and deadlined (RG-3)
        return found

    def exited(self) -> bytes:
        """Run the job to its exit (the executor wrote its result), without the supervisor looking yet."""
        self.assertEqual(self.submit(), "running")
        self.wait_for_file("exit.json")
        return (self.root / "jobs" / f"job-{MAIN}" / "scratch" / "outcome.json").read_bytes()

    # -- A4: durable writes ---------------------------------------------------------------------------
    def test_an_execution_record_over_the_quota_stalls_with_the_result_kept(self) -> None:
        """Enough quota for the result, none for its execution record."""
        result = self.exited()
        before = self.state()
        self.spool.quota_bytes = self.spool.usage() + len(result)
        outcomes = [self.supervisor.advance(MAIN) for _ in range(5)]
        self.assertEqual(outcomes, ["write_failed"] * 3 + ["stalled"] * 2)  # the write budget (3), then an incident
        found = self.incident("durable_write_failed")
        self.assertEqual(found["phase"], "collection")
        self.assertTrue(found["error"].startswith("SpoolFull"), found)
        self.assertEqual(self.state(), before)  # nothing reached the router: the job is authoritatively running
        kept = self.journal()["observing"]
        self.assertEqual(kept["result"]["content_hash"], canonical.bytes_digest(result))
        self.assertEqual(self.spool.read(kept["result"]["content_hash"], topic_id=rf.TOPIC), result)  # the collected bytes are staged and kept
        self.spool.quota_bytes = 1 << 30
        self.assertEqual(self.supervisor.recover()[MAIN], "committed")
        self.assertEqual(self.ended(), self.ended_clean())
        self.assertEqual(self.value("SELECT result_payload_digest FROM invocations WHERE invocation_id = ?", MAIN), canonical.bytes_digest(result))
        self.assertEqual((self.journal()["budgets"].get("write"), self.journal().get("write_failure")), (None, None))  # the write made progress: refunded

    def test_enospc_from_the_spool_stalls_with_an_incident(self) -> None:
        result = self.exited()
        before = self.state()
        real = spool_module._write_once

        def full_for_records(dir_fd, name, payload):
            if b'"record_version":"execution-record/1"' in payload:
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
            return real(dir_fd, name, payload)
        attempts = []

        def counted(dir_fd, name, payload):
            if b'"record_version":"execution-record/1"' in payload:
                attempts.append(name)
            return full_for_records(dir_fd, name, payload)
        with mock.patch.object(spool_module, "_write_once", counted):
            outcomes = [self.supervisor.advance(MAIN) for _ in range(4)]
            raised = self.incident("durable_write_failed")
            outcomes += [self.supervisor.advance(MAIN) for _ in range(3)]
        self.assertEqual(outcomes, ["write_failed"] * 3 + ["stalled"] * 4)
        self.assertEqual(len(attempts), 4)  # the budget (3), then the one that stalled; a stalled job retries nothing until recover()
        self.assertEqual(self.incident("durable_write_failed"), raised)  # and its incident stays as it was raised
        self.assertIn("No space left on device", raised["error"])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.supervisor.recover()[MAIN], "committed")
        self.assertEqual(self.ended(), self.ended_clean())
        self.assertEqual(self.value("SELECT result_payload_digest FROM invocations WHERE invocation_id = ?", MAIN), canonical.bytes_digest(result))

    def test_a_termination_record_that_cannot_be_written_keeps_the_termination(self) -> None:
        """The deadline ends the group (a local action, done once); its record
        cannot be staged. The retries and the eventual delivery carry the
        termination as it happened, not a second look at an empty group."""
        self.assertEqual(self.submit(HANG_WITH_DESCENDANT), "running")
        self.wait_for_file("scratch/descendant.pid")
        identity = self.job_file("identity.json")
        before = self.state()
        self.spool.quota_bytes = self.spool.usage()
        self.clock.set(AFTER_DEADLINE)
        outcomes = [self.supervisor.advance(MAIN) for _ in range(4)]
        self.assertEqual(outcomes, ["write_failed"] * 3 + ["stalled"])
        self.assertEqual(jobs.members(identity), [])  # ended at its deadline, whatever the spool
        kept = self.journal()["observing"]
        self.assertEqual((kept["terminated"], kept["observation"]["termination"], kept["observation"]["descendants"]["handling"]),
                         ("timeout", {"reason": "timeout"}, "terminated"))
        self.assertGreaterEqual(kept["observation"]["descendants"]["count"], 3)
        self.assertEqual(self.state(), before)
        self.spool.quota_bytes = 1 << 30
        self.assertEqual(self.supervisor.recover()[MAIN], "failed")
        record = self.evidence_record()
        self.assertEqual((record["termination"], record["descendants"]), (kept["observation"]["termination"], kept["observation"]["descendants"]))
        self.assertEqual(self.value("SELECT failure_class FROM invocations WHERE invocation_id = ?", MAIN), "timeout")

    def test_a_reconciliation_record_that_cannot_be_written_keeps_the_termination(self) -> None:
        """Delivery phase: the launcher vanishes, the group is terminated to
        reconcile the episode, and the reconciliation's record cannot be
        staged. The episode stays open under its hold meanwhile; recovery
        reconciles it with the termination's own facts."""
        self.assertEqual(self.submit(HANG_WITH_DESCENDANT), "running")
        self.wait_for_file("scratch/descendant.pid")
        identity = self.job_file("identity.json")
        os.kill(identity["pid"], signal.SIGKILL)
        deadline = time.monotonic() + 5
        while alive(identity["pid"]) and time.monotonic() < deadline:
            self.reap()
            time.sleep(0.01)
        self.spool.quota_bytes = self.spool.usage()
        outcomes = [self.supervisor.advance(MAIN) for _ in range(4)]
        self.assertEqual(outcomes, ["write_failed"] * 3 + ["stalled"])
        self.assertEqual(self.incident("durable_write_failed")["phase"], "delivery")
        self.assertEqual(jobs.members(identity), [])
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "outcome_unknown")
        pending = self.journal()["pending"]
        self.assertEqual((pending["purpose"], pending["resolution"], pending["record"]), ("reconcile:1", "terminated_group", None))
        self.spool.quota_bytes = 1 << 30
        self.assertEqual(self.supervisor.recover()[MAIN], "failed")
        self.assertEqual(self.ended()["reconciliations"], ["terminated_group"])
        self.assertEqual(self.evidence_record()["descendants"], pending["observation"]["descendants"])

    def test_a_journal_that_cannot_be_written_is_an_out_of_band_control_failure(self) -> None:
        """The journal is where the job's incident lives: when it cannot be
        written, nothing can be recorded about the failure, and advance()
        raises ControlFailure to its caller instead of reporting a state."""
        self.exited()
        before = self.state()
        real = jobs.Job.write

        def refuse_journal(job, name, value):
            if name == "journal.json":
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
            return real(job, name, value)
        with mock.patch.object(jobs.Job, "write", refuse_journal):
            for _ in range(2):
                with self.assertRaises(ControlFailure) as raised:
                    self.supervisor.advance(MAIN)
                self.assertIn(f"job-{MAIN}", str(raised.exception))
                self.assertIn("No space left on device", str(raised.exception))
        self.assertEqual(self.state(), before)
        self.assertEqual(self.supervisor.run(MAIN), "committed")  # the journal writable again: nothing was lost
        self.assertEqual(self.ended(), self.ended_clean())

    # -- A5: the router budget belongs to the operation, not to whichever call answers ------------------
    def test_a_write_that_keeps_failing_stalls_although_reads_succeed(self) -> None:
        self.exited()
        before = self.state()
        partial = WritesDown(self.router)
        supervisor = self.make_supervisor(control=partial)
        outcomes = [supervisor.advance(MAIN) for _ in range(8)]
        self.assertEqual(outcomes, ["router_unavailable"] * 5 + ["stalled"] * 3)
        self.assertEqual(partial.attempts, 6)  # the budget (5), then the one that stalled; nothing after
        self.assertEqual(self.incident("router_unreachable")["method"], "record_transition")
        self.assertEqual(self.state(), before)
        self.assertEqual(supervisor.recover()[MAIN], "stalled")  # still down: recovery resumes without refilling the exhausted budget
        self.assertEqual((partial.attempts, self.journal()["budgets"]["recovery"]), (7, 1))
        self.assertEqual(self.make_supervisor().recover()[MAIN], "committed")  # the write reaches the router: delivered once
        self.assertEqual(self.ended(), self.ended_clean())
        self.assertEqual((self.journal()["budgets"]["router"], self.journal().get("outage")), (0, None))  # progress ends the episode

    def test_an_outage_is_also_bounded_in_time(self) -> None:
        self.exited()
        partial = WritesDown(self.router)
        supervisor = self.make_supervisor(control=partial)
        self.assertEqual(supervisor.advance(MAIN), "router_unavailable")
        since = self.journal()["outage"]["since"]
        self.clock.set("2027-01-01T00:00:00Z")  # past the outage window, two attempts into a budget of five
        self.assertEqual(supervisor.advance(MAIN), "stalled")
        self.assertEqual((partial.attempts, self.incident("router_unreachable")["outage_since"]), (2, since))

    # -- a lifecycle write the router refuses (task 1c-repair-2) ----------------------------------------
    def failed_end(self) -> None:
        """The job exits 3: its end is a failure the supervisor records."""
        self.assertEqual(self.submit([{"op": "exit", "code": 3}]), "running")
        self.wait_for_file("exit.json")

    def ended_failed(self) -> dict:
        return {**self.ended_clean(), "state": "failed", "failure_class": "exit_nonzero", "evidence": True, "transitions": ["admitted", "launching", "running", "failed"],
                "receipts": 0, "lease_release": released(self.KIND, "failed")}

    def stalled_unchanged(self, control, count, advances: int = 3) -> dict:
        """A restarted supervisor, half an hour later, recover() not run: it
        sends nothing more, and the incident (its deadline included) and the
        store stay as they were."""
        found, before, done = self.journal()["incident"], self.state(exclude=()), count()
        self.clock.set("2026-09-27T10:30:00Z")
        restarted = self.make_supervisor(control=control)
        self.assertEqual([restarted.advance(MAIN) for _ in range(advances)], ["stalled"] * advances)
        self.assertEqual((count(), self.journal()["incident"], self.state(exclude=())), (done, found, before))
        self.assertIn({"invocation_id": MAIN, "blocking": True, **found}, restarted.incidents())
        return found

    def test_a_refused_end_is_resent_within_its_budget_then_stalls(self) -> None:
        self.failed_end()
        before = self.state()
        refusing = Refusing(self.router, "failed", "transition_not_allowed")
        supervisor = self.make_supervisor(control=refusing)
        outcomes = [supervisor.advance(MAIN) for _ in range(6)]
        self.assertEqual(outcomes, ["end_refused:transition_not_allowed"] * 3 + ["stalled"] * 3)
        self.assertEqual(refusing.refusals, 4)  # the budget (3), then the one that stalled; nothing after
        found = self.incident("lifecycle_write_refused")
        self.assertEqual({k: found[k] for k in ("budget", "write", "last_refusal", "final")},
                         {"budget": "refusal", "write": "end", "last_refusal": {"reason": "transition_not_allowed", "detail": "refused by the test"}, "final": False})
        self.assertEqual(self.state(), before)  # nothing recorded: the job is authoritatively running
        self.stalled_unchanged(refusing, lambda: refusing.refusals)
        self.assertEqual(self.make_supervisor().recover()[MAIN], "failed")  # the router accepts it: recovery delivers the end once
        self.assertEqual(self.ended(), self.ended_failed())

    def test_a_refusal_no_retry_can_change_stalls_at_once(self) -> None:
        """A conflict: another fact is recorded under the write-once key, so
        a retry would be refused the same way. It spends no budget."""
        self.failed_end()
        refusing = Refusing(self.router, "failed", "transition_conflict")
        supervisor = self.make_supervisor(control=refusing)
        self.assertEqual([supervisor.advance(MAIN) for _ in range(3)], ["stalled"] * 3)
        self.assertEqual(refusing.refusals, 1)
        found = self.incident("lifecycle_write_refused")
        self.assertEqual((found["last_refusal"]["reason"], found["final"], self.journal()["budgets"].get("refusal")), ("transition_conflict", True, None))
        self.stalled_unchanged(refusing, lambda: refusing.refusals)

    def test_a_refused_end_accepted_within_its_budget_refunds_it(self) -> None:
        self.failed_end()
        refusing = Refusing(self.router, "failed", "transition_not_allowed", times=2)
        supervisor = self.make_supervisor(control=refusing)
        self.assertEqual([supervisor.advance(MAIN) for _ in range(3)], ["end_refused:transition_not_allowed"] * 2 + ["failed"])
        journal = self.journal()
        self.assertEqual((journal.get("incident"), journal["budgets"].get("refusal"), journal.get("refusal")), (None, None, None))
        self.assertEqual(self.ended(), self.ended_failed())

    def refused_write_stalls(self, supervisor, refusing: Refusing, write: str, first: str | None = None) -> None:
        """Each refused send spends the refusal budget (3); the next stalls
        the job with its incident; a restart then sends nothing more."""
        outcomes = ([first] if first else []) + [supervisor.advance(MAIN) for _ in range(4 - bool(first))]
        self.assertEqual(outcomes, [f"{write}_refused:transition_not_allowed"] * 3 + ["stalled"])
        self.assertEqual(refusing.refusals, 4)
        self.assertEqual(self.incident("lifecycle_write_refused")["write"], write)
        self.stalled_unchanged(refusing, lambda: refusing.refusals)

    def test_a_refused_result_is_budgeted_too(self) -> None:
        self.exited()
        refusing = Refusing(self.router, "result_ready", "transition_not_allowed")
        self.refused_write_stalls(self.make_supervisor(control=refusing), refusing, "result_ready")
        self.assertEqual(self.make_supervisor().recover()[MAIN], "committed")

    def test_a_refused_outcome_unknown_entry_is_budgeted_too(self) -> None:
        self.vanished()
        refusing = Refusing(self.router, "outcome_unknown", "transition_not_allowed")
        self.refused_write_stalls(self.make_supervisor(control=refusing), refusing, "unknown")
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "running")
        self.assertEqual(self.make_supervisor().recover()[MAIN], "failed")
        self.ended_reconciled()

    def test_a_refused_reconciliation_is_budgeted_too(self) -> None:
        self.vanished()
        refusing = Refusing(self.router, None, "transition_not_allowed", method="reconcile")
        self.refused_write_stalls(self.make_supervisor(control=refusing), refusing, "reconcile")
        self.unknown_held()
        self.assertEqual(self.make_supervisor().recover()[MAIN], "failed")
        self.ended_reconciled("confirmed_failed")  # the first attempt ended the group; each refusal lets the next decide afresh

    def test_a_refused_cancellation_of_unlaunched_work_is_budgeted_too(self) -> None:
        """Launch admission refuses (the lease is not current), so the
        supervisor cancels the admitted work itself; the router refuses that
        cancellation too."""
        self.prepare(self.KIND)
        refusing = Refusing(Refusing(self.router, "launching", "lease_not_current"), None, "transition_not_allowed", method="request_cancel")
        supervisor = self.make_supervisor(control=refusing)
        first = supervisor.submit(self.order(self.KIND))
        self.refused_write_stalls(supervisor, refusing, "cancel", first=first)
        self.assertEqual((self.spawns(), self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN)), (0, "admitted"))

    # -- an outcome_unknown episode that cannot be reconciled yet (task 1c-repair-2) ----------------------
    def vanished(self) -> dict:
        """The job's launcher is killed and reaped, its executor and
        descendant left: the next advance enters outcome_unknown and
        reconciles by terminating the group."""
        self.assertEqual(self.submit(HANG_WITH_DESCENDANT), "running")
        self.wait_for_file("scratch/descendant.pid")
        identity = self.job_file("identity.json")
        os.kill(identity["pid"], signal.SIGKILL)
        deadline = time.monotonic() + 5
        while alive(identity["pid"]) and time.monotonic() < deadline:
            self.reap()
            time.sleep(0.01)
        return identity

    def unknown_held(self) -> None:
        """The episode is entered and nothing reconciled it: its hold is open."""
        self.assertEqual({k: v for k, v in self.ended().items() if k in ("state", "episodes", "open_holds", "reconciliations")},
                         {"state": "outcome_unknown", "episodes": 1, "open_holds": 1, "reconciliations": []})

    def ended_reconciled(self, resolution: str = "terminated_group") -> None:
        self.assertEqual({k: v for k, v in self.ended().items() if k in ("state", "failure_class", "episodes", "open_holds", "cleared_holds", "reconciliations")},
                         {"state": "failed", "failure_class": "no_exit_record", "episodes": 1, "open_holds": 0, "cleared_holds": 1,
                          "reconciliations": [resolution]})

    def test_an_unresolved_unknown_episode_stalls_within_its_budget_and_keeps_its_hold(self) -> None:
        identity = self.vanished()
        unconfirmed = Unconfirmed()
        with unconfirmed.patched():
            outcomes = [self.supervisor.advance(MAIN) for _ in range(7)]
            self.assertEqual(outcomes, ["unknown_unresolved"] * 5 + ["stalled"] * 2)
            self.assertEqual(unconfirmed.calls, 6)  # the budget (5), then the one that stalled; nothing after
            found = self.incident("outcome_unknown_unresolved")
            self.assertEqual({k: found[k] for k in ("budget", "unknown_episode", "last_finding")},
                             {"budget": "unknown", "unknown_episode": 1, "last_finding": "the group's termination (reconciliation) is not confirmed"})
            self.unknown_held()
            self.stalled_unchanged(self.control, lambda: unconfirmed.calls)
        self.assertNotEqual(jobs.members(identity), [])  # the group was never ended meanwhile
        self.assertEqual(self.make_supervisor().recover()[MAIN], "failed")  # the group can be ended: recovery reconciles the episode
        self.ended_reconciled()
        self.assertEqual(jobs.members(identity), [])

    def test_an_unresolved_unknown_episode_is_also_bounded_in_time(self) -> None:
        self.vanished()
        unconfirmed = Unconfirmed()
        with unconfirmed.patched():
            self.assertEqual(self.supervisor.advance(MAIN), "unknown_unresolved")
            since = self.journal()["unresolved"]["since"]
            self.clock.set("2026-09-27T10:20:00Z")  # past the unknown window (600 s), one attempt into a budget of five
            self.assertEqual(self.supervisor.advance(MAIN), "stalled")
            self.assertEqual((unconfirmed.calls, self.incident("outcome_unknown_unresolved")["unresolved_since"]), (2, since))
            self.unknown_held()

    def test_an_unknown_episode_reconciled_within_its_budget_refunds_it(self) -> None:
        self.vanished()
        unconfirmed = Unconfirmed()
        with unconfirmed.patched():
            self.assertEqual([self.supervisor.advance(MAIN) for _ in range(2)], ["unknown_unresolved"] * 2)
        self.assertEqual(self.supervisor.advance(MAIN), "failed")  # the group ends now: the episode is reconciled
        journal = self.journal()
        self.assertEqual((journal.get("incident"), journal.get("unresolved"), journal["budgets"].get("unknown")), (None, None, None))
        self.ended_reconciled()


class ResearchPassBudgetTest(BudgetFaults, SupervisedTestCase):
    KIND = "research_pass"


class DiscoveryBudgetTest(BudgetFaults, SupervisedTestCase):
    KIND = "discovery"


class DelegateBudgetTest(BudgetFaults, SupervisedTestCase):
    KIND = "delegate"


class VerificationBudgetTest(BudgetFaults, SupervisedTestCase):
    KIND = "verification"


class CheckpointBudgetTest(BudgetFaults, SupervisedTestCase):
    KIND = "checkpoint"


if __name__ == "__main__":
    unittest.main()
