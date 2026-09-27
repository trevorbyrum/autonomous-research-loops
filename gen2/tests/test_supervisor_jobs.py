"""The job layer (task 1c; gen2/supervisor/jobs.py and jobshim.py): lookup by
the stable handle, process identity, the execution group, and the launcher's
own records.

Trace: INVARIANTS L-2, L-3, L-4, L-7, §11.2 (no adoption by pid or command
line); design review §5 ("Crash fencing").

What these show: a pid alone is never the job — a live process named by an
identity with another start time, or on another boot, is not taken for the
launcher and its session is not the job's group; each lookup verdict arises
from exactly the job-directory and /proc facts it names; a start that left
no identity is settled as never started only when no launcher holds the
lock, and a launcher started after that starts nothing; the launcher
records how its executor ended (code or signal); terminating a group ends
the executor and a descendant and confirms them gone. Launchers here are
real child processes (jobshim.py, started from the code tree children.py
names, so the mutation runner's child tree reaches them).

Oracles: /proc read here; expected verdicts by hand.
What they cannot show: a descendant that leaves the session (not a member,
by construction), or pid reuse within a job's life (jobs.py, limits).
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from gen2.supervisor import jobs
from gen2.tests import children


def own_identity(**overrides) -> dict:
    pid = os.getpid()
    return {"pid": pid, "session": os.getsid(0), "starttime": jobs.proc_stat(pid)[2], "boot_id": jobs.boot_id(), **overrides}


class JobTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.job = jobs.Job(self.root, "job-inv_testjob01")
        self.popens = []

    def tearDown(self) -> None:
        identity = self.job.read("identity.json")
        if identity is not None and identity["pid"] != os.getpid():
            self.job.terminate(identity, term_grace=0.2, kill_grace=5, reap=self.reap)
        self.reap()
        self._tmp.cleanup()

    def reap(self) -> None:
        for popen in self.popens:
            popen.poll()

    def prepare(self, steps: list[dict]) -> None:
        script = self.root / "script.json"
        script.write_text(json.dumps({"steps": steps}))
        self.job.prepare({"command": [sys.executable, str(children.path("gen2/supervisor/fake_executor.py")), str(script)], "env": {}})

    def start(self) -> None:
        self.popens.append(self.job.spawn([sys.executable, str(children.path("gen2/supervisor/jobshim.py"))]))

    def wait(self, predicate, seconds: float = 10.0) -> None:
        deadline = time.monotonic() + seconds
        while not predicate():
            self.reap()
            if time.monotonic() >= deadline:
                self.fail("timed out")
            time.sleep(0.005)


class IdentityTest(JobTestCase):
    def test_a_pid_alone_is_not_the_job(self) -> None:
        """This test process is alive; an identity naming its pid with another
        start time, or another boot, is not it (L-3)."""
        self.job.prepare({"command": ["true"], "env": {}})
        cases = {"the same start": ("running", True), "another start time": ("vanished", True), "another boot": ("vanished", False)}
        for name, (verdict, session_counted) in cases.items():
            with self.subTest(name):
                identity = {"the same start": own_identity(),
                            "another start time": own_identity(starttime=own_identity()["starttime"] - 1),
                            "another boot": own_identity(boot_id="00000000-0000-0000-0000-000000000000")}[name]
                self.job.write("identity.json", identity)
                view = self.job.lookup()
                self.assertEqual(view["verdict"], verdict)
                self.assertEqual(os.getpid() in view["members"], session_counted)  # on another boot no process is anyone's member
        (self.job.dir / "identity.json").unlink()  # tearDown must not terminate this process

    def test_members_are_of_the_session_and_started_no_earlier(self) -> None:
        mine = own_identity()
        self.assertIn(os.getpid(), jobs.members(mine))
        self.assertNotIn(os.getpid(), jobs.members({**mine, "starttime": mine["starttime"] + 10**9}))  # started before the launcher
        self.assertEqual(jobs.members({**mine, "session": 2**22 + 12345}), [])


class LookupTest(JobTestCase):
    def test_each_verdict_from_the_facts_it_names(self) -> None:
        self.prepare([{"op": "wait_for", "name": "gate", "seconds": 60}])
        self.assertEqual(self.job.lookup()["verdict"], "not_started")
        self.job.write("spawn.json", {"attempts": 1, "failed": 1})
        self.assertEqual(self.job.lookup()["verdict"], "not_started")  # every start refused by the OS: nothing ran
        self.job.write("spawn.json", {"attempts": 1, "failed": 0})
        self.assertEqual(self.job.lookup()["verdict"], "unstarted")  # a start recorded, no launcher, no identity
        lock = os.open(self.job.dir / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            self.assertEqual(self.job.lookup()["verdict"], "starting")  # a launcher holds the lock, identity not yet written
        finally:
            os.close(lock)
        self.start()
        self.wait(lambda: len(self.job.lookup()["members"]) == 2)  # the launcher and its executor (started after the identity is written)
        self.assertEqual(self.job.lookup()["verdict"], "running")
        (self.job.scratch / "gate").write_text("open")
        self.wait(lambda: self.job.read("exit.json") is not None)
        self.assertEqual(self.job.lookup()["verdict"], "exited")

    def test_a_launcher_gone_without_an_exit_record_has_vanished(self) -> None:
        self.prepare([{"op": "hang"}])
        self.start()
        self.wait(lambda: len(self.job.lookup()["members"]) == 2)
        identity = self.job.read("identity.json")
        os.kill(identity["pid"], signal.SIGKILL)
        self.wait(lambda: identity["pid"] not in jobs.members(identity))
        view = self.job.lookup()
        self.assertEqual((view["verdict"], len(view["members"])), ("vanished", 1))  # the executor is left in the group

    def test_the_launcher_records_how_its_executor_ended(self) -> None:
        for steps, record in (([{"op": "exit", "code": 3}], {"code": 3, "signal": None}), ([{"op": "kill_self", "signal": 9}], {"code": None, "signal": 9})):
            with self.subTest(record=record):
                self.tearDown()
                self.setUp()
                self.prepare(steps)
                self.start()
                self.wait(lambda: self.job.read("exit.json") is not None)
                self.assertEqual(self.job.read("exit.json"), record)


class AbandonTest(JobTestCase):
    def test_a_start_without_identity_is_abandoned_only_with_the_lock_free(self) -> None:
        self.prepare([{"op": "hang"}])
        self.job.write("spawn.json", {"attempts": 1, "failed": 0})
        lock = os.open(self.job.dir / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            self.assertFalse(self.job.abandon())  # a launcher holds the lock: it is starting
        finally:
            os.close(lock)
        self.assertTrue(self.job.abandon())
        self.assertTrue((self.job.dir / "abandoned").exists())

    def test_a_launcher_started_after_abandonment_starts_nothing(self) -> None:
        self.prepare([{"op": "write", "name": "ran", "text": "yes"}])
        self.job.write("spawn.json", {"attempts": 1, "failed": 0})
        self.assertTrue(self.job.abandon())
        self.start()
        self.wait(lambda: self.popens[-1].poll() is not None)
        self.assertEqual(self.popens[-1].returncode, 0)
        self.assertIsNone(self.job.read("identity.json"))
        self.assertFalse((self.job.scratch / "ran").exists())

    def test_a_launcher_with_an_identity_is_never_abandoned(self) -> None:
        """Alive (its lock held) or gone (the lock free): a launcher that
        recorded its identity may have started the executor."""
        self.prepare([{"op": "wait_for", "name": "gate", "seconds": 60}])
        self.start()
        self.wait(lambda: self.job.read("identity.json") is not None)
        self.assertFalse(self.job.abandon())
        (self.job.scratch / "gate").write_text("open")
        self.wait(lambda: self.popens[-1].poll() is not None)
        self.assertFalse(self.job.abandon())


class TerminateTest(JobTestCase):
    def test_the_whole_group_is_ended_and_confirmed_gone(self) -> None:
        self.prepare([{"op": "spawn_descendant", "marker": "d.pid"}, {"op": "hang"}])
        self.start()
        self.wait(lambda: (self.job.scratch / "d.pid").exists())
        identity = self.job.read("identity.json")
        descendant = int((self.job.scratch / "d.pid").read_text())
        self.assertEqual(len(jobs.members(identity)), 3)
        ended = self.job.terminate(identity, term_grace=0.5, kill_grace=5, reap=self.reap)
        self.assertEqual(ended, {"found": 3, "confirmed": True})
        self.assertEqual(jobs.members(identity), [])
        self.wait(lambda: jobs.proc_stat(descendant) is None or jobs.proc_stat(descendant)[0] == "Z")


if __name__ == "__main__":
    unittest.main()
