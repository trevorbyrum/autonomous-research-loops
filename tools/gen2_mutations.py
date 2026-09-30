#!/usr/bin/env python3
"""Mutation harness for the gen-2 store DDL and its connection contract.

Each mutation in the inventory (tools/gen2_mutants/, one module per family;
task 2r) removes or weakens exactly one guard in memory (never on disk),
reruns the guard's declared killer tests and its paired controls against the
mutant, and checks that the killers catch it while the controls still pass:

  KILLED    every test listed in `killers` fails, and every paired control
            passes. A failure is an assertion failure, or an
            sqlite3.IntegrityError raised in a test body outside setUp (a
            write the test expects to succeed was refused, i.e. the mutant
            over-restricts);
  SURVIVED  no killer fails — the guard is untested;
  INVALID   the mutation text was not found exactly once, a listed killer
            did not fail, a paired control did not pass (it failed, erred,
            was skipped or did not run), or tests errored (setup broke
            rather than an assertion catching the mutant) while some listed
            killer did not fail in its own body. Setup errors elsewhere are
            reported but tolerated when every listed killer failed in its
            body: an over-restricting mutant can also break a shared fixture.

Children (task 1c; attestation task 1c-repair, Astra 1c review C1). A
Python-module or disk target is also written into a temporary copy of the
gen2/ tree, named in GEN2_CHILD_ROOT for the run of its killers; children
started through gen2/tests/children.py import that tree alone (their import
root is fixed there, whatever working directory a caller passes). The copy
written there carries a one-line prologue: a child that executes it appends
an attestation — the test running (GEN2_ATTEST_TEST, set as each test
starts), its pid, the file, the SHA-256 of the file's bytes — to the run's
attestation file. What is checked:
  * before the killers, for a module target, a probe child started through
    the helper imports the module and must attest exactly the mutant's
    bytes (the loading control; a disk target, a script only children run,
    is checked on the killers' own children below);
  * after the killers, every attestation must name the tree's copy and the
    mutant's bytes: a child that executed other bytes of the target makes
    the mutation INVALID;
  * a kill that rests on a child — every disk target, and a module target
    marked via_child — needs, for each declared killer, an attestation from
    a child that executed the mutant during that very test; a killer that
    failed without one is not credited (INVALID).
An in-process kill needs none: the killers run in this interpreter over the
in-memory mutant. What this does not cover: a child that executes the target
and dies before its prologue runs, and tools run by explicit path ("attr"
targets), which are handed the mutated copy by path. `--no-disk` turns the
child tree off, to show what an in-memory-only run misses.

Which tests run (task 1c-repair, runtime; task 1c-repair-2 C4, Astra 1c
re-review C4): per mutant, its declared killers, which must fail, and its
paired controls, which must pass — kept apart, because a control is not
expected to fail. The controls come from tools/gen2_mutation_controls.json:
tests that are not the mutant's killers and that, in a traced unmutated run,
took an accepted path through the code the mutant changes (that tool's
docstring says what counts: for Python, a changed line itself, or the guard
directly governing a changed statement, passed where the change is a
refusal — never a branch enclosing the guard; task 1c-repair-3). A control
passing under the mutant shows the mutant left that path working; it does
not by itself show why a killer failed (that tool's docstring, "What the
rule establishes"). A killer is not assumed to hold its own accepted
case: some do, many do not. Where only a killer takes that path, the file
may instead credit the killer with its own accepted case, read and recorded
as running under the mutant too (in_killer). A mutant with no entry
in that file, a killer or control name that does not resolve to exactly one
test, a test that is both, or an in_killer test that is not its killer stops
the run; a mutant with neither is listed in the file with its reason, and
the run names it. Controls that rest
on a child (a disk target's) need a child's attestation, as killers do.
Other tests do not run under a mutant: what they would have observed is not
evidence for it (broader discovery is a separate run when the mapping
changes). The unmutated baselines run once per loading mode, not once per
target: the whole store suite (the DDL and connection mutants' baseline,
their controls included); every module and disk target's killers and
controls together over one unmutated child tree; and each path-handed
("attr") target's killers and controls over its own unmutated copy. The
whole unmutated suite runs once per build, in make gen2-test. Workers are
bounded (default: one fewer than the cores, a core left for the children the
killers start), and each verdict is printed as its worker finishes; no test
timeout is changed. How long a run takes depends on the host's load and is
not a property of the inventory: recorded runs of the same inventory before
the controls took 434 s on an idle host and 737 s and 1,219 s under load.

Exit 0 only if the unmutated baselines pass and every mutation is KILLED.
The inventory is the reviewable claim: Astra's Gate C re-runs it
(`make gen2-mutation`) instead of trusting a count. A kill proves the named
tests notice the guard's absence; it does not prove the guard is the right
rule.

Trace: task 0a-repair ("every fix must be independently mutation-testable");
Astra 0a review, "Independent mutation record".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import re
import sqlite3
import sys
import time
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "gen2" / "tests"
CONTROLS_FILE = ROOT / "tools" / "gen2_mutation_controls.json"  # written by tools/gen2_mutation_controls.py
# The inventory (task 2r): tools/gen2_mutants, beside this file, whichever way the runner is loaded (as a script,
# tools/ is already on the path; a test loads it by file).
if str(ROOT / "tools") not in sys.path:
    sys.path.append(str(ROOT / "tools"))
from gen2_mutants import MUTATIONS, SECOND_LAYER, SECOND_LAYER_TRIGGERS, Mutation  # noqa: E402 (path set above)

# File targets: how the named tests are pointed at a mutated copy. ("attr",
# module, name): the file is written to a temp dir and module.name is set to
# its path (tests that run tools as subprocesses or read config files);
# ("module", dotted): the mutated source is loaded as that module and the
# killer test modules are reloaded so their imports rebind to it, and it is
# also written into the child tree (module docstring, "Children");
# ("disk",): a file only children run (a script started by path); the
# mutant exists only in the child tree.
FILE_TARGETS = {
    "tools/check_boundaries.py": ("attr", "test_check_boundaries", "CHECKER"),
    "gen2/boundaries.toml": ("attr", "test_check_boundaries", "REAL_BOUNDARIES"),
    "tools/check_gen2_schemas.py": ("attr", "test_check_ddl_rules", "CHECKER"),
    "gen2/core/instants.py": ("module", "gen2.core.instants"),
    "gen2/core/canonical.py": ("module", "gen2.core.canonical", "gen2.router.boundary", "gen2.router.lifecycle", "gen2.router.registries", "gen2.router.amendments",
                               "gen2.router.scheduling", "gen2.router.capabilities", "gen2.router.service", "gen2.tests.router_fixtures",
                               "gen2.gateway_client.observe", "gen2.gateway_client.client"),   # capabilities, observe: gateway_fact_id (2b-repair-2)
    "gen2/store/compat.py": ("module", "gen2.store.compat"),
    "gen2/store/db.py": ("module", "gen2.store.db"),
    "gen2/store/api.py": ("module", "gen2.store.api"),
    "gen2/importer/dry_run.py": ("module", "gen2.importer.dry_run"),
    "gen2/importer/__main__.py": ("disk",),  # `python -m gen2.importer` runs it; only children do
    # task 1c. A supervisor module's dependents are reloaded over the mutant; jobshim.py runs only in children.
    "gen2/router/lifecycle.py": ("module", "gen2.router.lifecycle", "gen2.router.scheduling", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/supervisor/spool.py": ("module", "gen2.supervisor.spool", "gen2.supervisor.supervisor", "gen2.tests.supervisor_fixtures"),
    "gen2/supervisor/jobs.py": ("module", "gen2.supervisor.jobs", "gen2.supervisor.supervisor", "gen2.tests.supervisor_fixtures"),
    "gen2/supervisor/supervisor.py": ("module", "gen2.supervisor.supervisor", "gen2.app.station", "gen2.tests.supervisor_fixtures",
                                      "gen2.app.engine", "gen2.tests.operator_fixtures"),
    "gen2/supervisor/jobshim.py": ("disk",),
    "gen2/schema/execution-record.schema.json": ("attr", "test_schema_counterfactuals", "EXECUTION_RECORD_SCHEMA"),
    # task 1b. A router module's dependents (named after the dotted module) are
    # reloaded over the mutant, in order, before the killers are.
    "gen2/router/service.py": ("module", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/router/boundary.py": ("module", "gen2.router.boundary", "gen2.router.lifecycle", "gen2.router.registries", "gen2.router.amendments",
                                "gen2.router.scheduling", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/router/schemas.py": ("attr", "test_router_schemas", "VALIDATOR"),  # the oracle tool loads the mutated copy
    # task 1d: the router's mixins (their dependents reloaded after them), and the composition root
    "gen2/router/registries.py": ("module", "gen2.router.registries", "gen2.router.service", "gen2.app.station", "gen2.tests.router_fixtures"),
    "gen2/router/amendments.py": ("module", "gen2.router.amendments", "gen2.router.service", "gen2.app.station", "gen2.app.engine", "gen2.tests.router_fixtures",
                                  "gen2.tests.operator_fixtures"),
    "gen2/router/scheduling.py": ("module", "gen2.router.scheduling", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/app/station.py": ("module", "gen2.app.station"),
    # task 1e: the operator surface, the router's status read, the listener and the CLI; each dependent that bound a name
    # from the mutated module is reloaded after it, up to the operator fixtures the killers build their engine with
    "gen2/router/status.py": ("module", "gen2.router.status", "gen2.router.service", "gen2.app.station", "gen2.app.engine", "gen2.tests.router_fixtures",
                              "gen2.tests.operator_fixtures"),
    "gen2/operator/auth.py": ("module", "gen2.operator.auth", "gen2.operator.service", "gen2.app.engine", "gen2.tests.operator_fixtures"),
    "gen2/operator/status.py": ("module", "gen2.operator.status", "gen2.operator.service", "gen2.app.engine", "gen2.tests.operator_fixtures"),
    "gen2/operator/service.py": ("module", "gen2.operator.service", "gen2.app.engine", "gen2.tests.operator_fixtures"),
    "gen2/app/engine.py": ("module", "gen2.app.engine", "gen2.tests.operator_fixtures"),
    "gen2/app/cli.py": ("module", "gen2.app.cli"),
    # task 1f: the router's probe record and the supervisor's probe, their dependents reloaded after them
    "gen2/router/capabilities.py": ("module", "gen2.router.capabilities", "gen2.router.service", "gen2.app.station", "gen2.app.engine",
                                    "gen2.tests.router_fixtures", "gen2.tests.operator_fixtures"),
    "gen2/supervisor/probe.py": ("module", "gen2.supervisor.probe", "gen2.app.station", "gen2.app.engine", "gen2.tests.operator_fixtures"),
    # task 2b: the engine's gateway client; the client module binds names from observe, so it is reloaded after it
    "gen2/gateway_client/observe.py": ("module", "gen2.gateway_client.observe", "gen2.gateway_client.client"),
    "gen2/gateway_client/client.py": ("module", "gen2.gateway_client.client"),
    "tools/gen2_trigger_order.py": ("attr", "test_trigger_order_tool", "TOOL"),
    "tools/gen_source_catalog.py": ("attr", "test_source_catalog", "TOOL"),
    # A schema file: the whole schema tree is re-checked with this file replaced (0c-repair, C1).
    "gen2/schema/export-bundle.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_BUNDLE_SCHEMA"),
    "gen2/schema/export-delivery-receipt.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_RECEIPT_SCHEMA"),
    "gen2/schema/export-manifest.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_MANIFEST_SCHEMA"),
    "gen2/schema/freshness-envelope.schema.json": ("attr", "test_schema_counterfactuals", "FRESHNESS_SCHEMA"),
    "gen2/schema/common.schema.json": ("attr", "test_schema_counterfactuals", "COMMON_SCHEMA"),
    "gen2/schema/decision-receipt.schema.json": ("attr", "test_schema_counterfactuals", "DECISION_RECEIPT_SCHEMA"),
    "gen2/schema/invocation.schema.json": ("attr", "test_schema_counterfactuals", "INVOCATION_SCHEMA"),
    "tools/gen2_linecount.py": ("attr", "test_size_rules", "TOOL"),  # task 2r: the size rules
}


def uncovered_triggers(ddl: str) -> list[str]:
    """DDL triggers that no mutation drops, scopes or edits, minus the
    documented second layers. The run fails while this is non-empty, so a new
    guard cannot land without a mutant (CHECK constraints are anonymous in
    SQLite and are not enumerated here; their mutants edit their text)."""
    blocks = {m.group(1): m.group(0) for m in re.finditer(r"CREATE TRIGGER (\w+)\b.*?\nEND;\n", ddl, re.DOTALL)}
    covered: set[str] = set()
    for m in MUTATIONS:
        if m.target != "ddl":
            continue
        if m.drop_trigger:
            covered.add(m.drop_trigger)
        elif m.scope:
            if m.scope in blocks:
                covered.add(m.scope)  # a scoped edit covers its scope only, whatever else shares the text
        else:
            for old in [m.old, *(o for o, _ in m.also)]:
                if old:  # unscoped edits must match the DDL exactly once; credit the trigger holding that match
                    covered.update(name for name, body in blocks.items() if old in body and ddl.count(old) == 1)
    return sorted(set(blocks) - covered - SECOND_LAYER_TRIGGERS)


class _Collector(unittest.TestResult):
    def __init__(self) -> None:
        super().__init__()
        self.failed: set[str] = set()
        self.errored: dict[str, str] = {}
        self.attestations: list[dict] = []  # what the killers' children attested (module docstring, "Children")
        self.expected: str | None = None     # the SHA-256 of the mutant as written into the child tree
        self.tree: Path | None = None
        self.ran: set[str] = set()
        self.skipped: set[str] = set()

    def startTest(self, test) -> None:  # noqa: N802 (unittest API)
        os.environ[ATTEST_TEST] = test.id()  # inherited by every child the test starts from here on
        self.ran.add(test.id())
        super().startTest(test)

    def addSkip(self, test, reason) -> None:  # noqa: N802
        self.skipped.add(test.id())

    def addFailure(self, test, err) -> None:  # noqa: N802 (unittest API)
        self.failed.add(test.id())

    def _record_error(self, test, err) -> None:
        in_setup = any(frame.name in ("setUp", "setUpClass") for frame in traceback.extract_tb(err[2]))
        if issubclass(err[0], sqlite3.IntegrityError) and not in_setup:
            self.failed.add(test.id())
        else:
            self.errored[test.id()] = self._exc_info_to_string(err, test).strip().splitlines()[-1]

    def addError(self, test, err) -> None:  # noqa: N802
        self._record_error(test, err)

    def addSubTest(self, test, subtest, err) -> None:  # noqa: N802
        if err is None:
            return
        if issubclass(err[0], test.failureException):
            self.failed.add(test.id())
        else:
            self._record_error(test, err)


def mutate(text: str, m: Mutation) -> str:
    if m.drop_trigger:
        pattern = re.compile(r"CREATE TRIGGER " + re.escape(m.drop_trigger) + r"\b.*?\nEND;\n", re.DOTALL)
        found = pattern.findall(text)
        if len(found) != 1:
            raise ValueError(f"trigger {m.drop_trigger!r} found {len(found)} times")
        return pattern.sub("", text)
    assert m.old is not None
    prefix, body, suffix = "", text, ""
    if m.scope:
        found = list(re.finditer(r"CREATE TRIGGER " + re.escape(m.scope) + r"\b.*?\nEND;\n", text, re.DOTALL))
        found += list(re.finditer(r"CREATE TABLE " + re.escape(m.scope) + r" \(.*?\n\) STRICT;\n", text, re.DOTALL))
        if len(found) != 1:
            raise ValueError(f"scope {m.scope!r} found {len(found)} times")
        prefix, body, suffix = text[: found[0].start()], found[0].group(0), text[found[0].end():]
    for old, new in ((m.old, m.new), *m.also):
        if body.count(old) != 1:
            raise ValueError(f"mutation text found {body.count(old)} times: {old[:60]!r}")
        body = body.replace(old, new)
    return prefix + body + suffix


def load_suite() -> unittest.TestSuite:
    return unittest.defaultTestLoader.discover(str(TESTS), pattern="test_store_*.py")


def killer_suite(names, modules: dict | None = None) -> unittest.TestSuite:
    """Exactly the named tests (module.Class.method), each once, loaded from
    the given module objects where one is named (a reloaded killer module
    must be the one run), else imported."""
    import importlib

    suite = unittest.TestSuite()
    for name in dict.fromkeys(names):
        module_name, _, rest = name.partition(".")
        module = (modules or {}).get(module_name) or importlib.import_module(module_name)
        suite.addTest(unittest.defaultTestLoader.loadTestsFromName(rest, module))
    return suite


def load_controls(path: Path = CONTROLS_FILE) -> dict[str, dict]:
    """Each mutant's paired controls and why they were chosen (module
    docstring, "Which tests run")."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


