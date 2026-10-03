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
  Implicit collaboration. For every class that inherits (by name, resolved
  through the file's imports) a project class defined in another file - the
  Router and its six mixins - the `self.<method>(...)` call sites, in any
  member class, whose method is defined in another member class's file. The
  method is resolved the way the composed class resolves it (its own class,
  then its bases depth-first). Counted by directed file pair. Gate D #1/#2
  measured the Router with a fixed list of mixin names; this finds the same
  family without one (it also finds `Response(SealedAnswer)` in the gateway).
  `super()` calls, `self.<attr>.method()` and attribute reads are not counted.
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
  I(B) > I(A) flags seven edges at the 2q-a pin, three of them under 4 points.
  God component. A component of >= 3,000 physical lines (two files at the
  per-file limit) that at least 5 other components import. At the 2q-a pin it
  names `research_gateway.core` (5,187 lines, imported by 7) and nothing else;
  the next, `research_gateway.adapters`, is 3,625 lines and imported by 4.
  Function over the thresholds. Cyclomatic proxy > 20 (Gate D's "over 20"; the
  SEI "high risk" band begins at 21) or cognitive proxy > 30 (about the 97th
  percentile of the proxy at the pin, 37 functions against 46 for cyclomatic
  > 20). Every cognitive offender at 40 and over is already a cyclomatic one.
  These are operating points, not derived constants: they freeze the present
  state and stop it growing; they do not say the present state is right.

The ratchet (charter: "ratcheted: a baseline is recorded, and any regression
fails the check unless a reviewed, reasoned exemption entry covers it")
  `docs/gen2/metrics-baseline.json` is written by `rebaseline` and only by it
  (it carries a digest of its own content, so a hand edit fails the check).
  `check` fails (exit 1) when, for either service, against the baseline:
    - propagation cost (file graph, component graph) is higher;
    - a cycle appears that is not inside a baseline cycle, at either level;
    - a directed file pair has more cross-file self-call sites than before,
      or a new pair appears;
    - a hub-like file, unstable dependency or god component is new;
    - a function is over the thresholds that was not at the baseline, or a
      baselined offender's cyclomatic or cognitive value is higher;
    - an import edge joins the engine and the gateway (baseline: none).
  Anything else is reported, not gated (edges, fan-in/out, instability,
  reach, counts, lines). The thresholds are read from the baseline, so
  loosening the constants here changes nothing.
  `docs/gen2/metrics-exemptions.md` is the only way past a regression: an entry
  naming the metric and location (and, for a number, the highest value
  accepted), the reason, the review that accepted it and a removal condition.
  An entry that no regression needs, one that is malformed, and one a value has
  outgrown all fail the check.
  `rebaseline` only tightens (the tool is run explicitly; the diff is
  committed): it refuses while an un-exempted regression exists, keeps the old
  value wherever an exemption covers a regression, drops what improved, and
  never records a regression.

Subcommands (exit 0 pass, 1 regression / invalid exemption, 2 the tool could
not run):
  check        the ratchet; also prints an advisory change-coupling summary
               that can never change the exit status (`make gen2-metrics`)
  rebaseline   rewrite the baseline, tighten only (`make gen2-metrics-rebaseline`)
  report DIR   every table as Gate D's CSV/JSON (file and component
               dependencies, function complexity, import edges, summary)
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
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

EXIT_OK, EXIT_FAIL, EXIT_TOOL = 0, 1, 2
SERVICES = ("engine", "gateway")
SERVICE_PREFIX = {"engine": "gen2/", "gateway": "gateway/research_gateway/"}
ENGINE_TESTS = "gen2/tests/"
BASELINE_VERSION = 1
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
METRICS_NUMERIC = ("propagation_file", "propagation_component", "self_calls", "function_cyclomatic", "function_cognitive")
METRICS_SET = ("cycle_file", "cycle_component", "cross_service_import", "smell_hub_like", "smell_unstable_dependency", "smell_god_component")
METRICS = METRICS_NUMERIC + METRICS_SET


class ToolError(Exception):
    """The tool could not run (exit 2): not a repository, unparseable source, unreadable or unknown-version baseline."""


# --- the files -----------------------------------------------------------------------------------------------------

def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True, timeout=120).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"git {' '.join(args)} failed in {root}: {getattr(exc, 'stderr', '') or exc}") from exc


