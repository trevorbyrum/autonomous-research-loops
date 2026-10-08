"""Self-tests of tools/gen2_replay_seams.py, the replay's seams for real processes (task 2q-t4; DEBT-023 item 1; Astra 2q-b3b ruling 4).

What each shows, by hand-written expectations: the seam gives one real launcher one identity in the recorder and in a child process, and two launchers two (the ordinal of first sight,
not the real value); it changes nothing when its registry is not named; the clock and ids a child reads are fixed, counted across the children of a test, and disjoint from the
recorder's own ids; the tests that assert a real identity do assert it (with the seam they fail by that assertion, without it they pass); the poll schedule waits once per launch for
the launch's end. Task 2q-t4b adds: children that run at once never draw the same id or instant; a child or a poll of a test that runs real is the stock one, in the recorder
and in a child; the interpreters a test starts are counted against those that armed, and the kinds that did not are named; and the recorder, end to end, runs a real-identity test
real and another with the seams. What they cannot show: that every Python process of a replay run gets the overlay (the per-test accounting in the run files of the evidence says
what did not), or that a change to the format of `jobs.fingerprint` is seen by the replay (it is not: only the real-identity tests see it).
"""
from __future__ import annotations

import gzip
import json
import os
import runpy
import shutil
import subprocess
import sys
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


def at_once(registry: str | None, count: int, code: str) -> list:
    """What `count` children report that run `code` at the same time, from an overlay as a replay's children do."""
    overlay = SEAMS["overlay"](str(children.code_root()))
    try:
        with mock.patch.dict(os.environ, {children.ROOT_VARIABLE: overlay, **({ENV: registry} if registry else {})}):
            running = [children.popen(["-c", code], stdout=subprocess.PIPE, text=True) for _ in range(count)]
        out = [json.loads(p.communicate(timeout=60)[0]) for p in running]
        assert all(p.returncode == 0 for p in running)
        return out
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


class DistinctnessTest(unittest.TestCase):
    """Task 2q-t4b: what two children of one test draw."""

    def test_children_running_at_once_never_draw_the_same_id_or_the_same_instant_and_none_the_recorders(self) -> None:
        draw = "import datetime, json, secrets; print(json.dumps([[secrets.token_hex(4) for _ in range(40)], [datetime.datetime.now().isoformat() for _ in range(40)]]))"
        with tempfile.TemporaryDirectory() as registry:
            drawn = at_once(registry, 5, draw)
        ids, instants = [i for ids, _ in drawn for i in ids], [t for _, ts in drawn for t in ts]
        self.assertEqual((len(set(ids)), len(set(instants))), (200, 200))  # no two draws alike, whichever children made them
        self.assertEqual(sorted(ids), [f"{0x80000000 + n:08x}" for n in range(1, 201)])  # counted across the five: none skipped, none repeated, all in the children's range (the recorder's are 0000000n)
        self.assertEqual(sorted(instants)[0], "2026-10-01T00:00:00.001000")

    def test_a_child_and_a_poll_of_a_test_that_runs_real_are_the_stock_ones(self) -> None:
        probe = ("import datetime, json, secrets; from gen2.supervisor import jobs; "
                 "print(json.dumps([type(datetime.datetime.now()).__name__, secrets.token_hex.__module__, jobs.fingerprint.__module__]))")
        with tempfile.TemporaryDirectory() as registry:
            self.assertEqual(at_once(registry, 1, probe), [["ChildDatetime", "sitecustomize", "sitecustomize"]])
        self.assertEqual(at_once(None, 1, probe), [["datetime", "secrets", "gen2.supervisor.jobs"]])  # nothing replaced, no hook: the overlay was imported and installed nothing


class AccountingTest(unittest.TestCase):
    def test_the_interpreters_a_test_started_are_counted_against_those_that_armed_and_the_kinds_that_did_not_are_named(self) -> None:
        with tempfile.TemporaryDirectory() as registry, tempfile.TemporaryDirectory() as scripts:
            for name in ("armed_one.py", "unarmed_one.py"):
                Path(scripts, name).write_text("pass\n")
            code = (f"import os, subprocess, sys; subprocess.run([sys.executable, {scripts + '/armed_one.py'!r}]); "  # inherits the environment: arms
                    f"subprocess.run([sys.executable, {scripts + '/unarmed_one.py'!r}], env={{k: v for k, v in os.environ.items() if k not in ('{ENV}', 'PYTHONPATH')}}); print('[]')")
            at_once(registry, 1, code)
            with mock.patch.dict(os.environ, {ENV: registry}):
                self.assertEqual(SEAMS["account"](), {"launched": 2, "armed": 2, "unarmed": {"unarmed_one.py": 1}})  # armed: the child (-c) and armed_one.py
            self.assertEqual(SEAMS["account"](), {"launched": 0, "armed": 0})  # no registry named: a test that runs real has nothing to count


