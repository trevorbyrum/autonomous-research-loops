"""The gen-2 store's read/write primitives (task 0b: the connection/schema
layer only — open, validate compatibility, read and write rows under the
DDL's own guards).

What every write does before any SQL runs, so a refused value leaves no
partial row:
  * JSON columns (those the DDL checks with json_valid) are stored as their
    RFC 8785 JCS serialization, via gen2/core/canonical.py. A caller may
    pass the parsed value or JSON text. Either way the stored text is the
    canonicalizer's output, never the caller's text, so storage format does
    not depend on each writer's discipline (the 0a review cycle's carried
    requirement: schema validation alone does not enforce storage form).
    Duplicate keys, non-finite numbers and precision-losing numerals are
    refused, as in canonical.parse_json_strict.
  * INTEGER columns are bounded by value. Identity, revision, generation and
    counter columns (IDENTITY_COLUMNS) go through canonical.identity_integer:
    [0, 2**53-1], whatever notation the value arrived in (Astra re-review
    RA8 — the bound is enforced at the schema/helper layer and applied by
    every writer, including this one; the DDL's 64-bit INTEGER would accept
    2**53). Other integers are JSON-interoperable (|v| <= 2**53-1), and
    their ranges are the DDL's. Every INTEGER column in the DDL must be
    classified here (a test enforces it).
  * Generated increments (next_in_sequence, advance) apply the same bound
    to the value they generate, before it is written.
  * Receipts record the frozen hashing contract their hashes were computed
    under (Astra 0a ruling R1, frozen in 0b): a commit receipt's
    hash_contract is FROZEN_HASH_CONTRACTS["operation_receipts"]
    (canonicalization and request fingerprint), and a decision receipt's is
    the canonicalization alone (its spec_hash is logical; it has no
    fingerprint). The DDL admits only these versions too; this check ties
    them to the versions canonical.py actually computes.

Writes run only inside transaction() (BEGIN IMMEDIATE ... COMMIT), and a
failure anywhere in it, COMMIT included, leaves nothing written (INVARIANTS
C-4: one short transaction; C-8: none spans a subprocess or network call —
that is the caller's discipline). COMMIT is where SQLite checks deferred
foreign keys (a capability fact's successor link), so it can refuse too, and
it is inside the rollback path (Astra 0b review A1). The DDL's guards are the
authority on what a row may be. Their refusals (sqlite3.IntegrityError)
propagate unchanged, and the store never retries a refused write or resolves
a conflict by REPLACE (C-11; the boundary lint forbids REPLACE in this
module).

A Store exists only through a checked route (Astra 0b review A4): open_store
(a durable store, through db.connect) or adopt_in_memory (an in-memory
connection a test fixture built, through the same compatibility gate and
schema-identity check). The constructor refuses any other caller, so a raw
connection plus a caller-supplied "compatibility" dict is not a store.

Not here (Phase 1+): commit_outcome, routing, scheduling, decisions,
hash-truth recomputation (the router boundary's).
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping

from gen2.core import canonical
from gen2.core.canonical import CanonicalizationError
from gen2.store import compat, db

# RA8: identity, revision, generation and counter columns, bounded to
# [0, 2**53-1] by canonical.identity_integer, by value, in every table.
IDENTITY_COLUMNS = frozenset({
    "revision", "parent_revision", "protocol_revision", "framing_version", "contract_revision", "active_contract_revision",
    "claim_revision", "dossier_revision", "evidence_revision", "source_revision", "subject_revision", "state_revision",
    "state_revision_before", "state_revision_after", "generation", "lease_generation", "supersedes_generation",
    "delivered_generation", "unknown_episode", "seq", "ordinal", "brief_version", "template_version", "policy_version",
    "eligibility_protocol_version", "attempt", "version", "parent_version",
})
FLAG_COLUMNS = frozenset({"load_bearing", "blind_sample", "exploratory", "quote_quarantined", "tombstones_acknowledged"})
SCORE_COLUMNS = frozenset({"proposed_importance_score", "operator_importance_score"})  # 1-9, the DDL's CHECKs
MEASURE_COLUMNS = frozenset({"size_bytes", "priority", "result_count", "cost_units", "rank", "span_start", "span_end"})

# The hashing contracts each receipt table's JSON records (INVARIANTS C-13).
# Verification receipts hold byte digests only, so they record none.
FROZEN_HASH_CONTRACTS = {
    "operation_receipts": {"canonicalization": canonical.CANONICALIZATION, "fingerprint": canonical.FINGERPRINT_CONTRACT},
    "decision_receipts": {"canonicalization": canonical.CANONICALIZATION},
}


class StoreWriteError(ValueError):
    """A write refused by the store module before any SQL ran."""


class IdentityBoundError(StoreWriteError):
    """An identity/revision/generation value outside [0, 2**53-1]."""


def _json_columns(create_sql: str) -> frozenset[str]:
    return frozenset(re.findall(r"json_valid\((\w+)\)", create_sql))


# Held only by this module's checked routes (open_store, adopt_in_memory).
_ADMITTED = object()


class Store:
    """One open, compatibility-checked, schema-identical store connection.
    Constructed by open_store or adopt_in_memory only."""

    def __init__(self, conn: sqlite3.Connection, compatibility: dict, *, _admitted_by: object = None) -> None:
        if _admitted_by is not _ADMITTED:
            raise db.StoreOpenError("a Store is made by open_store() or adopt_in_memory(), which check the connection; "
                                    "a connection and a compatibility dict supplied by the caller are not evidence (A4)")
        self._conn = conn
        self.compatibility = compatibility
        self._in_transaction = False  # inside this Store's own transaction() context
        self._unusable: str | None = None  # why the connection was closed after a failed rollback
        self._columns: dict[str, dict[str, str]] = {}
        self._json: dict[str, frozenset[str]] = {}
        for table, sql in conn.execute("SELECT name, sql FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
            self._columns[table] = {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({table})")}
            self._json[table] = _json_columns(sql)

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator["Store"]:
        """BEGIN IMMEDIATE ... COMMIT. An exception in the body or from COMMIT
        itself ends the transaction with nothing written (_end_failed), and
        that exception is what propagates."""
        self._require_usable()
        if self._conn.in_transaction or self._in_transaction:
            raise StoreWriteError("transactions do not nest")
        self._conn.execute("BEGIN IMMEDIATE")
        self._in_transaction = True
        try:
            yield self
            self._conn.execute("COMMIT")
        except BaseException as exc:
            self._end_failed(exc)
            raise
        finally:
            self._in_transaction = False

    def _end_failed(self, exc: BaseException) -> None:
        """Roll back a failed transaction, if SQLite still holds it open. Some
        failures end it on SQLite's side (an interrupt, SQLITE_FULL, an I/O
        error), and an unconditional ROLLBACK would then raise its own error
        in place of `exc`. If ROLLBACK fails, this connection cannot be shown
        to hold nothing: it is closed (SQLite discards an uncommitted
        transaction on close), this Store refuses further use, and `exc`
        carries a note saying so."""
        if not self._conn.in_transaction:
            return
        try:
            self._conn.execute("ROLLBACK")
        except BaseException as rollback_error:
            self._close_unusable(f"ROLLBACK failed ({rollback_error!r})", exc)

    def _close_unusable(self, reason: str, exc: BaseException) -> None:
        self._unusable = reason
        try:
            self._conn.close()
        except BaseException as close_error:
            reason += f"; closing the connection also failed ({close_error!r})"
            self._unusable = reason
        exc.add_note(f"gen2 store: {reason}. The connection was closed, and this Store refuses further use")

    def _require_usable(self) -> None:
        if self._unusable is not None:
            raise StoreWriteError(f"this Store's connection was closed after a failed transaction: {self._unusable}")

    # -- value preparation -------------------------------------------------
    def _check_names(self, table: str, columns) -> dict[str, str]:
        if table not in self._columns:
            raise StoreWriteError(f"unknown table {table!r}")
        known = self._columns[table]
        for column in columns:
            if column not in known:
                raise StoreWriteError(f"{table} has no column {column!r}")
        return known

    def _prepare(self, table: str, column: str, value: object) -> object:
        if value is None:
            return None
        if column in self._json[table]:
            try:
                parsed = canonical.parse_json_strict(value) if isinstance(value, (str, bytes)) else value
                return canonical.canonical_bytes(parsed).decode("utf-8")
            except CanonicalizationError as exc:
                raise StoreWriteError(f"{table}.{column}: {exc}") from exc
        if self._columns[table][column] == "INTEGER":
            if column in IDENTITY_COLUMNS:
                try:
                    return canonical.identity_integer(value)
                except CanonicalizationError as exc:
                    raise IdentityBoundError(f"{table}.{column}: {exc}") from exc
            if isinstance(value, bool):
                if column in FLAG_COLUMNS:
                    return int(value)
                raise StoreWriteError(f"{table}.{column}: a boolean is not an integer here")
            if not isinstance(value, int) or abs(value) > canonical.INT_BOUND:
                raise StoreWriteError(f"{table}.{column}: {value!r} is not an integer within +/-(2**53-1)")
        return value

    def _check_hash_contract(self, table: str, prepared: dict[str, object]) -> None:
        frozen = FROZEN_HASH_CONTRACTS.get(table)
        if frozen is None or prepared.get("receipt") is None:
            return
        recorded = canonical.parse_json_strict(prepared["receipt"]).get("hash_contract")
        if recorded != frozen:
            raise StoreWriteError(f"a {table} receipt records the frozen hash contract {frozen}, not {recorded!r} (C-13)")

    def _require_transaction(self) -> None:
        """Inside this Store's own transaction() context, not merely while
        SQLite reports some transaction open on the connection."""
        self._require_usable()
        if not (self._in_transaction and self._conn.in_transaction):
            raise StoreWriteError("writes run inside Store.transaction()")

    # -- writes ------------------------------------------------------------
    def insert(self, table: str, row: Mapping[str, object]) -> None:
        self._require_transaction()
        self._check_names(table, row)
        if not row:
            raise StoreWriteError("an insert names at least one column")
        prepared = {column: self._prepare(table, column, value) for column, value in row.items()}
        self._check_hash_contract(table, prepared)
        self._conn.execute(f"INSERT INTO {table} ({', '.join(prepared)}) VALUES ({', '.join('?' for _ in prepared)})", list(prepared.values()))

    def update(self, table: str, key: Mapping[str, object], changes: Mapping[str, object], *, expect: Mapping[str, object] | None = None) -> None:
        """UPDATE exactly one row: `key` and `expect` are equality conditions
        (expect is the compare-and-set part, e.g. the state revision the
        caller read); a miss raises and, inside the transaction, rolls back."""
        self._require_transaction()
        expect = expect or {}
        self._check_names(table, [*key, *changes, *expect])
        if not key or not changes:
            raise StoreWriteError("an update names its key and at least one change")
        sets = [self._prepare(table, column, value) for column, value in changes.items()]
        conds = [self._prepare(table, column, value) for column, value in {**key, **expect}.items()]
        where = " AND ".join(f"{column} = ?" for column in {**key, **expect})
        cursor = self._conn.execute(f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in changes)} WHERE {where}", [*sets, *conds])
        if cursor.rowcount != 1:
            raise StoreWriteError(f"update of {table} matched {cursor.rowcount} rows for {dict(key)} with {dict(expect)}; expected exactly one")

    def next_in_sequence(self, table: str, column: str, where: Mapping[str, object]) -> int:
        """max(column) + 1 over the rows matching `where` (1 when there are
        none), bounded before it is returned: a generated identity past
        2**53-1 is refused, never wrapped or written."""
        self._check_names(table, [column, *where])
        if column not in IDENTITY_COLUMNS:
            raise StoreWriteError(f"{column} is not an identity column")
        clause = " AND ".join(f"{c} = ?" for c in where) or "1"
        current = self._conn.execute(f"SELECT max({column}) FROM {table} WHERE {clause}", [self._prepare(table, c, v) for c, v in where.items()]).fetchone()[0]
        try:
            return canonical.identity_integer((current or 0) + 1)
        except CanonicalizationError as exc:
            raise IdentityBoundError(f"{table}.{column}: the next value after {current} {exc}") from exc

    def advance(self, table: str, key: Mapping[str, object], column: str, *, expected: int) -> int:
        """Compare-and-set `column` from `expected` to expected + 1 (a state
        revision, an unknown-episode counter). Both values pass the identity
        bound in update() before the UPDATE runs, so the generated value is
        refused, not written, past 2**53-1."""
        if column not in IDENTITY_COLUMNS or isinstance(expected, bool) or not isinstance(expected, int):
            raise StoreWriteError(f"advance needs an identity column and an integer expected value, not {column!r}={expected!r}")
        self.update(table, key, {column: expected + 1}, expect={column: expected})
        return expected + 1

    # -- reads -------------------------------------------------------------
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]:
        """Rows as dicts; JSON columns come back parsed."""
        where = where or {}
        self._check_names(table, where)
        clause = " AND ".join(f"{c} = ?" for c in where) or "1"
        cursor = self._conn.execute(f"SELECT * FROM {table} WHERE {clause} ORDER BY rowid", [self._prepare(table, c, v) for c, v in where.items()])
        names = [d[0] for d in cursor.description]
        out = []
        for row in cursor.fetchall():
            record = dict(zip(names, row))
            for column in self._json[table]:
                if record.get(column) is not None:
                    record[column] = canonical.parse_json_strict(record[column])
            out.append(record)
        return out

    def raw_text(self, table: str, column: str, where: Mapping[str, object]) -> list[str | None]:
        """The stored text of one column (what the DDL's JSON checks read)."""
        self._check_names(table, [column, *where])
        clause = " AND ".join(f"{c} = ?" for c in where) or "1"
        return [r[0] for r in self._conn.execute(f"SELECT {column} FROM {table} WHERE {clause} ORDER BY rowid", [self._prepare(table, c, v) for c, v in where.items()])]


def open_store(path: str | Path, *, create: bool = False) -> Store:
    """Create (create=True) or open the durable store at `path` through the
    compatibility gate and schema-identity check (gen2/store/db.py). The one
    route to a durable store."""
    conn, observed = db.connect(path, create=create)
    return Store(conn, observed, _admitted_by=_ADMITTED)


def adopt_in_memory(conn: sqlite3.Connection) -> Store:
    """A Store over an in-memory connection the caller built (test fixtures
    that load the DDL themselves). It runs the checks db.connect runs on a
    durable connection: the compatibility gate, with the connection contract
    applied and read back, then schema identity with gen2/store/schema.sql.
    Refused: a connection to a file (a durable store is opened with
    open_store, which also sets WAL, synchronous FULL and the busy timeout),
    one with a transaction open, and one not in autocommit mode
    (transaction() issues BEGIN and COMMIT itself)."""
    if conn.isolation_level is not None:
        raise db.StoreOpenError("adopt_in_memory needs an autocommit connection (isolation_level=None)")
    if conn.in_transaction:
        raise db.StoreOpenError("adopt_in_memory refuses a connection with a transaction open")
    files = [row[2] for row in conn.execute("PRAGMA database_list") if row[2]]
    if files:
        raise db.StoreOpenError(f"adopt_in_memory refuses a connection to {files}: open a durable store with open_store")
    observed = compat.check_connection(conn)
    db.check_schema_identity(conn)
    return Store(conn, observed, _admitted_by=_ADMITTED)


def integer_columns(store: Store) -> dict[str, list[str]]:
    """Every INTEGER column per table (for the classification test)."""
    return {t: [c for c, kind in cols.items() if kind == "INTEGER"] for t, cols in store._columns.items()}
