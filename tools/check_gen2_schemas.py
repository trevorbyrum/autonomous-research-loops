#!/usr/bin/env python3
"""Validate gen-2 schemas, their fixtures, and the store DDL.

Checks, in order (any failure exits 1; a missing validator exits 2):
  1. Every gen2/schema/*.schema.json is Draft 2020-12, has the expected $id,
     and carries a `$comment` trace header whose `boundaries:` names are real
     `## ` headings in docs/gen2/BOUNDARIES.md.
  2. Every schema passes the official 2020-12 metaschema and every $ref in it
     resolves.
  3. Fixtures under gen2/schema/examples/<schema stem>/:
       valid-*.json    must validate;
       invalid-*.json  are a valid base plus a JSON-patch mutation and must
                       fail with EXACTLY the declared (keyword, instance
                       path) errors — so a fixture that fails for an
                       unrelated reason does not pass. Errors are counted,
                       not collapsed into a set: two errors with one
                       signature are declared twice, because one signature
                       is never proof that only one rule failed (Astra 0c
                       review C1).
     Every schema needs at least one valid fixture.
  4. The SQLite this runs on passes the store's compatibility gate
     (gen2/store/compat.py: numeric version floor, JSON functions answering
     correctly — every json_* function the DDL uses must have a probe there),
     the same gate the store's open path runs; then gen2/store/schema.sql
     executes on an empty in-memory SQLite database opened with
     gen2/store/connection.sql through that gate (every pragma it sets, and
     foreign_keys/recursive_triggers, must read back as on); every table is
     STRICT, is preceded by a `-- trace:` comment and has
     a BEFORE DELETE trigger that raises ABORT; no constraint carries an
     ON CONFLICT clause (which would turn a plain INSERT into a REPLACE); and
     every foreign key targets an existing primary key or unique index.

Uses the `jsonschema` package (dev-only; see gen2/requirements-dev.txt) as the
independent metaschema/validation oracle. The `date-time` format is asserted
with gen2/core/instants.py:is_utc_instant — the same calendar validator the
router boundary uses (A11) — so a fixture naming February 31 fails. Gen-2 runtime code never imports it
(the boundary graph forbids third-party imports).

Trace: task 0a deliverables 2-4.
"""
from __future__ import annotations

import argparse
import collections
import copy
import json
import re
import sqlite3
import sys
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent.parent  # gen2.store.compat comes from here, whatever --root names
DRAFT = "https://json-schema.org/draft/2020-12/schema"
ID_BASE = "https://research-loops.invalid/gen2/schema/"
REQUIRED_TRACE_KEYS = ("flow", "boundaries")
KNOWN_TRACE_KEYS = {"flow", "boundaries", "adjudication", "design-review", "methodology", "invariants", "note"}


def _no_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)


def parse_trace(comment: str) -> dict[str, list[str]]:
    trace: dict[str, list[str]] = {}
    for part in comment.split(" | "):
        key, sep, value = part.partition(":")
        if not sep:
            raise ValueError(f"trace segment {part!r} is not `key: values`")
        key = key.strip()
        if key not in KNOWN_TRACE_KEYS:
            raise ValueError(f"unknown trace key {key!r}")
        trace[key] = [v.strip() for v in value.split(";") if v.strip()]
    return trace


