"""The SQLite compatibility gate and the store's open path.

Trace: Astra third review (gen2-0a-repair-3) ruling 4 — before 0b creates or
admits a durable store: numeric version floor, JSON actually present,
connection pragmas applied and read back, loud refusal; task 0b;
docs/gen2/ENVIRONMENT.md; INVARIANTS C-11, §11.2.

Oracles, independent of the code under test: version orderings written by
hand (including the pairs a string comparison gets wrong); SQLite's own
refusal text for a missing function ("no such function: ..."), which a
JSON-less build raises; a real connection whose json_extract is replaced by
an application function answering wrongly; the file system (does the store
path exist after a refused open?); and PRAGMA read-backs on the connection
the store hands out.

What these tests cannot show: behaviour on a real SQLite older than 3.45.1
or on a real build compiled without JSON. Neither is installed here, so the
old version is reported by a wrapper and the missing function is simulated
with SQLite's own error.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from gen2.core.instants import is_utc_instant
from gen2.store import api, compat, db
from gen2.store.compat import StoreCompatibilityError
from gen2.tests import children


class ReportingConnection:
    """A real in-memory connection that reports another sqlite_version() and,
    optionally, fails like a build without the named JSON function."""

    def __init__(self, version: str | None = None, missing: str | None = None) -> None:
        self.real = sqlite3.connect(":memory:")
        self.version, self.missing = version, missing

    def execute(self, sql: str, *args):
        if self.version is not None and sql.strip() == "SELECT sqlite_version()":
            return self.real.execute("SELECT ?", (self.version,))
        if self.missing is not None and self.missing + "(" in sql:
            raise sqlite3.OperationalError(f"no such function: {self.missing}")
        return self.real.execute(sql, *args)

    def executescript(self, text: str):
        return self.real.executescript(text)

    def close(self) -> None:
        self.real.close()


class VersionFloorTest(unittest.TestCase):
    def refused(self, version: str) -> bool:
        conn = ReportingConnection(version=version)
        try:
            compat.check_library(conn)
            return False
        except StoreCompatibilityError:
            return True
        finally:
            conn.close()

    def test_version_is_compared_as_numbers(self) -> None:
        """The floor is 3.45.1. "3.9.0" > "3.45.1" and "3.100.0" < "3.45.1"
        as strings; as versions it is the other way round."""
        for version, refused in (("3.45.1", False), ("3.45.2", False), ("3.46.0", False), ("3.100.0", False), ("4.0.0", False),
                                 ("3.45.0", True), ("3.44.99", True), ("3.9.0", True), ("3.9.9", True), ("2.99.99", True)):
            with self.subTest(version=version):
                self.assertEqual(self.refused(version), refused)

    def test_unparseable_version_is_refused_not_guessed(self) -> None:
        for version in ("3.45", "3.45.1a", "3.45.1.2", "v3.45.1", "", "3.45.1 "):
            with self.subTest(version=version):
                self.assertTrue(self.refused(version))
                with self.assertRaises(ValueError):
                    compat.parse_version(version)

    def test_refusal_is_a_dated_capability_fact(self) -> None:
        conn = ReportingConnection(version="3.44.0")
        with self.assertRaises(StoreCompatibilityError) as ctx:
            compat.check_library(conn)
        conn.close()
        fact = ctx.exception.fact
        self.assertEqual((fact["capability"], fact["state"], fact["affected_lanes"], fact["last_success_at"]), ("store.sqlite", "failing", ["store"], None))
        self.assertTrue(is_utc_instant(fact["since"]) and is_utc_instant(fact["recorded_at"]))
        self.assertIn("3.44.0 is below the supported floor 3.45.1", fact["detail"])
        self.assertEqual(fact["observed"]["sqlite_version"], "3.44.0")
        self.assertIn("since " + fact["since"], str(ctx.exception))

    def test_this_interpreters_sqlite_passes(self) -> None:
        conn = sqlite3.connect(":memory:")
        observed = compat.check_connection(conn)
        conn.close()
        self.assertEqual(observed["sqlite_version"], sqlite3.sqlite_version)
        self.assertEqual(observed["pragmas"], {"foreign_keys": 1, "recursive_triggers": 1})


class JsonCapabilityTest(unittest.TestCase):
    def test_missing_json_function_is_refused_at_a_passing_version(self) -> None:
        """The version passes; SQLITE_OMIT_JSON removes the functions anyway."""
        for name in ("json_valid", "json_extract", "json_type", "json_array_length", "json_remove", "json_each"):
            with self.subTest(function=name):
                conn = ReportingConnection(missing=name)
                with self.assertRaises(StoreCompatibilityError) as ctx:
                    compat.check_library(conn)
                conn.close()
                self.assertIn(f"{name}: no such function: {name}", ctx.exception.fact["detail"])

    def test_json_function_answering_wrongly_is_refused(self) -> None:
        """Presence is not enough: an application function shadowing
        json_extract answers, but not what SQLite's JSON answers."""
        conn = sqlite3.connect(":memory:")
        conn.create_function("json_extract", -1, lambda *args: None)
        with self.assertRaises(StoreCompatibilityError) as ctx:
            compat.check_library(conn)
        conn.close()
        self.assertIn("json_extract: answered [(None, None)]", ctx.exception.fact["detail"])

    def test_every_json_function_the_ddl_uses_is_probed(self) -> None:
        used = compat.json_functions_used(db.schema_text())
        self.assertTrue({"json_extract", "json_each", "json_valid"} <= used)  # the scan finds them at all
        self.assertEqual(used - {name for name, _, _ in compat.JSON_PROBES}, set())
        self.assertEqual(compat.json_functions_used("-- json_patch in a comment\nSELECT json_patch(a, b), json_valid(c)"), {"json_patch", "json_valid"})


