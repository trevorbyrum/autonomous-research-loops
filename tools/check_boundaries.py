#!/usr/bin/env python3
"""Gen-2 module-boundary checker (stdlib only).

Enforces gen2/boundaries.toml against every Python file under the gen-2
package root, and checks that the declared graph and docs/gen2/BOUNDARIES.md
have not drifted apart. Exit status: 0 clean, 1 boundary violations, 2 the
configuration itself is invalid (or cannot be read).

Trace: task 0a deliverable 4; charter "Standing rules"; design review §10
("Enforce dependency boundaries in CI"). The rules are listed in the header of
gen2/boundaries.toml.

What a static import check structurally cannot see: names reached through
getattr()/globals() tricks, code run by a child interpreter, filesystem writes,
and behaviour of permitted imports. It bounds *which* capabilities a module
can name, not what it does with them.
"""
from __future__ import annotations

import argparse
import ast
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
    cfg = Config(
        package_root=package_root,
        boundaries_doc=boundaries_doc,
        forbidden_imports=_str_list(raw, "forbidden_imports", config_rel, errors),
        forbidden_calls=_str_list(raw, "forbidden_calls", config_rel, errors),
        restricted_stdlib=_str_list(raw, "restricted_stdlib", config_rel, errors),
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


def collect_references(tree: ast.Module, package: str, rel: str) -> tuple[list[tuple[int, str, str, str]], list[str]]:
    """Return ([(lineno, dotted target, kind, alias base)], problems).

    kind is import|attr|call. For attr, `alias base` is the import target the
    attribute chain starts from (so `os.system(...)` is caught even though
    `import os` itself is unrestricted).
    """
    refs: list[tuple[int, str, str, str]] = []
    problems: list[str] = []
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.append((node.lineno, alias.name, "import", ""))
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".") if package else []
                if node.level - 1 >= len(base_parts):
                    problems.append(f"{rel}:{node.lineno}: relative import escapes the package root")
                    continue
                base = ".".join(base_parts[: len(base_parts) - (node.level - 1)])
                module = ".".join(p for p in (base, node.module) if p)
            else:
                module = node.module or ""
            if module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    problems.append(f"{rel}:{node.lineno}: star import from {module!r} hides its dependencies")
                    continue
                target = f"{module}.{alias.name}" if module else alias.name
                refs.append((node.lineno, target, "import", ""))
                aliases[alias.asname or alias.name] = target
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain = _attribute_chain(node)
            if chain and chain[0] in aliases:
                refs.append((node.lineno, ".".join([aliases[chain[0]], *chain[1]]), "attr", aliases[chain[0]]))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                refs.append((node.lineno, func.id, "call", ""))
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "builtins":
                refs.append((node.lineno, func.attr, "call", ""))
    return refs, problems


def check_file(root: Path, rel: str, mod: Module, cfg: Config) -> list[str]:
    try:
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [f"{rel}: cannot be parsed, so its imports cannot be checked: {exc}"]
    _, package = _dotted_of_file(rel)
    refs, problems = collect_references(tree, package, rel)
    violations = list(problems)
    stdlib = sys.stdlib_module_names
    seen: set[tuple[int, str]] = set()
    for lineno, target, kind, base in refs:
        if (lineno, target) in seen:
            continue
        seen.add((lineno, target))
        where = f"{rel}:{lineno}"
        if kind == "call":
            if target in cfg.forbidden_calls:
                violations.append(f"{where}: {mod.name} calls forbidden builtin {target}()")
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
