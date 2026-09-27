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

Oracles: expected outcomes written by hand; the store read back by raw SQL
(unchanged while the supervisor cannot deliver); the journal and spool read
from disk; process death read from /proc.
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
        found = self.journal()["incident"]
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
        with mock.patch.object(spool_module, "_write_once", full_for_records):
            outcomes = [self.supervisor.advance(MAIN) for _ in range(4)]
        self.assertEqual(outcomes, ["write_failed"] * 3 + ["stalled"])
        self.assertIn("No space left on device", self.incident("durable_write_failed")["error"])
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
