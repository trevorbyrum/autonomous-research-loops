#!/usr/bin/env python3
"""Gen-2 architecture metrics and their ratchet (stdlib only; task 2q-a).

Charter "Architecture metrics" (the operator, 2026-09-30): measured from the
actual code, not the declared graph, for the engine (`gen2/`) and the gateway
(`gateway/research_gateway/`) SEPARATELY, production code only (tests,
tooling, SQL and schemas are out). The definitions are Gate D #1's
(`private/evidence/gate-d-1/measure.py` and `supplemental.py`), reproduced so
the numbers compare across reviews; where this tool differs, the text says so.

Definitions
  Files. Tracked `*.py` under `gen2/` (not `gen2/tests/`) and under
  `gateway/research_gateway/`, package `__init__.py` files included. A
  tracked file missing from the working tree is skipped.
  Import graph. One node per file. An edge A -> B when A imports module B:
  every `import` and `from ... import` in the file counts, function-local and
  `TYPE_CHECKING` imports included, relative imports resolved, and each
  `from M import x` also counts as `M.x` (a submodule). External modules,
  tests and self edges are not edges. SQL, reflection, injected protocols and
  `self.` calls are NOT edges (the collaboration measure below is for those).
  Fan-in / fan-out. Distinct files importing a file / imported by it.
  Instability. fan_out / (fan_in + fan_out); undefined (None) when isolated.
  Reach. The files reachable from a file by following edges, itself excluded.
  Propagation cost. Over all ordered pairs of the N files: (sum over files of
  1 + reach) / N^2, self-reach included. Compared as an exact fraction.
  Mean other files reached. Mean reach, self excluded.
  Components. The first two dotted segments of a module name (`gen2.router`,
  `research_gateway.core`); the component graph has an edge when a file of one
  imports a file of another. The same statistics apply to it.
  Cycles. Strongly connected sets of more than one node, at file level and at
  component level (a Python circular import and a package-layering cycle are
  different things; both are reported).
  Implicit collaboration. For every class with a project ancestor defined in
  another file - the Router and its six mixins - the `self.<method>(...)` call
  sites, in any member class, whose method is defined in another member
  class's file. The bases, the methods and each method's receiver come from the
  source facts of the supported-source contract (tools/gen2_source_index.py,
  tools/gen2_source_contract.py, docs/gen2/SOURCE-CONTRACT.md): a base is a name
  or an attribute chain followed through explicit imports and uniquely bound
  re-exports to one class (or to something outside the production inventory, an
  external terminal), and anything the contract cannot make certain - a call, a
  name bound twice or conditionally, a measured module that defines no such name,
  a star import, a conditional class or method, an alias, an unrecorded
  decorator, an inconsistent hierarchy - is REFUSED before anything is measured;
  it is never read as "no collaboration" and nothing classifies it. The method
  is resolved the way Python resolves it, through the C3 linearization of the
  family (not a depth-first walk: a diamond `D(B, C)` with `B(A)`, `C(A)` and
  `C.f` overriding `A.f` binds a call in `B` to `C.f`). A name that a property
  (a data attribute) or a modelled decorator's generated method binds first in
  that order is not a project method call. A call site is counted once however
  many families contain it, by (site, defining file). Gate D #1/#2 measured the
  Router with a fixed list of mixin names; this finds the same family without
  one (it also finds `Response(SealedAnswer)` in the gateway). `super()` calls,
  `self.<attr>.method()` and attribute reads are not counted.
  Cyclomatic proxy. 1 + one per if / ternary / for / while / except handler /
  assert, + (operands - 1) per Boolean operator, + 1 + conditions per
  comprehension generator, + one per `match` case that is not a bare `_`.
  Nested functions and classes are measured separately; lambdas not at all.
  Cognitive proxy. Per flow construct (if, ternary, for, while, except,
  `match`): 1 + its nesting depth, an `elif` not nested; per Boolean operator
  sequence: 1; per comprehension generator: 1 + depth + conditions. Not
  SonarSource's cognitive complexity: a ranking aid with the same shape.
  Both are Gate D's proxies, so they are not formal McCabe/Sonar scores.

Smells (thresholds are the DEFAULT_THRESHOLDS below, recorded in the baseline)
  Hub-like file. fan-in >= 8 and fan-out >= 6. About the 90th percentile of
  the gateway's per-file fan-in (7) and fan-out (7) and above the engine's
  95th (7 and 5); it names `adapters/base.py` (30/8), the file Gate D #1
  called the gateway's hub, and no other file at the 2q-a pin.
  Unstable dependency (Martin's Stable Dependencies Principle). An edge A -> B
  where A is clearly stable (instability <= 30%) and B is at least 10 points
  more unstable than A. The margins keep two-decimal noise out: a strict
  I(B) > I(A) flags seven edges at the 2q-a pin, four of them within 6 points.
  God component. A component of >= 3,000 physical lines (two files at the
  per-file limit) that at least 5 other components import. At the 2q-a pin it
  names `research_gateway.core` (5,187 lines, imported by 7) and nothing else;
  the next, `research_gateway.adapters`, is 3,625 lines and imported by 4.
  Function over the thresholds. Cyclomatic proxy > 20 (Gate D's "over 20"; the
  SEI "high risk" band begins at 21) or cognitive proxy > 30 (about the 97th
  percentile of the proxy at the pin, 37 functions against 46 for cyclomatic
  > 20). The two sets overlap and neither contains the other: at the 2q-a pin
  `gen2/supervisor/fake_executor.py::run` is cyclomatic 19 and cognitive 40, an
  offender by the cognitive threshold alone, so neither threshold can be
  dropped for the other (task 2q-a-repair F6 corrects an earlier claim that
  every cognitive offender at 40 and over is a cyclomatic one).
  These are operating points, not derived constants: they freeze the present
  state and stop it growing; they do not say the present state is right.

The ratchet (charter Architecture metrics; tasks 2q-a-repair-2 and -3)
  The baseline records budgets and a persistent identity registry. The ledger
  docs/gen2/metrics-ledger.md explicitly admits, maps, moves or retires
  obligations; checking, drafting and folding read one effective transition
  plan (tools/gen2_metrics_ledger.py). Missing identity is failure, never
  improvement. Maps transport old budgets before comparing both function
  scores. New file, import edge, reach gained and collaboration/function
  budgets need reasoned admission.
  Fan-out is gated for every recorded file; fan-in of a previously stable
  target includes all dependents (its blast radius), regardless of file age.
  Instability is judged by causes and direction: taking on dependencies or
  losing dependents differ (Stable Dependencies Principle). Normalised
  propagation cost and smells remain additional guards, never admissions.
  Exemptions retain reason, accepting review and removal condition; they
  cannot excuse missing identity or an unadmitted population. Rebaseline
  folds committed ledger transitions and tightens all other budgets. Improved
  functions keep both scores and their identity, even below thresholds.
  Source outside the supported-source contract is refused first, in every
  command, and no ledger entry or exemption waives it.

Subcommands (exit 0 pass, 1 regression / invalid exemption / refused source, 2
the tool could not run):
  check        the ratchet; also prints an advisory change-coupling summary
               that can never change the exit status (`make gen2-metrics`)
  admit        draft what the transition plan still lacks, with reason: TODO;
               `--move OLD NEW` states one explicit file or directory move
  rebaseline   fold ledger transitions; otherwise tighten only (`make gen2-metrics-rebaseline`)
  report DIR   every table as Gate D's CSV/JSON (file and component
               dependencies, function complexity, import edges, summary); source
               the contract refuses is shown as an incomplete, non-passing input
               (exit 1) with the tables for what could be read
  hotspots DIR the git-history report for Gate D: churn x complexity per
               file and files that change together (`make gen2-hotspots`).
               Churn is lines added + deleted by reachable commits touching
               current production files; `--no-renames`; pair coupling counts
               commits touching both files (Jaccard and conditional fractions);
               no causal claim and no elapsed-time normalization.

Trace: task 2q-a; charter "Architecture metrics" and "Root-cause fixes, not
patches"; Gate D #1 findings 5 and 6, Gate D #2 section 5.
"""
from __future__ import annotations

