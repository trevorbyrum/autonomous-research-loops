#!/usr/bin/env python3
"""Exact deterministic Router replay, the recorder (task 2q-b3b; research note docs/gen2/research/2q-b-differential-20261006.md).

    python tools/gen2_replay.py TREE OUT.json.gz TESTMODULE [TESTMODULE ...]       (raw values: nothing is normalised, masked, sorted or hashed)

Replays the test modules through TREE's own gen2/ and records per test every top-level Router call (arguments copied when it starts, the result or the exception when it
returns), the store's rows right after each call of the TRACKED routes, and at the end each Router's rows (`store`), what a shadow Router over the same store answers
(`shadow_answers`) and its rows again (`store_after_shadow`). tools/gen2_replay_compare.py compares two such runs exactly and never calls an unstable baseline equivalent.

Nondeterminism is fixed at its source, not scrubbed from the output:
  * the clock: every `datetime.now` of a production module, one reading per millisecond from one fixed instant, counting afresh in each test;
  * ids and tokens: every `secrets.token_hex` of a production module (the router's `random_id`, probe ids, spool temp names), a counter counting afresh in each test;
  * PYTHONHASHSEED=0 (set iteration order): the recorder re-executes itself with it.
A Router a test gives its own clock or ids keeps them.
Real processes (task 2q-t4; tools/gen2_replay_seams.py, which says how): the identity a supervisor embeds in its records for a real job process (the pid, start time and session of
the launcher it started) is the ordinal of the real one among those the test saw, the same in every process of the test; a child process reads a fixed clock and draws counted ids
of its own range; and the first poll of a started job waits for the job's end, so how many polls a test makes no longer depends on how fast a real process ran (that wait
removes the one to three polls a supervisor makes while the job still runs, in about half the lifecycle tests, and stabilises a few that vary by timing: GEN2_REPLAY_POLLING=natural
leaves it out of a run, and the polls come as they come; evidence/2q-t4b/README.txt has the measure). Each of these acts
only in a replay run, and a test in REAL_IDENTITY (it asserts the real identity file) runs with none of it: its identity, its children and its polls are the real ones. The run
file also holds, outside `tests` (the comparator never reads it), what each test's seams did: the looks that waited for a job's end (`waited`, and `capped` when it never came), the
Python interpreters its processes started (`launched`), the children that armed themselves (`armed`), the kinds that did not (`unarmed`) and the children that asked for a job process's identity (`identified_by_children`). NOT seams, so a test they show in is reported unresolved with the field
named: that real identity, and the order in which threads the operating system schedules take their clock readings (two probes whose runners wait for each other).
"""
from __future__ import annotations

import datetime
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SEED, POLLING = "PYTHONHASHSEED", "GEN2_REPLAY_POLLING"
if os.environ.get(SEED) != "0":
    os.execve(sys.executable, [sys.executable, *sys.argv], {**os.environ, SEED: "0"})
TREE, OUT, MODULES = os.path.realpath(sys.argv[1]), sys.argv[2], sys.argv[3:]
HERE = os.path.dirname(os.path.realpath(__file__))
os.chdir(TREE)
sys.path[:0] = [TREE, os.path.join(TREE, "gen2", "tests")]
sys.path.append(HERE)

import gen2_replay_seams as seams  # noqa: E402  (this recorder's own, never the tree's)
from gen2.router import service  # noqa: E402  (the tree's own)
from gen2.supervisor import supervisor as supervised  # noqa: E402

assert os.path.realpath(service.__file__).startswith(TREE), service.__file__
TRACKED = {"record_capability_probe", "record_gateway_facts", "status", "healthy", "activate_config_bundle", "config_bundle", "restore_config_bundle", "record_qualification",
           "revoke_qualification", "is_qualified",
           "request_cancel", "reconcile", "record_transition", "commit_outcome", "apply_operator_decision",
           "requeue", "open_reservation", "open_review", "create_topic", "raise_signal", "claim",
           "version_brief", "open_brief", "mark_brief_overdue", "propose_amendment", "draft_contract", "close_brief"}  # the store is read back right after each of these: the collaborators' routes
