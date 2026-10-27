"""G-11 boundary and binding oracles, written by hand; in-memory stores only."""
import copy
import unittest
from dataclasses import replace

from gen2.accounting import stopping as s
from gen2.core import canonical
from gen2.tests import router_fixtures as am, test_stopping as st
from gen2.tests.router_fixtures import RouterTestCase

REF = {"content_hash": "sha256:" + "b" * 64, "size_bytes": 2048, "media_type": "application/json"}


def rule(family="known_item", tests="retrieval", mode="automatic"):
    params = {
        "known_item": {"sentinel_set": copy.deepcopy(REF), "tests": tests, "seeded_into_prompts": False},
        "statistical_target_recall": {"finite_pool": "retained finite pool", "screening_procedure": "declared random screening",
            "target_recall": 0.95, "confidence_level": 0.95, "method": "callaghan-mueller-hansen-2020"},
        "diminishing_returns": {"unit": "assessed_candidate", "min_assessed_per_window": 20, "consecutive_windows": 2, "max_new_fraction": 0.05},
        "counterevidence_pass": {"scope": "both", "min_completed_requests": 3},
    }.get(family, {})
    return {"rule_id": "R-check", "family": family, "evaluation": mode, "params": params}


UNSUPPORTED = tuple(rule(f) for f in ("capture_recapture", "voi_evpi", "safe", "code_meaning_saturation",
                                     "statistical_target_recall", "diminishing_returns", "counterevidence_pass", "unrecognized")) + (
    rule(tests="screening"), rule(tests="both"))


def set_rules(doc, rules):
    profile = doc["stopping_profiles"][0]
    profile["rules"] = copy.deepcopy(rules)
    profile["completion_condition"] = {"op": "all", "operands": [{"rule": r["rule_id"]} for r in rules]}


class AdmissionTest(RouterTestCase):
    def setUp(self):
        super().setUp()
        self.to_scoping()
        self.scope_seeded()

    def draft(self, rules):
        doc = am.contract_doc(1, None, rated=False, edit=lambda d: set_rules(d, rules))
        return self.router.draft_contract({"document": doc})

    def test_each_unsupported_rule_at_admission(self):
        for r in UNSUPPORTED:
            with self.subTest(family=r["family"], params=r["params"]):
                before = self.state()
                out = self.draft([r])
                self.assertEqual(out["status"], "refused", out)
                self.assertIn("R-check", out["detail"])
                self.assertIn(r["family"], out["detail"])
                self.assertEqual(self.state(), before)

    def test_control_supported_admission(self):
        self.assertEqual(self.draft([rule()])["status"], "recorded")

    def test_control_reviewed_admission(self):
        rules = [rule(f, mode="reviewed_judgment") for f in ("capture_recapture", "voi_evpi", "safe", "code_meaning_saturation")]
        for i, r in enumerate(rules): r["rule_id"] = f"R-review-{i}"
        self.assertEqual(self.draft(rules)["status"], "recorded")


class ApprovalTest(am.ContractWorld):
    def legacy_draft(self, r, edit_profile=None):
        # A previously admitted revision, seeded outside today's admission.
        doc = am.contract_doc(3, 2, edit=lambda d: set_rules(d, [r]))
        if edit_profile is not None:
            edit_profile(doc["stopping_profiles"][0])
        doc["protocol_revision"] = 2
        doc["content_hash"] = canonical.content_hash(doc)
        self.store_draft(doc)
        return doc

    def test_each_unsupported_rule_at_approval(self):
        for r in UNSUPPORTED:
            with self.subTest(family=r["family"], params=r["params"]):
                self.tearDown()
                self.setUp()  # Each case has its own in-memory history.
                doc = self.legacy_draft(r)
                before = self.state()
                out = self.approve(doc)
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"), out)
                self.assertIn("R-check", out["detail"])
                self.assertIn(r["family"], out["detail"])
                self.assertEqual(self.state(), before)

    def test_control_supported_approval(self):
        doc = self.propose(3, edit=lambda d: (set_rules(d, [rule()]), d.update(protocol_revision=2)))
        self.assertEqual(self.approve(doc)["status"], "applied")

    def test_invalid_profile_at_approval(self):
        doc = self.legacy_draft(rule(), lambda p: p.update(conjunctive_gates=[]))
        before = self.state()
        out = self.approve(doc)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"))
        self.assertIn("stopping profile", out["detail"])
        self.assertEqual(self.state(), before)

    def test_each_unsupported_rule_in_an_amendment(self):
        for r in UNSUPPORTED:
            with self.subTest(family=r["family"], params=r["params"]):
                doc = am.contract_doc(3, 2, edit=lambda d: (set_rules(d, [r]), d.update(protocol_revision=2)))
                before = self.state()
                out = self.router.propose_amendment({"document": doc})
                self.assertEqual(out["status"], "refused", out)
                self.assertIn(r["family"], out["detail"])
                self.assertEqual(self.state(), before)


