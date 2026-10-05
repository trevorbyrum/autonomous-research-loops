"""Throwaway git repositories for the tests of the documentation and metrics
tools (tools/gen2_metrics.py, tools/check_gen2_debt.py,
tools/check_gen2_locators.py; task 2q-a).

A `Repo` writes literal files into a temporary directory, tracks and commits
them (the tools read `git ls-files` and, for the history report, `git log`),
and runs a tool on it as a subprocess, so what a test asserts is the tool's
exit status and what it prints. The oracles are in the tests: numbers worked
out by hand from the fixture's text, never read back from the tool.

The three tool paths are module globals read at call time:
tools/gen2_mutations.py points them at mutated copies.

A tool run is judged as a PROGRAM before a test judges what it said (task 2q-a-repair-3, Gate D #4 F4). `Repo.run` raises `ToolDidNotComplete` - never an
AssertionError - when the child crashed (a traceback), timed out, died of a signal, could not be loaded or started (an import or syntax error, an exit
status the tool never returns, an exit 2 without the tool's own message) or left no result its caller needed. A test that asserts on such a run therefore
ERRORS instead of failing, and the mutation harness does not credit an errored killer as a kill: a mutant a tool crashes on is not shown to have behaved
wrongly, only to have crashed. Every child's return code, stdout and stderr are kept (`Repo.runs`, the exception, and the JSON lines `GEN2_TOOL_RUN_LOG`
names), whatever the outcome.

A completed run needs a POSITIVE witness (task 2q-a-repair-4, Astra's 2q-a-repair-3 review F4): an exit status of 0 or 1 and the absence of a recognised traceback
prove nothing, because a child that called `os._exit(0)`, or crashed with its exception hook suppressed, looks exactly like a tool's own refusal. Each tool child
therefore runs under `LAUNCHER`, which runs the tool as `__main__` and writes a completion record - a JSON file naming the status - ONLY when the tool returns or
exits normally (`sys.exit`, a return from `main`). `Repo.run` requires that record and that its status is the process's: a child with no record is incomplete
whatever its exit status, and a tool's own refusal (exit 1, or exit 2 with its message) is a completed run because it wrote one.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "gen2_metrics.py"
DEBT_TOOL = REPO / "tools" / "check_gen2_debt.py"
LOCATORS_TOOL = REPO / "tools" / "check_gen2_locators.py"
CONTRACT_TOOL = REPO / "tools" / "gen2_source_contract.py"

BASELINE = "docs/gen2/metrics-baseline.json"
EXEMPTIONS = "docs/gen2/metrics-exemptions.md"
GIT_ENV = {"GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "test@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}   # a fixture commit never depends on the host's git configuration (signing, hooks)


TOOL_MESSAGES = ("gen2-metrics:", "gen2-locators:", "gen2-debt:")   # the line a tool prints when it refuses or cannot run: a completed exit 2 carries one
LOAD_FAILURE = re.compile(r"^(?:SyntaxError|IndentationError|TabError|ModuleNotFoundError|ImportError):", re.M)


class ToolDidNotComplete(Exception):
    """A tool subprocess did not complete as a program (module docstring). `command`, `returncode`, `stdout` and `stderr` are those of the child, kept whole."""

    def __init__(self, why: str, command: list[str], returncode: int | None, stdout: str, stderr: str) -> None:
        super().__init__(f"the tool did not complete: {why}\ncommand: {' '.join(command)}\nreturn code: {returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}")
        self.why, self.command, self.returncode, self.stdout, self.stderr = why, command, returncode, stdout, stderr


LAUNCHER = """
import json, os, runpy, sys
record, tool, *rest = sys.argv[1:]
sys.argv = [tool, *rest]
if sys.path and sys.path[0] == "":
    del sys.path[0]
sys.path.insert(0, os.path.dirname(os.path.abspath(tool)))   # the script's own directory first, as `python tool.py` has it
if not os.path.isfile(tool):
    print(f"{sys.executable}: can't open file {tool!r}: [Errno 2] No such file or directory", file=sys.stderr)
    sys.exit(2)
try:
    with open(tool, "rb") as handle:
        compile(handle.read(), tool, "exec")
except SyntaxError as bad:   # reported as the interpreter reports a script it cannot load: no traceback header
    sys.excepthook(SyntaxError, bad.with_traceback(None), None)
    sys.exit(1)
status = 0
try:
    runpy.run_path(tool, run_name="__main__")
except SystemExit as stop:
    status = stop.code
    if status is None:
        status = 0
    elif not isinstance(status, int):
        print(status, file=sys.stderr)
        status = 1
with open(record, "w", encoding="utf-8") as handle:
    json.dump({"status": status}, handle)
