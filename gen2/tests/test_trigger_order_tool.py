"""Tests for tools/gen2_trigger_order.py, the permanent reversed-trigger-order
check (task 0b, cleanup 2; 0a-repair-3 note 3).

Oracles: sqlite_schema's own record of creation order for a literal DDL
written here, and hand-written outcome maps for the comparison. The tool is
loaded from TOOL (the mutation harness points it at a mutated copy).

What these tests cannot show: that SQLite fires triggers in creation order
(observed on 3.45.1, not documented); the real-schema run is `make
gen2-trigger-order` itself.
"""
from __future__ import annotations

import runpy
import sqlite3
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools" / "gen2_trigger_order.py"
CONTRACT = "PRAGMA foreign_keys = ON;\nPRAGMA recursive_triggers = ON;\n"
DDL = """\
CREATE TABLE t (id TEXT PRIMARY KEY, v INTEGER) STRICT;
CREATE TRIGGER t_first BEFORE INSERT ON t WHEN NEW.v < 0
BEGIN
  SELECT RAISE(ABORT, 'first');
END;
CREATE INDEX t_v ON t (v);
CREATE TRIGGER t_second BEFORE INSERT ON t WHEN NEW.v > 9
BEGIN
  SELECT RAISE(ABORT, 'second');
END;
CREATE TRIGGER t_third BEFORE DELETE ON t
BEGIN
  SELECT RAISE(ABORT, 'third');
END;
"""


def trigger_order(ddl: str) -> list[str]:
    conn = sqlite3.connect(":memory:")
    conn.executescript(ddl)
    order = [r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'trigger' ORDER BY rowid")]
    conn.close()
    return order


class TriggerOrderToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = runpy.run_path(str(TOOL))

    def test_rebuild_creates_the_same_triggers_in_reverse(self) -> None:
        rebuilt = self.tool["reverse_triggers"](DDL)
        self.assertEqual(trigger_order(DDL), ["t_first", "t_second", "t_third"])
        self.assertEqual(trigger_order(rebuilt), ["t_third", "t_second", "t_first"])
        self.assertEqual(self.tool["check_rebuild"](DDL, rebuilt, CONTRACT), [])

    def test_a_rebuild_that_keeps_the_order_is_refused(self) -> None:
        """Without this, a rebuild that reversed nothing would pass trivially."""
        problems = self.tool["check_rebuild"](DDL, DDL, CONTRACT)
        self.assertIn("sqlite_schema does not record the triggers in reversed creation order", problems)
        dropped = self.tool["reverse_triggers"](DDL).replace("CREATE TRIGGER t_third BEFORE DELETE ON t\nBEGIN\n  SELECT RAISE(ABORT, 'third');\nEND;\n", "")
        self.assertIn("the rebuild does not create the same triggers with identical SQL", self.tool["check_rebuild"](DDL, dropped, CONTRACT))

    def test_outcomes_must_be_green_and_identical(self) -> None:
        compare = self.tool["compare"]
        same = {"a.T.test_x": "pass", "a.T.test_y (case='k')": "pass"}
        self.assertEqual(compare(same, dict(same)), [])
        self.assertEqual(compare(same, {**same, "a.T.test_y (case='k')": "fail: AssertionError: 'm' not found"}),
                         ["reversed order differs: a.T.test_y (case='k'): pass -> fail: AssertionError: 'm' not found"])
        self.assertEqual(compare(same, {"a.T.test_x": "pass"}), ["reversed order differs: a.T.test_y (case='k'): pass -> not run"])
        failing = {**same, "a.T.test_x": "fail: AssertionError"}
        self.assertEqual(compare(failing, dict(failing)), ["original order: a.T.test_x: fail: AssertionError"])
        self.assertEqual(compare({}, {}), ["the store suite ran no tests"])


if __name__ == "__main__":
    unittest.main()
