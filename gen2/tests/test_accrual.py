"""2b2b independent operand oracles; retained fixtures and fakes only."""
import unittest
from dataclasses import replace

from gen2 import accounting as a
from gen2.tests import children
from gen2.tests.router_fixtures import TOPIC, OTHER
from gen2.tests.test_router_amendments import ContractWorld, compatible, reframed

DATE = "2026-10-09T00:00:00Z"
LATER = "2026-10-09T00:00:01Z"
SEMANTIC = a.SemanticAssessment("s1", "w1", "v1", 1, 1, 1, "novel", "shared_origin", "applicable", "answer", (), "primary", "inv", "op", DATE)
SOURCE = a.SourceDisposition("l1", "w1", "v1", 1, 1, 1, "add", None, None, None, "new", (), "primary", "inv", "op", DATE)
BRANCH = a.RegistryDisposition("b1", "branch", "B-1", "Bridge probe", "promote", 1, 1, 1, None, "probe", (), "primary", "inv", "op", DATE)
EXCLUSION = a.ScreeningAssessment("e1", "w1", 1, 1, 1, "abstract", "exclude", "adds_nothing", "primary", "inv", None, None, None, "op", DATE)


def impact(current=2, classification="compatible", standing_revision=1, reopened=()):
    return a.AmendmentImpact(f"approval-{current}", current, (a.RevisionStanding(standing_revision, classification),), reopened, LATER)


def inventory(**changes):
    return a.Inventory("native", semantic_assessments=(SEMANTIC,), source_lifecycle=(SOURCE,),
                       registry_dispositions=(BRANCH,), current_contract_revision=1, **changes)


def operands(inv):
    return a.semantic_accrual(inv, "w1", "v1", LATER)


