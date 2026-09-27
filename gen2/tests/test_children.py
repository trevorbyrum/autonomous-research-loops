"""Every gen-2 child a test starts goes through gen2/tests/children.py (task
1c: the mutation runner's child tree reaches only children started there).

Trace: Astra 1b-repair-2 review ("a future subprocess-only killer needs a disk
mutation or explicit loading mechanism"); tools/gen2_mutations.py module
docstring, "Children".

What the rule looks at: every call, in every test module, whose argument
list starts with sys.executable. Its next element must be a path (a tool run
by file, which the runner already hands a mutated copy by path), never "-m"
or "-c" (which import gen2 from the working directory, i.e. the repository).
The helper's own calls are the one exception. Oracle: the AST of the test
sources, read here; the positive control is a synthetic source that breaks
the rule in each spelling.

What it cannot see: a child started through a variable holding the
argument list, os.system or a shell string, or a tool that itself starts a
`-m` child. Review keeps those out.
"""
from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path

from gen2.tests import children

TESTS = Path(__file__).resolve().parent
FLAGS = ("-m", "-c")


def launches(source: str) -> list[tuple[int, str]]:
    """(line, flag) for every argument list [sys.executable, "-m"|"-c", ...]."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.List) or len(node.elts) < 2:
            continue
        first, second = node.elts[0], node.elts[1]
        is_executable = isinstance(first, ast.Attribute) and first.attr == "executable" and isinstance(first.value, ast.Name) and first.value.id == "sys"
        if is_executable and isinstance(second, ast.Constant) and second.value in FLAGS:
            found.append((node.lineno, second.value))
    return found


class ChildLaunchRuleTest(unittest.TestCase):
    def test_no_test_module_starts_a_gen2_child_around_the_helper(self) -> None:
        offenders = {}
        for path in sorted(TESTS.glob("*.py")):
            if path.name == "children.py":
                continue
            found = launches(path.read_text(encoding="utf-8"))
            if found:
                offenders[path.name] = found
        self.assertEqual(offenders, {})

    def test_the_rule_sees_each_spelling(self) -> None:
        bad = ('import subprocess, sys\n'
               'subprocess.run([sys.executable, "-m", "gen2.tests.router_crash_child"])\n'
               'subprocess.Popen([sys.executable, "-c", "import gen2"], cwd=".")\n'
               'subprocess.run([sys.executable, str(TOOL), "--check"])\n')
        self.assertEqual(launches(bad), [(2, "-m"), (3, "-c")])

    def test_the_helper_runs_children_from_the_named_tree(self) -> None:
        """children.python honours GEN2_CHILD_ROOT: a child imports gen2 from
        that tree, not from the repository (the positive control for the
        runner's loading check)."""
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "gen2"
            marker.mkdir()
            (marker / "__init__.py").write_text("WHERE = 'the named tree'\n", encoding="utf-8")
            saved = os.environ.get(children.ROOT_VARIABLE)
            os.environ[children.ROOT_VARIABLE] = tmp
            try:
                named = children.python(["-c", "import gen2, sys; sys.stdout.write(gen2.WHERE)"], capture_output=True, text=True, timeout=60)
                self.assertEqual(children.path("gen2/__init__.py"), marker / "__init__.py")
            finally:
                if saved is None:
                    os.environ.pop(children.ROOT_VARIABLE)
                else:
                    os.environ[children.ROOT_VARIABLE] = saved
            self.assertEqual((named.returncode, named.stdout), (0, "the named tree"), named.stderr)
        default = children.python(["-c", "import gen2.core.canonical as c, sys; sys.stdout.write(c.__file__)"], capture_output=True, text=True, timeout=60)
        self.assertEqual(Path(default.stdout).resolve(), (children.REPO / "gen2" / "core" / "canonical.py").resolve(), default.stderr)


if __name__ == "__main__":
    unittest.main()
