#!/usr/bin/env python3
"""Paired positive controls for the gen-2 mutation inventory (task
1c-repair-2 C4; Astra 1c re-review C4).

A mutant's killers are the tests that must fail under it. Its paired
controls are tests that must pass under it: tests that are not its killers
and that take an accepted path through the code the mutant changes, so that
its kill is the guard's absence and not a path the mutant broke.
tools/gen2_mutations.py runs both, per mutant, and reads the controls from
tools/gen2_mutation_controls.json, which this tool writes. It is not part of
the build: it is rerun when the inventory or the tests change (the runner
refuses a mutant with no entry, and a control that is not exactly one test).

  trace    one unmutated run of the whole suite, recording per test what it
           executed (below) and whether it passed -> --trace FILE
  choose   pick each mutant's controls from a trace -> the controls file

What counts as taking a path through the mutated code, per kind of target:
  * Python: the test executes a line the mutation changes, inside a function,
    or the test of an if/while that governs a changed branch, or the start
    of a try whose handler changed (a changed refusal branch is passed
    through by deciding against it); a changed statement of a module's own
    program counts as it is, a def line (run at import) does not, and a
    changed module or class constant counts where a function reads it. Its own process is traced
    with sys.monitoring; a child it starts runs a copy that carries a
    tracing prologue (the child tree for gen2/ modules and scripts, the
    path-handed copy for a tool) and its lines are credited to the test
    running when it recorded them. Line numbers are those of the repository
    file: the prologue shares an existing line.
  * a DDL trigger: a statement that succeeds enters the trigger (its WHEN is
    evaluated), in an instrumented copy of the DDL (the store suite only —
    the DDL mutants reach no other tests).
  * a DDL table or index: a statement that succeeds writes a row of that
    table (an insert, or failing any, an update).
  * a schema file: the test declares a valid fixture of that schema (each
    such test re-checks the whole schema tree with the mutant in place).
  * a DDL trigger that refuses every statement it enters (no WHEN): nothing
    accepted passes through it, so the control writes a row of the table it
    guards, in a statement that succeeds, and says so;
  * otherwise (the connection pragmas, boundaries.toml, common.schema.json)
    by hand, in MANUAL, with the reason.
Where only a killer takes that path, it may hold its own accepted case (the
task's other route: the accepted case inside the killer): credited only
where the case also runs under the mutant — before the assertion the mutant
fails, or beside it in a subTest — as read and recorded in READ_IN_KILLER or
MANUAL; otherwise the accepted case is split out into a test of its own.
Only tests that passed in the trace are candidates, and only tests the
runner points at the mutant: a path-handed tool reaches only the module
holding its path, and a DDL mutant only the store suite. For the
supervisor's own files the canonical accepted-path tests (PREFERRED: a clean
end commits, a regular file is staged as found, ...) are taken first where
they are candidates. Otherwise candidates in a killer's class come first, then its module, then the rest; within those,
the tests that took the fewest refusal or error paths in the target (an
exception raised inside the file — a refusal, or an error it handles — or,
for the DDL, a statement that failed), then those whose names state an
accepted behaviour before those whose names state a refusal (NEGATIVE), then
the fastest in the trace; for a mutant described as over-restricting the
first two preferences are reversed (its paired control is a refusal that
must still hold). The mutation run
checks that each control passes under its mutant; `choose --run LOG` reads a
run's log, keeps each control that did not pass as rejected for that mutant
(in the file, so it stays rejected), and takes the next candidate.

What this cannot show: that the accepted path is the one the guard exists
for. A line executed on a path that ends in another refusal, which the test
expects, also counts; so does a statement that enters a trigger whose WHEN
is false for a reason other than the guard's. A mutant with no candidate is
recorded with an empty list and its reason, and the runner reports it.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "gen2" / "tests"
CONTROLS = ROOT / "tools" / "gen2_mutation_controls.json"
TOOL_ID = 3  # a sys.monitoring tool id no one else in the suite uses

# Mutants whose code the tracing cannot reach, with their controls and why.
_REAL_GRAPH = "loads the same real gen2/boundaries.toml through the checker and shows what it grants still accepted"
_IMPORTER_GRAPH = ("test_check_boundaries.BoundaryCheckerTest.test_importer_cannot_reach_a_store_under_the_real_graph",
                   _REAL_GRAPH + " (the importer's import of core)")
_ROUTER_GRAPH = ("test_check_boundaries.BoundaryCheckerTest.test_store_writes_are_the_routers_under_the_real_graph",
                 _REAL_GRAPH + " (the router's reach to the store's write primitives)")
_ORDER = "the tool's own test; no other test calls compare()"
MANUAL: dict[str, dict] = {
    # connection.sql: every store connection applies it; the control's accepted writes fire triggers under it
    "A1-recursive-triggers-off": {"controls": ["test_store_ddl.LeaseFencingTest.test_release_is_write_once"],
                                  "why": "applies the connection contract and makes accepted writes that fire triggers under it"},
    **{mid: {"controls": [_IMPORTER_GRAPH[0]], "why": _IMPORTER_GRAPH[1]}
       for mid in ("RA7-real-graph-posix", "RA7-real-graph-nt", "A8-real-graph-posixsubprocess", "A8-real-graph-imaplib",
                   "1B-real-graph-writers-widened", "1B-real-graph-primitives-dropped")},
    # the importer's test also checks _sqlite3 (it failed under this mutant): the router's instead
    **{mid: {"controls": [_ROUTER_GRAPH[0]], "why": _ROUTER_GRAPH[1]} for mid in ("IMP-graph-store-granted", "IMP-graph-sqlite-granted",
                                                                                "A8-real-graph-sqlite3")},
    # common.schema.json has no fixtures of its own: a schema that takes its connector types from it
    "0D-connector-types-open-to-a-store-name": {
        "controls": ["test_schema_counterfactuals.FixtureCounterfactualTest.test_an_extension_connector_without_its_implementation_is_refused"],
        "why": "re-checks the schema tree with the mutant in place and declares a valid export-manifest fixture, whose connectors take "
               "their type from common.schema.json"},
    # only the killer executes the changed line; its accepted case was split out as its own test (task 1c-repair-2)
    "0CR-checker-errors-collapsed-to-a-set": {
        "controls": ["test_check_ddl_rules.SchemaFixtureRuleTest.test_two_rules_reporting_one_signature_pass_when_both_are_declared"],
        "why": "executes tools/check_gen2_schemas.py line 268 on the accepted path: the two errors declared twice pass"},
    # only the killer executes the changed lines, and it asserts its paired case before the one the mutant fails
    "RA7-walrus-binds-in-comprehension": {
        "controls": [], "in_killer": ["test_check_boundaries.BoundaryCheckerTest.test_scope_resolution_witnesses"],
        "why": "the mutant over-reports (the walrus case, the killer's positive control, becomes a violation); the killer asserts its "
               "paired negatives (the class-body and global cases reported) before that; no other test reaches these lines"},
    # a race, not a removed guard: which test notices it depends on timing
    "1C-jobs-probe-takes-the-lock": {
        "controls": [],
        "why": "the mutant is a race any job start can lose (a lookup takes the lock a starting launcher needs), so whether a test that "
               "takes this path notices it depends on timing: of 13 candidates run under it, one passed in one run and failed the next; "
               "none passes dependably, so none is paired"},
    "TO-differences-ignored": {
        "controls": [], "in_killer": ["test_trigger_order_tool.TriggerOrderToolTest.test_outcomes_must_be_green_and_identical"],
        "why": "the killer asserts the accepted case (identical green outcomes: no problem) before the refusals; " + _ORDER},
    "TO-original-failures-ignored": {
        "controls": [], "in_killer": ["test_trigger_order_tool.TriggerOrderToolTest.test_outcomes_must_be_green_and_identical"],
        "why": "the killer asserts the accepted case (identical green outcomes: no problem) before the refusals; " + _ORDER},
}
# A killer the trace shows entering its trigger in a statement that succeeds, where no other test does, is credited
# with its own accepted case only once read: that statement runs before the refusal the mutant fails (or the
# refusals sit in subTests, which go on), so it also runs under the mutant.
READ_IN_KILLER = {
    "test_store_ddl.ExportOutboxTest.test_connector_watermark_never_regresses":
        "the idempotent retry UPDATE runs before the refusals, which sit in subTests; an advancing UPDATE ends the test",
    "test_store_ddl.ObservationTest.test_one_current_capability_fact_supersede_to_transition":
        "the documented supersession UPDATE (cf-1 -> cf-2) runs before the refusals",
    "test_store_ddl.OrdinalAndTriggerTest.test_trigger_identity_unique_and_handled_is_final":
        "the UPDATE marking the trigger handled runs before the refusals",
    "test_store_history.RecordIdentityTest.test_work_identity_is_immutable":
        "the refusals sit in subTests, which go on; the accepted study_group_id UPDATE then runs",
}
# For the supervisor's own files (task 1c, the review's examples): the canonical accepted-path tests, taken first
# where they qualify (they take the mutated path, passed in the trace, are not the mutant's killers).
_CLEAN_END = "test_supervisor_lifecycle.ResearchPassLifecycleTest.test_a_clean_end_commits_the_result_with_its_execution_record"
PREFERRED = {
    "gen2/supervisor/spool.py": ("test_supervisor_spool.CollectTest.test_a_regular_file_is_staged_as_found",
                                 "test_supervisor_spool.StageTest.test_bytes_are_staged_once_under_their_hash_read_only_for_one_topic", _CLEAN_END),
    "gen2/supervisor/supervisor.py": (_CLEAN_END, "test_supervisor_delegates.ResearchPassParentTest.test_a_parent_that_completes",
                                      "test_supervisor_crash.DiscoveryCrashTest.test_crash_after_launch_intent_before_any_start",
                                      "test_supervisor_crash.DiscoveryCrashTest.test_crash_after_the_identity_is_recorded"),
    "gen2/supervisor/jobs.py": ("test_supervisor_jobs.TerminateTest.test_the_whole_group_is_ended_and_confirmed_gone", _CLEAN_END),
    "gen2/supervisor/jobshim.py": ("test_supervisor_jobs.LookupTest.test_the_launcher_records_how_its_executor_ended", _CLEAN_END),
}
# A test whose name says it checks a refusal: ranked after the others, which state what is accepted.
NEGATIVE = re.compile(r"refuse|reject|_not_|_never_|cannot|_no_|fail|invalid|wrong|conflict|missing|without|stale|lost|violat|denied|unknown|"
                      r"escape|bypass|forged|foreign|ignored|outlive|exceed|_only_")

HELPER = r'''
import json, os, sys, time
def _watch(path, rel, out, at, shift):
    mon = sys.monitoring
    state = getattr(sys, "_gen2_controls_trace", None)
    if state is None:
        state = sys._gen2_controls_trace = {"files": {}, "fd": os.open(out, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)}
        def on_line(code, line):
            known = state["files"].get(code.co_filename)
            if known is None:
                return mon.DISABLE
            rel, at, shift = known
            line = line - shift if line > at else line
            os.write(state["fd"], (json.dumps({"t": time.time_ns(), "rel": rel, "line": line}) + "\n").encode())
            return mon.DISABLE
        try:
            mon.use_tool_id(4, "gen2-controls-child")
        except ValueError:
            pass
        def on_raise(code, offset, exc):
            known = state["files"].get(code.co_filename)
            if known is not None:
                os.write(state["fd"], (json.dumps({"t": time.time_ns(), "rel": known[0], "raise": 1}) + "\n").encode())
        mon.register_callback(4, mon.events.LINE, on_line)
        mon.register_callback(4, mon.events.RAISE, on_raise)
        mon.set_events(4, mon.events.LINE | mon.events.RAISE)
    state["files"][path] = (rel, at, shift)
_watch(*WATCH)
'''


# -- trace ---------------------------------------------------------------------------------------
def _inventory():
    sys.path[:0] = [str(ROOT / "tools"), str(TESTS), str(ROOT)]
    import gen2_mutations  # noqa: E402
    return gen2_mutations


def _traced_copy(text: str, path: Path, rel: str, helper: Path, out: Path) -> str:
    """The file with a prologue on its last docstring/__future__ line (so no
    line moves) that runs the tracing helper for this file."""
    body, line = ast.parse(text).body, 0
    for node in body:
        docstring = node is body[0] and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        if docstring or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            line = node.end_lineno
        else:
            break
    call = (f'__import__("runpy").run_path({str(helper)!r}, init_globals={{"WATCH": ({str(path)!r}, {rel!r}, {str(out)!r}, '
            f'{line if line else 0}, {0 if line else 1})}})')
    lines = text.splitlines(keepends=True)
    if not line:
        return call + "\n" + text
    end = lines[line - 1].rstrip("\n")
    lines[line - 1] = end + "; " + call + "\n"
    return "".join(lines)


class _Recorder(unittest.TestResult):
    def __init__(self, windows: dict, outcomes: dict, current: dict) -> None:
        super().__init__()
        self.windows, self.outcomes, self.current = windows, outcomes, current

    def startTest(self, test) -> None:  # noqa: N802
        self.current["test"] = test.id()
        self.windows[test.id()] = [time.time_ns(), None]
        self.outcomes[test.id()] = "pass"
        sys.monitoring.restart_events()
        super().startTest(test)

    def stopTest(self, test) -> None:  # noqa: N802
        self.windows[test.id()][1] = time.time_ns()
        self.current["test"] = None
        super().stopTest(test)

    def addFailure(self, test, err) -> None:  # noqa: N802
        self.outcomes[test.id()] = "fail"

    def addError(self, test, err) -> None:  # noqa: N802
        self.outcomes[test.id()] = "error"

    def addSkip(self, test, reason) -> None:  # noqa: N802
        self.outcomes[test.id()] = "skip"

    def addSubTest(self, test, subtest, err) -> None:  # noqa: N802
        if err is not None:
            self.outcomes[test.id()] = "fail"


def _ddl_instrumented(ddl: str) -> str:
    """Every trigger records that it was entered; every table records each
    row written. Both through functions _connect registers."""
    def enter(match):
        name, header = match.group(1), match.group(2)
        if "\nWHEN " in header:
            header = header.replace("\nWHEN ", f"\nWHEN _gen2_entered('{name}') AND (", 1) + "\n)"  # its own line: the WHEN may end in a comment
        else:
            header += f"\nWHEN _gen2_entered('{name}')"
        return f"CREATE TRIGGER {name}{header}\nBEGIN"
    out = re.sub(r"CREATE TRIGGER (\w+)(.*?)\nBEGIN", enter, ddl, flags=re.DOTALL)
    tables = re.findall(r"^CREATE TABLE (\w+) \(", ddl, flags=re.MULTILINE)
    for table in tables:
        out += (f"\nCREATE TRIGGER _gen2_i_{table} AFTER INSERT ON {table} BEGIN SELECT _gen2_wrote('{table}', 'insert'); END;"
                f"\nCREATE TRIGGER _gen2_u_{table} AFTER UPDATE ON {table} BEGIN SELECT _gen2_wrote('{table}', 'update'); END;\n")
    return out


def _sqlite_recording(current: dict, found: dict):
    """sqlite3.connect, recording (per test) what statements that succeed
    enter and write; a failing statement's records are dropped."""
    real = sqlite3.connect

    class Cursor(sqlite3.Cursor):
        def _run(self, method, *args, **kwargs):
            conn = self.connection
            conn._pending = []
            try:
                result = getattr(super(), method)(*args, **kwargs)
            except BaseException:
                conn._pending = []
                if current["test"] is not None:
                    found[current["test"]].add(("failed", str(len([k for k in found[current["test"]] if k[0] == "failed"]))))
                raise
            conn._flush()
            return result

        def execute(self, *a, **k):
            return self._run("execute", *a, **k)

        def executemany(self, *a, **k):
            return self._run("executemany", *a, **k)

        def executescript(self, *a, **k):
            return self._run("executescript", *a, **k)

    class Connection(sqlite3.Connection):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._pending = []
            self.create_function("_gen2_entered", 1, lambda name: self._pending.append(("trigger", name)) or 1)
            self.create_function("_gen2_wrote", 2, lambda table, op: self._pending.append((op, table)) or 1)

        def _flush(self) -> None:
            test = current["test"]
            for kind, name in self._pending:
                if test is not None:
                    found[test].add((kind, name))
            self._pending = []

        def cursor(self, factory=Cursor):
            return super().cursor(factory)

        def execute(self, *a, **k):
            return self.cursor().execute(*a, **k)

        def executemany(self, *a, **k):
            return self.cursor().executemany(*a, **k)

        def executescript(self, *a, **k):
            return self.cursor().executescript(*a, **k)

    def connect(*args, **kwargs):
        kwargs.setdefault("factory", Connection)
        return real(*args, **kwargs)
    return connect


