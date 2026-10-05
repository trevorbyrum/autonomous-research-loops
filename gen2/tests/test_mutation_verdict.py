"""Tests of the mutation harness's verdict on a mutant whose killer did not complete (task 2q-a-repair-4; Astra's 2q-a-repair-3 review F4).

Astra rebuilt a mutant that both bypassed a ledger admission and made the cycle subcase of the killer crash the tool: the killer's smell subcase failed an assertion,
its cycle subcase met a tool child that did not complete, and the same test was therefore in the collector's failed set AND its errored set. The harness then
called it KILLED, "1 other test(s) errored in setup", although an error is not an assertion catching the mutant, and the test had not run to the end. The harness's rule
is that INCOMPLETE EXECUTION DOMINATES: any error in a test that runs under a mutant (only killers and paired controls run) makes the mutant INVALID, whatever a
sibling subtest asserted.

The collector runs real `unittest` cases here (a subtest that fails an assertion and a subtest that meets a child that crashed), and the verdict is the harness's own
(`tools/gen2_mutations.py`, loaded from the file named by HARNESS, which the mutation harness points at a mutated copy). The oracles are the cases' texts and the rule above.

What this cannot show: that every mutant in the inventory is judged by these cases (the whole inventory is rerun by `make gen2-mutation`), or that a killer which never
starts a child cannot hide a crash in its own process (an in-process error is an error just the same, and is covered by the same rule).
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from gen2.tests.tool_repo_fixtures import Repo

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "tools" / "gen2_mutations.py"   # tools/gen2_mutations.py's own mutants point this at a copy


def harness():
    """A fresh copy of the harness module, loaded from HARNESS at call time."""
    if str(REPO / "tools") not in sys.path:
        sys.path.append(str(REPO / "tools"))
    spec = importlib.util.spec_from_file_location("gen2_mutations_under_test", HARNESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHILD_THAT_CRASHES = "import sys\nprint('partial result of the child', flush=True)\nraise KeyError('cycle subcase')\n"
CHILD_THAT_REFUSES = "import sys\nprint('gen2-metrics: refused', file=sys.stderr)\nsys.exit(1)\n"


class VerdictCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Repo({})
        self.addCleanup(self.repo.close)
        self.h = harness()

    def script(self, body: str) -> Path:
        path = Path(self.dir.name) / f"child{len(list(Path(self.dir.name).iterdir()))}.py"
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def judge(self, case: type[unittest.TestCase], killer: str = "test_killer", control: str = "test_control") -> tuple[str, object]:
        """Run the case's tests through the harness's collector and return the harness's verdict on a mutant whose killer and control they are."""
        loader = unittest.defaultTestLoader
        ids = {test.id().rpartition(".")[2]: test.id() for test in loader.loadTestsFromTestCase(case)}
        result = self.h._Collector()
        loader.loadTestsFromTestCase(case).run(result)
        mutant = self.h.Mutation("T-mixed", "t", "a guard is bypassed", (ids[killer],), target="tools/x.py")
        return self.h.verdict(mutant, result, (ids[control],) if control else ()), result


class MixedSubtestTest(VerdictCase):
    def case(self, child: str, expect: str) -> type[unittest.TestCase]:
        repo, script = self.repo, self.script(child)

        class Mixed(unittest.TestCase):
            def test_killer(self) -> None:
                with self.subTest(part="the smell"):
                    self.assertEqual("admitted", "refused", msg="the mutant admits it")   # the assertion the mutant breaks
                with self.subTest(part="the cycle"):
                    done = repo.run(tool=script, root=False)
                    self.assertIn(expect, done.stderr)

            def test_control(self) -> None:
                self.assertTrue(True)
        return Mixed

    def test_an_assertion_failure_and_a_child_that_did_not_complete_in_one_killer_is_invalid(self) -> None:
        said, result = self.judge(self.case(CHILD_THAT_CRASHES, "refused"))
        self.assertEqual((sorted(n.rpartition(".")[2] for n in result.failed), sorted(n.rpartition(".")[2] for n in result.errored)), (["test_killer"], ["test_killer"]),
                         msg="the case is the mixed one: the killer is in both sets")
        self.assertTrue(said.startswith("INVALID"), msg=said)
        self.assertIn("did not complete", said)
        self.assertNotIn("KILLED", said)

    def test_the_invalid_verdict_keeps_the_complete_child_result(self) -> None:
        said, _ = self.judge(self.case(CHILD_THAT_CRASHES, "refused"))
        for needle in ("the tool did not complete", "partial result of the child", "KeyError: 'cycle subcase'", "return code: 1"):
            self.assertIn(needle, said)

    def test_the_same_killer_whose_child_completed_is_killed_by_its_assertion(self) -> None:
        """The paired positive: with the child completing (a refusal of its own), the identical assertion failure is a kill, so the verdict above is the crash's doing."""
        said, result = self.judge(self.case(CHILD_THAT_REFUSES, "refused"))
        self.assertEqual(dict(result.errored), {})
        self.assertTrue(said.startswith("KILLED"), msg=said)
        self.assertNotIn("errored", said)

    def test_a_child_that_vanished_without_a_record_is_the_same_incomplete_execution(self) -> None:
        said, _ = self.judge(self.case("import os\nos._exit(0)\n", "refused"))
        self.assertTrue(said.startswith("INVALID"), msg=said)
        self.assertIn("no completion record", said)

    def test_an_error_in_the_killers_own_process_is_incomplete_execution_too(self) -> None:
        class InProcess(unittest.TestCase):
            def test_killer(self) -> None:
                with self.subTest(part="the assertion"):
                    self.assertEqual(1, 2)
                with self.subTest(part="the lookup"):
                    {}["fan_out"]

            def test_control(self) -> None:
                pass
        said, _ = self.judge(InProcess)
        self.assertTrue(said.startswith("INVALID"), msg=said)

    def test_a_paired_control_that_errors_is_still_named_as_the_broken_control(self) -> None:
        class BrokenControl(unittest.TestCase):
            def test_killer(self) -> None:
                self.assertEqual(1, 2)

            def test_control(self) -> None:
                raise KeyError("control")
        said, _ = self.judge(BrokenControl)
        self.assertTrue(said.startswith("INVALID") and "paired control" in said, msg=said)


if __name__ == "__main__":
    unittest.main()