# and the registry routes (Astra 2q-b3 NB2), then Lifecycle's two write routes and the three write routes that reach its members through the core's delegates (2q-b6, ruling 2),
# then Scheduling's five write routes and `claim`, which reaches its lane and reservation members through the core's delegates (2q-b7, ruling 2), then Amendments' six write routes
# (2q-b8, ruling 2; `apply_operator_decision` and `commit_outcome`, which reach its impact, replacement, reference and pin members through the core's delegates, are tracked above)
SEEN = threading.local()


class Counters:
    clock = tokens = 0


class FixedDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        Counters.clock += 1
        return cls(2026, 9, 27, 10, tzinfo=tz) + datetime.timedelta(milliseconds=Counters.clock)


class FixedSecrets:
    @staticmethod
    def token_hex(nbytes: int = 32) -> str:
        Counters.tokens += 1
        return f"{Counters.tokens:0{2 * nbytes}x}"


def seam_processes() -> str:
    """The seams of real processes (tools/gen2_replay_seams.py) for this run and its children; returns the overlay a child imports the code from (removed at the end of the run)."""
    path = seams.overlay(TREE)
    os.environ.update(GEN2_CHILD_ROOT=path, PYTHONPATH=path)
    seams.install(child=False)
    if os.environ.get(POLLING) != "natural":  # the poll schedule is a seam like the others, and a run may leave it out: the polls then come as they come
        supervised.Supervisor._observe = seams.Settle.first_look(supervised.Supervisor._observe)
    return path


def fix_seams() -> None:
    """Every production module that reads the wall clock or draws a token, found by its source, so a new reader is fixed too and never silently missed."""
    for name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None) or ""
        if name.startswith("gen2.") and not name.startswith("gen2.tests") and path.endswith(".py"):
            text = open(path, encoding="utf-8").read()
            if "datetime.now(" in text:
                module.datetime = FixedDatetime
            if "secrets.token_" in text:
                module.secrets = FixedSecrets


def snap(value):
    """A deep copy as plain JSON values, taken now (an object that is not JSON is its repr, so an address in one shows as a difference, never as equality)."""
    try:
        return json.loads(json.dumps(value, default=repr))
    except (TypeError, ValueError, RecursionError):  # a key that is not a string, a cycle: the whole value as its repr, still compared
        return {"unserialisable": repr(value)}


def store_rows(router):
    conn = router._store._conn
    try:
        if conn.in_transaction:
            return "in-transaction"
        out = {}
        for (name,) in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            cursor = conn.execute(f"SELECT * FROM {name} ORDER BY rowid")
            columns = [c[0] for c in cursor.description]
            out[name] = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return snap(out)
    except Exception as exc:  # a closed store: said so, compared like any other value
        return f"unreadable: {type(exc).__name__}"


class Recorder:
    calls: list = []
    routers: list = []
    shadow = False


def wrap(name, fn):
    def wrapped(self, *args, **kwargs):
        if Recorder.shadow or self not in Recorder.routers or getattr(SEEN, "inside", False):
            return fn(self, *args, **kwargs)
        entry = {"method": name, "router": Recorder.routers.index(self), "args": snap(args), "kwargs": snap(kwargs)}
        SEEN.inside = True
        try:
            result = fn(self, *args, **kwargs)
            entry["result"] = snap(result)
            return result
        except BaseException as exc:  # a raised answer is an answer too
            entry["raised"] = [type(exc).__name__, str(exc)]
            raise
        finally:
            SEEN.inside = False
            if name in TRACKED:
                entry["store"] = store_rows(self)
            Recorder.calls.append(entry)
    return wrapped