def trace(out: Path) -> int:
    g = _inventory()
    tmp = Path(tempfile.mkdtemp(prefix="gen2-controls-"))
    helper, records = tmp / "helper.py", tmp / "lines.jsonl"
    helper.write_text(HELPER, encoding="utf-8")
    py_targets = sorted(t for t in g.FILE_TARGETS if t.endswith(".py"))
    # children: the child tree (gen2/ modules and scripts) and the path-handed tool copies carry the prologue
    tree = tmp / "tree"
    shutil.copytree(ROOT / "gen2", tree / "gen2", ignore=shutil.ignore_patterns("__pycache__"))
    copies: dict[str, str] = {}
    for rel in py_targets:
        how = g.FILE_TARGETS[rel]
        dest = tree / rel if how[0] in ("module", "disk") else tmp / "attr" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_traced_copy((ROOT / rel).read_text(encoding="utf-8"), dest, rel, helper, records), encoding="utf-8")
        copies[str(dest)] = rel
    os.environ["GEN2_CHILD_ROOT"] = str(tree)
    os.environ["GEN2_TEST_EVIDENCE"] = "off"
    sys.path[:0] = [str(TESTS), str(ROOT)]
    for rel in py_targets:
        how = g.FILE_TARGETS[rel]
        if how[0] == "attr":
            setattr(importlib.import_module(how[1]), how[2], tmp / "attr" / rel)
    # this process: the repository's files (and a path-handed copy run in here), by sys.monitoring
    files = {str(ROOT / rel): rel for rel in py_targets}
    files.update(copies)
    current: dict = {"test": None}
    lines: dict[str, set] = defaultdict(set)
    mon = sys.monitoring

    def on_line(code, line):
        rel = files.get(code.co_filename)
        if rel is None:
            return mon.DISABLE
        if current["test"] is not None:
            lines[current["test"]].add((rel, line))
        return mon.DISABLE
    raises: dict[str, dict] = defaultdict(lambda: defaultdict(int))  # per test, exceptions raised inside each target file

    def on_raise(code, offset, exc):
        rel = files.get(code.co_filename)
        if rel is not None and current["test"] is not None:
            raises[current["test"]][rel] += 1
    mon.use_tool_id(TOOL_ID, "gen2-controls")
    mon.register_callback(TOOL_ID, mon.events.LINE, on_line)
    mon.register_callback(TOOL_ID, mon.events.RAISE, on_raise)
    mon.set_events(TOOL_ID, mon.events.LINE | mon.events.RAISE)
    windows, outcomes = {}, {}
    suite = unittest.defaultTestLoader.discover(str(TESTS), pattern="test_*.py")
    started = time.monotonic()
    result = _Recorder(windows, outcomes, current)
    suite.run(result)
    mon.set_events(TOOL_ID, 0)
    print(f"traced run: {len(outcomes)} tests, {time.monotonic() - started:.0f}s; not passing: "
          f"{sorted(t for t, o in outcomes.items() if o != 'pass')}", flush=True)
    # a child's lines, to the test whose window holds them
    spans = sorted((w[0], w[1], t) for t, w in windows.items() if w[1] is not None)
    if records.exists():
        for raw in records.read_text(encoding="utf-8").splitlines():
            rec = json.loads(raw)
            for start, end, test in spans:
                if start <= rec["t"] <= end:
                    if "raise" in rec:
                        raises[test][rec["rel"]] += 1
                    else:
                        lines[test].add((rec["rel"], rec["line"]))
                    break
    # the store suite again over the instrumented DDL: triggers entered and rows written by statements that succeed
    fx = importlib.import_module("gen2.tests.store_fixtures")
    ddl0 = fx.DDL_TEXT
    fx.DDL_TEXT = _ddl_instrumented(ddl0)
    found: dict[str, set] = defaultdict(set)
    sqlite3.connect = _sqlite_recording(current, found)
    store_outcomes: dict = {}
    g.load_suite().run(_Recorder({}, store_outcomes, current))
    fx.DDL_TEXT = ddl0
    print(f"store run (instrumented DDL): {len(store_outcomes)} tests; not passing: "
          f"{sorted(t for t, o in store_outcomes.items() if o != 'pass')}", flush=True)
    durations = {t: (w[1] - w[0]) / 1e9 for t, w in windows.items() if w[1] is not None}
    doc = {"outcomes": outcomes, "durations": durations, "store_outcomes": store_outcomes,
           "lines": {t: sorted([r, n] for r, n in s) for t, s in lines.items()},
           "raises": {t: dict(d) for t, d in raises.items()},
           "sql": {t: sorted([k, n] for k, n in s) for t, s in found.items()}}
    out.write_text(json.dumps(doc), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"trace written: {out}")
    return 0