class RecorderTest(unittest.TestCase):
    """The recorder end to end (tools/gen2_replay.py on this tree): one test that asserts a real identity, one that does not."""
    LIFECYCLE = "gen2.tests.test_supervisor_lifecycle.ResearchPassLifecycleTest."
    REAL, FIXED = LIFECYCLE + "test_a_clean_end_commits_the_result_with_its_execution_record", LIFECYCLE + "test_a_wrong_declared_digest_fails"

    def record(self, *names: str, **env: str) -> dict:
        with tempfile.TemporaryDirectory() as out:
            done = subprocess.run([sys.executable, str(Path(SEAMS["__file__"]).with_name("gen2_replay.py")), str(children.code_root()), f"{out}/run.json.gz", *names],
                                  capture_output=True, text=True, timeout=300, env={**{k: v for k, v in os.environ.items() if k not in (ENV, "PYTHONPATH", children.ROOT_VARIABLE)}, **env})
            self.assertEqual(done.returncode, 0, done.stderr)
            with gzip.open(f"{out}/run.json.gz", "rt", encoding="utf-8") as handle:
                return json.load(handle)

    def test_a_real_identity_test_runs_real_and_another_runs_with_the_seams(self) -> None:
        run = self.record(self.REAL, self.FIXED)
        held = {name: [r["start_fingerprint"] for r in test["end"][0]["store"]["invocations"]] for name, test in run["tests"].items()}
        self.assertEqual({n: (t["outcome"], t["processes"]) for n, t in run["tests"].items()}, {self.REAL: ("pass", "real"), self.FIXED: ("pass", "fixed")})
        self.assertEqual(held[self.FIXED], ["pid=1001;starttime=2001;session=1001"])  # the ordinal of the only launcher
        self.assertRegex(held[self.REAL][0], r"^pid=(?!1001;)\d+;starttime=\d+;session=\d+$")  # the launcher's own, which the test asserted
        self.assertEqual(run["seams"][self.REAL], {"launched": 0, "armed": 0})  # no poll waited for, no interpreter counted
        fixed = run["seams"][self.FIXED]
        self.assertEqual((fixed["waited"], fixed["launched"], fixed["armed"], fixed["unarmed"]), (1, 2, 1, {"fake_executor.py": 1}))  # the launcher armed; the executor's environment is the job's own
        natural = self.record(self.FIXED, GEN2_REPLAY_POLLING="natural")  # the poll schedule left out of a run: no look waits, the rest is the same
        self.assertEqual(({k: v for k, v in natural["seams"][self.FIXED].items() if k != "waited"}, "waited" in natural["seams"][self.FIXED], natural["tests"][self.FIXED]["outcome"]),
                         ({"launched": 2, "armed": 1, "unarmed": {"fake_executor.py": 1}}, False, "pass"))


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

    def test_without_the_seams_each_passes_asserting_the_real_values_and_with_them_each_fails_by_that_assertion(self) -> None:
        for name in self.NAMES:
            with self.subTest(name.split(".")[-2]):
                real = self.run_one(name, None)
                self.assertEqual(real.returncode, 0, real.stderr)
                with tempfile.TemporaryDirectory() as registry:
                    fixed = self.run_one(name, registry)
                self.assertNotEqual(fixed.returncode, 0)
                self.assertRegex(fixed.stderr, r"'pid=100\d;starttime=200\d;session=100\d'")  # the router's row held the seam's identity (the delegate's is its test's second launcher); the identity file holds the real one


class SettleTest(unittest.TestCase):
    """`Settle.first_look`: the first look at a launch that has an identity and no end waits for the end, once."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patched = mock.patch.dict(os.environ, {ENV: self._tmp.name})  # a replay run: the registry is named
        patched.start()
        self.addCleanup(patched.stop)
        self.job = jobs.Job(Path(self._tmp.name), "job-x")
        self.job.prepare({})
        self.seen: list[bool] = []
        self.look = SEAMS["Settle"].first_look(lambda sup, job, order, journal: self.seen.append((job.dir / "exit.json").exists()))
        self.addCleanup(SEAMS["Settle"].looked.clear)
        self.addCleanup(SEAMS["Settle"].stats.clear)

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

    def test_a_test_that_runs_real_is_looked_at_as_in_production_and_counts_nothing(self) -> None:
        self.job.write("spawn.json", {"attempts": 1, "failed": 0})
        self.job.write("identity.json", LAUNCHER)
        with mock.patch.dict(os.environ, {ENV: ""}), mock.patch.object(SEAMS["Settle"], "CAP_S", 5.0):
            started = time.monotonic()
            self.look(None, self.job, {}, {})
        self.assertEqual((self.seen, time.monotonic() - started < 1.0, dict(SEAMS["Settle"].stats), SEAMS["Settle"].looked), ([False], True, {}, set()))

    def test_the_looks_that_waited_are_counted_and_those_that_waited_the_whole_cap(self) -> None:
        self.job.write("spawn.json", {"attempts": 1, "failed": 0})
        self.job.write("identity.json", LAUNCHER)
        with mock.patch.object(SEAMS["Settle"], "CAP_S", 0.05):
            self.look(None, self.job, {}, {})
        self.assertEqual(dict(SEAMS["Settle"].stats), {"waited": 1, "capped": 1})

    def test_a_job_with_no_identity_is_not_waited_for(self) -> None:
        with mock.patch.object(SEAMS["Settle"], "CAP_S", 5.0):
            started = time.monotonic()
            self.look(None, self.job, {}, {})
        self.assertEqual((self.seen, time.monotonic() - started < 1.0), ([False], True))


if __name__ == "__main__":
    unittest.main()
