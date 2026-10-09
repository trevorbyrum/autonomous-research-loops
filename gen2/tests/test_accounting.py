"""Hand-calculated E-1…E-5/E-8 fixtures; counts establish no semantic meaning.
Router fixture reads real durable rows, with no providers; properties use the
existing child helper so Hypothesis stays a dev-only dependency outside gen2 imports.
"""
import unittest
from dataclasses import replace
from fractions import Fraction

from gen2 import accounting as a
from gen2.tests import children
from gen2.tests.router_fixtures import TOPIC, empty_outcome
from gen2.tests.test_router_workflow import Workflow


def complete() -> a.Inventory:
    return a.Inventory("native", (a.Observation("o", "p", "lane", "query", "find", "complete", "exhausted", 1),),
                       (a.Retrieval("r", "o"),), (a.WorkLink("r", "w"),), (a.Assessment("w"),),
                       (a.Claim("c", 1, "accepted_support"),), (a.Pass("p", "research_pass", "committed"),))


def values(units: a.CandidateUnits) -> tuple:
    return tuple(c.value for c in (units.retrieved_records, units.deduplicated_works, units.assessed_candidates, units.accepted_claims))


class AccountingTest(unittest.TestCase):
    def test_zero_denominator(self):
        units = a.candidate_units(a.Inventory("native"))
        self.assertEqual(values(units), (0, 0, 0, 0))
        self.assertIsNone(a.novelty(units.assessed_candidates, ()))

    def test_control_complete(self):
        units = a.candidate_units(complete())
        self.assertEqual(values(units), (1, 1, 1, 1))
        self.assertEqual(units.saturation_passes, ("p",))
        self.assertEqual(a.novelty(units.assessed_candidates, (a.NoveltyJudgment("w", True),)), Fraction(1))

    def test_repeated_study_overlapping_lanes(self):
        # Two lanes each return A and B: four records, two works, not four
        # independent studies. A's two screening stages still assess one candidate.
        inv = a.Inventory("native",
                          (a.Observation("o1", "p", "lane1", "q1", "find", "complete", "exhausted", 2),
                           a.Observation("o2", "p", "lane2", "q2", "find", "complete", "exhausted", 2)),
                          tuple(a.Retrieval(r, o) for r, o in (("r1", "o1"), ("r2", "o1"), ("r3", "o2"), ("r4", "o2"))),
                          tuple(a.WorkLink(r, w) for r, w in (("r1", "A"), ("r2", "B"), ("r3", "A"), ("r4", "B"))),
                          (a.Assessment("A"), a.Assessment("A"), a.Assessment("B")),
                          (a.Claim("c1", 1, "accepted_support"), a.Claim("c1", 2, "accepted_support"),
                           a.Claim("c2", 1, "accepted_support"), a.Claim("c2", 2, "contested")),
                          (a.Pass("p", "research_pass", "committed"),))
        units = a.candidate_units(inv)
        self.assertEqual(values(units), (4, 2, 2, 1))
        self.assertEqual(a.novelty(units.assessed_candidates, (a.NoveltyJudgment("A", False), a.NoveltyJudgment("B", True))), Fraction(1, 2))

    def test_partial_pass(self):
        inv = complete()
        inv = replace(inv, observations=(replace(inv.observations[0], completeness="partial", page_outcome="end_unknown"),))
        units = a.candidate_units(inv)
        self.assertEqual(values(units), (None, None, 1, 1))
        self.assertEqual(units.retrieved_records.known_ids, frozenset({"r"}))
        self.assertEqual(units.saturation_passes, ())

    def test_failed_missing_and_capped_passes(self):
        inv = complete()
        self.assertEqual(a.saturation_passes(replace(inv, passes=(a.Pass("p", "research_pass", "failed"),))), ())
        for end in ("continuation", "limit_reached", "end_unknown", "failed"):
            self.assertEqual(a.saturation_passes(replace(inv, observations=(replace(inv.observations[0], page_outcome=end),))), ())
        self.assertIsNone(a.candidate_units(replace(inv, observations=(), retrievals=(), links=())).retrieved_records.value)
        self.assertEqual(a.saturation_passes(replace(inv, observations=())), ())

    def test_repeating_search_earns_no_window(self):
        inv = complete()
        inv = replace(inv, passes=inv.passes + (a.Pass("p2", "research_pass", "committed"),),
                      observations=inv.observations + (replace(inv.observations[0], observation_id="o2", invocation_id="p2"),),
                      retrievals=inv.retrievals + (a.Retrieval("r2", "o2"),), links=inv.links + (a.WorkLink("r2", "w"),))
        self.assertEqual(a.candidate_units(inv).saturation_passes, ("p",))

    def test_unlinked_and_capture_mismatch(self):
        inv = complete()
        self.assertEqual(values(a.candidate_units(replace(inv, links=()))), (1, None, 1, 1))
        self.assertIsNone(a.candidate_units(replace(inv, retrievals=())).retrieved_records.value)

    def test_deferred_remains_unassessed(self):
        units = a.candidate_units(replace(complete(), assessments=()))
        self.assertEqual(values(units), (1, 1, 0, 1))
        self.assertIsNone(a.novelty(units.assessed_candidates, ()))

    def test_legacy_history(self):
        for inv in (a.Inventory("legacy_unknown"), replace(complete(), history="legacy_unknown")):
            self.assertEqual(values(a.candidate_units(inv)), (None, None, None, None))
            self.assertEqual(a.saturation_passes(inv), ())

    def test_unknown_judgment(self):
        assessed = a.candidate_units(complete()).assessed_candidates
        for labels in ((), (a.NoveltyJudgment("w", None),), (a.NoveltyJudgment("other", True),),
                       (a.NoveltyJudgment("w", True), a.NoveltyJudgment("w", False))):
            self.assertIsNone(a.novelty(assessed, labels))
        self.assertIsNone(a.novelty(a.Count(frozenset({"w"}), "missing history"), (a.NoveltyJudgment("w", True),)))

    def test_properties(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROPERTIES = '''
from dataclasses import replace
from hypothesis import given, settings, strategies as st
from gen2 import accounting as a
from gen2.tests.test_accounting import complete
@settings(max_examples=80, derandomize=True, database=None)
@given(st.lists(st.integers(0, 20), min_size=1, max_size=30))
def identities(numbers):
    base = replace(complete(), retrievals=tuple(a.Retrieval(str(i), "o") for i in range(len(numbers))),
                   links=tuple(a.WorkLink(str(i), str(n)) for i, n in enumerate(numbers)),
                   observations=(replace(complete().observations[0], result_count=len(numbers)),))
    duplicate = replace(base, retrievals=base.retrievals + (a.Retrieval("extra", "o2"),),
                        links=base.links + (a.WorkLink("extra", str(numbers[0])),),
                        observations=base.observations + (replace(base.observations[0], observation_id="o2", lane="overlap", result_count=1),))
    assert a.candidate_units(duplicate).deduplicated_works == a.candidate_units(base).deduplicated_works
    assert a.candidate_units(replace(base, links=base.links[::-1])).deduplicated_works == a.candidate_units(base).deduplicated_works
@settings(max_examples=80, derandomize=True, database=None)
@given(st.sets(st.text(min_size=1), max_size=20))
def unknown(ids):
    count = a.Count(frozenset(ids), "unknown capture")
    assert count.value is None
    assert a.novelty(count, tuple(a.NoveltyJudgment(i, False) for i in ids)) is None
identities()
unknown()
'''


class DurableAccountingTest(Workflow):
    def test_reads_committed_inventories_without_writes_or_clock(self):
        self.to_queued()
        grant = self.started("inv_research01")
        events = self.observe(grant, "obs_search0001", ("A", "A-copy", "B"))
        self.assertEqual(self.register(grant, [("doi", "10.1/A", events[:2]), ("doi", "10.1/B", events[2:])])["status"], "recorded")
        self.x("UPDATE works SET study_group_id = 'shared-origin'")  # lineage never merges distinct identities.
        work = self.rows("SELECT work_id FROM works ORDER BY identity_value")[0][0]
        text = self.artifact(b"claim")
        outcome = {**empty_outcome("inv_research01"), "claims": [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text,
                    "load_bearing": False, "required_access_tier": None}], "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}],
                   "screening_assessments": [{"assessment_id": "asm_account001", "work_id": work,
                    "stage": "abstract", "decision": "include", "reason_code": None,
                    "criterion_results": {"C-1": "met"}, "actor_kind": "primary", "decision_receipt_id": None,
                    "supersedes_assessment_id": None}]}
        response = self.finish(grant, "op_account0001", outcome, refs=[text])
        self.assertEqual(response["status"], "committed", response)
        before = self.state(exclude=())
        def no_clock():
            self.fail("accounting read the clock")
        self.router._clock = no_clock
        self.assertEqual(values(self.router.candidate_units(TOPIC, history="native")), (3, 2, 1, 1))
        self.assertEqual(values(self.router.candidate_units("fleet-a:t2", history="native")), (0, 0, 0, 0))
        self.assertEqual(values(self.router.candidate_units(TOPIC, history="legacy_unknown")), (None, None, None, None))
        self.assertEqual(self.state(exclude=()), before)
