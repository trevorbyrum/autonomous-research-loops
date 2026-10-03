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
  class's file. The bases are resolved over a stated surface (`Classes`):
  module-level classes and names bound by `class`, `import m`, `import m.n`,
  `import m as x`, `from m import n [as x]` and `from m import *`, relative
  imports resolved, followed through any number of re-exports, a base being a
  name, an attribute chain (`gen2.router.lifecycle.Lifecycle`), `Outer.Inner`
  or any of them subscripted. A base outside the measured files (a builtin, a
  standard-library or third-party module) is external. A base the tool cannot
  follow to a class or to something outside - a call, a name bound twice, a
  measured module that defines no such name, a first-party module that is not
  measured, an inconsistent hierarchy - is UNRESOLVED: reported by name and
  reason and a regression (below) unless an exemption classifies it; it is
  never read as "no collaboration". The method is resolved the way Python
  resolves it, through the C3 linearization of the family (not a depth-first
  walk: a diamond `D(B, C)` with `B(A)`, `C(A)` and `C.f` overriding `A.f`
  binds a call in `B` to `C.f`). A call site is counted once however many
  families contain it, by (site, defining file). Gate D #1/#2 measured the
  Router with a fixed list of mixin names; this finds the same family without
  one (it also finds `Response(SealedAnswer)` in the gateway).
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

The ratchet (charter Architecture metrics; task 2q-a-repair-2)
  The baseline records budgets and a persistent identity registry. The ledger
  docs/gen2/metrics-ledger.md explicitly admits, maps, retires or classifies
  obligations. Missing identity is failure, never improvement. Maps transport
  old budgets before comparing both function scores. New file, import edge,
  reach gained and collaboration/function budgets need reasoned admission.
  Fan-out is gated for every recorded file; fan-in of a previously stable
  target includes all dependents (its blast radius), regardless of file age.
  Instability is judged by causes and direction: taking on dependencies or
  losing dependents differ (Stable Dependencies Principle). Normalised
  propagation cost and smells remain additional guards, never admissions.
  Exemptions retain reason, accepting review and removal condition; they
  cannot excuse missing identity or an unadmitted population. Rebaseline
  folds committed ledger transitions and tightens all other budgets. Improved
  functions keep both scores and their identity, even below thresholds.
  Classification cannot restore information an AST cannot resolve.

Subcommands (exit 0 pass, 1 regression / invalid exemption, 2 the tool could
not run):
  check        the ratchet; also prints an advisory change-coupling summary
               that can never change the exit status (`make gen2-metrics`)
  admit        draft ledger transitions and budgets with reason: TODO
  rebaseline   fold ledger transitions; otherwise tighten only (`make gen2-metrics-rebaseline`)
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
import builtins
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

import gen2_metrics_ledger as ledger

EXIT_OK, EXIT_FAIL, EXIT_TOOL = 0, 1, 2
SERVICES = ("engine", "gateway")
SERVICE_PREFIX = {"engine": "gen2/", "gateway": "gateway/research_gateway/"}
ENGINE_TESTS = "gen2/tests/"
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
METRICS_SET = ("cycle_file", "cycle_component", "cross_service_import", "unresolved_base", "smell_hub_like", "smell_unstable_dependency", "smell_god_component")
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

Ref = tuple  # ("class", file, qualified name) | ("module", dotted) | ("package", dotted) | ("external",) | ("unresolved", why)
_COMPOUND = tuple(t for t in (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, getattr(ast, "TryStar", None)) if t)


def c3_merge(sequences: list[list]) -> list:
    """Python's C3 merge of the linearizations of the bases and the list of the bases themselves; ValueError when none is consistent."""
    sequences = [list(seq) for seq in sequences if seq]
    order: list = []
    while sequences:
        head = next((seq[0] for seq in sequences if not any(seq[0] in other[1:] for other in sequences)), None)
        if head is None:
            raise ValueError("no consistent method resolution order")
        order.append(head)
        for seq in sequences:
            if seq[0] == head:
                del seq[0]
        sequences = [seq for seq in sequences if seq]
    return order