# -- choose --------------------------------------------------------------------------------------
def _span_lines(text: str, old: str) -> set[int]:
    at = text.find(old)
    first = text.count("\n", 0, at) + 1
    return set(range(first, first + old.count("\n") + (0 if old.endswith("\n") else 1)))


def evidence_lines(text: str, changed: set[int]) -> set[int]:
    """The lines whose execution takes a path through the changed code: each
    changed line inside a function body, and the test line of each if/while
    that governs one (a changed refusal branch is passed through by the test
    that decides against it) and the first line of each try whose handler
    holds one (the path through it is the try body completing); for a
    changed module or class assignment, the lines inside functions that read
    the names it binds; a changed statement of a module's own program (not a
    def, class, import or assignment) as it is. A def or class line, run at
    import, is not counted."""
    tree = ast.parse(text)
    bodies = []  # (first, last) line of each function body
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            body = node.body if isinstance(node.body, list) else [node.body]
            bodies.append((body[0].lineno, max(getattr(n, "end_lineno", n.lineno) for n in body)))
    inside = lambda n: any(a <= n <= b for a, b in bodies)
    span = lambda nodes: set().union(*(set(range(n.lineno, n.end_lineno + 1)) for n in nodes)) if nodes else set()
    keep = {n for n in changed if inside(n)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While)) and inside(node.lineno) and changed & (span(node.body) | span(node.orelse)):
            keep.update(range(node.test.lineno, node.test.end_lineno + 1))
        if isinstance(node, ast.Try) and inside(node.lineno) and changed & span(node.handlers):
            keep.add(node.body[0].lineno)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            keep |= changed & span([node])
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not inside(node.lineno) and changed & set(range(node.lineno, node.end_lineno + 1)):
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and node.id in names) or (isinstance(node, ast.Attribute) and node.attr in names):
            if inside(node.lineno):
                keep.add(node.lineno)
    return keep