def install() -> None:
    original = service.Router.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if not Recorder.shadow:
            Recorder.routers.append(self)
    service.Router.__init__ = init
    for name in sorted(n for n in dir(service.Router) if not n.startswith("_") and callable(getattr(service.Router, n)) and n not in ("open", "close")):
        setattr(service.Router, name, wrap(name, getattr(service.Router, name)))


def end_of_test() -> list:
    """What each Router the test made leaves, and what a shadow Router over the same store answers under two fixed clocks (`status` writes nothing)."""
    out = []
    for index, router in enumerate(Recorder.routers):
        before = store_rows(router)
        answers = []
        if isinstance(before, dict):
            Recorder.shadow = True
            try:
                for clock in ("2026-09-27T10:30:00.000Z", "2031-01-01T00:00:00.000Z"):
                    shadow = service.Router(router._store, router._spool, clock=lambda c=clock: c, schemas=router._schemas)
                    for method, args in (("status", ({},)), ("healthy", ())):
                        try:
                            answers.append([clock, method, snap(getattr(shadow, method)(*args))])
                        except BaseException as exc:
                            answers.append([clock, method, "raised", type(exc).__name__, str(exc)])
                for tid in [r["topic_id"] for r in before["queue_entries"]]:
                    shadow = service.Router(router._store, router._spool, clock=lambda: "2026-09-27T10:30:00.000Z", schemas=router._schemas)
                    answers.append([tid, "status", snap(shadow.status({"topic_id": tid}))])
            finally:
                Recorder.shadow = False
        out.append({"router": index, "store": before, "shadow_answers": answers, "store_after_shadow": store_rows(router)})
    return out


def noting(kind: str):
    def add(self, test, *rest):
        Result.log.setdefault(test.id(), {})["outcome"] = kind.lower()
        getattr(unittest.TextTestResult, f"add{kind}")(self, test, *rest)
    return add


class Result(unittest.TextTestResult):
    log: dict = {}
    seams: dict = {}
    addFailure, addError, addSkip = noting("Failure"), noting("Error"), noting("Skip")

    def startTest(self, test):
        Recorder.calls, Recorder.routers = [], []
        Counters.clock = Counters.tokens = 0
        seams.Settle.stats.clear()
        fix_seams()
        real = test.id() in seams.REAL_IDENTITY
        if real:
            os.environ.pop(seams.ENV, None)
        else:
            os.environ[seams.ENV] = tempfile.mkdtemp(dir=OVERLAY)
        Result.log.setdefault(test.id(), {})["processes"] = "real" if real else "fixed"
        original = test.tearDown

        def tear_down():
            Result.log.setdefault(test.id(), {}).update({"calls": Recorder.calls, "end": end_of_test()})
            return original()
        test.tearDown = tear_down
        super().startTest(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:  # a failing subtest is not a pass of its test
            Result.log.setdefault(test.id(), {})["outcome"] = "subtest"
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        Result.log.setdefault(test.id(), {}).setdefault("outcome", "pass")
        Result.seams[test.id()] = {**seams.Settle.stats, **seams.account()}  # after the cleanups: the children are reaped
        super().stopTest(test)


if __name__ == "__main__":
    OVERLAY = seam_processes()
    install()
    result = unittest.TextTestRunner(resultclass=Result, verbosity=0, stream=sys.stderr).run(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    shutil.rmtree(OVERLAY, ignore_errors=True)
    stale = sorted(t for t in seams.REAL_IDENTITY if t.rsplit(".", 2)[0] in MODULES and Result.log.get(t, {}).get("processes") != "real")
    assert not stale, f"seams.REAL_IDENTITY names tests that did not run: {stale}"
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with gzip.open(OUT, "wt", encoding="utf-8") as handle:
        json.dump({"tree": head, "python": sys.version.split()[0], "tests": Result.log, "seams": Result.seams}, handle, default=repr)
    print(f"{len(Result.log)} tests, {sum(len(v.get('calls', [])) for v in Result.log.values())} Router calls, {len(result.failures)} failures, {len(result.errors)} errors", file=sys.stderr)
