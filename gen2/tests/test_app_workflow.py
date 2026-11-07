"""The driver's program (T17 PR1). Oracle: the tables below, one row per queue status and per walk position; the config-bundle
schema for the executors entries (SchemaSet). Limits: pure; the walker, order issue and station wiring are PR 2's.
"""
import unittest

from gen2.app import workflow as w
from gen2.core import canonical
from gen2.exec.common import Refused
from gen2.router.schemas import SchemaSet

S = w.Step
C = w.Job("committed")
PROPOSING = w.Job("committed", proposals=True)
SCOPE1, SCOPE2 = S("research_pass", "scope", 1), S("research_pass", "scope", 2)
DISC1, DISC2 = S("discovery", "search", 1), S("discovery", "search", 2)
RES1, RES2 = S("research_pass", "research", 1), S("research_pass", "research", 2)
VER, CH1, CH2 = S("verification", "verify", 1), S("checkpoint", "challenge", 1), S("checkpoint", "challenge", 2)
DOS, REV = S("checkpoint", "dossier", 1), S("checkpoint", "review", 1)


def at(status, jobs=None, reviews=(), **budgets):
    return w.plan(status, jobs or {}, reviews=reviews, **budgets)


class PlanTest(unittest.TestCase):
    def test_each_queue_status_maps_to_exactly_one_kind_of_action(self):
        for status, expected in (("awaiting_brief_confirmation", w.Wait), ("awaiting_scope_approval", w.Wait), ("awaiting_contract_approval", w.Wait),
                                 ("scoping", w.Issue), ("queued", w.Issue), ("resting", w.Issue), ("active", w.Issue),
                                 ("completed_with_qualified_conclusions", w.Done), ("held", w.Stop), ("capability_blocked", w.Stop),
                                 ("stopped_for_resources", w.Stop), ("awaiting_judgment", w.Stop), ("retired", w.Stop)):
            with self.subTest(status):
                self.assertIsInstance(at(status), expected)

    def test_operator_waits_name_the_command_that_unblocks_them(self):
        got = {s: at(s) for s in ("awaiting_brief_confirmation", "awaiting_scope_approval", "awaiting_contract_approval")}
        self.assertEqual([a.command for a in got.values()], ["apply_operator_decision kind=brief_confirmation", "apply_operator_decision kind=scope_approval",
                                                             "apply_operator_decision kind=contract_approval"])

    def test_scoping_alternates_scope_passes_and_discovery_then_spends_its_budget(self):
        for case, jobs, expected in (
                ("first pass", {}, w.Issue(SCOPE1)),
                ("proposals run discovery before the next pass", {SCOPE1: PROPOSING}, w.Issue(DISC1)),
                ("then the next pass", {SCOPE1: PROPOSING, DISC1: C}, w.Issue(SCOPE2)),
                ("a live pass is advanced, not reissued", {SCOPE1: w.Job("live")}, w.Advance(SCOPE1)),
                ("a report sent back to scoping goes on to a new pass", {SCOPE1: C}, w.Issue(SCOPE2)),
                ("failed stops", {SCOPE1: w.Job("failed")}, w.Stop("research_pass/scope #1 is failed")),
                ("unknown stops", {SCOPE1: w.Job("unknown")}, w.Stop("research_pass/scope #1 is unknown")),
                ("held stops", {SCOPE1: w.Job("held")}, w.Stop("research_pass/scope #1 is held"))):
            with self.subTest(case):
                self.assertEqual(at("scoping", jobs, max_rounds=3), expected)
        self.assertEqual(at("scoping", {SCOPE1: C, SCOPE2: C}, max_rounds=2), w.Stop("scoping spent its 2 rounds"))

    def test_the_contract_walk_in_order(self):
        steps = [({}, w.Issue(RES1)), ({RES1: PROPOSING}, w.Issue(DISC1)), ({RES1: PROPOSING, DISC1: C}, w.Issue(RES2)),
                 ({RES1: C, RES2: C}, w.Issue(VER)), ({RES1: C, RES2: C, VER: C}, w.Wait("no review is open for the checkpoint", "open_review"))]
        for jobs, expected in steps:
            with self.subTest(sorted(s.purpose for s in jobs)):
                self.assertEqual(at("resting", jobs, max_passes=2), expected)
        base = {RES1: C, VER: C}
        for case, jobs, reviews, expected in (
                ("review open: challenge pass 1", base, ["rev_aaaaaaaa"], w.Issue(CH1)),
                ("pass 1 proposed: discovery", {**base, CH1: PROPOSING}, [], w.Issue(DISC1)),
                ("then pass 2 (the episode is not needed to continue)", {**base, CH1: PROPOSING, DISC1: C}, [], w.Issue(CH2)),
                ("no proposals: pass 1 was the challenge", {**base, CH1: C}, [], w.Issue(DOS)),
                ("after pass 2: dossier", {**base, CH1: PROPOSING, DISC1: C, CH2: C}, [], w.Issue(DOS)),
                ("after the dossier: review", {**base, CH1: C, DOS: C}, [], w.Issue(REV))):
            with self.subTest(case):
                self.assertEqual(at("resting", jobs, reviews=reviews), expected)
        self.assertEqual(at("resting", {**base, CH1: C, DOS: C, REV: C}),
                         w.Wait("the dossier and its review await the operator's approval", "apply_operator_decision kind=completion_approval"))

    def test_a_failed_or_unknown_step_anywhere_stops_the_walk(self):
        for state in ("failed", "unknown", "held"):
            with self.subTest(state):
                self.assertIsInstance(at("resting", {RES1: C, VER: C, CH1: C, DOS: w.Job(state)}), w.Stop)

    def test_the_plan_is_a_function_of_its_facts(self):
        jobs = {RES1: PROPOSING}
        self.assertEqual(at("queued", jobs), at("queued", dict(jobs)))


