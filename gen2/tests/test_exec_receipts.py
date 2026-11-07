"""gen2/exec verify builder and the `verification/verify` recorder. Oracles: byte offsets found with bytes.find in the test (not the
builder's), the receipt, detailed-check and quote-check schemas (SchemaSet), and the router's `admitted`/`replayed` vocabulary for
the recorder. The router's own acceptance of these documents is tests/test_exec_receipts_commit.py. Limits: rows follow topic_records'
shape; the supervisor-filled `verifier_capability_id` is added by the tests where a schema needs it (the builder must not write it)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from gen2.app.support_gate import RouterSupport
from gen2.core import canonical
from gen2.exec import common, receipts, verify, verify_record
from gen2.router.schemas import SchemaSet
from gen2.tests.test_exec_research import ADMISSION, RAW, Reader, exchanges
from gen2.tests.test_exec_scope import Exchanges, lineage
from gen2.tests.test_exec_verify import DIGEST, claim, link, records

SCHEMAS = SchemaSet()
NORM = "quote-nfc-safe/2+ucd15.1.0"
OK = {"outcome": "succeeded", "note": "Checked against the abstract."}
NA = {"outcome": "not_applicable", "note": "Nothing of this kind is stated."}
CHECKS = {"numeric_units": NA, "denominators": NA, "negation": OK, "qualifications": OK}
QUOTE = {"quote": "abstract", "locator": "abstract"}


def stage(data, media):
    return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": media}


def work(recs=None, ex=None):
    recs = recs or records()
    view = verify.verify_view(ADMISSION, recs, RouterSupport, ex or exchanges(), lambda ref: "A claim.", "2026-11-05T12:00:00Z", [])
    return {"invocation_id": "inv_verify0001", "topic_id": "fleet:topic", "view": view}


def judgment(verdict="supports", spans=(QUOTE,), checks=CHECKS, ref="clm_00000001"):
    return {"judgment_version": "judgment-verify/1", "items": [{"claim_ref": ref, "verdict": verdict, "cited_spans": list(spans), "checks": copy.deepcopy(checks)}]}


def build(j=None, w=None, recs=None, ex=None):
    ex = ex or exchanges()
    set_aside = lambda digest: next(data for ref, data in ex.staged.values() if ref["content_hash"] == digest)   # what the driver sets aside in scratch
    return receipts.make_builder(stage, set_aside, normalization=NORM)(w or work(recs or records(), ex), j or judgment())


def with_capability(outcome):
    out = copy.deepcopy(outcome)
    for doc in out["verification_receipts"]:
        doc["verifier_capability_id"] = "cap_systemfilled"
    return out


class BuilderTest(unittest.TestCase):
    def test_a_supported_claim_gets_a_receipt_a_quote_check_and_four_attributed_checks(self):
        outcome = build()
        start = RAW.find(b"An abstract.") + len(b"An ")
        (doc,), (quote,), records_out = outcome["verification_receipts"], outcome["quote_checks"], outcome["detailed_check_records"]
        self.assertEqual((quote["span_start"], quote["span_end"], quote["quoted_text"]), (start, start + len(b"abstract"), "abstract"))
        self.assertEqual(RAW[quote["span_start"]:quote["span_end"]], b"abstract")
        self.assertEqual(doc["cited_spans"], [{"start": start, "end": start + 8, "locator": {"kind": "section", "value": "abstract"}}])
        self.assertEqual((doc["verdict"], doc["access_tier"], doc["quote_check_id"], doc["obtained_content_hash"]), ("supports", "abstract", quote["check_id"], DIGEST))
        self.assertEqual(doc["checks"]["exact_quote"], {"status": "matched", "normalization_version": NORM, "source_artifact_hash": DIGEST})
        self.assertEqual(doc["acquisition"], {"gateway_call_ref": "call-1", "retrieved_at": "2026-11-05T11:00:00Z", "route": "gateway:semanticscholar", "cache_reuse": True})
        self.assertEqual((doc["extraction"]["method"], doc["extraction"]["produced_by_invocation_id"], doc["producer_invocation_id"], doc["verifier_invocation_id"]),
                         ("canonical_bytes", "inv_discover1", "inv_producer01", "inv_verify0001"))
        self.assertEqual(len(records_out), 4)
        self.assertEqual({k: v["record_id"] for k, v in doc["detailed_checks"].items()}, {r["assessment"]["kind"]: r["check_id"] for r in records_out})
        for record in records_out:
            self.assertEqual(record["assessment"]["cited_spans"], doc["cited_spans"])
            self.assertEqual(record["evidence_ref"]["content_hash"], canonical.bytes_digest(canonical.canonical_bytes(record["assessment"])))
        self.assertNotIn("verifier_capability_id", doc, "bearer authority: the supervisor fills it, never the child")

    def test_every_document_is_schema_valid(self):
        outcome = with_capability(build())
        self.assertEqual(SCHEMAS.errors(outcome, "outcome-document.schema.json"), [])
        for record in outcome["detailed_check_records"]:
            self.assertEqual(SCHEMAS.errors(record, "detailed-check-record.schema.json"), [])

    def test_a_replay_builds_identical_bytes(self):
        self.assertEqual(common.outcome_bytes(build()), common.outcome_bytes(build()))

    def test_a_tier_shortfall_is_the_systems_finding_whatever_the_judgment_said(self):
        recs = records(claims=[claim(required_access_tier="full_text")])
        (doc,) = build(judgment("supports"), recs=recs)["verification_receipts"]
        outcome = build(judgment("supports"), recs=recs)
        self.assertEqual((doc["verdict"], doc["access_tier"], doc["requested_for"]["required_access_tier"]), ("cannot_assess_at_required_tier", "abstract", "full_text"))
        self.assertEqual((doc["quote_check_id"], doc["checks"]["exact_quote"]["status"], outcome["quote_checks"]), (None, "not_applicable", []))
        self.assertEqual(doc["cited_spans"][0]["start"], 0)
        self.assertEqual(doc["cited_spans"][0]["end"], len(RAW), "the span names the bytes that were examined")
        self.assertEqual(SCHEMAS.errors(with_capability(outcome), "outcome-document.schema.json"), [])

    def test_bibliographic_only_content_cannot_assess_an_abstract_tier_claim(self):
        data = canonical.canonical_bytes({"gateway_response": {"records": [{"identity": "doi:10.1/a"}]}})
        digest = canonical.bytes_digest(data)
        recs = records(claim_source_links=[link(source_version=digest)], source_artifacts=[{"work_id": "wrk_aaaaaaaa", "source_version": digest}])
        (doc,) = build(judgment("supports"), recs=recs, ex=exchanges(data))["verification_receipts"]
        self.assertEqual((doc["verdict"], doc["access_tier"]), ("cannot_assess_at_required_tier", "bibliographic"))

    def test_adverse_verdicts_may_carry_failed_unperformed_checks_and_no_quote(self):
        failed = {**CHECKS, "negation": {"outcome": "failed", "note": "The claim negates the abstract."}, "qualifications": {"outcome": "unavailable", "note": ""}}
        (doc,) = build(judgment("does_not_support", spans=(), checks=failed))["verification_receipts"]
        self.assertEqual((doc["verdict"], doc["checks"]["negation"], doc["checks"]["qualifications"], doc["quote_check_id"]), ("does_not_support", "checked_problem", "unavailable", None))
        self.assertNotIn("record_id", doc["detailed_checks"]["qualifications"])
        partial = {**CHECKS, "qualifications": {"outcome": "failed", "note": "The claim drops a qualifier."}}
        self.assertEqual(build(judgment("partially_supports", checks=partial))["verification_receipts"][0]["checks"]["qualifications"], "checked_problem")

    def test_refusals_leave_nothing_repaired(self):
        def swap(**over):
            return {**CHECKS, **over}
        cases = {"a claim not in the view": judgment(ref="clm_99999999"),
                 "judged twice": {**judgment(), "items": judgment()["items"] * 2},
                 "support with a failed check": judgment(checks=swap(negation={"outcome": "failed", "note": "no"})),
                 "support with an unperformed check": judgment(checks=swap(qualifications={"outcome": "not_checked", "note": ""})),
                 "partial support with an unavailable check": judgment("partially_supports", checks=swap(qualifications={"outcome": "unavailable", "note": ""})),
                 "support without a quote": judgment(spans=()),
                 "a quote that is not in the retained text": judgment(spans=({"quote": "not there", "locator": "abstract"},)),
                 "a performed check with a blank note": judgment(checks=swap(negation={"outcome": "succeeded", "note": " \t"}))}
        for name, j in cases.items():
            with self.subTest(name), self.assertRaises(common.Refused):
                build(j)

    def test_an_abstract_with_escapes_still_verifies_a_plain_quote_and_refuses_one_that_crosses_an_escape(self):
        text = 'A "quoted" abstract.\nSecond line with an effect.'
        data = canonical.canonical_bytes({"gateway_response": {"records": [{"identity": "doi:10.1/a", "abstract": text}]}})
        digest = canonical.bytes_digest(data)
        recs = records(claim_source_links=[link(source_version=digest)], source_artifacts=[{"work_id": "wrk_aaaaaaaa", "source_version": digest}])
        outcome = build(judgment(spans=({"quote": "an effect", "locator": "abstract"},)), recs=recs, ex=exchanges(data))
        (quote,) = outcome["quote_checks"]
        self.assertEqual(data[quote["span_start"]:quote["span_end"]], b"an effect")
        with self.assertRaises(common.Refused):
            build(judgment(spans=({"quote": '"quoted" abstract', "locator": "abstract"},)), recs=recs, ex=exchanges(data))


class Control:
    """The router's topic_records and admit_reaccess, as doubles."""
    def __init__(self, status="admitted", rows=None):
        self.status, self.asked, self.rows = status, [], rows or lineage()

    def topic_records(self, request):
        return {"status": "ok", "topic_id": request["topic_id"], "records": {f: self.rows[f] for f in request["families"]}}

    def admit_reaccess(self, request):
        self.asked.append(request)
        return {"status": self.status}


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.order = {"invocation_id": "inv_verify0001", "topic_id": "fleet:topic"}
        self.grant = {"capability_id": "cap_aaaaaaaa", "invocation_id": "inv_verify0001"}

    def put(self, outcome):
        (self.root / "outcome.json").write_bytes(canonical.canonical_bytes(outcome))

    def run_recorder(self, control, ex=None):
        verify_record.recorder(lambda topic: ex or exchanges())(control, self.order, self.grant, self.root)

    def test_each_receipt_admits_its_retained_exchange_and_a_repeat_replays(self):
        self.put(build())
        control = Control()
        self.run_recorder(control)
        self.run_recorder(Control("replayed"))
        self.assertEqual(control.asked, [{"capability_id": "cap_aaaaaaaa", "invocation_id": "inv_verify0001", "work_id": "wrk_aaaaaaaa", "source_version": DIGEST, "event_id": "e1"}])

    def test_refusals(self):
        good = build()
        moved = copy.deepcopy(good)
        moved["verification_receipts"][0]["acquisition"]["gateway_call_ref"] = "call-2"
        other = {**good, "invocation_id": "inv_other00001"}
        cases = {"the router does not accept the admission": (good, Control("refused"), None),
                 "the receipt rests on another call": (moved, Control(), None),
                 "the retained exchange is not staged": (good, Control(), Exchanges({})),
                 "the outcome is another invocation's": (other, Control(), None)}
        for name, (outcome, control, ex) in cases.items():
            with self.subTest(name):
                self.put(outcome)
                with self.assertRaises(common.Refused):
                    self.run_recorder(control, ex)

    def test_an_outcome_without_receipts_admits_nothing(self):
        self.put(common.scaffold("inv_verify0001", "fleet:topic"))
        control = Control()
        self.run_recorder(control)
        self.assertEqual(control.asked, [])