import argparse
import ast
import collections
import csv
import hashlib
import itertools
import json
import re
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import gen2_metrics_ledger as ledger
import gen2_source_contract as contract
from gen2_source_index import SERVICES, SERVICE_PREFIX, ToolError, absolute_module, git, is_production, module_name, production_files, Facts  # noqa: F401 (the one inventory)

EXIT_OK, EXIT_FAIL, EXIT_TOOL = 0, 1, 2
BASELINE_VERSION = 3
DEFAULT_BASELINE = "docs/gen2/metrics-baseline.json"
DEFAULT_EXEMPTIONS = "docs/gen2/metrics-exemptions.md"
GEN2_ERA = "2026-09-25"  # the first gen-2 commit date: the "gen2-era" history report excludes inherited gateway history

DEFAULT_THRESHOLDS = {
    "function_cyclomatic": 20,
    "function_cognitive": 30,
    "hub_fan_in": 8,
    "hub_fan_out": 6,
    "unstable_stable_max_pct": 30,
    "unstable_margin_pct": 10,
    "god_component_lines": 3000,
    "god_component_fan_in": 5,
}
LOOSER_IS = {  # which direction of each threshold flags fewer things
    "function_cyclomatic": "higher", "function_cognitive": "higher", "hub_fan_in": "higher", "hub_fan_out": "higher",
    "unstable_stable_max_pct": "lower", "unstable_margin_pct": "higher", "god_component_lines": "higher", "god_component_fan_in": "higher",
}
SMELL_KINDS = ("hub_like", "unstable_dependency", "god_component")
METRICS_NUMERIC = ("propagation_file", "propagation_component", "self_calls", "function_cyclomatic", "function_cognitive", "fan_out", "fan_in", "reach_gained")
METRICS_SET = ("cycle_file", "cycle_component", "cross_service_import", "smell_hub_like", "smell_unstable_dependency", "smell_god_component")
METRICS = METRICS_NUMERIC + METRICS_SET




def component_of(path: str) -> str:
    return ".".join(module_name(path).split(".")[:2])


# --- the import graph ----------------------------------------------------------------------------------------------

def import_targets(path: str, node: ast.AST) -> list[str]:
    """The dotted module names an import statement names (the base and each `base.name`), relative imports resolved."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        base = absolute_module(path, node.level, node.module)
        return [base] + [f"{base}.{alias.name}" for alias in node.names]
    return []


def build_graph(trees: dict[str, ast.Module], names: dict[str, str]) -> tuple[dict[str, set[str]], list[tuple[str, str, int]]]:
    graph: dict[str, set[str]] = {path: set() for path in trees}
    edge_lines: list[tuple[str, str, int]] = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            for target in import_targets(path, node):
                if target in names and names[target] != path:
                    graph[path].add(names[target])
                    edge_lines.append((path, names[target], node.lineno))
    return graph, edge_lines


def reach(graph: dict[str, set[str]], start: str) -> set[str]:
    found: set[str] = set()
    pending = list(graph[start])
    while pending:
        node = pending.pop()
        if node in found:
            continue
        found.add(node)
        pending.extend(graph[node] - found)
    return found - {start}


def reverse_of(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {node: set() for node in graph}
    for node, targets in graph.items():
        for target in targets:
            reverse[target].add(node)
    return reverse


def node_rows(graph: dict[str, set[str]]) -> list[dict]:
    reverse = reverse_of(graph)
    rows = []
    for node in sorted(graph):
        fan_in, fan_out = len(reverse[node]), len(graph[node])
        rows.append({"module": node, "fan_in": fan_in, "fan_out": fan_out,
                     "instability": round(fan_out / (fan_in + fan_out), 4) if fan_in + fan_out else None,
                     "out_reach": len(reach(graph, node)), "in_reach": len(reach(reverse, node))})
    return rows


def cycles_of(graph: dict[str, set[str]]) -> list[list[str]]:
    remaining, cycles = set(graph), []
    while remaining:
        node = min(remaining)
        found = reach(graph, node)
        component = {node} | {other for other in found if node in reach(graph, other)}
        remaining -= component
        if len(component) > 1:
            cycles.append(sorted(component))
    return sorted(cycles)


def graph_stats(graph: dict[str, set[str]]) -> dict:
    rows = node_rows(graph)
    return {"nodes": len(graph), "edges": sum(len(t) for t in graph.values()),
            "reach_pairs": sum(1 + row["out_reach"] for row in rows),
            "mean_other_reached": round(sum(row["out_reach"] for row in rows) / len(graph), 3) if graph else 0.0,
            "cycles": cycles_of(graph)}


def cost(stats: dict) -> Fraction:
    return Fraction(stats["reach_pairs"], stats["nodes"] ** 2) if stats["nodes"] else Fraction(0)


def component_graph(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    coarse: dict[str, set[str]] = {component_of(path): set() for path in graph}
    for path, targets in graph.items():
        coarse[component_of(path)] |= {component_of(t) for t in targets if component_of(t) != component_of(path)}
    return coarse


# --- implicit collaboration: self-calls between the classes of one inheritance family ---------------------------------

def receiver_calls(fn):
    """Every `<receiver>.<name>(...)` call in a method, its closures included, nested classes not (their `self` is another object). The contract has refused any
    method that binds its receiver's name again, so each such call is on the method's own receiver."""
    stack = list(fn.node.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.ClassDef):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == fn.receiver:
            yield node
        stack.extend(ast.iter_child_nodes(node))


def self_calls(facts: Facts, files: list[str]) -> dict:
    """{"sites": n, "pairs": {"a->b": n}, "families": {"Class (file)": {"sites": n, "pairs": {...}}}}

    A family is rooted at every class with a project ancestor defined in another file (a same-file intermediate base does not hide it). Its methods resolve
    the way Python resolves them, through the C3 order of its project classes (the contract has made every base certain and every method a direct, unconditional
    declaration). A method name is attributed to the first class in that order that declares it: as a method (any role that is callable), as a modelled
    decorator's generated method, or as a property (a data attribute: a call of it calls its value, not a project method, and nothing after it is reached). A
    call site is counted once however many families contain it: by (site, defining file), so a site that two compositions bind to different files counts once
    for each file. `families` shows each root's own view."""
    sites: set[tuple[str, int, int, str]] = set()
    families: dict[str, dict] = {}
    for path in sorted(files):
        for cls in facts.indexes[path].classes.values():
            if not any(ref[0] == "class" for _, ref in cls.bases):
                continue
            order = facts.family(cls.key)
            if not any(member[0] != path for member in order):
                continue
            defined: dict[str, tuple[str, str]] = {}   # method name -> (file of the first class in resolution order that declares it, its role)
            for member in order:
                klass = facts.classes[member]
                for name, fn in klass.methods.items():
                    defined.setdefault(name, (member[0], fn.role))
                for name in klass.generated:
                    defined.setdefault(name, (member[0], "method"))
            mine: set[tuple[str, int, int, str]] = set()
            for member in order:
                for fn in facts.classes[member].methods.values():
                    for call in receiver_calls(fn) if fn.receiver and fn.role in ("method", "property") else ():
                        owner, role = defined.get(call.func.attr, ("", "property"))   # a name no class declares is not a project method
                        if owner and role != "property" and owner != member[0]:
                            mine.add((member[0], call.lineno, call.col_offset, owner))
            sites |= mine
            families[f"{cls.qual} ({path})"] = {"sites": len(mine), "pairs": dict(sorted(collections.Counter(f"{src}->{dst}" for src, _, _, dst in mine).items()))}
    pairs = collections.Counter(f"{src}->{dst}" for src, _, _, dst in sites)
    return {"sites": len(sites), "pairs": dict(sorted(pairs.items())), "families": families}


