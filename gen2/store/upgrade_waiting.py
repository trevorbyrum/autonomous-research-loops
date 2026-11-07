"""Explicit offline upgrade of the exact pre-hand-off schema; never called by open.

Trevor's 2026-11-07 §4.6 exception permits the synthetic predecessor witness;
DEBT-056 retains the first live-store check. Only one trigger is replaced.
"""
import sqlite3
from contextlib import closing
from pathlib import Path

from gen2.core import canonical
from gen2.store import api, db, compat

PREDECESSOR = "sha256:b2b2a5acd4b700f7d76372edb173fa83971ff374bfa13ead2b51fe868a644982"
TRIGGER = ("trigger", "queue_status_transitions")


def _previous(conn):
    signature = canonical.logical_hash({"user_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "objects": sorted((kind, name, sql) for (kind, name), sql in db._schema_objects(conn).items())})
    if signature != PREDECESSOR:
        raise db.StoreOpenError("waiting upgrade requires the exact predecessor schema")


def _replace(path):
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        compat.apply_connection_contract(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            _previous(conn)
            conn.execute("DROP TRIGGER queue_status_transitions")
            conn.execute(db.reference_schema()[0][TRIGGER])
            db.check_schema_identity(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def upgrade(path):
    """With runtime handles closed, admit the predecessor before maintenance's successor-only finally block."""
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        _previous(conn)
    api.Store.maintain(path, _replace)
