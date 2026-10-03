"""The child-root helper test under an environment that already names a tree
(task 2q-a-repair F7; Astra's 2q-a review).

`test_children.ChildLaunchRuleTest.test_the_helper_runs_children_from_the_named_tree`
asserted that, with no tree named, a child imports gen2 from the repository.
It restored the caller's GEN2_CHILD_ROOT before that assertion, so in a run
that already names a tree (the mutation runner's copy, a snapshot run of the
suite) the assertion saw the outer tree and failed. That is a test that
depended on its environment, not a product failure: the helper was honouring
the restored variable. This module runs that one test in a child whose
environment names another tree, as the mutation runner's does, and requires
that it pass and leave the variable as it found it.

The two lease-replacement tests the same snapshot run listed
(`DelegateCrashTest` and `ResearchPassCrashTest`,
`test_recovery_starts_nothing_once_the_lease_is_replaced`) are intentional
skips in every run, ordinary or snapshot, each with the reason in its skip
message; they were never failures. The test below states that too, so the
three entries of the 2q-a trace cannot be read as three failed behaviours again.

What this cannot show: that every test in the suite is independent of the
GEN2_CHILD_ROOT it is started under (the mutation runner exercises that for
the tests that kill mutants; the full suite is run without it).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from gen2.tests import children

NAMED_TREE_TEST = "gen2.tests.test_children.ChildLaunchRuleTest.test_the_helper_runs_children_from_the_named_tree"
KINDS = ("research_pass", "delegate")   # the two fixtures that skip it: ResearchPassCrashTest and DelegateCrashTest


class ChildRootEnvironmentTest(unittest.TestCase):
    def test_the_named_tree_test_passes_when_the_environment_already_names_another_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(children.REPO / "gen2", Path(tmp) / "gen2", ignore=shutil.ignore_patterns("__pycache__"))   # an outer tree, like the mutation runner's
            done = children.python(["-m", "unittest", "-v", NAMED_TREE_TEST], env={**os.environ, children.ROOT_VARIABLE: tmp},
                                   capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, msg=done.stdout + done.stderr)
        self.assertIn("ok", done.stderr)

    def test_the_two_lease_replacement_tests_are_intentional_skips_with_a_stated_reason(self) -> None:
        text = (children.REPO / "gen2" / "tests" / "test_supervisor_crash.py").read_text(encoding="utf-8")
        method = text.split("def test_recovery_starts_nothing_once_the_lease_is_replaced", 1)[1].split("\n    def ", 1)[0]   # one shared method, skipped by KIND
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.assertRegex(method, rf"if self\.KIND == \"{kind}\":\s+self\.skipTest\(\"[^\"]{{40,}}")   # skipped on purpose, with the reason in the message
        self.assertIn("the released-lease case covers it", method)
        self.assertIn("DelegateReplacementFaults", method)


if __name__ == "__main__":
    unittest.main()
