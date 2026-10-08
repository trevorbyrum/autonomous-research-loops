"""The replay's seams for real processes (task 2q-t4; DEBT-023 item 1; Astra 2q-b3b ruling 4). Control nondeterminism at its source, in the recorder and in every Python child of a replay run.

  identity   The identity of a real job process (pid, start time, session) is embedded by the supervisor in the records it sends the router (`start_fingerprint`), and so in their hashes.
             The operational identity stays real: the launcher writes `identity.json`, and the supervisor finds and signals the process by it. Only what the supervisor embeds in a
             record is replaced, at its one place, `jobs.fingerprint`, by the ordinal of the real fingerprint among those the test has seen: a pure function of the real one, kept in a
             file every process of the test shares, so two processes that see one launcher agree (a counter held in a process would not), and two launchers differ as the real ones do.
  children   A child process (a replacement engine, a recorder, a child supervisor) reads the real clock and draws random ids, which the recorder fixes only in itself. In a child,
             `datetime.now` is one reading per millisecond of a fixed instant and `secrets.token_hex` a counter, each counting in a file the children of the test share, and the
             ids start in a range (a leading 8) the recorder's own counter never reaches, so a child never mints an id the test process minted.
  polling    `Settle`: how many times a supervisor polls a job depends on whether the real process had ended when the first poll came; see the class.
  accounting Every Python interpreter a process of the test starts is noted (`launched`, by an audit hook, PEP 578) and every child that armed itself notes `armed`: the recorder
             reports both per test, so a child that did not get the seams is seen, not assumed away.

How a child gets the seams without a production change: the recorder points GEN2_CHILD_ROOT (the documented place a gen-2 child imports the code from, gen2/tests/children.py) and
PYTHONPATH at an overlay directory holding a link to the tree's `gen2/` and a link to this file named `sitecustomize.py`, which Python imports on start (`__name__` is then
"sitecustomize"). All of it works only while ENV names the test's registry directory: unset or empty, every function here returns the real answer (the identity, the polls, the
audit hook), and a child that starts without it installs nothing, so its clock, ids and imports are the stock ones. A test that asserts the real identity of a job process runs
with ENV unset and stays real in all of these. Outside a replay run nothing here is loaded.
"""
from __future__ import annotations

import collections
import contextlib
import datetime
import fcntl
import importlib.abc
import importlib.util
import os
import secrets
import sys
import tempfile
import time

ENV = "GEN2_REPLAY_SEAMS"  # the test's registry directory, made by the recorder; every child inherits it
JOBS = "gen2.supervisor.jobs"
REAL_IDENTITY = {f"gen2.tests.test_supervisor_lifecycle.{kind}LifecycleTest.test_a_clean_end_commits_the_result_with_its_execution_record"
                 for kind in ("ResearchPass", "Discovery", "Delegate", "Verification", "Checkpoint")}  # the tests that read a real job process's identity file and assert the router holds
# it, the identity the launcher recorded: they run with ENV unset, real, and stay unresolved by their named source. Run with the seams they fail by that assertion.


def overlay(tree: str) -> str:
    """A directory a child imports the tree's code from, with this file as its `sitecustomize` (the caller removes it)."""
    path = tempfile.mkdtemp(prefix="gen2-replay-")
    os.symlink(os.path.join(tree, "gen2"), os.path.join(path, "gen2"))
    os.symlink(os.path.realpath(__file__), os.path.join(path, "sitecustomize.py"))
    return path