def production_files(root: Path) -> dict[str, list[str]]:
    """Tracked production `.py` files per service (and "all", the two together), in `git ls-files` order, missing-from-disk ones skipped."""
    tracked = [p for p in git(root, "ls-files").splitlines() if p.endswith(".py") and (root / p).is_file()]
    engine = [p for p in tracked if p.startswith(SERVICE_PREFIX["engine"]) and not p.startswith(ENGINE_TESTS)]
    gateway = [p for p in tracked if p.startswith(SERVICE_PREFIX["gateway"])]
    return {"engine": engine, "gateway": gateway, "all": [p for p in tracked if p in set(engine) | set(gateway)]}


def module_name(path: str) -> str:
    return path.removeprefix("gateway/").removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def component_of(path: str) -> str:
    return ".".join(module_name(path).split(".")[:2])


def read_trees(root: Path, paths: list[str]) -> tuple[dict[str, str], dict[str, ast.Module]]:
    texts, trees = {}, {}
    for path in paths:
        texts[path] = (root / path).read_text(encoding="utf-8")
        try:
            trees[path] = ast.parse(texts[path], filename=path)
        except SyntaxError as exc:
            raise ToolError(f"{path} does not parse: {exc}") from exc
    return texts, trees


# --- the import graph ----------------------------------------------------------------------------------------------

