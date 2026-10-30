"""2c-4a part 1: literal scheme/impact oracles; in-memory Router worlds only.

These test declarations and approval, not obligation judgment production or
confidence admission (the remaining reconciliation slice and 2d/2e).
"""
import copy
import json
import unittest

from gen2.core import canonical
from gen2.router import amendments
from gen2.tests import router_fixtures as am
from gen2.tests.router_fixtures import RouterTestCase

# Example only: no production module defines a scale.
SCHEME = {"scheme_id": "plan-corroboration", "version": 1, "labels": {
    "corroborated": "Independent retained evidence agrees within the declared scope.",
    "tentative": "Retained evidence is relevant but material limitations remain."}}


def declare(doc):
    doc.update(confidence_scheme=copy.deepcopy(SCHEME), protocol_revision=2)


class SchemeAdmissionTest(RouterTestCase):
    def setUp(self):
        super().setUp()
        self.to_scoping()
        self.scope_seeded()

    def test_control_first_declaration(self):
        doc = am.contract_doc(1, None, rated=False, edit=declare)
        self.assertEqual(self.router.draft_contract({"document": doc})["status"], "recorded")
        stored = json.loads(self.value("SELECT document FROM contract_revisions WHERE revision = 1"))
        self.assertEqual(stored["confidence_scheme"], SCHEME)
        self.assertEqual(stored, doc)

    def test_invalid_declaration_leaves_no_writes(self):
        for scheme in ({**SCHEME, "probability": 0.9}, {**SCHEME, "labels": {}}, {**SCHEME, "labels": {"tentative": 0.5}}):
            doc = am.contract_doc(1, None, rated=False, edit=lambda d: d.update(confidence_scheme=scheme))
            before = self.state()
            self.assertEqual(self.router.draft_contract({"document": doc})["status"], "refused")
            self.assertEqual(self.state(), before)

    def test_scheme_is_in_the_contract_hash(self):
        doc = am.contract_doc(1, None, rated=False, edit=declare)
        original_hash = doc["content_hash"]
        doc["confidence_scheme"]["labels"]["tentative"] = "Changed rubric after hashing."
        self.assertNotEqual(canonical.content_hash(doc), original_hash)
        before = self.state()
        out = self.router.draft_contract({"document": doc})
        self.assertEqual((out["status"], out.get("reason")), ("refused", "request_invalid"))
        self.assertIn("does not hash", out["detail"])
        self.assertEqual(self.state(), before)


class SchemeImpactTest(am.ContractWorld):
    def install(self):
        doc = self.propose(3, declare)
        self.assertEqual(self.approve(doc)["status"], "applied")
        return doc

    def test_addition_records_g1_impact(self):
        doc = self.install()
        self.assertEqual(json.loads(self.value("SELECT document FROM contract_revisions WHERE revision = 3")), doc)
        impact = self.impact("opd_amend0003")
        self.assertEqual(impact["classification"], "protocol_changed")
        self.assertEqual(impact["standing"], [{"revision": 2, "classification": "protocol_changed"}])

    def test_control_unchanged_scheme(self):
        self.install()
        def edit(doc):
            declare(doc)
            am.compatible(doc)
        doc = self.propose(4, edit)
        self.assertEqual(self.approve(doc)["status"], "applied")
        self.assertEqual(self.impact("opd_amend0004")["classification"], "compatible")
        self.assertEqual(doc["confidence_scheme"], SCHEME)

    def test_scheme_change_requires_new_protocol_revision(self):
        self.install()
        doc = am.contract_doc(4, 3, edit=declare)
        doc["confidence_scheme"]["labels"]["tentative"] = "A revised plan-specific rubric."
        doc["content_hash"] = canonical.content_hash(doc)
        self.refused_command("propose_amendment", {"document": doc}, "request_invalid", "changed protocol takes a new protocol revision")

    def test_rubric_change_records_impact_and_retains_both_definitions(self):
        old = self.install()
        def edit(doc):
            declare(doc)
            doc["protocol_revision"] = 3
            doc["confidence_scheme"]["version"] = 2
            doc["confidence_scheme"]["labels"]["tentative"] = "A revised plan-specific rubric."
        new = self.propose(4, edit)
        self.assertEqual(self.approve(new)["status"], "applied")
        impact = self.impact("opd_amend0004")
        self.assertEqual((impact["classification"], impact["standing"]),
                         ("protocol_changed", [{"revision": 3, "classification": "protocol_changed"}]))
        self.assertEqual(json.loads(self.value("SELECT document FROM contract_revisions WHERE revision = 3")), old)
        self.assertEqual(json.loads(self.value("SELECT document FROM contract_revisions WHERE revision = 4")), new)
        self.assertNotEqual(old["content_hash"], new["content_hash"])

    def test_approval_names_exact_scheme_hash(self):
        doc = self.propose(3, declare)
        wrong = copy.deepcopy(doc)
        wrong["confidence_scheme"]["labels"]["tentative"] = "Another rubric."
        wrong["content_hash"] = canonical.content_hash(wrong)
        before = self.state()
        out = self.approve(wrong)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"))
        self.assertEqual(self.state(), before)
        self.assertEqual(self.approve(doc, did="opd_exact0003")["status"], "applied")


class SchemeClassificationTest(unittest.TestCase):
    def test_control_unchanged_scheme(self):
        old = am.contract_doc(1, None, edit=declare)
        current = copy.deepcopy(old)
        am.compatible(current)
        self.assertEqual(amendments.contract_compatibility(old, current), "compatible")

    def test_every_scheme_change_is_protocol_content(self):
        old = am.contract_doc(1, None, edit=declare)
        changes = ({**SCHEME, "scheme_id": "another-plan"}, {**SCHEME, "version": 2},
                   {**SCHEME, "labels": {"tentative": SCHEME["labels"]["tentative"]}},
                   {**SCHEME, "labels": {**SCHEME["labels"], "limited": "An additional rubric."}},
                   {**SCHEME, "labels": {**SCHEME["labels"], "tentative": "Changed rubric."}}, None)
        for scheme in changes:
            current = copy.deepcopy(old)
            if scheme is None:
                del current["confidence_scheme"]
            else:
                current["confidence_scheme"] = scheme
            with self.subTest(scheme=scheme):
                self.assertEqual(amendments.contract_compatibility(old, current), "protocol_changed")
                self.assertEqual(amendments.contract_compatibility(current, old), "protocol_changed")
