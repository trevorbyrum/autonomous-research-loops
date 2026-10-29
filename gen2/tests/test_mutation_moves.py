"""Literal move-scope witnesses and concurrent same-module mutation receipts."""
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
with mock.patch.object(sys, "path", [str(ROOT / "tools"), *sys.path]):
    spec = importlib.util.spec_from_file_location("move_scope", ROOT / "tools/gen2_mutation_scope.py")
    scope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scope)


class MutationMovesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("tools", "gen2/tests"):
            (self.root / name).mkdir(parents=True)
        shutil.copy(ROOT / ".gitignore", self.root / ".gitignore")
        for name in ("gen2_mutation_scope.py", "gen2_mutation_runner.py", "gen2_coverage.py",
                     "gen2_test.py", "gen2_ci_evidence.py"):
            shutil.copy(ROOT / "tools" / name, self.root / "tools" / name)
        self.git("init", "-q")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.STDOUT)

    def base(self, files):
        for name, content in files.items():
            (self.root / name).write_text(content)
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base")

    def moved(self):
        with mock.patch.object(scope, "ROOT", self.root):
            return scope.moved_scope("HEAD")

    def test_pure_move_is_excluded(self):
        self.base({"gen2/probe.py": "first = 11\nanchor_a = 2\nanchor_b = 3\nanchor_c = 4\n"})
        (self.root / "gen2/probe.py").write_text("anchor_a = 2\nanchor_b = 3\nanchor_c = 4\nfirst = 11\n")
        changed, moved = self.moved()
        self.assertEqual(changed, {"gen2/probe.py": {4}})
        self.assertEqual(moved, {"gen2/probe.py": {4}})
        item = self.item(4)
        self.assertTrue(scope.moved_only(item, changed, moved))

    @staticmethod
    def item(start, end=None):
        return SimpleNamespace(mutations=[SimpleNamespace(module_path=Path("gen2/probe.py"),
            start_pos=(start, 0), end_pos=(end or start, 10))])

    def test_move_with_edited_token_and_new_line_stay_in_scope(self):
        self.base({"gen2/probe.py": "first = 11\nanchor_a = 2\nanchor_b = 3\nanchor_c = 4\n"})
        (self.root / "gen2/probe.py").write_text("anchor_a = 2\nanchor_b = 3\nanchor_c = 4\nfirst = 12\nnew = 99\n")
        changed, moved = self.moved()
        self.assertEqual(changed, {"gen2/probe.py": {4, 5}})
        self.assertEqual(moved, {})
        self.assertFalse(scope.moved_only(self.item(4), changed, moved))
        self.assertFalse(scope.moved_only(self.item(5), changed, moved))

    def test_reindented_cross_file_move_is_excluded(self):
        self.base({"gen2/probe.py": "def answer():\n    return 11\n", "gen2/destination.py": ""})
        (self.root / "gen2/probe.py").write_text("")
        (self.root / "gen2/destination.py").write_text("class Box:\n    def answer():\n        return 11\n")
        changed, moved = self.moved()
        self.assertEqual(changed, {"gen2/destination.py": {1, 2, 3}})
        self.assertEqual(moved, {"gen2/destination.py": {2, 3}})

    def campaign(self, *args, expected=0, env=None):
        result = subprocess.run([sys.executable, "tools/gen2_mutation_scope.py", "--base", "HEAD",
            "--workers", "2", *args], cwd=self.root, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        report, = self.root.glob("build/mutation-evidence/*/mutation-report.json")
        return json.loads(report.read_text())

    def test_report_lists_cross_file_exclusions_and_full_campaign_keeps_moves(self):
        self.base({"gen2/probe.py": "def answer():\n    return 11\n", "gen2/destination.py": ""})
        (self.root / "gen2/probe.py").write_text("")
        (self.root / "gen2/destination.py").write_text("def answer():\n    return 11\ndef fresh(): return 7\n")
        (self.root / "gen2/tests/test_probe.py").write_text(
            "import unittest\nfrom gen2.destination import answer, fresh\nclass Case(unittest.TestCase):\n"
            " def test_answer(self): self.assertEqual(answer(), 11)\n"
            " def test_fresh(self): self.assertEqual(fresh(), 7)\n")
        self.git("add", "gen2/destination.py", "gen2/tests/test_probe.py")
        report = self.campaign()
        self.assertEqual(report["moved_exclusions"], {"gen2/destination.py": {"ranges": [[1, 2]], "count": 2}})
        self.assertEqual(report["moved_excluded_lines"], 2)
        self.assertEqual(report["selected_files"], ["gen2/destination.py"])
        self.assertEqual(report["omitted_files"], ["gen2/probe.py"])
        self.assertEqual(report["counts"], {"FILTERED_MOVE": 2, "ASSERTION_KILL": 2})
        self.assertFalse(report["failed"])
        # A multi-line operator spanning a move and a new line remains blocking.
        self.assertFalse(scope.moved_only(self.item(2, 3), {"gen2/probe.py": {2, 3}}, {"gen2/probe.py": {2}}))
        shutil.rmtree(self.root / "build/mutation-evidence")
        report = self.campaign("--full", "--report-only")
        self.assertEqual(report["moved_exclusions"], {})
        self.assertEqual(report["counts"], {"ASSERTION_KILL": 4})

    def test_parallel_same_module_mutants_have_independent_verdicts(self):
        self.base({"gen2/probe.py": "def answer(): return 0\n"})
        source = self.root / "gen2/probe.py"
        source.write_text("def answer(): return 1\n")
        receipts = self.root / "receipts"
        receipts.mkdir()
        (self.root / "gen2/tests/test_probe.py").write_text(
            "import json, os, time, unittest\nfrom pathlib import Path\nfrom gen2.probe import answer\n"
            "class Case(unittest.TestCase):\n def test_value(self):\n"
            "  value = answer()\n  if value != 1:\n"
            "   receipts = Path(os.environ['MUTATION_RECEIPTS'])\n"
            "   (receipts / (str(os.getpid()) + '.json')).write_text(json.dumps(dict(value=value, root=str(Path.cwd()), pid=os.getpid())))\n"
            "   deadline = time.monotonic() + 8\n"
            "   while len(list(receipts.glob('*.json'))) < 2 and time.monotonic() < deadline: time.sleep(0.01)\n"
            "   self.assertGreaterEqual(len(list(receipts.glob('*.json'))), 2, 'mutants did not overlap')\n"
            "  self.assertNotEqual(value, 0)\n")
        report = self.campaign(expected=1, env={**os.environ, "MUTATION_RECEIPTS": str(receipts)})
        self.assertEqual(report["counts"], {"ASSERTION_KILL": 1, "SURVIVED": 1})
        self.assertEqual(report["selected_mutants"], 2)
        self.assertEqual((report["case_workers"], report["stage2_workers"]), (2, 1))
        self.assertEqual(source.read_text(), "def answer(): return 1\n")
        rows = [json.loads(path.read_text()) for path in receipts.glob("*.json")]
        roots = {row["root"] for row in rows}
        self.assertEqual(len(roots), 2, rows)
        self.assertNotIn(str(self.root), roots)
        self.assertEqual({row["value"] for row in rows}, {0, 2})
        stages = [scope.marker(row["native"]["output"])["stages"][0] for row in report["mutants"]]
        self.assertEqual([stage["stage"] for stage in stages], [1, 1])
        self.assertEqual({stage["verdict"] for stage in stages}, {"ASSERTION_KILL", "SURVIVED"})
        self.assertEqual(len({stage["test_pid"] for stage in stages}), 2)
        survivor = next(row for row in report["mutants"] if row["verdict"] == "SURVIVED")
        fallback = scope.marker(survivor["native"]["output"])["stages"][-1]
        self.assertEqual(fallback["stage"], 2)
        self.assertNotIn("shards", fallback)
        self.assertTrue(all(row["valid"] for row in report["qualifications"]))

    def test_selected_test_timeout_is_not_a_kill(self):
        self.base({"gen2/probe.py": "def answer(): return 0\n"})
        (self.root / "gen2/probe.py").write_text("def answer(): return 1\n")
        (self.root / "gen2/tests/test_probe.py").write_text(
            "import subprocess, sys, unittest\nfrom gen2.probe import answer\n"
            "class Case(unittest.TestCase):\n def test_answer(self):\n"
            "  if answer() != 1:\n"
            "   subprocess.run([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=0.05)\n")
        report = self.campaign(expected=1)
        self.assertEqual(report["counts"], {"TIMEOUT": 2})
        self.assertTrue(report["failed"])
        self.assertEqual(report["qualifications"], [])
        for row in report["mutants"]:
            stages = scope.marker(row["native"]["output"])["stages"]
            self.assertEqual([stage["stage"] for stage in stages], [1])
            self.assertEqual(stages[0]["events"][0]["exception_type"], "subprocess.TimeoutExpired")
