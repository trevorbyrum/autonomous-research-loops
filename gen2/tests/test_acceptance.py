"""Acceptance scheduling with the actual Makefile and recording step stubs.

Disposable Git histories distinguish a known-empty DDL diff from changed or
unavailable comparisons. gen2-check is marked up to date; no real suite runs.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class AcceptanceSelectionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gen2-acceptance-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Acceptance fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.commit("gen2/store/schema/base.sql", "-- base\n")
        self.git("update-ref", "refs/remotes/origin/gen2", "HEAD")
        shutil.copyfile(Path(__file__).resolve().parents[2] / "Makefile", self.root / "Makefile")
        for name in ("requirements.txt", "requirements-dev.txt", "requirements-build.txt"):
            (self.root / "gen2" / name).touch()
        (self.root / ".venv-gen2").mkdir()
        (self.root / ".venv-gen2/.gen2-installed").touch()
        (self.root / "tools").mkdir()
        (self.root / "tools/gen2_trigger_order.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "Path('trigger-invoked').write_text('called')\n"
            "with Path('step-order').open('a') as log: log.write('trigger\\n')\n"
            "raise SystemExit(int(os.environ['STUB_TRIGGER_EXIT']))\n")
        (self.root / "tools/gen2_mutation_scope.py").write_text(
            "import argparse, os\nfrom pathlib import Path\n"
            "parser = argparse.ArgumentParser()\nparser.add_argument('--base', required=True)\nparser.add_argument('--coverage')\nparser.add_argument('--workers', type=int)\n"
            "args = parser.parse_args()\nPath('mutation-base').write_text(args.base)\n"
            "Path('shared-coverage').write_text(os.path.abspath(args.coverage))\n"
            "with Path('step-order').open('a') as log: log.write('mutation\\n')\n"
            "raise SystemExit(int(os.environ['STUB_MUTATION_EXIT']))\n")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, stderr=subprocess.STDOUT).strip()

    def commit(self, path, contents):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
        self.git("add", "--", path)
        self.git("commit", "-qm", path)

    def run_acceptance(self, *, base=None, coverage=None, trigger_exit=0, mutation_exit=0, run_units=False):
        for name in ("trigger-invoked", "mutation-base", "step-order"):
            (self.root / name).unlink(missing_ok=True)
        skipped = ["gen2-sqlite", "gen2-sqlite-native", "gen2-boundaries", "gen2-complexity", "gen2-debt",
                   "gen2-locators", "gen2-schemas", "gen2-ddl", "gen2-catalog-check", "gen2-size"] if run_units else ["gen2-check"]
        command = ["make", "--no-print-directory", *[arg for name in skipped for arg in ("-o", name)],
                   "gen2-accept", f"PYTHON={sys.executable}"]
        if base is not None:
            command.append(f"GEN2_BASE={base}")
        if coverage is not None:
            command.append(f"GEN2_COVERAGE={coverage}")
        env = {key: value for key, value in os.environ.items()
               if key not in {"MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "GEN2_BASE", "GEN2_COVERAGE", "GEN2_VENV",
                              "GEN2_TEST_WORKERS", "GEN2_MUTATION_ARGS", "GEN2_TEST_ARGS"}}
        return subprocess.run(command, cwd=self.root, env={**env, "PWD": str(self.root), "STUB_TRIGGER_EXIT": str(trigger_exit),
                              "STUB_MUTATION_EXIT": str(mutation_exit)},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)

    def assert_selection(self, invoked, reason, *, base=None, trigger_exit=0):
        result = self.run_acceptance(base=base, trigger_exit=trigger_exit)
        marker = self.root / "trigger-invoked"
        self.assertEqual(marker.read_text() if marker.exists() else None, "called" if invoked else None, result.stdout)
        self.assertIn(reason, result.stdout)
        self.assertEqual(result.returncode == 0, trigger_exit == 0, result.stdout)
        self.assertEqual("gen2-accept: all checks passed" in result.stdout, trigger_exit == 0, result.stdout)

    def test_successfully_empty_comparison_skips_trigger_order(self):
        self.assert_selection(False, "skipping trigger-order (no DDL changes:")
        self.commit("code.py", "# no DDL change\n")
        self.assert_selection(False, "skipping trigger-order (no DDL changes:")

    def test_units_and_mutation_share_the_acceptance_coverage_path(self):
        (self.root / "tools/gen2_test.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "Path('unit-coverage').write_text(os.environ['GEN2_TEST_COVERAGE'])\n"
            "with Path('step-order').open('a') as log: log.write('unit\\n')\n")
        result = self.run_acceptance(run_units=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "step-order").read_text().splitlines(), ["unit", "mutation"])
        self.assertEqual((self.root / "unit-coverage").read_text(), (self.root / "shared-coverage").read_text())

    def test_ddl_change_runs_trigger_order_and_propagates_failure(self):
        self.commit("gen2/store/schema/added.sql", "-- changed DDL\n")
        for code in (0, 9):
            with self.subTest(trigger_exit=code):
                self.assert_selection(True, "running trigger-order (DDL changed:", trigger_exit=code)

    def test_missing_default_base_invokes_trigger_order_and_propagates_failure(self):
        self.git("update-ref", "-d", "refs/remotes/origin/gen2")
        for code in (0, 9):
            with self.subTest(trigger_exit=code):
                self.assert_selection(True, "running trigger-order (DDL comparison unavailable (git diff exit 128): origin/gen2...HEAD)",
                                      trigger_exit=code)

    def test_invalid_explicit_base_invokes_trigger_order_and_propagates_failure(self):
        for code in (0, 9):
            with self.subTest(trigger_exit=code):
                self.assert_selection(True, "running trigger-order (DDL comparison unavailable (git diff exit 128): missing-base...HEAD)",
                                      base="missing-base", trigger_exit=code)

    def test_valid_base_without_merge_base_invokes_trigger_order(self):
        unrelated = self.git("commit-tree", "HEAD^{tree}", "-m", "unrelated history")
        self.assert_selection(True, "running trigger-order (DDL comparison unavailable (git diff exit 128):", base=unrelated)

    def test_trigger_precedes_mutation_and_forwards_the_exact_explicit_base(self):
        self.commit("gen2/store/schema/added.sql", "-- changed DDL\n")
        self.assert_selection(True, "running trigger-order (DDL changed:", base="HEAD~1")
        self.assertEqual((self.root / "step-order").read_text().splitlines(), ["trigger", "mutation"])
        self.assertEqual((self.root / "mutation-base").read_text(), "HEAD~1")

    def test_unchanged_ddl_still_runs_mutation_with_the_default_base(self):
        self.assert_selection(False, "skipping trigger-order (no DDL changes:")
        self.assertEqual((self.root / "step-order").read_text().splitlines(), ["mutation"])
        self.assertEqual((self.root / "mutation-base").read_text(), "origin/gen2")

    def test_each_step_failure_stops_acceptance_without_a_success_banner(self):
        self.commit("gen2/store/schema/added.sql", "-- changed DDL\n")
        for trigger, mutation, steps in ((9, 0, ["trigger"]), (0, 9, ["trigger", "mutation"])):
            with self.subTest(trigger_exit=trigger, mutation_exit=mutation):
                result = self.run_acceptance(trigger_exit=trigger, mutation_exit=mutation)
                self.assertEqual((self.root / "step-order").read_text().splitlines(), steps, result.stdout)
                self.assertEqual((self.root / "mutation-base").exists(), trigger == 0, result.stdout)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("gen2-accept: all checks passed", result.stdout)

    def test_unavailable_base_runs_trigger_before_mutation_failure(self):
        self.git("update-ref", "-d", "refs/remotes/origin/gen2")
        result = self.run_acceptance(mutation_exit=1)
        self.assertIn("running trigger-order (DDL comparison unavailable", result.stdout)
        self.assertEqual((self.root / "step-order").read_text().splitlines(), ["trigger", "mutation"])
        self.assertEqual((self.root / "mutation-base").read_text(), "origin/gen2")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("gen2-accept: all checks passed", result.stdout)
