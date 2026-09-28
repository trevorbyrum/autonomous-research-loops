"""One caller at a time per job: the supervisor's per-job lock (task
1c-repair-4; Astra 1c re-review 3, BLOCK 1; INVARIANTS L-6, RG-3, L-8).

Trace: L-6 (every retry path consumes a declared budget, which nothing
refills), RG-3 (an exhausted budget ends in an owned, deadlined incident).
Astra's reproduction: an advance that read its job's journal before another
advance exhausted the router budget and opened an incident later saved its
older copy over both — the incident erased, the router budget back at one,
twelve failing calls where six are allowed, the deadline moved — for each
parent kind, on one supervisor shared by two threads and on two supervisors
sharing the jobs directory.

What is checked, for each kind that may have delegates:
- Overlapping advances (Astra's regression, with the expectation it
  asserted): advance A of a job whose router is down is paused holding the
  job — in the chokepoint's read of its journal (Astra's schedule), or just
  after its own snapshot read — while six advances of B are started, on the
  same supervisor in another thread or on another supervisor over the same
  jobs directory. While A is paused, B sends and writes nothing. Then six
  failing calls in all (the first attempt and five retry allowances), the
  router budget at five, one router_unreachable incident; half an hour
  later five more advances send nothing and leave the journal (the
  incident's deadline included) and the store as they were.
- Overlapping recover() calls on the stalled job: two resumptions are two
  recovery attempts, each making its one call; neither is lost.
- Waiting for the lock is bounded and spends nothing: past lock_wait_s
  advance() and recover() answer busy, the journal unchanged byte for byte
  and nothing sent.
- The backstop: a caller that does not take the lock (as another host may
  not see it) still cannot save its older copy over the incident: that
  write is refused (StaleJournal, out of band). Its one extra call is still
  made — the lock prevents that, not the check.
- Parent and delegate, in both orders: the parent's executor fails while its
  delegate, never advanced yet, needs the parent's capability for its claim.
  The parent's advance holds its lock, about to end its delegates, while the
  delegate's advance waits; or the delegate's advance holds the parent's
  journal inside its grant while the parent's advance waits. Each completes
  (no deadlock: every caller takes the parent's lock before the
  delegate's), the delegate cancelled and nothing of it alive, the parent
  failed.
Once: a write resting on an older copy of the journal is refused, tested
directly; and a supervisor process killed while it holds a job's lock
(inside an advance) leaves it free — while the holder lives, another
advance and recover() answer busy and spend nothing; once it is dead the
next advance proceeds and the job commits.

Oracles: a waiting caller is seen waiting inside the lock's acquisition
(its thread's stack) having attempted no call; calls counted at the
ControlBackend; the journal read from disk; the store read back whole by
raw SQL; outcomes and ends written by hand. A pause delays a read's return
in this interpreter; it never changes a value. The router is this test's,
on this thread's store connection: a call a caller thread makes while the
router is reachable is made for it by the test's thread (Relay), which
serves them only while it waits for the callers to finish.

What this cannot show: callers on different hosts sharing a jobs directory
(nothing is claimed across hosts, jobs.py; the backstop above is all that is
relied on then). The lock makes every read-modify-write of a job's journal
one caller's, so the sequential claims carry over to overlapping callers on
one host; these are the schedules that show the exclusion, not every one.
"""
from __future__ import annotations

import contextlib
import queue
import subprocess
import sys
import threading
import time
import unittest
from dataclasses import replace
from unittest import mock

from gen2.supervisor import jobs
from gen2.supervisor.supervisor import ControlFailure, StaleJournal, Supervisor
from gen2.tests import children
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import FAST, MAIN, PARENT, SupervisedTestCase, Unreachable, succeed

HANG = [{"op": "hang"}]
FAILS_AT_THE_GATE = [{"op": "wait_for", "name": "gate", "seconds": 60}, {"op": "exit", "code": 3}]
PAUSE_S = 10.0    # a paused caller gives up after this, raising (a mutant that never lets it go costs this)
WATCH_S = 0.3     # how long a waiting caller is watched to show that it waits
JOIN_S = 60.0     # every caller of a test ends well within this; one still running is a deadlock
IMPATIENT = replace(FAST, lock_wait_s=0.3)
LATER = "2026-09-27T10:30:00Z"


