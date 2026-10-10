"""Literal /2 oracles: fixture operands, never proof of admission/provenance."""
import copy
import json
import unittest
from dataclasses import replace

from gen2 import accounting as a
from gen2.accounting import reconciliation as r
from gen2.core import canonical
from gen2.router.schemas import SchemaSet
from gen2.tests import children
from gen2.tests.router_fixtures import EXAMPLES
from gen2.tests.test_reconciliation_operands import SCHEME

SCHEMA_PATH = EXAMPLES.parent / "export-bundle-v2.schema.json"  # mutation seam
DATE, LATER = "2026-10-10T00:00:00Z", "2026-10-10T00:00:01Z"
REF = a.EvidenceReference("sha256:" + "1" * 64, 19, "text/plain")
UNKNOWN = r.UnknownConfidence("unknown", "  Confidence judgment pending adjudication.  ")
RECORDED = r.RecordedConfidence("recorded_assessment", r.SchemePin("plan-corroboration", 1), "tentative", "inv_assess001")
EXPECTED = json.loads((EXAMPLES / "export-bundle-v2/valid-unresolved-contradiction.json").read_text())["instance"]
OUTCOMES = ("completed_with_qualified_conclusions", "stopped_for_resources", "capability_blocked", "awaiting_judgment", "retired")


