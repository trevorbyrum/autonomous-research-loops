"""Self-tests of tools/gen2_replay_seams.py, the replay's seams for real processes (task 2q-t4; DEBT-023 item 1; Astra 2q-b3b ruling 4).

What each shows, by hand-written expectations: the seam gives one real launcher one identity in the recorder and in a child process, and two launchers two (the ordinal of first sight,
not the real value); it changes nothing when its registry is not named; the clock and ids a child reads are fixed, counted across the children of a test, and disjoint from the
recorder's own ids; the tests that assert a real identity do assert it (with the seam they fail by that assertion, without it they pass); the poll schedule waits once per launch for
the launch's end. What they cannot show: that every Python process of a replay run gets the overlay (the replays of the evidence, whose unresolved list says what is left), or that
a change to the format of `jobs.fingerprint` is seen by the replay (it is not: only the real-identity tests see it).
"""
from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from gen2.supervisor import jobs
from gen2.tests import children

SEAMS = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools" / "gen2_replay_seams.py"))
ENV = SEAMS["ENV"]
LAUNCHER = {"pid": 4242, "session": 4242, "starttime": 777, "boot_id": "b"}
OTHER = {**LAUNCHER, "pid": 4243, "session": 4243}
PRINT = ("import datetime, json, secrets; from gen2.supervisor import jobs; "
         "print(json.dumps([jobs.fingerprint(%s), jobs.fingerprint(%s), datetime.datetime.now(datetime.timezone.utc).isoformat(), secrets.token_hex(4), secrets.token_hex(4)]))")


