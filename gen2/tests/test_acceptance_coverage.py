"""Acceptance coverage reuse through the real recursive Makefile and runners."""
import json
from pathlib import Path
import shutil
import unittest

from gen2.tests import test_acceptance


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
                    result = fixture.run_acceptance(base=base, coverage=coverage, run_units=True)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    reports = root.glob("build/mutation-evidence/*/mutation-report.json")
                    report = json.loads(max(reports, key=lambda p: p.stat().st_mtime_ns).read_text())
                    self.assertTrue(report["baseline_reused"], result.stdout)
                    self.assertEqual(report["counts"].get("ASSERTION_KILL"), 2)
                    self.assertEqual(Path(report["coverage"]), root / (coverage or "build/gen2-coverage.sqlite"))
