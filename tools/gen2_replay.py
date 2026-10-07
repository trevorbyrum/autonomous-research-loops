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
A Router a test gives its own clock or ids keeps them. NOT seams here, so a test they show in is reported unresolved with the field named: the identity of a real job process
(pid, start time, session: a test asserts the real values, so replacing them fails the test itself, tried first) and real timing (how often a supervisor polls decides how many
router calls, clock readings and ids a test makes).
"""
from __future__ import annotations

import datetime
import gzip
import json
import os
import subprocess
import sys
import threading
import unittest

SEED = "PYTHONHASHSEED"
if os.environ.get(SEED) != "0":
    os.execve(sys.executable, [sys.executable, *sys.argv], {**os.environ, SEED: "0"})
TREE, OUT, MODULES = os.path.realpath(sys.argv[1]), sys.argv[2], sys.argv[3:]
os.chdir(TREE)
sys.path[:0] = [TREE, os.path.join(TREE, "gen2", "tests")]

from gen2.router import service  # noqa: E402  (the tree's own)

assert os.path.realpath(service.__file__).startswith(TREE), service.__file__
TRACKED = {"record_capability_probe", "record_gateway_facts", "status", "healthy", "activate_config_bundle", "config_bundle", "restore_config_bundle", "record_qualification",
           "revoke_qualification", "is_qualified",
           "request_cancel", "reconcile", "record_transition", "commit_outcome", "apply_operator_decision",
           "requeue", "open_reservation", "open_review", "create_topic", "raise_signal", "claim"}  # the store is read back right after each of these: the collaborators' routes
# and the registry routes (Astra 2q-b3 NB2), then Lifecycle's two write routes and the three write routes that reach its members through the core's delegates (2q-b6, ruling 2),
# then Scheduling's five write routes and `claim`, which reaches its lane and reservation members through the core's delegates (2q-b7, ruling 2)
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
    addFailure, addError, addSkip = noting("Failure"), noting("Error"), noting("Skip")

    def startTest(self, test):
        Recorder.calls, Recorder.routers = [], []
        Counters.clock = Counters.tokens = 0
        fix_seams()
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
        super().stopTest(test)


if __name__ == "__main__":
    install()
    result = unittest.TextTestRunner(resultclass=Result, verbosity=0, stream=sys.stderr).run(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with gzip.open(OUT, "wt", encoding="utf-8") as handle:
        json.dump({"tree": head, "python": sys.version.split()[0], "tests": Result.log}, handle, default=repr)
    print(f"{len(Result.log)} tests, {sum(len(v.get('calls', [])) for v in Result.log.values())} Router calls, {len(result.failures)} failures, {len(result.errors)} errors", file=sys.stderr)
