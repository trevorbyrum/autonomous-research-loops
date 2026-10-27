"""Black-box tests for tools/gen2_traceability.py and the toml mode of tools/check_gen2_locators.py (R2, ruling 5).

Each drift test renders the table so it is known current, changes one thing (a mapping row, a table cell, an
invariant ID) and requires `--check` to exit 1 and to name what disagrees; a checker that always said yes fails them.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from gen2.tests import tool_repo_fixtures as fx

TOOL = Path(fx.REPO) / "tools" / "gen2_traceability.py"
MAPPING = 'docs/gen2/traceability.toml'
INVARIANTS = "# Invariants\n\n**C-1 — One writer.** x. *Source:* DR.\n\n**C-2 — Envelope.** y.\n"
TOML = '[invariant.C-1]\nenforced_at = [\n  "router: gen2/router/a.py::A",\n]\ntests = [\n  "gen2/tests/test_a.py::T",\n]\n\n[invariant.C-2]\nenforced_at = []\ntests = []\ndeferred = "DEBT-0"\n'
FILES = {"docs/gen2/INVARIANTS.md": INVARIANTS, MAPPING: TOML, "gen2/router/a.py": "class A:\n    pass\n", "gen2/tests/test_a.py": "class T:\n    pass\n"}


class TraceabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = fx.Repo(FILES)
        self.addCleanup(self.repo.close)
        self.assertEqual(self.repo.run(tool=TOOL).returncode, 0)

    def check(self, expect: int, needle: str = ""):
        done = self.repo.run("--check", tool=TOOL)
        self.assertEqual(done.returncode, expect, msg=done.stderr)
        self.assertIn(needle, done.stderr)

    def test_the_table_renders_every_locator_in_backticks_and_passes_its_own_check(self) -> None:
        table = (self.repo.root / "docs/gen2/TRACEABILITY.md").read_text()
        self.assertIn("| C-1 | router: `gen2/router/a.py::A` | `gen2/tests/test_a.py::T` |", table)
        self.assertIn("| C-2 | deferred: DEBT-0 | — |", table)
        self.check(0)

    def test_a_stale_table_fails_the_check(self) -> None:
        self.repo.write({MAPPING: TOML.replace("A\"", "B\"")})
        self.check(1, "TRACEABILITY.md is stale")

    def test_a_hand_edited_table_fails_the_check(self) -> None:
        table = self.repo.root / "docs/gen2/TRACEABILITY.md"
        table.write_text(table.read_text().replace("test_a.py::T", "test_a.py::U"))
        self.check(1, "stale")

    def test_the_mapping_and_the_invariants_must_name_the_same_ids(self) -> None:
        self.repo.write({"docs/gen2/INVARIANTS.md": INVARIANTS + "\n**C-3 — New.** z.\n"})
        self.check(1, "C-3 is an invariant with no entry")

    def test_an_empty_row_must_say_why(self) -> None:
        self.repo.write({MAPPING: TOML.replace('deferred = "DEBT-0"\n', "")})
        self.repo.run(tool=TOOL)
        self.check(1, "C-2 has no enforced_at and no `deferred`")

    def test_the_locator_check_reads_the_mapping_and_fails_a_deleted_name(self) -> None:
        run = lambda: self.repo.run(MAPPING, tool=fx.LOCATORS_TOOL)
        self.assertEqual(run().returncode, 0)
        self.repo.write({"gen2/router/a.py": "class Z:\n    pass\n"})
        done = run()
        self.assertEqual(done.returncode, 1)
        self.assertIn("A is not defined", done.stderr)


if __name__ == "__main__":
    unittest.main()
