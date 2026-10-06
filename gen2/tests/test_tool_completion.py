"""Tests of how a tool subprocess is judged as a PROGRAM before a test judges what it said (task 2q-a-repair-3; Gate D #4 F4).

Gate D #4 rebuilt six mutations that were "killed" only because the tool crashed with a KeyError on the way to the defect: the parent unittest asserted that a
diagnostic was missing, the child had no diagnostic to give because it died, and the harness called that a kill although the advertised behaviour (accepting
growth without admission) never occurred. `Repo.run` (gen2/tests/tool_repo_fixtures.py) now raises `ToolDidNotComplete` for any child that did not complete as
a program: a traceback, a timeout, a signal, a load failure (an import or syntax error, an exit status no tool returns, an exit 2 without the tool's own
message). That exception is not an AssertionError, so a killer that meets it ERRORS, and the mutation harness never credits an errored killer as a kill
(tools/gen2_mutations.py: a listed killer that did not fail by assertion is INVALID). A tool's own refusal, exit 0, 1 or 2 with its message, is a completed
run: refusing is what the tools are for.

A completed run needs a positive witness (task 2q-a-repair-4, Astra's 2q-a-repair-3 review F4): exit 0 or 1 and the absence of a recognised traceback prove nothing, since
an `os._exit(0)` child, or a child that crashed with its exception hook suppressed, is indistinguishable from a tool's own refusal. Every child runs under
`tool_repo_fixtures.LAUNCHER`, which writes a completion record only when the tool returns or exits normally; `Repo.run` requires it. The witness detects ACCIDENTAL incomplete execution by trusted code (a crash, a signal, an `os._exit`, a suppressed exception hook); it does not authenticate execution. Code under test can find the record's path and write a record itself before exiting, so DELIBERATE same-process forgery is outside what it shows (trust model B: tool and test code is trusted; no confinement of the child is claimed or built; DEBT-016 item 7).

The children here are literal scripts, not the tools. What this cannot show: that every defect a tool can have ends in a program that completes (a mutant can
still hang or loop; the timeout is the only guard against that, and it is an error, not a kill).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.tool_repo_fixtures import Repo, ToolDidNotComplete


class ChildCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Repo({})
        self.addCleanup(self.repo.close)

    def run_child(self, body: str, **kwargs):
        script = Path(self.dir.name) / "child.py"
        script.write_text(textwrap.dedent(body), encoding="utf-8")
        return self.repo.run(tool=script, root=False, **kwargs)

    def completes(self, body: str, **kwargs):
        """A child that must complete as a program: if it does not, the test FAILS (by assertion), saying why, so that a mutant that wrongly rejects a completed run is killed."""
        try:
            return self.run_child(body, **kwargs)
        except ToolDidNotComplete as exc:
            self.fail(f"a completed run was judged not to be one: {exc.why}")

    def did_not_complete(self, body: str, **kwargs) -> ToolDidNotComplete:
        with self.assertRaises(ToolDidNotComplete) as raised:
            self.run_child(body, **kwargs)
        return raised.exception


class CompletedRunTest(ChildCase):
    def test_exit_zero_and_one_are_completed_runs_whatever_they_print(self) -> None:
        for status in (0, 1):
            with self.subTest(status=status):
                done = self.completes(f"import sys\nprint('out')\nprint('a refusal', file=sys.stderr)\nsys.exit({status})\n")
                self.assertEqual((done.returncode, done.stdout, done.stderr), (status, "out\n", "a refusal\n"))

    def test_a_tools_own_exit_two_with_its_message_is_a_completed_run(self) -> None:
        for prefix in fx.TOOL_MESSAGES:
            with self.subTest(prefix=prefix):
                done = self.completes(f"import sys\nprint('{prefix} the baseline cannot be read', file=sys.stderr)\nsys.exit(2)\n")
                self.assertEqual(done.returncode, 2)

    def test_every_completed_run_is_kept_whole_on_the_repository(self) -> None:
        self.completes("import sys\nprint('one')\nsys.exit(0)\n")
        self.completes("import sys\nprint('two', file=sys.stderr)\nsys.exit(1)\n")
        self.assertEqual([(r.returncode, r.stdout, r.stderr) for r in self.repo.runs], [(0, "one\n", ""), (1, "", "two\n")])


class DidNotCompleteTest(ChildCase):
    def test_a_traceback_is_a_crash_even_with_exit_one(self) -> None:
        raised = self.did_not_complete("raise KeyError('fan_out')\n")
        self.assertIn("crashed with a traceback", raised.why)
        self.assertEqual(raised.returncode, 1)
        self.assertIn("KeyError: 'fan_out'", raised.stderr)

    def test_a_signal_is_not_a_completed_run(self) -> None:
        raised = self.did_not_complete("import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n")
        self.assertEqual(raised.returncode, -9)
        self.assertIn("killed by signal 9", raised.why)

    def test_a_timeout_is_not_a_completed_run_and_keeps_what_was_printed(self) -> None:
        raised = self.did_not_complete("import sys, time\nprint('started', flush=True)\ntime.sleep(30)\n", timeout=1)
        self.assertIsNone(raised.returncode)
        self.assertIn("timed out after 1 s", raised.why)
        self.assertEqual(raised.stdout, "started\n")

    def test_a_script_that_cannot_be_loaded_is_not_a_completed_run(self) -> None:
        for name, body in {"an import error": "import not_a_module_at_all\n", "a syntax error": "def (:\n"}.items():
            with self.subTest(case=name):
                raised = self.did_not_complete(body)
                self.assertTrue("traceback" in raised.why or "could not be loaded" in raised.why, msg=raised.why)

    def test_a_syntax_error_in_the_script_itself_is_a_load_failure_without_a_traceback_header(self) -> None:
        raised = self.did_not_complete("x = (\n")
        self.assertNotIn("Traceback (most recent call last)", raised.stderr)
        self.assertIn("could not be loaded", raised.why)
        self.assertEqual(raised.returncode, 1)

    def test_a_script_that_does_not_exist_is_not_a_completed_run(self) -> None:
        with self.assertRaises(ToolDidNotComplete) as raised:
            self.repo.run(tool=Path(self.dir.name) / "nothing.py", root=False)
        self.assertEqual(raised.exception.returncode, 2)
        self.assertIn("without its own message", raised.exception.why)

    def test_an_exit_two_without_the_tools_message_is_not_a_completed_run(self) -> None:
        raised = self.did_not_complete("import sys\nprint('usage: tool [-h]', file=sys.stderr)\nsys.exit(2)\n")
        self.assertIn("exited 2 without its own message", raised.why)

    def test_an_exit_status_no_tool_returns_is_not_a_completed_run(self) -> None:
        raised = self.did_not_complete("import sys\nsys.exit(7)\n")
        self.assertIn("exit status 7", raised.why.replace("exited with status", "exit status"))
        self.assertEqual(raised.returncode, 7)

    def test_the_exception_keeps_the_command_and_the_whole_child_result_in_its_message(self) -> None:
        raised = self.did_not_complete("import sys\nprint('partial output')\nraise ValueError('boom')\n")
        text = str(raised)
        for needle in ("the tool did not complete", "child.py", "return code: 1", "partial output", "ValueError: boom"):
            self.assertIn(needle, text)
        self.assertEqual((raised.stdout, raised.command[1].endswith("child.py")), ("partial output\n", True))


class WitnessTest(ChildCase):
    """Astra's F4 boundary: statuses 0 and 1 without the tool having returned. Each case is one of her probes, run as the tool child it stands for."""

    def test_a_child_that_leaves_through_os_exit_zero_wrote_no_record_and_did_not_complete(self) -> None:
        raised = self.did_not_complete("import os\nos._exit(0)\n")
        self.assertEqual((raised.returncode, raised.stdout, raised.stderr), (0, "", ""))
        self.assertIn("no completion record", raised.why)

    def test_an_exit_one_child_whose_crash_report_is_suppressed_did_not_complete(self) -> None:
        raised = self.did_not_complete("import sys\nsys.excepthook = lambda *args: None\nraise KeyError('fan_out')\n")
        self.assertEqual((raised.returncode, raised.stderr), (1, ""))
        self.assertIn("no completion record", raised.why)

    def test_an_exit_one_child_that_is_a_refusal_wrote_its_record_and_completed(self) -> None:
        done = self.completes("import sys\nprint('gen2-metrics: refused', file=sys.stderr)\nsys.exit(1)\n")
        self.assertEqual(done.returncode, 1)

    def test_returning_from_the_script_without_exiting_is_a_normal_completion(self) -> None:
        self.assertEqual(self.completes("print('done')\n").returncode, 0)

    def test_a_status_that_is_a_message_is_exit_one_with_the_message(self) -> None:
        done = self.completes("import sys\nsys.exit('a refusal in words')\n")
        self.assertEqual((done.returncode, done.stderr), (1, "a refusal in words\n"))

    def test_the_tool_runs_as_main_with_its_own_arguments_and_its_own_directory_first_on_the_path(self) -> None:
        (Path(self.dir.name) / "sibling_module.py").write_text("VALUE = 'beside the tool'\n", encoding="utf-8")
        done = self.completes("""
            import sys
            import sibling_module
            print(__name__, sys.argv[1:], sibling_module.VALUE, __file__.endswith('child.py'), sys.argv[0].endswith('child.py'))
        """)
        self.assertEqual(done.stdout, "__main__ [] beside the tool True True\n")

    def test_a_record_that_disagrees_with_the_exit_status_is_not_a_completed_run(self) -> None:
        """The launcher cannot write such a record, so the judgment is exercised directly: a child that exited 1 whose record says 0 is not a completed run."""
        exited_one = subprocess.CompletedProcess([], 1, "", "")
        disagreeing, missing = fx.incomplete(exited_one, {"status": 0}), fx.incomplete(exited_one, None)
        self.assertIsNotNone(disagreeing, msg="a record that says 0 for a child that exited 1 is not a completed run")
        self.assertIn("record says status 0 but it exited 1", disagreeing)
        self.assertIsNone(fx.incomplete(exited_one, {"status": 1}))
        self.assertIsNotNone(missing, msg="no record, no completion")
        self.assertIn("no completion record", missing)

    def test_a_children_log_line_carries_the_completion_record(self) -> None:
        log = Path(self.dir.name) / "runs.jsonl"
        with mock.patch.dict(os.environ, {"GEN2_TOOL_RUN_LOG": str(log)}):
            self.completes("import sys\nprint('gen2-metrics: refused', file=sys.stderr)\nsys.exit(1)\n")
            self.did_not_complete("import os\nos._exit(0)\n")
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([(r["returncode"], r["completion"], bool(r["did_not_complete"])) for r in records], [(1, {"status": 1}, False), (0, None, True)])