_CONTROLS: dict[str, dict] = {}  # bound in main() before workers fork


def controls_of(m: Mutation, controls: dict | None = None) -> tuple[str, ...]:
    return tuple(((_CONTROLS if controls is None else controls).get(m.mid) or {}).get("controls", ()))


def control_problems(mutations, controls: dict) -> list[str]:
    """Why these mutants' paired controls cannot run: a mutant with no entry,
    a control that is also its killer, a control name that is not exactly
    one test."""
    bad = [f"{m.mid}: no entry in {CONTROLS_FILE.name}" for m in mutations if m.mid not in controls]
    bad += [f"{m.mid}: {c} is both a killer and a control" for m in mutations for c in controls_of(m, controls) if c in m.killers]
    bad += [f"{m.mid}: {k} holds the accepted case but is not its killer" for m in mutations for k in (controls.get(m.mid) or {}).get("in_killer", ())
            if k not in m.killers]
    bad += [f"control {name} is not exactly one test" for name in unresolved_tests(c for m in mutations for c in controls_of(m, controls))]
    return bad


def unresolved_killers(mutations) -> list[str]:
    """Killer names that do not resolve to exactly one test of that name."""
    return unresolved_tests(k for m in mutations for k in m.killers)


def unresolved_tests(names) -> list[str]:
    """Test names that do not resolve to exactly one test of that name."""
    def ids(suite):
        for test in suite:
            yield from ids(test) if isinstance(test, unittest.TestSuite) else [test.id()]
    bad = []
    for name in sorted(set(names)):
        try:
            found = list(ids(killer_suite([name])))
        except (ImportError, AttributeError) as exc:
            found = [repr(exc)]
        if found != [name]:
            bad.append(name)
    return bad


