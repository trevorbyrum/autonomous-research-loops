"""Black-box tests for the structural rules in tools/check_gen2_schemas.py.

Trace: Astra 0a review A1 (a table without a delete guard, or a connection
without recursive_triggers, lets history be rewritten); INVARIANTS C-11;
Astra third review ruling 4 (the build runs the store's SQLite gate);
Astra 0c review C1 (a fixture's declared errors are counted, not collapsed).

Each DDL test writes a throwaway store DDL (gen2/store/schema/: one part, its
order.txt naming it) and connection.sql, runs `check_gen2_schemas.py --part
ddl` as a subprocess, and asserts the exit code and the specific failure. The fixtures are literal SQL written here. The
fixture-rule test does the same with a literal one-file schema tree and
`--part schemas`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from gen2.tests import children

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "tools" / "check_gen2_schemas.py"
# The checker imports the store's SQLite gate (gen2.store.compat) from the
# code tree; the mutation harness runs a copy of the checker from a temp dir,
# so the import path is given explicitly (children.env(): the repository, or
# the harness's mutant tree) rather than derived from its location.
CONNECTION = "PRAGMA foreign_keys = ON;\nPRAGMA recursive_triggers = ON;\n"
ORDER = "# the fixture's one part\nfixture.sql\n"
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
        (store / "schema").mkdir(parents=True, exist_ok=True)
        (store / "schema" / "order.txt").write_text(ORDER, encoding="utf-8")
        (store / "schema" / "fixture.sql").write_text(textwrap.dedent(schema), encoding="utf-8")
        (store / "connection.sql").write_text(connection, encoding="utf-8")
        return subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root), "--part", "ddl"], capture_output=True, text=True, timeout=60, env=children.env())

    def test_refused_sqlite_fails_the_ddl_check(self) -> None:
        """The build route runs the store's gate: a SQLite it refuses fails
        the DDL check (here the floor is raised above this SQLite in the
        checker's own process)."""
        store = self.root / "gen2" / "store"
        (store / "schema").mkdir(parents=True)
        (store / "schema" / "order.txt").write_text(ORDER, encoding="utf-8")
        (store / "schema" / "fixture.sql").write_text(GUARDED, encoding="utf-8")
        (store / "connection.sql").write_text(CONNECTION, encoding="utf-8")
        code = ("import runpy, sys, gen2.store.compat as c\nc.SQLITE_FLOOR = (99, 0, 0)\n"
                f"sys.argv = [{str(CHECKER)!r}, '--root', {str(self.root)!r}, '--part', 'ddl']\nrunpy.run_path({str(CHECKER)!r}, run_name='__main__')")
        result = children.python(["-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, msg=result.stderr)
        self.assertIn("SQLite compatibility gate refused this build's SQLite", result.stderr)
        self.assertIn("below the supported floor 99.0.0", result.stderr)

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

    def test_json_function_without_a_gate_probe_fails(self) -> None:
        """A JSON function the compatibility gate does not probe would be an
        unchecked capability (Astra third review ruling 4)."""
        result = self.run_check(GUARDED + "-- trace: fixture\nCREATE VIEW v AS SELECT json_patch(v, '{}') AS p FROM t;\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("uses JSON function(s) ['json_patch'] that the compatibility gate does not probe", result.stderr)

    def test_connection_contract_without_recursive_triggers_fails(self) -> None:
        result = self.run_check(GUARDED, connection="PRAGMA foreign_keys = ON;\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("PRAGMA recursive_triggers does not read back as 1", result.stderr)


class SchemaFixtureRuleTest(unittest.TestCase):
    """An invalid fixture declares every error it produces, counted."""

    SCHEMA = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://research-loops.invalid/gen2/schema/t.schema.json",
        "$comment": "flow: fixture | boundaries: Router",
        "type": "object",
        "allOf": [{"required": ["a"]}, {"required": ["b"]}],
    }

    def run_check(self, declared: list[dict]) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "gen2").mkdir(parents=True)
            (root / "docs" / "gen2" / "BOUNDARIES.md").write_text("## Router\n", encoding="utf-8")
            examples = root / "gen2" / "schema" / "examples" / "t"
            examples.mkdir(parents=True)
            (root / "gen2" / "schema" / "t.schema.json").write_text(json.dumps(self.SCHEMA), encoding="utf-8")
            (examples / "valid-both.json").write_text(json.dumps(
                {"fixture": {"schema": "t.schema.json", "expect": "valid", "tests": "positive control"},
                 "instance": {"a": 1, "b": 2}}), encoding="utf-8")
            (examples / "invalid-neither.json").write_text(json.dumps(
                {"fixture": {"schema": "t.schema.json", "expect": "invalid", "tests": "two rules, one signature",
                             "base": "valid-both.json", "patch": [{"op": "remove", "path": "/a"}, {"op": "remove", "path": "/b"}],
                             "errors": declared}}), encoding="utf-8")
            return subprocess.run([sys.executable, str(CHECKER), "--root", str(root), "--part", "schemas"],
                                  capture_output=True, text=True, timeout=60, env=children.env())

    def test_two_rules_reporting_one_signature_must_both_be_declared(self) -> None:
        """Two rules fail at one (keyword, path). Declared once, the fixture
        would survive removal of either rule, so the check refuses it (Astra
        0c review C1); declared twice, it passes (the next test)."""
        once = self.run_check([{"keyword": "required", "path": ""}])
        self.assertEqual(once.returncode, 1, msg=once.stdout)
        self.assertIn("invalid-neither.json: expected exactly [('required', '')], got [('required', ''), ('required', '')]", once.stderr)

    def test_two_rules_reporting_one_signature_pass_when_both_are_declared(self) -> None:
        """The previous test's accepted case, apart, so that it runs whether
        or not the refusal is noticed (task 1c-repair-2 C4: a paired control
        must pass under the mutant it is paired with)."""
        twice = self.run_check([{"keyword": "required", "path": ""}] * 2)
        self.assertEqual(twice.returncode, 0, msg=twice.stderr)


if __name__ == "__main__":
    unittest.main()