def _ddl_guard(ddl: str, m) -> tuple[str, str] | None:
    """("trigger", name) or ("table", name) the mutant changes."""
    if m.drop_trigger:
        return ("trigger", m.drop_trigger)
    blocks = [(k, n, mt.start(), mt.end()) for mt in re.finditer(r"CREATE (TRIGGER|TABLE|UNIQUE INDEX|INDEX) (\w+)\b.*?(?:\nEND;\n|\) STRICT;\n|;\n)", ddl, re.DOTALL)
              for k, n in [(mt.group(1), mt.group(2))]]
    if m.scope:
        found = [b for b in blocks if b[1] == m.scope]
    else:
        at = ddl.find(m.old)
        found = [b for b in blocks if b[2] <= at < b[3]]
    if not found:
        return None
    kind, name, start, end = found[0]
    if kind == "TRIGGER":
        return ("trigger", name)
    if kind == "TABLE":
        return ("table", name)
    table = re.search(r"\bON (\w+)", ddl[start:end])
    return ("table", table.group(1)) if table else None


VERDICT = re.compile(r"^INVALID +(\S+): paired control\(s\) did not pass under the mutant: (\[.*\])$")


def _probe_one(job: tuple[str, list[str]]) -> tuple[str, dict, str | None]:
    """In a forked worker: run a mutant's killers and these candidate
    controls under it, through the runner's own mutation machinery; which
    candidates passed (a disk target's needing a child that met the mutant)."""
    mid, cands = job
    g = sys.modules["gen2_mutations"]
    m = next(x for x in g.MUTATIONS if x.mid == mid)
    g._CONTROLS = {mid: {"controls": cands}}
    fx = g._FX
    try:
        if m.target in g.FILE_TARGETS:
            res = g._run_file_mutation(m)
        else:
            ddl = g.mutate(fx.DDL_TEXT, m) if m.target == "ddl" else fx.DDL_TEXT
            conn = g.mutate(fx.CONNECTION_TEXT, m) if m.target == "connection" else fx.CONNECTION_TEXT
            res = g.run(fx, ddl, conn, (*m.killers, *cands))
    except ValueError as exc:
        return mid, {}, str(exc)
    named = g._named
    passed = {c: any(named(t, c) for t in res.ran) and not any(named(t, c) for t in (*res.failed, *res.errored, *res.skipped)) for c in cands}
    if res.tree is not None and g.FILE_TARGETS[m.target][0] == "disk":
        met = [a for a in res.attestations if a["pid"] != os.getpid() and a["test"]]
        passed = {c: ok and any(named(a["test"], c) for a in met) for c, ok in passed.items()}
    return mid, passed, None