def run(fx, ddl: str, connection: str, killers=None) -> _Collector:
    """The store tests over this DDL and connection text: the named killers,
    or (killers None) the whole store suite."""
    fx.DDL_TEXT, fx.CONNECTION_TEXT = ddl, connection
    result = _Collector()
    (load_suite() if killers is None else killer_suite(killers)).run(result)
    return result


_FX = None  # the fixtures module, bound in main() before workers fork


DISK = True  # --no-disk clears it (module docstring, "Children")
CHILD_ROOT = "GEN2_CHILD_ROOT"  # gen2/tests/children.py ROOT_VARIABLE
ATTEST_FILE, ATTEST_TEST = "GEN2_ATTEST_FILE", "GEN2_ATTEST_TEST"
PROLOGUE = ('(lambda os, json, hashlib: os.environ.get("GEN2_ATTEST_FILE") and open(os.environ["GEN2_ATTEST_FILE"], "a").write(json.dumps('
            '{"test": os.environ.get("GEN2_ATTEST_TEST"), "pid": os.getpid(), "file": __file__, '
            '"sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest()}) + "\\n"))(__import__("os"), __import__("json"), __import__("hashlib"))'
            '  # gen2_mutations attestation\n')


def attested(text: str) -> str:
    """The mutant as written into the child tree: its prologue placed after
    the module docstring and any __future__ imports (which must stay first)."""
    import ast

    body, line = ast.parse(text).body, 0
    for node in body:
        docstring = node is body[0] and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        if docstring or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            line = node.end_lineno
        else:
            break
    lines = text.splitlines(keepends=True)
    return "".join(lines[:line]) + PROLOGUE + "".join(lines[line:])