class WaitingLineTest(unittest.TestCase):
    SHOWN = {"dossier": {"revision": 3, "content_hash": "sha256:" + "d" * 64, "state": "satisfied", "gates": [{"gate": "coverage_integrity", "state": "satisfied"}]},
             "reviews": [{"outcome": "insufficient", "summary": "Claim 2 was never searched.",
                          "evidence": [{"content_hash": "sha256:" + "e" * 64, "text": "the judgment text", "cut": False}, {"content_hash": "sha256:" + "f" * 64, "text": None, "cut": False}]}],
             "approvable": True}

    def test_the_line_names_what_is_awaited_and_the_command(self):
        self.assertEqual(w.waiting_line(w.Wait("the contract awaits approval", "apply_operator_decision kind=contract_approval")),
                         "waiting for: the contract awaits approval; run: apply_operator_decision kind=contract_approval")

    def test_the_approval_line_prints_the_review_and_its_evidence_even_when_insufficient(self):
        text = w.waiting_line(w.Wait("approval", "apply_operator_decision kind=completion_approval"), self.SHOWN)
        for fragment in ("review insufficient: Claim 2 was never searched.", "the judgment text", "NOT RETAINED", "gate coverage_integrity: satisfied"):
            self.assertIn(fragment, text)

    def test_a_revision_with_no_review_says_so(self):
        text = w.shown_text({**self.SHOWN, "reviews": [], "approvable": False})
        self.assertIn("no sufficiency review is bound to this revision", text)


class ExecutorEntriesTest(unittest.TestCase):
    PINS = [{"kind": k, "purpose": p, "prompt": {"version": 1, "content_hash": canonical.bytes_digest(f"{k}.{p}".encode())}} for k, p in w.LIMITS]

    def test_one_valid_entry_per_purpose_of_the_workflow(self):
        entries = w.executor_entries(self.PINS)
        self.assertEqual(len(entries), 7)
        self.assertEqual({(e["kind"], e["purpose"]) for e in entries}, set(w.MODEL) | set(w.CODE_ONLY))
        self.assertEqual(SchemaSet().errors(entries, "config-bundle.schema.json#/properties/policy/properties/executors"), [])
        self.assertTrue(SchemaSet().errors([{**entries[0], "deadline_s": 0}], "config-bundle.schema.json#/properties/policy/properties/executors"))   # the check is not vacuous

    def test_a_purpose_with_no_pin_is_refused(self):
        with self.assertRaises(Refused):
            w.executor_entries(self.PINS[1:])

    def test_the_code_only_purposes_have_mounted_prompt_files(self):
        from pathlib import Path
        from gen2.tests import children
        for kind, purpose in w.CODE_ONLY:
            self.assertTrue(Path(children.path(f"gen2/prompts/{kind}.{purpose}.md")).read_bytes().strip())