def child(registry: str | None, *identities: dict) -> list:
    """What a child process reports: its fingerprint of each identity, one clock reading and two ids. It runs from an overlay, as a replay's children do."""
    overlay = SEAMS["overlay"](str(children.code_root()))
    try:
        env = {children.ROOT_VARIABLE: overlay, **({ENV: registry} if registry else {})}
        with mock.patch.dict(os.environ, env):
            done = children.python(["-c", PRINT % tuple(map(repr, identities))], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(overlay)


class IdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.registry = self._tmp.name

    def virtual(self, identity: dict) -> str:
        with mock.patch.dict(os.environ, {ENV: self.registry}):
            return SEAMS["replaced"](jobs.fingerprint)(identity)

    def test_without_its_registry_the_answer_is_the_real_one(self) -> None:
        with mock.patch.dict(os.environ, {ENV: ""}):
            self.assertEqual(SEAMS["replaced"](jobs.fingerprint)(LAUNCHER), "pid=4242;starttime=777;session=4242")

    def test_one_launcher_has_one_identity_and_two_launchers_two_whatever_their_real_values(self) -> None:
        first, second = self.virtual(LAUNCHER), self.virtual(OTHER)
        self.assertEqual((first, second, self.virtual(LAUNCHER)), ("pid=1001;starttime=2001;session=1001", "pid=1002;starttime=2002;session=1002", first))
        with tempfile.TemporaryDirectory() as fresh:  # another test: other real values, seen in the same order, are the same two identities
            self.registry = fresh
            self.assertEqual((self.virtual({**LAUNCHER, "pid": 9}), self.virtual({**OTHER, "starttime": 5})), (first, second))

    def test_a_child_gives_one_launcher_the_identity_its_parent_gave_it_and_a_new_one_a_new_identity(self) -> None:
        parent = self.virtual(LAUNCHER)
        in_child = child(self.registry, LAUNCHER, OTHER)
        self.assertEqual(in_child[0], parent)  # the parent saw it first
        self.assertEqual(in_child[1], "pid=1002;starttime=2002;session=1002")
        self.assertEqual(self.virtual(OTHER), in_child[1])  # the child saw it first: the parent agrees
        self.assertEqual(child(self.registry, OTHER, LAUNCHER)[:2], [in_child[1], parent])  # and a second child agrees with both

    def test_a_child_not_given_the_registry_is_real(self) -> None:
        real = child(None, LAUNCHER, OTHER)
        self.assertEqual(real[:2], ["pid=4242;starttime=777;session=4242", "pid=4243;starttime=777;session=4243"])
        self.assertNotEqual(real[2][:19], "2026-10-01T00:00:00")  # not the fixed instant: a real reading

    def test_a_childs_clock_and_ids_are_fixed_counted_across_children_and_apart_from_the_recorders(self) -> None:
        first, second = child(self.registry, LAUNCHER, OTHER), child(self.registry, LAUNCHER, OTHER)
        self.assertEqual((first[2], second[2]), ("2026-10-01T00:00:00.001000+00:00", "2026-10-01T00:00:00.002000+00:00"))
        self.assertEqual((first[3], first[4], second[3]), ("80000001", "80000002", "80000003"))  # a leading 8: never an id the recorder's own counter mints (0000000n)


class RealIdentityTest(unittest.TestCase):
    """Task 2q-t4 item 2: the tests that assert the real pid, start time and session stay real."""
    NAMES = sorted(SEAMS["REAL_IDENTITY"])

    def run_one(self, name: str, registry: str | None) -> subprocess.CompletedProcess:
        overlay = SEAMS["overlay"](str(children.code_root()))
        try:
            with mock.patch.dict(os.environ, {children.ROOT_VARIABLE: overlay, **({ENV: registry} if registry else {})}):
                return children.python(["-m", "unittest", name], capture_output=True, text=True, timeout=120)
        finally:
            shutil.rmtree(overlay)

    def test_they_are_the_five_clean_end_tests_one_per_kind(self) -> None:
        found = [[t.id() for t in unittest.defaultTestLoader.loadTestsFromName(name)] for name in self.NAMES]
        self.assertEqual(found, [[name] for name in self.NAMES])  # each names one test that exists (a stale name loads as a failing stand-in with another id)
        self.assertEqual(len(self.NAMES), 5)

    def test_without_the_seams_one_passes_asserting_the_real_values_and_with_them_it_fails_by_that_assertion(self) -> None:
        name = self.NAMES[0]
        real = self.run_one(name, None)
        self.assertEqual(real.returncode, 0, real.stderr)
        with tempfile.TemporaryDirectory() as registry:
            fixed = self.run_one(name, registry)
        self.assertNotEqual(fixed.returncode, 0)
        self.assertIn("'pid=1001;starttime=2001;session=1001'", fixed.stderr)  # the router's row held the seam's identity; the identity file holds the real one


class SettleTest(unittest.TestCase):
    """`Settle.first_look`: the first look at a launch that has an identity and no end waits for the end, once."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.job = jobs.Job(Path(self._tmp.name), "job-x")
        self.job.prepare({})
        self.seen: list[bool] = []
        self.look = SEAMS["Settle"].first_look(lambda sup, job, order, journal: self.seen.append((job.dir / "exit.json").exists()))
        self.addCleanup(SEAMS["Settle"].looked.clear)

    def test_a_launch_that_ends_while_the_first_look_waits_is_found_ended_and_not_waited_for_again(self) -> None:
        self.job.write("spawn.json", {"attempts": 1, "failed": 0})
        self.job.write("identity.json", LAUNCHER)
        ends = threading.Timer(0.1, lambda: self.job.write("exit.json", {"code": 0, "signal": None}))
        self.addCleanup(ends.join)
        ends.start()
        self.look(None, self.job, {}, {})
        self.look(None, self.job, {}, {})
        self.assertEqual(self.seen, [True, True])

    def test_a_launch_that_does_not_end_is_waited_for_once_up_to_the_cap_then_looked_at_as_ever(self) -> None:
        self.job.write("spawn.json", {"attempts": 1, "failed": 0})
        self.job.write("identity.json", LAUNCHER)
        with mock.patch.object(SEAMS["Settle"], "CAP_S", 0.2):
            started = time.monotonic()
            self.look(None, self.job, {}, {})
            waited = time.monotonic() - started
            self.look(None, self.job, {}, {})
            self.assertEqual((self.seen, 0.2 <= waited < 1.0, time.monotonic() - started - waited < 0.1), ([False, False], True, True))
            self.job.write("spawn.json", {"attempts": 2, "failed": 0})  # a new start of the job is a new launch
            started = time.monotonic()
            self.look(None, self.job, {}, {})
            self.assertGreaterEqual(time.monotonic() - started, 0.2)

    def test_a_job_with_no_identity_is_not_waited_for(self) -> None:
        with mock.patch.object(SEAMS["Settle"], "CAP_S", 5.0):
            started = time.monotonic()
            self.look(None, self.job, {}, {})
        self.assertEqual((self.seen, time.monotonic() - started < 1.0), ([False], True))


if __name__ == "__main__":
    unittest.main()
