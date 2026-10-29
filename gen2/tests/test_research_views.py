"""Hand-written research-state view oracles; fake snapshots only."""
import unittest
from dataclasses import replace

from gen2 import accounting as a
from gen2.accounting import views as v
from gen2.accounting.stopping import WindowPin
from gen2.tests import children, test_accrual as f
from gen2.tests.router_fixtures import ContractWorld, compatible
from gen2.tests.router_fixtures import OTHER

DATE, LATER = f.DATE, f.LATER
SEARCH = a.SearchIdentity("other", False, False, "probe", None, None, None, None)
OBS = a.Observation("o", "p", "crossref", "exact-request", "find", "complete", "exhausted", 2,
                    a.SearchPage(SEARCH, 1, None, None))
LINEAGE = a.SourceLineage("s1", "shared_study_origin", "study-A", None, None)
BASE = replace(f.inventory(source_lineage=(LINEAGE,)), observations=(OBS,),
    retrievals=(a.Retrieval("r1", "o"), a.Retrieval("r2", "o")), links=(a.WorkLink("r1", "w1"), a.WorkLink("r2", "w1")),
    assessments=(a.Assessment("w1"), a.Assessment("w1")),
    claims=(a.Claim("c1", 1, "accepted_support"), a.Claim("c2", 1, "accepted_support"), a.Claim("c2", 2, "rejected")),
    passes=(a.Pass("p", "research_pass", "committed"),))
PIN = (WindowPin("p", 1),)
LINK = v.BranchLink("B-1", "p")
WINDOW = v.CoverageWindow(a.WindowStanding("p", "eligible", "completed distinct search"), 1, "current",
                         frozenset({("crossref", replace(SEARCH, lanes=("crossref",)))}))
CONFLICT = replace(f.BRANCH, disposition_id="c1", registry_kind="contradiction", registry_id="C-1",
                   disposition="unresolved", reason_code="conflicting_results")