def attestations(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _child_tree(tmp: str) -> Path:
    """A copy of the gen2/ package that children import instead of the
    repository's (no bytecode, so nothing compiled from the original is
    reused)."""
    import shutil

    tree = Path(tmp) / "tree"
    shutil.copytree(ROOT / "gen2", tree / "gen2", ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def _loading_control(tree: Path, m: Mutation, text: str) -> None:
    """Before the killers: a child started through gen2/tests/children.py, as
    the killers start theirs, must execute exactly the mutant's bytes — for a
    module target, a probe child imports it and must attest them; a disk
    target (a script only children run) must be the tree's copy, and is
    attested on the killers' own children (_evaluate). Otherwise its kills
    would not be about this mutant (ValueError: INVALID)."""
    from gen2.tests import children

    how, expected = FILE_TARGETS[m.target], hashlib.sha256(text.encode("utf-8")).hexdigest()
    if how[0] == "module":
        record = Path(os.environ[ATTEST_FILE])
        before = len(attestations(record))
        os.environ[ATTEST_TEST] = "loading-control"
        probe = children.python(["-c", f"import {how[1]}"], capture_output=True, text=True, timeout=60)
        attested_now = attestations(record)[before:]
        if probe.returncode != 0 or not any(a["sha256"] == expected and Path(a["file"]).resolve().is_relative_to(tree.resolve()) for a in attested_now):
            raise ValueError(f"loading control: a probe child did not attest the mutant in {tree} (exit {probe.returncode}, attested {attested_now})")
        return
    loaded = children.path(m.target)
    if not loaded.resolve().is_relative_to(tree.resolve()) or loaded.read_text(encoding="utf-8") != text:
        raise ValueError(f"loading control: a child runs {loaded}, not the mutant in {tree}")


def _run_file_mutation(m: Mutation) -> _Collector:
    """Mutate a Python/config file into a temp copy, point the killers' test
    modules at it, run just those modules. Runs in a forked worker (or at the
    end of a serial run), so module state it changes is not reused."""
    import importlib
    import tempfile
    import types

    text = mutate((ROOT / m.target).read_text(encoding="utf-8"), m)
    how = FILE_TARGETS[m.target]
    names = (*m.killers, *controls_of(m))
    modules = sorted({k.split(".")[0] for k in names})
    with tempfile.TemporaryDirectory() as tmp, _child_root(tmp, m, text) as tree:
        if how[0] == "disk":
            loaded = [importlib.import_module(name) for name in modules]
        elif how[0] == "attr":
            path = Path(tmp) / Path(m.target).name
            path.write_text(text, encoding="utf-8")
            loaded = [importlib.import_module(name) for name in modules]
            setattr(importlib.import_module(how[1]), how[2], path)
        else:
            mutant = types.ModuleType(how[1])
            mutant.__file__ = str((tree or ROOT) / m.target)  # file-relative paths (a script it starts) resolve in the child tree
            exec(compile(text, str(ROOT / m.target), "exec"), mutant.__dict__)
            sys.modules[how[1]] = mutant
            parent, _, leaf = how[1].rpartition(".")
            setattr(importlib.import_module(parent), leaf, mutant)
            for dependent in how[2:]:  # modules that bound names from the mutated one at import
                importlib.reload(importlib.import_module(dependent))
            loaded = [importlib.reload(importlib.import_module(name)) for name in modules]
        suite = killer_suite(names, {mod.__name__: mod for mod in loaded})
        result = _Collector()
        suite.run(result)
        if tree is not None:
            result.tree, result.expected = tree, hashlib.sha256((tree / m.target).read_bytes()).hexdigest()
            result.attestations = attestations(Path(tmp) / "attest.jsonl")
        return result


class _child_root:
    """For a module or disk target (with DISK on): the child tree with the
    mutant written in, named in GEN2_CHILD_ROOT and checked by the loading
    control; restored on exit (a serial run reuses this process). Yields the
    tree, or None when children are not redirected."""

    def __init__(self, tmp: str, m: Mutation, text: str | None) -> None:
        self.tmp, self.m, self.text = tmp, m, text

    def __enter__(self) -> Path | None:
        self.saved = {name: os.environ.get(name) for name in (CHILD_ROOT, ATTEST_FILE, ATTEST_TEST)}
        if not DISK or FILE_TARGETS[self.m.target][0] == "attr":
            return None
        tree = _child_tree(self.tmp)
        os.environ[CHILD_ROOT] = str(tree)
        os.environ[ATTEST_FILE] = str(Path(self.tmp) / "attest.jsonl")
        if self.text is not None:
            text = attested(self.text) if self.m.target.endswith(".py") else self.text
            (tree / self.m.target).write_text(text, encoding="utf-8")
            _loading_control(tree, self.m, text)
        return tree

    def __exit__(self, *exc) -> None:
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _run_file_mutation_unmutated(m: Mutation) -> _Collector:
    """The killers against the file as it is (a mutation that finds its text
    is only meaningful if they pass unmutated), in the loading mode its
    mutants use: a module or disk target over an unmutated child tree (one
    run covers every such target, main()); an "attr" target from an
    unmodified temp copy, exactly as its mutants are, so a file that only
    works from its own location (an import resolved relative to itself)
    fails here instead of letting every mutant "die" of it."""
    import importlib
    import tempfile

    modules = sorted({k.split(".")[0] for k in m.killers})
    how = FILE_TARGETS[m.target]
    with tempfile.TemporaryDirectory() as tmp, _child_root(tmp, m, None):  # children run from an unmutated copy, as the mutants' do
        loaded = [importlib.import_module(name) for name in modules]
        if how[0] == "attr":
            path = Path(tmp) / Path(m.target).name
            path.write_text((ROOT / m.target).read_text(encoding="utf-8"), encoding="utf-8")
            holder = importlib.import_module(how[1])
            original = getattr(holder, how[2])
            setattr(holder, how[2], path)
        try:
            suite = killer_suite(m.killers, {mod.__name__: mod for mod in loaded})
            result = _Collector()
            suite.run(result)
        finally:
            if how[0] == "attr":
                setattr(holder, how[2], original)
    return result


def judge_children(m: Mutation, attested: list[dict], tree: Path, expected: str, own_pid: int, controls: tuple[str, ...] = ()) -> str | None:
    """Why the killers' children do not support this mutant's kills, or None
    (module docstring, "Children"): a child that executed other bytes of the
    target, or — for a kill that rests on a child — a declared killer with no
    child that executed the mutant during it; for a disk target, whose mutant
    only children run, a paired control with none either (it would pass
    without meeting the mutant)."""
    children = [a for a in attested if a["pid"] != own_pid]
    foreign = [a for a in children if a["sha256"] != expected or not Path(a["file"]).resolve().is_relative_to(tree.resolve())]
    if foreign:
        return f"a child executed other bytes than the mutant: {foreign[0]}"
    ran_it = lambda name: any(a["test"] and _named(a["test"], name) for a in children)
    if m.via_child or FILE_TARGETS[m.target][0] == "disk":
        unattested = [k for k in m.killers if not ran_it(k)]
        if unattested:
            return f"killer(s) with no child that executed the mutant: {unattested}"
    if FILE_TARGETS[m.target][0] == "disk":
        unattested = [c for c in controls if not ran_it(c)]
        if unattested:
            return f"paired control(s) with no child that executed the mutant: {unattested}"
    return None


def _named(test_id: str, name: str) -> bool:
    return test_id == name or test_id.endswith("." + name)


def verdict(m: Mutation, res: _Collector, controls: tuple[str, ...], own_pid: int | None = None) -> str:
    """The verdict on one mutant from what its killers and its paired
    controls did under it (module docstring)."""
    missing = [k for k in m.killers if not any(_named(f, k) for f in res.failed)]
    if res.tree is not None:
        refused = judge_children(m, res.attestations, res.tree, res.expected, os.getpid() if own_pid is None else own_pid, controls)
        if refused:
            return f"INVALID   {m.mid}: {refused}"
    broken = [c for c in controls if not any(_named(t, c) for t in res.ran) or any(_named(t, c) for t in (*res.failed, *res.errored, *res.skipped))]
    if broken:
        return f"INVALID   {m.mid}: paired control(s) did not pass under the mutant: {broken}"
    if res.errored and (missing or not m.killers):
        return f"INVALID   {m.mid}: {len(res.errored)} test error(s), e.g. {next(iter(res.errored.items()))}"
    if not res.failed:
        return f"SURVIVED  {m.mid}: {m.description}"
    if missing:
        return f"INVALID   {m.mid}: listed killer(s) did not fail: {missing}"
    note = f" ({len(res.errored)} other test(s) errored in setup: the mutant also breaks a shared fixture)" if res.errored else ""
    return f"KILLED    {m.mid} by {len(res.failed)} test(s), {len(controls)} paired control(s) passing{note}"


def _evaluate(m: Mutation) -> str:
    fx = _FX
    ddl0, conn0 = fx.DDL_TEXT, fx.CONNECTION_TEXT
    try:
        if m.target in FILE_TARGETS:
            res = _run_file_mutation(m)
        else:
            ddl = mutate(ddl0, m) if m.target == "ddl" else ddl0
            conn = mutate(conn0, m) if m.target == "connection" else conn0
            try:
                res = run(fx, ddl, conn, (*m.killers, *controls_of(m)))
            finally:
                fx.DDL_TEXT, fx.CONNECTION_TEXT = ddl0, conn0
    except ValueError as exc:
        return f"INVALID   {m.mid}: {exc}"
    return verdict(m, res, controls_of(m))


def main(argv: list[str] | None = None) -> int:
    global _FX
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run only mutations whose id starts with this prefix (several: comma-separated)")
    parser.add_argument("--list", action="store_true", help="print the inventory and exit")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="worker processes (default: one fewer than the cores, one left for the killers' children)")
    parser.add_argument("--no-disk", action="store_true", help="swap modules in memory only; children import the unmutated tree (shows the 1b gap)")
    args = parser.parse_args(argv)
    global DISK
    DISK = not args.no_disk
    if args.list:
        for m in MUTATIONS:
            print(f"{m.mid:45} {m.finding:6} {m.description}")
        for guard, reason in SECOND_LAYER.items():
            print(f"second layer (not independently killable): {guard}\n    first layer: {reason}")
        return 0
    sys.path[:0] = [str(TESTS), str(ROOT)]
    os.environ["GEN2_TEST_EVIDENCE"] = "off"  # mutants fail tests on purpose: no failure evidence is kept (gen2/tests/supervisor_fixtures.py)
    import gen2.tests.store_fixtures as fx  # noqa: E402 (path set above)

    ddl0, conn0 = fx.DDL_TEXT, fx.CONNECTION_TEXT
    started = time.monotonic()
    base = run(fx, ddl0, conn0)
    if base.failed or base.errored or not base.testsRun:
        print(f"BASELINE NOT GREEN: failed={sorted(base.failed)} errored={base.errored}", file=sys.stderr)
        return 1
    selected = [m for m in MUTATIONS if not args.only or m.mid.startswith(tuple(args.only.split(",")))]
    unresolved = unresolved_killers(selected)
    if unresolved:
        print(f"UNRESOLVED KILLERS (no single test of that name): {unresolved}", file=sys.stderr)
        return 1
    global _CONTROLS
    _CONTROLS = load_controls()
    problems = control_problems(selected, _CONTROLS)
    if problems:
        print(f"PAIRED CONTROLS NOT RUNNABLE (tools/gen2_mutation_controls.py writes them): {problems}", file=sys.stderr)
        return 1
    tested = lambda m: (*m.killers, *controls_of(m))
    tree_targets = sorted({m.target for m in selected if FILE_TARGETS.get(m.target, ("",))[0] in ("module", "disk")})
    baselines = [Mutation("baseline", "-", "unmutated", tuple(k for m in selected if m.target in tree_targets for k in tested(m)), target=tree_targets[0])] \
        if tree_targets else []  # one unmutated child tree covers every module and disk target: the same loading mode
    baselines += [Mutation("baseline", "-", "unmutated", tuple(k for m in selected if m.target == target for k in tested(m)), target=target)
                  for target in sorted({m.target for m in selected if FILE_TARGETS.get(m.target, ("",))[0] == "attr"})]
    for clean in baselines:
        res = _run_file_mutation_unmutated(clean)
        if res.failed or res.errored:
            print(f"BASELINE NOT GREEN ({clean.target if FILE_TARGETS[clean.target][0] == 'attr' else 'the child tree'}): "
                  f"failed={sorted(res.failed)} errored={res.errored}", file=sys.stderr)
            return 1
    held = [m.mid for m in selected if not controls_of(m) and (_CONTROLS.get(m.mid) or {}).get("in_killer")]
    unpaired = [m.mid for m in selected if not controls_of(m) and m.mid not in held]
    print(f"gen2 mutation run: baselines green ({base.testsRun} store tests; {len(baselines)} file-target baseline(s)); "
          f"{len(selected)} mutants on {args.jobs} worker(s); {len(selected) - len(held) - len(unpaired)} with paired controls, "
          f"{len(held)} whose killer holds its accepted case, {len(unpaired)} with neither (reasons in {CONTROLS_FILE.name}): {unpaired}", flush=True)
    ids = [m.mid for m in MUTATIONS]
    if len(set(ids)) != len(ids):
        print("duplicate mutation ids", file=sys.stderr)
        return 1
    missing = uncovered_triggers(ddl0)
    if missing and not args.only:
        print(f"UNCOVERED TRIGGERS (add a mutant or document a second layer): {missing}", file=sys.stderr)
        return 1
    _FX = fx
    bad = 0

    paired = 0

    def report(verdict: str) -> None:  # as each worker finishes
        nonlocal bad, paired
        bad += not verdict.startswith("KILLED")
        paired += verdict.startswith("KILLED") and ", 0 paired control(s)" not in verdict
        print(verdict, flush=True)
    if args.jobs > 1 and len(selected) > 1:
        with multiprocessing.get_context("fork").Pool(args.jobs, maxtasksperchild=1) as pool:
            for verdict in pool.imap_unordered(_evaluate, selected, chunksize=1):
                report(verdict)
    else:
        for m in [m for m in selected if m.target not in FILE_TARGETS] + [m for m in selected if m.target in FILE_TARGETS]:  # file targets may rebind modules: last
            report(_evaluate(m))
    coverage = "" if args.only else f"every DDL trigger covered (second layers: {len(SECOND_LAYER_TRIGGERS)}), "
    print(f"gen2 mutation run: {len(selected) - bad}/{len(selected)} killed, {paired} of them with paired controls passing, "
          f"baseline {base.testsRun} tests green, {coverage}{time.monotonic() - started:.1f}s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