# --- function complexity (Gate D's proxies) -----------------------------------------------------------------------------

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_FLOW = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)
_ONE_BRANCH = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.Assert)


def complexity(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, int]:
    """(cyclomatic proxy, cognitive proxy) of one function body; nested scopes and lambdas are not entered."""
    cyclomatic, cognitive = 1, 0
    stack = [(statement, 0) for statement in reversed(function.body)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, _SCOPES):
            continue
        structural = isinstance(node, _FLOW)
        if isinstance(node, _ONE_BRANCH):
            cyclomatic += 1
        if isinstance(node, ast.BoolOp):
            cyclomatic += len(node.values) - 1
            cognitive += 1
        if isinstance(node, ast.comprehension):
            cyclomatic += 1 + len(node.ifs)
            cognitive += 1 + depth + len(node.ifs)
        if isinstance(node, ast.Match):
            cyclomatic += sum(not isinstance(case.pattern, ast.MatchAs) or case.pattern.name is not None for case in node.cases)
            cognitive += 1 + depth
        if structural or isinstance(node, ast.IfExp):
            cognitive += 1 + depth
        for name, child in ast.iter_fields(node):
            for sub in child if isinstance(child, list) else [child]:
                if isinstance(sub, ast.AST):
                    inner = depth + int(structural)
                    if isinstance(node, ast.If) and name == "orelse" and isinstance(sub, ast.If):
                        inner = depth  # an `elif` is not nested
                    stack.append((sub, inner))
    return cyclomatic, cognitive


@dataclass
class Fn:
    file: str
    name: str
    line: int
    lines: int
    cyclomatic: int
    cognitive: int
    key: str = ""


def functions_of(facts: Facts) -> list[Fn]:
    """Every authored function of both services, with both scores: one lexical identity each (`file::qualified.name`), in file and source order."""
    return [Fn(fn.path, fn.qual, fn.node.lineno, fn.node.end_lineno - fn.node.lineno + 1, *complexity(fn.node), key=fn.key) for fn in facts.functions]


# --- one measurement -----------------------------------------------------------------------------------------------

@dataclass
class Measurement:
    root: Path
    thresholds: dict
    paths: dict[str, list[str]]
    texts: dict[str, str]
    graph: dict[str, set[str]]
    edge_lines: list[tuple[str, str, int]]
    functions: list[Fn]
    facts: Facts
    report: dict = field(default_factory=dict)