class Classes:
    """Binding occurrences stay distinct; conditional and competing alternatives fail closed.

    What a class base expression names, resolved statically over the measured files (task 2q-a-repair F1).

    The supported surface: classes defined at module level (nested classes by `Outer.Inner`), and names bound at module level, also under
    `if`/`try`/`with`/loops, by `class`, `import m`, `import m.n`, `import m as x`, `from m import n [as x]` (relative imports resolved) and
    `from m import *` of a measured module. A base is a name, a dotted attribute chain (`pkg.mod.Class`) or either subscripted (`Generic[T]`).
    Names resolve through any number of re-exports. A base from outside the measured files (a standard-library or third-party module, a
    builtin) is EXTERNAL; anything else the tool cannot follow to a class - a call, a name bound twice or by assignment, a measured module
    that defines no such name, an import of a first-party module that is not measured - is UNRESOLVED, and an unresolved base is reported
    (never read as "no collaboration")."""

    def __init__(self, trees: dict[str, ast.Module], names: dict[str, str]) -> None:
        self.names = names
        self.packages = {".".join(m.split(".")[:i]) for m in names for i in range(1, len(m.split(".")))} - set(names)
        self.tops = {m.partition(".")[0] for m in names}
        self.scope = {path: self._bindings(path, tree) for path, tree in trees.items()}
        self.classes = {path: self._classes(tree) for path, tree in trees.items()}
        self.exports = {}
        for path, tree in trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                    try:
                        value = ast.literal_eval(node.value)
                        self.exports[path] = value if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value) else None
                    except (ValueError, TypeError):
                        self.exports[path] = None
        self.conditional = set()
        def alternatives(path, node, uncertain=False):
            if isinstance(node, ast.ClassDef) and uncertain:
                self.conditional.add((path, node.lineno))
            for child in ast.iter_child_nodes(node):
                alternatives(path, child, uncertain or isinstance(node, _COMPOUND))
        for path, tree in trees.items():
            alternatives(path, tree)
        self._mro: dict[tuple[str, str], list] = {}

    @staticmethod
    def _classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
        found: dict[str, ast.ClassDef] = {}

        def walk(node: ast.AST, scope: list[str]) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    qual = ".".join(scope + [child.name])
                    key = qual
                    n = 2
                    while key in found:
                        key = f"{qual}#{n}"
                        n += 1
                    found[key] = child
                    walk(child, scope + [child.name])
                else:
                    walk(child, scope + [getattr(child, "name", "?"), "<locals>"] if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope)

        walk(tree, [])
        return found

    @staticmethod
    def _bindings(path: str, tree: ast.Module) -> dict[str, list[tuple]]:
        found: dict[str, list[tuple]] = collections.defaultdict(list)

        def visit(statements: list[ast.stmt], conditional: bool = False) -> None:
            def bind(name, ref):
                found[name].append(("conditional", ref) if conditional else ref)
            for node in statements:
                if isinstance(node, ast.ClassDef):
                    bind(node.name, ("class", node.name))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    bind(node.name, ("other",))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        bind(alias.asname or alias.name.partition(".")[0], ("module", alias.name if alias.asname else alias.name.partition(".")[0]))
                elif isinstance(node, ast.ImportFrom):
                    base = import_targets(path, node)[0]
                    for alias in node.names:
                        bind("*" if alias.name == "*" else alias.asname or alias.name, ("star", base) if alias.name == "*" else ("from", base, alias.name))
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        for leaf in ast.walk(target):
                            if isinstance(leaf, ast.Name):
                                bind(leaf.id, ("other",))
                elif isinstance(node, _COMPOUND):
                    for block in ("body", "orelse", "finalbody"):
                        visit(getattr(node, block, []), True)
                    for handler in getattr(node, "handlers", []):
                        visit(handler.body, True)

        visit(tree.body)
        return found

    def module(self, dotted: str) -> Ref:
        if dotted in self.names:
            return ("module", dotted)
        if dotted in self.packages:
            return ("package", dotted)
        return ("unresolved", f"{dotted} is not a measured module") if dotted.partition(".")[0] in self.tops else ("external",)

    def member(self, ref: Ref, attr: str, seen: frozenset = frozenset()) -> Ref:
        """The attribute `attr` of a module, package or class."""
        if ref[0] in ("external", "unresolved"):
            return ref
        if ref[0] == "class":
            nested = f"{ref[2]}.{attr}"
            if nested + "#2" in self.classes[ref[1]] or (nested in self.classes[ref[1]] and (ref[1], self.classes[ref[1]][nested].lineno) in self.conditional):
                return ("unresolved", f"{nested} has competing class declarations")
            return ("class", ref[1], nested) if nested in self.classes[ref[1]] else ("unresolved", f"{ref[2]} defines no class {attr}")
        dotted = ref[1]
        if ref[0] == "module":
            path = self.names[dotted]
            if (path, attr) in seen:
                return ("unresolved", f"{dotted}.{attr} is imported through itself")
            candidates = []
            if attr in self.scope[path]:
                candidates.append(self.bound(path, attr, seen | {(path, attr)}))
            for binding in self.scope[path].get("*", ()):
                if binding[0] == "conditional":
                    candidates.append(("unresolved", "conditional star re-export"))
                    continue
                star = binding[1]
                star_path = self.names.get(star)
                if star_path:
                    exports = self.scope[star_path].get("__all__", [])
                    if exports and (len(exports) != 1 or exports[0][0] == "conditional" or self.exports.get(star_path) is None):
                        candidates.append(("unresolved", f"{star} has uncertain __all__ exports"))
                        continue
                    if (exports and attr not in self.exports[star_path]) or (not exports and attr.startswith("_")):
                        continue
                found = self.member(self.module(star), attr, seen | {(path, attr)})
                if found[0] != "unresolved" or "defines no" not in found[1]:
                    candidates.append(found)
            if len(candidates) > 1:
                return ("unresolved", f"{dotted}.{attr} has competing binding occurrences/re-exports")
            if candidates:
                return candidates[0]
        sub = f"{dotted}.{attr}"
        return self.module(sub) if sub in self.names or sub in self.packages else ("unresolved", f"{dotted} defines no {attr}")

    def bound(self, path: str, name: str, seen: frozenset = frozenset()) -> Ref:
        """What the module-level name `name` of file `path` is bound to."""
        options = self.scope[path].get(name, [])
        if not options:
            if self.scope[path].get("*", ()):
                return self.member(self.module(module_name(path)), name, seen)
            return ("external",) if hasattr(builtins, name) else ("unresolved", f"{name} is neither defined nor imported in {path}")
        if len(options) > 1 and not (all(o[0] == "module" for o in options) and len(set(options)) == 1):
            return ("unresolved", f"{name} is bound more than once in {path}")
        kind, *rest = next(iter(options))
        if kind == "class":
            return ("class", path, rest[0])
        if kind == "module":
            return self.module(rest[0])
        if kind == "from":
            return self.member(self.module(rest[0]), rest[1], seen)
        return ("unresolved", f"{name} is not a class or an import in {path}")

    def expr(self, path: str, node: ast.expr) -> Ref:
        if isinstance(node, ast.Name):
            return self.bound(path, node.id)
        if isinstance(node, ast.Attribute):
            return self.member(self.expr(path, node.value), node.attr)
        if isinstance(node, ast.Subscript):
            return self.expr(path, node.value)
        return ("unresolved", f"{ast.unparse(node)} is not a name")

    def bases(self, path: str, qual: str) -> list[tuple[str, Ref]]:
        """(source text, what it resolves to) for each base of a class, in order."""
        out = []
        for node in self.classes[path][qual].bases:
            ref = self.expr(path, node)
            out.append((ast.unparse(node), ("unresolved", f"{ast.unparse(node)} is a module, not a class") if ref[0] in ("module", "package") else ref))
        return out

    def mro(self, key: tuple[str, str], building: tuple = ()) -> list:
        """C3 linearization of a class: project classes are (file, name); a base outside them is an opaque ("base", text) entry."""
        if key in self._mro:
            return self._mro[key]
        if key in building:
            raise ValueError("inheritance cycle")
        sequences, direct = [], []
        for text, ref in self.bases(*key):
            node = (ref[1], ref[2]) if ref[0] == "class" else ("base", text)
            direct.append(node)
            sequences.append(self.mro(node, building + (key,)) if ref[0] == "class" else [node])
        self._mro[key] = [key] + c3_merge(sequences + [direct])
        return self._mro[key]


