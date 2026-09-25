"""Black-box tests for the structural DDL rules in tools/check_gen2_schemas.py.

Trace: Astra 0a review A1 (a table without a delete guard, or a connection
without recursive_triggers, lets history be rewritten); INVARIANTS C-11.

Each test writes a throwaway gen2/store/{schema,connection}.sql pair, runs
`check_gen2_schemas.py --part ddl` as a subprocess, and asserts the exit code
and the specific failure. The fixtures are literal SQL written here.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

CHECKER = Path(__file__).resolve().parents[2] / "tools" / "check_gen2_schemas.py"
CONNECTION = "PRAGMA foreign_keys = ON;\nPRAGMA recursive_triggers = ON;\n"
GUARDED = """\
-- trace: fixture
CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT) STRICT;
CREATE TRIGGER t_no_delete BEFORE DELETE ON t
BEGIN
  SELECT RAISE(ABORT, 'never deleted');
END;
"""


class DdlRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_check(self, schema: str, connection: str = CONNECTION) -> subprocess.CompletedProcess:
        store = self.root / "gen2" / "store"
        store.mkdir(parents=True, exist_ok=True)
        (store / "schema.sql").write_text(textwrap.dedent(schema), encoding="utf-8")
        (store / "connection.sql").write_text(connection, encoding="utf-8")
        return subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root), "--part", "ddl"], capture_output=True, text=True, timeout=60)

    def test_guarded_table_passes(self) -> None:
        result = self.run_check(GUARDED)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_table_without_delete_guard_fails(self) -> None:
        result = self.run_check(GUARDED + "-- trace: fixture\nCREATE TABLE u (id TEXT PRIMARY KEY) STRICT;\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("table u has no unconditional BEFORE DELETE", result.stderr)

    def test_conditional_delete_guard_does_not_count(self) -> None:
        result = self.run_check(GUARDED + "-- trace: fixture\nCREATE TABLE u (id TEXT PRIMARY KEY) STRICT;\n"
                                "CREATE TRIGGER u_no_delete BEFORE DELETE ON u WHEN OLD.id = 'x'\nBEGIN\n  SELECT RAISE(ABORT, 'no');\nEND;\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("table u has no unconditional BEFORE DELETE", result.stderr)

    def test_on_conflict_replace_clause_fails(self) -> None:
        result = self.run_check(GUARDED.replace("id TEXT PRIMARY KEY", "id TEXT PRIMARY KEY ON CONFLICT REPLACE"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("ON CONFLICT clause", result.stderr)

    def test_connection_contract_without_recursive_triggers_fails(self) -> None:
        result = self.run_check(GUARDED, connection="PRAGMA foreign_keys = ON;\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("PRAGMA recursive_triggers does not read back as 1", result.stderr)


if __name__ == "__main__":
    unittest.main()
