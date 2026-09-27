"""Shared fixtures for the supervisor suites (not collected as tests).

A SupervisedTestCase holds a durable store under a temporary directory, the
real protected spool, a router built on both (the fixture builders of
router_fixtures, pointed at the durable store), and a supervisor whose
launcher and fake executor are started as real child processes from the
code tree children.py names (so the mutation runner's child tree reaches
them). Read-backs are raw SQL on the test's own connection, never the
router's or the supervisor's readers.

Every invocation kind is set up the same way: `order(kind, steps)` makes a
work order whose fake executor follows `steps`; a delegate's parent is a
hanging research pass of the same supervisor, running before the delegate
is submitted. tearDown ends every process any job left behind and checks
none survives it.

Expected outcomes are written by hand in each test.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from gen2.core import canonical
from gen2.core.control import ControlUnavailable
from gen2.store import api
from gen2.supervisor import jobs
from gen2.supervisor.spool import Spool
from gen2.supervisor.supervisor import Policy, Supervisor, WorkOrder
from gen2.tests import children, store_fixtures
from gen2.tests import router_fixtures as rf

KINDS = ("research_pass", "discovery", "delegate", "verification", "checkpoint")
ARTIFACTS = "GEN2_TEST_ARTIFACTS"  # where a failed supervisor test's temporary tree is kept (default <tmp>/gen2-test-artifacts)
EVIDENCE = "GEN2_TEST_EVIDENCE"  # "off": keep nothing (the mutation runner, whose mutants fail tests on purpose)
JOB_RECORDS = ("order.json", "spawn.json", "identity.json", "exit.json", "abandoned", "journal.json", "launcher.log", "executor.log")
FAST = Policy(identity_grace_s=10.0, start_grace_s=1.0, term_grace_s=0.5, kill_grace_s=5.0, poll_s=0.01)
DEADLINE = "2026-09-27T12:00:00Z"   # the test's clock starts at 10:00 and moves only when told
AFTER_DEADLINE = "2026-09-27T12:00:01Z"
PARENT = "inv_parent0001"
MAIN = "inv_subject001"
# The tables a lifecycle writes. Any other table changing in a fault test is an unexpected write ("other_tables" in ended()).
LIFECYCLE_TABLES = frozenset({"invocations", "invocation_transitions", "invocation_reconciliations", "leases", "queue_entries", "artifacts", "artifact_topics",
                              "operation_receipts", "research_ordinals", "holds", "audit_events"})


def outcome_text(invocation_id: str, topic: str = rf.TOPIC) -> str:
    return canonical.canonical_bytes(rf.empty_outcome(invocation_id, topic=topic)).decode("utf-8")


def succeed(invocation_id: str = MAIN) -> list[dict]:
    return [{"op": "write", "name": "outcome.json", "text": outcome_text(invocation_id)}]


def launcher() -> tuple[str, ...]:
    return (sys.executable, str(children.path("gen2/supervisor/jobshim.py")))


class TestSupervisor(Supervisor):
    """A supervisor whose run() gives up after 20 s of wall time (not 60): a
    normal job ends in well under a second, and a mutant that leaves a job
    running should cost each test 20 s, not a minute."""

    def run(self, invocation_id: str, *, timeout_s: float = 20.0, **kwargs) -> str:
        return super().run(invocation_id, timeout_s=timeout_s, **kwargs)


class Unreachable:
    """A ControlBackend between the supervisor and the router that can be
    made unreachable (C-10): while down, every call raises
    ControlUnavailable and reaches nothing. `calls` counts attempts."""

    def __init__(self, router) -> None:
        self.router, self.down, self.calls, self.refused = router, False, 0, 0

    def __getattr__(self, name):
        target = getattr(self.router, name)

        def call(request):
            self.calls += 1
            if self.down:
                self.refused += 1
                raise ControlUnavailable(name)
            return target(request)
        return call


class SupervisedTestCase(rf.RouterTestCase):
    POLICY = FAST

    def run(self, result=None):
        """Run the test, noting whether it fails (an assertion, an error or a
        failing subtest), so tearDown can keep the evidence: an intermittent
        failure must carry its own diagnosis (task 1c-repair C2)."""
        self._failed: list[str] = []
        if result is None:
            return super().run(result)
        hooks = ("addFailure", "addError", "addSubTest")
        for name in hooks:
            def recording(*args, _original=getattr(result, name), _name=name):
                if _name != "addSubTest" or args[-1] is not None:  # addSubTest(test, subtest, None) is a passing subtest
                    self._failed.append(_name)
                return _original(*args)
            setattr(result, name, recording)
        try:
            return super().run(result)
        finally:
            for name in hooks:
                result.__dict__.pop(name, None)

    def keep_evidence(self) -> None:
        """Print what this test's jobs left — each job's records and logs, the
        exit status of every launcher its supervisors started, every child
        supervisor's output — and keep its whole temporary tree."""
        base = Path(os.environ.get(ARTIFACTS) or Path(tempfile.gettempdir()) / "gen2-test-artifacts")
        dest = base / f"{self.id()}-{os.getpid()}-{time.time_ns()}"
        special = lambda folder, names: [n for n in names if not (os.path.islink(os.path.join(folder, n)) or os.path.isdir(os.path.join(folder, n))
                                                                  or os.path.isfile(os.path.join(folder, n)))]  # a FIFO would block the copy
        shutil.copytree(self.root, dest, symlinks=True, ignore=special)
        lines = [f"=== evidence of the failure of {self.id()}, kept at {dest}"]
        for supervisor in getattr(self, "_supervisors", []):
            lines += [f"launcher {handle}: pid {popen.pid}, exit status {popen.poll()}" for handle, popen in supervisor._children.items()]
        lines += [f"child {run}" for run in getattr(self, "child_runs", [])]
        for job in sorted((self.root / "jobs").glob("*")):
            for name in JOB_RECORDS:
                if (job / name).is_file():
                    lines.append(f"{job.name}/{name}: {(job / name).read_text(errors='replace')[-4000:]}")
        print("\n".join(lines), file=sys.stderr)

    def setUp(self) -> None:  # not the in-memory setUp: a durable store, the real spool
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = api.open_store(self.root / "store.sqlite3", create=True)
        self.db = sqlite3.connect(self.root / "store.sqlite3", isolation_level=None)
        self.db.executescript(store_fixtures.CONNECTION_TEXT)
        self.spool = Spool(self.root / "spool")
        self.clock, self.ids, self.faults = rf.Clock(), rf.Ids(), {}
        self.router = self.make_router()
        self.control = Unreachable(self.router)
        for tid in (rf.TOPIC, rf.OTHER):
            self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)",
                   tid, "2026-09-27T09:00:00Z", "2026-09-27T09:00:00Z")
        self.to_queued()
        self._baseline = self.state(exclude=())  # the world before any job: ended() reports every other table that changed since
        self._supervisors: list[Supervisor] = []  # every supervisor a test made, so tearDown reaps every launcher it started
        self.child_runs: list[tuple] = []  # (what, exit status, stdout, stderr) of every child supervisor the test ran
        self.supervisor = self.make_supervisor()

    def tearDown(self) -> None:
        if getattr(self, "_failed", None) and os.environ.get(EVIDENCE) != "off":
            self.keep_evidence()
        survivors = self.end_every_process()
        self.store.close()
        self.db.close()
        self._tmp.cleanup()
        self.assertEqual(survivors, [], "a job's process outlived its test")

    def make_supervisor(self, **overrides) -> Supervisor:
        kwargs = dict(station_id="station-1", host_id="host-test", policy=self.POLICY, clock=self.clock, launcher=launcher())
        kwargs.update(overrides)
        supervisor = TestSupervisor(kwargs.pop("control", self.control), self.spool, self.root / "jobs", **kwargs)
        self._supervisors.append(supervisor)
        return supervisor

    def end_every_process(self) -> list[int]:
        """SIGKILL every member of every job's group, and every marked
        descendant; returns any pid still alive after that."""
        left, own = [], os.getsid(0)
        for identity_file in (self.root / "jobs").glob("*/identity.json"):
            identity = json.loads(identity_file.read_text())
            if identity["session"] == own:  # never this process's own session (a launcher started without one would name it)
                continue
            for pid in jobs.members(identity):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 5
        for identity_file in (self.root / "jobs").glob("*/identity.json"):
            identity = json.loads(identity_file.read_text())
            if identity["session"] == own:
                continue
            while jobs.members(identity) and time.monotonic() < deadline:
                self.reap()
                time.sleep(0.01)
            left += jobs.members(identity)
        self.reap()
        return left

    def reap(self) -> None:
        for supervisor in self._supervisors:
            for popen in supervisor._children.values():
                popen.poll()

    # -- orders ------------------------------------------------------------------
    def order(self, kind: str, steps: list[dict] | None = None, *, inv: str = MAIN, deadline: str = DEADLINE, lease_expires: str | None = None,
              topic: str = rf.TOPIC) -> WorkOrder:
        script = self.root / "scripts" / f"{inv}.json"
        script.parent.mkdir(exist_ok=True)
        script.write_text(json.dumps({"steps": succeed(inv) if steps is None else steps}))
        return WorkOrder(invocation_id=inv, kind=kind, topic_id=topic, config_bundle_hash=rf.CONFIG, deadline_at=deadline,
                         lease_expires_at=None if kind == "delegate" else (lease_expires or deadline),
                         parent_invocation_id=PARENT if kind == "delegate" else None,
                         command=(sys.executable, str(children.path("gen2/supervisor/fake_executor.py")), str(script)))

    def start_parent(self, lease_expires: str | None = None) -> None:
        """A delegate's parent: a hanging research pass of this supervisor, running."""
        out = self.supervisor.submit(self.order("research_pass", [{"op": "hang"}], inv=PARENT, deadline=rf.DEADLINE, lease_expires=lease_expires))
        self.assertEqual(out, "running")

    def prepare(self, kind: str, lease_expires: str | None = None) -> None:
        if kind == "delegate":
            self.start_parent(lease_expires)

    def gate(self, inv: str = MAIN) -> None:
        """Open the gate a `wait_for` step of the job's executor waits on."""
        (self.root / "jobs" / f"job-{inv}" / "scratch" / "gate").write_text("open")

    def journal(self, inv: str = MAIN) -> dict:
        return json.loads((self.root / "jobs" / f"job-{inv}" / "journal.json").read_text())

    def job_file(self, name: str, inv: str = MAIN) -> dict | None:
        path = self.root / "jobs" / f"job-{inv}" / name
        return json.loads(path.read_text()) if path.exists() else None

    def wait_for_file(self, name: str, inv: str = MAIN, seconds: float = 10.0) -> None:
        deadline = time.monotonic() + seconds
        while not (self.root / "jobs" / f"job-{inv}" / name).exists():
            if time.monotonic() >= deadline:
                self.fail(f"{name} never appeared for {inv}")
            time.sleep(0.005)

    # -- read-back ---------------------------------------------------------------
    def ended(self, inv: str = MAIN) -> dict:
        """The invocation's end as the store holds it (raw SQL)."""
        row = self.rows("SELECT state, failure_class, end_evidence_ref, descendants_confirmed_at IS NOT NULL, unknown_episode, lease_id, kind "
                        "FROM invocations WHERE invocation_id = ?", inv)[0]
        lease_id = row[5] or self.value("SELECT lease_id FROM invocations WHERE invocation_id = ?", PARENT)
        return {"state": row[0], "failure_class": row[1], "evidence": row[2] is not None, "descendants_confirmed": bool(row[3]), "episodes": row[4],
                "transitions": [r[0] for r in self.rows("SELECT to_state FROM invocation_transitions WHERE invocation_id = ? ORDER BY seq", inv)],
                "receipts": self.value("SELECT count(*) FROM operation_receipts WHERE invocation_id = ?", inv),
                "lease_release": self.rows("SELECT release_reason FROM leases WHERE lease_id = ?", lease_id)[0][0],
                "open_holds": self.value("SELECT count(*) FROM holds WHERE subject_ref LIKE ? AND cleared_at IS NULL", f"invocation:{inv}#%"),
                "cleared_holds": self.value("SELECT count(*) FROM holds WHERE subject_ref LIKE ? AND cleared_at IS NOT NULL", f"invocation:{inv}#%"),
                "reconciliations": [r[0] for r in self.rows("SELECT resolution FROM invocation_reconciliations WHERE invocation_id = ? ORDER BY unknown_episode", inv)],
                "other_tables": sorted(name for name, rows in self.state(exclude=()).items() if name not in LIFECYCLE_TABLES and rows != self._baseline.get(name))}

    def evidence_record(self, inv: str = MAIN) -> dict:
        digest = self.value("SELECT end_evidence_ref FROM invocations WHERE invocation_id = ?", inv)
        return json.loads(self.spool.read(digest, topic_id=rf.TOPIC))

    def spawns(self, inv: str = MAIN) -> int:
        spawn = self.job_file("spawn.json", inv)
        return 0 if spawn is None else spawn["attempts"]


def released(kind: str, reason: str) -> str | None:
    """The main invocation's lease release: a delegate releases nothing (its
    lease is its parent's, still running)."""
    return None if kind == "delegate" else reason
