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
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "gen2_metrics.py"
DEBT_TOOL = REPO / "tools" / "check_gen2_debt.py"
LOCATORS_TOOL = REPO / "tools" / "check_gen2_locators.py"

BASELINE = "docs/gen2/metrics-baseline.json"
EXEMPTIONS = "docs/gen2/metrics-exemptions.md"
GIT_ENV = {"GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "test@example.invalid"}


class Repo:
    """A temporary repository. `files` are written and committed at once; `commit` makes later changes tracked."""

    def __init__(self, files: dict[str, str] | None = None, *, commit: bool = True) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
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

    def run(self, *args: str, tool: Path | None = None, root: bool = True) -> subprocess.CompletedProcess:
        """The metrics tool (or another) on this repository: `args` are the tool's, after --root."""
        command = [sys.executable, str(tool or TOOL), *(["--root", str(self.root)] if root else []), *args]
        return subprocess.run(command, capture_output=True, text=True, timeout=120)

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
