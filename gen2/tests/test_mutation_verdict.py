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

Serial runs (task 2q-t3; DEBT-025 NB1, Astra's 2q-b6 review): `--jobs 1` reuses one process for every case, and a case that replaced a module left the replacement in
`sys.modules`, loaded from a temporary tree deleted since. RestoredModulesTest shows what `_restored_modules` puts back (a module put in place of another, a namespace package's
attribute for it, a module the case imported, the names a reload rebinds) on a stand-in package in a temporary directory; SerialRunTest runs the real harness serially over the
two families Astra reproduced it on, in a process of its own, and requires every mutant KILLED. What these cannot show: that no other state outlives a case (environment variables
are `_child_root`'s, a cwd or a sys.path edit nobody restores is not covered, nor is a module of the standard library or of site-packages).
"""
from __future__ import annotations

import importlib
import importlib.util
import contextlib
import io
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

from gen2.tests import children
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


class TriggerCoverageTest(unittest.TestCase):
    """Final installed guards need coverage; retired source text does not."""

    def setUp(self) -> None:
        self.h = harness()
        self.ddl = "CREATE TABLE t (v INTEGER);\n"
        self.h.MUTATIONS = []
        self.h.SECOND_LAYER_TRIGGERS = set()

    @staticmethod
    def guard(name: str, reason: str) -> str:
        return (f"CREATE TRIGGER {name} BEFORE INSERT ON t WHEN NEW.v < 0\n"
                f"BEGIN\n  SELECT RAISE(ABORT, '{reason}');\nEND;\n")

    def cover(self, name: str) -> None:
        self.h.MUTATIONS.append(self.h.Mutation("test-" + name, "test", "drop guard", (), drop_trigger=name))

    def test_replacement_ignores_retired_definition_but_keeps_uncovered_live_guard(self) -> None:
        self.ddl += (self.guard("retired", "old") + "DROP TRIGGER retired;\n"
                     + self.guard("successor", "new") + self.guard("uncovered_live", "live"))
        self.cover("successor")
        self.assertEqual(self.h.uncovered_triggers(self.ddl), ["uncovered_live"])
        self.cover("uncovered_live")
        self.assertEqual(self.h.uncovered_triggers(self.ddl), [])

    def test_same_name_recreation_requires_coverage_of_the_final_body(self) -> None:
        self.ddl += self.guard("same", "retired body") + "DROP TRIGGER same;\n" + self.guard("same", "live body")
        self.h.MUTATIONS = [self.h.Mutation("old-body", "test", "edit retired body", (), old="'retired body'", new="'changed'")]
        self.assertEqual(self.h.uncovered_triggers(self.ddl), ["same"])
        self.h.MUTATIONS = [self.h.Mutation("live-body", "test", "edit live body", (), old="'live body'", new="'changed'")]
        self.assertEqual(self.h.uncovered_triggers(self.ddl), [])

    def test_identical_same_name_recreation_remains_installed(self) -> None:
        self.ddl += self.guard("same", "same body") + "DROP TRIGGER same;\n" + self.guard("same", "same body")
        self.assertEqual(self.h.uncovered_triggers(self.ddl), ["same"])
        self.cover("same")
        self.assertEqual(self.h.uncovered_triggers(self.ddl), [])

    def test_comments_literals_and_unrelated_drops_do_not_retire_a_live_guard(self) -> None:
        self.ddl += (self.guard("live", "DROP TRIGGER live;")
                     + "-- DROP TRIGGER live;\n/* DROP TRIGGER live; */\n"
                     + self.guard("unrelated", "other") + "DROP TRIGGER unrelated;\n")
        self.assertEqual(self.h.uncovered_triggers(self.ddl), ["live"])
        self.cover("live")
        self.assertEqual(self.h.uncovered_triggers(self.ddl), [])


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


class RestoredModulesTest(unittest.TestCase):
    """`_restored_modules` (the harness's own), on a stand-in package in a temporary directory: `<pkg>.mod`, loaded before the case, and `<pkg>.other`, not. The package has no
    `__init__.py`, as gen2 and gen2.router have none: a namespace package has no file, only a path."""

    def setUp(self) -> None:
        self.h = harness()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.pkg = f"t3pkg{id(self):x}"
        (Path(self.dir.name) / self.pkg).mkdir()
        for name, value in (("mod", "original"), ("other", "other")):
            (Path(self.dir.name) / self.pkg / f"{name}.py").write_text(f'VALUE = "{value}"\n', encoding="utf-8")
        sys.path.insert(0, self.dir.name)
        self.addCleanup(sys.path.remove, self.dir.name)
        self.addCleanup(lambda: [sys.modules.pop(name) for name in [n for n in sys.modules if n == self.pkg or n.startswith(self.pkg + ".")]])
        importlib.invalidate_caches()
        self.mod = importlib.import_module(f"{self.pkg}.mod")
        self.name = f"{self.pkg}.mod"

    def test_a_module_put_in_place_of_another_in_sys_modules_is_the_original_again(self) -> None:
        with self.h._restored_modules():
            sys.modules[self.name] = types.ModuleType(self.name)
        self.assertIs(sys.modules[self.name], self.mod)

    def test_a_namespace_packages_attribute_for_a_replaced_submodule_is_the_original_again(self) -> None:
        """The attribute `from <pkg> import mod` reads: the half of the contamination a restored `sys.modules` alone leaves (the first draft of the fix made 2QB6 worse)."""
        package = sys.modules[self.pkg]
        self.assertIsNone(getattr(package, "__file__", None), msg="the stand-in is a namespace package, as gen2.router is")
        with self.h._restored_modules():
            setattr(package, "mod", types.ModuleType(self.name))
        self.assertIs(package.mod, self.mod)

    def test_a_module_first_imported_by_the_case_is_dropped(self) -> None:
        other = f"{self.pkg}.other"
        self.assertNotIn(other, sys.modules)
        with self.h._restored_modules():
            importlib.import_module(other)
            self.assertIn(other, sys.modules)
        self.assertNotIn(other, sys.modules)
        self.assertFalse(hasattr(sys.modules[self.pkg], "other"), msg="nor is it left as an attribute of its package")

    def test_a_module_reloaded_over_a_mutant_holds_what_it_held(self) -> None:
        (Path(self.dir.name) / self.pkg / "mod.py").write_text('VALUE = "reloaded by the case"\nEXTRA = 1\n', encoding="utf-8")
        with self.h._restored_modules():
            importlib.reload(self.mod)
            self.assertEqual((self.mod.VALUE, self.mod.EXTRA), ("reloaded by the case", 1), msg="the case's own state: what the restore undoes")
            self.mod.POINTED = "a temporary path"   # a name a case adds, as it points a test module's attribute at a mutant's copy
        self.assertEqual(self.mod.VALUE, "original")
        self.assertFalse(hasattr(self.mod, "EXTRA") or hasattr(self.mod, "POINTED"))

    def test_the_modules_are_restored_when_the_case_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.h._restored_modules():
                sys.modules[self.name] = types.ModuleType(self.name)
                raise RuntimeError("a case that died")
        self.assertIs(sys.modules[self.name], self.mod)

    def test_modules_of_the_standard_library_are_left_alone(self) -> None:
        sys.modules.pop("sched", None)
        with self.h._restored_modules():
            import sched  # noqa: F401 (a standard-library module first imported by the case)
        self.assertIn("sched", sys.modules, msg="a C extension or a stdlib module is not unloaded: only the repository's own, and temporary copies of it")


class BaselineModesTest(unittest.TestCase):
    def selected(self, target, *, sql_bad, file_bad):
        with mock.patch.object(sys, 'path', list(sys.path)):
            return self._selected(target, sql_bad=sql_bad, file_bad=file_bad)

    def _selected(self, target, *, sql_bad, file_bad):
        h = harness()
        good, bad = h._Collector(), h._Collector()
        good.testsRun = bad.testsRun = 1
        bad.failed.add('unmutated-baseline-failure')
        mutation = h.Mutation('T-selection', 'test', 'loading mode', ('killer',), target=target)
        with mock.patch.multiple(h, MUTATIONS=[mutation], load_controls=mock.Mock(return_value={}),
                unresolved_killers=mock.Mock(return_value=[]), control_problems=mock.Mock(return_value=[]),
                uncovered_triggers=mock.Mock(return_value=[])), \
                mock.patch.object(h, 'run', return_value=bad if sql_bad else good) as sql, \
                mock.patch.object(h, '_run_file_mutation_unmutated', return_value=bad if file_bad else good) as file, \
                mock.patch.object(h, '_evaluate', return_value='KILLED T-selection') as evaluate, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = h.main(['--only', 'T-selection', '--jobs', '1'])
        return code, sql.call_count, file.call_count, evaluate.call_count

    def test_sql_baseline_refusal_stops_selected_sql(self):
        for target in ('ddl', 'connection'):
            with self.subTest(target=target):
                self.assertEqual(self.selected(target, sql_bad=True, file_bad=False), (1, 1, 0, 0))

    def test_sql_selection_runs_its_baseline(self):
        self.assertEqual(self.selected('ddl', sql_bad=False, file_bad=False), (0, 1, 0, 1))

    def test_file_baseline_refusal_stops_selected_file(self):
        self.assertEqual(self.selected('gen2/router/service.py', sql_bad=True, file_bad=True), (1, 0, 1, 0))

    def test_file_selection_runs_its_baseline_without_unrelated_sql(self):
        self.assertEqual(self.selected('gen2/router/service.py', sql_bad=True, file_bad=False), (0, 0, 1, 1))


    def test_selection_preserves_the_import_search_path(self):
        before = sys.path, tuple(sys.path)
        self.selected('ddl', sql_bad=False, file_bad=False)
        self.assertIs(sys.path, before[0])
        self.assertEqual(tuple(sys.path), before[1])


class SerialRunTest(unittest.TestCase):
    """Astra's two reproductions of the contamination (DEBT-025 NB1), through the real harness run as `--jobs 1` in a process of its own: before the fix `--only 2QB6` reported 5
    of 6 killed and the Status pair 1 of 2 (the control of the mutant after a transaction mutant read the deleted temporary file of the one before)."""

    def serial(self, only: str) -> subprocess.CompletedProcess:
        return children.python([str(REPO / "tools" / "gen2_mutations.py"), "--only", only, "--jobs", "1"], capture_output=True, text=True, timeout=900)

    def verdicts(self, only: str, expected: list[str]) -> None:
        done = self.serial(only)
        diagnostic = f"command: {done.args!r}\nexit code: {done.returncode}\nstdout:\n{done.stdout}\nstderr:\n{done.stderr}"
        self.assertEqual(done.returncode, 0, msg=diagnostic)
        lines = done.stdout.splitlines()
        said = [line for line in lines if line.startswith(("KILLED", "INVALID", "SURVIVED"))]
        self.assertEqual([line.split()[0] for line in said], ["KILLED"] * len(expected), msg=diagnostic)
        self.assertEqual(sorted(line.split()[1] for line in said), sorted(expected), msg=diagnostic)
        self.assertIn(f"mutation run: {len(expected)}/{len(expected)} killed", lines[-1] if lines else "", msg=diagnostic)

    def test_the_six_lifecycle_composition_mutants_are_all_killed_serially(self) -> None:
        expected = [m.mid for m in harness().MUTATIONS if m.mid.startswith("2QB6")]
        self.assertEqual(len(expected), 6, msg="Astra's reproduction is the six of 2QB6")
        self.verdicts("2QB6", expected)

    def test_the_status_pair_is_killed_serially_too(self) -> None:
        pair = ["2QB2-status-opens-its-own-transaction", "2QB2-router-inherits-a-collaborator"]
        self.verdicts(",".join(pair), pair)


class SerialDiagnosticsTest(unittest.TestCase):
    def test_every_verdict_failure_keeps_the_command_exit_code_stdout_and_stderr(self) -> None:
        command = [sys.executable, str(HARNESS), "--only", "T-example", "--jobs", "1"]
        for code, out in ((7, "partial output\n"), (0, ""), (0, "KILLED T-other\n"), (0, "KILLED T-example\nwrong summary\n")):
            with self.subTest(code=code, out=out):
                done = subprocess.CompletedProcess(command, code, out, "child startup diagnostic\n")
                with mock.patch.object(children, "python", return_value=done), self.assertRaises(AssertionError) as caught:
                    SerialRunTest().verdicts("T-example", ["T-example"])
                message = str(caught.exception)
                for needle in (repr(command), f"exit code: {code}", "stdout:", out, "stderr:", done.stderr):
                    self.assertIn(needle, message)


if __name__ == "__main__":
    unittest.main()
