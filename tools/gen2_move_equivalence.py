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

The --inline acceptance claim is SUPERSEDED / ADVISORY (2026-10-08): scalar/tuple return or assignment changes, @staticmethod and async def can receive false IDENTICAL
verdicts. It supplies no behavioral guarantee. See docs/gen2/BUILD-CHARTER.md, "Refactor evidence standard", and the external review
private/reviews/gen2-2q-b8-b9-astra-rereview-20261008.md. The description below records the historical algorithm, not an accepted plumbing guarantee.

Extract-method (task 2q-b9, historical advisory report): `--inline FILE:Class.method=HELPER,HELPER...` names the private helpers a method was split into. The AFTER method gets each helper's call statement
(`self.h(a, b)` or `x = self.h(a, b)`) replaced by the helper's body, and must then dump to the same AST as the BEFORE method, signature included. The only plumbing declared: the
helper's signature, its docstring, and its last statement `return x` (or `return x, y`) when the call assigns exactly those names; the arguments must be the helper's parameters,
name for name and in order, so no renaming is needed. A helper that already existed, one not called exactly once, a call outside statement position, a `return` anywhere but last,
and a name a function reads that nothing binds and the module and builtins lack (a local of the caller used by the helper) are each reported. Mapping: helper -> original lines.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import collections
import copy
import symtable
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


def without_docstring(body: list) -> list:
    return body[1:] or [ast.Pass()] if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str) else body


def dump(fn, rules=None) -> str:
    """The function as a tree with its docstring dropped; the declared rewrites applied first when given."""
    fn = copy.deepcopy(fn)
    fn.body = without_docstring(fn.body)
    return ast.dump(Rewrite(rules).visit(fn) if rules else fn)


def names_of(node) -> list[str] | None:
    """The names a target or a returned value is made of (`x`, `a, b`); None for anything else."""
    items = node.elts if isinstance(node, ast.Tuple) else [node]
    return [i.id for i in items] if all(isinstance(i, ast.Name) for i in items) else None


def helper_call(statement, helpers):
    """(call, target) when the statement is `self.<helper>(...)` or `<target> = self.<helper>(...)` for a declared helper, else None."""
    assigned = isinstance(statement, ast.Assign) and len(statement.targets) == 1
    value = statement.value if assigned or isinstance(statement, ast.Expr) else None
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and isinstance(value.func.value, ast.Name) and value.func.value.id == "self" and value.func.attr in helpers:
        return value, statement.targets[0] if assigned else None
    return None


def plumbing(call, target, helper) -> list[str]:
    """Why the call is not a plain stand-in for the helper's body: empty when the parameters are the names passed (in order) and the last statement returns the target."""
    args, body, problems = helper.args, without_docstring(helper.body), []
    if [a.arg for a in args.args[:1]] != ["self"] or args.defaults or args.kwonlyargs or args.vararg or args.kwarg or args.posonlyargs:
        problems.append(f"{helper.name}: its parameters are more than `self` and plain names")
    if call.keywords or [getattr(a, "id", None) for a in call.args] != [a.arg for a in args.args[1:]]:
        problems.append(f"{helper.name}: the arguments ({', '.join(map(ast.unparse, call.args))}) are not its parameters, name for name and in order")
    last = body[-1]
    matched = isinstance(last, ast.Return) and target is not None and names_of(last.value) is not None and names_of(last.value) == names_of(target)
    if not matched and (target is not None or isinstance(last, ast.Return)):
        problems.append(f"{helper.name}: its last statement does not return exactly what the call assigns")
    if any(isinstance(n, ast.Return) for statement in (body[:-1] if isinstance(last, ast.Return) else body) for n in ast.walk(statement)):
        problems.append(f"{helper.name}: a return other than the last statement")
    return problems


