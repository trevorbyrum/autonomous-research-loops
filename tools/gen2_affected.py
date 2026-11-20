#!/usr/bin/env python3
"""Select the gen-2 test modules a change affects (make gen2-affected).

Usage: gen2_affected.py BASE HEAD. Prints test module names, one per line;
or `NONE: <why>`; or `FULL: <why>` when no safe subset exists. Method: the
reverse import closure over a static AST import graph of gen2/, built at the
merge base AND at head (a deleted module still selects its former importers).
A test helper that no test imports by name but a test mentions (a subprocess
child) is an edge too. Anything the graph cannot speak for is FULL.
Ruling: Trevor, 2026-11-20 (gen2-orchestration-rules, "affected tests per PR").
"""
from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tarfile
from collections import defaultdict

TESTS = "gen2/tests/"
FULL_PREFIXES = ("tools/", "gen2/core/", "gen2/schema/", "gen2/requirements")


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def sources(ref: str) -> dict[str, str]:
    with tarfile.open(fileobj=io.BytesIO(git("archive", ref, "gen2")), mode="r:") as tar:
        return {m.name: tar.extractfile(m).read().decode() for m in tar if m.isfile() and m.name.endswith(".py")}


def is_test(path: str) -> bool:
    return path.startswith(TESTS) and path.count("/") == 2 and path.rpartition("/")[2].startswith("test_")


def graph(files: dict[str, str]) -> dict[str, set[str]]:
    modules = {p[:-3].replace("/", ".").removesuffix(".__init__"): p for p in files}
    helpers = {p.rpartition("/")[2][:-3]: p for p in files if p.startswith(TESTS) and not is_test(p)}
    edges: dict[str, set[str]] = {}
    for path, source in files.items():
        package = path.rpartition("/")[0].replace("/", ".").split(".")
        names = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = ".".join(package[:len(package) - node.level + 1] if node.level else []
                                + ([node.module] if node.module else []))
                names += [base] + [f"{base}.{a.name}" for a in node.names]
        found = {modules.get(".".join(n.split(".")[:i])) for n in names for i in range(1, n.count(".") + 2)}
        found |= {h for stem, h in helpers.items() if re.search(rf"\b{stem}\b", source)}
        edges[path] = found - {None, path}
    return edges


def affected(edges: dict[str, set[str]], seeds: set[str]) -> set[str]:
    reverse = defaultdict(set)
    for path, targets in edges.items():
        for target in targets:
            reverse[target].add(path)
    reached, todo = set(), [s for s in seeds if s in edges]
    while todo:
        if (path := todo.pop()) not in reached:
            reached.add(path)
            todo += reverse[path]
    return reached


def select(base: str, head: str) -> str:
    base = git("merge-base", base, head).decode().strip()
    changed = git("diff", "--name-only", "--no-renames", base, head).decode().split("\n")[:-1]
    seeds = set()
    for path in changed:
        if path.startswith("docs/") or path.endswith(".md"):
            continue
        if path == "Makefile" or path.startswith(FULL_PREFIXES) or path.endswith(".sql"):
            return f"FULL: {path} is shared machinery"
        if not (path.startswith("gen2/") and path.endswith(".py")):
            return f"FULL: {path} is a file type the selector cannot map"
        seeds.add(path)
    if not seeds:
        return "NONE: docs-only change"
    try:
        graphs = [graph(sources(ref)) for ref in (base, head)]
    except SyntaxError as error:
        return f"FULL: a gen2 module does not parse ({error})"
    for path in sorted(seeds):
        if path.startswith(TESTS) and not is_test(path):
            importers = {i for edges in graphs for i, t in edges.items() if path in t and is_test(i)}
            if len(importers) > 1:
                return f"FULL: {path} is a shared test helper ({len(importers)} test modules use it)"
    reached = set().union(*(affected(edges, seeds) for edges in graphs))
    names = sorted(p[len(TESTS):-3] for p in reached if is_test(p) and p in graphs[1])
    return "\n".join(names) or "NONE: no test module imports the changed code"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(select(sys.argv[1], sys.argv[2]))