def fixture():
    contract = json.loads((EXAMPLES / "contract-v2/valid-two-obligations.json").read_text())["instance"]
    contract["confidence_scheme"] = copy.deepcopy(SCHEME)
    contract["content_hash"] = canonical.content_hash(contract)
    base = r.ObligationAssessment("oba_fixture001", contract["topic_id"], "O-1", "Effect under the approved framing", 2,
        contract["content_hash"], 1, 1, (REF,), "primary", "inv_assess001", "op_assess0001", DATE,
        "Opposing estimates remain unadjudicated.", None, "unresolved", RECORDED)
    obligations = (
        replace(base, reason="Independent estimate supports the effect.", disposition="supported"),
        replace(base, record_id="oba_fixture002", reason="Counterestimate contradicts the effect.", disposition="contradicted", confidence=UNKNOWN),
        replace(base, record_id="oba_fixture003", reason="Opposing estimates remain unadjudicated.", confidence=UNKNOWN),
        replace(base, record_id="oba_fixture004", reason="Adjudication deferred pending the branch probe.", disposition="deferred", confidence=UNKNOWN, supersedes_id="oba_fixture003", created_at=LATER),
        r.OpenObligation("oba_fixture005", base.topic_id, "O-2", "Operator time remains unassessed", 2, base.contract_content_hash, 1, 1, (), "primary", "inv_assess001", "op_assess0001", DATE, "No obligation judgment has been recorded.", None, "open", UNKNOWN))
    semantic = a.SemanticAssessment("asm_fixture001", "wrk_fixture001", "v1", 2, 1, 1, "novel", "shared_origin", "applicable", "contradiction", (REF,), "primary", "inv_assess001", "op_assess0001", DATE)
    lineage = a.SourceLineage("asm_fixture001", "shared_study_origin", "study-A", None, None)
    lifecycle = a.SourceDisposition("sld_fixture001", "wrk_fixture001", "v1", 2, 1, 1, "add", None, None, None, "new", (REF,), "primary", "inv_assess001", "op_assess0001", DATE)
    unresolved = a.RegistryDisposition("rdp_history00", "contradiction", "C-1", "Opposing estimates in the retained evidence", "unresolved", 2, 1, 1, None, "conflicting_estimates", (REF,), "primary", "inv_assess001", "op_assess0001", DATE)
    competing = a.RegistryDisposition("rdp_history01", "contradiction", "C-1", "Opposing estimates in the retained evidence", "resolved", 2, 1, 1, None, "competing_resolution", (REF,), "primary", "inv_assess002", "op_assess0002", LATER)
    branch = a.RegistryDisposition("rdp_history02", "branch", "B-1", "Competing explanation probe", "park", 2, 1, 1, None, "probe_pending", (REF,), "primary", "inv_assess001", "op_assess0001", DATE)
    impact = a.AmendmentImpact("opd_amend0001", 2, (a.RevisionStanding(1, "protocol_changed"),), ("asm_excluded01",), DATE)
    operands = r.ReconciliationOperands(base.topic_id, obligations, (semantic,), (lineage,), (lifecycle,), (unresolved, competing, branch), 2, (impact,))
    fields = copy.deepcopy({k: v for k, v in EXPECTED.items() if k not in {"bundle_version", "topic_id", "obligations", "reconciliation_history"}})
    return operands, {2: contract}, fields


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.operands, self.contracts, self.fields = fixture()
        self.schemas = SchemaSet(extra={"export-bundle-v2.schema.json": json.loads(SCHEMA_PATH.read_text())})

    def test_exact_fixture_and_inverse(self):
        before = copy.deepcopy((self.operands, self.contracts, self.fields))
        bundle = r.to_bundle(self.operands, self.contracts, self.fields)
        self.assertEqual(bundle, EXPECTED)  # hand-written JSON, independent of either codec
        self.assertEqual(self.schemas.errors(bundle, "export-bundle-v2.schema.json"), [])
        restored, fields = r.from_bundle(json.loads(json.dumps(bundle)))
        self.assertEqual((restored, fields), (self.operands, self.fields))
        self.assertEqual(r.to_bundle(restored, self.contracts, fields), EXPECTED)
        inv = a.Inventory("native", registry_dispositions=restored.registry_dispositions, current_contract_revision=2)
        self.assertEqual(tuple(x.disposition for x in inv.registry_dispositions), ("unresolved", "resolved", "park"))
        self.assertEqual((self.operands, self.contracts, self.fields), before)
        fields["completion"]["outcome"] = "retired"
        bundle["reconciliation_history"]["amendment_impacts"][0]["standing"][0]["classification"] = "compatible"
        self.assertEqual(self.fields["completion"]["outcome"], "awaiting_judgment")
        self.assertEqual(restored.amendment_impacts[0].standing[0].classification, "protocol_changed")

    def test_control_supported(self):
        operands = replace(self.operands, obligations=self.operands.obligations[:1])
        bundle = r.to_bundle(operands, self.contracts, self.fields)
        self.assertEqual(bundle["obligations"], EXPECTED["obligations"][:1])
        self.assertEqual(r.from_bundle(bundle), (operands, self.fields))

    def test_control_absent_outcome(self):
        self.fields["completion"]["outcome"] = None
        self.assertIsNone(r.to_bundle(self.operands, self.contracts, self.fields)["completion"]["outcome"])

    def test_all_outcomes_independent(self):
        for status in ("completed", "not_completed"):
            for outcome in OUTCOMES:
                self.fields["completion"] = {"status": status, "outcome": outcome, "dossier_revision": 5,
                    "qualifications": {"framing": "Declared framing", "coverage": "Retained coverage", "discovery_mechanisms": "Declared lanes"}, "residual_uncertainty": "Competing estimates remain."}
                bundle = r.to_bundle(self.operands, self.contracts, self.fields)
                self.assertEqual(bundle["completion"], self.fields["completion"])
                self.assertEqual(self.schemas.errors(bundle, "export-bundle-v2.schema.json"), [])
                self.assertEqual(r.from_bundle(bundle)[1], self.fields)

    def test_mapper_guards(self):
        for confidence in (replace(RECORDED, label="borrowed"), replace(UNKNOWN, reason=" ")):
            with self.assertRaises(ValueError):
                r.to_bundle(replace(self.operands, obligations=(replace(self.operands.obligations[0], confidence=confidence),)), self.contracts, self.fields)
        with self.assertRaisesRegex(ValueError, "different topic"):
            r.to_bundle(replace(self.operands, topic_id="another-topic"), self.contracts, self.fields)
        with self.assertRaisesRegex(ValueError, "overlap"):
            r.to_bundle(self.operands, self.contracts, {**self.fields, "obligations": []})
        with self.assertRaisesRegex(ValueError, "export-bundle/2"):
            r.from_bundle({**EXPECTED, "bundle_version": "export-bundle/1"})
        with self.assertRaises(KeyError):
            r.to_bundle(self.operands, {}, self.fields)

    def test_schema_guards(self):
        for path, value in (((), {**EXPECTED, "invented": 1}), (("obligations", 0, "disposition"), "not_supported"),
            (("obligations", 4, "confidence"), {"basis": "recorded_assessment", "scheme": {"scheme_id": "plan-corroboration", "version": 1}, "label": "tentative", "assessed_by_invocation_id": "inv_assess001"}),
            (("obligations", 0, "confidence", "probability"), 0.9), (("reconciliation_history", "registry_dispositions", 0, "disposition"), "park")):
            bad = copy.deepcopy(EXPECTED)
            if path:
                node = bad
                for key in path[:-1]: node = node[key]
                node[path[-1]] = value
            else: bad = value
            self.assertTrue(self.schemas.errors(bad, "export-bundle-v2.schema.json"))
        for changes in ({"state": "open"}, {"disposition": "open"}):
            bad = copy.deepcopy(EXPECTED); bad["obligations"][0].update(changes)
            self.assertTrue(self.schemas.errors(bad, "export-bundle-v2.schema.json"))
        for field in ("invocation_id", "evidence_refs", "supersedes_id", "reason", "contract_content_hash"):
            bad = copy.deepcopy(EXPECTED); del bad["obligations"][0][field]
            self.assertTrue(self.schemas.errors(bad, "export-bundle-v2.schema.json"))
        paths = ((), ("completion",), ("obligations", 0), ("reconciliation_history",),
            *(("reconciliation_history", key, 0) for key in ("semantic_assessments", "source_lineage", "source_lifecycle", "registry_dispositions", "amendment_impacts")),
            ("reconciliation_history", "amendment_impacts", 0, "standing", 0))
        for path in paths:
            original = EXPECTED
            for key in path: original = original[key]
            for bad_value in ("not an object", {**original, "invented": 1},
                              *({k: v for k, v in original.items() if k != field} for field in original
                                if field not in {"disposition", "state"})):
                bad = copy.deepcopy(EXPECTED)
                parent = bad
                for key in path[:-1]: parent = parent[key]
                if path: parent[path[-1]] = bad_value
                else: bad = bad_value
                self.assertTrue(self.schemas.errors(bad, "export-bundle-v2.schema.json"), (path, bad_value))

    def test_v1_still_valid(self):
        for path in (EXAMPLES / "export-bundle").glob("valid-*.json"):
            document = json.loads(path.read_text())["instance"]
            self.assertEqual(self.schemas.errors(document, "export-bundle.schema.json"), [])

    def test_hypothesis_round_trip(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROPERTIES = '''
from hypothesis import given, settings, strategies as st
from dataclasses import replace
from gen2.tests.test_reconciliation_bundle import fixture, OUTCOMES
from gen2.accounting import reconciliation as r
@settings(max_examples=60, derandomize=True, database=None, deadline=None)
@given(st.lists(st.integers(0, 4), max_size=12), st.text(min_size=1).filter(lambda x: bool(x.strip())), st.permutations((0, 1, 2)), st.sampled_from(OUTCOMES), st.booleans(), st.integers(0, 63))
def law(indices, reason, order, outcome, completed, mask):
    operands, contracts, fields = fixture()
    records = tuple(replace(operands.obligations[i], reason=reason) for i in indices)
    operands = replace(operands, obligations=records, registry_dispositions=tuple(operands.registry_dispositions[i] for i in order))
    keys = ("semantic_assessments", "source_lineage", "source_lifecycle", "registry_dispositions", "amendment_impacts")
    operands = replace(operands, **{key: getattr(operands, key) if mask & (1 << index) else () for index, key in enumerate(keys)},
        current_contract_revision=2 if mask & 32 else None)
    fields["completion"] = {"status": "completed" if completed else "not_completed", "outcome": outcome, "dossier_revision": 5,
        "qualifications": {"framing": "F", "coverage": "C", "discovery_mechanisms": "D"}, "residual_uncertainty": reason}
    bundle = r.to_bundle(operands, contracts, fields)
    restored, metadata = r.from_bundle(bundle)
    assert (restored, metadata) == (operands, fields)
    assert r.to_bundle(restored, contracts, metadata) == bundle
law()
'''