def import_targets(path: str, node: ast.AST) -> list[str]:
    """The dotted module names an import statement names (the base and each `base.name`), relative imports resolved."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        base = node.module or ""
        if node.level:
            module = module_name(path)
            package = module if path.endswith("__init__.py") else module.rpartition(".")[0]
            parts = package.split(".")
            base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
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

def class_index(trees: dict[str, ast.Module]) -> dict[tuple[str, str], ast.ClassDef]:
    return {(path, node.name): node for path, tree in trees.items() for node in tree.body if isinstance(node, ast.ClassDef)}


def project_bases(path: str, cls: ast.ClassDef, trees: dict[str, ast.Module], names: dict[str, str],
                  index: dict[tuple[str, str], ast.ClassDef]) -> list[tuple[str, str]]:
    """The project classes `cls` names as bases, in order, resolved through the imports of its own file."""
    local: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    for node in ast.walk(trees[path]):
        if isinstance(node, ast.ImportFrom):
            base = import_targets(path, node)[0]
            for alias in node.names:
                if base in names and (names[base], alias.name) in index:
                    local[alias.asname or alias.name] = (names[base], alias.name)
                elif f"{base}.{alias.name}" in names:
                    modules[alias.asname or alias.name] = names[f"{base}.{alias.name}"]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in names:
                    modules[alias.asname or alias.name] = names[alias.name]
    found = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            if (path, base.id) in index:
                found.append((path, base.id))
            elif base.id in local:
                found.append(local[base.id])
        elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id in modules \
                and (modules[base.value.id], base.attr) in index:
            found.append((modules[base.value.id], base.attr))
    return found


def family_order(root_key: tuple[str, str], trees: dict[str, ast.Module], names: dict[str, str],
                 index: dict[tuple[str, str], ast.ClassDef]) -> list[tuple[str, str]]:
    """The class and its project bases, transitively, depth-first left to right: how its own methods resolve."""
    order: list[tuple[str, str]] = []

    def visit(key: tuple[str, str]) -> None:
        if key in order:
            return
        order.append(key)
        for base in project_bases(key[0], index[key], trees, names, index):
            visit(base)

    visit(root_key)
    return order


def self_calls(trees: dict[str, ast.Module], names: dict[str, str]) -> dict:
    """{"sites": n, "pairs": {"a->b": n}, "families": {"Class (file)": {"sites": n, "pairs": {...}}}}"""
    index = class_index(trees)
    families: dict[str, dict] = {}
    for key in sorted(index):
        bases = project_bases(key[0], index[key], trees, names, index)
        if not any(base_path != key[0] for base_path, _ in bases):
            continue
        order = family_order(key, trees, names, index)
        defined: dict[str, str] = {}  # method name -> the file of the first class in resolution order that defines it
        for member in order:
            for item in index[member].body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defined.setdefault(item.name, member[0])
        pairs: collections.Counter = collections.Counter()
        for member in order:
            for node in ast.walk(index[member]):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                        and node.func.value.id == "self" and node.func.attr in defined and defined[node.func.attr] != member[0]:
                    pairs[f"{member[0]}->{defined[node.func.attr]}"] += 1
        families[f"{key[1]} ({key[0]})"] = {"sites": sum(pairs.values()), "pairs": dict(sorted(pairs.items()))}
    total: collections.Counter = collections.Counter()
    for family in families.values():
        total.update(family["pairs"])
    return {"sites": sum(total.values()), "pairs": dict(sorted(total.items())), "families": families}


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


def functions_of(path: str, tree: ast.Module) -> list[Fn]:
    found: list[Fn] = []

    def walk(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, scope + [child.name])
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cyclomatic, cognitive = complexity(child)
                found.append(Fn(path, ".".join(scope + [child.name]), child.lineno, child.end_lineno - child.lineno + 1, cyclomatic, cognitive))
                walk(child, scope + [child.name])
            else:
                walk(child, scope)

    walk(tree, [])
    seen: collections.Counter = collections.Counter()
    for fn in found:  # a repeated qualified name in one file keeps its own key: `name`, `name#2`, ...
        seen[(fn.file, fn.name)] += 1
        n = seen[(fn.file, fn.name)]
        fn.key = f"{fn.file}::{fn.name}" + (f"#{n}" if n > 1 else "")
    return found


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


def measure(root: Path, thresholds: dict | None = None) -> Measurement:
    thresholds = dict(DEFAULT_THRESHOLDS if thresholds is None else thresholds)
    paths = production_files(root)
    every = paths["all"]
    texts, trees = read_trees(root, every)
    names = {module_name(p): p for p in every}
    graph, edge_lines = build_graph(trees, names)
    functions = [fn for path in every for fn in functions_of(path, trees[path])]
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
            "modules": {row["module"]: {k: row[k] for k in ("fan_in", "fan_out", "instability", "out_reach", "in_reach")} for row in rows},
            "self_calls": self_calls({p: trees[p] for p in files}, names),
            "smells": smells_of(own, rows, components, thresholds),
            "functions": {"count": len(mine), "over_cyclomatic": sum(fn.cyclomatic > thresholds["function_cyclomatic"] for fn in mine),
                          "over_cyclomatic_50": sum(fn.cyclomatic > 50 for fn in mine),
                          "over_cognitive": sum(fn.cognitive > thresholds["function_cognitive"] for fn in mine),
                          "over_physical_lines_100": sum(fn.lines > 100 for fn in mine), "offenders": offenders},
        }
    cross = sorted(f"{a}->{b}" for a, targets in graph.items() for b in targets
                   if (a in paths["engine"]) != (b in paths["engine"]))
    measurement = Measurement(root, thresholds, paths, texts, graph, edge_lines, functions)
    measurement.report = {"definitions": __doc__, "thresholds": thresholds, "services": services, "cross_service_imports": cross,
                          "pin": {"commit": head_commit(root), "production_sha256": production_digest(root, every)}}
    return measurement


# --- the baseline --------------------------------------------------------------------------------------------------

def gated(report: dict) -> dict:
    """The part of a measurement the ratchet compares: nothing else in a report is gated."""
    services = {}
    for service in SERVICES:
        s = report["services"][service]
        services[service] = {
            "propagation_file": {"reach_pairs": s["propagation_file"]["reach_pairs"], "nodes": s["propagation_file"]["nodes"]},
            "propagation_component": {"reach_pairs": s["propagation_component"]["reach_pairs"], "nodes": s["propagation_component"]["nodes"]},
            "cycles_file": s["cycles_file"], "cycles_component": s["cycles_component"],
            "self_calls": dict(s["self_calls"]["pairs"]),
            "smells": {kind: list(s["smells"][kind]) for kind in SMELL_KINDS},
            "functions": {key: dict(value) for key, value in sorted(s["functions"]["offenders"].items())},
        }
    return {"services": services, "cross_service_imports": list(report["cross_service_imports"])}


def with_digest(body: dict) -> dict:
    body = {k: v for k, v in body.items() if k != "digest"}
    body["digest"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body


def baseline_text(baseline: dict) -> str:
    return json.dumps(with_digest(baseline), indent=2, sort_keys=True) + "\n"


def load_baseline(path: Path) -> dict:
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"no baseline at {path}: record one with `make gen2-metrics-rebaseline` and commit it") from exc
    except (OSError, ValueError) as exc:
        raise ToolError(f"the baseline {path} cannot be read: {exc}") from exc
    if not isinstance(baseline, dict) or baseline.get("version") != BASELINE_VERSION:
        raise ToolError(f"the baseline {path} is not version {BASELINE_VERSION}")
    if baseline.get("digest") != with_digest(baseline)["digest"]:
        raise ToolError(f"the baseline {path} does not match its own digest: it was edited by hand. "
                        "Only `make gen2-metrics-rebaseline` writes it (and only tightens); restore it from git")
    for key in DEFAULT_THRESHOLDS:
        if not isinstance(baseline.get("thresholds", {}).get(key), int):
            raise ToolError(f"the baseline {path} has no integer threshold {key}")
    return baseline


def make_baseline(report: dict, thresholds: dict) -> dict:
    return {"version": BASELINE_VERSION, "pin": report["pin"], "thresholds": dict(sorted(thresholds.items())), **gated(report)}


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
        for kind in SMELL_KINDS:
            for item in new["smells"][kind]:
                if item not in old["smells"][kind]:
                    violations.append(Violation(f"smell_{kind}", where(service, item), 1, 0))
            for item in old["smells"][kind]:
                if item not in new["smells"][kind]:
                    improvements.append(f"smell_{kind} {service}: {item} is gone")
        limits = baseline["thresholds"]
        for key, now in new["functions"].items():
            was = old["functions"].get(key)
            for metric, field_, limit in (("function_cyclomatic", "cyclomatic", limits["function_cyclomatic"]),
                                          ("function_cognitive", "cognitive", limits["function_cognitive"])):
                if was is None and now[field_] > limit:
                    violations.append(Violation(metric, where(service, key), now[field_], f"limit {limit}, not an offender"))
                elif was is not None and now[field_] > was[field_]:
                    violations.append(Violation(metric, where(service, key), now[field_], was[field_]))
        for key, was in old["functions"].items():
            now = new["functions"].get(key)
            if now is None:
                improvements.append(f"function {service}:{key} is no longer over the thresholds (or is gone)")
            elif now["cyclomatic"] < was["cyclomatic"] or now["cognitive"] < was["cognitive"]:
                improvements.append(f"function {service}:{key}: {now['cyclomatic']}/{now['cognitive']}, baseline {was['cyclomatic']}/{was['cognitive']}")
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
        entry = next((e for e in valid if (e.fields["metric"], e.fields["location"]) == (violation.metric, violation.where)), None)
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

def tighten(baseline: dict, at_old: dict, at_new: dict) -> dict:
    """The new gated content: `at_old` and `at_new` are measurements under the baseline's thresholds and the (possibly tighter) new ones."""
    services = {}
    for service in SERVICES:
        old, was, now = baseline["services"][service], at_old["services"][service], at_new["services"][service]
        out: dict = {}
        for key in ("propagation_file", "propagation_component"):
            out[key] = min((old[key], now[key]), key=gated_cost)
        for key in ("cycles_file", "cycles_component"):
            out[key] = [cycle for cycle in now[key] if inside_a_baseline_cycle(cycle, old[key])]
        out["self_calls"] = {pair: min(count, old["self_calls"][pair]) for pair, count in now["self_calls"].items() if pair in old["self_calls"]}
        out["smells"] = {}
        for kind in SMELL_KINDS:  # kept: baselined, or newly flagged only because a threshold got tighter (not a regression)
            out["smells"][kind] = [item for item in now["smells"][kind] if item in old["smells"][kind] or item not in was["smells"][kind]]
        out["functions"] = {}
        for key, value in now["functions"].items():
            if key in old["functions"]:
                out["functions"][key] = {f: min(value[f], old["functions"][key][f]) for f in ("cyclomatic", "cognitive")}
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
            f"cross-file self-calls {s['self_calls']['sites']} over {len(s['self_calls']['pairs'])} file pairs, "
            f"smells hub/unstable/god {len(s['smells']['hub_like'])}/{len(s['smells']['unstable_dependency'])}/{len(s['smells']['god_component'])}, "
            f"{s['functions']['count']} functions, {len(s['functions']['offenders'])} over the thresholds")
    return lines


