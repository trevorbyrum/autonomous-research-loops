"""The gen-2 store's connection layer: the one way a durable store is created
or opened.

open_store runs the SQLite compatibility gate (gen2/store/compat.py) on an
in-memory connection before it creates or opens anything on disk:
`sqlite3.connect(path)` creates the file at once, so it cannot come first. It
then opens the path (creating it only when asked, refusing a missing store
otherwise), re-runs the gate on that durable connection with the connection
contract applied and read back, and admits the store only if its schema is
exactly the DDL in gen2/store/schema/ (schema_text: its parts, in order).

Trace: Astra third review ruling 4 (compatibility enforced in the common
store initialization path before a durable store is created or admitted);
task 0b ("open, validate compatibility, expose read/write primitives that
respect the DDL's own guards"); INVARIANTS C-11 (connection contract), §11.2
(a missing store is a startup error, not a mode), C-8 (short transactions);
gen2/store/schema/01-queue-and-contracts.sql header (the store module adds
WAL, synchronous FULL, busy_timeout).

Not here: router logic, scheduling, decisions (Phase 1+). This module holds
the connection; the router is its only intended caller (boundaries.toml).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from gen2.store import compat

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"  # the DDL's parts; order.txt declares their order
BUSY_TIMEOUT_MS = 5000
# Operational settings (they do not change which rows the schema admits, so
# they are not in connection.sql), each read back after it is set.
OPERATIONAL_PRAGMAS = (("journal_mode", "WAL", "wal"), ("synchronous", "FULL", 2), ("busy_timeout", str(BUSY_TIMEOUT_MS), BUSY_TIMEOUT_MS))


def schema_parts(schema_dir: Path = SCHEMA_DIR) -> list[Path]:
    """The DDL's parts, in the order schema_dir/order.txt declares them (one
    file name per line; blank lines and # comments ignored)."""
    names = [line.strip() for line in (schema_dir / "order.txt").read_text(encoding="utf-8").splitlines()]
    return [schema_dir / name for name in names if name and not name.startswith("#")]


def schema_text(schema_dir: Path = SCHEMA_DIR) -> str:
    """The DDL the store applies: its parts joined in their declared order,
    executed as one script (task 2r split the one schema.sql into these parts
    so that no file passes the 1,500-line limit; their join is its text)."""
    return "".join(part.read_text(encoding="utf-8") for part in schema_parts(schema_dir))


class StoreOpenError(RuntimeError):
    """The path does not hold (or cannot become) a gen-2 store."""


def _schema_objects(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    rows = conn.execute("SELECT type, name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchall()
    return {(kind, name): sql for kind, name, sql in rows}


def reference_schema(ddl_text: str | None = None) -> tuple[dict[tuple[str, str], str], int]:
    """The objects and user_version the DDL produces on a fresh connection."""
    conn = sqlite3.connect(":memory:")
    try:
        compat.apply_connection_contract(conn)
        conn.executescript(schema_text() if ddl_text is None else ddl_text)
        return _schema_objects(conn), conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def check_schema_identity(conn: sqlite3.Connection, ddl_text: str | None = None) -> None:
    expected, version = reference_schema(ddl_text)
    actual = _schema_objects(conn)
    missing = sorted(f"{k} {n}" for k, n in expected.keys() - actual.keys())
    extra = sorted(f"{k} {n}" for k, n in actual.keys() - expected.keys())
    changed = sorted(f"{k} {n}" for (k, n) in expected.keys() & actual.keys() if expected[(k, n)] != actual[(k, n)])
    stored_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if missing or extra or changed or stored_version != version:
        raise StoreOpenError(
            f"store schema is not the DDL in gen2/store/schema/ (user_version {stored_version}, expected {version}; "
            f"missing {missing[:5]}{'...' if len(missing) > 5 else ''}, unexpected {extra[:5]}, changed {changed[:5]})")


def _apply_operational(conn: sqlite3.Connection) -> dict:
    observed = {}
    for name, value, expected in OPERATIONAL_PRAGMAS:
        got = conn.execute(f"PRAGMA {name} = {value}").fetchone()
        got = conn.execute(f"PRAGMA {name}").fetchone() if got is None else got
        observed[name] = got[0]
        if got[0] != expected:
            raise StoreOpenError(f"PRAGMA {name} = {value} reads back {got[0]!r}, expected {expected!r}")
    return observed


def connect(path: str | Path, *, create: bool = False) -> tuple[sqlite3.Connection, dict]:
    """Open (or, with create=True, create) the durable store at `path` and
    return (connection, observation). The compatibility gate runs before the
    path is touched; see the module docstring for the order."""
    probe = sqlite3.connect(":memory:")
    try:
        compat.check_connection(probe)  # the library itself; nothing on disk exists or is opened yet
    finally:
        probe.close()
    path = Path(path)
    if create and path.exists():
        raise StoreOpenError(f"{path}: already exists; open it (create=False) instead of creating over it")
    if not create and not path.is_file():
        raise StoreOpenError(f"{path}: no store here. A missing store is a startup error, not a mode (INVARIANTS §11.2); create one explicitly")
    uri = path.resolve().as_uri() + ("?mode=rwc" if create else "?mode=rw")
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        observed = compat.check_connection(conn)  # the durable connection: contract applied and read back here
        observed["operational"] = _apply_operational(conn)
        if create:
            try:
                conn.executescript("BEGIN IMMEDIATE;\n" + schema_text() + "\nCOMMIT;\n")
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        check_schema_identity(conn)
    except BaseException:
        conn.close()
        raise
    return conn, observed
