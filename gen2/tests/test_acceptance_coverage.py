"""Acceptance coverage reuse through the real recursive Makefile and runners."""
import json
import copy
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from gen2.tests import test_acceptance

CAMPAIGN_TIMEOUT_S = test_acceptance.ACCEPTANCE_UNITS_TIMEOUT_S  # nested campaign hang guard, same load-safe bound


class ParallelAcceptanceTest(unittest.TestCase):
    def test_union_rejects_missing_overlap_and_failed_shards(self):
        with mock.patch.object(sys, "path", [str(Path(__file__).resolve().parents[2] / "tools"), *sys.path]):
            check = importlib.import_module("gen2_ci_evidence").complete_union
        rows = [dict(expected=["a", "a", "b"], selected=selection, shard=[i, 2], success=True)
                for i, selection in enumerate((["a", "a"], ["b"]), 1)]
        check(rows, 2)
        for fault in ("missing_test", "missing_shard", "overlap", "failure"):
            with self.subTest(fault=fault):
                broken = copy.deepcopy(rows)
                if fault == "missing_test": broken[1]["selected"] = []
                if fault == "missing_shard": broken.pop()
                if fault == "overlap": broken[0]["selected"], broken[1]["selected"] = ["a"], ["a", "b"]
                if fault == "failure": broken[1]["success"] = False
                with self.assertRaises(ValueError): check(broken, 2)

    def test_stage2_attributes_kill_and_reproduces_its_control(self):
        fixture = test_acceptance.AcceptanceSelectionTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.root
        repository = Path(__file__).resolve().parents[2]
        for name in ("gen2_ci_evidence.py", "gen2_coverage.py", "gen2_mutation_runner.py"):
            shutil.copyfile(repository / "tools" / name, root / "tools" / name)
        source = root / "gen2/probe.py"
        source.write_text("def answer(): return 0\n")
        (root / "gen2/tests").mkdir()
        (root / "gen2/tests/test_probe.py").write_text(
            "import unittest, subprocess, sys\nfrom gen2.probe import answer\n"
            "class Parent(unittest.TestCase):\n def test_parent(self): answer()\n"
            "class Child(unittest.TestCase):\n def test_child(self):\n"
            "  self.assertEqual(subprocess.check_output([sys.executable, '-c', "
            "'from gen2.probe import answer; print(answer())'], text=True).strip(), '1')\n")
        with mock.patch.object(sys, "path", [str(repository / "tools"), *sys.path]):
            runner = importlib.import_module("gen2_mutation_runner")
            key = importlib.import_module("gen2_mutation_scope").control_key
        config = dict(targets=["gen2/probe.py"], tests=["test_probe.Parent.test_parent"], full_tests=None, stage=1, workers=2)
        def execute(config):
            result = subprocess.run([sys.executable, "tools/gen2_mutation_runner.py", json.dumps(config)],
                cwd=root, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=CAMPAIGN_TIMEOUT_S)
            return runner.marker(result.stdout)
        data = execute(config)
        stage = data["stages"][-1]
        self.assertEqual([s["verdict"] for s in data["stages"]], ["SURVIVED", "ASSERTION_KILL"])
        self.assertEqual(stage["boundary"][1], "test_probe.Child.test_child")
        self.assertEqual(sum(row["failures"] for row in stage["shards"]), 1)
        self.assertIn(stage["shard"], [row["shard"] for row in stage["shards"] if row["failures"]])
        self.assertEqual(len({row["test_pid"] for row in stage["shards"]} | {data["stages"][0]["test_pid"]}), 3)
        source.write_text("def answer(): return 1\n")
        control = dict(targets=config["targets"], tests=None, shard=stage["shard"], cutoff=stage["boundary"])
        clean = execute(control)["stages"][-1]
        self.assertEqual(clean["verdict"], "SURVIVED")
        self.assertEqual(clean["boundary"], stage["boundary"])
        self.assertEqual(clean["selected"], stage["selected"])
        survivor = execute({**config, "tests": None, "stage": 2})["stages"][-1]
        self.assertEqual(survivor["verdict"], "SURVIVED")
        self.assertEqual(survivor["tests_run"], 2)
        self.assertNotEqual(key(stage, stage["boundary"], "same"), key({**stage, "shard": [1, 3]}, stage["boundary"], "same"))


class AcceptanceCoverageReuseTest(unittest.TestCase):
    def test_recursive_make_reuses_coverage(self):
        fixture = test_acceptance.AcceptanceSelectionTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.root
        repository = Path(__file__).resolve().parents[2]
        shutil.copyfile(repository / ".gitignore", root / ".gitignore")
        for name in ("gen2_coverage.py", "gen2_test.py", "gen2_ci_evidence.py",
                     "gen2_mutation_runner.py", "gen2_mutation_scope.py"):
            shutil.copyfile(repository / "tools" / name, root / "tools" / name)
        fixture.commit("gen2/probe.py", "def answer(): return 0\n")
        (root / "gen2/probe.py").write_text("def answer(): return 1\n")
        (root / "gen2/tests").mkdir()
        (root / "gen2/tests/test_probe.py").write_text(
            "import unittest\nfrom gen2.probe import answer\nclass Probe(unittest.TestCase):\n"
            " def test_answer(self): self.assertEqual(answer(), 1)\n")
        for base in (fixture.git("rev-parse", "HEAD"), None):
            for coverage in (None, "build/explicit-coverage.sqlite"):
                with self.subTest(base=base, coverage=coverage):
                    with mock.patch.dict(os.environ, {"GEN2_TEST_LOG": str(root / "summary.log")}):
                        result = fixture.run_acceptance(base=base, coverage=coverage, run_units=True)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertEqual([row["exit"] for row in json.loads((root / "summary.log").read_text())], [0] * 8)
                    reports = root.glob("build/mutation-evidence/*/mutation-report.json")
                    report = json.loads(max(reports, key=lambda p: p.stat().st_mtime_ns).read_text())
                    self.assertTrue(report["baseline_reused"], result.stdout)
                    receipt = json.loads(Path(report["coverage"]).with_suffix(".json").read_text())
                    self.assertEqual(receipt["workers"], 8)
                    self.assertEqual(len(receipt["shards"]), 8)
                    with mock.patch.object(sys, "path", [str(repository / "tools"), *sys.path]):
                        collected = importlib.import_module("gen2_coverage").Baseline(report["coverage"]).coverage
                    collected.load()
                    self.assertIn("test_probe.Probe.test_answer", collected.get_data().measured_contexts())
                    self.assertEqual(report["counts"].get("ASSERTION_KILL"), 2)
                    self.assertEqual(Path(report["coverage"]), root / (coverage or "build/gen2-coverage.sqlite"))
