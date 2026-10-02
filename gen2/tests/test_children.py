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

KillAttestationTest also pins the runner's verdict rules for a mutant's
paired controls (task 1c-repair-2 C4): each must pass under the mutant, a
disk target's through a child, and the inventory's controls must all be
runnable. Oracle: synthetic results written here, one defect each, beside the
accepted one.
"""
from __future__ import annotations

import ast
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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



class ReadinessTest(unittest.TestCase):
    """children.started / await_line (task 2b-repair-13d, Astra R13B-3): the multi-process tests waited on a child's `ready` with a blocking
    readline, kept nothing of why a child that never said it had died, and registered no cleanup before the handshake. A child that does not
    say its line within the bound now fails the test with its exit status and stderr, and it is reaped whatever the outcome. Oracle: children
    written here, one behaviour each, and the operating system's own account of them (poll, returncode)."""

    def launched(self) -> list:
        """children.popen, recording every child it starts."""
        made, real = [], children.popen

        def record(*args, **kwargs):
            made.append(real(*args, **kwargs))
            return made[-1]
        patch = mock.patch.object(children, "popen", record)
        patch.start()
        self.addCleanup(patch.stop)
        return made

    def failure(self, args: list[str], wait: float = 5.0) -> str:
        with self.assertRaises(AssertionError) as caught:
            children.started(self, args, ready="ready", wait=wait)
        return str(caught.exception)

    def test_a_child_that_says_its_line_is_started(self) -> None:
        child = children.started(self, ["-c", "print('ready', flush=True); input()"], ready="ready", stdin=subprocess.PIPE)
        self.assertIsNone(child.poll(), "and it is still running, for the test to use")

    def test_a_child_that_died_before_saying_it_fails_the_test_with_its_exit_status_and_stderr(self) -> None:
        made = self.launched()
        message = self.failure(["-c", "import sys; sys.stderr.write('open failed: database is locked'); sys.exit(3)"])
        self.assertIn("it had exited", message)
        self.assertIn("exit status 3", message)
        self.assertIn("open failed: database is locked", message)
        self.assertIn("first line ''", message, "the empty read the 13b failure showed")
        self.assertEqual([c.returncode for c in made], [3])

    def test_a_child_that_said_something_else_fails_the_test_with_what_it_said(self) -> None:
        message = self.failure(["-c", "print('starting'); print('ready', flush=True)"])
        self.assertIn("first line 'starting\\n'", message)

    def test_a_child_that_says_nothing_in_time_fails_the_test_and_is_ended(self) -> None:
        made = self.launched()
        began = time.monotonic()
        message = self.failure(["-c", "import time; time.sleep(60)"], wait=0.4)
        self.assertLess(time.monotonic() - began, 5.0, "the wait is bounded")
        self.assertIn("still running when stopped", message)
        self.assertIsNotNone(made[0].poll(), "the child that never answered is not left running")

    def test_a_line_whose_first_byte_is_timely_and_whose_rest_is_late_fails_at_the_deadline(self) -> None:
        """Astra's F3 probe (2b-repair-15): the child writes `r`, flushes, and finishes `ready` 2 s later. One `select` saw the `r` and an unbounded `readline` then waited for the rest and
        accepted it at 2 s (Astra's 0.1 s wait was accepted at 0.62 s). The line is held to the one deadline: it fails at 0.5 s, the child is ended, and the late newline is never a ready."""
        made = self.launched()
        began = time.monotonic()
        message = self.failure(["-c", "import sys, time; sys.stdout.write('r'); sys.stdout.flush(); time.sleep(2); print('eady', flush=True)"], wait=0.5)
        self.assertLess(time.monotonic() - began, 1.5, "it failed at the deadline, not when the rest of the line arrived")
        self.assertIn("still running when stopped", message)
        self.assertIsNotNone(made[0].poll(), "the child that never finished its line is not left running")

    def test_a_line_that_never_completes_fails_at_the_deadline_and_the_child_is_reaped(self) -> None:
        """On c0d963d this waited for ever on the `readline`, and nothing after it (the failure message, the cleanup's kill) ran."""
        made = self.launched()
        probe = unittest.TestCase()
        began = time.monotonic()
        with self.assertRaises(AssertionError) as caught:
            children.started(probe, ["-c", "import sys, time; sys.stdout.write('read'); sys.stdout.flush(); time.sleep(60)"], ready="ready", wait=0.4)
        self.assertLess(time.monotonic() - began, 5.0, "the wait is bounded")
        self.assertIn("still running when stopped", str(caught.exception))
        self.assertTrue(probe.doCleanups(), "the registered cleanup runs without error")
        self.assertIsNotNone(made[0].poll(), "and the child is gone")

    def test_a_line_that_arrives_in_two_timely_parts_is_accepted_and_what_follows_it_is_left_unread(self) -> None:
        """The line is taken a byte at a time up to its newline and no further: what the child printed after it is still on the pipe for the test."""
        child = children.started(self, ["-c", "import sys, time; sys.stdout.write('rea'); sys.stdout.flush(); time.sleep(0.2); sys.stdout.write('dy\\nmore\\n'); sys.stdout.flush(); input()"],
                                 ready="ready", stdin=subprocess.PIPE)
        self.assertEqual(child.stdout.readline(), "more\n")

    def test_a_child_left_running_by_a_handshake_that_failed_is_reaped_when_the_test_ends(self) -> None:
        """The cleanup is registered before anything waits on the child. Here the handshake itself fails (a stand-in that raises, and kills nothing, as a helper's own error would):
        the child is still running when the test's body is over, and only the registered cleanup ends it."""
        made = self.launched()
        probe = unittest.TestCase()

        def handshake_fails(test, child, ready, *, wait):
            raise AssertionError("the handshake failed")
        with mock.patch.object(children, "await_line", handshake_fails), self.assertRaises(AssertionError):
            children.started(probe, ["-c", "import time; time.sleep(60)"], ready="ready")
        child = made[0]
        self.assertIsNone(child.poll(), "the failed handshake left the child running")
        probe.doCleanups()
        self.assertIsNotNone(child.poll(), "the cleanup the helper registered first reaped it")
        self.assertEqual(len(made), 1)
        children.reap(child)   # and reaping again is harmless


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
        """A mutant runs its declared killers and its paired controls, and
        nothing else (task 1c-repair runtime; 1c-repair-2 C4): a killer name
        that is not exactly one test would run nothing, so it stops the run
        (unresolved_killers). The whole inventory resolves."""
        runner = self.runner
        typo = runner.Mutation("X-typo", "t", "a misspelt killer", ("test_children.KillAttestationTest.test_no_such_test",), target="ddl", old="x")
        whole_class = runner.Mutation("X-class", "t", "a class, not a test", ("test_children.KillAttestationTest",), target="ddl", old="x")
        real = runner.Mutation("X-real", "t", "a real killer", ("test_children.KillAttestationTest.test_every_killer_names_exactly_one_test",), target="ddl", old="x")
        self.assertEqual(runner.unresolved_killers([typo, whole_class, real]),
                         ["test_children.KillAttestationTest", "test_children.KillAttestationTest.test_no_such_test"])
        self.assertEqual(runner.unresolved_killers(runner.MUTATIONS), [])

    def test_a_kill_needs_its_paired_controls_passing(self) -> None:
        """Killers must fail and paired controls must pass under the mutant:
        a control that failed, erred, was skipped or never ran makes the
        mutation INVALID, however its killers did (task 1c-repair-2 C4)."""
        runner = self.runner
        m = runner.Mutation("X-paired", "t", "a guard", ("test_m.T.test_killer",), target="ddl", old="x")
        controls = ("test_m.T.test_control",)

        def result(failed=(), errored=(), skipped=(), ran=("test_m.T.test_killer", "test_m.T.test_control")):
            res = runner._Collector()
            res.failed, res.errored, res.skipped, res.ran = set(failed), {t: "boom" for t in errored}, set(skipped), set(ran)
            return res
        killed = runner.verdict(m, result(failed=["test_m.T.test_killer"]), controls)
        self.assertTrue(killed.startswith("KILLED    X-paired by 1 test(s), 1 paired control(s) passing"), killed)
        for broken in (result(failed=["test_m.T.test_killer", "test_m.T.test_control"]), result(failed=["test_m.T.test_killer"], errored=["test_m.T.test_control"]),
                       result(failed=["test_m.T.test_killer"], skipped=["test_m.T.test_control"]), result(failed=["test_m.T.test_killer"], ran=["test_m.T.test_killer"])):
            self.assertIn("paired control(s) did not pass under the mutant", runner.verdict(m, broken, controls))
        self.assertTrue(runner.verdict(m, result(), controls).startswith("SURVIVED"))
        self.assertTrue(runner.verdict(m, result(failed=["test_m.T.test_control"]), controls).startswith("INVALID"))

    def test_a_disk_targets_control_needs_a_child_that_met_the_mutant(self) -> None:
        runner, tree, sha = self.runner, Path("/tmp/child-tree"), "a" * 64
        disk = runner.Mutation("X-disk", "t", "a script only children run", ("test_m.T.test_killer",), target="gen2/supervisor/jobshim.py", old="x")
        killer = {"test": "test_m.T.test_killer", "pid": 2, "file": str(tree / "gen2/supervisor/jobshim.py"), "sha256": sha}
        judge = lambda attested: runner.judge_children(disk, attested, tree, sha, 1, ("test_m.T.test_control",))
        self.assertIsNone(judge([killer, {**killer, "test": "test_m.T.test_control"}]))
        self.assertIn("paired control(s) with no child that executed the mutant", judge([killer]))

    def test_every_mutant_has_runnable_paired_controls(self) -> None:
        """Every mutant has an entry in the controls file; each control is
        exactly one test and not one of its killers (control_problems)."""
        runner = self.runner
        m = runner.Mutation("X-m", "t", "a guard", ("test_children.KillAttestationTest.test_every_killer_names_exactly_one_test",), target="ddl", old="x")
        self.assertEqual(runner.control_problems([m], {}), [f"X-m: no entry in {runner.CONTROLS_FILE.name}"])
        self.assertEqual(runner.control_problems([m], {"X-m": {"controls": list(m.killers)}}),
                         [f"X-m: {m.killers[0]} is both a killer and a control"])
        self.assertEqual(runner.control_problems([m], {"X-m": {"controls": ["test_children.KillAttestationTest.test_no_such_test"]}}),
                         ["control test_children.KillAttestationTest.test_no_such_test is not exactly one test"])
        self.assertEqual(runner.control_problems([m], {"X-m": {"controls": ["test_children.KillAttestationTest.test_a_kill_needs_its_paired_controls_passing"]}}), [])
        self.assertEqual(runner.control_problems(runner.MUTATIONS, runner.load_controls()), [])


if __name__ == "__main__":
    unittest.main()
