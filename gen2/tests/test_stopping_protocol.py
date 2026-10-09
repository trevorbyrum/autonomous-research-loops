"""Literal 2c-3b2 oracles; Router history is recorded in disposable memory."""
import unittest
from dataclasses import replace

from gen2.accounting import stopping as s
from gen2.tests import test_accounting as at, test_router_amendments as am, test_stopping as st
from gen2.tests import test_stopping_bindings as sb
from gen2.tests.router_fixtures import TOPIC, find_request


def coverage_rule(scope, minimum=1):
    return {"rule_id": "R-windows", "family": "coverage", "evaluation": "automatic",
            "params": {"minimum_windows": minimum, "scope": list(scope)}}


DESCRIPTIVE = {"rule_id": "R-yield", "family": "descriptive", "evaluation": "automatic", "params": {}}


class BindingTest(unittest.TestCase):
    def evaluate_binding(self, *args, **kwargs):
        try:
            return s.evaluate_binding(*args, **kwargs)
        except ValueError as error:
            self.fail(f"supported automatic binding was refused: {error}")

    def test_control_descriptive(self):
        bound = s.bind_rule(DESCRIPTIVE)
        result = self.evaluate_binding(bound, st.CTX, st.inventory(), as_of=st.DATE)
        self.assertEqual((bound.family, bound.evaluator, bound.params), ("descriptive", "descriptive", {}))
        self.assertEqual((result.rule_id, result.state, result.operands.new_fraction), ("R-yield", "unknown", 0))

    def test_control_coverage(self):
        declared = coverage_rule(["p"])
        bound = s.bind_rule(declared)
        declared["params"]["scope"].clear()
        result = self.evaluate_binding(bound, st.CTX, st.inventory(), pins=(s.WindowPin("p", 1),))
        self.assertEqual((bound.family, bound.evaluator), ("coverage", "coverage"))
        self.assertEqual((result.state, result.operands.minimum_windows, result.operands.scope, result.operands.lower),
                         ("satisfied", 1, frozenset({"p"}), 1))

    def test_control_coverage_evaluation(self):
        result = self.evaluate_binding(s.bind_rule(coverage_rule(["p"])), st.CTX, st.inventory(), pins=(s.WindowPin("p", 1),))
        self.assertEqual((result.state, result.operands.minimum_windows, result.operands.lower), ("satisfied", 1, 1))

    def test_control_current_profile(self):
        gate = s.GateResult(st.CTX, "coverage_integrity", "satisfied", (st.REF,))
        profile = s.Profile("profile", s.Expression("r"), (gate.gate,))
        result = s.evaluate_profile(st.CTX, profile, (st.rule(),), (gate,), inventory=st.inventory())
        self.assertEqual((result.rules, result.state), ((st.rule(),), "satisfied"))

    def test_declared_minimum_and_scope(self):
        for declaration, expected in ((coverage_rule(["p"], 2), "not_satisfied"),
                                      (coverage_rule([]), "not_satisfied"), (coverage_rule(["other"]), "not_satisfied")):
            with self.subTest(declaration=declaration):
                result = self.evaluate_binding(s.bind_rule(declaration), st.CTX, st.inventory(), pins=(s.WindowPin("p", 1),))
                self.assertEqual(result.state, expected)
                self.assertEqual(result.operands.scope, frozenset(declaration["params"]["scope"]))

    def test_required_runtime_operands(self):
        with self.assertRaisesRegex(ValueError, "explicit as_of"):
            s.evaluate_binding(s.bind_rule(DESCRIPTIVE), st.CTX, st.inventory())
        with self.assertRaisesRegex(ValueError, "sentinel inventory required"):
            s.evaluate_binding(s.bind_rule(sb.rule()), st.CTX, st.inventory())
        for declaration in (DESCRIPTIVE, coverage_rule(["p"])):
            with self.subTest(declaration=declaration), self.assertRaisesRegex(ValueError, "no automatic evaluator"):
                s.evaluate_binding(s.bind_rule({**declaration, "evaluation": "reviewed_judgment"}), st.CTX, st.inventory())

    def test_reuse_requires_current_snapshot_and_exact_context(self):
        current = replace(st.CTX, contract_revision=2)
        impact = st.a.AmendmentImpact("approval", 2, (st.a.RevisionStanding(1, "compatible"),), (), st.DATE)
        inv = replace(st.inventory(), current_contract_revision=2, amendment_impacts=(impact,))
        old = st.rule()
        profile = s.Profile("profile", s.Expression("r"), ())
        for snapshot, result in ((replace(inv, current_contract_revision=3), replace(old, context=replace(old.context, contract_revision=3))),
                                 (replace(inv, amendment_impacts=()), old),
                                 (inv, replace(old, context=replace(old.context, topic_id="other"))),
                                 (inv, replace(old, context=replace(old.context, protocol_revision=9)))):
            with self.subTest(snapshot=snapshot, result=result):
                dossier = s.evaluate_profile(current, profile, (result,), (), inventory=snapshot)
                self.assertEqual((dossier.state, dossier.rules), ("unknown", ()))

    def test_recorded_invalidation_with_same_protocol(self):
        impact = st.a.AmendmentImpact("approval", 2, (st.a.RevisionStanding(1, "reframed"),), (), st.DATE)
        inv = replace(st.inventory(), current_contract_revision=2, amendment_impacts=(impact,))
        dossier = s.evaluate_profile(replace(st.CTX, contract_revision=2), s.Profile("profile", s.Expression("r"), ()),
                                     (st.rule(),), (), inventory=inv)
        self.assertEqual((dossier.state, dossier.rules), ("unknown", ()))