sys.exit(status)
"""   # the witness: the record is written only after the tool returned or exited normally, so os._exit and a suppressed crash write none


def incomplete(done: subprocess.CompletedProcess, completion: dict | None = None) -> str | None:
    """Why a finished child is not a completed run (a crash, a signal, a load failure, no completion record), or None. A tool's own refusal is a completed run."""
    if done.returncode < 0:
        return f"it was killed by signal {-done.returncode}"
    if "Traceback (most recent call last)" in (done.stdout or "") + (done.stderr or ""):
        return "it crashed with a traceback"
    if LOAD_FAILURE.search(done.stderr or ""):
        return "it could not be loaded (an import or syntax error)"
    if done.returncode not in (0, 1, 2):
        return f"it exited with status {done.returncode}, which no tool returns"
    if done.returncode == 2 and not any(prefix in (done.stderr or "") for prefix in TOOL_MESSAGES):
        return "it exited 2 without its own message (the interpreter could not start it, or the arguments were refused by argparse)"
    if completion is None:
        return "it left no completion record: it did not return or exit normally (an os._exit, or a crash whose report was suppressed)"
    if completion.get("status") != done.returncode:
        return f"its completion record says status {completion.get('status')!r} but it exited {done.returncode}"
    return None


def record_run(command: list[str], returncode: int | None, stdout: str, stderr: str, problem: str | None, completion: dict | None = None) -> None:
    log = os.environ.get("GEN2_TOOL_RUN_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"test": os.environ.get("GEN2_ATTEST_TEST"), "command": command, "returncode": returncode, "stdout": stdout, "stderr": stderr,
                                     "completion": completion, "did_not_complete": problem}) + "\n")


