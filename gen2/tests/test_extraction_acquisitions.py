"""Trusted acquired input through Router; pending extraction has no authority."""
import json
import unittest

from gen2.tests.router_fixtures import FULL, attributed_fixture as fixture
from gen2.tests.router_fixtures import AttributedReceiptCase
from gen2.tests.detailed_receipt_fixtures import attach_checks, historical_receipt
from gen2.tests.router_fixtures import EXTRACTION_METHODS as METHODS
from gen2.tests.router_fixtures import send, extraction_document


class ExtractionRouterTest(unittest.TestCase):
    def refuse(self, case, doc):
        historical_receipt(doc)  # /1 isolates the existing acquisition predicate.
        before = case.state()
        out = send(case, doc)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        detail = {"verifier_extraction": "receipt needs its verifier durable extraction",
            "validated_extraction": "receipt needs its successful durable /2 validation"}[doc["extraction"]["method"]]
        self.assertIn(detail, out["detail"])
        case.assert_audited_state(before, 1)

    def test_missing(self):
        for method in METHODS:
            with self.subTest(method=method):
                case = AttributedReceiptCase()
                case.setUp()
                try:
                    self.refuse(case, extraction_document(case, method, detailed=False))
                    case.admit()
                    self.assertEqual(send(case, extraction_document(case, method))["status"], "committed")
                finally:
                    case.tearDown()

    def test_selectors(self):
        for method in METHODS:
            for name in ("work", "version", "verifier", "hash", "call", "time", "route"):
                with self.subTest(method=method, selector=name), fixture(FULL) as case:
                    doc = extraction_document(case, method)
                    if name == "work":
                        events = case.observe(case.producer, "obs_otherwork1", ("other-record",))
                        work = case.register(case.producer, [("doi", "10.1/other", events)])["works"][0]["work_id"]
                        doc["source"]["work_id"] = work
                    elif name == "version":
                        doc["source"]["source_version"] = "v2"
                    elif name == "verifier":
                        self.assertEqual(case.finish(case.verifier, "op_oldver001")["status"], "committed")
                        case.verifier = case.started("inv_otherver1", "verification")
                        doc = extraction_document(case, method, detailed=False)
                    elif name == "hash":
                        doc["obtained_content_hash"] = case.artifact(b"Other input")["content_hash"]
                    else:
                        key, value = {"call": ("gateway_call_ref", "gw-call:102"), "time": ("retrieved_at", "2026-09-28T10:00:00Z"), "route": ("route", "gateway:core")}[name]
                        doc["acquisition"][key] = value
                    self.refuse(case, doc)
                    if name == "verifier":
                        case.admit()
                    self.assertEqual(send(case, extraction_document(case, method))["status"], "committed")

    def test_control_replay_rollback(self):
        for method in METHODS:
            with self.subTest(method=method), fixture(FULL) as case:
                doc = extraction_document(case, method)
                before = case.state(exclude=())
                case.faults["in_transaction:end"] = RuntimeError("after extraction input")
                with self.assertRaisesRegex(RuntimeError, "after extraction input"):
                    send(case, doc)
                self.assertEqual(case.state(exclude=()), before)
                case.faults.clear()
                out = send(case, doc)
                self.assertEqual(out["status"], "committed", out)
                self.assertEqual(json.loads(case.value("SELECT receipt FROM verification_receipts")), doc)
                self.assertEqual(case.rows("SELECT response_bytes FROM source_acquisitions"), [(case.raw,)])
                self.assertEqual(case.rows("SELECT count(*) FROM holds"), [(0,)])
                before = case.state(exclude=())
                self.assertEqual(case.router.commit_outcome(case.env), {"status": "replayed", "receipt": out["receipt"]})
                self.assertEqual(case.state(exclude=()), before)
                doc["acquisition"]["route"] = "gateway:core"
                self.assertEqual(send(case, doc)["reason"], "operation_id_conflict")

    def test_missing_content_hold(self):
        for method in METHODS:
            with self.subTest(method=method), fixture({"identity": FULL["identity"], "abstract": "Recorded abstract"}) as case:
                doc = extraction_document(case, method)
                doc.update(access_tier="abstract", verdict="cannot_assess_at_required_tier")
                doc["requested_for"]["required_access_tier"] = "full_text"
                out = send(case, doc)
                self.assertEqual(out["status"], "committed", out)
                self.assertEqual(case.rows("SELECT cause, recoverability, required_authority, owner, clears_when FROM holds"),
                    [("verification missing content: cannot_assess_at_required_tier", "needs_remediation", "primary", "primary:station-1", "independent verification with the required content")])