def self_call_nodes(cls: ast.ClassDef):
    """Every `self.<name>(...)` call in the class's own methods, closures included, nested classes not (their `self` is another object)."""
    stack = list(cls.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.ClassDef):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
            yield node
        stack.extend(ast.iter_child_nodes(node))


def self_calls(resolver: Classes, files: list[str]) -> dict:
    """{"sites": n, "pairs": {"a->b": n}, "families": {"Class (file)": {"sites": n, "pairs": {...}}}, "unresolved": {"file::Class(base)": why}}

    A family is rooted at every class with a project ancestor defined in another file (a same-file intermediate base does not hide it). Its
    methods resolve the way Python resolves them, through
    the C3 order of its project classes. A call site is counted once however many families contain it: by (site, defining file), so a site
    that two compositions bind to different files counts once for each file. `families` shows each root's own view."""
    in_service = set(files)
    sites: set[tuple[str, int, int, str]] = set()
    families: dict[str, dict] = {}
    unresolved: dict[str, str] = {}
    for path in sorted(files):
        for qual, node in resolver.classes[path].items():
            simple = qual.split("#", 1)[0]
            if simple + "#2" in resolver.classes[path] or (path, node.lineno) in resolver.conditional:
                unresolved[f"{path}::{qual}(binding)"] = "competing class declarations"
                continue
            if "." not in simple:
                binding = resolver.bound(path, simple)
                if binding[0] == "unresolved":
                    unresolved[f"{path}::{qual}(binding)"] = binding[1]
                    continue
            bases = resolver.bases(path, qual)
            for text, ref in bases:
                if ref[0] == "unresolved" or (ref[0] == "class" and ref[1] not in in_service):
                    unresolved[f"{path}::{qual}({text})"] = ref[1] if ref[0] == "unresolved" else f"{text} is defined in {ref[1]}, outside this service"
            if not any(ref[0] == "class" for _, ref in bases):
                continue
            try:
                order = [member for member in resolver.mro((path, qual)) if member[0] != "base"]
            except ValueError as exc:
                unresolved[f"{path}::{qual}({', '.join(text for text, _ in bases)})"] = str(exc)
                continue
            if not any(member[0] != path for member in order):
                continue
            defined: dict[str, str] = {}  # method name -> the file of the first class in resolution order that defines it
            for member in order:
                for item in resolver.classes[member[0]][member[1]].body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        defined.setdefault(item.name, member[0])
            mine: set[tuple[str, int, int, str]] = set()
            for member in order:
                for call in self_call_nodes(resolver.classes[member[0]][member[1]]):
                    if call.func.attr in defined and defined[call.func.attr] != member[0]:
                        mine.add((member[0], call.lineno, call.col_offset, defined[call.func.attr]))
            sites |= mine
            families[f"{qual} ({path})"] = {"sites": len(mine), "pairs": dict(sorted(collections.Counter(f"{src}->{dst}" for src, _, _, dst in mine).items()))}
    pairs = collections.Counter(f"{src}->{dst}" for src, _, _, dst in sites)
    return {"sites": len(sites), "pairs": dict(sorted(pairs.items())), "families": families, "unresolved": dict(sorted(unresolved.items()))}


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
    resolver = Classes(trees, names)
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
            "self_calls": self_calls(resolver, files),
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
            "unresolved_bases": dict(s["self_calls"]["unresolved"]),
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
        del body["services"][service]["unresolved_bases"]  # an unresolved base is never baselined: only an exemption classifies it
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
        for item, why in new["unresolved_bases"].items():
            violations.append(Violation("unresolved_base", where(service, item), 1, f"0; {why}"))
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
        entry = None if violation.metric in ("identity", "admission", "unresolved_base") else next((e for e in valid if (e.fields["metric"], e.fields["location"]) == (violation.metric, violation.where)), None)
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
            f"cross-file self-calls {s['self_calls']['sites']} over {len(s['self_calls']['pairs'])} file pairs, unresolved bases {len(s['self_calls']['unresolved'])}, "
            f"smells hub/unstable/god {len(s['smells']['hub_like'])}/{len(s['smells']['unstable_dependency'])}/{len(s['smells']['god_component'])}, "
            f"{s['functions']['count']} functions, {len(s['functions']['offenders'])} over the thresholds")
    return lines


