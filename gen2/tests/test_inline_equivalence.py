"""Tests for the extract-method check of tools/gen2_move_equivalence.py (`--inline`, task 2q-b9): a method split into private helpers is the original after the helpers are inlined back.

Oracle: literal sources written here, with each verdict, line range and problem worked out by hand. What they cannot show: that the helpers behave the same where they now run
(the replay's work), nor what a name resolves to beyond "the module or the builtins define it" (the scope check).
"""
from __future__ import annotations

import ast
import contextlib
import io
import runpy
import tempfile
import unittest
from pathlib import Path

TOOL = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools" / "gen2_move_equivalence.py"))
HELPERS = ("_ids", "_dump", "_logged")
BEFORE = '''\
import json


class R:
    def work(self, items: list, top: str, now: str) -> dict:
        """the original"""
        out = []
        for item in items:
            if item["topic"] != top:
                raise ValueError(item)
            out.append(item["id"])
        done, seen = [], set()
        for item in items:
            seen.add(item["id"])
            done.append(json.dumps(item))
        for item in items:
            self.log(now)
        return {"out": out, "done": done, "seen": seen}
'''
AFTER = '''\
import json


class R:
    def work(self, items: list, top: str, now: str) -> dict:
        """split"""
        out = self._ids(items, top)
        done, seen = self._dump(items)
        self._logged(items, now)
        return {"out": out, "done": done, "seen": seen}

    def _ids(self, items: list, top: str) -> list:
        out = []
        for item in items:
            if item["topic"] != top:
                raise ValueError(item)
            out.append(item["id"])
        return out

    def _dump(self, items: list) -> tuple:
        done, seen = [], set()
        for item in items:
            seen.add(item["id"])
            done.append(json.dumps(item))
        return done, seen

    def _logged(self, items: list, now: str) -> None:
        for item in items:
            self.log(now)
'''


def methods(text: str) -> dict:
    return {f.name: f for f in ast.parse(text).body[-1].body if isinstance(f, ast.FunctionDef)}