class Pause:
    """Stops the first caller in the thread named `thread` that reaches
    here() until release(); `reached` is set when it stops."""

    def __init__(self, thread: str) -> None:
        self.thread, self.reached, self.resume, self.used = thread, threading.Event(), threading.Event(), False

    def here(self) -> None:
        if threading.current_thread().name == self.thread and not self.used:
            self.used = True
            self.reached.set()
            if not self.resume.wait(PAUSE_S):
                raise RuntimeError("the paused caller was never released")


def after_snapshot(pause: Pause, inv: str):
    """Pause just after the caller's first read of the job's journal: the
    snapshot an advance() or a recover() rests its writes on."""
    real = Supervisor._journal

    def journal(self, job):
        value = real(self, job)
        if job.handle == "job-" + inv:
            pause.here()
        return value
    return mock.patch.object(Supervisor, "_journal", journal)


def in_the_chokepoint(pause: Pause, inv: str):
    """Astra's schedule: pause in the chokepoint's read of the journal of
    the job called for, after the caller's snapshot, before its call."""
    real = jobs.Job.read

    def read(job, name):
        value = real(job, name)
        if name == "journal.json" and job.handle == "job-" + inv and sys._getframe(1).f_code.co_name == "_call":
            pause.here()
        return value
    return mock.patch.object(jobs.Job, "read", read)


