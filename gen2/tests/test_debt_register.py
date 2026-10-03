"""Black-box tests of `tools/check_gen2_debt.py`, the debt register's phase-close
check (task 2q-a; charter "Root-cause fixes, not patches": "the build fails if
that phase closes with the entry still open").

Each test writes a throwaway repository holding `docs/gen2/DEBT-REGISTER.md` and
`docs/gen2/phase-status.json` (gen2/tests/tool_repo_fixtures.py), runs the
tool on it and asserts its exit status and what it prints. The oracle is the
rule: an OPEN entry owned, itself or through its phase, by a CLOSED task or
phase fails; so does an entry that is incomplete, unowned or unevidenced; a
mitigation needs the operator's dated acceptance (only the operator accepts
one).

What this cannot show: that the register is complete, that a `closed by` is
true, or that anyone sets a task to closed when it is accepted. The last is a
process step, written where the status file lives and in BUILD-STATE.md.
"""
from __future__ import annotations

import json
import re
import unittest

from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.tool_repo_fixtures import Repo

REGISTER = "docs/gen2/DEBT-REGISTER.md"
STATUS = "docs/gen2/phase-status.json"

DEFAULT_ENTRY = {"kind": "obligation", "status": "open", "owner": "task 2e1", "what": "a rule the task must satisfy",
                 "source": "operator ruling 2026-10-02 (REVIEW-LOG.md)", "removal": "the 2e1 review verifies it"}
MITIGATION = {"kind": "mitigation", "status": "open", "owner": "phase 3", "what": "a shim", "found_by": "Astra review of 2026-09-30",
              "accepted_by": "the operator, 2026-10-03", "removal": "the shim is deleted in Phase 3"}


def entry(ident: str = "DEBT-001", **given: str | None) -> str:
    """A well-formed obligation by default; a field given as None is left out, as text replaces the default."""
    base = MITIGATION if given.get("kind") == "mitigation" else DEFAULT_ENTRY
    fields = base | given
    lines = [f"### {ident} - an entry"]
    lines += [f"- {key.replace('_', ' ')}: {value}" for key, value in fields.items() if value is not None]
    return "\n".join(lines) + "\n"


def status(phases: dict[str, str] | None = None, tasks: dict[str, tuple[str, str]] | None = None) -> str:
    phases = phases or {"1": "closed", "2": "open", "3": "pending"}
    tasks = tasks or {"2a": ("2", "closed"), "2e1": ("2", "open"), "2e2": ("2", "pending")}
    return json.dumps({"phases": phases, "tasks": {k: {"phase": p, "state": s} for k, (p, s) in tasks.items()}})


class DebtTestCase(unittest.TestCase):
    def run_check(self, register: str | None, status_text: str | None = None, expect: int | None = None):
        files = {}
        if register is not None:
            files[REGISTER] = "# Register\n\n" + register
        files[STATUS] = status() if status_text is None else status_text
        repo = Repo(files)
        self.addCleanup(repo.close)
        done = repo.run(tool=fx.DEBT_TOOL)
        if expect is not None:
            self.assertEqual(done.returncode, expect, msg=f"{done.stdout}\n{done.stderr}")
        return done


class PhaseCloseTest(DebtTestCase):
    def test_an_open_entry_owned_by_an_open_or_pending_task_or_phase_passes(self) -> None:
        text = entry("DEBT-001", owner="task 2e1") + entry("DEBT-002", owner="task 2e2") + entry("DEBT-003", owner="phase 3") + entry("DEBT-004", owner="phase 2")
        done = self.run_check(text, expect=0)
        self.assertIn("debt register: 4 entries, 4 open: phase 2 1, phase 3 1, task 2e1 1, task 2e2 1", done.stdout)
        self.assertIn("no closed phase or task owns an open entry", done.stdout)

    def test_an_open_entry_owned_by_a_closed_task_fails_naming_it(self) -> None:
        done = self.run_check(entry("DEBT-001", owner="task 2a"), expect=1)
        self.assertIn("DEBT OWNED BY A CLOSED PHASE OR TASK IS STILL OPEN: DEBT-001 (task 2a is closed): the 2e1 review verifies it", done.stderr)

    def test_an_open_entry_owned_by_a_closed_phase_fails(self) -> None:
        done = self.run_check(entry("DEBT-007", owner="phase 1"), expect=1)
        self.assertIn("DEBT OWNED BY A CLOSED PHASE OR TASK IS STILL OPEN: DEBT-007 (phase 1 is closed)", done.stderr)

    def test_a_task_of_a_closed_phase_is_closed_with_it_and_the_status_itself_is_inconsistent(self) -> None:
        text = entry("DEBT-001", owner="task 2e1")
        done = self.run_check(text, status({"2": "closed"}, {"2e1": ("2", "open")}), expect=1)
        self.assertIn("DEBT OWNED BY A CLOSED PHASE OR TASK IS STILL OPEN: DEBT-001 (task 2e1 is closed)", done.stderr)
        self.assertIn("phase 2 is closed but task 2e1 is open", done.stderr)

    def test_closing_the_owner_without_closing_the_entry_is_what_fails(self) -> None:
        text = entry("DEBT-001", owner="task 2e1")
        self.run_check(text, status({"2": "open"}, {"2e1": ("2", "open")}), expect=0)
        self.run_check(text, status({"2": "open"}, {"2e1": ("2", "closed")}), expect=1)

    def test_a_closed_entry_under_a_closed_owner_passes_with_its_evidence(self) -> None:
        text = entry("DEBT-001", owner="task 2a", status="closed", closed_by="the 2a review of 2026-09-30, no other construction site")
        self.run_check(text, expect=0)

    def test_a_closed_entry_needs_its_evidence(self) -> None:
        for given in ({}, {"closed_by": "TODO"}, {"closed_by": "n/a"}):
            with self.subTest(given=given):
                done = self.run_check(entry("DEBT-001", owner="task 2a", status="closed", **given), expect=1)
                self.assertIn("DEBT-001: a closed entry needs `closed by`", done.stderr)

    def test_an_empty_register_passes(self) -> None:
        done = self.run_check("None.\n", expect=0)
        self.assertIn("debt register: 0 entries, 0 open", done.stdout)


