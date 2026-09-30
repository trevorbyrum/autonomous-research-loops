#!/usr/bin/env python3
"""Mutation run for the gateway repairs of task 2b (the gateway's own suite).

tools/gen2_mutations.py drives the gen-2 tree; the gateway is a separate package with
its own interpreter needs (psycopg), so its guards are checked here, the same way: each
mutant in tools/gen2_gateway_mutants.py removes or weakens exactly one guard in a
temporary copy of gateway/ (never the working tree), runs the mutant's declared killers
and its paired controls in a child process on that copy, and is

  KILLED    when every killer fails (an assertion failure) and every control passes;
  SURVIVED  when no killer fails — the guard is untested;
  INVALID   when the edit is not found exactly once, a killer did not fail, a control
            did not pass, or a killer errored instead of failing (setup broke rather
            than an assertion catching the mutant).

Mutants that need the database run only when RESEARCH_GATEWAY_DSN and
RESEARCH_GATEWAY_TEST_OK=1 name a scratch database (tools/gen2_gateway_check.py
provides one); otherwise they are listed as NOT RUN and the run fails — a guard that was
not exercised is not reported as killed. Exit 0 only if every mutant is KILLED.

What a kill shows: the named tests notice the guard's absence. It does not show the
guard is the right rule, and a control passing shows only that its accepted path still
works under the mutant.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATEWAY = ROOT / "gateway"
sys.path.insert(0, str(ROOT / "tools"))
from gen2_gateway_mutants import MUTANTS  # noqa: E402

# the child: run named tests, print {test id: outcome} as one JSON line
CHILD = r'''
import json, sys, unittest
names = sys.argv[1:]
outcomes = {}
class R(unittest.TextTestResult):
    def addSuccess(self, t): outcomes[t.id()] = "pass"; super().addSuccess(t)
    def addFailure(self, t, e): outcomes[t.id()] = "fail"; super().addFailure(t, e)
    def addError(self, t, e): outcomes[getattr(t, "id", lambda: str(t))()] = "error"; super().addError(t, e)
    def addSkip(self, t, r): outcomes[t.id()] = "skip"; super().addSkip(t, r)
    def addSubTest(self, t, st, e):
        if e is not None:
            outcomes[t.id()] = "fail" if issubclass(e[0], t.failureException) else "error"
        super().addSubTest(t, st, e)
suite = unittest.defaultTestLoader.loadTestsFromNames(names)
unittest.TextTestRunner(resultclass=R, stream=open("/dev/null", "w"), verbosity=0).run(suite)
print("OUTCOMES " + json.dumps(outcomes))
'''


def have_db() -> bool:
    return bool(os.environ.get("RESEARCH_GATEWAY_DSN")) and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1"


def run_tests(tree: Path, names: list[str]) -> dict:
    proc = subprocess.run([sys.executable, "-c", CHILD, *names], cwd=tree, capture_output=True, text=True, timeout=900,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("OUTCOMES ")), None)
    if line is None:
        raise RuntimeError(f"the child printed no outcomes (exit {proc.returncode}): {proc.stderr[-2000:]}")
    return json.loads(line[len("OUTCOMES "):])


def verdict(m, tree: Path) -> tuple[str, str]:
    target = tree / m.target
    text = target.read_text(encoding="utf-8")
    if text.count(m.old) != 1:
        return "INVALID", f"the edit is found {text.count(m.old)} times in {m.target}"
    target.write_text(text.replace(m.old, m.new), encoding="utf-8")
    try:
        outcomes = run_tests(tree, [*m.killers, *m.controls])
    finally:
        target.write_text(text, encoding="utf-8")
    killers = {k: outcomes.get(k, "not run") for k in m.killers}
    controls = {c: outcomes.get(c, "not run") for c in m.controls}
    if not any(v == "fail" for v in killers.values()):
        return ("SURVIVED" if all(v == "pass" for v in killers.values()) else "INVALID"), f"killers {killers}"
    if any(v != "fail" for v in killers.values()):
        return "INVALID", f"not every killer failed in its assertions: {killers}"
    if any(v != "pass" for v in controls.values()):
        return "INVALID", f"a paired control did not pass: {controls}"
    return "KILLED", f"{len(killers)} killer(s) failed, {len(controls)} control(s) passed"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated mutant ids")
    args = ap.parse_args(argv)
    chosen = [m for m in MUTANTS if not args.only or m.mid in args.only.split(",")]
    ids = [m.mid for m in MUTANTS]
    if len(set(ids)) != len(ids):
        print("gateway mutations: duplicate mutant ids", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "gateway"
        shutil.copytree(GATEWAY, tree, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        baseline_names = sorted({n for m in chosen if not m.db or have_db() for n in (*m.killers, *m.controls)})
        base = run_tests(tree, baseline_names)
        broken = {n: o for n, o in base.items() if o != "pass"}
        missing = [n for n in baseline_names if n not in base]
        if broken or missing:
            print(f"gateway mutations: the unmutated baseline does not pass: {broken} missing {missing}", file=sys.stderr)
            return 1
        results = {"KILLED": 0, "SURVIVED": 0, "INVALID": 0, "NOT RUN": 0}
        for m in chosen:
            if m.db and not have_db():
                results["NOT RUN"] += 1
                print(f"NOT RUN   {m.mid}: needs a scratch database (RESEARCH_GATEWAY_DSN + RESEARCH_GATEWAY_TEST_OK=1)")
                continue
            v, why = verdict(m, tree)
            results[v] += 1
            print(f"{v:<9} {m.mid}: {m.description} — {why}", flush=True)
    print("gateway mutations: " + ", ".join(f"{n} {k}" for k, n in results.items()))
    return 0 if results["KILLED"] == len(chosen) else 1


if __name__ == "__main__":
    sys.exit(main())