@contextlib.contextmanager
def registry(name: str):
    with open(os.path.join(os.environ[ENV], name), "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        yield handle


def ordinal(real: str) -> int:
    """The 1-based place of `real` among the fingerprints the test has seen, in the order first seen."""
    with registry("identities") as handle:
        seen = handle.read().splitlines()
        if real not in seen:
            handle.write(real + "\n")
            seen.append(real)
        return seen.index(real) + 1


def note(name: str, line: str) -> None:
    """Add a line to the test's registry file `name`."""
    with registry(name) as handle:
        handle.write(line + "\n")


def kind(argv: list) -> str:
    """What an interpreter was told to run, as one word: a script's name, `-m module` or `-c`."""
    first = str(argv[1]) if len(argv) > 1 else ""
    return f"-m {argv[2]}" if first == "-m" and len(argv) > 2 else first if first.startswith("-") else os.path.basename(first)


def launching(event: str, args: tuple) -> None:
    """Audit hook: the test's processes note each Python interpreter they start (`subprocess.Popen` of an argv list that names one) by what it runs, and those they start with an
    environment that leaves out the registry (`withheld`, with the launcher: a job's executor gets the job's own environment, not the test's)."""
    if event == "subprocess.Popen" and os.environ.get(ENV) and isinstance(args[1], (list, tuple)) and args[1] and os.path.basename(str(args[1][0])).startswith("python"):
        note("launched", kind(list(args[1])))
        if args[3] is not None and ENV not in args[3]:
            note("withheld", f"{kind(sys.orig_argv)} > {kind(list(args[1]))}")


def account() -> dict:
    """For the test now running: the Python interpreters its processes started, the children that armed themselves, the kinds that were started and did not arm (`unarmed`), of those
    the launches that withheld the registry (`withheld`), the unarmed kinds no launch withheld it from (`unexplained`: a child that should have armed and did not), and how many
    children asked for a job process's identity."""
    seen = {}
    for name in ("launched", "armed", "withheld", "identified"):
        try:
            with open(os.path.join(os.environ[ENV], name), encoding="utf-8") as handle:
                seen[name] = collections.Counter(handle.read().splitlines())
        except (KeyError, FileNotFoundError):
            seen[name] = collections.Counter()
    unarmed = dict(seen["launched"] - seen["armed"])
    withheld = collections.Counter()
    for line, n in seen["withheld"].items():
        withheld[line.split(" > ")[1]] += n
    unexplained = dict(collections.Counter(unarmed) - withheld)
    by_children = len(set(seen["identified"]) - {str(os.getpid())})  # the processes other than the recorder that asked for an identity
    return {"launched": sum(seen["launched"].values()), "armed": sum(seen["armed"].values()), **({"unarmed": unarmed} if unarmed else {}), **({"withheld": dict(seen["withheld"])} if seen["withheld"] else {}),
            **({"unexplained": unexplained} if unexplained else {}), **({"identified_by_children": by_children} if by_children else {})}


def tick(name: str) -> int:
    """The next value of a counter the test's children share."""
    with registry(name) as handle:
        n = int(handle.read() or 0) + 1
        handle.truncate(0)
        handle.write(str(n))
        return n


def replaced(fingerprint):
    def virtual(identity: dict) -> str:
        real = fingerprint(identity)
        if not os.environ.get(ENV):
            return real
        n = ordinal(real)
        note("identified", str(os.getpid()))
        return f"pid={1000 + n};starttime={2000 + n};session={1000 + n}"
    return virtual


class ChildDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        if not os.environ.get(ENV):
            return super().now(tz)
        return cls(2026, 10, 1, tzinfo=tz) + datetime.timedelta(milliseconds=tick("clock"))


def child_tokens(token_hex):
    def fixed(nbytes: int | None = None) -> str:
        if not os.environ.get(ENV):
            return token_hex(nbytes)
        nbytes = 32 if nbytes is None else nbytes
        return f"{(1 << (8 * nbytes - 1)) + tick('tokens'):0{2 * nbytes}x}"
    return fixed


class Wrap(importlib.abc.MetaPathFinder):
    """Wraps `fingerprint` of gen2.supervisor.jobs when that module is first imported."""

    def find_spec(self, name, path, target=None):
        if name != JOBS:
            return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name)
        run = spec.loader.exec_module

        def exec_module(module):
            run(module)
            module.fingerprint = replaced(module.fingerprint)
        spec.loader.exec_module = exec_module
        return spec


def install(*, child: bool) -> None:
    """In the recorder (child=False): the identity. In a child (child=True): the identity, and the clock and the ids; a child of a test that runs real installs nothing."""
    if child and not os.environ.get(ENV):
        return
    sys.addaudithook(launching)
    module = sys.modules.get(JOBS)
    if module is not None:
        module.fingerprint = replaced(module.fingerprint)
    else:
        sys.meta_path.insert(0, Wrap())
    if child:
        note("armed", kind(sys.orig_argv))
        datetime.datetime = ChildDatetime
        secrets.token_hex = child_tokens(secrets.token_hex)


class Settle:
    """The poll schedule. How many times a supervisor polls a job, and so how many router calls, clock readings and ids a test makes, depends on whether the real process had
    ended when the first poll came. The first time a supervisor looks at a launch that has recorded its identity and no end (`Supervisor._observe`, once per advance), it waits,
    up to CAP_S, for the launch to record its end, so that look finds the end however fast the process ran. A job that does not end in CAP_S (one that hangs, or waits for a gate
    the test opens) is looked at as in production, and where its polls then differ between runs the comparison says so. A test that runs real (ENV unset) is looked at as in
    production throughout: `stats` counts, for the test now running, the looks that waited and those that waited the whole CAP_S."""
    CAP_S = 1.5
    looked: set = set()
    stats: collections.Counter = collections.Counter()

    @staticmethod
    def look(job) -> None:
        launch = (str(job.dir), (job.read("spawn.json") or {}).get("attempts"))
        if launch not in Settle.looked and (job.dir / "identity.json").exists():
            Settle.looked.add(launch)
            deadline = time.monotonic() + Settle.CAP_S
            while not (job.dir / "exit.json").exists() and time.monotonic() < deadline:
                time.sleep(0.001)
            Settle.stats["waited"] += 1
            Settle.stats["capped"] += not (job.dir / "exit.json").exists()

    @staticmethod
    def first_look(observe):
        def wrapped(self, job, order, journal):
            if os.environ.get(ENV):
                Settle.look(job)
            return observe(self, job, order, journal)
        return wrapped


if __name__ == "sitecustomize":  # the overlay's sitecustomize.py is a link to this file
    install(child=True)
