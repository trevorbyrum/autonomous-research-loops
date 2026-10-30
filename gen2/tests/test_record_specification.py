"""B1: one record specification drives common validation, writing and admission.

A kind added to boundary.RECORDS alone must receive the pin/topic checks and
the admission check; an entry lacking its policy cannot be built. Fake rows
only. Every outcome is compared with a literal (admitted, or the refusal's code
and detail) against a counterpart that differs only in the tested field, so a
wrong behaviour is an assertion failure rather than an unhandled exception.
"""
import contextlib
import unittest
from unittest import mock

from gen2.router import assessments, boundary
from gen2.router.assessments import Assessments
from gen2.router.boundary import Record, Refusal

INV = {"topic_id": "top_a", "contract_revision": 3, "invocation_id": "inv_1"}
SCHEME = {"scheme_id": "s", "version": 1, "labels": ["ok"]}
CONTRACT = {"framing_version": 2, "content_hash": "sha256:c", "status": "approved", "approved_by_decision_id": "dec_1", "document": {"eligibility_protocol": {"protocol_version": 5}, "confidence_scheme": SCHEME}}
NEW = Record("new_assessments", "assessment_id", (), "", boundary.PRIMARY, boundary.CONTRACT, True, {})
PINS = {"contract_revision": 3, "framing_version": 2, "eligibility_protocol_version": 5}
PIN_REFUSAL = ("payload_invalid", "semantic assessment protocol/framing differs from the invocation's pins")
SUBJECT_REFUSAL = ("cross_topic", "semantic assessment subject was not retrieved by this topic")
RELATED_REFUSAL = ("cross_topic", "related lifecycle work was not retrieved by this topic")
OBLIGATION = {"record_id": "oa_1", "obligation_id": "ob_1", "supersedes_id": None, "disposition": "supported",
    "contract_content_hash": "sha256:c", "evidence_refs": [], **PINS}
RECORDED = {"basis": "recorded_assessment", "scheme": {"scheme_id": "s", "version": 1}, "label": "ok"}
UNKNOWN = {"basis": "unknown", "reason": "no access"}
LIFECYCLE = {"disposition_id": "sld_1", "work_id": "wrk_mine", "source_version": "v1", "supersedes_id": None,
    "related_work_id": None, "related_source_version": None, "action": "add", **PINS}


class FakeStore:
    def __init__(self):
        self.rows = []

    def insert(self, table, row):
        self.rows.append((table, row))


class FakeCore:
    def __init__(self):
        self._store = FakeStore()

    def _one(self, table, where):
        return {"contract_revisions": CONTRACT, "obligations": {},
            "registry_dispositions": {"topic_id": "top_a", "registry_kind": "branch", "registry_id": "br_1"},
            "invocations": {"topic_id": "top_a", "kind": "research_pass", "admission_context": "contract/1", "contract_revision": 3}}.get(table)

    def _work_of_topic(self, work_id, topic_id):
        return work_id == "wrk_mine"


def outcome(call):
    try:
        return call()
    except Refusal as refusal:
        return (refusal.reason, refusal.detail)
    except Exception as fault:  # a crash is a wrong outcome, not an unhandled test error
        return (type(fault).__name__, str(fault))


def table(spec):
    patched = (*boundary.RECORDS, spec)
    stack = contextlib.ExitStack()
    for module in (boundary, assessments):
        stack.enter_context(mock.patch.object(module, "RECORDS", patched))
    return stack


def validated(payload, spec=NEW):
    with table(spec):
        return outcome(lambda: Assessments(FakeCore()).validate(payload, INV))


def admitted(section, kind, context="contract/1", parent=None, spec=NEW):
    with table(spec):
        return outcome(lambda: boundary.check_sections({section: [{}]}, kind, context, parent))


def written(payload):
    core = FakeCore()
    result = outcome(lambda: Assessments(core).write(payload, INV, "op_1", "2026-10-30T00:00:00Z"))
    return result, [row for _, row in core._store.rows]


def new_record(**changes):
    return {"assessment_id": "new_1", "work_id": "wrk_mine", **PINS, **changes}