class ErrorNotFailureTest(ChildCase):
    """The point of the exception: a test that meets a crashed child ERRORS, so no mutation harness can credit it as the failure of a killer."""

    def run_case(self, child: str) -> unittest.TestResult:
        repo = self.repo
        script = Path(self.dir.name) / "child.py"
        script.write_text(child, encoding="utf-8")

        class Probe(unittest.TestCase):
            def test_the_child_says_nothing_wrong(self) -> None:
                done = repo.run(tool=script, root=False)
                self.assertEqual(done.stderr, "")   # an assertion a crash would satisfy by accident if the child's death were read as an empty diagnostic

        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(Probe).run(result)
        return result

    def test_a_crashed_child_is_an_error_and_not_a_failure(self) -> None:
        result = self.run_case("raise KeyError('x')\n")
        self.assertEqual((len(result.errors), len(result.failures)), (1, 0))
        self.assertIn("ToolDidNotComplete", result.errors[0][1])

    def test_a_child_that_completes_and_says_something_is_a_failure(self) -> None:
        result = self.run_case("import sys\nprint('a diagnostic', file=sys.stderr)\nsys.exit(1)\n")
        self.assertEqual((len(result.errors), len(result.failures)), (0, 1))

    def test_astras_two_boundary_children_are_errors_when_a_test_expects_a_missing_diagnostic(self) -> None:
        """Her probe: a test that expects the tool to say something ("admission") meets a child that said nothing. For an ordinary refusal that silence is a failure of
        the test's assertion; for a child that vanished or crashed unreported it must be an ERROR, or a mutant that crashed the tool would be credited with a wrong result."""
        script = Path(self.dir.name) / "child.py"
        repo = self.repo
        verdicts = {}
        for name, child in {"clean-no-result": "import os\nos._exit(0)\n", "crash-without-traceback": "import sys\nsys.excepthook = lambda *args: None\nraise KeyError('fan_out')\n",
                            "crash-with-traceback": "raise KeyError('fan_out')\n", "a silent refusal": "import sys\nsys.exit(1)\n"}.items():
            script.write_text(child, encoding="utf-8")

            class Probe(unittest.TestCase):
                def test_refusal_result(self) -> None:
                    self.assertIn("admission", repo.run(tool=script, root=False).stderr)
            result = unittest.TestResult()
            unittest.defaultTestLoader.loadTestsFromTestCase(Probe).run(result)
            verdicts[name] = (len(result.errors), len(result.failures))
        self.assertEqual(verdicts, {"clean-no-result": (1, 0), "crash-without-traceback": (1, 0), "crash-with-traceback": (1, 0), "a silent refusal": (0, 1)})

    def test_a_clean_child_passes(self) -> None:
        result = self.run_case("print('fine')\n")
        self.assertEqual((len(result.errors), len(result.failures), result.testsRun), (0, 0, 1))


