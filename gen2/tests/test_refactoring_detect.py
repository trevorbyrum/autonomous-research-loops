"""Tests for the parts of tools/gen2_refactoring_detect.py that need no Docker and no Java (task 2q-r1): the container command, the report summary, the expectation check.

Oracle: a RefactoringMiner-shaped document written here, and the counts and verdicts worked out by hand. What they cannot show: that the pinned image runs, or that the detector finds
what it should; the trial's evidence (private/evidence/2q-r1/rm/) is that.
"""
from __future__ import annotations

import runpy
import unittest
from collections import Counter
from pathlib import Path

TOOL = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools" / "gen2_refactoring_detect.py"))


def found(kind: str, path: str = "gen2/x.py", line: int = 3) -> dict:
    return {"type": kind, "description": f"{kind} thing", "leftSideLocations": [], "rightSideLocations": [{"filePath": path, "startLine": line, "codeElementType": "METHOD_DECLARATION"}]}


REPORT = {"commits": [{"sha1": "a" * 40, "refactorings": []},
                      {"sha1": "b" * 40, "refactorings": [found("Extract Method", line=10), found("Extract Method", line=20), found("Rename Variable", "tools/y.py", 7)]}]}


class ContainerCommandTest(unittest.TestCase):
    def test_the_container_has_no_network_no_pull_a_read_only_repository_and_the_pinned_digest(self) -> None:
        command = TOOL["docker_command"](Path("/r"), Path("/o"), "s1", "e1", "out.json", 1000, 1001)
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertIn("/r:/repo:ro", command)
        self.assertIn("--read-only", command)
        self.assertEqual(command[command.index("--user") + 1], "1000:1001")
        self.assertEqual(command[command.index(TOOL["IMAGE"]) + 1:], ["-bc", "/repo", "s1", "e1", "-json", "/out/out.json"])
        self.assertRegex(TOOL["IMAGE"], r"^tsantalis/refactoringminer@sha256:[0-9a-f]{64}$")  # a digest, never a moving tag


class ReportTest(unittest.TestCase):
    def test_the_summary_counts_each_type_and_lists_each_refactoring_under_its_commit(self) -> None:
        lines, counts = TOOL["summarise"](REPORT)
        self.assertEqual(counts, Counter({"Extract Method": 2, "Rename Variable": 1}))
        self.assertEqual(lines[0], "aaaaaaa  0 refactoring(s)")
        self.assertEqual(lines[1], "bbbbbbb  3 refactoring(s)")
        self.assertEqual(len(lines), 5)
        self.assertIn("gen2/x.py:10", lines[2])
        self.assertIn("tools/y.py:7", lines[4])

    def test_a_report_with_no_location_is_summarised_with_a_dash(self) -> None:
        self.assertEqual(TOOL["location"]({"rightSideLocations": [], "leftSideLocations": []}), "-")


class ExpectationTest(unittest.TestCase):
    check = staticmethod(TOOL["check_expected"])

    def test_exact_counts_for_every_reported_type_pass(self) -> None:
        self.assertEqual(self.check(Counter({"Extract Method": 2, "Rename Variable": 1}), {"Extract Method": 2, "Rename Variable": 1}), [])

    def test_a_wrong_count_is_reported(self) -> None:
        self.assertEqual(self.check(Counter({"Extract Method": 2}), {"Extract Method": 5}), ["Extract Method: expected 5, reported 2"])

    def test_a_type_nobody_named_is_unexplained_even_when_the_named_ones_match(self) -> None:
        problems = self.check(Counter({"Extract Method": 5, "Move Method": 1}), {"Extract Method": 5})
        self.assertEqual(problems, ["Move Method: 1 reported and not expected (unexplained)"])

    def test_an_expected_type_that_was_not_reported_is_a_mismatch_not_a_pass(self) -> None:
        self.assertEqual(self.check(Counter(), {"Extract Method": 1}), ["Extract Method: expected 1, reported 0"])

    def test_the_command_line_form_is_type_equals_number_and_nothing_else(self) -> None:
        self.assertEqual(TOOL["parse_expect"](["Extract Method=5", "Merge Conditional=1"]), {"Extract Method": 5, "Merge Conditional": 1})
        for bad in ("Extract Method", "=5", "Extract Method=five"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                TOOL["parse_expect"]([bad])


if __name__ == "__main__":
    unittest.main()