class RecordSpecificationTest(unittest.TestCase):
    def test_new_entry_receives_pin_and_topic_checks(self):
        self.assertEqual(validated({"new_assessments": [new_record()]}), None)
        self.assertEqual(validated({"new_assessments": [new_record(contract_revision=999)]}), PIN_REFUSAL)
        self.assertEqual(validated({"new_assessments": [new_record(work_id="wrk_foreign")]}), SUBJECT_REFUSAL)
        for pin in PINS:  # a record lacking a pin is refused, not a crash
            self.assertEqual(validated({"new_assessments": [{k: v for k, v in new_record().items() if k != pin}]}), PIN_REFUSAL, pin)

    def test_new_entry_receives_its_admission_check(self):
        self.assertEqual(admitted("new_assessments", "research_pass"), None)
        self.assertEqual(admitted("new_assessments", "delegate"), ("kind_not_permitted", "a delegate invocation cannot commit new_assessments"))
        self.assertEqual(admitted("new_assessments", "research_pass", "pre-contract/1"),
            ("kind_not_permitted", "pre-contract/1 work records scoping material only, not new_assessments (C-12)"))

    def test_entry_without_common_validation_is_explicit(self):
        bad = {"new_assessments": [new_record(contract_revision=999)]}
        self.assertEqual(validated(bad, NEW._replace(common=False)), None)
        self.assertEqual(validated(bad), PIN_REFUSAL)

    def test_branch_windows_validate_themselves_without_pins(self):
        window = {"association_id": "as_1", "branch_disposition_id": "dsp_1", "registry_id": "br_1", "window_invocation_id": "inv_w"}
        self.assertEqual(validated({"branch_windows": [window]}), None)
        self.assertEqual(validated({"branch_windows": [{**window, "registry_id": "br_2"}]}),
            ("payload_invalid", "association differs from its same-topic registered branch identity"))

    def test_entry_missing_policy_cannot_be_built(self):
        for missing in ("kinds", "contexts", "common", "defaults"):
            fields = {**NEW._asdict()}
            del fields[missing]
            with self.assertRaises(TypeError, msg=missing) as caught:
                Record(**fields)
            self.assertIn(missing, str(caught.exception))
        self.assertEqual(Record(**NEW._asdict()), NEW)

    def test_every_record_section_is_admitted_by_its_entry(self):
        for spec in boundary.RECORDS:
            self.assertNotIn(spec.section, boundary.SECTION_KINDS)
            self.assertEqual(admitted(spec.section, "research_pass"), None, spec.section)
            self.assertEqual(admitted(spec.section, "delegate"),
                ("kind_not_permitted", f"a delegate invocation cannot commit {spec.section}"), spec.section)


class WriteTest(unittest.TestCase):
    def test_recorded_confidence_is_attributed_and_unknown_is_not(self):
        _, rows = written({"obligation_assessments": [{**OBLIGATION, "confidence": RECORDED}]})
        self.assertEqual([r.get("confidence") for r in rows], [{**RECORDED, "assessed_by_invocation_id": "inv_1"}])
        _, rows = written({"obligation_assessments": [{**OBLIGATION, "confidence": UNKNOWN}]})
        self.assertEqual([r.get("confidence") for r in rows], [UNKNOWN])

    def test_record_defaults_fill_omitted_columns_only(self):
        _, rows = written({"obligation_assessments": [{**OBLIGATION, "confidence": RECORDED}]})
        self.assertEqual([(r.get("disposition"), r.get("state", "absent")) for r in rows], [("supported", None)])
        omitted = {k: v for k, v in OBLIGATION.items() if k != "disposition"}
        _, rows = written({"obligation_assessments": [{**omitted, "state": "open", "confidence": RECORDED}]})
        self.assertEqual([(r.get("disposition", "absent"), r.get("state")) for r in rows], [(None, "open")])

    def test_related_work_must_be_the_topics(self):
        result, rows = written({"source_lifecycle": [{**LIFECYCLE, "related_work_id": "wrk_mine"}]})
        self.assertEqual((result, [r.get("related_work_id") for r in rows]), ({"source_lifecycle": ["sld_1"]}, ["wrk_mine"]))
        result, rows = written({"source_lifecycle": [{**LIFECYCLE, "related_work_id": "wrk_foreign"}]})
        self.assertEqual((result, rows), (RELATED_REFUSAL, []))

    def test_written_names_only_sections_with_records(self):
        self.assertEqual(written({"source_lifecycle": [LIFECYCLE], "semantic_assessments": [], "obligation_assessments": []})[0],
            {"source_lifecycle": ["sld_1"]})
        self.assertEqual(written({})[0], {})


class AdmissionTest(unittest.TestCase):
    def test_only_listed_sections_need_independence(self):
        for section in ("detailed_check_records", "extraction_validations", "extraction_validations_v2"):
            self.assertEqual(admitted(section, "verification"), None, section)
            self.assertEqual(admitted(section, "verification", parent="inv_parent"),
                ("kind_not_permitted", f"{section} requires independent verification"), section)
        self.assertEqual(admitted("quote_checks", "verification", parent="inv_parent"), None)
        self.assertEqual(admitted("source_extractions", "verification", parent="inv_parent"), None)

    def test_only_listed_sections_accept_scoping_work(self):
        for section, kind in (("claims", "research_pass"), ("review_triggers", "checkpoint"), ("source_proposals", "delegate"), ("holds", "verification")):
            self.assertEqual(admitted(section, kind, "pre-contract/1"), None, section)
            self.assertEqual(admitted(section, kind), None, section)
        for section in ("claim_promotions", "claim_source_links", "decision_receipts", "screening_assessments", "exports", "source_artifacts"):
            self.assertEqual(admitted(section, "research_pass"), None, section)
            self.assertEqual(admitted(section, "research_pass", "pre-contract/1"),
                ("kind_not_permitted", f"pre-contract/1 work records scoping material only, not {section} (C-12)"), section)
        self.assertEqual(admitted("scoping_reports", "research_pass", "pre-contract/1"), None)
        self.assertEqual(admitted("scoping_reports", "research_pass"),
            ("kind_not_permitted", "scoping_reports are pre-contract work's (flow S2), not contract/1's"))
