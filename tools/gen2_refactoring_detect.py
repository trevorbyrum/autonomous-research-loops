#!/usr/bin/env python3
"""Describe the refactorings in a commit range with RefactoringMiner (task 2q-r1; stdlib only, dev tooling).

RefactoringMiner 3.x is a Java tool that detects refactorings (extract method, move, rename, ...) between commits, Python included. Java is not installed here, so it
runs from the project's official image, PINNED BY DIGEST (IMAGE below), offline: `--network none`, the repository mounted read-only, no pull (`--pull never`). Pull it once,
by hand, before first use:

    docker pull tsantalis/refactoringminer@sha256:2d44dccea74ffcd4fa8e1fcd8cef0d29e78a52e2662d5c863b7e5e691d51e1ba

  tools/gen2_refactoring_detect.py START END [--repo DIR] [--json-out FILE] [--expect "Extract Method=5" ...]

START and END are revisions of the repository; the tool analyses START (included: the detector reports it too) through END and prints every refactoring it reports, per
commit, with the file and line of the right-hand code element. With --expect (repeatable) the TOTAL count of each named type over the range must match exactly, and a
type that is reported but not named is an unexplained refactoring: exit 1. Exit 0 = the report matches (or none was asked for), 1 = it does not, 2 = the detector could
not run (no image, git or docker failure).

What it is: a description of what changed, to be read against the diff. What it is not: a proof of behaviour. A detector reports that a statement block now lives in a new
method and is called from the old place; it does not check the helper's parameters, the order of effects, or what a name resolves to. Behaviour is the tests' and the
differential's work.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGE = "tsantalis/refactoringminer@sha256:2d44dccea74ffcd4fa8e1fcd8cef0d29e78a52e2662d5c863b7e5e691d51e1ba"
ROOT = Path(__file__).resolve().parent.parent


def docker_command(repo: Path, out_dir: Path, start: str, end: str, json_name: str, uid: int, gid: int) -> list[str]:
    """The whole container invocation: no network, no pull, a read-only root file system with a scratch /tmp, the repository read-only, only `out_dir` writable."""
    return ["docker", "run", "--rm", "--network", "none", "--pull", "never", "--read-only", "--tmpfs", "/tmp", "--user", f"{uid}:{gid}", "-e", "HOME=/tmp",
            "-v", f"{repo}:/repo:ro", "-v", f"{out_dir}:/out", IMAGE, "-bc", "/repo", start, end, "-json", f"/out/{json_name}"]


def rev(repo: Path, name: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{name}^{{commit}}"], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"gen2_refactoring_detect: {name!r} is not a commit of {repo}: {done.stderr.strip()}")
    return done.stdout.strip()


def location(refactoring: dict) -> str:
    """file:line of the right-hand code element that is the declaration (else the first one), '-' when the report has none."""
    sides = refactoring.get("rightSideLocations") or refactoring.get("leftSideLocations") or []
    decl = next((s for s in sides if "DECLARATION" in str(s.get("codeElementType"))), sides[0] if sides else None)
    return f"{decl['filePath']}:{decl['startLine']}" if decl else "-"


def summarise(report: dict) -> tuple[list[str], collections.Counter]:
    """(report lines, counts by type) of a RefactoringMiner JSON document."""
    lines, counts = [], collections.Counter()
    for commit in report.get("commits", []):
        found = commit.get("refactorings", [])
        lines.append(f"{commit['sha1'][:7]}  {len(found)} refactoring(s)")
        for refactoring in found:
            counts[refactoring["type"]] += 1
            lines.append(f"    {refactoring['type']:<22} {location(refactoring):<48} {refactoring['description'][:150]}")
    return lines, counts


def check_expected(counts: collections.Counter, expected: dict[str, int]) -> list[str]:
    """Why the report does not match the expectation: a wrong count for a named type, or a reported type nobody named."""
    problems = [f"{kind}: expected {want}, reported {counts.get(kind, 0)}" for kind, want in expected.items() if counts.get(kind, 0) != want]
    problems += [f"{kind}: {n} reported and not expected (unexplained)" for kind, n in sorted(counts.items()) if kind not in expected]
    return problems


def parse_expect(items: list[str]) -> dict[str, int]:
    expected = {}
    for item in items:
        kind, _, number = item.rpartition("=")
        if not kind or not number.isdigit():
            raise SystemExit(f"gen2_refactoring_detect: --expect wants 'Type=N', got {item!r}")
        expected[kind] = int(number)
    return expected


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("start")
    parser.add_argument("end")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--json-out", type=Path, help="keep the detector's JSON here (default: a temporary file)")
    parser.add_argument("--expect", action="append", default=[], metavar="TYPE=N")
    args = parser.parse_args(argv)
    expected = parse_expect(args.expect)
    repo = args.repo.resolve()
    start, end = rev(repo, args.start), rev(repo, args.end)
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        print(f"gen2_refactoring_detect: the pinned image is not present locally; pull it once:\n    docker pull {IMAGE}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="gen2-refactoring-detect-") as scratch:
        out_dir = Path(scratch)
        out_dir.chmod(0o777)  # the container runs as this user, but a rootless daemon maps ids differently
        done = subprocess.run(docker_command(repo, out_dir, start, end, "report.json", os.getuid(), os.getgid()), capture_output=True, text=True)
        if done.returncode != 0 or not (out_dir / "report.json").is_file():
            print(f"gen2_refactoring_detect: the detector did not run (exit {done.returncode}):\n{done.stdout}{done.stderr}", file=sys.stderr)
            return 2
        raw = (out_dir / "report.json").read_text(encoding="utf-8")
    if args.json_out:
        args.json_out.write_text(raw, encoding="utf-8")
    lines, counts = summarise(json.loads(raw))
    print(f"RefactoringMiner {IMAGE.split('@')[1][:19]}  {start[:7]}..{end[:7]}  (start commit included)")
    print("\n".join(lines))
    print("totals: " + (", ".join(f"{kind} x{n}" for kind, n in sorted(counts.items())) or "none"))
    problems = check_expected(counts, expected) if expected else []
    for problem in problems:
        print(f"MISMATCH {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