class EntryTest(DebtTestCase):
    def test_each_required_field_is_required(self) -> None:
        for field in ("kind", "status", "owner", "what", "removal", "source"):
            with self.subTest(field=field):
                done = self.run_check(entry(**{field: None}), expect=1)
                self.assertIn(f"DEBT-001: field {field} is missing or a placeholder", done.stderr)

    def test_a_mitigation_needs_who_found_it_and_the_operators_dated_acceptance(self) -> None:
        self.run_check(entry(kind="mitigation"), expect=0)
        for field in ("found_by", "accepted_by"):
            with self.subTest(field=field):
                done = self.run_check(entry(kind="mitigation", **{field: None}), expect=1)
                self.assertIn(f"DEBT-001: field {field.replace('_', ' ')} is missing or a placeholder", done.stderr)
        # a mitigation has no `source`; an obligation has no `found by` or `accepted by`
        self.run_check(entry(kind="mitigation", source=None), expect=0)

    def test_only_the_operator_accepts_a_mitigation_and_the_acceptance_is_dated(self) -> None:
        for accepted in ("Astra accepted it, 2026-10-03", "the operator accepted it", "the orchestrator, 2026-10-03"):
            with self.subTest(accepted=accepted):
                done = self.run_check(entry(kind="mitigation", accepted_by=accepted), expect=1)
                self.assertIn("accepted by must be the operator's acceptance, with its date", done.stderr)

    def test_a_mitigation_cites_the_review_that_found_it(self) -> None:
        done = self.run_check(entry(kind="mitigation", found_by="the coder noticed"), expect=1)
        self.assertIn("found by must cite the review", done.stderr)

    def test_an_obligation_cites_its_ruling_or_review(self) -> None:
        done = self.run_check(entry(source="somebody said so"), expect=1)
        self.assertIn("source must cite the ruling or review that carries it", done.stderr)
        for source in ("operator ruling 2026-10-02", "Gate D #2 finding F6", "gen2-gate-d-2-astra-review.md"):
            with self.subTest(source=source):
                self.run_check(entry(source=source), expect=0)

    def test_a_placeholder_is_not_content(self) -> None:
        for text in ("TODO", "tbd", "n/a", "-", "none"):
            with self.subTest(text=text):
                done = self.run_check(entry(what=text), expect=1)
                self.assertIn("field what is missing or a placeholder", done.stderr)

    def test_an_owner_that_the_status_file_does_not_name_fails(self) -> None:
        for owner in ("task 9z", "phase 9", "2e1", "team 2e1", "task"):
            with self.subTest(owner=owner):
                done = self.run_check(entry(owner=owner), expect=1)
                self.assertIn("is not a `task <id>` or `phase <id>` that phase-status.json names", done.stderr)

    def test_unknown_kind_status_and_field_fail(self) -> None:
        self.assertIn("kind 'wish' is not one of mitigation, obligation", self.run_check(entry(kind="wish"), expect=1).stderr)
        self.assertIn("status 'later' is not open or closed", self.run_check(entry(status="later"), expect=1).stderr)
        self.assertIn("unknown field 'severity'", self.run_check(entry() + "- severity: high\n", expect=1).stderr)

    def test_a_repeated_field_or_entry_fails(self) -> None:
        self.assertIn("field removal given twice", self.run_check(entry() + "- removal: again\n", expect=1).stderr)
        self.assertIn("DEBT-001: appears twice", self.run_check(entry("DEBT-001") + entry("DEBT-001"), expect=1).stderr)

    def test_an_example_inside_a_fenced_block_is_not_an_entry(self) -> None:
        text = "```\n" + entry("DEBT-009", owner="task 2a") + "```\n" + entry("DEBT-001")
        done = self.run_check(text, expect=0)
        self.assertIn("1 entries, 1 open", done.stdout)

    def test_a_wrapped_value_continues_on_indented_lines(self) -> None:
        done = self.run_check(entry(removal="the 2e1 review verifies") + "  that no other construction site exists\n", expect=0)
        self.assertIn("1 entries", done.stdout)

    def test_only_debt_sections_are_entries(self) -> None:
        text = "### Notes\n- kind: obligation\n\n" + entry("DEBT-001")
        done = self.run_check(text, expect=0)
        self.assertIn("1 entries", done.stdout)