class BindingTest(unittest.TestCase):
    def test_control_retrieval_binding(self):
        doc = am.contract_doc(1, None, rated=False, edit=lambda d: set_rules(d, [rule()]))
        bound = s.bind_profile(doc["stopping_profiles"][0])
        self.assertEqual(bound.profile, s.Profile("SP-effect", s.Expression(op="all", operands=(s.Expression("R-check"),)),
            ("challenge_pass_completed", "coverage_integrity", "load_bearing_verification_tiers")))
        binding = bound.rules[0]
        self.assertEqual((binding.family, binding.evaluator, binding.params, binding.prerequisites), ("known_item", "known_item", rule()["params"], ()))
        declared = s.KnownItems(st.a.EvidenceReference(**REF), frozenset({"w1"}))
        result = s.evaluate_binding(binding, st.CTX, st.inventory(), declared)
        self.assertEqual((result.rule_id, result.context, result.state, result.operands.declared), ("R-check", st.CTX, "satisfied", declared))
        missing = s.evaluate_binding(binding, st.CTX, st.inventory(), replace(declared, work_ids=frozenset({"w2"})))
        self.assertEqual((missing.state, missing.operands.found, missing.operands.missing), ("not_satisfied", frozenset(), frozenset({"w2"})))

    def test_every_unsupported_binding(self):
        for r in UNSUPPORTED:
            with self.subTest(family=r["family"], params=r["params"]), self.assertRaisesRegex(ValueError, "R-check"):
                s.bind_rule(r)
        with self.assertRaisesRegex(ValueError, "unknown family"):
            s.bind_rule(rule("unrecognized", mode="reviewed_judgment"))
        with self.assertRaisesRegex(ValueError, "unknown evaluation mode"):
            s.bind_rule(rule(mode="future"))

    def test_control_reviewed_binding(self):
        r = rule("statistical_target_recall", mode="reviewed_judgment")
        r["prerequisites"] = ["independently reviewed pool"]
        binding = s.bind_rule(r)
        self.assertEqual((binding.evaluator, binding.params, binding.prerequisites), (None, r["params"], ("independently reviewed pool",)))
        r["params"]["finite_pool"] = "changed"
        self.assertEqual(binding.params["finite_pool"], "retained finite pool")

    def test_expression_and_parameters_are_retained(self):
        doc = am.contract_doc(1, None, rated=False)
        profile = doc["stopping_profiles"][0]
        bound = s.bind_profile(profile)
        expected = s.Expression(op="all", operands=(s.Expression("R-counter"),
            s.Expression(op="any", operands=(s.Expression("R-dr"), s.Expression("R-meaning"))), s.Expression("R-known")))
        self.assertEqual(bound.profile.completion_condition, expected)
        self.assertEqual(tuple(r.params for r in bound.rules), tuple(r["params"] for r in profile["rules"]))

    def test_inventory_reference_and_reviewed_execution_are_refused(self):
        binding = s.bind_rule(rule())
        for reference in (replace(st.a.EvidenceReference(**REF), content_hash="sha256:" + "c" * 64), replace(st.a.EvidenceReference(**REF), size_bytes=2049),
                          replace(st.a.EvidenceReference(**REF), media_type="text/plain")):
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, "declared reference"):
                s.evaluate_binding(binding, st.CTX, st.inventory(), s.KnownItems(reference, frozenset({"w1"})))
        with self.assertRaisesRegex(ValueError, "no automatic evaluator"):
            s.evaluate_binding(s.bind_rule(rule(mode="reviewed_judgment")), st.CTX, st.inventory(),
                               s.KnownItems(st.a.EvidenceReference(**REF), frozenset({"w1"})))
