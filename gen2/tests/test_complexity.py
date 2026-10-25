"""Black-box controls for the two absolute Radon ceilings (ruling D5)."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from gen2.tests import children


class ComplexityTest(unittest.TestCase):
    def check(self, source: str, function: int, average: float):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gen2").mkdir()
            (root / "gen2/probe.py").write_text(source)
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "add", "gen2/probe.py"], check=True, capture_output=True)
            return children.python([str(children.path("tools/check_gen2_complexity.py")), "--root", directory,
                                    "--max-function", str(function), "--max-average", str(average)], capture_output=True, text=True)

    def test_exact_ceiling_passes_and_each_ceiling_blocks_independently(self) -> None:
        # One decision gives f complexity 2; g is straight-line, so the mean is 1.5.
        source = "def f(x):\n    if x: return 1\n    return 0\ndef g(): return 0\n"
        for function, average, expected, message in ((2, 1.5, 0, "average 1.500000"),
                                                       (1, 1.5, 1, "COMPLEXITY EXCEEDED: gen2/probe.py:1::f"),
                                                       (2, 1.4, 1, "AVERAGE COMPLEXITY EXCEEDED")):
            with self.subTest(function=function, average=average):
                result = self.check(source, function, average)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIn(message, result.stdout)

    def test_a_closure_and_a_method_are_both_subject_to_the_function_ceiling(self) -> None:
        for source, name in (("def outer():\n    def inner(x):\n        if x: return 1\n        return 0\n    return inner\n", "inner"),
                              ("class C:\n    def method(self, x):\n        if x: return 1\n        return 0\n", "method")):
            with self.subTest(name=name):
                result = self.check(source, 1, 10)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(name, result.stdout)

    def test_unparseable_production_cannot_pass(self) -> None:
        result = self.check("def broken(:\n", 10, 10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("gen2-complexity:", result.stderr)


if __name__ == "__main__":
    unittest.main()