class StatusFileTest(DebtTestCase):
    def test_a_phase_may_not_be_closed_with_a_task_that_is_not(self) -> None:
        done = self.run_check(entry(owner="phase 3"), status({"2": "closed", "3": "pending"}, {"2e1": ("2", "pending")}), expect=1)
        self.assertIn("phase 2 is closed but task 2e1 is pending", done.stderr)

    def test_a_state_must_be_one_of_the_three(self) -> None:
        self.assertIn("phase 3: state 'done' is not one of pending, open, closed",
                      self.run_check(entry(owner="phase 3"), status({"3": "done"}, {}), expect=1).stderr)
        self.assertIn("task 2e1: state 'done' is not one of pending, open, closed",
                      self.run_check(entry(), status({"2": "open"}, {"2e1": ("2", "done")}), expect=1).stderr)

    def test_a_task_must_name_a_known_phase(self) -> None:
        done = self.run_check(entry(owner="phase 2"), status({"2": "open"}, {"2e1": ("7", "open")}), expect=1)
        self.assertIn("task 2e1: names a phase that phase-status.json does not", done.stderr)


class ToolFailureTest(DebtTestCase):
    def test_a_missing_register_or_status_file_is_a_tool_failure(self) -> None:
        self.assertIn("no debt register", self.run_check(None, expect=2).stderr)
        repo = Repo({REGISTER: "# Register\n"})
        self.addCleanup(repo.close)
        done = repo.run(tool=fx.DEBT_TOOL)
        self.assertEqual(done.returncode, 2)
        self.assertIn("no phase status", done.stderr)

    def test_an_unreadable_or_misshapen_status_file_is_a_tool_failure(self) -> None:
        self.assertIn("cannot be read", self.run_check(entry(), "{not json", expect=2).stderr)
        self.assertIn("must hold the objects `phases` and `tasks`", self.run_check(entry(), json.dumps({"phases": {}}), expect=2).stderr)


class RealRegisterTest(unittest.TestCase):
    """The register in this repository carries each ruling task 2q-a was told to keep, with its owner."""

    def sections(self) -> dict[str, dict[str, str]]:
        text = (fx.REPO / REGISTER).read_text(encoding="utf-8")
        found = {}
        for block in re.split(r"^### (?=DEBT-)", text, flags=re.MULTILINE)[1:]:
            ident = block.split(" ", 1)[0]
            found[ident] = dict(re.findall(r"^- ([a-z ]+): (.*)$", block, flags=re.MULTILINE)) | {"title": block.splitlines()[0]}
        return found

    def test_the_named_obligations_are_owned_as_the_rulings_assign_them(self) -> None:
        entries = self.sections()
        wanted = [("construction site", "task 2e1", "2026-10-02"),          # the 2e1 gateway-client construction rule
                  ("one client instance per station or job", "task 2e1", "2026-10-03"),   # the client-model ruling
                  ("retrieval-audit evidence", "task 2e2", "Gate D #2"),    # Gate D #2 F6
                  ("stores written before", "phase 4", "13b"),               # the Phase 4 release items
                  ("real-data migration", "phase 4", "2026-09-30"),
                  ("stopping and fencing", "phase 4", "2026-09-30"),
                  ("non-lead restrictions", "phase 4", "2026-09-30"),
                  ("privilege separation", "phase 4", "2b-repair-5"),
                  ("canary", "phase 4", "2b-repair-6"),
                  ("revision lifetime", "phase 3", "2b-repair-3"),           # the Phase 3 item Gate D #1 finding 6 asked to carry
                  ("rejected-credential", "task 2e1", "2026-09-29"),         # the operator's §4(d) decision, which AUTH-DEMO's residual becomes
                  ("adapter compatibility", "phase 3", "2026-10-01"),         # BUILD-STATE's "Phase 3 items"
                  ("catalogue partial-result", "phase 3", "2026-10-01")]
        for words, owner, source in wanted:
            with self.subTest(words=words):
                matching = [e for e in entries.values() if words in e["title"].lower()]
                self.assertEqual(len(matching), 1, msg=f"one entry about {words!r}")
                self.assertEqual((matching[0]["kind"], matching[0]["status"], matching[0]["owner"]), ("obligation", "open", owner))
                self.assertIn(source, matching[0]["source"])


if __name__ == "__main__":
    unittest.main()
