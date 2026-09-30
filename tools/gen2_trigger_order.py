#!/usr/bin/env python3
"""Reversed-trigger-order check for the gen-2 store DDL (a permanent CI check).

Rebuilds the store DDL (gen2/store/schema/, its parts joined in order) with
every CREATE TRIGGER moved after all other statements, in the reverse of its
original order, runs the whole store suite (gen2/tests/test_store_*.py)
against the original and against the rebuilt DDL, and fails unless both
runs are green and every test (and subtest) has the same outcome in both.

Why: where more than one guard refuses the same write, which message SQLite
reports is its trigger-firing order (observed: most recently created first;
not documented), not the invariant. 0a-repair-3 found six subtests asserting
one specific overlapping reason by running exactly this rebuild once; the
review asked for it as standing regression coverage for trigger-order
dependence (task 0b, ruling 3). It checks accept/refuse outcomes and
diagnostics alike, because the suite asserts both.

Before running, it checks the rebuild itself: the same triggers with
byte-identical SQL, the non-trigger statements unchanged and in order, and
sqlite_schema recording the triggers in exactly the reversed order. A rebuild
that silently kept the original order would otherwise pass trivially.

What it cannot show: any order other than these two; that SQLite's firing
order is creation order on every version (it is what 3.45.1 does — the
rebuild's reversal is checked in sqlite_schema, the firing order is not
observable separately).

Exit 0 only if every check passes.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "gen2" / "tests"
TRIGGER = re.compile(r"CREATE TRIGGER (\w+)\b.*?\nEND;\n", re.DOTALL)


def reverse_triggers(ddl: str) -> str:
    """The DDL with its triggers removed in place and re-created, last to
    first, after everything else."""
    blocks = [m.group(0) for m in TRIGGER.finditer(ddl)]
    rest = TRIGGER.sub("", ddl)
    return rest.rstrip("\n") + "\n\n-- triggers, in reverse creation order (tools/gen2_trigger_order.py)\n" + "\n".join(reversed(blocks))


def _schema(ddl: str, contract: str) -> tuple[list[str], dict[str, str], list[tuple[str, str, str]]]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(contract)
        conn.executescript(ddl)
        order = [r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'trigger' ORDER BY rowid")]
        sql = dict(conn.execute("SELECT name, sql FROM sqlite_schema WHERE type = 'trigger'").fetchall())
        others = conn.execute("SELECT type, name, sql FROM sqlite_schema WHERE type != 'trigger' ORDER BY rowid").fetchall()
        return order, sql, others
    finally:
        conn.close()


def check_rebuild(ddl: str, rebuilt: str, contract: str) -> list[str]:
    problems = []
    order, sql, others = _schema(ddl, contract)
    r_order, r_sql, r_others = _schema(rebuilt, contract)
    if not order:
        problems.append("the DDL has no triggers: nothing to reverse")
    if r_sql != sql:
        problems.append("the rebuild does not create the same triggers with identical SQL")
    if r_others != others:
        problems.append("the rebuild changed a non-trigger statement or its order")
    if r_order != list(reversed(order)):
        problems.append("sqlite_schema does not record the triggers in reversed creation order")
    if TRIGGER.sub("", rebuilt).rstrip("\n").split("\n\n-- triggers, in reverse creation order")[0] != TRIGGER.sub("", ddl).rstrip("\n"):
        problems.append("the rebuild changed text outside the trigger blocks")
    return problems


class _Outcomes(unittest.TestResult):
    """Outcome per test id, and per subtest (test id + its parameters)."""

    def __init__(self) -> None:
        super().__init__()
        self.outcomes: dict[str, str] = {}

    def addSuccess(self, test) -> None:  # noqa: N802 (unittest API)
        self.outcomes.setdefault(test.id(), "pass")

    def addFailure(self, test, err) -> None:  # noqa: N802
        self.outcomes[test.id()] = "fail: " + self._exc_info_to_string(err, test).strip().splitlines()[-1]

    def addError(self, test, err) -> None:  # noqa: N802
        self.outcomes[test.id()] = "error: " + self._exc_info_to_string(err, test).strip().splitlines()[-1]

    def addSkip(self, test, reason) -> None:  # noqa: N802
        self.outcomes[test.id()] = "skip: " + reason

    def addSubTest(self, test, subtest, err) -> None:  # noqa: N802
        if err is None:
            self.outcomes[subtest.id()] = "pass"
        else:
            kind = "fail" if issubclass(err[0], test.failureException) else "error"
            self.outcomes[subtest.id()] = f"{kind}: " + self._exc_info_to_string(err, test).strip().splitlines()[-1]
            self.outcomes[test.id()] = "fail: a subtest failed"


def run_suite(fx, ddl: str) -> dict[str, str]:
    original = fx.DDL_TEXT
    fx.DDL_TEXT = ddl
    try:
        result = _Outcomes()
        unittest.defaultTestLoader.discover(str(TESTS), pattern="test_store_*.py").run(result)
        return result.outcomes
    finally:
        fx.DDL_TEXT = original


def compare(normal: dict[str, str], reversed_: dict[str, str]) -> list[str]:
    problems = []
    if not normal:
        problems.append("the store suite ran no tests")
    for name, outcome in sorted(normal.items()):
        if outcome != "pass":
            problems.append(f"original order: {name}: {outcome}")
    for name in sorted(normal.keys() | reversed_.keys()):
        a, b = normal.get(name, "not run"), reversed_.get(name, "not run")
        if a != b:
            problems.append(f"reversed order differs: {name}: {a} -> {b}")
    return problems


def main() -> int:
    sys.path[:0] = [str(TESTS), str(ROOT)]
    import gen2.tests.store_fixtures as fx  # noqa: E402 (path set above)

    ddl = fx.DDL_TEXT
    rebuilt = reverse_triggers(ddl)
    problems = check_rebuild(ddl, rebuilt, fx.CONNECTION_TEXT)
    if not problems:
        normal = run_suite(fx, ddl)
        problems = compare(normal, run_suite(fx, rebuilt))
    for problem in problems:
        print(f"TRIGGER ORDER CHECK FAILURE: {problem}", file=sys.stderr)
    if problems:
        print(f"gen2 trigger-order check FAILED: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    n_triggers = len(TRIGGER.findall(ddl))
    print(f"gen2 trigger-order check OK: {n_triggers} triggers re-created in reverse order; "
          f"{len(normal)} store tests and subtests pass identically in both orders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