class ViewsTest(unittest.TestCase):
    def test_control_current(self):
        self.assertEqual(v.coverage_view(BASE, PIN, (LINK,)), v.CoverageView("native",
            a.CandidateUnits(a.Count(frozenset({"r1", "r2"})), a.Count(frozenset({"w1"})),
                             a.Count(frozenset({"w1"})), a.Count(frozenset({"c1"})), ("p",)),
            (OBS,), (WINDOW,), (v.BranchCoverage("B-1", (LINK,), (WINDOW,), None),)))
        self.assertEqual(v.depth_view(BASE, DATE), v.DepthView(DATE,
            (a.SemanticOperand(f.SEMANTIC, "current", (LINEAGE,), (a.LifecycleOperand(f.SOURCE, "current"),)),),
            (a.LifecycleOperand(f.SOURCE, "current"),), (a.LifecycleOperand(f.SOURCE, "current"),),
            (v.RegistryHistory("branch", "B-1", (f.BRANCH,), (v.RegistryOperand(f.BRANCH, "current"),)),), (), ()))

    def test_control_empty(self):
        inv = a.Inventory("native")
        self.assertEqual(v.depth_view(inv, DATE), v.DepthView(DATE, (), (), (), (), (), ()))
        self.assertEqual(v.coverage_view(inv, ()).windows, ())

    def test_attempts_and_unknown(self):
        inv = replace(BASE, passes=(*BASE.passes, a.Pass("f", "research_pass", "failed"), a.Pass("u", "research_pass", "committed")))
        view = v.coverage_view(inv, (*PIN, WindowPin("f", 1), WindowPin("u", 1)))
        self.assertEqual(view.windows, (WINDOW,
            v.CoverageWindow(a.WindowStanding("f", "ineligible", "invocation failed or cancelled"), 1, "current", None),
            v.CoverageWindow(a.WindowStanding("u", "indeterminate", "invocation capture missing: u"), 1, "current", None)))
        self.assertEqual(view.units.retrieved_records, a.Count(frozenset({"r1", "r2"}), "invocation capture missing"))
        self.assertIsNone(view.units.deduplicated_works.value)
        self.assertEqual(view.observations, (OBS,))

    def test_control_missing_capture(self):
        inv = replace(BASE, observations=(), retrievals=(), links=())
        self.assertEqual(v.coverage_view(inv, PIN).windows[0].searches, None)

    def test_pins_and_standing(self):
        with self.assertRaises(ValueError):
            v.coverage_view(BASE, (*PIN, WindowPin("p", 2)))
        self.assertEqual(v.coverage_view(BASE, ()).windows[0].standing, "unknown")
        for classification, standing in (("compatible", "compatible"), ("reframed", "stale")):
            inv = replace(BASE, current_contract_revision=2, amendment_impacts=(f.impact(classification=classification),))
            self.assertEqual(v.coverage_view(inv, PIN).windows[0], replace(WINDOW, standing=standing))

    def test_branch_links_only(self):
        inv = replace(BASE, registry_dispositions=(replace(f.BRANCH, subject="p crossref probe"), CONFLICT))
        self.assertEqual(v.coverage_view(inv, PIN).branches,
                         (v.BranchCoverage("B-1", (), (), "branch search links not recorded"),))
        missing = v.BranchLink("B-1", "absent")
        extra = v.BranchLink("B-2", "absent")
        self.assertEqual(v.coverage_view(BASE, PIN, (LINK, missing, extra)).branches, (
            v.BranchCoverage("B-1", (LINK, missing), (WINDOW,), "linked research window missing"),
            v.BranchCoverage("B-2", (extra,), (), "linked research window missing")))

    def test_contradiction_history_and_competing_records(self):
        resolved = replace(CONFLICT, disposition_id="c2", disposition="resolved", supersedes_id="c1", created_at=LATER)
        competing = replace(CONFLICT, disposition_id="c3", disposition="contested", created_at=LATER)
        same_id_branch = replace(f.BRANCH, registry_id="C-1")
        inv = replace(BASE, registry_dispositions=(resolved, same_id_branch, competing, CONFLICT))
        self.assertEqual(v.depth_view(inv, DATE).registries, (
            v.RegistryHistory("branch", "C-1", (same_id_branch,), (v.RegistryOperand(same_id_branch, "current"),)),
            v.RegistryHistory("contradiction", "C-1", (CONFLICT,), (v.RegistryOperand(CONFLICT, "current"),))))
        self.assertEqual(v.depth_view(inv, LATER).registries[1], v.RegistryHistory("contradiction", "C-1",
            (CONFLICT, resolved, competing), (v.RegistryOperand(resolved, "current"), v.RegistryOperand(competing, "current"))))
        untouched = replace(inv, registry_dispositions=(CONFLICT, competing, same_id_branch))
        contradiction = v.depth_view(untouched, LATER).registries[1]
        self.assertEqual(contradiction.dispositions, ("unresolved", "contested"))
        self.assertEqual(contradiction.history, (CONFLICT, competing))

    def test_dated_lifecycle_lineage_and_reopenings(self):
        quarantine = replace(f.SOURCE, disposition_id="l2", action="quarantine", supersedes_id="l1", created_at=LATER)
        other = replace(f.SEMANTIC, assessment_id="s2", source_version="v2")
        lineage2 = replace(LINEAGE, assessment_id="s2", study_origin_id="study-B")
        impact = f.impact(classification="reframed", reopened=("e1",))
        inv = replace(BASE, source_lifecycle=(quarantine, f.SOURCE), semantic_assessments=(other, f.SEMANTIC),
            source_lineage=(LINEAGE, lineage2), registry_dispositions=(CONFLICT, f.BRANCH),
            amendment_impacts=(impact,), screening_history=(f.EXCLUSION,), current_contract_revision=2)
        early, late = v.depth_view(inv, DATE), v.depth_view(inv, LATER)
        self.assertEqual(early.lifecycle_history, (a.LifecycleOperand(f.SOURCE, "stale"),))
        self.assertEqual(late.lifecycle_history, (a.LifecycleOperand(f.SOURCE, "stale"), a.LifecycleOperand(quarantine, "stale")))
        self.assertEqual(late.lifecycle_active, (a.LifecycleOperand(quarantine, "stale"),))
        self.assertEqual(late.semantic, (
            a.SemanticOperand(f.SEMANTIC, "stale", (LINEAGE,), (a.LifecycleOperand(quarantine, "stale"),)),
            a.SemanticOperand(other, "stale", (lineage2,), ())))
        self.assertEqual(late.semantic[0].labels, ("unknown",) * 4)
        self.assertEqual((early.amendment_impacts, early.reopenings), ((), ()))
        self.assertEqual((late.amendment_impacts, late.reopenings), ((impact,), (f.EXCLUSION,)))
        self.assertIsNone(late.registries[1].dispositions)
        self.assertEqual(late.registries[1].active, (v.RegistryOperand(CONFLICT, "stale"),))
        future_exclusion = replace(f.EXCLUSION, created_at="2026-10-09T00:00:02Z")
        self.assertEqual(v.depth_view(replace(inv, screening_history=(future_exclusion,)), LATER).reopenings, ())

    def test_control_registry_labels(self):
        self.assertEqual(v.depth_view(BASE, DATE).registries[0].dispositions, ("promote",))

    def test_branch_history_and_empty_unknown(self):
        park = replace(f.BRANCH, disposition_id="b2", disposition="park", supersedes_id="b1", created_at=LATER)
        inv = replace(BASE, registry_dispositions=(park, f.BRANCH))
        self.assertEqual(v.depth_view(inv, LATER).registries, (
            v.RegistryHistory("branch", "B-1", (f.BRANCH, park), (v.RegistryOperand(park, "current"),)),))
        self.assertIsNone(v.RegistryHistory("branch", "missing", (), ()).dispositions)

    def test_registry_identity(self):
        other = replace(CONFLICT, disposition_id="c2", registry_id="C-2")
        inv = replace(BASE, registry_dispositions=(CONFLICT, other))
        self.assertEqual(v.depth_view(inv, DATE).registries, (
            v.RegistryHistory("contradiction", "C-1", (CONFLICT,), (v.RegistryOperand(CONFLICT, "current"),)),
            v.RegistryHistory("contradiction", "C-2", (other,), (v.RegistryOperand(other, "current"),))))

    def test_properties(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class SnapshotTest(ContractWorld):
    def test_unrelated_topic_and_read_only(self):
        self.research()
        before = self.state(exclude=())
        self.router._clock = lambda: self.fail("view read a clock")
        from unittest.mock import patch
        from gen2.store import capture
        read = capture.read
        def snapshot(conn, columns, topic):
            self.assertTrue(self.db.in_transaction)
            return read(conn, columns, topic)
        with patch.object(capture, "read", snapshot):
            inv = self.router.evidence_inventory(OTHER, history="native")
        coverage, depth = v.coverage_view(inv, ()), v.depth_view(inv, LATER)
        self.assertEqual(coverage.units.retrieved_records, a.Count(frozenset()))
        self.assertEqual(depth, v.DepthView(LATER, (), (), (), (), (), ()))
        self.assertEqual(self.state(exclude=()), before)
        self.router._clock = lambda: "2026-10-09T00:00:00Z"
        self.approve(self.propose(3, compatible))
        self.router._clock = lambda: self.fail("view read a clock")
        other = self.router.evidence_inventory(OTHER, history="native")
        self.assertEqual((v.coverage_view(other, ()), v.depth_view(other, LATER)), (coverage, depth))


PROPERTIES = '''
from hypothesis import given, settings, strategies as st
from gen2.tests.test_research_views import BASE, PIN, DATE, CONFLICT
from gen2.accounting import views as v
from dataclasses import replace
@settings(max_examples=30, derandomize=True, database=None, deadline=None)
@given(st.sampled_from(["novelty", "independence", "applicability", "contribution"]))
def unknown(field):
    record = replace(BASE.semantic_assessments[0], **{field: "unknown"})
    inv = replace(BASE, semantic_assessments=(record,))
    labels = v.depth_view(inv, DATE).semantic[0].labels
    assert labels[["novelty", "independence", "applicability", "contribution"].index(field)] == "unknown"
    legacy = v.coverage_view(replace(inv, history="legacy_unknown"), PIN)
    assert legacy.units.retrieved_records.value is None
    assert legacy.windows[0].capture.state == "indeterminate"
    unpinned = replace(inv, current_contract_revision=2)
    assert v.coverage_view(unpinned, PIN).windows[0].standing == "unknown"
    assert v.depth_view(unpinned, DATE).semantic[0].labels == ("unknown",) * 4
@settings(max_examples=30, derandomize=True, database=None, deadline=None)
@given(st.permutations((BASE.registry_dispositions[0], CONFLICT)))
def permutation(records):
    inv = replace(BASE, registry_dispositions=tuple(records))
    canonical = replace(BASE, registry_dispositions=(BASE.registry_dispositions[0], CONFLICT))
    assert v.depth_view(inv, DATE) == v.depth_view(canonical, DATE)
    assert inv.registry_dispositions == tuple(records)
unknown()
permutation()
'''