def production_digest(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(f"{path}\0{hashlib.sha256((root / path).read_bytes()).hexdigest()}\n".encode())
    return digest.hexdigest()


def head_commit(root: Path) -> str | None:
    try:
        return git(root, "rev-parse", "HEAD").strip() or None
    except ToolError:
        return None


def smells_of(graph: dict[str, set[str]], rows: list[dict], components: dict[str, dict], thresholds: dict) -> dict[str, list[str]]:
    by_file = {row["module"]: row for row in rows}
    hubs = sorted(row["module"] for row in rows if row["fan_in"] >= thresholds["hub_fan_in"] and row["fan_out"] >= thresholds["hub_fan_out"])
    stable_max, margin = Fraction(thresholds["unstable_stable_max_pct"], 100), Fraction(thresholds["unstable_margin_pct"], 100)

    def instability(file: str) -> Fraction | None:
        row = by_file[file]
        return Fraction(row["fan_out"], row["fan_in"] + row["fan_out"]) if row["fan_in"] + row["fan_out"] else None

    unstable = sorted(f"{a}->{b}" for a, targets in graph.items() for b in targets
                      if instability(a) is not None and instability(b) is not None
                      and instability(a) <= stable_max and instability(b) - instability(a) >= margin)
    gods = sorted(name for name, c in components.items()
                  if c["lines"] >= thresholds["god_component_lines"] and c["fan_in"] >= thresholds["god_component_fan_in"])
    return {"hub_like": hubs, "unstable_dependency": unstable, "god_component": gods}


def measure(root: Path, thresholds: dict | None = None, *, strict: bool = True) -> Measurement:
    """One measurement of both services from the facts the source contract admits. Source outside the contract is refused (`SourceRefused`) before anything is
    measured; only `report` passes strict=False, to show what it can of an input it marks incomplete and non-passing (no collaboration is measured then)."""
    thresholds = dict(DEFAULT_THRESHOLDS if thresholds is None else thresholds)
    facts = contract.load(root)
    if strict:
        contract.require(facts)
    paths = {**{service: [p for p in facts.paths[service] if p in facts.indexes] for service in SERVICES}}
    every = paths["all"] = [p for p in facts.paths["all"] if p in facts.indexes]
    texts = facts.texts
    names = {module_name(p): p for p in every}
    graph, edge_lines = build_graph({p: facts.indexes[p].tree for p in every}, names)
    functions = functions_of(facts)
    refused = {is_production(d.file) for d in facts.diagnostics}   # a service whose own source is refused is not measured for collaboration; the other still is
    services: dict[str, dict] = {}
    for service in SERVICES:
        files = paths[service]
        in_service = set(files)
        own = {p: graph[p] & in_service for p in files}  # an import into the other service is a cross-service edge, reported on its own
        coarse = component_graph(own)
        crows = {row["module"]: row for row in node_rows(coarse)}
        components = {name: {"files": sum(component_of(p) == name for p in files),
                             "lines": sum(len(texts[p].splitlines()) for p in files if component_of(p) == name),
                             "fan_in": crows[name]["fan_in"], "fan_out": crows[name]["fan_out"]} for name in sorted(coarse)}
        rows = node_rows(own)
        stats, cstats = graph_stats(own), graph_stats(coarse)
        mine = [fn for fn in functions if fn.file in own]
        offenders = {fn.key: {"cyclomatic": fn.cyclomatic, "cognitive": fn.cognitive} for fn in mine
                     if fn.cyclomatic > thresholds["function_cyclomatic"] or fn.cognitive > thresholds["function_cognitive"]}
        services[service] = {
            "files": len(files), "edges": stats["edges"],
            "propagation_file": {"reach_pairs": stats["reach_pairs"], "nodes": stats["nodes"], "mean_other_reached": stats["mean_other_reached"]},
            "propagation_component": {"reach_pairs": cstats["reach_pairs"], "nodes": cstats["nodes"], "edges": cstats["edges"],
                                      "mean_other_reached": cstats["mean_other_reached"]},
            "cycles_file": stats["cycles"], "cycles_component": cstats["cycles"],
            "components": components,
            "graph": {p: sorted(own[p]) for p in files}, "reach": {p: sorted(reach(own, p)) for p in files},
            "modules": {row["module"]: {k: row[k] for k in ("fan_in", "fan_out", "instability", "out_reach", "in_reach")} for row in rows},
            "self_calls": self_calls(facts, files) if service not in refused and None not in refused else {"sites": 0, "pairs": {}, "families": {}, "measured": False},
            "smells": smells_of(own, rows, components, thresholds),
            "functions": {"count": len(mine), "over_cyclomatic": sum(fn.cyclomatic > thresholds["function_cyclomatic"] for fn in mine),
                          "over_cyclomatic_50": sum(fn.cyclomatic > 50 for fn in mine),
                          "over_cognitive": sum(fn.cognitive > thresholds["function_cognitive"] for fn in mine),
                          "over_physical_lines_100": sum(fn.lines > 100 for fn in mine), "offenders": offenders},
        }
    cross = sorted(f"{a}->{b}" for a, targets in graph.items() for b in targets
                   if (a in paths["engine"]) != (b in paths["engine"]))
    measurement = Measurement(root, thresholds, paths, texts, graph, edge_lines, functions, facts)
    measurement.report = {"definitions": __doc__, "thresholds": thresholds, "services": services, "cross_service_imports": cross,
                          "input": {"contract": contract.CONTRACT_ID, "complete": not facts.diagnostics, "passing": not facts.diagnostics,
                                    "refusals": [d.render() for d in facts.diagnostics]},
                          "pin": {"commit": head_commit(root), "production_sha256": production_digest(root, every)}}
    return measurement


# --- the baseline --------------------------------------------------------------------------------------------------

def gated(measurement: Measurement, tracked: dict[str, set[str]] | None = None) -> dict:
    """The part of a measurement the ratchet compares: nothing else in a report is gated. `tracked` names, per service, the functions the
    baseline holds: their scores are carried in BOTH dimensions whether or not they are still over a threshold, so that a baselined
    function is compared with its baseline before the thresholds are applied (task 2q-a-repair F2). The thresholds only decide which
    OTHER functions are new offenders."""
    report, scores = measurement.report, {fn.key: fn for fn in measurement.functions}
    services = {}
    for service in SERVICES:
        s = report["services"][service]
        functions = {key: dict(value) for key, value in sorted(s["functions"]["offenders"].items())}
        for key in sorted((tracked or {}).get(service, ())):
            if key in scores:
                functions.setdefault(key, {"cyclomatic": scores[key].cyclomatic, "cognitive": scores[key].cognitive})
        services[service] = {
            "propagation_file": {"reach_pairs": s["propagation_file"]["reach_pairs"], "nodes": s["propagation_file"]["nodes"]},
            "propagation_component": {"reach_pairs": s["propagation_component"]["reach_pairs"], "nodes": s["propagation_component"]["nodes"]},
            "cycles_file": s["cycles_file"], "cycles_component": s["cycles_component"],
            "graph": s["graph"], **dependency_record(s["graph"], s["reach"]),
            "self_calls": dict(s["self_calls"]["pairs"]),
            "smells": {kind: list(s["smells"][kind]) for kind in SMELL_KINDS},
            "functions": dict(sorted(functions.items())),
            "all_functions": {fn.key: {"cyclomatic": fn.cyclomatic, "cognitive": fn.cognitive} for fn in measurement.functions if fn.file in s["graph"]},
        }
    return {"services": services, "cross_service_imports": list(report["cross_service_imports"])}


def tracked_of(baseline: dict) -> dict[str, set[str]]:
    return {service: set(baseline["services"][service]["functions"]) for service in SERVICES}


def with_digest(body: dict) -> dict:
    body = {k: v for k, v in body.items() if k != "digest"}
    body["digest"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body


def baseline_text(baseline: dict) -> str:
    return json.dumps(with_digest(baseline), indent=2, sort_keys=True) + "\n"


def load_baseline(path: Path, upgradable: bool = False) -> dict:
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"no baseline at {path}: record one with `make gen2-metrics-rebaseline` and commit it") from exc
    except (OSError, ValueError) as exc:
        raise ToolError(f"the baseline {path} cannot be read: {exc}") from exc
    if isinstance(baseline, dict) and baseline.get("version") in (1, 2) and not upgradable:
        raise ToolError(f"the baseline {path} is version {baseline['version']}, before the identity ratchet: "
                        "`make gen2-metrics-rebaseline` upgrades it, recording the import graph as it is, and the diff is committed")
    if not isinstance(baseline, dict) or baseline.get("version") not in (BASELINE_VERSION, 1, 2):
        raise ToolError(f"the baseline {path} is not version {BASELINE_VERSION}")
    if baseline.get("digest") != with_digest(baseline)["digest"]:
        raise ToolError(f"the baseline {path} does not match its own digest: it was edited by hand. "
                        "Only `make gen2-metrics-rebaseline` writes it (and only tightens); restore it from git")
    for key in DEFAULT_THRESHOLDS:
        if not isinstance(baseline.get("thresholds", {}).get(key), int):
            raise ToolError(f"the baseline {path} has no integer threshold {key}")
    if baseline["version"] == BASELINE_VERSION:
        try:
            ledger.validate_registry(baseline)
        except (ValueError, KeyError, TypeError) as exc:
            raise ToolError(str(exc)) from exc
    return baseline


def make_baseline(measurement: Measurement, thresholds: dict) -> dict:
    body = gated(measurement)
    for service in SERVICES:
        del body["services"][service]["all_functions"]
    registry = ledger.register(body)
    return {"version": BASELINE_VERSION, "pin": measurement.report["pin"], "thresholds": dict(sorted(thresholds.items())),
            "identities": registry, "identity_serial": len(registry), **body}


# --- the comparison ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Violation:
    metric: str
    where: str  # "engine", "gateway:<location>" or "repo:<location>": what an exemption names
    value: object
    baseline: object

    def describe(self) -> str:
        return f"{self.metric} {self.where}: {show(self.value)} against a baseline of {show(self.baseline)}"


def show(value: object) -> str:
    return f"{float(value):.6f}" if isinstance(value, Fraction) else str(value)


def gated_cost(entry: dict) -> Fraction:
    return Fraction(entry["reach_pairs"], entry["nodes"] ** 2) if entry["nodes"] else Fraction(0)


def inside_a_baseline_cycle(cycle: list[str], recorded: list[list[str]]) -> bool:
    return any(set(cycle) <= set(old) for old in recorded)


def dependency_regressions(service: str, old: dict, new: dict, stable_max: Fraction) -> tuple[list[Violation], list[str]]:
    """Fan-out, stable-target fan-in (all dependents), and absolute reach gained.
    Identity/admission accounting runs before these directional comparisons.
    Losing dependents differs from taking on dependencies: instability alone
    does not decide direction (Stable Dependencies Principle)."""
    survivors = set(old["fan_out"]) & set(new["fan_out"])
    violations: list[Violation] = []
    fewer = 0
    for f in sorted(survivors):
        violations += [Violation("fan_out", f"{service}:{f}", new["fan_out"][f], old["fan_out"][f])] if new["fan_out"][f] > old["fan_out"][f] else []
        fewer += new["fan_out"][f] < old["fan_out"][f]
        total = old["fan_out"][f] + old["fan_in"][f]
        if total and Fraction(old["fan_out"][f], total) <= stable_max:
            now = sum(f in new["graph"][x] for x in new["graph"])
            violations += [Violation("fan_in", f"{service}:{f}", now, old["fan_in"][f])] if now > old["fan_in"][f] else []
    pairs = lambda reached: {(x, y) for x in survivors for y in reached[x] if y in survivors}
    gained, lost = pairs(new["reach"]) - pairs(old["reach"]), pairs(old["reach"]) - pairs(new["reach"])
    violations += [Violation("reach_gained", service, len(gained), 0)] if gained else []
    return violations, [f"dependencies {service}: {fewer} file(s) with a lower fan-out and {len(lost)} reachable pair(s) gone"] if fewer or lost else []


def dependency_record(graph: dict[str, list[str]], reached: dict[str, list[str]]) -> dict:
    """What the baseline holds of a service's graph: each file's fan-out and fan-in, and the files each reaches."""
    fan_in = {f: sum(f in targets for targets in graph.values()) for f in graph}
    return {"fan_out": {f: len(t) for f, t in graph.items()}, "fan_in": fan_in, "reach": {f: sorted(r) for f, r in reached.items()}}


def compare(baseline: dict, current: dict) -> tuple[list[Violation], list[str]]:
    """Regressions of `current` (a `gated` dict) against `baseline`, and the improvements `rebaseline` would record."""
    violations: list[Violation] = []
    improvements: list[str] = []

    def where(service: str, location: str = "") -> str:
        return f"{service}:{location}" if location else service

    for service in SERVICES:
        old, new = baseline["services"][service], current["services"][service]
        for metric, key in (("propagation_file", "propagation_file"), ("propagation_component", "propagation_component")):
            was, now = gated_cost(old[key]), gated_cost(new[key])
            if now > was:
                violations.append(Violation(metric, where(service), now, was))
            elif now < was:
                improvements.append(f"{metric} {service}: {show(now)} is below the baseline {show(was)}")
        for metric, key in (("cycle_file", "cycles_file"), ("cycle_component", "cycles_component")):
            for cycle in new[key]:
                if not inside_a_baseline_cycle(cycle, old[key]):
                    violations.append(Violation(metric, where(service, ",".join(cycle)), len(cycle), 0))
            for cycle in old[key]:
                if cycle not in new[key]:
                    improvements.append(f"{metric} {service}: the baseline cycle {','.join(cycle)} is gone or smaller")
        for pair, count in new["self_calls"].items():
            was = old["self_calls"].get(pair, 0)
            if count > was:
                violations.append(Violation("self_calls", where(service, pair), count, was))
        for pair, was in old["self_calls"].items():
            if new["self_calls"].get(pair, 0) < was:
                improvements.append(f"self_calls {service}:{pair}: {new['self_calls'].get(pair, 0)} sites, baseline {was}")
        found, notes = dependency_regressions(service, old, new, Fraction(baseline["thresholds"]["unstable_stable_max_pct"], 100))
        violations += found
        improvements += notes
        for kind in SMELL_KINDS:
            for item in new["smells"][kind]:
                if item not in old["smells"][kind]:
                    violations.append(Violation(f"smell_{kind}", where(service, item), 1, 0))
            for item in old["smells"][kind]:
                if item not in new["smells"][kind]:
                    improvements.append(f"smell_{kind} {service}: {item} is gone")
        limits = baseline["thresholds"]
        pairs = (("function_cyclomatic", "cyclomatic", limits["function_cyclomatic"]), ("function_cognitive", "cognitive", limits["function_cognitive"]))
        for key, was in old["functions"].items():  # a baselined function: both dimensions against its baseline, whatever the thresholds say
            now = new["functions"].get(key)
            if now is None:
                violations.append(Violation("identity", where(service, key), "missing", "present"))
                continue
            grown = [(metric, field_) for metric, field_, _ in pairs if now[field_] > was[field_]]
            violations += [Violation(metric, where(service, key), now[field_], was[field_]) for metric, field_ in grown]
            if grown:
                continue
            if all(now[field_] <= limit for _, field_, limit in pairs):
                improvements.append(f"function {service}:{key} is no longer over the thresholds (or is gone)")
            elif now != was:
                improvements.append(f"function {service}:{key}: {now['cyclomatic']}/{now['cognitive']}, baseline {was['cyclomatic']}/{was['cognitive']}")
        for key, now in new["functions"].items():  # any other function: the thresholds decide whether it is a new offender
            if key not in old["functions"]:
                violations += [Violation(metric, where(service, key), now[field_], f"limit {limit}, not an offender")
                               for metric, field_, limit in pairs if now[field_] > limit]
    for edge in current["cross_service_imports"]:
        if edge not in baseline["cross_service_imports"]:
            violations.append(Violation("cross_service_import", f"repo:{edge}", 1, 0))
    return violations, improvements


# --- the exemptions ------------------------------------------------------------------------------------------------

@dataclass
class Exemption:
    ident: str
    fields: dict[str, str]


FIELD_ALIASES = {"accepted by": "accepted_by", "accepted_by": "accepted_by", "metric": "metric", "location": "location", "limit": "limit",
                 "reason": "reason", "removal": "removal"}
PLACEHOLDER = re.compile(r"^\W*(todo|tbd|n/?a|none|nil|unknown|\?+|-+|x+)\W*$", re.IGNORECASE)
REVIEW_CITATION = re.compile(r"\d{4}-\d{2}-\d{2}|\.md\b|Gate D\s*#\d+", re.IGNORECASE)


def parse_entries(text: str, heading: str, aliases: dict[str, str]) -> tuple[list[Exemption], list[str]]:
    """Entries are `### <ID> ...` sections of `- key: value` lines (a continuation is indented two spaces); fenced blocks are skipped."""
    entries: list[Exemption] = []
    errors: list[str] = []
    current: Exemption | None = None
    last_key = ""
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = re.match(rf"^### ({heading}[\w.-]*)\b", line)
        if match:
            current = Exemption(match.group(1), {})
            entries.append(current)
            last_key = ""
            continue
        if line.startswith("#"):
            current = None
            continue
        if current is None:
            continue
        field_match = re.match(r"^- ([A-Za-z_ ]+?):\s*(.*)$", line)
        if field_match:
            key = aliases.get(field_match.group(1).strip().lower().replace("_", " ")) or aliases.get(field_match.group(1).strip().lower())
            if key is None:
                errors.append(f"{current.ident} (line {number}): unknown field {field_match.group(1)!r}")
                last_key = ""
                continue
            if key in current.fields:
                errors.append(f"{current.ident} (line {number}): field {key} given twice")
            current.fields[key] = field_match.group(2).strip()
            last_key = key
        elif line.startswith("  ") and line.strip() and last_key:
            current.fields[last_key] = (current.fields[last_key] + " " + line.strip()).strip()
    return entries, errors


def exemption_problems(entry: Exemption) -> list[str]:
    fields, problems = entry.fields, []
    for key in ("metric", "location", "reason", "accepted_by", "removal"):
        if not fields.get(key) or PLACEHOLDER.match(fields[key]):
            problems.append(f"{entry.ident}: field {key} is missing or a placeholder")
    metric = fields.get("metric", "")
    if metric and metric not in METRICS:
        problems.append(f"{entry.ident}: metric {metric!r} is not one of {', '.join(METRICS)}")
    if fields.get("accepted_by") and not PLACEHOLDER.match(fields["accepted_by"]) and not REVIEW_CITATION.search(fields["accepted_by"]):
        problems.append(f"{entry.ident}: accepted_by must cite the accepting review (a report file name, a date, or `Gate D #n`)")
    if fields.get("removal") and not PLACEHOLDER.match(fields["removal"]) and len(fields["removal"]) < 15:
        problems.append(f"{entry.ident}: removal must state a condition, not a word")
    if metric in METRICS_NUMERIC:
        limit = fields.get("limit", "")
        try:
            Fraction(limit) if metric.startswith("propagation") else int(limit)
        except (ValueError, ZeroDivisionError):
            problems.append(f"{entry.ident}: {metric} is a number, so `limit` (the highest value accepted) is required"
                            + (" as a decimal" if metric.startswith("propagation") else " as an integer"))
    elif metric in METRICS_SET and fields.get("limit"):
        problems.append(f"{entry.ident}: {metric} names one instance, so it takes no `limit`")
    return problems


def apply_exemptions(violations: list[Violation], text: str | None) -> tuple[list[Violation], list[str], list[str]]:
    """(violations left, notes for the exempted ones, errors: invalid, duplicate or unused exemptions)"""
    if text is None:
        return violations, [], []
    entries, errors = parse_entries(text, "EX-", FIELD_ALIASES)
    valid: list[Exemption] = []
    for entry in entries:
        problems = exemption_problems(entry)
        errors.extend(problems)
        if not problems:
            valid.append(entry)
    seen: dict[tuple[str, str], str] = {}
    for entry in valid:
        key = (entry.fields["metric"], entry.fields["location"])
        if key in seen:
            errors.append(f"{entry.ident}: duplicates {seen[key]} (same metric and location)")
        seen[key] = entry.ident
    used: set[str] = set()
    left: list[Violation] = []
    notes: list[str] = []
    for violation in violations:
        entry = None if violation.metric in ("identity", "admission") else next((e for e in valid if (e.fields["metric"], e.fields["location"]) == (violation.metric, violation.where)), None)
        if entry is None:
            left.append(violation)
            continue
        used.add(entry.ident)
        if violation.metric in METRICS_NUMERIC:
            limit = Fraction(entry.fields["limit"]) if violation.metric.startswith("propagation") else int(entry.fields["limit"])
            if violation.value > limit:
                left.append(Violation(violation.metric, violation.where, violation.value,
                                      f"{violation.baseline} (exemption {entry.ident} accepts up to {entry.fields['limit']})"))
                continue
        notes.append(f"exempted by {entry.ident}: {violation.describe()}")
    for entry in valid:
        if entry.ident not in used:
            errors.append(f"{entry.ident}: no regression needs this exemption (metric {entry.fields['metric']}, location "
                          f"{entry.fields['location']}): remove it")
    return left, notes, errors


# --- rebaseline: tighten only --------------------------------------------------------------------------------------

def tighten(baseline: dict, at_old: dict, at_new: dict, limits: dict) -> dict:
    """The new gated content: `at_old` and `at_new` are measurements under the baseline's thresholds and the (possibly tighter) new ones,
    `limits` the new thresholds."""
    services = {}
    for service in SERVICES:
        old, was, now = baseline["services"][service], at_old["services"][service], at_new["services"][service]
        out: dict = {}
        for key in ("propagation_file", "propagation_component"):
            out[key] = min((old[key], now[key]), key=gated_cost)
        for key in ("cycles_file", "cycles_component"):
            out[key] = [cycle for cycle in now[key] if inside_a_baseline_cycle(cycle, old[key])]
        out["graph"] = {f: list(t) for f, t in now["graph"].items()}
        out["self_calls"] = {pair: min(count, old["self_calls"][pair]) for pair, count in now["self_calls"].items() if pair in old["self_calls"]}
        survivors = set(old["fan_out"]) & set(now["fan_out"])  # a record of a file that existed is only ever lowered; one that touches a new file is recorded as it is
        out["fan_out"] = {f: min(n, old["fan_out"][f]) if f in survivors else n for f, n in now["fan_out"].items()}
        out["fan_in"] = {f: min(sum(f in now["graph"][x] for x in now["graph"]), old["fan_in"][f])
                         if f in survivors and old["fan_in"][f] + old["fan_out"][f] and
                         Fraction(old["fan_out"][f], old["fan_in"][f] + old["fan_out"][f]) <= Fraction(limits["unstable_stable_max_pct"], 100)
                         else n for f, n in now["fan_in"].items()}
        out["reach"] = {f: sorted(t for t in targets if not (f in survivors and t in survivors) or t in old["reach"][f]) for f, targets in now["reach"].items()}
        out["smells"] = {}
        for kind in SMELL_KINDS:  # kept: baselined, or newly flagged only because a threshold got tighter (not a regression)
            out["smells"][kind] = [item for item in now["smells"][kind] if item in old["smells"][kind] or item not in was["smells"][kind]]
        out["functions"] = {}
        for key, value in now["functions"].items():
            if key in old["functions"]:
                kept = {f: min(value[f], old["functions"][key][f]) for f in ("cyclomatic", "cognitive")}
                grown = any(value[f] > old["functions"][key][f] for f in kept)  # an exempted growth: never recorded, and the entry stays
                out["functions"][key] = kept  # identity persists below thresholds
            elif key not in was["functions"]:
                out["functions"][key] = dict(value)
        services[service] = out
    return {"services": services, "cross_service_imports": [e for e in at_new["cross_service_imports"] if e in baseline["cross_service_imports"]]}


def tighter_thresholds(old: dict, tool: dict) -> dict:
    result = {}
    for key, was in old.items():
        mine = tool.get(key, was)
        result[key] = min(was, mine) if LOOSER_IS[key] == "higher" else max(was, mine)
    return result


# --- reports -------------------------------------------------------------------------------------------------------

COLUMNS = {
    "file-dependencies.csv": ["module", "fan_in", "fan_out", "instability", "out_reach", "in_reach"],
    "component-dependencies.csv": ["module", "fan_in", "fan_out", "instability", "out_reach", "in_reach"],
    "function-complexity.csv": ["file", "function", "line", "physical_lines", "cyclomatic_proxy", "cognitive_proxy"],
    "change-hotspots.csv": ["file", "commits", "added_plus_deleted", "max_function_cc", "churn_times_cc", "physical_lines"],
    "change-coupling.csv": ["file_a", "file_b", "joint_commits", "a_commits", "b_commits", "jaccard", "p_b_given_a", "p_a_given_b"],
    "change-hotspots-gen2-era.csv": ["file", "commits", "added_plus_deleted", "max_function_cc", "churn_times_cc"],
    "change-coupling-gen2-era.csv": ["file_a", "file_b", "joint_commits", "a_commits", "b_commits", "jaccard"],
}


def write_table(path: Path, rows: list[dict]) -> None:
    with path.open("w") as handle:  # Gate D's writer, so a CSV of the same measurement is the same bytes
        writer = csv.DictWriter(handle, fieldnames=COLUMNS[path.name])
        writer.writeheader()
        writer.writerows(rows)


def write_report(measurement: Measurement, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    report = measurement.report
    rows, crows = [], []
    for service in SERVICES:
        in_service = set(measurement.paths[service])
        own = {p: measurement.graph[p] & in_service for p in measurement.paths[service]}
        rows += node_rows(own)
        crows += node_rows(component_graph(own))
    write_table(out / "file-dependencies.csv", sorted(rows, key=lambda r: r["module"]))
    write_table(out / "component-dependencies.csv", sorted(crows, key=lambda r: r["module"]))
    write_table(out / "function-complexity.csv", [
        {"file": fn.file, "function": fn.name, "line": fn.line, "physical_lines": fn.lines, "cyclomatic_proxy": fn.cyclomatic, "cognitive_proxy": fn.cognitive}
        for fn in sorted(measurement.functions, key=lambda f: (-f.cyclomatic, -f.cognitive))])
    (out / "import-edges.json").write_text(json.dumps(sorted(set(map(tuple, measurement.edge_lines))), indent=2) + "\n")
    shown = json.loads(json.dumps(report))
    for service in SERVICES:
        shown["services"][service]["functions"]["offenders"] = dict(sorted(shown["services"][service]["functions"]["offenders"].items()))
    (out / "metrics-summary.json").write_text(json.dumps(shown, indent=2, sort_keys=True) + "\n")


def history_commits(root: Path) -> tuple[str, list[dict]]:
    text = git(root, "log", "--format=@@%H %aI %s", "--numstat", "--no-renames", "HEAD", "--", "gen2", "gateway/research_gateway")
    commits: list[dict] = []
    current = None
    for line in text.splitlines():
        if line.startswith("@@"):
            current = {"header": line[2:], "numstat": []}
            commits.append(current)
        elif line and current is not None:
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                current["numstat"].append((parts[2], int(parts[0]), int(parts[1])))
    return text, commits


def hotspot_tables(measurement: Measurement, commits: list[dict]) -> dict[str, list[dict]]:
    production = set(measurement.paths["engine"]) | set(measurement.paths["gateway"])
    order = measurement.paths["all"]
    max_cc: collections.defaultdict = collections.defaultdict(int)
    for fn in measurement.functions:
        max_cc[fn.file] = max(max_cc[fn.file], fn.cyclomatic)

    def tally(selected: list[dict]):
        freq: collections.Counter = collections.Counter()
        churn: collections.Counter = collections.Counter()
        pairs: collections.Counter = collections.Counter()
        for commit in selected:
            files = {path: (added, deleted) for path, added, deleted in commit["numstat"] if path in production}
            freq.update(files.keys())
            churn.update({p: sum(v) for p, v in files.items()})
            pairs.update(itertools.combinations(sorted(files), 2))
        return freq, churn, pairs

    freq, churn, pairs = tally(commits)
    era = [c for c in commits if c["header"].split()[1][:10] >= GEN2_ERA]
    efreq, echurn, epairs = tally(era)
    lines = {p: len(measurement.texts[p].splitlines()) for p in production}
    return {
        "change-hotspots.csv": [{"file": p, "commits": freq[p], "added_plus_deleted": churn[p], "max_function_cc": max_cc[p],
                                 "churn_times_cc": churn[p] * max_cc[p], "physical_lines": lines[p]}
                                for p in sorted(order, key=lambda p: -churn[p] * max_cc[p])],
        "change-coupling.csv": [{"file_a": a, "file_b": b, "joint_commits": n, "a_commits": freq[a], "b_commits": freq[b],
                                 "jaccard": round(n / (freq[a] + freq[b] - n), 4), "p_b_given_a": round(n / freq[a], 4),
                                 "p_a_given_b": round(n / freq[b], 4)} for (a, b), n in pairs.most_common()],
        "change-hotspots-gen2-era.csv": [{"file": p, "commits": efreq[p], "added_plus_deleted": echurn[p], "max_function_cc": max_cc[p],
                                          "churn_times_cc": echurn[p] * max_cc[p]} for p in sorted(order, key=lambda p: -echurn[p] * max_cc[p])],
        "change-coupling-gen2-era.csv": [{"file_a": a, "file_b": b, "joint_commits": n, "a_commits": efreq[a], "b_commits": efreq[b],
                                          "jaccard": round(n / (efreq[a] + efreq[b] - n), 4)} for (a, b), n in epairs.most_common()],
    }


def advisory_hotspots(measurement: Measurement, top: int = 6) -> list[str]:
    """A few lines of the gen2-era history report; any failure to read history returns nothing and never changes the exit status."""
    try:
        _, commits = history_commits(measurement.root)
        tables = hotspot_tables(measurement, commits)
    except (ToolError, KeyError, ValueError, ZeroDivisionError):
        return ["history report: unavailable here (no reachable history); advisory only"]
    lines = ["change hotspots since " + GEN2_ERA + " (churn x highest function cyclomatic; advisory, never gates):"]
    for row in tables["change-hotspots-gen2-era.csv"][:top]:
        lines.append(f"  {row['file']}: {row['commits']} commits, churn {row['added_plus_deleted']}, max CC {row['max_function_cc']}, score {row['churn_times_cc']}")
    coupled = [r for r in tables["change-coupling-gen2-era.csv"] if r["joint_commits"] >= 5]
    lines.append("files that change together since " + GEN2_ERA + " (Jaccard, at least 5 joint commits; advisory, never gates):")
    for row in sorted(coupled, key=lambda r: (-r["jaccard"], -r["joint_commits"]))[:top]:
        lines.append(f"  {row['file_a']} + {row['file_b']}: {row['joint_commits']} joint of {row['a_commits']}/{row['b_commits']}, Jaccard {row['jaccard']}")
    return lines


def write_hotspots(measurement: Measurement, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    history, commits = history_commits(measurement.root)
    (out / "git-production-history.txt").write_text(history)
    tables = hotspot_tables(measurement, commits)
    for name, rows in tables.items():
        write_table(out / name, rows)
    summary = {"definitions": __doc__, "commits_in_log": len(commits), "commits_with_production_changes": sum(bool(c["numstat"]) for c in commits),
               "latest": commits[0]["header"] if commits else None, "oldest": commits[-1]["header"] if commits else None}
    (out / "hotspots-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


# --- the commands --------------------------------------------------------------------------------------------------

def summary_lines(report: dict) -> list[str]:
    lines = []
    for service in SERVICES:
        s = report["services"][service]
        lines.append(
            f"{service}: {s['files']} files, {s['edges']} edges, propagation {float(gated_cost(s['propagation_file'])):.4%} "
            f"(components {float(gated_cost(s['propagation_component'])):.4%}), file cycles {len(s['cycles_file'])}, component cycles {len(s['cycles_component'])}, "
            f"cross-file self-calls {s['self_calls']['sites'] if s['self_calls'].get('measured', True) else 'not measured (source refused)'} over {len(s['self_calls']['pairs'])} file pairs, "
            f"smells hub/unstable/god {len(s['smells']['hub_like'])}/{len(s['smells']['unstable_dependency'])}/{len(s['smells']['god_component'])}, "
            f"{s['functions']['count']} functions, {len(s['functions']['offenders'])} over the thresholds")
    return lines


def read_exemptions(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


@dataclass
class Assessment:
    old: dict                  # the baseline at the locations the plan gives its budgets
    current: dict              # the current facts, the compared population completed with each map's destination
    entries: list
    plan: "ledger.Plan | None"
    violations: list           # before the ledger's budgets and the exemptions
    left: list                 # what still fails
    notes: list
    errors: list


def assess(root, args, baseline, measurement) -> Assessment:
    current = gated(measurement, tracked_of(baseline))
    text = read_exemptions(root / args.ledger)
    entries, errors = ledger.read_entries(text, parse_entries, PLACEHOLDER)
    if entries:
        try:
            committed = git(root, "show", f"HEAD:{args.ledger}")
        except ToolError:
            committed = None
        if text != committed:
            errors.append("ledger entries must be committed before check/rebaseline")
    if errors:
        return Assessment(baseline, current, entries, None, [], [], [], errors)
    plan = ledger.make_plan(baseline, current, entries, Violation)
    old, current = ledger.transport(baseline, plan), ledger.effective_current(current, plan)
    violations, improvements = compare(old, current)
    left, problems = ledger.budgets(plan.failures + violations, entries, METRICS_NUMERIC, plan.used, Violation)
    left, notes, exemptions = apply_exemptions(left, read_exemptions(root / args.exemptions))
    errors += problems + exemptions
    notes += [f"ledger {e.fields['action']} {e.fields.get('identity', e.fields.get('target', e.fields.get('from', '')))}" for e in entries if e.fields["action"] in ("map", "retire", "admit", "move")]
    notes += [f"ledger {line}" for line in ledger.describe(plan, entries)]
    return Assessment(old, current, entries, plan, violations, left, improvements + notes, errors)


def command_admit(args):
    root = Path(args.root)
    baseline = load_baseline(root / args.baseline)
    measurement = measure(root, tighter_thresholds(baseline["thresholds"], DEFAULT_THRESHOLDS))
    current = gated(measurement, tracked_of(baseline))
    entries, errors = parse_entries(read_exemptions(root / args.ledger) or "", "ML-", ledger.ALIASES)
    if errors:
        raise ToolError("; ".join(errors))
    stated = [dict(action="move", **{"from": old, "to": new}) for old, new in args.move or []]   # the author's explicit moves: drafted as entries, expanded by the plan
    existing = {ledger.subject(e.fields) for e in entries}
    moves = [f for f in stated if ledger.subject(f) not in existing]
    plan = ledger.make_plan(baseline, current, entries + [Exemption(f"DRAFT-{i}", f) for i, f in enumerate(moves)], Violation, drafting=True)
    old, effective = ledger.transport(baseline, plan), ledger.effective_current(current, plan)
    violations, _ = compare(old, effective)
    drafts = [f for f in moves + ledger.draft_fields(plan, violations) if ledger.subject(f) not in existing]
    rendered = [(e.ident, e.fields) for e in entries]
    serial = max((int(e.ident[3:]) for e in entries if e.ident[3:].isdigit()), default=0)
    for f in drafts:
        serial += 1
        rendered.append((f"ML-{serial:04}", {**f, "reason": "TODO", "task": "TODO"}))
    path = root / args.ledger
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.render(rendered), encoding="utf-8")
    print(f"drafted {len(drafts)} entries in {path}; replace TODOs, review and commit")
    for line in ledger.describe(plan, [Exemption(ident, fields) for ident, fields in rendered]):
        print(f"  {line}")
    return EXIT_OK


def print_refusal(diagnostics, stream=sys.stderr) -> None:
    for diagnostic in diagnostics:
        print(f"SOURCE REFUSED: {diagnostic.render()}", file=stream)
    print(f"gen2-metrics: the production source is outside the supported-source contract ({contract.CONTRACT_ID}, docs/gen2/SOURCE-CONTRACT.md): "
          f"{len(diagnostics)} refusal(s); nothing was measured, recorded or certified", file=stream)


def command_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    baseline = load_baseline(root / args.baseline)
    measurement = measure(root, baseline["thresholds"])
    assessed = assess(root, args, baseline, measurement)
    left, notes, errors = assessed.left, assessed.notes, assessed.errors
    if notes:
        print("the baseline can be tightened: `make gen2-metrics-rebaseline`, then commit the diff")
    tighter = [k for k in DEFAULT_THRESHOLDS if tighter_thresholds(baseline["thresholds"], DEFAULT_THRESHOLDS)[k] != baseline["thresholds"][k]]
    if tighter:
        print(f"note: thresholds {', '.join(tighter)} can be tightened")
    for line in summary_lines(measurement.report) + notes + advisory_hotspots(measurement):
        print((f"note: {line}" if line.startswith(("exempted", "ledger")) else f"improved: {line}") if line in notes else line)
    for violation in left:
        print(f"METRICS REGRESSION: {violation.describe()}", file=sys.stderr)
    for error in errors:
        print(f"METRICS LEDGER/EXEMPTION PROBLEM: {error}", file=sys.stderr)
    if left or errors:
        print(f"gen2-metrics: {len(left)} regression(s), {len(errors)} ledger/exemption problem(s)", file=sys.stderr)
        return EXIT_FAIL
    print(f"gen2-metrics: no regression against the baseline ({sum(n.startswith('exempted') for n in notes)} exempted)")
    return EXIT_OK


def command_rebaseline(args: argparse.Namespace) -> int:
    root, path = Path(args.root), Path(args.root) / args.baseline
    try:
        baseline = load_baseline(path, upgradable=True)
    except ToolError:
        if path.exists():
            raise
        measurement = measure(root)   # a refusal here is raised before anything is written
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(baseline_text(make_baseline(measurement, DEFAULT_THRESHOLDS)), encoding="utf-8")
        print(f"wrote the first baseline {path}")
        return EXIT_OK
    at_old = measure(root, baseline["thresholds"])
    upgrading = baseline["version"] != BASELINE_VERSION
    if upgrading:
        if baseline["pin"]["production_sha256"] != at_old.report["pin"]["production_sha256"]:
            print("identity migration refused: restore the exact baseline production pin first", file=sys.stderr)
            return EXIT_FAIL
        original = baseline
        baseline = make_baseline(at_old, original["thresholds"])
        # Preserve every previous budget; migration only adds graph/registry.
        for service in SERVICES:
            baseline["services"][service].update(original["services"][service])
        baseline["identities"] = ledger.register(baseline)
        baseline["identity_serial"] = len(baseline["identities"])
    thresholds = tighter_thresholds(baseline["thresholds"], DEFAULT_THRESHOLDS)
    at_new = at_old if thresholds == baseline["thresholds"] else measure(root, thresholds)
    assessed = assess(root, args, baseline, at_new)
    if assessed.left or assessed.errors:
        for v in assessed.left:
            print(f"METRICS REGRESSION: {v.describe()}", file=sys.stderr)
        for error in assessed.errors:
            print(f"METRICS LEDGER/EXEMPTION PROBLEM: {error}", file=sys.stderr)
        print("gen2-metrics-rebaseline: refused; resolve identity/admission and regressions first", file=sys.stderr)
        return EXIT_FAIL
    plan, entries = assessed.plan, assessed.entries
    folded = ledger.fold(assessed.old, assessed.current, entries, assessed.violations)
    tracked = tracked_of(folded)
    updated = {"version": BASELINE_VERSION, "pin": at_new.report["pin"], "thresholds": dict(sorted(thresholds.items())),
               **tighten(folded, assessed.current, gated(at_new, tracked), thresholds)}
    # New threshold offenders have a budget only because a tighter operating
    # point was adopted; every previously recorded identity still persists.
    remaining = ledger.inventory(updated) - set(plan.registry.values())
    if remaining:
        raise ToolError(f"unadmitted budgets during folding: {sorted(remaining)}")
    updated.update(identities=plan.registry, identity_serial=plan.serial)
    try:
        ledger.validate_registry(updated)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    unchanged = {k: v for k, v in updated.items() if k != "pin"} == {k: v for k, v in baseline.items() if k not in ("pin", "digest")}
    if unchanged and not upgrading and not entries:
        print("the baseline is already as tight as the code allows; nothing written")
        return EXIT_OK
    path.write_text(baseline_text(updated), encoding="utf-8")
    if entries:
        (root / args.ledger).write_text(ledger.render([]), encoding="utf-8")   # every transition is folded into the baseline: the ledger starts empty again
    print(f"wrote {path}; review baseline and ledger diffs and commit them")
    return EXIT_OK


def command_report(args: argparse.Namespace) -> int:
    """Every table, from what the contract admits; source it refuses is shown as an INCOMPLETE, NON-PASSING input (exit 1) with its diagnostics, and the
    tables are written for what could be read (the import graph and function complexity do not depend on the refused forms)."""
    measurement = measure(Path(args.root), strict=False)
    write_report(measurement, Path(args.out))
    for line in summary_lines(measurement.report):
        print(line)
    if measurement.facts.diagnostics:
        print_refusal(measurement.facts.diagnostics)
        print(f"gen2-metrics: report written to {args.out}, marked input.complete=false, input.passing=false", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


def command_hotspots(args: argparse.Namespace) -> int:
    measurement = measure(Path(args.root), strict=False)
    write_hotspots(measurement, Path(args.out))
    for line in advisory_hotspots(measurement, top=10):
        print(line)
    if measurement.facts.diagnostics:   # the history tables need only the files and their complexity; the input is still not a passing one
        print_refusal(measurement.facts.diagnostics)
        return EXIT_FAIL
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="the repository (default: this one)")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--exemptions", default=DEFAULT_EXEMPTIONS)
    parser.add_argument("--ledger", default=ledger.LEDGER)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    admit = commands.add_parser("admit")
    admit.add_argument("--move", nargs=2, action="append", metavar=("FROM", "TO"),
                       help="state one explicit file move (or directory prefix, both ending in /): drafted as a `move` entry, expanded by the plan; repeatable")
    commands.add_parser("rebaseline")
    report = commands.add_parser("report")
    report.add_argument("out")
    hotspots = commands.add_parser("hotspots")
    hotspots.add_argument("out")
    args = parser.parse_args(argv)
    try:
        return {"admit": command_admit, "check": command_check, "rebaseline": command_rebaseline, "report": command_report, "hotspots": command_hotspots}[args.command](args)
    except contract.SourceRefused as exc:
        print_refusal(exc.diagnostics)
        return EXIT_FAIL
    except ToolError as exc:
        print(f"gen2-metrics: {exc}", file=sys.stderr)
        return EXIT_TOOL


if __name__ == "__main__":
    sys.exit(main())
