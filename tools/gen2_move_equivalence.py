#!/usr/bin/env python3
"""Mechanical-move equivalence (task 2q-b3b): for a refactor that only MOVES code, is every moved function body AST-identical after exactly the declared rewrites?

    python tools/gen2_move_equivalence.py BEFORE_TREE AFTER_TREE [--moved FILE[:Class][=FILE[:Class]]]... [--rewrite 'OLD -> NEW']... [--files FILE]...

A moved unit is a class (or a whole file) named by --moved, as BEFORE=AFTER or one spelling for both. Its functions are compared by name: the AFTER body gets the declared
rewrites, then must dump to the same AST as the BEFORE body (docstrings aside; signature, decorators and annotations count). A rewrite is two Python expressions, `$X` in both one
identifier bound by the OLD side, e.g. `self._core.$X -> self.$X` and `self._core._transaction() -> self._store.transaction()`; rules are tried in the order given, top-down, the
first match wins. Every other function that differs (added, removed, changed) is listed for review, so is one added or removed inside a moved unit. Without --files the files
compared are every non-test .py under gen2/ that differs between the trees. Exit 1 when a moved body differs beyond the rewrites; the review list decides nothing.

It shows the moved bodies are the same code. It does not show the code behaves the same where it now runs (a rewrite can change what a name resolves to): that is the replay's
work (tools/gen2_replay.py).
"""
from __future__ import annotations

import argparse
import ast
import copy
import sys
from pathlib import Path

MV = "__mv_"


def pattern(text: str) -> ast.expr:
    return ast.parse(text.strip().replace("$", MV), mode="eval").body


def match(pat, node, env: dict) -> bool:
    if isinstance(pat, ast.AST):
        return type(pat) is type(node) and all(match(getattr(pat, f), getattr(node, f, None), env) for f in pat._fields)
    if isinstance(pat, list):
        return isinstance(node, list) and len(pat) == len(node) and all(match(p, n, env) for p, n in zip(pat, node))
    return env.setdefault(pat, node) == node if isinstance(pat, str) and pat.startswith(MV) else pat == node


class Rewrite(ast.NodeTransformer):
    def __init__(self, rules: list[tuple[ast.expr, ast.expr]]) -> None:
        self.rules = rules

    def visit(self, node):
        for old, new in self.rules:
            env: dict = {}
            if isinstance(node, ast.expr) and match(old, node, env):
                return ast.copy_location(self.substitute(copy.deepcopy(new), env), node)
        return self.generic_visit(node)

    @staticmethod
    def substitute(node, env: dict):
        for field in ast.walk(node):
            for name, value in ast.iter_fields(field):
                if isinstance(value, str) and value.startswith(MV):
                    setattr(field, name, env[value])
        return node


def functions(path: Path, cls: str | None) -> dict[str, ast.AST]:
    """Qualified name -> function node, of the class (names `f`) or of the whole file (names `f` or `Class.f`); nested functions belong to their outer one."""
    if not path.is_file():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = next((c.body for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls), []) if cls else tree.body
    out = {}
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
        elif isinstance(node, ast.ClassDef) and not cls:
            out.update({f"{node.name}.{f.name}": f for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))})
    return out


def dump(fn, rules=None) -> str:
    """The function as a tree with its docstring dropped; the declared rewrites applied first when given."""
    fn = copy.deepcopy(fn)
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) and isinstance(fn.body[0].value.value, str):
        fn.body = fn.body[1:] or [ast.Pass()]
    return ast.dump(Rewrite(rules).visit(fn) if rules else fn)


def compare(before: Path, after: Path, moved: list[tuple[str, str]], rewrites: list[str], files: list[str] | None = None) -> dict:
    """{'identical': [...], 'different': [...] (moved, beyond the rewrites), 'review': [(kind, file, name)]}."""
    rules = [tuple(map(pattern, r.split("->"))) for r in rewrites]
    out: dict = {"identical": [], "different": [], "review": []}
    spec = lambda s: tuple(s.split(":")) if ":" in s else (s, None)
    claimed = {spec(s) for pair in moved for s in pair}
    for old_spec, new_spec in moved:
        (old_file, old_cls), (new_file, new_cls) = spec(old_spec), spec(new_spec)
        old, new = functions(before / old_file, old_cls), functions(after / new_file, new_cls)
        for name in sorted(old.keys() & new.keys()):
            out["identical" if dump(old[name]) == dump(new[name], rules) else "different"].append(f"{new_spec}.{name}")
        out["review"] += [("added", new_spec, n) for n in sorted(new.keys() - old.keys())] + [("removed", old_spec, n) for n in sorted(old.keys() - new.keys())]
    for file in changed_files(before, after) if files is None else files:
        old, new = functions(before / file, None), functions(after / file, None)
        for name in sorted(old.keys() | new.keys()):
            if (file, None) in claimed or any(name.startswith(f"{cls}.") for f, cls in claimed if f == file and cls):
                continue
            kind = "removed" if name not in new else "added" if name not in old else "changed" if dump(old[name]) != dump(new[name]) else None
            if kind:
                out["review"].append((kind, file, name))
    return out


def changed_files(before: Path, after: Path) -> list[str]:
    """Every non-test .py under gen2/ in either tree whose bytes differ (or that exists in one tree only)."""
    read = lambda path: path.read_bytes() if path.is_file() else None
    names = {p.relative_to(t).as_posix() for t in (before, after) for p in (t / "gen2").rglob("*.py") if "tests" not in p.relative_to(t).parts}
    return sorted(n for n in names if read(before / n) != read(after / n))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("before"), parser.add_argument("after")
    parser.add_argument("--moved", action="append", default=[]), parser.add_argument("--rewrite", action="append", default=[]), parser.add_argument("--files", nargs="*")
    args = parser.parse_args(argv)
    moved = [tuple(m.split("=")) if "=" in m else (m, m) for m in args.moved]
    result = compare(Path(args.before), Path(args.after), moved, args.rewrite, args.files)
    print(f"moved, identical after the rewrites ({len(result['identical'])}): " + ", ".join(result["identical"]))
    print(f"moved, DIFFERENT beyond the rewrites ({len(result['different'])}): " + ", ".join(result["different"]))
    print(f"for review ({len(result['review'])}):")
    for kind, file, name in result["review"]:
        print(f"  {kind:8s} {file} {name}")
    return 1 if result["different"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
