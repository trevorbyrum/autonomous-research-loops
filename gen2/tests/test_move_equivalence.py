"""Tests for tools/gen2_move_equivalence.py, the mechanical-move equivalence check (task 2q-b3b).

Oracle: literal before/after sources written here, with the verdict worked out by hand. What they cannot show: that a rewrite
which leaves the AST equal also leaves the behaviour equal where the code now runs (a name can resolve differently); that is the replay's work.
"""
from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path

TOOL = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools" / "gen2_move_equivalence.py"))
REWRITES = ["self._core._transaction() -> self._store.transaction()", "self._core.$X -> self.$X"]
BEFORE = '''
class Reg:
    """before"""
    def a(self, req):
        with self._store.transaction():
            return self._one("t", req)

    def b(self, x: int) -> int:
        return self._now() + x

    def gone(self):
        pass


def helper(x):
    return x
'''
AFTER = BEFORE.replace('"""before"""', '"""after, reworded"""').replace("self._store.transaction()", "self._core._transaction()").replace("self._one", "self._core._one").replace(
    "self._now", "self._core._now").replace("    def gone(self):\n        pass\n", "    def __init__(self, core):\n        self._core = core\n")


class MoveEquivalenceTest(unittest.TestCase):
    def run_tool(self, before: str, after: str, rewrites=REWRITES, files=("gen2/m.py",)) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            for side, text in (("before", before), ("after", after)):
                (Path(tmp) / side / "gen2").mkdir(parents=True)
                (Path(tmp) / side / "gen2" / "m.py").write_text(text)
            return TOOL["compare"](Path(tmp) / "before", Path(tmp) / "after", [("gen2/m.py:Reg", "gen2/m.py:Reg")], rewrites, list(files))

    def test_bodies_equal_after_exactly_the_declared_rewrites_are_identical_and_the_rest_is_listed(self) -> None:
        got = self.run_tool(BEFORE, AFTER)
        self.assertEqual((got["identical"], got["different"]), (["gen2/m.py:Reg.a", "gen2/m.py:Reg.b"], []))
        self.assertEqual(got["review"], [("added", "gen2/m.py:Reg", "__init__"), ("removed", "gen2/m.py:Reg", "gone")])  # the docstring is not compared; helper is untouched

    def test_a_rewrite_that_is_not_declared_leaves_the_body_different(self) -> None:
        got = self.run_tool(BEFORE, AFTER, rewrites=REWRITES[1:])  # `self._core._transaction()` becomes `self._transaction()`, not the Store's own call
        self.assertEqual((got["identical"], got["different"]), (["gen2/m.py:Reg.b"], ["gen2/m.py:Reg.a"]))

    def test_a_change_beside_a_rewrite_is_not_hidden_by_it(self) -> None:
        for name, edit in (("a changed argument", ("self._core._one(\"t\", req)", "self._core._one(\"u\", req)")), ("another member", ("self._core._now()", "self._core._later()")),
                           ("a signature", ("def b(self, x: int)", "def b(self, x: str)")), ("an operator", ("+ x", "- x"))):
            with self.subTest(name):
                got = self.run_tool(BEFORE, AFTER.replace(*edit))
                self.assertEqual(len(got["different"]), 1, got)

    def test_a_metavariable_keeps_the_name_it_matched(self) -> None:
        got = self.run_tool(BEFORE, AFTER.replace("self._core._one", "self._core._two"))
        self.assertEqual(got["different"], ["gen2/m.py:Reg.a"])  # `_two` stays `_two`, never read back as `_one`; `b` is still identical

    def test_functions_outside_the_moved_unit_are_listed_when_they_change(self) -> None:
        got = self.run_tool(BEFORE, AFTER.replace("return x", "return x + 1") + "\ndef extra():\n    pass\n")
        self.assertEqual([r for r in got["review"] if r[1] == "gen2/m.py"], [("added", "gen2/m.py", "extra"), ("changed", "gen2/m.py", "helper")])