def read_exemptions(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def assess(root, args, baseline, measurement):
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
        return baseline, current, entries, {}, 0, [], [], [], errors
    old, registry, serial, accounting, used = ledger.account(baseline, current, entries, Violation)
    violations, improvements = compare(old, current)
    left, problems = ledger.budgets(accounting + violations, entries, METRICS_NUMERIC, used, Violation)
    left, notes, exemptions = apply_exemptions(left, read_exemptions(root / args.exemptions))
    errors += problems + exemptions
    notes += [f"ledger {e.fields['action']} {e.fields.get('identity', e.fields.get('target', ''))}" for e in entries if e.fields["action"] in ("map", "retire", "admit")]
    return old, current, entries, registry, serial, violations, left, improvements + notes, errors


def command_admit(args):
    root = Path(args.root)
    baseline = load_baseline(root / args.baseline)
    measurement = measure(root, tighter_thresholds(baseline["thresholds"], DEFAULT_THRESHOLDS))
    current = gated(measurement, tracked_of(baseline))
    entries, errors = parse_entries(read_exemptions(root / args.ledger) or "", "ML-", ledger.ALIASES)
    if errors:
        raise ToolError("; ".join(errors))
    proposals = ledger.draft_fields(baseline, current, [])
    subjects = [{k: v for k, v in e.fields.items() if k not in ("reason", "task")} for e in entries]
    virtual = entries + [Exemption(f"DRAFT-{i}", f) for i, f in enumerate(proposals) if f not in subjects]
    adjusted, _registry, _serial, _failures, _used = ledger.account(baseline, current, virtual, Violation)
    violations, _ = compare(adjusted, current)
    fields = ledger.draft_fields(baseline, current, violations)
    existing = [{k: v for k, v in e.fields.items() if k not in ("reason", "task")} for e in entries]
    rendered = [(e.ident, e.fields) for e in entries]
    serial = max((int(e.ident[3:]) for e in entries if e.ident[3:].isdigit()), default=0)
    for f in fields:
        if f not in existing:
            serial += 1
            rendered.append((f"ML-{serial:04}", {**f, "reason": "TODO", "task": "TODO"}))
    path = root / args.ledger
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.render(rendered), encoding="utf-8")
    print(f"drafted {len(rendered) - len(entries)} entries in {path}; replace TODOs, review and commit")
    return EXIT_OK


