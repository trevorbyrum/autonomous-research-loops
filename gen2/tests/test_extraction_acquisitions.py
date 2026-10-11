"""Trusted acquired input through Router; pending extraction has no authority."""
import json
import unittest

from gen2.tests.test_canonical_content_tiers import FULL, fixture, document
from gen2.tests.test_canonical_receipt_admission import ReceiptCase
from gen2.tests.test_pending_extraction_support import METHODS
from gen2.tests.router_fixtures import empty_outcome


def send(case, doc):
    case.env = case.envelope(case.verifier, "op_verify001",
        {**empty_outcome(case.verifier["invocation_id"], "interim_transition"), "verification_receipts": [doc]})
    return case.router.commit_outcome(case.env)


def extraction_document(case, method):
    doc = document(case, "bibliographic")
    doc["extraction"].update(method=method,
        produced_by_invocation_id=case.verifier["invocation_id"] if method == "verifier_extraction" else case.ACQUIRER,
        validation_ref="validation_unrecorded" if method == "validated_extraction" else None)
    doc["verifier_invocation_id"] = case.verifier["invocation_id"]
    doc["verifier_capability_id"] = case.verifier["capability_id"]
    return doc


class ExtractionRouterTest(unittest.TestCase):
    def refuse(self, case, doc):
        before = case.state()
        out = send(case, doc)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertIn("extraction receipt must consume its admitted acquisition", out["detail"])
        self.assertEqual(case.state(), before)

    def test_missing(self):
        for method in METHODS:
            with self.subTest(method=method):
                case = ReceiptCase()
                case.setUp()
                try:
                    self.refuse(case, extraction_document(case, method))
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
                        doc = extraction_document(case, method)
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
                self.assertEqual(case.rows("SELECT count(*) FROM holds"), [(1,)])
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