class InlineBackTest(unittest.TestCase):
    def check(self, after: str, names=HELPERS) -> dict:
        old, new = methods(BEFORE), methods(after)
        return TOOL["inline_back"](old["work"], new["work"], {n: new[n] for n in names if n in new})

    def test_the_original_is_the_helpers_inlined_back_and_each_helper_names_its_original_lines(self) -> None:
        got = self.check(AFTER)
        self.assertEqual((got["identical"], got["problems"]), (True, []))
        self.assertEqual(got["mapping"], [("_ids", 7, 11), ("_dump", 12, 15), ("_logged", 16, 17)])  # counted by hand in BEFORE
        self.assertEqual(TOOL["unbound"](AFTER, "R", ["work", *HELPERS]), {"work": [], "_ids": [], "_dump": [], "_logged": []})  # `json` is the module's, `ValueError` and `set` the builtins'

    def test_a_helper_docstring_is_plumbing_too(self) -> None:
        self.assertTrue(self.check(AFTER.replace("    def _dump(self, items: list) -> tuple:\n", '    def _dump(self, items: list) -> tuple:\n        """the rows"""\n'))["identical"])  # not the first helper: a docstring first in the body would be dropped by dump itself

    def test_a_change_inside_a_helper_or_beside_the_calls_is_different(self) -> None:
        for name, edit in (("a comparison", ('item["topic"] != top', 'item["topic"] == top')), ("a dropped statement", ('            out.append(item["id"])\n', "")),
                           ("a changed argument", ("json.dumps(item)", "json.dumps(items)")), ("another error type", ("ValueError(item)", "KeyError(item)")),
                           ("calls swapped", ("        out = self._ids(items, top)\n        done, seen = self._dump(items)\n", "        done, seen = self._dump(items)\n        out = self._ids(items, top)\n")),
                           ("a signature", ("def work(self, items: list, top: str, now: str)", "def work(self, items: list, top: str, now: int)")),
                           ("the answer", ('"seen": seen}\n\n', '"seen": done}\n\n'))):
            with self.subTest(name):
                got = self.check(AFTER.replace(*edit))
                self.assertEqual((got["identical"], got["mapping"]), (False, []))

    def test_the_plumbing_is_checked_and_not_assumed(self) -> None:
        for name, edit, said in (("arguments swapped", ("self._ids(items, top)", "self._ids(top, items)"), "not its parameters"),
                                 ("another return", ("        return done, seen\n", "        return seen, done\n"), "does not return exactly what the call assigns"),
                                 ("a return nobody assigns", ("            self.log(now)\n", "            self.log(now)\n        return None\n"), "does not return exactly what the call assigns"),
                                 ("an early return", ('            out.append(item["id"])\n', '            out.append(item["id"])\n            return out\n'), "a return other than the last statement"),
                                 ("a helper called twice", ("        self._logged(items, now)\n", "        self._logged(items, now)\n        self._logged(items, now)\n"), "_logged: called 2 times, not once"),
                                 ("a helper never called", ("        self._logged(items, now)\n", ""), "_logged: called 0 times, not once"),
                                 ("a call inside an expression", ("out = self._ids(items, top)", "out = self._ids(items, top) or []"), "not a whole statement"),
                                 ("a call on another object", ("self._ids(items, top)", "other._ids(items, top)"), "_ids: called 0 times, not once"),
                                 ("a default parameter", ("top: str) -> list", 'top: str = "") -> list'), "more than `self` and plain names")):
            with self.subTest(name):
                got = self.check(AFTER.replace(*edit))
                self.assertFalse(got["identical"])
                self.assertTrue(any(said in p for p in got["problems"]), got["problems"])

    def test_a_local_of_the_caller_used_by_a_helper_is_invisible_to_the_ast_and_found_by_scope(self) -> None:
        after = AFTER.replace("self._ids(items, top)", "self._ids(items)").replace("def _ids(self, items: list, top: str)", "def _ids(self, items: list)")
        self.assertEqual((self.check(after)["identical"], TOOL["unbound"](after, "R", ["work", *HELPERS])), (True, {"work": [], "_ids": ["top"], "_dump": [], "_logged": []}))  # inlined, `top` is the caller's

    def test_the_command_reports_each_verdict_and_refuses_a_helper_that_was_already_a_method(self) -> None:
        def run(before: str, after: str, helpers: str) -> tuple[int, str]:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
                for side, text in (("before", before), ("after", after)):
                    (Path(tmp) / side / "gen2").mkdir(parents=True)
                    (Path(tmp) / side / "gen2" / "m.py").write_text(text)
                code = TOOL["main"]([str(Path(tmp) / "before"), str(Path(tmp) / "after"), "--files", "gen2/m.py", "--inline", f"gen2/m.py:R.work={helpers}"])
            return code, out.getvalue()
        code, text = run(BEFORE, AFTER, ",".join(HELPERS))
        self.assertEqual(code, 0)
        self.assertIn("IDENTICAL", text)
        self.assertIn("_ids <- original lines 7-11", text)
        code, text = run(BEFORE + "\n    def _ids(self):\n        pass\n", AFTER, ",".join(HELPERS))
        self.assertEqual(code, 1)
        self.assertIn("_ids: already a method of BEFORE", text)
        code, text = run(BEFORE, AFTER, ",".join(HELPERS) + ",_missing")
        self.assertEqual(code, 1)
        self.assertIn("_missing: not defined in AFTER", text)
        code, text = run(BEFORE, AFTER.replace("def _ids(self, items: list, top: str)", "def _ids(self, items: list)").replace("self._ids(items, top)", "self._ids(items)"), ",".join(HELPERS))
        self.assertEqual(code, 1)
        self.assertIn("_ids reads ['top']", text)
