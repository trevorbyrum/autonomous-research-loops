#!/usr/bin/env python3
"""Gen-2 module-boundary checker (stdlib only).

Enforces gen2/boundaries.toml against every Python file under the gen-2
package root, and checks that the declared graph and docs/gen2/BOUNDARIES.md
have not drifted apart. Exit status: 0 clean, 1 boundary violations, 2 the
configuration itself is invalid (or cannot be read).

Trace: task 0a deliverable 4; charter "Standing rules"; design review §10
("Enforce dependency boundaries in CI"). The rules are listed in the header of
gen2/boundaries.toml.

This is an ARCHITECTURAL LINT, not a sandbox (Astra 0a review A8). It bounds
which capability-bearing names a module can reach through ordinary static
Python: imports (including the private low-level modules behind public ones,
e.g. _sqlite3, _posixsubprocess), attribute chains on imported modules, and
the forbidden builtins by any static spelling (bare reference, `from builtins
import eval as e`, an alias of `builtins`, `__builtins__`) — in any expression
position, signature annotations, defaults, decorators and type-parameter
bounds included (they are evaluated code). Import aliases are resolved in the
scope that binds them (module, function, class, comprehension; `global` and
`nonlocal` honoured, including an import that rebinds a nonlocal name), so an
alias reused in another function cannot hide a restricted module.

What it structurally cannot see, and so leaves to runtime isolation and
review: names reached through reflection (getattr/globals/vars/sys.modules),
assignment of a module to another variable, code run by a child interpreter,
filesystem I/O (open/pathlib/io are not restricted — a module described as
"no I/O" is held to that by review, not by this tool), which network endpoint
a permitted client talks to, and the behaviour of permitted imports.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

EXIT_OK, EXIT_VIOLATION, EXIT_CONFIG = 0, 1, 2
NON_PYTHON_CODE_SUFFIXES = {".sh", ".bash"}


class ConfigError(Exception):
    pass


@dataclass
class Module:
    name: str
    path: str  # repo-relative, "/"-separated
    dotted: str
    may_import: list[str]
    stdlib_capabilities: list[str]
    third_party: list[str]
    boundaries: list[str]


@dataclass
class Config:
    package_root: str
    boundaries_doc: str
    forbidden_imports: list[str]
    forbidden_calls: list[str]
    restricted_stdlib: list[str]
    forbidden_sql: list[re.Pattern]
    forbidden_sql_exempt: list[str]
    modules: dict[str, Module]
    unmapped_components: dict[str, str]
    errors: list[str] = field(default_factory=list)


def _str_list(table: dict, key: str, where: str, errors: list[str]) -> list[str]:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        errors.append(f"{where}: `{key}` must be a list of non-empty strings")
        return []
    return value


def load_config(root: Path, config_rel: str) -> Config:
    path = root / config_rel
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{config_rel}: not found") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_rel}: invalid TOML: {exc}") from None
    errors: list[str] = []
    if raw.get("schema_version") != 1:
        errors.append(f"{config_rel}: schema_version must be 1")
    package_root = raw.get("package_root")
    boundaries_doc = raw.get("boundaries_doc")
    if not isinstance(package_root, str) or not package_root:
        raise ConfigError(f"{config_rel}: package_root must be a non-empty string")
    if not isinstance(boundaries_doc, str) or not boundaries_doc:
        raise ConfigError(f"{config_rel}: boundaries_doc must be a non-empty string")
    modules: dict[str, Module] = {}
    raw_modules = raw.get("modules")
    if not isinstance(raw_modules, dict) or not raw_modules:
        raise ConfigError(f"{config_rel}: [modules] must declare at least one module")
    for name, table in raw_modules.items():
        where = f"{config_rel}: modules.{name}"
        if not isinstance(table, dict):
            errors.append(f"{where}: must be a table")
            continue
        mod_path = table.get("path")
        if not isinstance(mod_path, str) or not (mod_path == package_root or mod_path.startswith(package_root + "/")):
            errors.append(f"{where}: `path` must lie under package_root {package_root!r}")
            continue
        if not isinstance(table.get("purpose"), str) or not table["purpose"].strip():
            errors.append(f"{where}: `purpose` must be a non-empty string")
        dotted = mod_path[:-3] if mod_path.endswith(".py") else mod_path
        modules[name] = Module(
            name=name,
            path=mod_path,
            dotted=dotted.replace("/", "."),
            may_import=_str_list(table, "may_import", where, errors),
            stdlib_capabilities=_str_list(table, "stdlib_capabilities", where, errors),
            third_party=_str_list(table, "third_party", where, errors),
            boundaries=_str_list(table, "boundaries", where, errors),
        )
    unmapped = raw.get("unmapped_components", {})
    if not isinstance(unmapped, dict) or not all(isinstance(v, str) and v.strip() for v in unmapped.values()):
        errors.append(f"{config_rel}: [unmapped_components] values must be non-empty reasons")
        unmapped = {}
    forbidden_sql: list[re.Pattern] = []
    for pattern in _str_list(raw, "forbidden_sql", config_rel, errors):
        try:
            forbidden_sql.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            errors.append(f"{config_rel}: forbidden_sql pattern {pattern!r} is not a valid regex: {exc}")
    cfg = Config(
        package_root=package_root,
        boundaries_doc=boundaries_doc,
        forbidden_imports=_str_list(raw, "forbidden_imports", config_rel, errors),
        forbidden_calls=_str_list(raw, "forbidden_calls", config_rel, errors),
        restricted_stdlib=_str_list(raw, "restricted_stdlib", config_rel, errors),
        forbidden_sql=forbidden_sql,
        forbidden_sql_exempt=_str_list(raw, "forbidden_sql_exempt_modules", config_rel, errors) if "forbidden_sql_exempt_modules" in raw else [],
        modules=modules,
        unmapped_components=unmapped,
        errors=errors,
    )
    return cfg


def doc_headings(root: Path, doc_rel: str) -> list[str]:
    try:
        text = (root / doc_rel).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{doc_rel}: not found (boundaries_doc)") from None
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def validate_config(cfg: Config, headings: list[str], config_rel: str) -> list[str]:
    errors = list(cfg.errors)
    names = set(cfg.modules)
    restricted = set(cfg.restricted_stdlib)
    for name in cfg.forbidden_sql_exempt:
        if name not in names:
            errors.append(f"{config_rel}: forbidden_sql_exempt_modules names undeclared module {name!r}")
    for mod in cfg.modules.values():
        where = f"{config_rel}: modules.{mod.name}"
        for dep in mod.may_import:
            if dep != "*" and dep not in names:
                errors.append(f"{where}: may_import names undeclared module {dep!r}")
        for grant in mod.stdlib_capabilities:
            if grant != "*" and grant not in restricted:
                errors.append(f"{where}: stdlib capability {grant!r} is not in restricted_stdlib")
        for heading in mod.boundaries:
            if heading not in headings:
                errors.append(f"{where}: boundaries entry {heading!r} is not a `## ` heading in {cfg.boundaries_doc} (BOUNDARY-DRIFT)")
    paths = sorted((m.path, m.name) for m in cfg.modules.values())
    for i, (p, n) in enumerate(paths):
        for q, other in paths[i + 1:]:
            if q == p or q.startswith(p.rstrip("/") + "/"):
                errors.append(f"{config_rel}: module paths overlap: {n} ({p}) contains {other} ({q})")
    mapped = {h for m in cfg.modules.values() for h in m.boundaries}
    for heading in cfg.unmapped_components:
        if heading not in headings:
            errors.append(f"{config_rel}: unmapped_components entry {heading!r} is not a `## ` heading in {cfg.boundaries_doc} (BOUNDARY-DRIFT)")
        if heading in mapped:
            errors.append(f"{config_rel}: {heading!r} is both mapped to a module and listed as unmapped")
    for heading in headings:
        if heading not in mapped and heading not in cfg.unmapped_components:
            errors.append(f"{cfg.boundaries_doc}: component {heading!r} is neither mapped to a module nor listed in [unmapped_components] (BOUNDARY-DRIFT)")
    # Acyclicity of the declared graph ("*" is test-only and excluded).
    graph = {m.name: [d for d in m.may_import if d != "*" and d != m.name and d in names] for m in cfg.modules.values()}
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in graph[node]:
            if state.get(nxt) == 1:
                cycle = stack[stack.index(nxt):] + [nxt]
                errors.append(f"{config_rel}: declared may_import graph has a cycle: {' -> '.join(cycle)}")
            elif nxt not in state:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for node in sorted(graph):
        if node not in state:
            visit(node)
    return errors


def _matches(target: str, entry: str) -> bool:
    if entry.endswith("*"):
        return target.startswith(entry[:-1])
    return target == entry or target.startswith(entry + ".")


def module_of_file(rel: str, cfg: Config) -> Module | None:
    for mod in cfg.modules.values():
        if rel == mod.path or rel.startswith(mod.path.rstrip("/") + "/"):
            return mod
    return None


def module_of_import(dotted: str, cfg: Config) -> Module | None:
    for mod in cfg.modules.values():
        if dotted == mod.dotted or dotted.startswith(mod.dotted + "."):
            return mod
    return None


def _dotted_of_file(rel: str) -> tuple[str, str]:
    """Return (module dotted name, package used for relative imports)."""
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
        return ".".join(parts), ".".join(parts)
    return ".".join(parts), ".".join(parts[:-1])


def _attribute_chain(node: ast.Attribute) -> tuple[str, list[str]] | None:
    attrs: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        attrs.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        return cur.id, list(reversed(attrs))
    return None


class _Scope:
    """One Python name scope (module, function/lambda, class, comprehension)."""

    def __init__(self, kind: str, parent: "_Scope | None") -> None:
        self.kind = kind
        self.parent = parent
        self.imports: dict[str, set[str]] = {}
        self.bound: set[str] = set()
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()

    def module(self) -> "_Scope":
        scope = self
        while scope.parent is not None:
            scope = scope.parent
        return scope


class _Binder(ast.NodeVisitor):
    """Scope-aware name binding (Astra 0a review A8): an import alias is
    resolved in the scope where the name is actually bound, so `import json as
    x` inside one function cannot hide `import os as x` used by another.
    Records, per scope, which names are bound and to which import targets;
    every Name load keeps the scope it occurs in for later resolution."""

    def __init__(self, package: str, rel: str) -> None:
        self.package, self.rel = package, rel
        self.scope = _Scope("module", None)
        self.imports: list[tuple[int, str]] = []
        self.loads: list[tuple[ast.Name, _Scope]] = []
        self.attrs: list[tuple[ast.Attribute, _Scope]] = []
        self.nonlocal_imports: list[tuple[_Scope, str, str]] = []
        self.problems: list[str] = []

    # -- binding helpers ------------------------------------------------------
    def _target_scope(self, name: str) -> _Scope:
        if name in self.scope.global_names:
            return self.scope.module()
        return self.scope

    def bind(self, name: str, import_target: str | None = None) -> None:
        scope = self._target_scope(name)
        scope.bound.add(name)
        if import_target is not None:
            if name in scope.nonlocal_names:
                # `nonlocal x; import os as x` rebinds the ENCLOSING function's
                # x (Astra re-review RA7); resolved once every binding is known
                self.nonlocal_imports.append((scope, name, import_target))
            else:
                scope.imports.setdefault(name, set()).add(import_target)

    def finish(self) -> None:
        """Attach each nonlocal import to the function scope that owns the name:
        the nearest enclosing function scope binding it (class bodies and
        comprehensions are not enclosing scopes for nonlocal; a scope that
        itself declares the name nonlocal or global does not own it). Python
        refuses a nonlocal with no owner, so the module scope is only a
        conservative fallback."""
        for scope, name, target in self.nonlocal_imports:
            owner = scope.parent
            while owner is not None and owner.parent is not None and (
                    owner.kind != "function" or name not in owner.bound or name in owner.nonlocal_names or name in owner.global_names):
                owner = owner.parent
            owner = owner or scope.module()
            owner.bound.add(name)
            owner.imports.setdefault(name, set()).add(target)

    def bind_target(self, node: ast.AST) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                self.bind(sub.id)
            elif isinstance(sub, ast.Starred) and isinstance(sub.value, ast.Name):
                self.bind(sub.value.id)

    # -- scopes ---------------------------------------------------------------
    def _type_params(self, node: ast.AST) -> None:
        """Type-parameter bounds/defaults (3.12+) are evaluated code; visited
        conservatively in the enclosing scope."""
        for param in getattr(node, "type_params", ()):
            for field in ("bound", "default_value"):
                value = getattr(param, field, None)
                if value is not None:
                    self.visit(value)

    def _signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Everything a `def` evaluates outside its body, in the enclosing
        scope (Astra re-review RA7): decorators, defaults, parameter and return
        annotations (run at definition time, or later by typing.get_type_hints
        under `from __future__ import annotations` — either way code), type
        parameters. The parameters themselves are not yet bound here."""
        args = node.args
        for expr in (*node.decorator_list, *args.defaults, *args.kw_defaults, node.returns,
                     *(a.annotation for a in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg) if a is not None)):
            if expr is not None:
                self.visit(expr)
        self._type_params(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._signature(node)
        self.bind(node.name)
        outer = self.scope
        self.scope = _Scope("function", outer)
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg):
            if arg is not None:
                self.scope.bound.add(arg.arg)
        for stmt in node.body:
            self.visit(stmt)
        self.scope = outer

    visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        outer = self.scope
        self.scope = _Scope("function", outer)
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg):
            if arg is not None:
                self.scope.bound.add(arg.arg)
        self.visit(node.body)
        self.scope = outer

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        for expr in (*node.decorator_list, *node.bases, *(k.value for k in node.keywords)):
            self.visit(expr)
        self._type_params(node)
        self.bind(node.name)
        outer = self.scope
        self.scope = _Scope("class", outer)
        for stmt in node.body:
            self.visit(stmt)
        self.scope = outer

    def _comprehension(self, node: ast.AST, elements: list[ast.AST]) -> None:
        generators = node.generators  # type: ignore[attr-defined]
        self.visit(generators[0].iter)  # the first iterable is evaluated in the enclosing scope
        outer = self.scope
        self.scope = _Scope("comprehension", outer)
        for index, gen in enumerate(generators):
            if index:
                self.visit(gen.iter)
            self.bind_target(gen.target)
            for cond in gen.ifs:
                self.visit(cond)
        for element in elements:
            self.visit(element)
        self.scope = outer

    def visit_ListComp(self, node: ast.ListComp) -> None:  # noqa: N802
        self._comprehension(node, [node.elt])

    visit_SetComp = visit_ListComp  # noqa: N815
    visit_GeneratorExp = visit_ListComp  # noqa: N815

    def visit_DictComp(self, node: ast.DictComp) -> None:  # noqa: N802
        self._comprehension(node, [node.key, node.value])

    # -- bindings -------------------------------------------------------------
    def visit_Global(self, node: ast.Global) -> None:  # noqa: N802
        self.scope.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:  # noqa: N802
        self.scope.nonlocal_names.update(node.names)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.imports.append((node.lineno, alias.name))
            if alias.asname:
                self.bind(alias.asname, alias.name)
            else:
                top = alias.name.split(".")[0]
                self.bind(top, top)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.level:
            base_parts = self.package.split(".") if self.package else []
            if node.level - 1 >= len(base_parts):
                self.problems.append(f"{self.rel}:{node.lineno}: relative import escapes the package root")
                return
            base = ".".join(base_parts[: len(base_parts) - (node.level - 1)])
            module = ".".join(part for part in (base, node.module) if part)
        else:
            module = node.module or ""
        if module == "__future__":
            return
        for alias in node.names:
            if alias.name == "*":
                self.problems.append(f"{self.rel}:{node.lineno}: star import from {module!r} hides its dependencies")
                continue
            target = f"{module}.{alias.name}" if module else alias.name
            self.imports.append((node.lineno, target))
            self.bind(alias.asname or alias.name, target)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bind(node.id)
        else:
            self.loads.append((node, self.scope))

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
        scope = self.scope
        while scope.kind == "comprehension" and scope.parent is not None:  # PEP 572: binds in the enclosing scope
            scope = scope.parent
        scope.bound.add(node.target.id)
        self.visit(node.value)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        if node.name:
            self.bind(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:  # noqa: N802
        if node.name:
            self.bind(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:  # noqa: N802
        if node.name:
            self.bind(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:  # noqa: N802
        if node.rest:
            self.bind(node.rest)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        self.attrs.append((node, self.scope))
        self.generic_visit(node)


def resolve(name: str, scope: _Scope) -> set[str] | None:
    """Import targets `name` refers to from `scope`: None if it is bound nowhere
    (a builtin), an empty set if its binding is not an import. A name bound by
    import and by other statements in the same scope resolves to the imports
    (conservative)."""
    start = scope
    if name in scope.global_names:
        scope = scope.module()
    while scope is not None:
        visible = scope is start or scope.kind != "class"  # class bodies are not visible to nested scopes
        if visible and name in scope.bound and name not in scope.nonlocal_names:
            return set(scope.imports.get(name, set()))
        scope = scope.parent
    return None


def collect_references(tree: ast.Module, package: str, rel: str, forbidden_calls: list[str]) -> tuple[list[tuple[int, str, str, str]], list[str]]:
    """Return ([(lineno, dotted target, kind, alias base)], problems).

    kind is import|attr|builtin. For attr, `alias base` is the import target
    the attribute chain starts from (so `os.system(...)` is caught even though
    `import os` itself is unrestricted), resolved in the chain's own scope.
    builtin refs name a forbidden builtin reached by any static spelling: a
    bare reference to it (called or not) where the name is not rebound, an
    import of builtins.<name>, an attribute on an alias of `builtins`, or any
    use of `__builtins__`.
    """
    binder = _Binder(package, rel)
    binder.visit(tree)
    binder.finish()
    refs: list[tuple[int, str, str, str]] = [(lineno, target, "import", "") for lineno, target in binder.imports]
    forbidden = set(forbidden_calls)
    for lineno, target in binder.imports:
        if target.startswith("builtins.") and target.split(".", 1)[1] in forbidden:
            refs.append((lineno, target.split(".", 1)[1], "builtin", ""))
    for node, scope in binder.attrs:
        chain = _attribute_chain(node)
        if chain is None:
            continue
        for base in sorted(resolve(chain[0], scope) or ()):
            dotted = ".".join([base, *chain[1]])
            refs.append((node.lineno, dotted, "attr", base))
            if base == "builtins" and chain[1] and chain[1][0] in forbidden:
                refs.append((node.lineno, chain[1][0], "builtin", ""))
    for node, scope in binder.loads:
        if node.id == "__builtins__":
            refs.append((node.lineno, "__builtins__", "builtin", ""))
        elif node.id in forbidden:
            targets = resolve(node.id, scope)
            if targets is None or any(t == f"builtins.{node.id}" for t in targets):
                refs.append((node.lineno, node.id, "builtin", ""))
    return refs, binder.problems


def _docstring_nodes(tree: ast.Module) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def forbidden_sql_uses(tree: ast.Module, patterns: list[re.Pattern]) -> list[tuple[int, str]]:
    """String literals (not docstrings) matching a forbidden SQL pattern.
    A lint over literal text: SQL assembled at runtime from fragments that do
    not individually match is not seen."""
    docstrings = _docstring_nodes(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            for pattern in patterns:
                if pattern.search(node.value):
                    hits.append((node.lineno, pattern.pattern))
    return hits


def check_file(root: Path, rel: str, mod: Module, cfg: Config) -> list[str]:
    try:
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [f"{rel}: cannot be parsed, so its imports cannot be checked: {exc}"]
    _, package = _dotted_of_file(rel)
    refs, problems = collect_references(tree, package, rel, cfg.forbidden_calls)
    violations = list(problems)
    if mod.name not in cfg.forbidden_sql_exempt:
        for lineno, pattern in forbidden_sql_uses(tree, cfg.forbidden_sql):
            violations.append(f"{rel}:{lineno}: {mod.name} has SQL matching forbidden pattern {pattern!r}: conflict resolution by REPLACE rewrites stored rows (INVARIANTS C-11)")
    stdlib = sys.stdlib_module_names
    seen: set[tuple[int, str]] = set()
    for lineno, target, kind, base in refs:
        if (lineno, target) in seen:
            continue
        seen.add((lineno, target))
        where = f"{rel}:{lineno}"
        if kind == "builtin":
            violations.append(f"{where}: {mod.name} reaches forbidden builtin {target}" + ("" if target == "__builtins__" else "()"))
            continue
        top = target.split(".")[0]
        if kind == "attr" and (top != base.split(".")[0] or top not in stdlib or any(_matches(base, e) for e in cfg.restricted_stdlib)):
            # Attribute chains matter only for restrictions invisible at the
            # import line (os.system after `import os`); anything else was
            # already judged where it was imported.
            continue
        if top in cfg.forbidden_imports:
            violations.append(f"{where}: {mod.name} imports forbidden {target!r} (gen-2 never imports gen-1 code)")
            continue
        if top == cfg.package_root:
            dep = module_of_import(target, cfg)
            if dep is None:
                violations.append(f"{where}: {mod.name} imports {target!r}, which is not inside any declared module")
            elif dep.name != mod.name and "*" not in mod.may_import and dep.name not in mod.may_import:
                violations.append(f"{where}: {mod.name} imports {dep.name} ({target}); allowed: {sorted(mod.may_import) or 'none'}")
            continue
        if top in stdlib:
            for entry in cfg.restricted_stdlib:
                if _matches(target, entry) and "*" not in mod.stdlib_capabilities and entry not in mod.stdlib_capabilities:
                    violations.append(f"{where}: {mod.name} uses restricted stdlib {entry!r} (via {target}); not granted in stdlib_capabilities")
            continue
        if kind == "import" and top not in mod.third_party:
            violations.append(f"{where}: {mod.name} imports third-party package {top!r}; not declared in third_party")
    return violations


def run(root: Path, config_rel: str) -> tuple[int, list[str], str]:
    try:
        cfg = load_config(root, config_rel)
        headings = doc_headings(root, cfg.boundaries_doc)
    except ConfigError as exc:
        return EXIT_CONFIG, [f"BOUNDARY CONFIG ERROR: {exc}"], ""
    config_errors = validate_config(cfg, headings, config_rel)
    if config_errors:
        return EXIT_CONFIG, [f"BOUNDARY CONFIG ERROR: {e}" for e in config_errors], ""
    pkg_dir = root / cfg.package_root
    violations: list[str] = []
    files = sorted(p for p in pkg_dir.rglob("*") if p.is_file()) if pkg_dir.is_dir() else []
    checked = 0
    present: set[str] = set()
    for path in files:
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts:
            continue
        if path.suffix in NON_PYTHON_CODE_SUFFIXES:
            violations.append(f"{rel}: non-Python code under {cfg.package_root}/ cannot be boundary-checked")
            continue
        if path.suffix != ".py":
            continue
        mod = module_of_file(rel, cfg)
        if mod is None:
            violations.append(f"{rel}: not inside any declared module (declare it in {config_rel} first)")
            continue
        present.add(mod.name)
        checked += 1
        violations.extend(check_file(root, rel, mod, cfg))
    if violations:
        return EXIT_VIOLATION, [f"BOUNDARY VIOLATION: {v}" for v in violations], ""
    summary = (
        f"gen2 boundary check OK: {checked} Python file(s) in {len(present)} module(s) "
        f"({', '.join(sorted(present)) or 'no code yet'}); {len(cfg.modules)} modules declared; "
        f"{len(headings)} BOUNDARIES.md components all accounted for"
    )
    return EXIT_OK, [], summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent, help="repository root")
    parser.add_argument("--config", default="gen2/boundaries.toml", help="config path relative to --root")
    args = parser.parse_args(argv)
    code, messages, summary = run(args.root.resolve(), args.config)
    for message in messages:
        print(message, file=sys.stderr)
    if code == EXIT_VIOLATION:
        print(f"gen2 boundary check FAILED: {len(messages)} violation(s)", file=sys.stderr)
    elif code == EXIT_CONFIG:
        print(f"gen2 boundary check FAILED: {len(messages)} configuration error(s)", file=sys.stderr)
    else:
        print(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