def iter_refs(node, pointer=""):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield pointer, value
            else:
                yield from iter_refs(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from iter_refs(value, f"{pointer}/{i}")


def _pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"bad JSON pointer {pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]


def apply_patch(doc, patch: list[dict]):
    """Minimal RFC 6902 subset: add, remove, replace."""
    doc = copy.deepcopy(doc)
    for op in patch:
        tokens = _pointer_tokens(op["path"])
        if not tokens:
            raise ValueError("patching the document root is not supported")
        parent = doc
        for token in tokens[:-1]:
            parent = parent[int(token)] if isinstance(parent, list) else parent[token]
        last = tokens[-1]
        kind = op["op"]
        if isinstance(parent, list):
            if kind == "add":
                parent.append(op["value"]) if last == "-" else parent.insert(int(last), op["value"])
            elif kind == "remove":
                del parent[int(last)]
            elif kind == "replace":
                parent[int(last)] = op["value"]
            else:
                raise ValueError(f"unsupported patch op {kind!r}")
        else:
            if kind == "remove" or kind == "replace":
                if last not in parent:
                    raise ValueError(f"patch path {op['path']!r} does not exist")
            if kind in ("add", "replace"):
                parent[last] = op["value"]
            elif kind == "remove":
                del parent[last]
            else:
                raise ValueError(f"unsupported patch op {kind!r}")
    return doc


def error_signature(error) -> tuple[str, str]:
    path = "".join(f"/{p}" for p in error.absolute_path)
    return error.validator, path


def check_schemas(root: Path, headings: set[str]) -> tuple[list[str], int, int]:
    try:
        import jsonschema
    except ImportError:
        print(
            "SCHEMA CHECK ERROR: the `jsonschema` package is required for schema validation "
            "(run through `make gen2-check`, which builds the hash-locked .venv-gen2 environment: docs/gen2/ENVIRONMENT.md). "
            "Refusing to report success without it.",
            file=sys.stderr,
        )
        sys.exit(2)
    failures: list[str] = []
    schema_dir = root / "gen2" / "schema"
    files = sorted(schema_dir.glob("*.schema.json"))
    if not files:
        return [f"{schema_dir.relative_to(root)}: no *.schema.json files"], 0, 0
    store: dict[str, dict] = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            schema = load_json(path)
        except ValueError as exc:
            failures.append(f"{rel}: invalid JSON: {exc}")
            continue
        if schema.get("$schema") != DRAFT:
            failures.append(f"{rel}: $schema must be {DRAFT}")
        if schema.get("$id") != ID_BASE + path.name:
            failures.append(f"{rel}: $id must be {ID_BASE + path.name}")
        comment = schema.get("$comment")
        if not isinstance(comment, str):
            failures.append(f"{rel}: missing top-level $comment trace header")
        else:
            try:
                trace = parse_trace(comment)
            except ValueError as exc:
                failures.append(f"{rel}: $comment trace header: {exc}")
                trace = {}
            for key in REQUIRED_TRACE_KEYS:
                if trace and not trace.get(key):
                    failures.append(f"{rel}: $comment trace header lacks `{key}:`")
            for name in trace.get("boundaries", []):
                if name != "none" and name not in headings:
                    failures.append(f"{rel}: $comment names BOUNDARIES.md component {name!r}, which is not a `## ` heading (BOUNDARY-DRIFT)")
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            failures.append(f"{rel}: fails the 2020-12 metaschema: {exc.message} at {'/'.join(map(str, exc.absolute_path))}")
        store[schema.get("$id", rel)] = schema
    sys.path.insert(0, str(root))
    from gen2.core.instants import is_utc_instant

    format_checker = jsonschema.FormatChecker(formats=())

    @format_checker.checks("date-time")
    def _utc_instant(instance) -> bool:
        return not isinstance(instance, str) or is_utc_instant(instance)

    resolvers = {}
    for sid, schema in store.items():
        resolver = jsonschema.RefResolver(base_uri=sid, referrer=schema, store=store)
        resolvers[sid] = resolver
        for pointer, ref in iter_refs(schema):
            try:
                resolver.resolve(ref)  # relative to this file's $id (no nested $id is used)
            except Exception as exc:  # RefResolutionError and friends
                failures.append(f"{sid.removeprefix(ID_BASE)}{pointer}: unresolvable $ref {ref!r}: {exc}")

    def validator_for(target: str):
        name, _, fragment = target.partition("#")
        sid = ID_BASE + name
        if sid not in store:
            raise KeyError(f"unknown schema {name!r}")
        schema = store[sid]
        if fragment:
            _, sub = resolvers[sid].resolve(f"{sid}#{fragment}")
            schema = sub
        return jsonschema.Draft202012Validator(schema, resolver=resolvers[sid], format_checker=format_checker)

    n_valid = n_invalid = 0
    examples = schema_dir / "examples"
    stems_with_valid: set[str] = set()
    for fixture_path in sorted(examples.rglob("*.json")) if examples.is_dir() else []:
        rel = fixture_path.relative_to(root).as_posix()
        try:
            fixture = load_json(fixture_path)
            meta = fixture["fixture"]
            target = meta["schema"]
            expect = meta["expect"]
            if not meta.get("tests"):
                raise ValueError("fixture.tests must say which invariant/rule it exercises")
        except (ValueError, KeyError, TypeError) as exc:
            failures.append(f"{rel}: malformed fixture: {exc}")
            continue
        if not fixture_path.name.startswith(f"{expect}-"):
            failures.append(f"{rel}: file name must start with '{expect}-'")
            continue
        try:
            validator = validator_for(target)
        except Exception as exc:
            failures.append(f"{rel}: cannot build validator for {target!r}: {exc}")
            continue
        if expect == "valid":
            instance = fixture.get("instance")
            errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
            if errors:
                detail = "; ".join(f"{e.validator} at {error_signature(e)[1] or '/'}: {e.message[:160]}" for e in errors[:5])
                failures.append(f"{rel}: expected valid, got {len(errors)} error(s): {detail}")
            if target.partition("#")[0] == fixture_path.parent.name + ".schema.json":
                stems_with_valid.add(fixture_path.parent.name)
            n_valid += 1
        elif expect == "invalid":
            try:
                base = load_json(fixture_path.parent / meta["base"])
                if base["fixture"]["schema"] != target or base["fixture"]["expect"] != "valid":
                    raise ValueError("base must be a valid fixture for the same schema target")
                instance = apply_patch(base["instance"], meta["patch"])
                expected = collections.Counter((e["keyword"], e["path"]) for e in meta["errors"])
            except (ValueError, KeyError, TypeError, IndexError, FileNotFoundError) as exc:
                failures.append(f"{rel}: malformed invalid fixture: {exc}")
                continue
            if not expected:
                failures.append(f"{rel}: invalid fixture must declare its expected errors")
                continue
            actual = collections.Counter(error_signature(e) for e in validator.iter_errors(instance))
            if actual != expected:
                failures.append(
                    f"{rel}: expected exactly {sorted(expected.elements())}, "
                    f"got {sorted(actual.elements()) or 'no errors (instance validated)'}"
                )
            n_invalid += 1
        else:
            failures.append(f"{rel}: fixture.expect must be 'valid' or 'invalid'")
    for path in files:
        stem = path.name.removesuffix(".schema.json")
        if stem not in stems_with_valid:
            failures.append(f"gen2/schema/{path.name}: no valid fixture under gen2/schema/examples/{stem}/")
    return failures, n_valid, n_invalid


def _compat():
    """The store's SQLite gate: the repository's gen2.store.compat (from the
    import path when one is given, else from this tool's own checkout)."""
    try:
        from gen2.store import compat
    except ImportError:
        sys.path.insert(0, str(TOOL_ROOT))
        from gen2.store import compat
    return compat


def _strip_sql_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def check_ddl(root: Path) -> tuple[list[str], int]:
    rel = "gen2/store/schema.sql"
    conn_rel = "gen2/store/connection.sql"
    path = root / rel
    if not path.exists():
        return [f"{rel}: not found"], 0
    if not (root / conn_rel).exists():
        return [f"{conn_rel}: not found"], 0
    text = path.read_text(encoding="utf-8")
    failures: list[str] = []
    compat = _compat()
    unprobed = sorted(compat.json_functions_used(text) - {name for name, _, _ in compat.JSON_PROBES})
    if unprobed:
        failures.append(f"{rel}: uses JSON function(s) {unprobed} that the compatibility gate does not probe (add them to gen2/store/compat.py JSON_PROBES)")
    conn = sqlite3.connect(":memory:")
    try:
        compat.check_library(conn)
    except compat.StoreCompatibilityError as exc:
        conn.close()
        return [f"SQLite compatibility gate refused this build's SQLite: {exc}"], 0
    try:
        compat.apply_connection_contract(conn, (root / conn_rel).read_text(encoding="utf-8"))
    except compat.StoreCompatibilityError as exc:
        failures.append(f"{conn_rel}: {exc.fact['detail']}")
    try:
        conn.executescript(text)
    except sqlite3.Error as exc:
        return failures + [f"{rel}: does not execute on SQLite {sqlite3.sqlite_version}: {exc}"], 0
    if re.search(r"\bON\s+CONFLICT\b", _strip_sql_comments(text), re.IGNORECASE):
        failures.append(f"{rel}: an ON CONFLICT clause in the DDL would let a plain INSERT replace a stored row (INVARIANTS C-11)")
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        strict = conn.execute("SELECT strict FROM pragma_table_list WHERE name = ?", (table,)).fetchone()
        if not strict or strict[0] != 1:
            failures.append(f"{rel}: table {table} is not STRICT")
    for match in re.finditer(r"CREATE TABLE (\w+)", text):
        preceding = text[: match.start()].rstrip().splitlines()  # the whole contiguous comment block above
        block = []
        for line in reversed(preceding):
            if not line.startswith("--"):
                break
            block.append(line)
        if not any(line.lower().startswith("-- trace:") for line in block):
            failures.append(f"{rel}: CREATE TABLE {match.group(1)} lacks a `-- trace:` comment directly above it")
    triggers = conn.execute("SELECT tbl_name, sql FROM sqlite_schema WHERE type = 'trigger'").fetchall()
    for table in tables:
        guarded = any(
            tbl == table
            and re.search(r"\bBEFORE\s+DELETE\s+ON\s+" + re.escape(table) + r"\b", sql, re.IGNORECASE)
            and re.search(r"RAISE\s*\(\s*ABORT", sql, re.IGNORECASE)
            and not re.search(r"\bWHEN\b", sql.split("BEGIN", 1)[0], re.IGNORECASE)
            for tbl, sql in triggers
        )
        if not guarded:
            failures.append(f"{rel}: table {table} has no unconditional BEFORE DELETE ... RAISE(ABORT) guard, so a delete or REPLACE could rewrite it (INVARIANTS C-11)")
    for table in tables:
        fks = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        groups: dict[int, list] = {}
        for row in fks:
            groups.setdefault(row[0], []).append(row)
        for rows in groups.values():
            parent = rows[0][2]
            parent_cols = [r[4] for r in rows]
            if parent not in tables:
                failures.append(f"{rel}: {table} has a foreign key to missing table {parent}")
                continue
            pk = [r[1] for r in sorted(conn.execute(f"PRAGMA table_info({parent})").fetchall(), key=lambda r: r[5]) if r[5] > 0]
            if None in parent_cols:
                parent_cols = pk
            ok = sorted(parent_cols) == sorted(pk)
            if not ok:
                for idx in conn.execute(f"PRAGMA index_list({parent})").fetchall():
                    if idx[2] and not idx[4]:  # unique and not partial
                        cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx[1]})").fetchall()]
                        if sorted(cols) == sorted(parent_cols):
                            ok = True
                            break
            if not ok:
                failures.append(f"{rel}: {table} foreign key -> {parent}({', '.join(parent_cols)}) does not target a primary key or full unique index")
    conn.close()
    return failures, len(tables)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--part", choices=("all", "schemas", "ddl"), default="all")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    failures: list[str] = []
    summary: list[str] = []
    if args.part in ("all", "schemas"):
        doc = root / "docs" / "gen2" / "BOUNDARIES.md"
        headings = {line[3:].strip() for line in doc.read_text(encoding="utf-8").splitlines() if line.startswith("## ")}
        schema_failures, n_valid, n_invalid = check_schemas(root, headings)
        failures += schema_failures
        n_schemas = len(list((root / "gen2" / "schema").glob("*.schema.json")))
        summary.append(
            f"{n_schemas} schemas pass the 2020-12 metaschema with resolvable refs; "
            f"{n_valid} valid and {n_invalid} invalid fixtures behave as declared"
        )
    if args.part in ("all", "ddl"):
        ddl_failures, n_tables = check_ddl(root)
        failures += ddl_failures
        summary.append(f"DDL creates {n_tables} STRICT tables on SQLite {sqlite3.sqlite_version} (compatibility gate passed)")
    for failure in failures:
        print(f"SCHEMA CHECK FAILURE: {failure}", file=sys.stderr)
    if failures:
        print(f"gen2 schema check FAILED: {len(failures)} failure(s)", file=sys.stderr)
        return 1
    print("gen2 schema check OK: " + "; ".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