class ProtocolTest(am.ContractWorld):
    page = at.WindowTest.page

    def declaration(self, doc, scope, protocol):
        sb.set_rules(doc, [coverage_rule(scope), DESCRIPTIVE])
        doc["stopping_profiles"][0]["completion_condition"] = {"rule": "R-windows"}
        doc["protocol_revision"] = protocol

    def approve_a(self):
        doc = self.propose(3, lambda d: self.declaration(d, ["inv_windowsA01"], 2))
        self.assertEqual(self.approve(doc)["status"], "applied")
        self.window("inv_windowsA01", "obs_windowsA01", "population A")
        return doc

    def window(self, inv, obs, query):
        grant = self.started(inv)
        self.page(grant, obs, find_request(query))
        self.assertEqual(self.finish(grant, "op_" + inv[4:])["status"], "committed")

    def evaluate(self, doc, rules=None, gates=()):
        inv = self.router.evidence_inventory(TOPIC, history="native")
        context = s.Context(TOPIC, doc["revision"], doc["protocol_revision"])
        binding = s.bind_profile(doc["stopping_profiles"][0])
        if rules is None:
            pins = tuple(s.WindowPin(i, revision) for i, revision in self.rows(
                "SELECT invocation_id, contract_revision FROM invocations WHERE topic_id = ?", TOPIC))
            rules = tuple(s.evaluate_binding(r, context, inv, pins=pins, as_of=st.DATE) for r in binding.rules)
        return s.evaluate_profile(context, binding.profile, rules, gates, inventory=inv)

    def test_incompatible_amendment_and_b_current_evaluation(self):
        a = self.approve_a()
        before = self.evaluate(a)
        self.assertEqual(([r.state for r in before.rules], before.state), (["satisfied", "unknown"], "unknown"))
        bad = am.contract_doc(4, 3, edit=lambda d: self.declaration(d, ["inv_windowsB01"], 2))
        self.assertEqual(self.router.propose_amendment({"document": bad})["status"], "refused")
        b = self.propose(4, lambda d: self.declaration(d, ["inv_windowsB01"], 3))
        self.assertEqual(self.approve(b)["effects"]["impact"]["classification"], "protocol_changed")
        inv = self.router.evidence_inventory(TOPIC, history="native")
        self.assertIn(st.a.RevisionStanding(3, "protocol_changed"), inv.amendment_impacts[-1].standing)
        stale = self.evaluate(b, before.rules)
        self.assertEqual((stale.rules, stale.state), ((), "unknown"))
        self.assertEqual(self.evaluate(b).rules[0].state, "not_satisfied")
        self.window("inv_windowsB01", "obs_windowsB01", "population B")
        after = self.evaluate(b)
        self.assertEqual(([r.state for r in after.rules], after.state), (["satisfied", "unknown"], "unknown"))
        self.assertEqual(after.rules[0].operands.windows, (s.WindowOperand("inv_windowsB01", 4, "current"),))
        self.assertEqual(before.rules[0].context, s.Context(TOPIC, 3, 2))

    def test_control_compatible_reuse(self):
        a = self.approve_a()
        before = self.evaluate(a)
        def edit(doc):
            self.declaration(doc, ["inv_windowsA01"], 2)
            am.compatible(doc)
        b = self.propose(4, edit)
        self.assertEqual(self.approve(b)["effects"]["impact"]["classification"], "compatible")
        inv = self.router.evidence_inventory(TOPIC, history="native")
        self.assertIn(st.a.RevisionStanding(3, "compatible"), inv.amendment_impacts[-1].standing)
        reused = self.evaluate(b, before.rules)
        self.assertEqual((reused.rules, reused.state), (before.rules, "unknown"))
        self.assertIs(reused.rules[0], before.rules[0])
        self.assertEqual(self.evaluate(b).rules[0].operands.windows,
                         (s.WindowOperand("inv_windowsA01", 3, "compatible"),))
        # Hand-supplied gate inputs are controls, not gate-evidence production.
        gates = tuple(s.GateResult(reused.context, g, "satisfied", (st.REF,)) for g in reused.profile.conjunctive_gates)
        self.assertEqual(self.evaluate(b, before.rules, gates).state, "satisfied")
        self.assertEqual(self.evaluate(b, before.rules, tuple(replace(g, context=before.context) for g in gates)).state, "unknown")

    def test_control_new_families_at_admission(self):
        doc = am.contract_doc(3, 2, edit=lambda d: self.declaration(d, ["inv_windowsA01"], 2))
        self.assertEqual(self.router.propose_amendment({"document": doc})["status"], "recorded")
        self.assertEqual(self.approve(doc)["status"], "applied")
