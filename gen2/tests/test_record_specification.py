"""B1: one record specification drives common validation and admission.

A kind added to boundary.RECORDS alone must receive the pin/topic checks and
the admission check; an entry lacking its policy cannot be built. Fake rows
only; each refusal is asserted by its literal code and fragment, against an
admitted counterpart that differs only in the tested field.
"""
import contextlib
import unittest
from unittest import mock

from gen2.router import assessments, boundary
from gen2.router.assessments import Assessments
from gen2.router.boundary import Record, Refusal

INV = {"topic_id": "top_a", "contract_revision": 3, "invocation_id": "inv_1"}
CONTRACT = {"framing_version": 2, "document": {"eligibility_protocol": {"protocol_version": 5}}}
NEW = Record("new_assessments", "assessment_id", (), "", boundary.PRIMARY, boundary.CONTRACT, True)


class FakeCore:
    def _one(self, table, where):
        return CONTRACT if table == "contract_revisions" else None

    def _work_of_topic(self, work_id, topic_id):
        return work_id == "wrk_mine"


def record(**changes):
    return {"assessment_id": "new_1", "work_id": "wrk_mine", "contract_revision": 3, "framing_version": 2,
        "eligibility_protocol_version": 5, **changes}


class RecordSpecificationTest(unittest.TestCase):
    def table(self, spec):
        patched = (*boundary.RECORDS, spec)
        stack = contextlib.ExitStack()
        for module in (boundary, assessments):
            stack.enter_context(mock.patch.object(module, "RECORDS", patched))
        return stack

    def validate(self, rec, spec=NEW):
        with self.table(spec):
            Assessments(FakeCore()).validate({"new_assessments": [rec]}, INV)

    def admit(self, spec=NEW, kind="research_pass", context="contract/1"):
        with self.table(spec):
            boundary.check_sections({"new_assessments": [{}]}, kind, context, None)

    def refused(self, call, reason, fragment):
        with self.assertRaises(Refusal) as caught:
            call()
        self.assertEqual((caught.exception.reason, fragment in caught.exception.detail), (reason, True), caught.exception)

    def test_new_entry_receives_pin_and_topic_checks(self):
        self.validate(record())
        self.refused(lambda: self.validate(record(contract_revision=999)), "payload_invalid", "differs from the invocation's pins")
        self.refused(lambda: self.validate(record(work_id="wrk_foreign")), "cross_topic", "subject was not retrieved by this topic")

    def test_new_entry_receives_its_admission_check(self):
        self.admit()
        self.refused(lambda: self.admit(kind="delegate"), "kind_not_permitted", "a delegate invocation cannot commit new_assessments")
        self.refused(lambda: self.admit(context="pre-contract/1"), "kind_not_permitted", "scoping material only, not new_assessments")

    def test_entry_without_common_validation_is_explicit(self):
        # The same operands that the common check refuses pass when the entry says common=False.
        self.validate(record(contract_revision=999), NEW._replace(common=False))
        self.refused(lambda: self.validate(record(contract_revision=999)), "payload_invalid", "differs from the invocation's pins")

    def test_entry_missing_policy_cannot_be_built(self):
        for missing in ("kinds", "contexts", "common"):
            fields = {**NEW._asdict()}
            del fields[missing]
            with self.assertRaises(TypeError, msg=missing) as caught:
                Record(**fields)
            self.assertIn(missing, str(caught.exception))
        Record(**NEW._asdict())

    def test_every_record_section_is_admitted_by_its_entry(self):
        for spec in boundary.RECORDS:
            self.assertNotIn(spec.section, boundary.SECTION_KINDS)
            boundary.check_sections({spec.section: [{}]}, "research_pass", "contract/1", None)
            self.refused(lambda: boundary.check_sections({spec.section: [{}]}, "delegate", "contract/1", None),
                "kind_not_permitted", f"cannot commit {spec.section}")
