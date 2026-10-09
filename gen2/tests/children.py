"""How a test starts a fresh Python child (not collected as tests).

Every gen-2 test that runs gen-2 code in a child interpreter goes through
here, so that the child imports the code tree the mutation runner points it
at (task 1c: Astra's 1b-repair-2 finding that tools/gen2_mutations.py swapped
modules only in its own interpreter, while fresh children imported the
unmutated files from disk, so no kill resting on a child was real).

The tree is the repository by default. The mutation runner copies gen2/ into
a temporary directory, writes the mutant there, and names that directory in
GEN2_CHILD_ROOT; a child started through these helpers has that tree alone on
its import path, with PYTHONSAFEPATH set so that neither its working
directory nor a script's own directory is put in front of it (task 1c-repair
C1: a working directory holding another gen2/ used to win). So `-m gen2...`,
`-c "import gen2..."` and a script under gen2/ all load the mutant, whatever
working directory a caller passes; an environment that names another import
path is refused. test_children.ChildLaunchRuleTest is a narrow lint of the
literal launch it recognises; the mutation runner, not the lint, attests
which bytes a killing child executed (tools/gen2_mutations.py, "Children").

Scripts a test runs by path — the launcher and the fake executor, also
through a shell as the slow-start test does — are taken from path(), the
same tree, and inherit the test's environment. Tools run as children with an
explicit file path (tools/check_boundaries.py and the like) are not gen-2
code trees: the runner already hands their tests a mutated copy by path.
They may still import gen2 (the DDL checker imports gen2.store.compat), so
env() gives them the same import path.
"""
from __future__ import annotations

import os
import select
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT_VARIABLE = "GEN2_CHILD_ROOT"


def code_root() -> Path:
    """The tree a child imports gen2 from: the mutation runner's copy while a
    mutant is under test, the repository otherwise."""
    named = os.environ.get(ROOT_VARIABLE)
    return Path(named) if named else REPO


def path(relative: str) -> Path:
    """A file of the code tree (a script a child runs by path)."""
    return code_root() / relative


IMPORT_ROOT = ("PYTHONPATH", "PYTHONSAFEPATH")  # what fixes where a child imports gen2 from


def env(base: dict | None = None) -> dict:
    """The child's environment: the code tree alone on its import path, and
    nothing put in front of it (PYTHONSAFEPATH: not the working directory,
    not a script's directory). A caller's environment that sets either to
    something else is refused, not overridden silently."""
    wanted = {"PYTHONPATH": str(code_root()), "PYTHONSAFEPATH": "1"}  # alone: gen2 is a namespace package, and a second tree would merge into it
    if base is not None:
        conflicting = sorted(name for name in IMPORT_ROOT if name in base and base[name] != wanted[name])
        if conflicting:
            raise ValueError(f"a gen-2 child imports from the code tree alone; this environment sets {conflicting} otherwise")
    out = dict(os.environ if base is None else base)
    out.update(wanted, PYTHONDONTWRITEBYTECODE="1")
    return out


def python(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run `python <args>` from the code tree and wait for it (a working
    directory the caller passes changes nothing it imports)."""
    kwargs.setdefault("cwd", code_root())
    kwargs["env"] = env(kwargs.get("env"))
    return subprocess.run([sys.executable, *args], **kwargs)


def popen(args: list[str], **kwargs) -> subprocess.Popen:
    """Start `python <args>` from the code tree without waiting."""
    kwargs.setdefault("cwd", code_root())
    kwargs["env"] = env(kwargs.get("env"))
    return subprocess.Popen([sys.executable, *args], **kwargs)


def reap(child: subprocess.Popen, wait: float = 10.0) -> None:
    """End `child` if it still runs, wait for it, and close its pipes. Safe to call twice, and after the test collected the child itself."""
    if child.poll() is None:
        child.kill()
    try:
        child.communicate(timeout=wait)
    except (ValueError, subprocess.TimeoutExpired):   # already collected (its pipes closed), or it will not die: nothing more to do
        pass
    for pipe in (child.stdin, child.stdout, child.stderr):
        if pipe is not None and not pipe.closed:
            pipe.close()


def started(test: unittest.TestCase, args: list[str], *, ready: str | None = None, wait: float = 30.0, **kwargs) -> subprocess.Popen:
    """Start `python <args>` as a child the test owns: it is reaped when the test ends (the cleanup is registered before anything waits on
    the child, so a test that fails at its handshake leaves no process behind), its stdout and stderr are pipes unless given, and with
    `ready` the child is waited on, for at most `wait` seconds in all, to print that line first (all of it: `await_line`). A child that does not say it (it exited,
    printed something else, or said nothing in time) fails the test with what it did: its exit status, what it printed and its stderr."""
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("text", True)
    child = popen(args, **kwargs)
    test.addCleanup(reap, child)
    if ready is not None:
        await_line(test, child, ready, wait=wait)
    return child


def await_line(test: unittest.TestCase, child: subprocess.Popen, ready: str, *, wait: float = 30.0) -> None:
    """Wait for `child` to print `ready` as its next stdout line, the whole line, newline included, inside ONE deadline of `wait` seconds from the call: a line that is still partial at the
    deadline, or whose newline arrives after it, is not the child saying it (task 2b-repair-15, Astra F3: one bounded `select` and then an unbounded `readline` took a line of which the first
    byte was timely and the rest 0.5 s late, and would have waited for ever on one that never ended). Otherwise fail `test` with the child's exit status, what it printed and its stderr (the
    child gets up to 0.5 s to exit after a failed handshake, then is ended if it still runs, so there is a stderr to read). This exit wait never extends the readiness deadline.

    The line is read from the pipe's descriptor a byte at a time, so that nothing past its newline is taken from the pipe (what follows is the test's to read from `child.stdout`); this needs that
    nothing has been read from `child.stdout` before, which is so for a child just started."""
    began = time.monotonic()
    deadline, raw, fd, last = began + wait, b"", child.stdout.fileno(), began
    while not raw.endswith(b"\n"):
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            break
        more = os.read(fd, 1)
        if not more:   # EOF: the child closed its stdout inside the line, or before it
            break
        raw, last = raw + more, time.monotonic()
    line = raw.decode(errors="replace")
    if line.endswith("\n") and last <= deadline and line.strip() == ready:   # `last`: when the byte that ended it was read
        return
    # EOF can precede exit notification: a single poll can misclassify an exiting child.
    try:
        child.wait(timeout=0.5)
        running = False
    except subprocess.TimeoutExpired:
        running = True
    if running:
        child.kill()
    out, err = child.communicate(timeout=10)
    test.fail(f"the child did not say {ready!r} within {wait}s ({'still running when stopped' if running else 'it had exited'}, "
              f"waited {time.monotonic() - began:.1f}s): exit status {child.returncode}; first line {line!r}; "
              f"the rest of stdout {out!r}; stderr {err!r}")
