#!/usr/bin/env python3
"""Ban SQLite native write/replace APIs (2d-4c-p4b2c2 closure).

Scan tracked Python in the INVARIANTS B-3 surface, excluding test trees.
Attribute names are forbidden on every receiver, including access without a
call and literal getattr lookups. Unrelated local names and strings are legal.
Dynamic code generation is outside this gate's scope; gen2-source already
forbids eval/exec in engine and gateway production (SOURCE-CONTRACT.md).
"""
import argparse
import ast
import sys
from pathlib import Path

from gen2_linecount import in_surface, tracked_files

BANNED = {"blobopen", "backup", "deserialize", "enable_load_extension", "load_extension"}
TEST_TREES = ("gen2/tests/", "gateway/tests/")


def violations(text, filename):
    for node in ast.walk(ast.parse(text, filename=filename)):
        name = None
        if isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.Call) and len(node.args) >= 2:
            function = node.func
            if ((isinstance(function, ast.Name) and function.id == "getattr") or
                    (isinstance(function, ast.Attribute) and function.attr == "getattr")):
                literal = node.args[1]
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    name = literal.value
        if name in BANNED:
            yield f"{filename}:{node.lineno}: forbidden SQLite native API {name}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args(argv).root.resolve()
    problems = []
    try:
        for rel in tracked_files(root):
            if in_surface(rel) and rel.endswith(".py") and not rel.startswith(TEST_TREES):
                problems.extend(violations((root / rel).read_text(encoding="utf-8"), rel))
    except (OSError, UnicodeError, SyntaxError) as exc:
        print(f"gen2-sqlite-native: cannot check source: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("gen2-sqlite-native: no forbidden native write/replace APIs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
