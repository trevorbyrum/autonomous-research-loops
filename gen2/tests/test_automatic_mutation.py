"""Outcome safety, unittest subtest fail-fast, and native diff/pragma filters."""
import io
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("mutation_runner", ROOT / "tools/gen2_mutation_runner.py")
runner = importlib.util.module_from_spec(spec)
with mock.patch.object(sys, "path", [str(ROOT / "tools"), *sys.path]):
    spec.loader.exec_module(runner)
EvidenceResult, MARKER, normalize = runner.EvidenceResult, runner.MARKER, runner.normalize


class AutomaticMutationTest(unittest.TestCase):
    def test_cached_execution_configuration(self):
        coverage_tool = sys.modules["gen2_coverage"]
        with tempfile.TemporaryDirectory() as tmp:
            baseline = coverage_tool.Baseline(Path(tmp) / "map.sqlite")
            baseline.start()
            result = unittest.TestResult()
            result.testsRun = 1
            baseline.finish(result)
            self.assertTrue(baseline.valid())
            for name, value in (("executable", sys.executable + ".other"), ("version", sys.version + " changed")):
                with self.subTest(name=name), mock.patch.object(sys, name, value):
                    self.assertFalse(baseline.valid())
            with mock.patch.object(coverage_tool, "distributions", return_value=[]):
                self.assertFalse(baseline.valid())
            self.assertFalse(coverage_tool.Baseline(baseline.path, arguments={"tests": ["different"]}).valid())

    def test_native_killed_is_not_a_verdict(self):
        def result(data=None, output=None, worker="normal", native="killed"):
            return SimpleNamespace(worker_outcome=worker, test_outcome=native,
                output=output if output is not None else MARKER + json.dumps(data))
        clean = dict(exit=1, tests_run=1, errors=0, failures=1)
        cases = [(None, "PENDING"), (result(output="timeout"), "TIMEOUT"),
            (result(output=""), "INVALID"), (result(output=MARKER + "{"), "INVALID"),
            (result({**clean, "exit": 3}), "INVALID"), (result({**clean, "exit": -9}), "CRASH"),
            (result({**clean, "errors": 1}), "INVALID"),
            (result({**clean, "errors": 1, "events": [{"kind": "error", "executed": True}]}), "ERROR_KILL"),
            (result({**clean, "errors": 1, "events": [{"kind": "error", "executed": False}]}), "INVALID"),
            (result(dict(kind="SYNTAX_INVALID")), "SYNTAX_INVALID"),
            (result(clean), "ASSERTION_KILL"),
            (result({**clean, "exit": 0, "failures": 0}, native="survived"), "SURVIVED"),
            (result(clean, worker="exception"), "INVALID")]
        for native, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(normalize(native), expected)

    def test_subtests_stop_on_first_failure_and_preserve_typed_errors(self):
        visited = []
        class Case(unittest.TestCase):
            def test_failure(self):
                for i in range(5):
                    with self.subTest(i=i):
                        visited.append(i)
                        self.fail("counterexample")
            def test_error(self):
                raise ValueError("broken setup")
        runner = unittest.TextTestRunner(stream=io.StringIO(), failfast=True, resultclass=EvidenceResult)
        failed = runner.run(Case("test_failure"))
        errored = runner.run(Case("test_error"))
        self.assertEqual(visited, [0])
        self.assertEqual(failed.events[0]["kind"], "failure")
        self.assertEqual(errored.events[0]["exception_type"], "builtins.ValueError")
        loader_error = runner.run(unittest.defaultTestLoader.loadTestsFromName("no_such_mutation_test_module"))
        self.assertFalse(loader_error.events[0]["executed"])
        native = SimpleNamespace(worker_outcome="normal", test_outcome="killed", output=MARKER + json.dumps(dict(
            exit=1, tests_run=loader_error.testsRun, errors=1, failures=0, events=loader_error.events)))
        self.assertEqual(normalize(native), "INVALID")
        class FixtureError(unittest.TestCase):
            @classmethod
            def setUpClass(cls): raise ValueError("fixture execution")
            def test_unused(self): pass
        fixture = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(FixtureError))
        native.output = MARKER + json.dumps(dict(exit=1, tests_run=0, errors=1, failures=0, events=fixture.events))
        self.assertEqual(normalize(native), "ERROR_KILL")

    def test_native_filters_and_incomplete_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(ROOT / ".gitignore", root / ".gitignore")
            for rel in ("tools", "gen2/tests"):
                (root / rel).mkdir(parents=True)
            for name in ("gen2_mutation_scope.py", "gen2_mutation_runner.py", "gen2_coverage.py", "gen2_test.py", "gen2_ci_evidence.py"):
                shutil.copy(ROOT / "tools" / name, root / "tools" / name)
            source = root / "gen2/probe.py"
            source.write_text("untouched = 100\ndef answer(): return 0\ndef equivalent(): return 5\n")
            def git(*args):
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            git("init", "-q")
            git("add", "gen2/probe.py")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base")
            source.write_text("untouched = 100\ndef answer(): return 1\ndef equivalent(): return 5 # pragma: no mutate -- equivalent diagnostic\n")
            test = root / "gen2/tests/test_probe.py"
            test.write_text("import unittest\nfrom gen2.probe import answer\nclass Case(unittest.TestCase):\n def test_answer(self): self.assertEqual(answer(), 1)\n")
            def campaign(*args, env=None, flags=()):
                result = subprocess.run([sys.executable, *flags, "tools/gen2_mutation_scope.py", "--base", "HEAD", *args],
                    cwd=root, env=env, capture_output=True, text=True, timeout=60)
                reports = sorted(root.glob("build/mutation-evidence/*/mutation-report.json"), key=lambda p: p.stat().st_mtime_ns)
                return result, json.loads(reports[-1].read_text())
            result, report = campaign()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(set(report["counts"]), {"FILTERED_GIT", "PRAGMA", "ASSERTION_KILL"})
            self.assertEqual(set(report["stage_verdicts"]), {"1:ASSERTION_KILL"})
            self.assertEqual(source.read_text().splitlines()[1], "def answer(): return 1")
            self.assertFalse(report["baseline_reused"])
            cache = root / "build/gen2-coverage.sqlite"
            env = {**os.environ, "GEN2_TEST_COVERAGE": str(cache), "GEN2_TEST_LOG": str(root / "build/unit.log")}
            unit = subprocess.run([sys.executable, "tools/gen2_test.py"], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(unit.returncode, 0, unit.stdout + unit.stderr)
            partial = subprocess.run([sys.executable, "tools/gen2_test.py", "--shard", "1/2"], cwd=root, env=env, capture_output=True)
            self.assertNotEqual(partial.returncode, 0)
            result, report = campaign()
            self.assertTrue(report["baseline_reused"])
            cache.write_bytes(b"corrupt coverage")
            result, report = campaign()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(report["baseline_reused"])
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "new head")
            result, report = campaign()
            self.assertFalse(report["baseline_reused"])
            source.write_text(source.read_text().replace("equivalent diagnostic", "changed reason"))
            result, report = campaign()
            self.assertFalse(report["baseline_reused"])
            original = test.read_text()
            # A real coverage selection exceeding Linux's per-argument limit
            # must reach both fresh processes without losing test names.
            test.write_text("import unittest\nfrom gen2.probe import answer\n"
                "class Case(unittest.TestCase): pass\n"
                "def check(self): self.assertEqual(answer(), 1)\n"
                "for n in range(3000): setattr(Case, 'test_' + 'covering_' * 8 + str(n), check)\n")
            result, report = campaign()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            selected = [runner.marker(row["native"]["output"])["stages"][0]["tests"]
                        for row in report["mutants"] if row["verdict"] == "ASSERTION_KILL"]
            self.assertTrue(selected)
            self.assertTrue(all(len(json.dumps(names)) > 131072 and len(names) == 3000 for names in selected))
            test.write_text(original)
            test.write_text(original.replace("self.assertEqual(answer(), 1)", "\n  if answer() != 1: raise ValueError('mutant error')"))
            result, report = campaign()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ERROR_KILL", report["counts"])
            self.assertFalse(report["baseline_reused"])
            test.write_text(original)
            test.write_text(test.read_text().replace("answer(), 1", "answer(), 2"))
            result, report = campaign()
            self.assertEqual(result.returncode, 1)
            self.assertEqual(report["status"], "incomplete")
            self.assertGreater(report["counts"]["PENDING"], 0)
            result, report = campaign("--full", "--report-only")
            self.assertEqual(result.returncode, 0)
            self.assertTrue(report["failed"])
            self.assertEqual(report["scope"], "full")

            saved_source = source.read_text()
            for stage in (1, "1b"):
                for kind, check in (("ASSERTION_KILL", "self.assertTrue(state.get('ready'))"),
                                    ("ERROR_KILL", "state['ready']")):
                    with self.subTest(stage=stage, clean_failure=kind):
                        source.write_text("untouched = 100\ndef answer(): return " + ("1" if stage == 1 else "0") +
                            "\ndef equivalent(): return 5\n" + ("uncovered = 7\n" if stage == "1b" else ""))
                        test.write_text("import unittest\nfrom gen2.probe import answer\nstate = {}\n"
                            "class Case(unittest.TestCase):\n def test_a_setup(self): state['ready'] = True\n"
                            " def test_z_consumer(self): answer(); " + check + "\n")
                        result, report = campaign()
                        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                        self.assertEqual(report["counts"].get("SURVIVED"), 2)
                        self.assertEqual(set(report["stage_verdicts"]), {"2:SURVIVED"})
                        self.assertEqual([q["verdict"] for q in report["qualifications"]], [kind])
                        if stage == 1:
                            test.write_text(test.read_text().replace("import answer", "import answer, equivalent").replace(
                                "state['ready'] = True", "equivalent(); state['ready'] = True"))
                            result, report = campaign()
                            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                            self.assertEqual(report["counts"].get("SURVIVED"), 2)
                            self.assertEqual(set(report["stage_verdicts"]), {"1b:SURVIVED", "2:SURVIVED"})
                            self.assertEqual([q["verdict"] for q in report["qualifications"]], [kind, "SURVIVED"])

            source.write_text(saved_source)
            for kind, check in (("ASSERTION_KILL", "self.assertEqual(os.environ['TEST_RESOURCE'], 'available')"),
                                ("ERROR_KILL", "{'available': True}[os.environ['TEST_RESOURCE']]")):
                with self.subTest(environment_failure=kind):
                    test.write_text("import os, unittest\nfrom gen2.probe import answer\n"
                        "class Case(unittest.TestCase):\n def test_answer(self): answer(); " + check + "\n")
                    available = {**os.environ, "TEST_RESOURCE": "available"}
                    result, report = campaign(env=available)
                    self.assertEqual(result.returncode, 1)  # Both mutants survive.
                    result, report = campaign(env={**available, "TEST_RESOURCE": "unavailable"})
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertFalse(report.get("baseline_reused"))
                    self.assertEqual(report["status"], "incomplete")
                    self.assertGreater(report["counts"]["PENDING"], 0)

            test.write_text("import unittest\nfrom gen2.probe import answer\nclass Case(unittest.TestCase):\n"
                            " def test_answer(self): answer(); self.assertFalse(__debug__)\n")
            unit = subprocess.run([sys.executable, "-O", "tools/gen2_test.py"], cwd=root, env=env, capture_output=True)
            self.assertEqual(unit.returncode, 0, unit.stdout + unit.stderr)
            result, report = campaign(flags=("-O",))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertFalse(report.get("baseline_reused"))
            self.assertGreater(report["counts"]["PENDING"], 0)

            # Child-only coverage is absent from the parent's contexts: the
            # covering parent test survives; the full-suite child kills it.
            test.write_text("import subprocess, sys, unittest\nfrom gen2.probe import answer\n"
                "class Case(unittest.TestCase):\n def test_parent(self): answer()\n"
                " def test_child(self):\n"
                "  value = subprocess.check_output([sys.executable, '-c', 'from gen2.probe import answer; print(answer())'], text=True)\n"
                "  self.assertEqual(value.strip(), '1')\n")
            result, report = campaign()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(set(report["stage_verdicts"]), {"1:SURVIVED", "2:ASSERTION_KILL"})

            # A covering test without an assertion survives both stages and
            # must fail the gate. A new import-only line uses module coverage.
            test.write_text("import unittest\nfrom gen2.probe import answer\n"
                            "class Case(unittest.TestCase):\n def test_answer(self): answer()\n")
            result, report = campaign()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(set(report["stage_verdicts"]), {"1:SURVIVED", "2:SURVIVED"})
            source.write_text(source.read_text() + "\nuncovered = 7\n")
            result, report = campaign()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            uncovered = [row for row in report["mutants"] if row["mutation"]["start_pos"][0] == 5]
            self.assertTrue(uncovered)
            for row in uncovered:
                stages = runner.marker(row["native"]["output"])["stages"]
                self.assertEqual([stage["stage"] for stage in stages], ["1b", 2])
                self.assertEqual(stages[0]["tests"], ["test_probe.Case.test_answer"])
            source.write_text(source.read_text() + "class Box:\n @classmethod\n def value(cls): return 1\n")
            test.write_text("import unittest\nfrom gen2.probe import Box\nclass Case(unittest.TestCase):\n"
                            " def test_box(self): self.assertEqual(Box.value(), 1)\n")
            (root / "gen2/lonely.py").write_text("number = 1\n")
            git("add", "gen2/lonely.py")
            result, report = campaign()
            decorators = [row for row in report["mutants"] if row["mutation"]["operator_name"] == "core/RemoveDecorator"]
            self.assertTrue(decorators)
            for row in decorators:
                self.assertEqual(row["verdict"], "ERROR_KILL")
                self.assertEqual(runner.marker(row["native"]["output"])["stages"][0]["stage"], "1b")
            lonely = [row for row in report["mutants"] if row["mutation"]["module_path"] == "gen2/lonely.py"]
            self.assertTrue(lonely)
            for row in lonely:
                self.assertEqual([s["stage"] for s in runner.marker(row["native"]["output"])["stages"]], [2])