class ConnectionContractGateTest(unittest.TestCase):
    def refusal(self, contract: str) -> str:
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaises(StoreCompatibilityError) as ctx:
                compat.apply_connection_contract(conn, contract)
        finally:
            conn.close()
        return ctx.exception.fact["detail"]

    def test_a_contract_without_a_required_pragma_is_refused(self) -> None:
        self.assertIn("PRAGMA recursive_triggers does not read back as 1", self.refusal("PRAGMA foreign_keys = ON;\n"))
        self.assertIn("PRAGMA foreign_keys does not read back as 1", self.refusal("PRAGMA recursive_triggers = ON;\n"))

    def test_a_misspelled_pragma_does_not_pass_silently(self) -> None:
        """SQLite ignores an unknown pragma; the read-back does not."""
        detail = self.refusal("PRAGMA foreign_keys = ON;\nPRAGMA recursive_trigger = ON;\n")
        self.assertIn("PRAGMA recursive_triggers does not read back as 1", detail)
        self.assertIn("PRAGMA recursive_trigger does not read back as 1", detail)

    def test_the_real_contract_reads_back_on(self) -> None:
        conn = sqlite3.connect(":memory:")
        self.assertEqual(compat.apply_connection_contract(conn), {"foreign_keys": 1, "recursive_triggers": 1})
        self.assertEqual([conn.execute(f"PRAGMA {p}").fetchone() for p in compat.REQUIRED_PRAGMAS], [(1,), (1,)])
        conn.close()


class OpenStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def open_error(self, path: Path, **kwargs) -> BaseException:
        with self.assertRaises(Exception) as ctx:
            db.connect(path, **kwargs)
        return ctx.exception

    def test_refused_library_creates_nothing_on_disk(self) -> None:
        """The gate runs before the path is touched: a refused create leaves
        no file (sqlite3.connect would have created one). The refusal holds
        for every route to a Store (A4): open_store, the in-memory adoption
        route, and the constructor, which admits no caller-built store."""
        path = self.dir / "store.sqlite3"
        with mock.patch.object(compat, "SQLITE_FLOOR", (99, 0, 0)):
            exc = self.open_error(path, create=True)
            self.refused(StoreCompatibilityError, api.open_store, path, create=True)
            memory = self.memory_store()
            adopted = self.refused(StoreCompatibilityError, api.adopt_in_memory, memory)
            self.refused(db.StoreOpenError, api.Store, memory, {})
            memory.close()
        self.assertIsInstance(exc, StoreCompatibilityError)
        self.assertIn("below the supported floor 99.0.0", exc.fact["detail"])
        self.assertIn("below the supported floor 99.0.0", adopted.fact["detail"])
        self.assertFalse(path.exists())
        self.assertEqual(list(self.dir.iterdir()), [])

    def refused(self, error: type, call, *args, **kwargs) -> BaseException:
        """call(*args) raises `error` (any other outcome fails the test)."""
        with self.assertRaises(Exception) as ctx:
            call(*args, **kwargs)
        self.assertIsInstance(ctx.exception, error)
        return ctx.exception

    @staticmethod
    def memory_store(ddl: str | None = None, *, contract: bool = False) -> sqlite3.Connection:
        """An in-memory connection holding the shipped DDL (or `ddl`), built
        by hand; the connection contract is applied only when asked."""
        conn = sqlite3.connect(":memory:", isolation_level=None)
        if contract:
            conn.executescript(compat.CONNECTION_CONTRACT.read_text(encoding="utf-8"))
        conn.executescript(db.schema_text() if ddl is None else ddl)
        return conn

    def test_a_store_is_made_only_through_a_checked_route(self) -> None:
        """Astra 0b review A4, the review's reproduction: a file holding the
        complete shipped schema, with foreign_keys and recursive_triggers
        left off and the supported floor raised above this SQLite. Store(conn,
        {}) accepted it and then persisted a lease for a topic that does not
        exist. Now the constructor refuses every caller-built store, open_store
        refuses the library, and adoption refuses a file connection; the file
        gains no row. The adoption route (in-memory fixtures) runs the gate:
        it applies and reads back the contract, and refuses another schema, a
        connection with a transaction open, and one not in autocommit mode."""
        path = self.dir / "store.sqlite3"
        raw = sqlite3.connect(path, isolation_level=None)
        raw.executescript(db.schema_text())
        self.assertEqual([raw.execute(f"PRAGMA {p}").fetchone() for p in ("foreign_keys", "recursive_triggers")], [(0,), (0,)])
        with mock.patch.object(compat, "SQLITE_FLOOR", (99, 0, 0)):
            self.refused(db.StoreOpenError, api.Store, raw, {})
            self.refused(db.StoreOpenError, api.Store, raw, {"sqlite_version": "99.0.0", "pragmas": {"foreign_keys": 1, "recursive_triggers": 1}})
            self.refused(StoreCompatibilityError, api.open_store, path)
            adopted = self.refused(db.StoreOpenError, api.adopt_in_memory, raw)
        self.assertIn("open a durable store with open_store", str(adopted))
        self.assertEqual(raw.execute("SELECT count(*) FROM leases").fetchone(), (0,))
        raw.close()
        # Ordinary construction: open_store's connection has the contract read back on.
        with api.open_store(path) as store:
            self.assertEqual(store.compatibility["pragmas"], {"foreign_keys": 1, "recursive_triggers": 1})
            with self.assertRaises(sqlite3.IntegrityError):
                with store.transaction() as s:
                    s.insert("leases", {"lease_id": "lease_orphan", "topic_id": "fleet-a:nowhere", "scope": "research", "generation": 1,
                                        "station_id": "st1", "granted_at": "2026-09-25T00:00:00Z", "expires_at": "2026-09-25T00:00:00Z"})
        # Adoption: the gate applies the contract to a hand-built in-memory store and reads it back.
        memory = self.memory_store()
        self.assertEqual(memory.execute("PRAGMA foreign_keys").fetchone(), (0,))
        store = api.adopt_in_memory(memory)
        self.assertEqual([memory.execute(f"PRAGMA {p}").fetchone() for p in ("foreign_keys", "recursive_triggers")], [(1,), (1,)])
        self.assertEqual(store.compatibility["pragmas"], {"foreign_keys": 1, "recursive_triggers": 1})
        with self.assertRaises(sqlite3.IntegrityError):
            with store.transaction() as s:
                s.insert("leases", {"lease_id": "lease_orphan", "topic_id": "fleet-a:nowhere", "scope": "research", "generation": 1,
                                    "station_id": "st1", "granted_at": "2026-09-25T00:00:00Z", "expires_at": "2026-09-25T00:00:00Z"})
        store.close()
        ddl = db.schema_text()
        weakened = ddl.replace("SELECT RAISE(ABORT, 'contract revisions are never deleted (G-1)');", "SELECT 1;")
        self.assertNotEqual(weakened, ddl)
        open_tx = self.memory_store(contract=True)
        open_tx.execute("BEGIN")
        legacy = sqlite3.connect(":memory:")  # default isolation_level: Python opens transactions implicitly
        legacy.executescript(ddl)
        for case, conn, error, fragment in (("another schema", self.memory_store(weakened, contract=True), db.StoreOpenError, "changed ['trigger contract_no_delete']"),
                                            ("transaction open", open_tx, db.StoreOpenError, "transaction open"),
                                            ("not autocommit", legacy, db.StoreOpenError, "autocommit")):
            with self.subTest(case=case):
                self.assertIn(fragment, str(self.refused(error, api.adopt_in_memory, conn)))
                conn.close()

    def test_refused_library_does_not_admit_an_existing_store(self) -> None:
        path = self.dir / "store.sqlite3"
        db.connect(path, create=True)[0].close()
        before = path.read_bytes()
        with mock.patch.object(compat, "JSON_PROBES", compat.JSON_PROBES + (("json_extract", "SELECT json_extract('[1]', '$[0]')", [(2,)]),)):
            exc = self.open_error(path)
        self.assertIsInstance(exc, StoreCompatibilityError)
        self.assertEqual(path.read_bytes(), before)

    def test_missing_store_is_an_error_not_a_mode(self) -> None:
        path = self.dir / "absent.sqlite3"
        exc = self.open_error(path)
        self.assertIsInstance(exc, db.StoreOpenError)
        self.assertIn("A missing store is a startup error", str(exc))
        self.assertFalse(path.exists())

    def test_create_refuses_an_existing_path(self) -> None:
        path = self.dir / "store.sqlite3"
        path.write_bytes(b"not a store")
        exc = self.open_error(path, create=True)
        self.assertIsInstance(exc, db.StoreOpenError)
        self.assertEqual(path.read_bytes(), b"not a store")

    def test_created_store_reopens_with_the_contract_applied(self) -> None:
        """The connection handed out has the contract read back on, and it is
        load-bearing there: REPLACE of a stored row aborts on the delete
        guard (it would silently succeed without recursive_triggers)."""
        path = self.dir / "store.sqlite3"
        conn, observed = db.connect(path, create=True)
        conn.close()
        conn, observed = db.connect(path)
        self.assertEqual([conn.execute(f"PRAGMA {p}").fetchone() for p in ("foreign_keys", "recursive_triggers", "journal_mode", "synchronous")],
                         [(1,), (1,), ("wal",), (2,)])
        self.assertEqual(observed["pragmas"], {"foreign_keys": 1, "recursive_triggers": 1})
        conn.execute("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 1, 'text/plain', '2026-09-25T00:00:00Z')", ("sha256:" + "a" * 64,))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            conn.execute("INSERT OR REPLACE INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 2, 'text/plain', '2026-09-25T00:00:00Z')", ("sha256:" + "a" * 64,))
        self.assertIn("artifact records are never deleted", str(ctx.exception))
        self.assertEqual(conn.execute("SELECT size_bytes FROM artifacts").fetchall(), [(1,)])
        conn.close()

    def test_a_store_with_another_schema_is_not_admitted(self) -> None:
        """Schema identity: a missing guard, a guard with the same name and a
        weaker body, an extra table, or another user_version is refused on
        open."""
        ddl = db.schema_text()
        cases = {
            "missing trigger": ddl.replace("CREATE TRIGGER contract_no_delete BEFORE DELETE ON contract_revisions\nBEGIN\n  SELECT RAISE(ABORT, 'contract revisions are never deleted (G-1)');\nEND;\n", ""),
            "weakened trigger": ddl.replace("SELECT RAISE(ABORT, 'contract revisions are never deleted (G-1)');", "SELECT 1;"),
            "extra table": ddl + "\nCREATE TABLE shadow (x TEXT) STRICT;\n",
            "user_version": ddl.replace("PRAGMA user_version = 1;", "PRAGMA user_version = 2;"),
        }
        for case, text in cases.items():
            with self.subTest(case=case):
                self.assertNotEqual(text, ddl)
                path = self.dir / f"{case.replace(' ', '-')}.sqlite3"
                raw = sqlite3.connect(path)
                raw.executescript(text)
                raw.close()
                exc = self.open_error(path)
                self.assertIsInstance(exc, db.StoreOpenError)
                self.assertIn("store schema is not the DDL in gen2/store/schema/", str(exc))


