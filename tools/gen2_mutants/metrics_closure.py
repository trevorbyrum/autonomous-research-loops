"""Remaining debt, locator and tool-execution mutations after S3 retirement."""
from __future__ import annotations

from .base import Mutation

FIX = 'gen2/tests/tool_repo_fixtures.py'
HAR = 'tools/gen2_mutations.py'
MV = 'test_mutation_verdict.MixedSubtestTest.'
WT = 'test_tool_completion.WitnessTest.'


def c(mid: str, description: str, killers: tuple[str, ...], target: str, old: str, new: str, also: tuple[tuple[str, str], ...] = ()) -> Mutation:
    return Mutation(f"2QC-{mid}", "2q-a-repair-4", description, killers, target=target, old=old, new=new, also=also)


MUTATIONS: list[Mutation] = [
    c("run-no-record-is-complete", "a child that left no completion record is a completed run", (WT + "test_a_child_that_leaves_through_os_exit_zero_wrote_no_record_and_did_not_complete",
                                                                                                   WT + "test_an_exit_one_child_whose_crash_report_is_suppressed_did_not_complete"), FIX,
      "    if completion is None:\n        return \"it left no completion record: it did not return or exit normally (an os._exit, or a crash whose report was suppressed)\"",
      "    if completion is None:\n        return None"),
    c("run-record-status-unchecked", "a completion record that disagrees with the exit status is accepted", (WT + "test_a_record_that_disagrees_with_the_exit_status_is_not_a_completed_run",), FIX,
      "    if completion.get(\"status\") != done.returncode:", "    if False:"),
    c("run-launcher-records-the-status-wrongly", "the launcher records status 0 whatever the tool exited with", (WT + "test_an_exit_one_child_that_is_a_refusal_wrote_its_record_and_completed",), FIX,
      '    json.dump({"status": status}, handle)', '    json.dump({"status": 0}, handle)'),
    c("run-launcher-records-before-the-tool-runs", "the launcher writes its record before the tool has run", (WT + "test_a_child_that_leaves_through_os_exit_zero_wrote_no_record_and_did_not_complete",), FIX,
      'status = 0\ntry:\n    runpy.run_path(tool, run_name="__main__")', 'status = 0\nwith open(record, "w", encoding="utf-8") as handle:\n    json.dump({"status": 0}, handle)\ntry:\n    runpy.run_path(tool, run_name="__main__")'),
    c("harness-an-error-beside-a-failure-is-a-kill", "a killer that errored in one subtest and failed in another is KILLED", (MV + "test_an_assertion_failure_and_a_child_that_did_not_complete_in_one_killer_is_invalid",
                                                                                                                              MV + "test_a_child_that_vanished_without_a_record_is_the_same_incomplete_execution",
                                                                                                                              MV + "test_an_error_in_the_killers_own_process_is_incomplete_execution_too"), HAR,
      "    if res.errored:   # only killers and controls ran", "    if res.errored and (missing or not m.killers):   # only killers and controls ran"),
    c("harness-the-complete-child-result-is-dropped", "the collector keeps only the last line of an error", (MV + "test_the_invalid_verdict_keeps_the_complete_child_result",), HAR,
      "            self.errored_detail.setdefault(test.id(), []).append(text)\n", "            pass\n"),
    c("harness-the-invalid-verdict-shows-no-detail", "the INVALID verdict does not print the complete errors", (MV + "test_the_invalid_verdict_keeps_the_complete_child_result",), HAR,
      '                f"even when the same test also failed an assertion){shown}")', '                f"even when the same test also failed an assertion)")'),
]