class AccrualTest(unittest.TestCase):
    def test_control_current(self):
        lineage = a.SourceLineage("s1", "shared_study_origin", "study-A", None, None)
        inv = inventory(source_lineage=(lineage,))
        self.assertEqual(operands(inv), (a.SemanticOperand(SEMANTIC, "current", (lineage,), (a.LifecycleOperand(SOURCE, "current"),)),))
        self.assertEqual(operands(inv)[0].labels, ("novel", "shared_origin", "applicable", "answer"))
        self.assertEqual(a.branch_accrual(inv, "B-1", DATE).dispositions, ("promote",))
        self.assertEqual(a.rescreening_view(inv), ())

    def test_control_compatible(self):
        inv = replace(inventory(), current_contract_revision=2, amendment_impacts=(impact(),))
        self.assertEqual(operands(inv)[0].standing, "compatible")
        self.assertEqual(operands(inv)[0].labels, ("novel", "shared_origin", "applicable", "answer"))
        self.assertEqual(a.branch_accrual(inv, "B-1", DATE).dispositions, ("promote",))

    def test_invalid_and_cycling(self):
        inv = replace(inventory(), current_contract_revision=2, amendment_impacts=(impact(classification="reframed"),))
        self.assertEqual((operands(inv)[0].standing, operands(inv)[0].labels), ("stale", ("unknown",) * 4))
        self.assertIsNone(a.branch_accrual(inv, "B-1", DATE).dispositions)
        # Even a later explicit compatible record cannot undo the invalidation.
        cycled = replace(inv, current_contract_revision=3, amendment_impacts=inv.amendment_impacts + (impact(3),))
        self.assertEqual((operands(cycled)[0].standing, operands(cycled)[0].labels), ("stale", ("unknown",) * 4))
        self.assertEqual(operands(cycled)[0].assessment, SEMANTIC)  # original labels retained

    def test_missing_standing(self):
        for inv in (replace(inventory(), current_contract_revision=None),
                    replace(inventory(), current_contract_revision=2),
                    replace(inventory(), current_contract_revision=3, amendment_impacts=(impact(),)),
                    replace(inventory(), current_contract_revision=2, amendment_impacts=(impact(classification="reframed", standing_revision=9),)),
                    replace(inventory(), current_contract_revision=2, amendment_impacts=(impact(standing_revision=9),))):
            with self.subTest(inv=inv):
                self.assertEqual((operands(inv)[0].standing, operands(inv)[0].labels), ("unknown", ("unknown",) * 4))
                self.assertIsNone(a.branch_accrual(inv, "B-1", DATE).dispositions)
        self.assertIsNone(a.branch_accrual(inventory(), "missing", DATE).dispositions)
        self.assertEqual(a.semantic_accrual(inventory(), "missing", "v1", DATE), ())

    def test_exact_joins_and_lifecycle_reversal(self):
        lineage = a.SourceLineage("s1", "shared_study_origin", "study-A", None, None)
        other = replace(lineage, assessment_id="s2", study_origin_id="study-B")
        quarantine = replace(SOURCE, disposition_id="l2", action="quarantine", supersedes_id="l1", created_at=LATER)
        reversal = replace(SOURCE, disposition_id="l3", action="keep", supersedes_id="l2", created_at="2026-10-09T00:00:02Z")
        inv = replace(inventory(source_lineage=(lineage, other)),
            source_lifecycle=(SOURCE, quarantine, reversal, replace(SOURCE, disposition_id="l4", source_version="v2"),
                              replace(SOURCE, disposition_id="l5", work_id="w2")),
            semantic_assessments=(SEMANTIC, replace(SEMANTIC, assessment_id="s2", source_version="v2"),
                                  replace(SEMANTIC, assessment_id="s3", work_id="w2"), replace(SEMANTIC, assessment_id="s4", created_at=reversal.created_at)))
        self.assertEqual(operands(inv), (a.SemanticOperand(SEMANTIC, "current", (lineage,), (a.LifecycleOperand(quarantine, "current"),)),))
        self.assertEqual(a.semantic_accrual(inv, "w1", "v1", reversal.created_at)[0].lifecycle, (a.LifecycleOperand(reversal, "current"),))

    def test_lifecycle_standing(self):
        inv = replace(inventory(), current_contract_revision=2, semantic_assessments=(replace(SEMANTIC, contract_revision=2),))
        self.assertEqual(operands(inv)[0].lifecycle, (a.LifecycleOperand(SOURCE, "unknown"),))
        stale = replace(inv, amendment_impacts=(impact(classification="reframed"),))
        self.assertEqual((operands(stale)[0].standing, operands(stale)[0].lifecycle), ("current", (a.LifecycleOperand(SOURCE, "stale"),)))

    def test_control_branch_reversal(self):
        park = replace(BRANCH, disposition_id="b2", disposition="park", supersedes_id="b1", created_at=LATER)
        drop = replace(BRANCH, disposition_id="b3", disposition="drop", supersedes_id="b2", created_at="2026-10-09T00:00:02Z")
        promote = replace(BRANCH, disposition_id="b4", supersedes_id="b3", created_at="2026-10-09T00:00:03Z")
        inv = replace(inventory(), registry_dispositions=(promote, BRANCH, drop, park))
        for date, expected, prefix in ((DATE, ("promote",), (BRANCH,)), (LATER, ("park",), (BRANCH, park)),
                                      (drop.created_at, ("drop",), (BRANCH, park, drop)), (promote.created_at, ("promote",), (BRANCH, park, drop, promote))):
            view = a.branch_accrual(inv, "B-1", date)
            self.assertEqual((view.dispositions, view.history), (expected, prefix))

    def test_disagreement_and_unrelated(self):
        competing = replace(BRANCH, disposition_id="b2", disposition="park")
        other = replace(BRANCH, disposition_id="b3", registry_id="B-2")
        contradiction = replace(BRANCH, disposition_id="c1", registry_kind="contradiction", disposition="unresolved")
        inv = replace(inventory(), registry_dispositions=(BRANCH, competing, other, contradiction))
        self.assertEqual(a.branch_accrual(inv, "B-1", DATE).dispositions, ("promote", "park"))
        disagreement = replace(SEMANTIC, assessment_id="s2", novelty="not_novel")
        sem = operands(replace(inv, semantic_assessments=(SEMANTIC, disagreement)))
        self.assertEqual([r.labels[0] for r in sem], ["novel", "not_novel"])
        self.assertEqual(inv.registry_dispositions[-1], contradiction)

    def test_control_reopened(self):
        inv = inventory(screening_history=(EXCLUSION,), amendment_impacts=(impact(classification="reframed", reopened=("e1",)),))
        self.assertEqual(a.rescreening_view(inv), (EXCLUSION,))

    def test_rescreening_recorded_only(self):
        included = replace(EXCLUSION, assessment_id="i1", decision="include", reason_code=None)
        untouched = replace(EXCLUSION, assessment_id="e2", framing_version=2)
        inv = inventory(screening_history=(included, untouched, EXCLUSION),
                        amendment_impacts=(impact(classification="reframed", reopened=("e1", "i1", "missing")),))
        self.assertEqual(a.rescreening_view(inv), (EXCLUSION,))
        self.assertEqual(a.rescreening_view(replace(inv, amendment_impacts=(impact(classification="reframed"),))), ())
        self.assertEqual(inv.screening_history, (included, untouched, EXCLUSION))

    def test_properties(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class SnapshotTest(ContractWorld):
    def test_control_initial(self):
        self.research()
        inv = self.router.evidence_inventory(TOPIC, history="native")
        self.assertEqual((inv.current_contract_revision, inv.amendment_impacts), (2, ()))
        self.assertEqual(len(inv.screening_history), 2)

    def test_control_empty_topic(self):
        inv = self.router.evidence_inventory(OTHER, history="native")
        self.assertEqual((inv.current_contract_revision, inv.amendment_impacts, inv.screening_history), (None, (), ()))

    def test_control_context(self):
        self.research()
        self.approve(self.propose(3, compatible))
        inv = self.router.evidence_inventory(TOPIC, history="native")
        self.assertEqual((a.label_standing(inv, 3), inv.amendment_impacts[0].current_revision), ("current", 3))
        self.assertEqual(a.rescreening_view(inv), ())

    def test_reframe_inventory(self):
        self.research()
        before = self.router.evidence_inventory(TOPIC, history="native").screening_history
        self.approve(self.propose(3, reframed), "reframe_approval")
        state = self.state(exclude=())
        self.router._clock = lambda: self.fail("read used clock")
        from unittest.mock import patch
        from gen2.store import capture
        read = capture.read
        tables = []
        def in_snapshot(conn, columns, topic):
            self.assertTrue(self.db.in_transaction)
            raw = read(conn, columns, topic)
            tables.extend(t.name for t in raw.tables)
            return raw
        with patch.object(capture, "read", in_snapshot):
            inv = self.router.evidence_inventory(TOPIC, history="native")
        self.assertEqual(inv.current_contract_revision, 3)
        self.assertEqual(len(inv.amendment_impacts), 1)
        self.assertEqual(inv.amendment_impacts[0].standing, (a.RevisionStanding(2, "reframed"),))
        self.assertEqual(a.label_standing(inv, 2), "stale")
        self.assertEqual(a.rescreening_view(inv), (before[1],))
        self.assertEqual((before[1].reason_code, before[1].framing_version, before[1].contract_revision), ("EC-outcome", 1, 2))
        self.assertEqual(inv.screening_history, before)
        self.assertEqual(self.router.evidence_inventory(OTHER, history="native").amendment_impacts, ())
        self.assertEqual(self.state(exclude=()), state)
        self.assertTrue({"semantic_assessments", "source_lineage", "source_lifecycle", "registry_dispositions", "amendment_impacts", "screening_assessments", "contract_revisions"} <= set(tables))

    def test_control_unaffected(self):
        self.research()
        self.approve(self.propose(3, compatible))
        inv = self.router.evidence_inventory(TOPIC, history="native")
        self.assertEqual((a.label_standing(inv, 2), a.rescreening_view(inv)), ("compatible", ()))
        self.assertEqual(len(inv.screening_history), 2)


PROPERTIES = '''
from hypothesis import given, settings, strategies as st
from gen2.tests.test_accrual import *
@settings(max_examples=30, derandomize=True, database=None, deadline=None)
@given(st.sampled_from(["promote", "park", "drop"]), st.integers(min_value=2, max_value=100))
def unrelated(label, revision):
    inv = inventory()
    extra = replace(BRANCH, disposition_id="extra", registry_id="B-2", disposition=label, contract_revision=revision)
    appended = replace(inv, registry_dispositions=inv.registry_dispositions + (extra,))
    assert operands(inv) == operands(appended)
    assert a.branch_accrual(inv, "B-1", DATE) == a.branch_accrual(appended, "B-1", DATE)
    future = replace(BRANCH, disposition_id="future", supersedes_id="b1", disposition=label, created_at=LATER)
    assert a.branch_accrual(inv, "B-1", DATE) == a.branch_accrual(replace(inv, registry_dispositions=(BRANCH, future)), "B-1", DATE)
@settings(max_examples=30, derandomize=True, database=None, deadline=None)
@given(st.sampled_from(["novelty", "independence", "applicability", "contribution"]))
def unknown(field):
    inv = replace(inventory(), semantic_assessments=(replace(SEMANTIC, **{field: "unknown"}),))
    assert operands(inv)[0].labels[["novelty", "independence", "applicability", "contribution"].index(field)] == "unknown"
    stale = replace(inv, current_contract_revision=2, amendment_impacts=(impact(classification="protocol_changed"),))
    assert operands(stale)[0].labels == ("unknown",) * 4
unrelated()
unknown()
'''