def command_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    baseline = load_baseline(root / args.baseline)
    measurement = measure(root, baseline["thresholds"])
    _old, _current, _entries, _registry, _serial, _violations, left, notes, errors = assess(root, args, baseline, measurement)
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
        measurement = measure(root)
        # Bootstrap cannot silently certify unresolved source.
        unresolved = [(service, key) for service in SERVICES for key in measurement.report["services"][service]["self_calls"]["unresolved"]]
        if unresolved:
            print(f"unresolved bindings at bootstrap: {unresolved}", file=sys.stderr)
            return EXIT_FAIL
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
    old, current, entries, registry, serial, violations, left, _notes, errors = assess(root, args, baseline, at_new)
    if left or errors:
        for v in left:
            print(f"METRICS REGRESSION: {v.describe()}", file=sys.stderr)
        for error in errors:
            print(f"METRICS LEDGER/EXEMPTION PROBLEM: {error}", file=sys.stderr)
        print("gen2-metrics-rebaseline: refused; resolve identity/admission and regressions first", file=sys.stderr)
        return EXIT_FAIL
    thresholds = tighter_thresholds(baseline["thresholds"], DEFAULT_THRESHOLDS)
    at_new = at_old if thresholds == baseline["thresholds"] else measure(root, thresholds)
    folded = ledger.fold(old, current, entries, violations)
    tracked = tracked_of(folded)
    updated = {"version": BASELINE_VERSION, "pin": at_new.report["pin"], "thresholds": dict(sorted(thresholds.items())),
               **tighten(folded, current, gated(at_new, tracked), thresholds)}
    # New threshold offenders have a budget only because a tighter operating
    # point was adopted; every previously recorded identity still persists.
    remaining = ledger.inventory(updated) - set(registry.values())
    if remaining:
        raise ToolError(f"unadmitted budgets during folding: {sorted(remaining)}")
    updated.update(identities=registry, identity_serial=serial)
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
        (root / args.ledger).write_text(ledger.render([(e.ident, e.fields) for e in entries if e.fields["action"] == "classify"]), encoding="utf-8")
    print(f"wrote {path}; review baseline and ledger diffs and commit them")
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
    parser.add_argument("--ledger", default=ledger.LEDGER)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("admit")
    commands.add_parser("rebaseline")
    report = commands.add_parser("report")
    report.add_argument("out")
    hotspots = commands.add_parser("hotspots")
    hotspots.add_argument("out")
    args = parser.parse_args(argv)
    try:
        return {"admit": command_admit, "check": command_check, "rebaseline": command_rebaseline, "report": command_report, "hotspots": command_hotspots}[args.command](args)
    except ToolError as exc:
        print(f"gen2-metrics: {exc}", file=sys.stderr)
        return EXIT_TOOL


if __name__ == "__main__":
    sys.exit(main())
