"""Tests for the evidence rule of tools/gen2_mutation_controls.py: what a
paired control must have executed for a mutant's changed code (task
1c-repair-3; Astra 1c re-review 2 BLOCK 2: reaching an enclosing branch was
credited as exercising the guard).

Oracles: small sources written here, each a shape Astra's audit named — a
changed conjunct of a refusal guard nested in another branch, a changed
guard whose body is an accepted action, a changed statement inside a
branch, a changed refusal in an exception handler — and the requirement
each must yield, written by hand. The lines a mutant changes come from
difflib over the whole text.

What these tests cannot show: that a traced run records the lines and arcs
the requirements name (that is the tool's trace step, run by hand), or that
a control meeting them asserts anything about the guard.
"""
from __future__ import annotations

import runpy
import unittest
from pathlib import Path

TOOL = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools" / "gen2_mutation_controls.py"))
changed_lines, requirements = TOOL["changed_lines"], TOOL["requirements"]

SOURCE = '''\
LIMIT = 3


def check(found, request, cancel):
    if found is not None:
        if found["digest"] != request["digest"] or found["exit"] != 0:
            raise ValueError("refused")
        kept = found["digest"]
    if cancel and found is None:
        stop(found)
    return kept


def stop(found):
    if found is None:
        record(found)
    try:
        write(found)
    except OSError:
        raise RuntimeError("unwritable")
    return LIMIT
'''


def reqs(old: str, new: str) -> list[tuple]:
    assert SOURCE.count(old) == 1, old
    return requirements(SOURCE, changed_lines(SOURCE, SOURCE.replace(old, new)))


def line(*lines: int) -> tuple:
    return ("line", frozenset(lines), frozenset(lines[:1]))


class EvidenceRuleTest(unittest.TestCase):
    def test_a_weakened_refusal_guard_is_passed_there_never_at_an_enclosing_branch(self) -> None:
        """Astra's found-result case: the changed conjunct is on the guard
        itself (line 6), inside another branch (line 5). Only leaving line 6
        for a line outside the refusal (6-7) counts; reaching line 5 does not."""
        self.assertEqual(reqs(' or found["exit"] != 0', ""), [("pass", frozenset({6}), frozenset({6, 7}), frozenset({6}))])

    def test_a_changed_guard_with_an_accepted_body_must_itself_be_executed(self) -> None:
        """Astra's cancelled-exit case: the guard at line 9 decides an
        accepted action; executing line 9 counts, and nothing encloses it."""
        self.assertEqual(reqs("    if cancel and found is None:", "    if False:"), [line(9)])

    def test_a_changed_action_counts_where_it_runs_or_where_its_own_guard_decides(self) -> None:
        """Astra's evidence-not-recorded case: the removed statement (line 16)
        or the test of the if directly holding it (line 15), either way."""
        self.assertEqual(reqs("        record(found)", "        pass"), [line(16), line(15)])

    def test_a_changed_refusal_in_a_handler_is_passed_by_the_try_completing(self) -> None:
        self.assertEqual(reqs('        raise RuntimeError("unwritable")', '        return 0'),
                         [("pass", frozenset({18}), frozenset(range(17, 21)), frozenset())])

    def test_a_changed_except_clause_counts_where_it_is_consulted_or_where_the_try_completes(self) -> None:
        self.assertEqual(reqs("    except OSError:", "    except ValueError:"),
                         [line(19), ("pass", frozenset({18}), frozenset(range(17, 21)), frozenset())])

    def test_an_insertion_is_the_line_it_runs_before_and_unchanged_context_is_not_counted(self) -> None:
        self.assertEqual(changed_lines(SOURCE, SOURCE.replace("    except OSError:\n        raise", "    except OSError:\n        return 0\n        raise")),
                         {20})
        self.assertEqual(reqs("    except OSError:\n        raise", "    except OSError:\n        return 0\n        raise"),
                         [("pass", frozenset({18}), frozenset(range(17, 21)), frozenset())])

    def test_an_outcome_raised_to_return_it_is_no_refusal(self) -> None:
        """The supervisor's Waiting returns an outcome from inside a step (a
        budgeted wait, say): its branch is executed or decided, not passed."""
        source = "def step(budget):\n    if budget.spend():\n        raise Waiting(\"waiting\")\n    return cancel()\n"
        self.assertEqual(requirements(source, changed_lines(source, source.replace("if budget.spend():", "if True:"))), [line(2)])

    def test_a_changed_constant_counts_where_a_function_reads_it(self) -> None:
        self.assertEqual(reqs("LIMIT = 3", "LIMIT = 4"), [("line", frozenset({21}), frozenset({21}))])


class HolderUsersTest(unittest.TestCase):
    """Task 2q-a: where a fixtures module holds a path-handed tool's path, its users are the test modules that import it."""

    def test_the_users_of_the_tool_fixtures_are_exactly_the_modules_that_import_them(self) -> None:
        users = TOOL["holder_users"]("gen2.tests.tool_repo_fixtures")
        # by hand: each of these test modules imports the fixtures (`from gen2.tests import tool_repo_fixtures as fx` or
        # `from gen2.tests.tool_repo_fixtures import ...`); no other test module does
        self.assertEqual(users, {"test_metrics_measure", "test_metrics_ratchet", "test_debt_register", "test_locators",
                                 "test_metrics_offenders", "test_metrics_collaboration", "test_metrics_dependencies", "test_metrics_identity"})   # the last three: task 2q-a-repair

    def test_a_module_nobody_imports_has_no_users(self) -> None:
        self.assertEqual(TOOL["holder_users"]("gen2.tests.no_such_fixtures"), set())

if __name__ == "__main__":
    unittest.main()
