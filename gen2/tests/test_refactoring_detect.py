"""Regression for the detector invalid-revision exit status (2q-t5 / DEBT-027 NB4)."""

from __future__ import annotations

import unittest

from pathlib import Path

from gen2.tests import children

TOOL_PATH = Path(__file__).resolve().parents[2] / "tools" / "gen2_refactoring_detect.py"

class RevisionTest(unittest.TestCase):
    def test_an_invalid_start_or_end_revision_exits_two_with_the_git_diagnostic(self) -> None:
        invalid = "0" * 40  # Git's null object ID cannot name a commit.
        for start, end in ((invalid, "HEAD"), ("HEAD", invalid)):
            with self.subTest(start=start, end=end):
                done = children.python([str(TOOL_PATH), start, end], capture_output=True, text=True, timeout=10)
                self.assertEqual(done.returncode, 2, msg=f"command: {done.args!r}\nstdout: {done.stdout}\nstderr: {done.stderr}")
                self.assertIn(f"{invalid!r} is not a commit", done.stderr)
                self.assertIn("fatal:", done.stderr)
                self.assertEqual(done.stdout, "")

if __name__ == "__main__":
    unittest.main()