def choose(trace_file: Path, runs: list[Path], probe_width: int = 0, jobs: int = 5, reprobe: tuple[str, ...] = ()) -> int:
    """Each mutant's controls from the trace. A control a mutation run found
    not passing under its mutant (INVALID ... paired control(s) did not pass,
    in the runs' logs) is kept in the file as rejected and never chosen for
    that mutant again. With probe_width, each mutant with a control rejected
    by those runs first has its next candidates (that many at a time, a few
    rounds) run under it, and the ones that do not pass are rejected too."""
    g = _inventory()
    tr = json.loads(trace_file.read_text(encoding="utf-8"))
    previous = json.loads(CONTROLS.read_text(encoding="utf-8")) if CONTROLS.exists() else {}
    rejected = {mid: set(e.get("rejected", ())) for mid, e in previous.items()}
    for log in runs:
        for line in log.read_text(encoding="utf-8").splitlines():
            found = VERDICT.match(line)
            if found:
                rejected.setdefault(found.group(1), set()).update(ast.literal_eval(found.group(2)))
    import gen2.tests.store_fixtures as fx
    ddl = fx.DDL_TEXT
    passing = {t for t, o in tr["outcomes"].items() if o == "pass"}
    store_passing = {t for t, o in tr["store_outcomes"].items() if o == "pass"}
    by_line: dict[tuple[str, int], set] = defaultdict(set)
    for test, pairs in tr["lines"].items():
        for rel, n in pairs:
            by_line[(rel, n)].add(test)
    by_sql: dict[tuple[str, str], set] = defaultdict(set)
    for test, pairs in tr["sql"].items():
        for kind, name in pairs:
            by_sql[(kind, name)].add(test)
    failed_sql = {t: sum(1 for k, _ in pairs if k == "failed") for t, pairs in tr["sql"].items()}

    def refusals(test: str, target: str) -> int:
        """How often the test took a refusal or error path in the target: an
        exception raised inside that file, or for the DDL a statement that
        failed. Fewer first: the accepted path is what a control is for."""
        if target in ("ddl", "connection"):
            return failed_sql.get(test, 0)
        return tr["raises"].get(test, {}).get(target, 0)
    sources: dict[str, str] = {}
    fixed, plans = {}, {}  # an entry decided without ranking; else (ranked candidates, why)
    for m in g.MUTATIONS:
        if m.mid in MANUAL:
            fixed[m.mid] = {"by_hand": True, **MANUAL[m.mid]}
            continue
        how = g.FILE_TARGETS.get(m.target)
        if m.target in ("ddl", "connection"):
            guard = _ddl_guard(ddl, m) if m.target == "ddl" else None
            if guard is None:
                cands, why = set(), "no DDL object found for this mutation"
            elif guard[0] == "trigger":
                cands, why = by_sql[guard] & store_passing, f"a statement that succeeds enters trigger {guard[1]}"
                if not cands - set(m.killers):
                    holding = sorted(set(m.killers) & by_sql[guard] & store_passing)
                    header = re.search(r"CREATE TRIGGER " + guard[1] + r"\b(.*?)\nBEGIN", ddl, re.DOTALL).group(1)
                    table = re.search(r"\bON (\w+)", header).group(1)
                    if holding and all(k in READ_IN_KILLER for k in holding):  # the killer itself holds the accepted case (read)
                        fixed[m.mid] = {"controls": [], "in_killer": holding,
                                        "why": f"no other test enters trigger {guard[1]} in a statement that succeeds; the killer does, and "
                                               f"under the mutant too: {'; '.join(READ_IN_KILLER[k] for k in holding)}"}
                        continue
                    if "\nWHEN " not in header:  # it refuses every statement it enters: nothing accepted passes through it
                        cands = by_sql[("insert", table)] & store_passing
                        why = (f"trigger {guard[1]} refuses every statement it enters (no WHEN), so no accepted path passes through it; "
                               f"the control inserts a row into {table}, the table it guards, in a statement that succeeds")
            else:
                cands, why = by_sql[("insert", guard[1])] & store_passing, f"a statement that succeeds inserts a row into {guard[1]}"
                if not cands - set(m.killers):
                    cands, why = by_sql[("update", guard[1])] & store_passing, f"a statement that succeeds updates a row of {guard[1]}"
        elif m.target.endswith(".py"):
            text = (ROOT / m.target).read_text(encoding="utf-8")
            changed = set()
            for old in [m.old, *(o for o, _ in m.also)]:
                changed |= _span_lines(text, old)
            wanted = evidence_lines(text, changed)
            cands = set().union(*(by_line[(m.target, n)] for n in wanted)) & passing if wanted else set()
            why = f"executes {m.target} line(s) {sorted(wanted)}"
            if how[0] == "attr":
                cands = {t for t in cands if t.split(".")[0] == how[1]}  # only that module is handed the mutant's path
        elif m.target.startswith("gen2/schema/") and m.target.endswith(".schema.json"):
            schema = Path(m.target).name[: -len(".schema.json")]
            module = how[1]
            if module not in sources:
                sources[module] = (TESTS / f"{module}.py").read_text(encoding="utf-8")
            declared = set(re.findall(r"def (test_\w+)\(self\) -> None:\n(?:\s*\"\"\"[\s\S]*?\"\"\"\n)?\s*self\.assertBehaveAsDeclared\(\"" + re.escape(schema) + r"\",\s*\"valid-",
                                      sources[module]))
            cands = {t for t in passing if t.split(".")[0] == module and t.rsplit(".", 1)[1] in declared}
            why = f"re-checks the schema tree and declares a valid {schema} fixture"
        else:
            cands, why = set(), f"no tracing for {m.target}"
        cands -= set(m.killers)
        classes = {k.rsplit(".", 1)[0] for k in m.killers}
        modules = {k.split(".")[0] for k in m.killers}
        preferred = PREFERRED.get(m.target, ())
        # an over-restricting mutant refuses what should be accepted: its paired control is a refusal that must still hold
        sign = -1 if "over-restrict" in m.description else 1
        rank = lambda t: (preferred.index(t) if t in preferred else len(preferred),
                          0 if t.rsplit(".", 1)[0] in classes else 1 if t.split(".")[0] in modules else 2, sign * refusals(t, m.target),
                          sign * bool(NEGATIVE.search(t.rsplit(".", 1)[1])), tr["durations"].get(t, 99.0), t)
        plans[m.mid] = (sorted(cands, key=rank), why)
    to_probe = {mid for mid in rejected if mid in plans and rejected[mid] - set(previous.get(mid, {}).get("rejected", ()))} if probe_width else set()
    to_probe |= set(reprobe)
    exhausted = {mid for mid, e in previous.items() if e.get("exhausted") and mid not in to_probe}  # probed before: none passed
    if to_probe:
        import multiprocessing
        os.environ["GEN2_TEST_EVIDENCE"] = "off"
        g._FX = importlib.import_module("gen2.tests.store_fixtures")
        for round_ in range(3):
            batch = [(mid, [c for c in plans[mid][0] if c not in rejected[mid]][:probe_width]) for mid in sorted(to_probe)]
            batch = [(mid, cands) for mid, cands in batch if cands]
            if not batch:
                break
            by_mid = {m.mid: m for m in g.MUTATIONS}
            g.unresolved_tests(t for mid, cands in batch for t in (*by_mid[mid].killers, *cands))  # imported before the fork, as the runner does
            with multiprocessing.get_context("fork").Pool(jobs, maxtasksperchild=1) as pool:
                for mid, passed, error in pool.imap_unordered(_probe_one, batch, chunksize=1):
                    rejected[mid].update(c for c, ok in passed.items() if not ok)
                    print(f"probe round {round_ + 1}: {mid}: {sum(passed.values())}/{len(passed)} candidate(s) pass under the mutant"
                          + (f" ({error})" if error else ""), flush=True)
                    if any(passed.values()):
                        to_probe.discard(mid)
        exhausted |= to_probe  # every candidate probed failed: none is chosen unverified
    out, unpaired = {}, []
    for m in g.MUTATIONS:
        if m.mid in fixed:
            out[m.mid] = fixed[m.mid]
            if set(fixed[m.mid]["controls"]) & rejected.get(m.mid, set()) or not (fixed[m.mid]["controls"] or fixed[m.mid].get("in_killer")):
                unpaired.append(m.mid)
        else:
            ranked, why = plans[m.mid]
            picked = [] if m.mid in exhausted else [c for c in ranked if c not in rejected.get(m.mid, set())][:1]
            tried = len(rejected.get(m.mid, ()))
            effect = ("an over-restricting mutant refuses the accepted path, which every test tried needs (in its case or its fixture)"
                      if "over-restrict" in m.description else "the mutant changes what the accepted path does rather than removing a refusal")
            out[m.mid] = {"controls": picked, "why": why if picked else
                          (f"all {tried} candidates run under the mutant fail ({len(ranked) - tried} of the {len(ranked)} that take the path "
                           f"were not run): {effect}" if ranked else f"no candidate: {why}")}
            if not picked and ranked:
                out[m.mid]["exhausted"] = tried
            if not picked:
                unpaired.append(m.mid)
        if rejected.get(m.mid):
            out[m.mid]["rejected"] = sorted(rejected[m.mid])
    CONTROLS.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    held = sorted(mid for mid, e in out.items() if e.get("in_killer"))
    table = sorted(mid for mid, e in out.items() if "refuses every statement" in e["why"])
    print(f"{len(out)} mutants: {len(out) - len(held) - len(unpaired)} with a paired control ({len(table)} of them a write to the table of a "
          f"trigger that refuses every statement it enters; {sum(1 for e in out.values() if e.get('by_hand') and e['controls'])} by hand), "
          f"{len(held)} whose killer holds its accepted case, {len(unpaired)} with neither: {unpaired}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("trace", "choose"))
    parser.add_argument("--trace", type=Path, required=True, help="the trace file (written by trace, read by choose)")
    parser.add_argument("--run", type=Path, action="append", default=[], help="choose: a mutation run's log, whose failing controls are rejected")
    parser.add_argument("--probe", type=int, default=0, metavar="N", help="choose: run each newly rejected mutant's next N candidates under it first")
    parser.add_argument("--reprobe", action="append", default=[], metavar="MID", help="choose, with --probe: probe this mutant's candidates again")
    args = parser.parse_args(argv)
    return trace(args.trace) if args.step == "trace" else choose(args.trace, args.run, args.probe, reprobe=tuple(args.reprobe))


if __name__ == "__main__":
    sys.exit(main())
