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

from gen2.tests import test_acceptance

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
            "--workers", "2", *args], cwd=self.root, env=env, capture_output=True, text=True,
            timeout=test_acceptance.ACCEPTANCE_UNITS_TIMEOUT_S)  # nested campaign hang guard, shared bound
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

    def test_qualified_production_error_passes_and_test_code_error_fails(self):
        self.base({"gen2/probe.py": "def answer():\n value = 0\n return {1: 'ok'}[value]\n"})
        source = self.root / "gen2/probe.py"
        source.write_text("def answer():\n value = 1\n return {1: 'ok'}[value]\n")
        test = self.root / "gen2/tests/test_probe.py"
        test.write_text("import unittest\nfrom gen2.probe import answer\nclass Case(unittest.TestCase):\n"
                        " def test_answer(self): answer()\n")
        report = self.campaign()
        self.assertEqual(report["counts"], {"ERROR_KILL": 2, "FILTERED_GIT": 2})
        self.assertFalse(report["failed"])
        self.assertEqual(report["stage_verdicts"], {"1:ERROR_KILL": 2})
        self.assertTrue(report["qualifications"])
        self.assertTrue(all(q["valid"] for q in report["qualifications"]))
        for row in (row for row in report["mutants"] if row["verdict"] == "ERROR_KILL"):
            data = scope.marker(row["native"]["output"])
            self.assertEqual(data.get("module_path"), "gen2/probe.py")
            event, = data["events"]
            self.assertEqual(event["exception_type"], "builtins.KeyError")
            self.assertIn(event["message"], ("0", "2"))
            self.assertEqual(event.get("innermost_frame"), dict(path="gen2/probe.py", line=3))
        shutil.rmtree(self.root / "build/mutation-evidence")
        source.write_text("def answer():\n value = 1\n return value\n")
        test.write_text("import unittest\nfrom gen2.probe import answer\nclass Case(unittest.TestCase):\n"
                        " def test_answer(self): {1: 'ok'}[answer()]\n")
        report = self.campaign(expected=1)
        self.assertEqual(report["counts"], {"TEST_ERROR": 2})
        self.assertTrue(report["failed"])
        self.assertTrue(all(q["valid"] for q in report["qualifications"]))
        for row in report["mutants"]:
            event, = scope.marker(row["native"]["output"])["events"]
            self.assertEqual(event.get("innermost_frame"), dict(path="gen2/tests/test_probe.py", line=4))

    def test_unchanged_helper_error_is_not_a_kill(self):
        self.base({"gen2/probe.py": "def answer(): return 0\n",
                   "gen2/helper.py": "def consume(value):\n return value['required']\n"})
        (self.root / "gen2/probe.py").write_text("def answer(): return 1\n")
        (self.root / "gen2/tests/test_probe.py").write_text(
            "import unittest\nfrom gen2.probe import answer\nfrom gen2.helper import consume\n"
            "class Case(unittest.TestCase):\n def test_answer(self):\n"
            "  value = {'required': True} if answer() == 1 else {}\n  consume(value)\n")
        report = self.campaign(expected=1)
        self.assertEqual(report["targets"], ["gen2/probe.py"])
        self.assertEqual(report["counts"], {"TEST_ERROR": 2})
        self.assertTrue(report["failed"])
        self.assertEqual(report["stage_verdicts"], {"1:TEST_ERROR": 2})
        self.assertTrue(report["qualifications"])
        self.assertTrue(all(q["valid"] for q in report["qualifications"]))
        for row in report["mutants"]:
            self.assertEqual(row["mutation"]["module_path"], "gen2/probe.py")
            data = scope.marker(row["native"]["output"])
            self.assertEqual(data.get("module_path"), "gen2/probe.py")
            event, = data["events"]
            self.assertEqual(event.get("innermost_frame"), dict(path="gen2/helper.py", line=2))
            self.assertEqual(event["exception_type"], "builtins.KeyError")
            self.assertEqual(event["message"], "'required'")

    def test_production_error_still_requires_clean_qualification(self):
        self.base({"gen2/probe.py": "state = {}\ndef answer():\n value = 0\n return state['ready']\n"})
        (self.root / "gen2/probe.py").write_text("state = {}\ndef answer():\n value = 1\n return state['ready']\n")
        (self.root / "gen2/tests/test_probe.py").write_text(
            "import unittest\nfrom gen2.probe import answer, state\nclass Case(unittest.TestCase):\n"
            " def test_a_setup(self): state['ready'] = True\n"
            " def test_z_consumer(self): answer()\n")
        report = self.campaign(expected=1)
        self.assertEqual(report["counts"], {"SURVIVED": 2})
        self.assertTrue(report["failed"])
        self.assertEqual(report["stage_verdicts"], {"2:SURVIVED": 2})
        self.assertTrue(report["qualifications"])
        self.assertTrue(all(q["verdict"] == "ERROR_KILL" for q in report["qualifications"]))
        self.assertTrue(all(not q["valid"] for q in report["qualifications"]))

    def test_unqualified_full_stage_production_error_is_invalid(self):
        self.base({"gen2/probe.py": "def answer(fail):\n value = 0\n if fail: return {}[value]\n return value\n"})
        (self.root / "gen2/probe.py").write_text(
            "def answer(fail):\n value = 1\n if fail: return {}[value]\n return value\n")
        (self.root / "gen2/tests/test_probe.py").write_text(
            "import unittest\nfrom gen2.probe import answer\nclass Case(unittest.TestCase):\n"
            " def test_answer(self): answer(self._outcome.result.failfast)\n")
        report = self.campaign(expected=1)
        self.assertEqual(report["counts"], {"INVALID": 2, "FILTERED_GIT": 1})
        self.assertTrue(report["failed"])
        self.assertEqual(report["stage_verdicts"], {"2:ERROR_KILL": 2})
        self.assertTrue(report["qualifications"])
        self.assertTrue(all(q["verdict"] == "ERROR_KILL" and not q["valid"] for q in report["qualifications"]))

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

    # S3-1: declaration-only lines and string-literal ordering mutants are filtered in the tool.
    def classify(self, source, token, operator, occurrence=0):
        (self.root / "gen2/probe.py").write_text(source)
        index = -1
        for _ in range(occurrence + 1):
            index = source.index(token, index + 1)
        line = source.count("\n", 0, index) + 1
        column = index - (source.rfind("\n", 0, index) + 1)
        mutation = SimpleNamespace(module_path=Path("gen2/probe.py"), operator_name=operator,
                                   start_pos=(line, column), end_pos=(line, column + len(token)))
        with mock.patch.object(scope, "ROOT", self.root):
            return scope.filtered_verdict(SimpleNamespace(mutations=[mutation]), {})

    def test_declaration_shapes_are_filtered(self):
        star, flip = "core/ReplaceBinaryOperator_Mul_Div", "core/ReplaceTrueWithFalse"
        for source, token, operator in (
                ("def f(a=10):\n    return a\n", "10", "core/NumberReplacer"),
                ("def f(a, *, b):\n    return a\n", "*", star),
                ("def f(a, /, b):\n    return a\n", "/", "core/ReplaceBinaryOperator_Div_Mul"),
                ("def f(a: int | None):\n    return a\n", "|", "core/ReplaceBinaryOperator_BitOr_Add"),
                ("def f() -> int | None:\n    return None\n", "|", "core/ReplaceBinaryOperator_BitOr_Add"),
                ("x: int | None = None\n", "|", "core/ReplaceBinaryOperator_BitOr_Add"),
                ("class P(Protocol):\n    def m(self, flag: bool = True) -> int: ...\n", "True", flip),
                ("class P(Protocol):\n    def m(self): ...\n", "...", "core/NumberReplacer"),
                ('class P(typing.Protocol):\n    async def m(self):\n        "stub"\n', '"stub"', "core/NumberReplacer"),
                ("class P(Protocol[T]):\n    def m(self) -> int | None: ...\n", "|", "core/ReplaceBinaryOperator_BitOr_Add"),
                ("T = TypeVar('T', covariant=True)\n", "True", flip)):
            with self.subTest(source=source):
                self.assertEqual(self.classify(source, token, operator), "FILTERED_DECLARATION")

    def test_string_literal_ordering_mutants_are_filtered(self):
        for source in ('def f(x):\n    return x == "lit"\n', 'def f(x):\n    return "lit" == x\n',
                       'def f(x):\n    return x != "lit"\n', 'def f(x):\n    return x < "lit"\n'):
            original = "NotEq" if "!=" in source else "Lt" if "<" in source else "Eq"
            token = "!=" if "!=" in source else "<" if "<" in source else "=="
            targets = ("Lt", "LtE", "Gt", "GtE") if original != "Lt" else ("Eq", "NotEq")
            for target in targets:
                with self.subTest(source=source, target=target):
                    self.assertEqual(self.classify(source, token, f"core/ReplaceComparisonOperator_{original}_{target}"),
                                     "FILTERED_STRING_ORDER")

    def test_live_controls_are_not_filtered(self):
        eq = "core/ReplaceComparisonOperator_Eq_"
        for source, token, operator in (
                ("def f(a=1 + 2):\n    return a\n", "+", "core/ReplaceBinaryOperator_Add_Sub"),
                ("def f(a=len('x')):\n    return a\n", "len", "core/NumberReplacer"),
                ("@deco(True)\ndef f(a):\n    return a\n", "True", "core/ReplaceTrueWithFalse"),
                ("def g(a):\n    @deco(True)\n    def f(b):\n        return b\n    return f\n", "True", "core/ReplaceTrueWithFalse"),
                ("def f(a=1):\n    return a + 1\n", "+", "core/ReplaceBinaryOperator_Add_Sub"),
                ("class C:\n    x = 1 + 2\n", "+", "core/ReplaceBinaryOperator_Add_Sub"),
                ("class C:\n    def m(self):\n        return 1 + 2\n", "+", "core/ReplaceBinaryOperator_Add_Sub"),
                ("def f(x, y):\n    return x == y\n", "==", eq + "Lt"),
                ("def f(x, y):\n    return x == y\n", "==", eq + "GtE"),
                ('def f(x):\n    return x == "lit"\n', "==", eq + "NotEq"),
                ('def f(x):\n    return x == "lit"\n', "==", eq + "Is"),
                ('def f(x):\n    return x in "lit"\n', "in", "core/ReplaceComparisonOperator_In_NotIn"),
                ('def f(x):\n    return x == "lit" and 1 < 2\n', "<", "core/ReplaceComparisonOperator_Lt_Eq")):
            with self.subTest(source=source, operator=operator):
                self.assertIsNone(self.classify(source, token, operator))

    def test_declaration_overlap_controls_stay_live(self):
        flip, add = "core/ReplaceTrueWithFalse", "core/ReplaceBinaryOperator_Add_Sub"
        for source, token, operator in (
                ("class P(Protocol):\n    def f(self, a=make(True)): ...\n", "True", flip),
                ("class P(Protocol):\n    @deco(True)\n    def f(self): ...\n", "True", flip),
                ("class P(Protocol):\n    x = 1 + 2\n", "+", add),
                ("def f(a=TypeVar('T', covariant=True)): ...\n", "True", flip),
                ("def f():\n    return TypeVar('T', covariant=True)\n", "True", flip),
                ("class P(Protocol):\n    def m(self):\n        return 1 + 2\n", "+", add),
                ("class P(Protocol):\n    do_work(True)\n", "True", flip),
                ("class P(Protocol):\n    x: int = 1 + 2\n", "+", add),
                ("class P(Protocol):\n    T = TypeVar('T', covariant=True)\n", "True", flip),
                ("def f():\n    T = TypeVar('T', covariant=True)\n", "True", flip)):
            with self.subTest(source=source):
                self.assertIsNone(self.classify(source, token, operator))

    def test_campaign_reports_filtered_verdicts_and_passes_without_stage_two(self):
        self.base({"gen2/probe.py": ""})
        (self.root / "gen2/probe.py").write_text(
            "from typing import Protocol\n"
            "class Reader(Protocol):\n"
            "    def read(self, count: int = 10, flag: bool = True) -> int: ...\n"
            "def answer(): return 11\n"
            "def kind(x): return x == 'canonical'\n")
        (self.root / "gen2/tests/test_probe.py").write_text(
            "import unittest\nfrom gen2.probe import answer, kind\nclass Case(unittest.TestCase):\n"
            " def test_answer(self): self.assertEqual(answer(), 11)\n"
            " def test_kind(self): self.assertTrue(kind(''.join(['canon', 'ical']))); self.assertFalse(kind('other'))\n")
        self.git("add", "gen2/probe.py", "gen2/tests/test_probe.py")
        report = self.campaign()
        rows = {}
        for row in report["mutants"]:
            rows.setdefault(row["verdict"], []).append(row["mutation"]["start_pos"][0])
        self.assertEqual(set(rows["FILTERED_DECLARATION"]), {3})
        self.assertGreaterEqual(len(rows["FILTERED_DECLARATION"]), 2)
        self.assertEqual(set(rows["FILTERED_STRING_ORDER"]), {5})
        self.assertEqual(len(rows["FILTERED_STRING_ORDER"]), 4)
        self.assertEqual(set(rows["ASSERTION_KILL"]) - {4, 5}, set())
        self.assertEqual(set(report["counts"]), {"FILTERED_DECLARATION", "FILTERED_STRING_ORDER", "ASSERTION_KILL"})
        self.assertEqual(report["filtered_declaration_mutants"], len(rows["FILTERED_DECLARATION"]))
        self.assertEqual(report["filtered_string_order_mutants"], 4)
        self.assertEqual(report["selected_mutants"], len(rows["ASSERTION_KILL"]))
        self.assertFalse(report["failed"])
        for row in report["mutants"]:
            if row["verdict"].startswith("FILTERED"):
                self.assertEqual(scope.marker(row["native"]["output"] or "").get("stages", []), [])
        self.assertFalse([name for name in report["stage_verdicts"] if name.startswith("2:")])
