#!/usr/bin/env python3
"""Select the gen-2 test modules a change affects (make gen2-affected).

Usage: gen2_affected.py BASE HEAD. Prints test module names, one per line;
or `NONE: <why>`; or `FULL: <why>` when no safe subset exists. Method: the
reverse import closure over a static AST import graph of gen2/, built at the
merge base AND at head (a deleted module still selects its former importers).
A string naming a module or a .py file (a subprocess launched by -m or by path)
is an edge too; a launch whose target is no string is an edge to every file.
Anything the graph cannot speak for is FULL; only documentation no code names is inert.
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
LAUNCHERS = {"import_module", "__import__", "run_module", "run_path"}
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
    byname = defaultdict(set)
    for p in files:
        byname[p.rpartition("/")[2]].add(p)
    edges: dict[str, set[str]] = {}
    for path, source in files.items():
        package = path.rpartition("/")[0].replace("/", ".").split(".")
        names, found, dynamic = [], set(), False
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = ".".join((package[:len(package) - node.level + 1] if node.level else [])
                                + ([node.module] if node.module else []))
                names += [base] + [f"{base}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):  # a launch by module or by file name
                names.append(node.value)
                found |= byname[node.value.rpartition("/")[2]] if node.value.endswith(".py") else set()
            elif isinstance(node, ast.Call):  # a target no string names: it could be any file
                dynamic |= getattr(node.func, "id", getattr(node.func, "attr", "")) in LAUNCHERS and not all(
                    isinstance(a, ast.Constant) for a in node.args[:1])
            elif isinstance(node, (ast.List, ast.Tuple)):
                dynamic |= any(isinstance(a, ast.Constant) and a.value == "-m" and not isinstance(b, ast.Constant)
                               for a, b in zip(node.elts, node.elts[1:]))
        found |= {modules.get(".".join(n.split(".")[:i])) for n in names for i in range(1, n.count(".") + 2)}
        edges[path] = (found | (set(files) if dynamic else set())) - {None, path}
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
    changed = git("diff", "--name-only", "-z", "--no-renames", base, head).decode().split("\0")[:-1]
    seeds, docs = set(), []
    for path in changed:  # the mandatory FULL paths first: nothing is exempt from them
        if path == "Makefile" or path.startswith(FULL_PREFIXES) or path.endswith(".sql"):
            return f"FULL: {path} is shared machinery"
        if path.endswith(".md"):
            docs.append(path)
        elif path.startswith("gen2/") and path.endswith(".py"):
            seeds.add(path)
        else:
            return f"FULL: {path} is a file type the selector cannot map"
    try:
        files = [sources(ref) for ref in (base, head)]
        graphs = [graph(f) for f in files]
    except SyntaxError as error:
        return f"FULL: a gen2 module does not parse ({error})"
    for doc in docs:  # prose is inert unless gen2 code or a test names the file as an input
        name = re.escape(doc.rpartition("/")[2])
        if any(re.search(f"[\"'/]{name}[\"']", text) for f in files for text in f.values()):
            return f"FULL: {doc} is a quoted name in gen2 code or tests (a possible input)"
    if not seeds:
        return "NONE: docs-only change"
    for path in sorted(seeds):
        if not any(path in f for f in files):
            return f"FULL: {path} is in neither source map (a symlink or special file)"
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
