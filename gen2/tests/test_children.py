"""Every gen-2 child a test starts goes through gen2/tests/children.py (task
1c: the mutation runner's child tree reaches only children started there).

Trace: Astra 1b-repair-2 review ("a future subprocess-only killer needs a disk
mutation or explicit loading mechanism"); tools/gen2_mutations.py module
docstring, "Children".

The lint (ChildLaunchRuleTest) is narrow: it looks at every literal list,
in every test module, that starts with sys.executable, and requires its next
element to be a path (a tool run by file, which the runner already hands a
mutated copy by path), never "-m" or "-c" (which would import gen2 from the
working directory). It sees only that literal-list spelling: not a tuple,
not a list held in a variable, not os.system or a shell string, not a tool
that itself starts a child (Astra 1c review C1 reproduced a tuple launch it
misses). It is a lint, not the guarantee: the mutation runner attests, per
killing test, which bytes its children executed (tools/gen2_mutations.py,
"Children"), and the helper itself fixes the import root
(HelperImportRootTest). Oracle: the AST of the test sources, read here; the
positive control is a synthetic source in each recognised spelling, and the
tuple spelling it does not recognise is pinned as unrecognised.
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
        self.assertEqual(launches('import subprocess, sys\nsubprocess.run((sys.executable, "-m", "gen2.x"))\n'), [])  # a tuple: not seen (a lint's limit)

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



class HelperImportRootTest(unittest.TestCase):
    """Astra 1c review C1: children.py used setdefault for the working
    directory, and `python -c`/`-m` put the working directory in front of
    PYTHONPATH, so a caller passing cwd=<the repository> imported the
    unmutated repository while the mutant tree was named. The helper now
    fixes the import root (the named tree alone, PYTHONSAFEPATH) whatever
    the working directory, and refuses an environment that names another."""

    def named_tree(self, tmp: str) -> None:
        """A tree like the runner's: gen2 a namespace package (as in the
        repository), one module of it marked."""
        marker = Path(tmp) / "gen2" / "core"
        marker.mkdir(parents=True)
        (marker / "canonical.py").write_text("WHERE = 'the named tree'\n", encoding="utf-8")
        saved = os.environ.get(children.ROOT_VARIABLE)
        os.environ[children.ROOT_VARIABLE] = tmp
        self.addCleanup(lambda: os.environ.pop(children.ROOT_VARIABLE) if saved is None else os.environ.__setitem__(children.ROOT_VARIABLE, saved))

    def test_a_working_directory_does_not_change_what_a_child_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.named_tree(tmp)
            (Path(tmp) / "gen2" / "core" / "where.py").write_text("import sys\nfrom gen2.core import canonical\nsys.stdout.write(canonical.WHERE)\n", encoding="utf-8")
            for flag, code in (("-c", "import gen2.core.canonical as c, sys; sys.stdout.write(c.WHERE)"), ("-m", "gen2.core.where")):
                with self.subTest(flag):
                    child = children.python([flag, code], cwd=children.REPO, capture_output=True, text=True, timeout=60)
                    self.assertEqual((child.returncode, child.stdout), (0, "the named tree"), child.stderr)

    def test_an_environment_naming_another_import_path_is_refused(self) -> None:
        for name, value in (("PYTHONPATH", str(children.REPO / "elsewhere")), ("PYTHONSAFEPATH", "")):
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    children.python(["-c", "pass"], env={**os.environ, name: value}, timeout=60)
        self.assertEqual(children.python(["-c", "pass"], env=dict(os.environ), timeout=60).returncode, 0)  # the same environment, unset: accepted



class KillAttestationTest(unittest.TestCase):
    """Astra 1c review C1: a kill is credited to a mutant only as far as the
    executing children attest it (tools/gen2_mutations.py judge_children).
    Oracle: synthetic attestations written here, one defect each, beside the
    accepted evidence."""

    @classmethod
    def setUpClass(cls) -> None:
        import importlib.util

        import sys

        spec = importlib.util.spec_from_file_location("gen2_mutations_under_test", children.REPO / "tools" / "gen2_mutations.py")
        cls.runner = sys.modules[spec.name] = importlib.util.module_from_spec(spec)  # dataclasses look the module up while it loads
        cls.addClassCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(cls.runner)
        if str(TESTS) not in sys.path:  # the runner resolves killers as it runs them: test modules by their top-level names
            sys.path.insert(0, str(TESTS))
            cls.addClassCleanup(sys.path.remove, str(TESTS))

    def test_a_kill_is_credited_only_to_attested_mutant_bytes(self) -> None:
        runner, tree, sha = self.runner, Path("/tmp/child-tree"), "a" * 64
        disk = runner.Mutation("X-disk", "t", "a script only children run", ("test_m.T.test_killer",), target="gen2/supervisor/jobshim.py", old="x")
        module = runner.Mutation("X-module", "t", "an in-process kill", ("test_m.T.test_killer",), target="gen2/supervisor/jobs.py", old="x")
        via_child = runner.Mutation("X-child", "t", "a kill through a child", ("test_m.T.test_killer",), target="gen2/supervisor/jobs.py", old="x", via_child=True)
        good = {"test": "test_m.T.test_killer", "pid": 2, "file": str(tree / "gen2/supervisor/jobshim.py"), "sha256": sha}
        judge = lambda m, attested: runner.judge_children(m, attested, tree, sha, own_pid=1)
        self.assertIsNone(judge(disk, [good]))
        self.assertIsNone(judge(module, []))  # killed in this interpreter: no child needed
        self.assertIn("no child that executed the mutant", judge(disk, []))
        self.assertIn("no child that executed the mutant", judge(via_child, []))
        self.assertIn("no child that executed the mutant", judge(disk, [{**good, "test": "test_m.T.test_other"}]))  # bound to its own test
        self.assertIn("no child that executed the mutant", judge(disk, [{**good, "pid": 1}]))  # this interpreter is not a child
        self.assertIn("other bytes", judge(disk, [good, {**good, "sha256": "b" * 64}]))  # the unmutated file, or anything else
        self.assertIn("other bytes", judge(module, [{**good, "file": str(children.REPO / "gen2/supervisor/jobs.py")}]))  # outside the tree


    def test_every_killer_names_exactly_one_test(self) -> None:
        """A mutant runs only its declared killers (task 1c-repair runtime):
        a killer name that is not exactly one test would run nothing, so it
        stops the run (unresolved_killers). The whole inventory resolves."""
        runner = self.runner
        typo = runner.Mutation("X-typo", "t", "a misspelt killer", ("test_children.KillAttestationTest.test_no_such_test",), target="ddl", old="x")
        whole_class = runner.Mutation("X-class", "t", "a class, not a test", ("test_children.KillAttestationTest",), target="ddl", old="x")
        real = runner.Mutation("X-real", "t", "a real killer", ("test_children.KillAttestationTest.test_every_killer_names_exactly_one_test",), target="ddl", old="x")
        self.assertEqual(runner.unresolved_killers([typo, whole_class, real]),
                         ["test_children.KillAttestationTest", "test_children.KillAttestationTest.test_no_such_test"])
        self.assertEqual(runner.unresolved_killers(runner.MUTATIONS), [])


if __name__ == "__main__":
    unittest.main()
