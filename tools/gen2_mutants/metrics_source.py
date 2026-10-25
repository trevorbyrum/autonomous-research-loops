"""Remaining debt, locator and tool-execution mutations after S3 retirement."""
from __future__ import annotations

from .base import Mutation

CP = {'CompletedRunTest': 'test_tool_completion.CompletedRunTest.', 'DidNotCompleteTest': 'test_tool_completion.DidNotCompleteTest.', 'ErrorNotFailureTest': 'test_tool_completion.ErrorNotFailureTest.', 'RunLogTest': 'test_tool_completion.RunLogTest.'}
FIX = 'gen2/tests/tool_repo_fixtures.py'


def s(mid: str, description: str, killers: tuple[str, ...], target: str, old: str, new: str, also: tuple[tuple[str, str], ...] = ()) -> Mutation:
    return Mutation(f"2QS-{mid}", "2q-a-repair-3", description, killers, target=target, old=old, new=new, also=also)


MUTATIONS: list[Mutation] = [
    s("run-signal-is-complete", "a child killed by a signal is a completed run", (CP["DidNotCompleteTest"] + "test_a_signal_is_not_a_completed_run",), FIX, "    if done.returncode < 0:", "    if False:"),
    s("run-traceback-is-complete", "a child that crashed with a traceback is a completed run (the crash is still no completion: only the reason differs)",
      (CP["DidNotCompleteTest"] + "test_a_traceback_is_a_crash_even_with_exit_one",), FIX,
      '    if "Traceback (most recent call last)" in (done.stdout or "") + (done.stderr or ""):', "    if False:"),
    s("run-load-failure-is-complete", "a child that could not be loaded is a completed run", (CP["DidNotCompleteTest"] + "test_a_syntax_error_in_the_script_itself_is_a_load_failure_without_a_traceback_header",), FIX,
      '    if LOAD_FAILURE.search(done.stderr or ""):', "    if False:"),
    s("run-odd-status-is-complete", "a child that exits with a status no tool returns is a completed run", (CP["DidNotCompleteTest"] + "test_an_exit_status_no_tool_returns_is_not_a_completed_run",), FIX,
      "    if done.returncode not in (0, 1, 2):", "    if False:"),
    s("run-exit-two-without-message-is-complete", "an exit 2 with no message of the tool's is a completed run", (CP["DidNotCompleteTest"] + "test_an_exit_two_without_the_tools_message_is_not_a_completed_run",
                                                                                                                CP["DidNotCompleteTest"] + "test_a_script_that_does_not_exist_is_not_a_completed_run"), FIX,
      '    if done.returncode == 2 and not any(prefix in (done.stderr or "") for prefix in TOOL_MESSAGES):', "    if False:"),
    s("run-tool-refusal-is-incomplete", "a tool's own exit 2 with its message is not a completed run", (CP["CompletedRunTest"] + "test_a_tools_own_exit_two_with_its_message_is_a_completed_run",), FIX,
      '    if done.returncode == 2 and not any(prefix in (done.stderr or "") for prefix in TOOL_MESSAGES):', "    if done.returncode == 2:"),
    s("run-timeout-is-complete", "a child that timed out is a completed run", (CP["DidNotCompleteTest"] + "test_a_timeout_is_not_a_completed_run_and_keeps_what_was_printed",), FIX,
      '            raise ToolDidNotComplete(f"it timed out after {timeout} s", command, None, out, err) from exc', "            return subprocess.CompletedProcess(command, 0, out, err)"),
    s("run-result-not-kept", "a completed run is not kept on the repository", (CP["CompletedRunTest"] + "test_every_completed_run_is_kept_whole_on_the_repository",), FIX, "        runs.append(done)\n", "        pass\n"),
    s("run-log-ignored", "the run log is not written", (CP["RunLogTest"] + "test_every_child_is_logged_whole_with_its_test_and_why_it_did_not_complete",), FIX, "    if log:\n", "    if False:\n"),
    s("run-exception-drops-the-output", "the exception drops the child's stdout and stderr", (CP["DidNotCompleteTest"] + "test_the_exception_keeps_the_command_and_the_whole_child_result_in_its_message",), FIX,
      '\\nstdout:\\n{stdout}\\nstderr:\\n{stderr}")', '")'),
]