class FirstOpenContentionTest(unittest.TestCase):
    """A store first opened in rollback-journal mode while another connection holds its write lock (task 2b-repair-13d, Astra R13B-3).

    The 13b multi-process test sometimes saw one of its two recorders die in open_store with `database is locked`. Cause, reproduced here
    without a second process: switching a store from the rollback journal to WAL is a statement that has read the file's header, so SQLite
    does not call the busy handler for it (waiting for the write lock could deadlock with a writer waiting for this connection's read
    lock) and `busy_timeout` does not apply. A store made by `create=True` is WAL from the start; one that was copied or restored
    (sqlite3's backup, which the test uses) is not, and every opener of it before the first switch was exposed. `db._wal` retries
    within the same budget the busy timeout promises. Oracle: SQLite's own behaviour, observed on real connections, and the clock."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "restored.sqlite3"
        source = sqlite3.connect(":memory:")
        source.executescript(db.schema_text())
        disk = sqlite3.connect(self.path)
        source.backup(disk)
        disk.close()
        source.close()

    def writer(self) -> sqlite3.Connection:
        """Another connection, in the middle of a write transaction on the store."""
        holder = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN IMMEDIATE")
        return holder

    def journal_mode(self) -> str:
        check = sqlite3.connect(self.path)
        try:
            return check.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            check.close()

    def test_sqlite_does_not_apply_the_busy_timeout_to_the_switch_to_wal(self) -> None:
        """The cause, observed: a generous timeout and a writer that lets go in a moment, and the switch still fails at once."""
        self.assertEqual(self.journal_mode(), "delete")
        self.writer()
        other = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        self.addCleanup(other.close)
        began = time.monotonic()
        with self.assertRaises(sqlite3.OperationalError) as caught:
            other.execute("PRAGMA journal_mode = WAL")
        self.assertLess(time.monotonic() - began, 1.0, "it did not wait for the 5 s it was given")
        self.assertEqual(caught.exception.sqlite_errorcode & 0xFF, sqlite3.SQLITE_BUSY)

    def test_the_first_open_waits_for_the_lock_to_clear(self) -> None:
        holder, sleeps = self.writer(), []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 3:
                holder.execute("COMMIT")   # the other writer finishes while the opener is waiting
            self.assertLess(len(sleeps), 50, "the opener waits for ever")
        with mock.patch.object(db, "_sleep", sleep):
            try:
                conn, observed = db.connect(self.path)
            except (sqlite3.OperationalError, db.StoreOpenError) as e:
                self.fail(f"the first open failed instead of waiting for the writer: {e}")
        conn.close()
        self.assertEqual((len(sleeps), observed["operational"]["journal_mode"], self.journal_mode()), (3, "wal", "wal"))
        self.assertEqual(sleeps, [0.005, 0.01, 0.02], "a short wait first, doubling")

    def test_the_wait_is_bounded_by_the_busy_timeout(self) -> None:
        self.writer()   # never lets go
        clock, sleeps = [0.0], []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds
            self.assertLess(len(sleeps), 1000, "the wait never ends")
        with mock.patch.object(db, "_sleep", sleep), mock.patch.object(db, "_monotonic", lambda: clock[0]):
            with self.assertRaises(db.StoreOpenError) as caught:
                db.connect(self.path)
        self.assertIn("database is locked", str(caught.exception))
        self.assertAlmostEqual(sum(sleeps), db.BUSY_TIMEOUT_MS / 1000, delta=0.11, msg="it waited out the busy timeout, and no longer")
        self.assertEqual(self.journal_mode(), "delete", "and the store is as it was")

    def test_only_a_busy_database_is_waited_for(self) -> None:
        refusal = sqlite3.OperationalError("disk I/O error")
        refusal.sqlite_errorcode = sqlite3.SQLITE_IOERR

        class Failing:
            def execute(self, sql):
                raise refusal
        with mock.patch.object(db, "_sleep", side_effect=AssertionError("it waited for an error that is not a lock")):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                db._wal(Failing())
        self.assertIs(caught.exception, refusal)

    def test_a_store_that_is_already_wal_opens_beside_a_writer_without_waiting(self) -> None:
        db.connect(self.path)[0].close()   # the first open makes it WAL
        self.writer()
        with mock.patch.object(db, "_sleep", side_effect=AssertionError("it waited with nothing to wait for")):
            conn, observed = db.connect(self.path)
        conn.close()
        self.assertEqual(observed["operational"]["journal_mode"], "wal")


class GateCommandTest(unittest.TestCase):
    """`make gen2-sqlite` runs `python -m gen2.store.compat`: its exit status
    is the gate's verdict, and it records what it ran on (JSON on stdout when
    it passes, on stderr with the refusal when it does not)."""

    def run_gate(self, prelude: str = "", *args: str) -> subprocess.CompletedProcess:
        code = f"import sys, gen2.store.compat as c\n{prelude}\nsys.exit(c.main({list(args)!r}))"
        return children.python(["-c", code], capture_output=True, text=True, timeout=60)

    def test_passing_gate_exits_zero_and_records_the_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "summary.md"
            result = self.run_gate("", "--report", str(report))
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            record = json.loads(result.stdout)
            self.assertEqual((record["state"], record["observed"]["sqlite_version"]), ("healthy", sqlite3.sqlite_version))
            self.assertIn(f'"sqlite_version": "{sqlite3.sqlite_version}"', report.read_text(encoding="utf-8"))

    def test_refusing_gate_exits_nonzero_loudly(self) -> None:
        result = self.run_gate("c.SQLITE_FLOOR = (99, 0, 0)")
        self.assertEqual(result.returncode, 1)
        self.assertIn("gen2 SQLite gate REFUSED", result.stderr)
        self.assertIn('"state": "failing"', result.stderr)


if __name__ == "__main__":
    unittest.main()