class RunLogTest(ChildCase):
    def test_every_child_is_logged_whole_with_its_test_and_why_it_did_not_complete(self) -> None:
        log = Path(self.dir.name) / "runs.jsonl"
        with mock.patch.dict(os.environ, {"GEN2_TOOL_RUN_LOG": str(log), "GEN2_ATTEST_TEST": "test_x.Case.test_y"}):
            self.run_child("import sys\nprint('out')\nprint('err', file=sys.stderr)\nsys.exit(1)\n")
            with self.assertRaises(ToolDidNotComplete):
                self.run_child("raise ValueError('boom')\n")
        self.assertTrue(log.exists(), "a child run is logged when the log is named")
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([(r["returncode"], r["stdout"], r["stderr"], r["test"]) for r in records[:1]], [(1, "out\n", "err\n", "test_x.Case.test_y")])
        self.assertIsNone(records[0]["did_not_complete"])
        self.assertEqual((records[1]["returncode"], records[1]["did_not_complete"]), (1, "it crashed with a traceback"))
        self.assertIn("ValueError: boom", records[1]["stderr"])

    def test_nothing_is_logged_unless_asked(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEN2_TOOL_RUN_LOG", None)
            self.run_child("print('x')\n")
        self.assertEqual(len(self.repo.runs), 1)


if __name__ == "__main__":
    unittest.main()
