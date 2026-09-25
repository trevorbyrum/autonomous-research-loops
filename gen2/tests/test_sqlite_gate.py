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
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen2.core.instants import is_utc_instant
from gen2.store import compat, db
from gen2.store.compat import StoreCompatibilityError

ROOT = Path(__file__).resolve().parents[2]


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
        used = compat.json_functions_used((ROOT / "gen2" / "store" / "schema.sql").read_text(encoding="utf-8"))
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
        no file (sqlite3.connect would have created one)."""
        path = self.dir / "store.sqlite3"
        with mock.patch.object(compat, "SQLITE_FLOOR", (99, 0, 0)):
            exc = self.open_error(path, create=True)
        self.assertIsInstance(exc, StoreCompatibilityError)
        self.assertIn("below the supported floor 99.0.0", exc.fact["detail"])
        self.assertFalse(path.exists())
        self.assertEqual(list(self.dir.iterdir()), [])

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
        ddl = (ROOT / "gen2" / "store" / "schema.sql").read_text(encoding="utf-8")
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
                self.assertIn("store schema is not gen2/store/schema.sql", str(exc))


class GateCommandTest(unittest.TestCase):
    """`make gen2-sqlite` runs `python -m gen2.store.compat`: its exit status
    is the gate's verdict, and it records what it ran on (JSON on stdout when
    it passes, on stderr with the refusal when it does not)."""

    def run_gate(self, prelude: str = "", *args: str) -> subprocess.CompletedProcess:
        code = f"import sys, gen2.store.compat as c\n{prelude}\nsys.exit(c.main({list(args)!r}))"
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)

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
