"""Hand-written E-6 truth tables and evaluator inventories; no providers."""
import unittest
from dataclasses import replace
from fractions import Fraction

from gen2 import accounting as a
from gen2.accounting import stopping as s
from gen2.tests import children

S, N, U = "satisfied", "not_satisfied", "unknown"
CTX = s.Context("topic", 1, 1)
DATE = "2026-10-09T00:00:00Z"
REF = a.EvidenceReference("a" * 64, 10, "application/json")
ITEMS = s.KnownItems(REF, frozenset({"w1"}))


def inventory():
    semantic = a.SemanticAssessment("label", "w1", "v1", 1, 1, 1, "not_novel", "independent", "applicable", "answer", (REF,), "primary", "p", "op", DATE)
    return a.Inventory("native",
        observations=(a.Observation("o", "p", "lane", "q", "find", "complete", "exhausted", 1,
                                   a.SearchPage(a.search_identity({"query": "q"}), 1, None, None)),),
        retrievals=(a.Retrieval("r", "o"),), links=(a.WorkLink("r", "w1"),),
        assessments=(a.Assessment("w1"),), passes=(a.Pass("p", "research_pass", "committed"),),
        semantic_assessments=(semantic,), current_contract_revision=1)


def rule(state=S, rule_id="r"):
    return replace(s.known_item(CTX, rule_id, inventory(), ITEMS), state=state)


def profile(op="all", gates=()):
    return s.Profile("profile", s.Expression(op=op, operands=(s.Expression("r"), s.Expression("r2"))), gates)


