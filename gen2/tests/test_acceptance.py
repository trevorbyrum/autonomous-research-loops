"""Acceptance scheduling with the actual Makefile and recording step stubs.

gen2-check is marked up to date unless its unit step is explicitly exercised;
no real suite runs.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

# Hang guards, not performance assertions: stage-2 qualification and verifiers run suites in parallel under load.
ACCEPTANCE_TIMEOUT_S = 300
ACCEPTANCE_UNITS_TIMEOUT_S = 900


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
        (self.root / "tools/gen2_mutation_scope.py").write_text(
            "import argparse, os\nfrom pathlib import Path\n"
            "parser = argparse.ArgumentParser()\nparser.add_argument('--base', required=True)\nparser.add_argument('--coverage')\nparser.add_argument('--workers', type=int)\nparser.add_argument('--report-only', action='store_true')\n"
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

    def run_acceptance(self, *, base=None, coverage=None, mutation_exit=0, run_units=False):
        for name in ("mutation-base", "step-order"):
            (self.root / name).unlink(missing_ok=True)
        skipped = ["gen2-sqlite", "gen2-sqlite-native", "gen2-boundaries", "gen2-complexity", "gen2-debt",
                   "gen2-locators", "gen2-schemas", "gen2-ddl", "gen2-catalog-check", "gen2-size"] if run_units else ["gen2-check"]
        command = ["make", "--no-print-directory", *[arg for name in skipped for arg in ("-o", name)],
                   "gen2-campaign", f"PYTHON={sys.executable}"]
        if base is not None:
            command.append(f"GEN2_BASE={base}")
        if coverage is not None:
            command.append(f"GEN2_COVERAGE={coverage}")
        env = {key: value for key, value in os.environ.items()
               if key not in {"MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "GEN2_BASE", "GEN2_COVERAGE", "GEN2_VENV",
                              "GEN2_TEST_WORKERS", "GEN2_MUTATION_ARGS", "GEN2_TEST_ARGS"}}
        # Real recursive units initialize coverage and mutation workers. This
        # fixture checks scheduling and reuse, not a 15-second speed target.
        return subprocess.run(command, cwd=self.root, env={**env, "PWD": str(self.root), "STUB_MUTATION_EXIT": str(mutation_exit)},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=ACCEPTANCE_UNITS_TIMEOUT_S if run_units else ACCEPTANCE_TIMEOUT_S)

    def test_units_and_mutation_share_the_acceptance_coverage_path(self):
        (self.root / "tools/gen2_test.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "Path('unit-coverage').write_text(os.environ['GEN2_TEST_COVERAGE'])\n"
            "with Path('step-order').open('a') as log: log.write('unit\\n')\n")
        result = self.run_acceptance(run_units=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "step-order").read_text().splitlines(), ["unit", "mutation"])
        self.assertEqual((self.root / "unit-coverage").read_text(), (self.root / "shared-coverage").read_text())

    def test_unchanged_ddl_still_runs_mutation_with_the_default_base(self):
        result = self.run_acceptance()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "step-order").read_text().splitlines(), ["mutation"])
        self.assertEqual((self.root / "mutation-base").read_text(), "origin/gen2")

    def test_each_step_failure_stops_acceptance_without_a_success_banner(self):
        result = self.run_acceptance(mutation_exit=9)
        self.assertEqual((self.root / "step-order").read_text().splitlines(), ["mutation"], result.stdout)
        self.assertTrue((self.root / "mutation-base").exists(), result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("gen2-campaign: complete", result.stdout)