def run_judged(command: list[str], timeout: int, runs: list | None = None) -> subprocess.CompletedProcess:
    """Run `[python, script, *arguments]` under LAUNCHER and judge it as a program (module docstring): the finished child, kept whole in `runs` and in the run log, or
    ToolDidNotComplete. A repository-less caller (a test of the tool on the real tree) uses this directly."""
    with tempfile.TemporaryDirectory() as records:
        record = Path(records) / "completion.json"
        try:
            done = subprocess.run([command[0], "-c", LAUNCHER, str(record), *command[1:]], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            out, err = (x.decode(errors="replace") if isinstance(x, bytes) else x or "" for x in (exc.stdout, exc.stderr))
            record_run(command, None, out, err, f"timed out after {timeout} s")
            raise ToolDidNotComplete(f"it timed out after {timeout} s", command, None, out, err) from exc
        completion = json.loads(record.read_text(encoding="utf-8")) if record.exists() else None
    why = incomplete(done, completion)
    if runs is not None:
        runs.append(done)
    record_run(command, done.returncode, done.stdout, done.stderr, why, completion)
    if why:
        raise ToolDidNotComplete(why, command, done.returncode, done.stdout, done.stderr)
    return done


class Repo:
    """A temporary repository. `files` are written and committed at once; `commit` makes later changes tracked."""

    def __init__(self, files: dict[str, str] | None = None, *, commit: bool = True) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.runs: list[subprocess.CompletedProcess] = []   # every child this repository ran, whole (return code, stdout, stderr)
        self.git("init", "-q")
        self.write(files or {}, commit=commit)

    def close(self) -> None:
        self._tmp.cleanup()

    def git(self, *args: str, date: str | None = None) -> str:
        env = {**os.environ, **GIT_ENV, **({"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {})}
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, env=env, timeout=60)
        if done.returncode:
            raise RuntimeError(f"git {' '.join(args)}: {done.stderr}")
        return done.stdout

    def write(self, files: dict[str, str | None], *, commit: bool = True, message: str = "fixture", date: str | None = None) -> None:
        """Write (or, for None, delete) files; track and commit them unless commit is False."""
        for rel, text in files.items():
            path = self.root / rel
            if text is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if commit:
            self.git("add", "-A")
            self.git("commit", "-q", "--allow-empty", "-m", message, date=date)

    def run(self, *args: str, tool: Path | None = None, root: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
        """The metrics tool (or another) on this repository: `args` are the tool's, after --root. Raises ToolDidNotComplete when the child did not complete as a
        program (module docstring); what it printed and returned is otherwise the caller's to judge."""
        from gen2.tests import children
        target = tool or TOOL
        if target.is_relative_to(REPO):
            target = children.path(str(target.relative_to(REPO)))
        return run_judged([sys.executable, str(target), *(["--root", str(self.root)] if root else []), *args], timeout, self.runs)

    def baseline(self) -> dict:
        return json.loads((self.root / BASELINE).read_text())


def py(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def padding(n: int) -> str:
    """n physical lines of code that import and call nothing."""
    return "".join(f"x{i} = {i}\n" for i in range(n))


def digest_of(body: dict) -> str:
    """The baseline's digest as the tool's docstring states it: sha256 of the compact, key-sorted JSON of the body without `digest`."""
    import hashlib
    body = {k: v for k, v in body.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def rewrite_baseline(repo: Repo, edit) -> None:
    """Apply `edit(baseline_dict)` to the committed baseline and write it back with a correct digest (as a tool run would)."""
    baseline = repo.baseline()
    edit(baseline)
    if baseline["version"] == 3:
        refs = set()
        for service, data in baseline["services"].items():
            refs |= {f"{service}|file|{p}" for p in data["fan_out"]}
            refs |= {f"{service}|function|{p}" for p in data["functions"]}
            refs |= {f"{service}|self_calls|{p}" for p in data["self_calls"]}
            for kind, field in (("edge", "graph"), ("reach", "reach")):
                refs |= {f"{service}|{kind}|{a}->{b}" for a, targets in data[field].items() for b in targets}
            refs |= {f"{service}|{m}|{service}" for m in ("propagation_file", "propagation_component")}
            for kind in ("file", "component"):
                refs |= {f"{service}|cycle_{kind}|{','.join(c)}" for c in data["cycles_" + kind]}
            refs |= {f"{service}|smell_{kind}|{loc}" for kind, items in data["smells"].items() for loc in items}
        refs |= {f"repo|cross_service_import|{edge}" for edge in baseline["cross_service_imports"]}
        baseline["identities"] = {f"MI-{i:06}": ref for i, ref in enumerate(sorted(refs), 1)}
        baseline["identity_serial"] = len(refs)
    baseline["digest"] = digest_of(baseline)
    (repo.root / BASELINE).write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")


def importers(n: int, target: str, prefix: str = "gen2/imp") -> dict[str, str]:
    """n files, each importing the module `target`."""
    return {f"{prefix}{i}.py": py(f"import {target}") for i in range(n)}


def leaves(n: int, prefix: str = "gen2/leaf") -> dict[str, str]:
    return {f"{prefix}{i}.py": "v = 1\n" for i in range(n)}


def hub_files(fan_in: int, fan_out: int) -> dict[str, str]:
    """gen2/hub.py with `fan_in` importers and `fan_out` imports of its own."""
    return {"gen2/hub.py": py(*(f"import gen2.leaf{i}" for i in range(fan_out))), **importers(fan_in, "gen2.hub"), **leaves(fan_out)}


def unstable_files(a_in: int, a_out_extra: int, b_in_extra: int, b_out: int) -> dict[str, str]:
    """A imports B (that edge counts in A's fan-out and B's fan-in), plus `a_out_extra` other leaves, with `a_in` importers of A and
    `b_in_extra` further importers of B, and B importing `b_out` leaves of its own."""
    files = {"gen2/a.py": py("import gen2.b", *(f"import gen2.la{i}" for i in range(a_out_extra))),
             "gen2/b.py": py(*(f"import gen2.lb{i}" for i in range(b_out)))}
    files |= {f"gen2/la{i}.py": "v = 1\n" for i in range(a_out_extra)} | {f"gen2/lb{i}.py": "v = 1\n" for i in range(b_out)}
    files |= importers(a_in, "gen2.a", "gen2/ia") | importers(b_in_extra, "gen2.b", "gen2/ib")
    return files


def component_files(lines: int, importing_components: int) -> dict[str, str]:
    """A component gen2.big of `lines` lines, imported by that many other components."""
    return {"gen2/big/m.py": padding(lines)} | {f"gen2/user{i}/u.py": py("import gen2.big.m") for i in range(importing_components)}


def with_branches(n: int, name: str = "f") -> str:
    """A function of cyclomatic complexity n + 1 and cognitive complexity n."""
    return py(f"def {name}(a):", *(f"    if a == {i}:\n        pass" for i in range(n)))


def fixture_python(cwd: Path, code: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """What the INTERPRETER does with a fixture package, as the control of a source fixture: `code` run in a fresh Python child whose working directory is `cwd` (the fixture tree: a
    `gen2/` or `gateway/research_gateway/` package of its own is the only one it can import, the repository's is not on its path) and an environment of nothing but PATH. Not a
    gen-2 child of the repository's code tree, so it does not go through tests/children.py; a name for the executable in a variable keeps tests/test_children.py's lint, which is about
    the repository's tree, from reading it as one."""
    python = sys.executable
    return subprocess.run([python, "-c", code], cwd=cwd, env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=timeout)