class StoppingTest(unittest.TestCase):
    def test_truth_tables(self):
        all_table = ((S, S, S), (S, N, N), (S, U, U), (N, S, N), (N, N, N), (N, U, N), (U, S, U), (U, N, N), (U, U, U))
        any_table = ((S, S, S), (S, N, S), (S, U, S), (N, S, S), (N, N, N), (N, U, U), (U, S, S), (U, N, U), (U, U, U))
        for op, table in (("all", all_table), ("any", any_table)):
            for left, right, expected in table:
                with self.subTest(op=op, left=left, right=right):
                    self.assertEqual(s.combine(op, (left, right)), expected)
        self.assertEqual(s.combine("all", ()), U)
        self.assertEqual(s.combine("any", ()), U)

    def test_control_satisfied(self):
        self.assertEqual(s.combine("all", (S, S)), S)
        self.assertEqual(s.combine("any", (S, S)), S)
        self.assertEqual(s.evaluate_profile(CTX, profile(), (rule(), rule(rule_id="r2")), ()).state, S)

    def test_all_is_not_majority(self):
        self.assertEqual(s.combine("all", (S, S, N)), N)
        self.assertEqual(s.combine("all", (S, S, U)), U)
        self.assertEqual(s.combine("any", (N, N, S)), S)

    def test_gates_override_any_and_unknown(self):
        for state in (N, U):
            gate = s.GateResult(CTX, "coverage_integrity", state, (REF,))
            result = s.evaluate_profile(CTX, profile("any", (gate.gate,)), (rule(), rule(N, "r2")), (gate,))
            self.assertEqual((result.state, result.gates), (state, (gate,)))
        self.assertEqual(s.evaluate_profile(CTX, profile(gates=("challenge_pass_completed",)), (rule(), rule(rule_id="r2")), ()).state, U)

    def test_control_gate_pass(self):
        gates = tuple(s.GateResult(CTX, g, S, (REF,)) for g in ("challenge_pass_completed", "coverage_integrity", "load_bearing_verification_tiers"))
        self.assertEqual(s.evaluate_profile(CTX, profile(gates=tuple(g.gate for g in gates)), (rule(), rule(rule_id="r2")), gates).state, S)

    def test_expressions_and_pins(self):
        nested = s.Expression(op="all", operands=(s.Expression("r"), s.Expression(op="any", operands=(s.Expression("r2"), s.Expression("missing")))))
        self.assertEqual(s.expression_state(nested, {"r": S, "r2": N}), U)
        for context in (replace(CTX, topic_id="other"), replace(CTX, contract_revision=2), replace(CTX, protocol_revision=2)):
            with self.subTest(context=context):
                self.assertEqual(s.evaluate_profile(CTX, profile(), (replace(rule(), context=context), rule(rule_id="r2")), ()).state, U)
                gate = s.GateResult(context, "coverage_integrity", S, (REF,))
                self.assertEqual(s.evaluate_profile(CTX, profile(gates=(gate.gate,)), (rule(), rule(rule_id="r2")), (gate,)).state, U)
        for expr in ({}, {"op": "majority", "operands": (s.Expression("r"),)}, {"op": "all"}, {"rule": "r", "op": "all", "operands": (s.Expression("r2"),)}):
            with self.assertRaises(ValueError): s.Expression(**expr)
        with self.assertRaises(ValueError): s.combine("majority", (S, S, N))
        with self.assertRaises(ValueError): s.combine("all", ("false",))
        with self.assertRaises(ValueError): s.evaluate_profile(CTX, profile(), (rule(), rule()), ())
        gate = s.GateResult(CTX, "coverage_integrity", S, (REF,))
        with self.assertRaises(ValueError): s.evaluate_profile(CTX, profile(), (), (gate, gate))

    def test_control_descriptive(self):
        result = s.descriptive(CTX, "yield", inventory(), DATE)
        self.assertEqual((result.state, result.operands.new_fraction), (U, Fraction(0)))
        self.assertEqual(result.operands.units.deduplicated_works, a.Count(frozenset({"w1"})))
        self.assertEqual(result.operands.labels[0].assessment_id, "label")
        self.assertEqual((result.schema_version, result.context), ("stopping-result/1", CTX))

    def test_stale_unknown_and_empty_labels(self):
        for classification in ("protocol_changed", "reframed"):
            impact = a.AmendmentImpact("amendment", 1, (a.RevisionStanding(1, classification),), (), DATE)
            inv = replace(inventory(), amendment_impacts=(impact,))
            self.assertIsNone(s.descriptive(CTX, "yield", inv, DATE).operands.new_fraction)
            self.assertEqual(s.coverage(CTX, "coverage", inv, (s.WindowPin("p", 1),), 1).state, N)
        for inv in (replace(inventory(), current_contract_revision=2), replace(inventory(), semantic_assessments=()),
                    replace(inventory(), assessments=()), replace(inventory(), semantic_assessments=(replace(inventory().semantic_assessments[0], novelty="unknown"),))):
            self.assertIsNone(s.descriptive(CTX, "yield", inv, DATE).operands.new_fraction)

    def test_control_coverage(self):
        result = s.coverage(CTX, "coverage", inventory(), (s.WindowPin("p", 1),), 1)
        self.assertEqual((result.state, result.operands.windows), (S, (s.WindowOperand("p", 1, "current"),)))
        self.assertEqual(s.coverage(CTX, "coverage", inventory(), (s.WindowPin("p", 1),), 2).state, N)

    def test_control_short_coverage(self):
        self.assertEqual(s.coverage(CTX, "coverage", inventory(), (s.WindowPin("p", 1),), 2).state, N)

    def test_compatible_and_unknown_standing(self):
        inv = replace(inventory(), current_contract_revision=2)
        context = replace(CTX, contract_revision=2)
        self.assertEqual(s.coverage(context, "coverage", inv, (s.WindowPin("p", 1),), 1).state, U)
        impact = a.AmendmentImpact("amendment", 2, (a.RevisionStanding(1, "compatible"),), (), DATE)
        inv = replace(inv, amendment_impacts=(impact,))
        self.assertEqual(s.coverage(context, "coverage", inv, (s.WindowPin("p", 1),), 1).state, S)
        self.assertEqual(s.descriptive(context, "yield", inv, DATE).operands.new_fraction, Fraction(0))

    def test_evaluator_context(self):
        context = replace(CTX, contract_revision=2)
        self.assertIsNone(s.descriptive(context, "yield", inventory(), DATE).operands.new_fraction)
        self.assertEqual(s.coverage(context, "coverage", inventory(), (s.WindowPin("p", 1),), 1).state, U)
        self.assertEqual(s.known_item(context, "sentinels", inventory(), ITEMS).state, U)

    def test_nonwindows_repetition_and_missing_pins(self):
        inv = inventory()
        for changed in (replace(inv, passes=(replace(inv.passes[0], state="failed"),)),
                        replace(inv, observations=(replace(inv.observations[0], request_type="resolve", page=None),))):
            self.assertEqual(s.coverage(CTX, "coverage", changed, (s.WindowPin("p", 1),), 1).state, N)
        partial = replace(inv, observations=(replace(inv.observations[0], completeness="partial"),))
        self.assertEqual(s.coverage(CTX, "coverage", partial, (s.WindowPin("p", 1),), 1).state, U)
        repeat = replace(inv, passes=inv.passes + (a.Pass("p2", "research_pass", "committed"),),
                         observations=inv.observations + (replace(inv.observations[0], observation_id="o2", invocation_id="p2"),),
                         retrievals=inv.retrievals + (a.Retrieval("r2", "o2"),), links=inv.links + (a.WorkLink("r2", "w1"),))
        self.assertEqual(s.coverage(CTX, "coverage", repeat, (s.WindowPin("p", 1), s.WindowPin("p2", 1)), 2).state, N)
        self.assertEqual(s.coverage(CTX, "coverage", inv, (), 1).state, U)
        self.assertEqual(s.coverage(CTX, "coverage", replace(inv, history="legacy_unknown"), (), 1).state, U)
        self.assertEqual(s.coverage(CTX, "coverage", a.Inventory("legacy_unknown", current_contract_revision=1), (), 1).state, U)
        with self.assertRaises(ValueError): s.coverage(CTX, "coverage", inv, (), 0)
        with self.assertRaises(ValueError): s.coverage(CTX, "coverage", inv, (s.WindowPin("p", 1),) * 2, 1)

    def test_control_known_item(self):
        result = s.known_item(CTX, "sentinels", inventory(), ITEMS)
        self.assertEqual((result.state, result.operands.found, result.operands.missing), (S, frozenset({"w1"}), frozenset()))
        self.assertEqual(result.operands.declared, ITEMS)

    def test_known_item_missing_and_unknown(self):
        result = s.known_item(CTX, "sentinels", inventory(), replace(ITEMS, work_ids=frozenset({"w1", "w2"})))
        self.assertEqual((result.state, result.operands.found, result.operands.missing), (N, frozenset({"w1"}), frozenset({"w2"})))
        self.assertEqual(s.known_item(CTX, "sentinels", inventory(), replace(ITEMS, work_ids=frozenset())).state, U)
        for inv in (replace(inventory(), links=()), replace(inventory(), history="legacy_unknown"), replace(inventory(), current_contract_revision=2)):
            self.assertEqual(s.known_item(CTX, "sentinels", inv, ITEMS).state, U)

    def test_properties(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROPERTIES = '''
from hypothesis import given, settings, strategies as st
from gen2.accounting.stopping import combine
states = ("not_satisfied", "unknown", "satisfied")
@settings(max_examples=80, derandomize=True, database=None)
@given(st.lists(st.integers(0, 2), min_size=1, max_size=12), st.sampled_from(("all", "any")), st.integers(0, 11))
def monotone(indices, op, slot):
    lower = tuple(states[i] for i in indices)
    indices[slot % len(indices)] = min(2, indices[slot % len(indices)] + 1)
    upper = tuple(states[i] for i in indices)
    assert states.index(combine(op, lower)) <= states.index(combine(op, upper))
@settings(max_examples=40, derandomize=True, database=None)
@given(st.lists(st.sampled_from(("unknown", "satisfied")), max_size=12))
def unknown_persists(values):
    assert combine("all", ("unknown", *values, "satisfied")) == "unknown"
monotone(); unknown_persists()
'''