class Relay(Unreachable):
    """The test's router, reached from caller threads: its store connection
    belongs to the thread that made it, so a call from another thread, while
    the router is reachable, is queued for that thread to make (serve()) and
    its caller waits for the answer. While the router is down a call fails
    where it is made, reaching nothing. `pending`: calls queued, not yet
    served."""

    def __init__(self, router) -> None:
        super().__init__(router)
        self.owner, self.queue = threading.current_thread(), queue.Queue()

    @property
    def pending(self) -> int:
        return self.queue.qsize()

    def __getattr__(self, name):
        call = super().__getattr__(name)

        def relayed(request):
            if self.down or threading.current_thread() is self.owner:
                return call(request)
            answer = {"done": threading.Event()}
            self.queue.put((call, request, answer))
            if not answer["done"].wait(JOIN_S):
                raise RuntimeError(f"{name} was never served")
            if "raised" in answer:
                raise answer["raised"]
            return answer["value"]
        return relayed

    def serve(self, until, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not until() and time.monotonic() < deadline:
            try:
                call, request, answer = self.queue.get(timeout=0.01)
            except queue.Empty:
                continue
            try:
                answer["value"] = call(request)
            except BaseException as exc:  # noqa: BLE001 — handed back to its caller
                answer["raised"] = exc
            finally:
                answer["done"].set()


class Caller:
    """work() in a thread of its own, named `name`: its result, or what it raised."""

    def __init__(self, name: str, work) -> None:
        self.result, self.raised = None, None
        self.thread = threading.Thread(target=self._run, args=(work,), name=name, daemon=True)
        self.thread.start()

    def _run(self, work) -> None:
        try:
            self.result = work()
        except BaseException as exc:  # noqa: BLE001 — kept for the test to assert on
            self.raised = exc


class Serialized:
    KIND: str  # a kind that may have delegates (L-8)

    def setUp(self) -> None:
        super().setUp()
        self.control = Relay(self.router)
        self.supervisor = self.make_supervisor()
        self._callers: list[Caller] = []
        self._pauses: list[Pause] = []

    def tearDown(self) -> None:
        """Every caller released and finished (its calls served) before the
        store and the jobs directory go: a failed test leaves none behind."""
        for pause in self._pauses:
            pause.resume.set()
        self.control.serve(lambda: not any(c.thread.is_alive() for c in self._callers), PAUSE_S + JOIN_S)
        super().tearDown()

    def pause(self, thread: str) -> Pause:
        self._pauses.append(Pause(thread))
        return self._pauses[-1]

    def caller(self, name: str, work) -> Caller:
        self._callers.append(Caller(name, work))
        return self._callers[-1]

    def reached(self, pause: Pause) -> None:
        self.control.serve(pause.reached.is_set, PAUSE_S)  # the paused caller's calls before it stops are made meanwhile
        self.assertTrue(pause.reached.is_set())

    def joined(self, *callers: Caller) -> None:
        self.control.serve(lambda: not any(c.thread.is_alive() for c in callers), JOIN_S)
        self.assertEqual([c.thread.name for c in callers if c.thread.is_alive()], [])  # none deadlocked

    def waiting(self, caller: Caller) -> None:
        """The caller is waiting inside a job lock's acquisition, and has
        attempted no router call."""
        time.sleep(WATCH_S)
        self.assertTrue(caller.thread.is_alive(), f"{caller.thread.name} did not wait for the lock: {caller.result!r} {caller.raised!r}")
        frame, stack = sys._current_frames().get(caller.thread.ident), []
        while frame is not None:
            stack.append((frame.f_globals.get("__name__"), frame.f_code.co_name))
            frame = frame.f_back
        self.assertIn((jobs.__name__, "hold"), stack, f"{caller.thread.name} is not waiting for a lock: {stack}")
        self.assertEqual(self.control.pending, 0)

    def down(self) -> None:
        self.control.down = True
        self.supervisor.prepare(self.order(self.KIND, HANG, inv=PARENT))

    def stalled(self) -> dict:
        """The job stalled by the router's outage: six calls, then its incident."""
        self.down()
        self.assertEqual([self.supervisor.advance(PARENT) for _ in range(6)], ["router_unavailable"] * 5 + ["stalled"])
        self.assertEqual((self.control.calls, self.journal(PARENT)["incident"]["kind"]), (6, "router_unreachable"))
        return self.journal(PARENT)

    # -- overlapping advances (Astra 1c re-review 3, BLOCK 1) ----------------------------------------
    def overlap(self, point, *, supervisors: int) -> None:
        self.down()
        a = self.make_supervisor()
        b = a if supervisors == 1 else self.make_supervisor()
        before, pause = self.state(exclude=()), self.pause("held")
        with point(pause, PARENT):
            held = self.caller("held", lambda: a.advance(PARENT))
            self.reached(pause)
            other = self.caller("other", lambda: [b.advance(PARENT) for _ in range(6)])
            self.waiting(other)
            self.assertEqual((self.control.calls, self.job_file("journal.json", PARENT)), (0, None))  # it sent and wrote nothing meanwhile
            pause.resume.set()
            self.joined(held, other)
        self.assertEqual((held.raised, other.raised), (None, None))
        self.assertEqual((held.result, other.result), ("router_unavailable", ["router_unavailable"] * 4 + ["stalled"] * 2))
        journal = self.journal(PARENT)
        self.assertEqual((self.control.calls, journal["budgets"]["router"], journal["incident"]["kind"]), (6, 5, "router_unreachable"))
        self.clock.set(LATER)
        self.assertEqual([b.advance(PARENT) for _ in range(5)], ["stalled"] * 5)
        self.assertEqual((self.control.calls, self.journal(PARENT)), (6, journal))  # the incident, its deadline and the budgets as raised
        self.assertEqual(self.state(exclude=()), before)  # nothing reached the store

    def test_overlapping_advances_on_one_supervisor_paused_in_the_chokepoint(self) -> None:
        """Astra's regression, one supervisor shared by two threads: the
        advance holding its snapshot in the chokepoint keeps the other six
        out until it is done; six calls, the incident kept."""
        self.overlap(in_the_chokepoint, supervisors=1)

    def test_overlapping_advances_on_two_supervisors_paused_in_the_chokepoint(self) -> None:
        """Astra's regression, two supervisors sharing the jobs directory."""
        self.overlap(in_the_chokepoint, supervisors=2)

    def test_overlapping_advances_on_one_supervisor_paused_after_the_snapshot(self) -> None:
        """The same, the advance paused just after it read its snapshot: the
        read is under the lock, so the others wait from there."""
        self.overlap(after_snapshot, supervisors=1)

    def test_overlapping_advances_on_two_supervisors_paused_after_the_snapshot(self) -> None:
        self.overlap(after_snapshot, supervisors=2)

    def test_overlapping_recoveries_are_two_recovery_attempts(self) -> None:
        """Two supervisors' recover() of the stalled job, the first paused
        after reading its snapshot: the second waits, then each resumption
        spends its own recovery attempt and makes its one call, and each
        stalls again at once (the router budget stays spent)."""
        self.stalled()
        a, b, pause = self.make_supervisor(), self.make_supervisor(), self.pause("held")
        with after_snapshot(pause, PARENT):
            held = self.caller("held", a.recover)
            self.reached(pause)
            before = self.journal(PARENT)
            other = self.caller("other", b.recover)
            self.waiting(other)
            self.assertEqual((self.control.calls, self.journal(PARENT)), (6, before))
            pause.resume.set()
            self.joined(held, other)
        self.assertEqual((held.raised, other.raised, held.result, other.result), (None, None, {PARENT: "stalled"}, {PARENT: "stalled"}))
        journal = self.journal(PARENT)
        self.assertEqual((self.control.calls, journal["budgets"]["recovery"], journal["budgets"]["router"], journal["incident"]["kind"]),
                         (8, 2, 5, "router_unreachable"))

    def test_waiting_for_the_lock_is_bounded_and_spends_nothing(self) -> None:
        """While an advance holds the stalled job, an advance and a recover()
        waiting at most lock_wait_s answer busy: nothing sent, no recovery
        attempt spent, the journal unchanged byte for byte."""
        self.stalled()
        journal = (self.root / "jobs" / f"job-{PARENT}" / "journal.json").read_bytes()
        pause = self.pause("held")
        with after_snapshot(pause, PARENT):
            held = self.caller("held", lambda: self.make_supervisor().advance(PARENT))
            self.reached(pause)
            impatient = self.make_supervisor(policy=IMPATIENT)
            started = time.monotonic()
            self.assertEqual(impatient.advance(PARENT), "busy")
            self.assertEqual(impatient.recover(), {PARENT: "busy"})
            self.assertGreaterEqual(time.monotonic() - started, 2 * IMPATIENT.lock_wait_s)
            self.assertEqual(((self.root / "jobs" / f"job-{PARENT}" / "journal.json").read_bytes(), self.control.calls), (journal, 6))
            pause.resume.set()
            self.joined(held)
        self.assertEqual((held.raised, held.result), (None, "stalled"))
        self.assertIsNone(self.journal(PARENT)["budgets"].get("recovery"))

    def test_a_caller_not_taking_the_lock_cannot_save_over_the_incident(self) -> None:
        """The backstop, with the lock not taken (as a caller on another host
        may not see it): Astra's schedule runs as she ran it — six
        advances stall the job while the first waits in the chokepoint with
        its older copy, and half an hour passes. That caller's one call is
        made (the lock is what prevents it), but its write resting on the
        older copy is refused, raised out of band as StaleJournal; the
        incident, its deadline and the router budget stay as they were."""
        self.down()
        a, b, pause = self.make_supervisor(), self.make_supervisor(), self.pause("held")
        with mock.patch.object(jobs.Job, "hold", lambda job, deadline, poll_s: contextlib.nullcontext()), in_the_chokepoint(pause, PARENT):
            held = self.caller("held", lambda: a.advance(PARENT))
            self.reached(pause)
            self.assertEqual([b.advance(PARENT) for _ in range(6)], ["router_unavailable"] * 5 + ["stalled"])
            stalled = self.journal(PARENT)
            self.clock.set(LATER)
            pause.resume.set()
            self.joined(held)
        self.assertIsInstance(held.raised, StaleJournal)
        self.assertIsInstance(held.raised, ControlFailure)
        self.assertEqual((self.control.calls, self.journal(PARENT)), (7, stalled))
        self.assertEqual([b.advance(PARENT) for _ in range(5)], ["stalled"] * 5)
        self.assertEqual((self.control.calls, self.journal(PARENT)), (7, stalled))

    # -- a parent and its delegate: one lock order, parent before delegate (L-8) ---------------------
    def failing_parent_with_an_unclaimed_delegate(self) -> None:
        self.assertEqual(self.supervisor.submit(self.order(self.KIND, FAILS_AT_THE_GATE, inv=PARENT, deadline=rf.DEADLINE)), "running")
        self.supervisor.prepare(self.order("delegate", HANG))
        self.gate(PARENT)
        self.wait_for_file("exit.json", PARENT)

    def test_a_parent_ending_first_holds_its_delegate_off_then_cancels_it(self) -> None:
        """The parent's advance holds its lock, about to end its delegates;
        the delegate's advance, which needs the parent's journal for its
        claim, waits and writes nothing. Released: the parent claims the
        delegate and cancels it before any start, then fails; the waiting
        advance finds the delegate cancelled."""
        self.failing_parent_with_an_unclaimed_delegate()
        pause, settle = self.pause("parent"), Supervisor._settle_delegates

        def settling(supervisor, order):
            if order["invocation_id"] == PARENT:
                pause.here()
            return settle(supervisor, order)
        with mock.patch.object(Supervisor, "_settle_delegates", settling):
            parent = self.caller("parent", lambda: self.supervisor.advance(PARENT))
            self.reached(pause)
            calls = self.control.calls
            delegate = self.caller("delegate", lambda: self.make_supervisor().advance(MAIN))
            self.waiting(delegate)
            self.assertEqual((self.control.calls, self.job_file("journal.json")), (calls, None))
            pause.resume.set()
            self.joined(parent, delegate)
        self.assertEqual((parent.raised, delegate.raised, parent.result, delegate.result), (None, None, "failed", "cancelled"))
        self.assertEqual((self.ended(PARENT)["state"], self.ended(PARENT)["failure_class"]), ("failed", "exit_nonzero"))
        self.assertEqual((self.ended()["state"], self.ended()["transitions"]), ("cancelled", ["admitted", "cancelled"]))
        self.assertEqual((self.spawns(), self.job_file("identity.json")), (0, None))

    def test_a_delegate_claiming_first_holds_its_parent_off_then_is_ended_by_it(self) -> None:
        """The delegate's advance holds its parent's journal inside its grant
        (the parent's lock first, then its own); the parent's advance waits
        and changes nothing. Released: the delegate is claimed and started;
        then the parent ends it — cancelled, its group ended — and fails."""
        self.failing_parent_with_an_unclaimed_delegate()
        pause, grant = self.pause("delegate"), Supervisor._grant

        def granting(supervisor, job, order, journal):
            if job.handle == "job-" + PARENT:
                pause.here()
            return grant(supervisor, job, order, journal)
        with mock.patch.object(Supervisor, "_grant", granting):
            delegate = self.caller("delegate", lambda: self.make_supervisor().advance(MAIN))
            self.reached(pause)
            calls, journal = self.control.calls, self.journal(PARENT)
            parent = self.caller("parent", lambda: self.supervisor.advance(PARENT))
            self.waiting(parent)
            self.assertEqual((self.control.calls, self.journal(PARENT)), (calls, journal))
            pause.resume.set()
            self.joined(parent, delegate)
        self.assertEqual((parent.raised, delegate.raised, delegate.result, parent.result), (None, None, "running", "failed"))
        self.assertEqual((self.ended(PARENT)["state"], self.ended(PARENT)["failure_class"]), ("failed", "exit_nonzero"))
        self.assertEqual((self.ended()["state"], self.ended()["transitions"]), ("cancelled", ["admitted", "launching", "running", "cancelled"]))
        self.assertEqual((self.spawns(), jobs.members(self.job_file("identity.json"))), (1, []))


class ResearchPassSerializedTest(Serialized, SupervisedTestCase):
    KIND = "research_pass"


class DiscoverySerializedTest(Serialized, SupervisedTestCase):
    KIND = "discovery"


class VerificationSerializedTest(Serialized, SupervisedTestCase):
    KIND = "verification"


class CheckpointSerializedTest(Serialized, SupervisedTestCase):
    KIND = "checkpoint"


class BackstopAndCrashTest(SupervisedTestCase):
    def test_a_write_resting_on_an_older_copy_of_the_journal_is_refused(self) -> None:
        """Two copies of one journal: the one saved first moves it on; the
        other, now older, is refused and nothing is written."""
        self.control.down = True
        self.supervisor.prepare(self.order("research_pass", HANG))
        self.assertEqual(self.supervisor.advance(MAIN), "router_unavailable")
        job = self.supervisor.job(MAIN)
        older, current = self.supervisor._journal(job), self.supervisor._journal(job)
        current["budgets"]["router"] = 2
        self.supervisor._save(job, current)
        saved = self.journal()
        self.assertEqual(saved["budgets"]["router"], 2)
        older["budgets"]["router"] = 0
        with self.assertRaises(StaleJournal):
            self.supervisor._save(job, older)
        self.assertEqual(self.journal(), saved)

    def test_reaping_while_another_advance_starts_a_launcher(self) -> None:
        """One supervisor shared by threads advancing different jobs: one
        advance reaps the launchers this process started while another
        starts one — here, during the walk. The walk is over a copy, so the
        start neither breaks it nor is lost."""
        supervisor, polled = self.supervisor, []

        class Launcher:
            def __init__(self, name: str, starts: str | None = None) -> None:
                self.name, self.starts = name, starts

            def poll(self):
                polled.append(self.name)
                if self.starts:
                    supervisor._children[self.starts] = Launcher(self.starts)
        supervisor._children["job-first"] = Launcher("job-first", starts="job-second")
        try:
            supervisor._reap()
        except RuntimeError as broken:
            self.fail(f"the walk broke: {broken}")
        self.assertEqual((polled, sorted(supervisor._children)), (["job-first"], ["job-first", "job-second"]))
        supervisor._reap()
        self.assertEqual(polled, ["job-first", "job-first", "job-second"])

    def test_a_supervisor_killed_holding_the_lock_leaves_it_to_the_next_advance(self) -> None:
        """A supervisor process stops inside an advance, once launch intent
        is recorded, holding the job's lock. While it lives, an advance and a
        recover() waiting at most lock_wait_s answer busy, spending and
        sending nothing. Killed (SIGKILL: no cleanup), it leaves the lock
        free: the next recover() takes it at once and the job commits,
        started once."""
        self.supervisor.prepare(self.order("research_pass", succeed()))
        child = children.popen(["-m", "gen2.tests.supervisor_child", str(self.root), MAIN, "launch_recorded", LATER, "hold"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(child.communicate)
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "holding")
        path = self.root / "jobs" / f"job-{MAIN}" / "journal.json"
        journal, impatient = path.read_bytes(), self.make_supervisor(policy=IMPATIENT)
        self.assertEqual((impatient.advance(MAIN), impatient.recover()), ("busy", {MAIN: "busy"}))
        self.assertEqual((path.read_bytes(), self.control.calls), (journal, 0))
        child.kill()
        self.assertEqual(child.wait(10), -9)
        self.clock.set("2026-09-27T11:00:00Z")
        started = time.monotonic()
        self.assertEqual(self.make_supervisor(policy=IMPATIENT).recover(), {MAIN: "running"})
        self.assertLess(time.monotonic() - started, IMPATIENT.identity_grace_s)
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        self.assertEqual((self.ended()["state"], self.ended()["transitions"], self.spawns()),
                         ("committed", ["admitted", "launching", "running", "result_ready", "committed"], 1))


if __name__ == "__main__":
    unittest.main()
