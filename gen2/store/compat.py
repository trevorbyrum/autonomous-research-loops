"""SQLite compatibility gate for the gen-2 store.

Every route to a store (the store module's open_store, and adopt_in_memory
for a test fixture's in-memory store) and the build route (`make
gen2-sqlite`, and tools/check_gen2_schemas.py before it runs the DDL) calls
these same functions, so the library the build accepts is the library the
runtime accepts.

Trace: Astra third review (gen2-0a-repair-3), ruling 4 — hard and not
deferrable: before 0b creates or admits a durable store, check the linked
SQLite version numerically against the documented floor, verify JSON is
actually present, apply and read back the connection pragmas, refuse loudly;
task 0b; docs/gen2/ENVIRONMENT.md "SQLite version floor"; flow §4.2
(capability facts are first-class, dated and loud); INVARIANTS C-11, H-2.

The checks, in order. None substitutes for another:
  1. Version. The linked library's own `sqlite_version()`, parsed into
     integers and compared as a tuple with SQLITE_FLOOR. 3.45.1 is the only
     version the complete DDL and suite have run on (ENVIRONMENT.md). A
     string comparison would rank "3.9.0" above "3.45.1".
  2. JSON. Each JSON function the DDL uses is executed on a known input and
     its answer compared. SQLite can be compiled without JSON at any version
     (SQLITE_OMIT_JSON), so the version alone does not establish it, and a
     function that exists but answers wrongly is refused too.
     json_functions_used() lists the json_* names in the DDL; the build
     fails if one has no probe here (tools/check_gen2_schemas.py).
  3. Connection contract. connection.sql is applied and every pragma it sets
     reads back as 1. REQUIRED_PRAGMAS must be among them, so a contract file
     that drops one is refused rather than trusted.

A failure raises StoreCompatibilityError. Its `fact` has the capability_facts
row shape (capability, state, detail, since, last_success_at,
affected_lanes, recorded_at). It is not written to the store, because the
store is exactly what cannot be trusted at that point. `since` is when the
failure was observed. The first failure time is unknown, so it is not
claimed, and `last_success_at` is null (unknown, not "never").
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SQLITE_FLOOR = (3, 45, 1)
CAPABILITY = "store.sqlite"
AFFECTED_LANES = ("store",)
REQUIRED_PRAGMAS = ("foreign_keys", "recursive_triggers")
CONNECTION_CONTRACT = Path(__file__).resolve().parent / "connection.sql"

# (function, probe SQL, expected rows). Inputs are literals, and the expected
# answers are SQLite's documented results, written by hand.
JSON_PROBES: tuple[tuple[str, str, list[tuple]], ...] = (
    ("json_valid", """SELECT json_valid('{"a":[1,2]}'), json_valid('{"a":')""", [(1, 0)]),
    ("json_extract", """SELECT json_extract('{"a":[1,{"b":"x"}]}', '$.a[1].b'), json_extract('{"a":2}', '$.missing')""", [("x", None)]),
    ("json_type", """SELECT json_type('{"a":[1]}', '$.a'), json_type('{"a":null}', '$.a'), json_type('{"a":1}', '$.b')""", [("array", "null", None)]),
    ("json_array_length", """SELECT json_array_length('[1,2,3]'), json_array_length('{"a":[1]}', '$.a')""", [(3, 1)]),
    ("json_remove", """SELECT json_remove('{"a":1,"b":2}', '$.a')""", [('{"b":2}',)]),
    ("json_each", """SELECT key, value FROM json_each('{"a":1,"b":"x"}') ORDER BY key""", [("a", 1), ("b", "x")]),
)

_VERSION = re.compile(r"\A([0-9]+)\.([0-9]+)\.([0-9]+)\Z")
_PRAGMA_ON = re.compile(r"^\s*PRAGMA\s+(\w+)\s*=\s*ON\s*;\s*$", re.IGNORECASE | re.MULTILINE)
_JSON_NAME = re.compile(r"\bjson_\w+\b")


class StoreCompatibilityError(RuntimeError):
    """The linked SQLite (or this connection) cannot hold the gen-2 store."""

    def __init__(self, fact: dict) -> None:
        super().__init__(f"{fact['capability']} {fact['state']} since {fact['since']}: {fact['detail']}")
        self.fact = fact


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def capability_fact(state: str, detail: str, observed: dict) -> dict:
    now = _now()
    return {"capability": CAPABILITY, "state": state, "detail": detail, "since": now, "last_success_at": None,
            "affected_lanes": list(AFFECTED_LANES), "recorded_at": now, "observed": observed,
            "required": {"sqlite_floor": ".".join(map(str, SQLITE_FLOOR)), "json_functions": [p[0] for p in JSON_PROBES],
                         "pragmas": list(REQUIRED_PRAGMAS)}}


def parse_version(text: object) -> tuple[int, int, int]:
    """'3.45.1' -> (3, 45, 1). Anything else is refused, never guessed."""
    match = _VERSION.match(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f"unparseable SQLite version {text!r}")
    return tuple(int(part) for part in match.groups())


def meets_floor(version: tuple[int, int, int]) -> bool:
    return version >= SQLITE_FLOOR


def json_functions_used(ddl_text: str) -> set[str]:
    """Every json_* function name in the DDL (comments excluded)."""
    code = "\n".join(line.split("--", 1)[0] for line in ddl_text.splitlines())
    return set(_JSON_NAME.findall(code))


def pragmas_set_by(contract_text: str) -> list[str]:
    return [name.lower() for name in _PRAGMA_ON.findall(contract_text)]


def check_library(conn: sqlite3.Connection) -> dict:
    """Checks 1 and 2 on `conn`. Returns what was observed; raises
    StoreCompatibilityError (with a dated capability fact) on any failure."""
    observed: dict = {"python_sqlite3_module_version": sqlite3.sqlite_version}
    try:
        reported = conn.execute("SELECT sqlite_version()").fetchone()[0]
    except sqlite3.Error as exc:
        raise StoreCompatibilityError(capability_fact("failing", f"cannot read sqlite_version(): {exc}", observed)) from exc
    observed["sqlite_version"] = reported
    try:
        version = parse_version(reported)
    except ValueError as exc:
        raise StoreCompatibilityError(capability_fact("failing", str(exc), observed)) from exc
    if not meets_floor(version):
        raise StoreCompatibilityError(capability_fact(
            "failing", f"SQLite {reported} is below the supported floor {'.'.join(map(str, SQLITE_FLOOR))} (docs/gen2/ENVIRONMENT.md)", observed))
    failures = []
    for name, sql, expected in JSON_PROBES:
        try:
            got = [tuple(row) for row in conn.execute(sql).fetchall()]
        except sqlite3.Error as exc:
            failures.append(f"{name}: {exc}")
            continue
        if got != expected:
            failures.append(f"{name}: answered {got!r}, expected {expected!r}")
    observed["json_probes"] = "failed" if failures else "passed"
    if failures:
        raise StoreCompatibilityError(capability_fact(
            "failing", "JSON support is missing or wrong in this SQLite build: " + "; ".join(failures), observed))
    return observed


def apply_connection_contract(conn: sqlite3.Connection, contract_text: str | None = None) -> dict:
    """Check 3: execute the connection contract, then read back every pragma
    it sets and every REQUIRED_PRAGMAS entry. Returns {pragma: value}."""
    text = CONNECTION_CONTRACT.read_text(encoding="utf-8") if contract_text is None else contract_text
    observed: dict = {}
    try:
        conn.executescript(text)
    except sqlite3.Error as exc:
        raise StoreCompatibilityError(capability_fact("failing", f"the connection contract does not execute: {exc}", observed)) from exc
    failures = []
    for pragma in dict.fromkeys([*REQUIRED_PRAGMAS, *pragmas_set_by(text)]):
        row = conn.execute(f"PRAGMA {pragma}").fetchone()
        observed[pragma] = None if row is None else row[0]
        if row != (1,):
            failures.append(f"PRAGMA {pragma} does not read back as 1 after applying the connection contract")
    if failures:
        raise StoreCompatibilityError(capability_fact("failing", "; ".join(failures), {"pragmas": observed}))
    return observed


def check_connection(conn: sqlite3.Connection, contract_text: str | None = None) -> dict:
    """All three checks on one connection. Returns the observation record."""
    observed = check_library(conn)
    observed["pragmas"] = apply_connection_contract(conn, contract_text)
    return observed


def main(argv: list[str] | None = None) -> int:
    """`make gen2-sqlite`: run the gate on this interpreter's SQLite and print
    the observation (JSON) — the record of what a build actually ran on.
    --report PATH also appends it there (CI: the job summary)."""
    import argparse

    parser = argparse.ArgumentParser(description="gen-2 SQLite compatibility gate")
    parser.add_argument("--report", type=Path, help="also append the observation to this file")
    args = parser.parse_args(argv)
    conn = sqlite3.connect(":memory:")
    try:
        record = capability_fact("healthy", "SQLite compatibility gate passed", check_connection(conn))
        record["last_success_at"] = record["since"]
        status = 0
    except StoreCompatibilityError as exc:
        record, status = exc.fact, 1
    finally:
        conn.close()
    text = json.dumps(record, indent=2, sort_keys=True)
    print(text, file=sys.stdout if status == 0 else sys.stderr)
    if args.report is not None:
        with args.report.open("a", encoding="utf-8") as handle:
            handle.write(f"### gen-2 SQLite compatibility gate\n\n```json\n{text}\n```\n")
    if status:
        print(f"gen2 SQLite gate REFUSED: {record['detail']}", file=sys.stderr)
    else:
        print(f"gen2 SQLite gate OK: SQLite {record['observed']['sqlite_version']} (floor {record['required']['sqlite_floor']}), "
              f"JSON probes passed, pragmas {record['observed']['pragmas']}", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main())
