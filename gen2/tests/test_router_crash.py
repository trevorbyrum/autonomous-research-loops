"""RG-1a: a crash at each commit_outcome boundary, for every invocation kind
that finalizes, recovers to exactly one committed result (task 1b).

Trace: INVARIANTS RG-1a ("recovery leaves exactly one committed result for
the invocation, at most one research ordinal, exactly one lease release, and
at most one instance of each review-trigger identity ... counts read back
from the store — not the router's return value — after each injected crash,
for every invocation kind that finalizes"), RG-1b(a), C-4, C-5; design review
§5 ("Crash fencing"), §10 gate 1.

Boundaries: before validation, after validation but before the transaction,
inside the transaction (at its start, after fencing, after the receipt row,
after the evidence rows, at its end — each before COMMIT), after commit
before the reply, and after the reply. Recovery is what a station does after
losing a reply: resubmit the same envelope.

Two kinds of crash:
  * CrashMatrixTest raises an exception at the boundary, in memory: the
    transaction's own rollback path runs;
  * KilledProcessTest ends a child process with os._exit inside the
    transaction on a durable store, so no rollback code runs at all and
    atomicity rests on SQLite's journal alone; a fresh process then reads
    the store back and resubmits.

What these cannot show: a crash inside SQLite's own commit (the fault points
are the router's), power loss (the kill leaves the OS page cache intact), or
a spool that lost the staged bytes (1c).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from gen2.tests.router_crash_child import tables
from gen2.tests.router_fixtures import RouterTestCase, empty_outcome

ROOT = Path(__file__).resolve().parents[2]
BOUNDARIES = ("before_validation", "after_validation", "in_transaction:start", "in_transaction:fenced", "in_transaction:receipt",
              "in_transaction:evidence", "in_transaction:end", "after_commit", "after_reply")
TRIGGER = {"reason_code": "persistent_contradiction", "cause_ref": "c", "source_revision": 1, "observed_at": "2026-09-27T10:00:00Z"}


class Crash(Exception):
    pass


class CrashMatrixTest(RouterTestCase):
    # kind -> (admission, expected ordinals for the invocation, carries a trigger)
    KINDS = {
        "research_pass": ("contract", 1, True),
        "research_pass/pre-contract": ("pre-contract", 0, True),
        "discovery": ("contract", 0, False),
        "verification": ("contract", 0, False),
        "checkpoint": ("contract", 0, True),
        "delegate": ("contract", 0, False),
    }

    def world(self, name: str) -> dict:
        admission, _, _ = self.KINDS[name]
        if admission == "pre-contract":
            self.to_scoping()
            return self.started("inv_invocation1", "research_pass")
        self.to_queued()
        if name == "delegate":
            parent = self.started("inv_parent0001")
            return self.started("inv_invocation1", "delegate", parent=parent)
        return self.started("inv_invocation1", name)

    def test_every_boundary_for_every_finalizing_kind(self) -> None:
        for name, (_, ordinals, trigger) in self.KINDS.items():
            for boundary in BOUNDARIES:
                with self.subTest(kind=name, boundary=boundary):
                    self.tearDown()
                    self.setUp()
                    grant = self.world(name)
                    outcome = empty_outcome("inv_invocation1")
                    if trigger:
                        outcome["review_triggers"] = [TRIGGER]
                    env = self.envelope(grant, "op_final000001", outcome)
                    self.ready(grant, env["payload_digest"])
                    env["expected_state_revision"] = self.state_revision()
                    if boundary == "after_reply":
                        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
                    else:
                        self.faults[boundary] = Crash(boundary)
                        with self.assertRaises(Crash):
                            self.router.commit_outcome(env)
                    first = self.router.commit_outcome(env)  # recovery: the same envelope again
                    self.assertIn(first["status"], ("committed", "replayed"))
                    again = self.router.commit_outcome(env)
                    self.assertEqual(again["status"], "replayed")
                    self.assertEqual(again["receipt"], first["receipt"])
                    self.assertCounts(grant, ordinals, trigger)

    def assertCounts(self, grant: dict, ordinals: int, trigger: bool) -> None:
        inv = grant["invocation_id"]
        self.assertEqual(self.value("SELECT count(*) FROM operation_receipts WHERE invocation_id = ? AND operation_kind = 'final_outcome'", inv), 1)
        self.assertEqual(self.value("SELECT count(*) FROM operation_receipts WHERE invocation_id = ?", inv), 1)
        self.assertEqual(self.value("SELECT count(*) FROM research_ordinals WHERE invocation_id = ?", inv), ordinals)
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", inv), "committed")
        lease = grant["lease"]["lease_id"]
        if grant["kind"] == "delegate":  # a delegate releases nothing: its lease is its parent's, still live
            self.assertEqual(self.rows("SELECT released_at FROM leases WHERE lease_id = ?", lease), [(None,)])
        else:
            self.assertEqual(self.rows("SELECT count(*), release_reason FROM leases WHERE lease_id = ? AND released_at IS NOT NULL", lease), [(1, "final_outcome")])
        self.assertEqual(self.value("SELECT count(*) FROM review_triggers"), 1 if trigger else 0)
        self.assertEqual(self.value("SELECT count(*) FROM invocation_transitions WHERE invocation_id = ? AND to_state = 'committed'", inv), 1)


class KilledProcessTest(RouterTestCase):
    def child(self, directory: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "gen2.tests.router_crash_child", str(directory), *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)

    def test_a_process_killed_inside_the_transaction_leaves_nothing(self) -> None:
        for point in ("in_transaction:receipt", "in_transaction:evidence", "in_transaction:end"):
            with self.subTest(point), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                prepared = self.child(directory, "prepare")
                self.assertEqual(prepared.returncode, 0, prepared.stderr)
                before = json.loads((directory / "before.json").read_text())
                killed = self.child(directory, "crash", point)
                self.assertEqual(killed.returncode, 137, killed.stderr)  # os._exit at the point: nothing after it ran
                self.assertEqual(json.loads(json.dumps(tables(directory / "store.sqlite3"))), before)
                resubmitted = self.child(directory, "resubmit")
                self.assertEqual(resubmitted.returncode, 0, resubmitted.stderr)
                self.assertEqual(json.loads(resubmitted.stdout)["status"], "committed")
                after = tables(directory / "store.sqlite3")
                self.assertEqual(len(after["operation_receipts"]), 1)
                self.assertEqual(len(after["research_ordinals"]), 1)
                self.assertEqual(len(after["claims"]), 1)
                self.assertEqual(len(after["review_triggers"]), 1)
                replayed = self.child(directory, "resubmit")
                self.assertEqual(json.loads(replayed.stdout)["status"], "replayed")

    def test_a_process_killed_after_commit_has_committed_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertEqual(self.child(directory, "prepare").returncode, 0)
            self.assertEqual(self.child(directory, "crash", "after_commit").returncode, 137)
            committed = tables(directory / "store.sqlite3")
            self.assertEqual(len(committed["operation_receipts"]), 1)
            recovered = json.loads(self.child(directory, "resubmit").stdout)
            self.assertEqual(recovered["status"], "replayed")
            self.assertEqual(tables(directory / "store.sqlite3"), committed)
