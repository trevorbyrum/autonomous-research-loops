"""Hand-calculated E-1…E-5/E-8 fixtures; counts establish no semantic meaning.
Router fixture reads real durable rows, with no providers; properties use the
existing child helper so Hypothesis stays a dev-only dependency outside gen2 imports.
"""
import json
import unittest
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path

from gen2 import accounting as a
from gen2.core import canonical
from gen2.tests import children
from gen2.tests.router_fixtures import TOPIC, empty_outcome, find_request
from gen2.tests.router_fixtures import Workflow


def complete() -> a.Inventory:
    return a.Inventory("native", (a.Observation("o", "p", "lane", "query", "find", "complete", "exhausted", 1,
                       a.SearchPage(a.search_identity({"query": "query"}), 1, None, None)),),
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

    def test_transitive_delegate_capture(self):
        inv = complete()
        child = replace(inv.observations[0], observation_id="child", invocation_id="d",
                        page=replace(inv.observations[0].page, search=a.search_identity({"query": "child query"})))
        grandchild = replace(child, observation_id="grandchild", invocation_id="g", completeness="partial")
        nested = replace(inv, passes=inv.passes + (a.Pass("d", "delegate", "committed", "p"), a.Pass("g", "delegate", "committed", "d")),
                         observations=inv.observations + (child, grandchild),
                         retrievals=inv.retrievals + (a.Retrieval("r2", "child"), a.Retrieval("r3", "grandchild")))
        self.assertEqual(a.saturation_passes(nested), ())

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


class WindowTest(Workflow):
    """E-4 through Router capture/lifecycle APIs; every expected ID is literal.

    Fixtures trust station-reported exhaustion, as admission already does; they
    test relationships between durable captures, not providers' truthfulness.
    """
    def setUp(self):
        super().setUp()
        self.to_queued()

    def page(self, grant, oid, request=None, *, end="exhausted", partial=False, failed=False, next_cursor=None):
        request = request or find_request("same search")
        observation = {"observation_id": oid, "request": request, "request_identity": canonical.logical_hash(request),
                       "attempt": 1, "lane": request["lane"], "obligation_ids": ["O-1"],
                       "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:01Z",
                       "coverage_state": "searched_ok" if request["request"]["request_type"] == "find" else "metadata_only",
                       "result_count": 1, "completeness": "partial" if partial else "complete",
                       "error_class": "partial_pagination" if partial else None, "capability_fact_id": None,
                       "policy_version": "pol-1", "cost_units": None, "gateway_call_ref": "fixture-call",
                       "page_outcome": end, "continuation": {"cursor": next_cursor} if next_cursor is not None else None}
        if failed:
            observation.update(coverage_state="provider_unavailable", completeness="unobserved", result_count=None,
                               page_outcome="failed", error_class="provider_outage", gateway_call_ref=None)
        response = self.router.record_observation({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"],
                                                  "observation": observation, "retrieval_events": [{"event_id": "rev_" + oid[4:],
                                                  "provider_record_id": "fixture-record", "rank": 1, "captured_at": "2026-09-27T10:00:01Z"}] if not failed else []})
        self.assertEqual(response["status"], "recorded", response)
        return observation["request_identity"]

    def committed(self, grant):
        response = self.finish(grant, "op_" + grant["invocation_id"][4:])
        self.assertEqual(response["status"], "committed", response)

    def eligible(self):
        return self.router.candidate_units(TOPIC, history="native").saturation_passes

    def test_equivalent_requests_and_different_search(self):
        first = self.started("inv_equiv00001")
        original = self.page(first, "obs_equiv00001", find_request("query", lanes=["crossref", "openalex"]))
        self.page(first, "obs_equiv00002", {**find_request("query", lanes=["crossref", "openalex"]), "lane": "openalex"})
        self.committed(first)
        second = self.started("inv_equiv00002")
        explicit = find_request("query", lanes=["openalex", "crossref"], limit=20, commercial=False,
                                accept_per_item=False, domain="other", kind=None, year_from=None, published_after=None)
        changed = self.page(second, "obs_equiv00003", explicit)
        self.page(second, "obs_equiv00004", {**explicit, "lane": "openalex"})
        self.committed(second)
        self.assertNotEqual(original, changed)  # Capture identity remains exact.
        self.assertEqual(self.eligible(), ("inv_equiv00001",))
        third = self.started("inv_equiv00003")
        self.page(third, "obs_equiv00005", find_request("different query"))
        self.committed(third)
        self.assertEqual(self.eligible(), ("inv_equiv00001", "inv_equiv00003"))

    def test_distinct_search_control(self):
        for n, query in enumerate(("first query", "different query"), 1):
            grant = self.started(f"inv_distinct{n:03d}")
            self.page(grant, f"obs_distinct{n:03d}", find_request(query))
            self.committed(grant)
        self.assertEqual(self.eligible(), ("inv_distinct001", "inv_distinct002"))

    def test_page_size_changes_no_population(self):
        for n, limit in enumerate((20, 5), 1):
            grant = self.started(f"inv_pagesize{n:03d}")
            self.page(grant, f"obs_pagesize{n:03d}", find_request("same query", limit=limit))
            self.committed(grant)
        self.assertEqual(self.eligible(), ("inv_pagesize001",))

    def test_filter_and_population_differences(self):
        for n, request in enumerate((find_request("query"), find_request("query", year_from=2020),
                                     {**find_request("query"), "lane": "openalex"}), 1):
            grant = self.started(f"inv_population{n:02d}")
            self.page(grant, f"obs_population{n:02d}", request)
            self.committed(grant)
        self.assertEqual(self.eligible(), ("inv_population01", "inv_population02", "inv_population03"))

    def test_gateway_canonical_form(self):
        samples = [{"request_type": "find"}, {"request_type": "find", "domain": "unlisted", "limit": 20},
                   {"request_type": "find", "query": "q", "lanes": ["openalex", "crossref"], "kind": "paper",
                    "domain": "biomed", "commercial": True, "accept_per_item": True, "year_from": 2020,
                    "published_after": "2026-01-01", "limit": 7, "cursors": {"crossref": "tail"}}]
        gateway = Path(__file__).resolve().parents[2] / "gateway/research_gateway/core/request_identity.py"
        # Run the gateway's pure form in its own process; no engine import grant.
        result = children.python(["-c", "import json, runpy, sys; effective = runpy.run_path(sys.argv[1])['effective_request']; "
                                  "print(json.dumps([effective(p) for p in json.loads(sys.argv[2])]))", str(gateway), json.dumps(samples)],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for request, expected in zip(samples, json.loads(result.stdout), strict=True):
            del expected["cursors"]
            del expected["limit"]
            del expected["request_type"]
            expected["lanes"] = tuple(expected["lanes"]) if expected["lanes"] else None
            self.assertEqual(asdict(a.search_identity(request)), expected)

    def test_partial_failed_and_missing_delegates(self):
        for n, problem in enumerate(("partial", "failed", "missing"), 1):
            parent = self.started(f"inv_parentbad{n:02d}")
            child = self.started(f"inv_childbad{n:02d}", kind="delegate", parent=parent)
            self.page(parent, f"obs_parentbad{n:02d}", find_request(f"parent {n}"))
            if problem != "missing":
                self.page(child, f"obs_childbad{n:02d}", partial=problem == "partial", end="end_unknown" if problem == "partial" else "exhausted")
            if problem == "failed":
                response = self.router.record_transition({"capability_id": child["capability_id"], "invocation_id": child["invocation_id"],
                                                         "to_state": "failed", "failure_class": "exit_nonzero", "end_evidence_ref": self.evidence(child)})
                self.assertEqual(response["status"], "recorded", response)
            else:
                self.committed(child)
            self.committed(parent)
            self.assertEqual(self.eligible(), ())

    def test_complete_delegated_search(self):
        parent = self.started("inv_parentgood1")
        self.page(parent, "obs_parentgood1", find_request("parent"))
        child = self.started("inv_childgood01", kind="delegate", parent=parent)
        sibling = self.started("inv_othergood01", kind="delegate", parent=parent)
        self.page(child, "obs_childgood01", find_request("child"))
        self.page(sibling, "obs_othergood01", find_request("sibling"))
        self.committed(sibling)
        self.committed(child)
        self.committed(parent)
        self.assertEqual(self.eligible(), ("inv_parentgood1",))

    def test_parent_can_coordinate_delegated_search(self):
        parent = self.started("inv_coordinate1")
        child = self.started("inv_coordinate2", kind="delegate", parent=parent)
        self.page(child, "obs_coordinate2")
        self.committed(child)
        self.committed(parent)
        self.assertEqual(self.eligible(), ("inv_coordinate1",))

    def test_unrelated_failure_does_not_poison_window(self):
        parent = self.started("inv_oldparent01")
        self.page(parent, "obs_oldparent01")
        failed = self.started("inv_unrelated01", kind="delegate", parent=parent)
        response = self.router.record_transition({"capability_id": failed["capability_id"], "invocation_id": failed["invocation_id"],
                                                 "to_state": "failed", "failure_class": "exit_nonzero", "end_evidence_ref": self.evidence(failed)})
        self.assertEqual(response["status"], "recorded", response)
        self.committed(parent)
        good = self.started("inv_unrelated02")
        self.page(good, "obs_unrelated02")
        self.committed(good)
        self.assertEqual(self.eligible(), ("inv_unrelated02",))

    def test_missing_and_partial_prefix(self):
        tail = self.started("inv_tailonly001")
        self.page(tail, "obs_tailonly001", find_request("query", cursors={"crossref": "tail"}))
        self.committed(tail)
        self.assertEqual(self.eligible(), ())
        prefix = self.started("inv_prefix00001")
        self.page(prefix, "obs_prefix00001", find_request("query"), partial=True, end="continuation", next_cursor="tail")
        self.committed(prefix)
        resumed = self.started("inv_resumed0001")
        self.page(resumed, "obs_resumed0001", {**find_request("query", cursors={"crossref": "tail"}), "page": 2})
        self.committed(resumed)
        self.assertEqual(self.eligible(), ())

    def test_complete_linked_pages(self):
        grant = self.started("inv_linked00001")
        self.page(grant, "obs_linked00001", end="continuation", next_cursor=0)
        self.page(grant, "obs_linked00002", {**find_request("same search", cursors={"crossref": 0}, lanes=["crossref"], limit=5), "page": 2})
        self.committed(grant)
        self.assertEqual(self.eligible(), ("inv_linked00001",))

    def test_broken_chains(self):
        for n, (page, cursor, end) in enumerate(((2, "wrong", "continuation"), (3, "next", "continuation"), (2, "next", "limit_reached")), 1):
            grant = self.started(f"inv_broken{n:05d}")
            self.page(grant, f"obs_broken{n:05d}a", find_request(f"query {n}"), end=end, next_cursor="next")
            self.page(grant, f"obs_broken{n:05d}b", {**find_request(f"query {n}", cursors={"crossref": cursor}), "page": page})
            self.committed(grant)
            self.assertEqual(self.eligible(), ())

    def test_nonpaging_success_preserves_window(self):
        grant = self.started("inv_nonpaging01")
        self.page(grant, "obs_nonpaging01")
        for n, kind in enumerate(("resolve", "enrich", "fetch", "data"), 2):
            self.page(grant, f"obs_nonpaging{n:02d}", {"lane": "crossref", "page": 1, "request": {"request_type": kind}}, end="end_unknown")
        self.committed(grant)
        self.assertEqual(self.eligible(), ("inv_nonpaging01",))

    def test_nonpaging_partial_and_failed_remain_visible(self):
        for n, failed in enumerate((False, True), 6):
            grant = self.started(f"inv_nonpaging{n:02d}")
            self.page(grant, f"obs_nonpaging{n:02d}a")
            self.page(grant, f"obs_nonpaging{n:02d}b", {"lane": "crossref", "page": 1, "request": {"request_type": "resolve"}},
                      end="end_unknown", partial=not failed, failed=failed)
            self.committed(grant)
            self.assertEqual(self.eligible(), ())
            self.assertIsNone(self.router.candidate_units(TOPIC, history="native").retrieved_records.value)

    def test_nonpaging_alone_adds_no_window(self):
        grant = self.started("inv_nonpaging08")
        self.page(grant, "obs_nonpaging08", {"lane": "crossref", "page": 1, "request": {"request_type": "resolve"}}, end="end_unknown")
        self.committed(grant)
        self.assertEqual(self.eligible(), ())