def unbound(source: str, cls: str | None, names: list[str]) -> dict[str, list[str]]:
    """Per named function of the class, the names it (or a scope inside it) reads that nothing in it binds and the module and the builtins lack: a caller's local a helper uses."""
    top = symtable.symtable(source, "<module>", "exec")
    known = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    reads = lambda table: [s.get_name() for s in table.get_symbols() if s.is_global() and s.get_name() not in known and not hasattr(builtins, s.get_name())] + [
        n for child in table.get_children() for n in reads(child)]
    scope = next((c for c in top.get_children() if c.get_name() == cls), top) if cls else top
    return {t.get_name(): sorted(set(reads(t))) for t in scope.get_children() if t.get_name() in names}


def inline_back(before, after, helpers: dict) -> dict:
    """{'identical', 'mapping': [(helper, first, last original line)], 'problems'}: AFTER with each helper called once, as a statement, replaced by its body must dump like BEFORE."""
    problems, spans, calls, flat = [], [], collections.Counter(), []
    for statement in without_docstring(after.body):
        found = helper_call(statement, helpers)
        if found is None:
            flat.append(statement)
            continue
        call, target = found
        helper = helpers[call.func.attr]
        calls[helper.name] += 1
        problems += plumbing(call, target, helper)
        body = without_docstring(helper.body)
        body = body[:-1] if isinstance(body[-1], ast.Return) else body
        spans.append((helper.name, len(flat), len(body)))
        flat += body
    problems += [f"{name}: called {calls[name]} times, not once" for name in helpers if calls[name] != 1]
    inlined = copy.copy(after)
    inlined.body = flat
    problems += [f"{n.func.attr}: a call that is not a whole statement, or inside a helper" for s in flat for n in ast.walk(s) if helper_call(ast.Expr(value=n), helpers)]
    original = without_docstring(before.body)
    same = dump(before) == dump(inlined)
    mapping = [(name, original[first].lineno, original[first + count - 1].end_lineno) for name, first, count in spans] if same else []
    return {"identical": same and not problems, "mapping": mapping, "problems": problems or ([] if same else ["the inlined method is not the original's AST"])}


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
    parser.add_argument("--inline", action="append", default=[], help="FILE:Class.method=helper,helper: the method was split into these private helpers")
    args = parser.parse_args(argv)
    moved = [tuple(m.split("=")) if "=" in m else (m, m) for m in args.moved]
    result = compare(Path(args.before), Path(args.after), moved, args.rewrite, args.files)
    print(f"moved, identical after the rewrites ({len(result['identical'])}): " + ", ".join(result["identical"]))
    print(f"moved, DIFFERENT beyond the rewrites ({len(result['different'])}): " + ", ".join(result["different"]))
    print(f"for review ({len(result['review'])}):")
    for kind, file, name in result["review"]:
        print(f"  {kind:8s} {file} {name}")
    return 1 if result["different"] or not all([inline_report(Path(args.before), Path(args.after), spec) for spec in args.inline]) else 0


def inline_report(before: Path, after: Path, spec: str) -> bool:
    """Print the inline-back verdict of one `FILE:Class.method=helper,...` and say whether it is clean."""
    where, helper_names = spec.split("=")
    file, qualified = where.split(":")
    cls, method = qualified.split(".")
    old, new = functions(before / file, cls), functions(after / file, cls)
    helpers = {n: new[n] for n in helper_names.split(",") if n in new}
    result = inline_back(old[method], new[method], helpers)
    result["problems"] += [f"{n}: not defined in AFTER" for n in helper_names.split(",") if n not in new] + [f"{n}: already a method of BEFORE" for n in helpers if n in old]
    scopes = unbound((after / file).read_text(encoding="utf-8"), cls, [method, *helpers])
    result["problems"] += [f"{f} reads {names}, which nothing binds and neither the module nor the builtins define" for f, names in scopes.items() if names]
    print(f"inline-back {file}:{qualified} ({len(helpers)} helpers): " + ("IDENTICAL to the original after the declared plumbing" if not result["problems"] else "DIFFERENT"))
    print("".join(f"  {name} <- original lines {first}-{last}\n" for name, first, last in result["mapping"]) + "".join(f"  PROBLEM {p}\n" for p in result["problems"]), end="")
    return not result["problems"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