def read_exemptions(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def command_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    baseline = load_baseline(root / args.baseline)
    measurement = measure(root, baseline["thresholds"])
    violations, improvements = compare(baseline, gated(measurement.report))
    left, notes, errors = apply_exemptions(violations, read_exemptions(root / args.exemptions))
    for line in summary_lines(measurement.report):
        print(line)
    for note in notes:
        print(f"note: {note}")
    for improvement in improvements:
        print(f"improved: {improvement}")
    if improvements:
        print("the baseline can be tightened: `make gen2-metrics-rebaseline`, then commit the diff")
    tighter = [k for k in DEFAULT_THRESHOLDS if tighter_thresholds(baseline["thresholds"], DEFAULT_THRESHOLDS)[k] != baseline["thresholds"][k]]
    if tighter:
        print(f"note: the tool's thresholds {', '.join(tighter)} are tighter than the baseline's; `make gen2-metrics-rebaseline` adopts them")
    for line in advisory_hotspots(measurement):
        print(line)
    for violation in left:
        print(f"METRICS REGRESSION: {violation.describe()}", file=sys.stderr)
    for error in errors:
        print(f"METRICS EXEMPTION PROBLEM: {error}", file=sys.stderr)
    if left or errors:
        print(f"gen2-metrics: {len(left)} regression(s), {len(errors)} exemption problem(s); docs/gen2/metrics-exemptions.md "
              "is the only way past a regression", file=sys.stderr)
        return EXIT_FAIL
    print(f"gen2-metrics: no regression against the baseline ({len(notes)} exempted)")
    return EXIT_OK


def command_rebaseline(args: argparse.Namespace) -> int:
    root = Path(args.root)
    path = root / args.baseline
    try:
        baseline = load_baseline(path)
    except ToolError as exc:
        if path.exists():
            raise
        print(f"no baseline yet ({exc}); recording the first one", file=sys.stderr)
        measurement = measure(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(baseline_text(make_baseline(measurement.report, DEFAULT_THRESHOLDS)), encoding="utf-8")
        print(f"wrote the first baseline {path}")
        return EXIT_OK
    at_old = measure(root, baseline["thresholds"])
    violations, _ = compare(baseline, gated(at_old.report))
    left, _notes, errors = apply_exemptions(violations, read_exemptions(root / args.exemptions))
    if left or errors:
        for violation in left:
            print(f"METRICS REGRESSION: {violation.describe()}", file=sys.stderr)
        for error in errors:
            print(f"METRICS EXEMPTION PROBLEM: {error}", file=sys.stderr)
        print("gen2-metrics-rebaseline: refused; a baseline is never loosened. Fix the regression or add a reviewed exemption", file=sys.stderr)
        return EXIT_FAIL
    thresholds = tighter_thresholds(baseline["thresholds"], DEFAULT_THRESHOLDS)
    at_new = at_old if thresholds == baseline["thresholds"] else measure(root, thresholds)
    updated = {"version": BASELINE_VERSION, "pin": at_new.report["pin"], "thresholds": dict(sorted(thresholds.items())),
               **tighten(baseline, gated(at_old.report), gated(at_new.report))}
    if {k: v for k, v in updated.items() if k != "pin"} == {k: v for k, v in baseline.items() if k not in ("pin", "digest")}:
        print("the baseline is already as tight as the code allows; nothing written")  # a new commit alone is not a reason to rewrite it
        return EXIT_OK
    path.write_text(baseline_text(updated), encoding="utf-8")
    print(f"wrote {path}; review the diff and commit it")
    return EXIT_OK


def command_report(args: argparse.Namespace) -> int:
    measurement = measure(Path(args.root))
    write_report(measurement, Path(args.out))
    for line in summary_lines(measurement.report):
        print(line)
    return EXIT_OK


def command_hotspots(args: argparse.Namespace) -> int:
    measurement = measure(Path(args.root))
    write_hotspots(measurement, Path(args.out))
    for line in advisory_hotspots(measurement, top=10):
        print(line)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="the repository (default: this one)")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--exemptions", default=DEFAULT_EXEMPTIONS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("rebaseline")
    report = commands.add_parser("report")
    report.add_argument("out")
    hotspots = commands.add_parser("hotspots")
    hotspots.add_argument("out")
    args = parser.parse_args(argv)
    try:
        return {"check": command_check, "rebaseline": command_rebaseline, "report": command_report, "hotspots": command_hotspots}[args.command](args)
    except ToolError as exc:
        print(f"gen2-metrics: {exc}", file=sys.stderr)
        return EXIT_TOOL


if __name__ == "__main__":
    sys.exit(main())
