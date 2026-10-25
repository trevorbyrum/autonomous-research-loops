"""Acceptance scheduling with the actual Makefile and a recording trigger stub.

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
        for name in ("requirements.txt", "requirements-dev.txt"):
            (self.root / "gen2" / name).touch()
        (self.root / ".venv-gen2").mkdir()
        (self.root / ".venv-gen2/.gen2-installed").touch()
        (self.root / "tools").mkdir()
        (self.root / "tools/gen2_trigger_order.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "Path('trigger-invoked').write_text('called')\n"
            "raise SystemExit(int(os.environ['STUB_TRIGGER_EXIT']))\n")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, stderr=subprocess.STDOUT).strip()

    def commit(self, path, contents):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
        self.git("add", "--", path)
        self.git("commit", "-qm", path)

    def assert_selection(self, invoked, reason, *, base=None, trigger_exit=0):
        marker = self.root / "trigger-invoked"
        marker.unlink(missing_ok=True)
        command = ["make", "--no-print-directory", "-o", "gen2-check", "gen2-accept", f"PYTHON={sys.executable}"]
        if base is not None:
            command.append(f"GEN2_BASE={base}")
        env = {key: value for key, value in os.environ.items()
               if key not in {"MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "GEN2_BASE", "GEN2_VENV"}}
        result = subprocess.run(command, cwd=self.root, env={**env, "STUB_TRIGGER_EXIT": str(trigger_exit)},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
        self.assertEqual(marker.read_text() if marker.exists() else None, "called" if invoked else None, result.stdout)
        self.assertIn(reason, result.stdout)
        self.assertEqual(result.returncode == 0, trigger_exit == 0, result.stdout)
        self.assertEqual("gen2-accept: all checks passed" in result.stdout, trigger_exit == 0, result.stdout)

    def test_successfully_empty_comparison_skips_trigger_order(self):
        self.assert_selection(False, "skipping trigger-order (no DDL changes:")
        self.commit("code.py", "# no DDL change\n")
        self.assert_selection(False, "skipping trigger-order (no DDL changes:")

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
