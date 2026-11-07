"""The DEBT-051 proof: the verify builder's output commits through the REAL router only after the recorder admits re-access, and
the claim then promotes to accepted support. Oracle: the router and store (commit_outcome, admit_reaccess, promotion), with the
discovery job's own staging format (`exchanges.build`) as the retained bytes and the router's `gateway_captures` hook reading
them. Limits: the producer's claim and source rows are the router fixtures' (a real research pass is T18's); the supervisor's
fill of `verifier_capability_id` is done by the test, as the supervisor will; the exchange is a canonical reconstruction."""
import json
import tempfile
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.core.gateway_capture import RetainedExchange
from gen2.discovery import exchanges as staged_exchanges
from gen2.exec import receipts, verify_record
from gen2.router import quote_matching
from gen2.tests.router_fixtures import STAMP, TOPIC, QuotesCase, find_request

RECORD = "quote-record"
ABSTRACT = "effect observed"


def retained_bytes():
    """The discovery job's staged response for the fixture's one captured call, built by the production code."""
    request = find_request("obs_quote00001")
    observation = {"gateway_call_ref": "gw-call:1", "request": request, "lane": "crossref", "coverage_state": "searched_ok", "completeness": "complete"}
    out = {"pages": [{"page": 1, "sent": request["request"], "call_ref": 1, "effective_request": None}],
           "observations": [{"observation": observation, "retrieval_events": [{"provider_record_id": RECORD}], "records": []}],
           "records_by_call": {"gw-call:1": [{"identity": RECORD, "kind": "article", "abstract": ABSTRACT}]}}
    return staged_exchanges.build({"invocation_id": "inv_capture001", "attempt": 1, "searches": [{"proposal_id": "p1", "out": out}]})["gw-call:1"][1]


class Retained:
    """artifacts.Exchanges over the fixture's one staged response."""
    def __init__(self, case):
        self.case = case

    def response(self, call):
        return (self.case.source, self.case.SOURCE_BYTES) if call == "gw-call:1" else None


class CommitCase(QuotesCase):
    SOURCE_BYTES = retained_bytes()
    SOURCE_MEDIA = "application/json"

    def observe(self, grant, observation_id, records):
        request = find_request(observation_id)
        events = [{"event_id": f"rev_{observation_id[4:]}{n:02d}", "provider_record_id": record, "rank": n, "captured_at": STAMP} for n, record in enumerate(records, 1)]
        observation = {"observation_id": observation_id, "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1, "lane": "crossref",
                       "obligation_ids": ["O-1"], "started_at": STAMP, "ended_at": STAMP, "coverage_state": "searched_ok", "result_count": len(events),
                       "completeness": "complete", "error_class": None, "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None,
                       "gateway_call_ref": "gw-call:1", "page_outcome": "end_unknown", "continuation": None}
        out = self.router.record_observation({**{k: grant[k] for k in ("capability_id", "invocation_id")}, "observation": observation, "retrieval_events": events})
        self.assertEqual(out["status"], "recorded", out)
        return [e["event_id"] for e in events]

    def read(self, **key):
        request = json.loads(self.value("SELECT request FROM search_observations WHERE observation_id = 'obs_quote00001'"))
        return RetainedExchange(self.grant["topic_id"], "inv_capture001", 1, "gw-call:1", canonical.canonical_bytes(request), self.SOURCE_BYTES)

    def setUp(self):
        super().setUp()
        self.router = self.make_router(gateway_captures=self)
        self.text2 = self.artifact(ABSTRACT.encode())
        out = self.send([], grant=self.capture_grant, refs=[self.text2], claims=[{"claim_id": "clm_quote00001", "revision": 2, "text_ref": self.text2,
                                                                                     "load_bearing": True, "required_access_tier": "abstract"}])
        self.assertEqual(out["status"], "committed", out)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def outcome(self):
        """What the job writes: the builder over the real router's rows, then the supervisor's fill of the capability id."""
        events = self.router.topic_records({"topic_id": TOPIC, "families": ["retrieval_events"]})["records"]["retrieval_events"]
        view = {"as_of": "2026-09-27T10:00:00Z", "claims": [{"claim_ref": "clm_quote00001", "revision": 2, "tier": "abstract", "producer": "inv_capture001", "text": ABSTRACT,
                "sources": [{"work_id": self.work, "source_version": "v1", "content_hash": self.source["content_hash"], "identity": RECORD, "content_tier": "abstract",
                             "content": ABSTRACT, "acquisition": {"gateway_call_ref": "gw-call:1", "retrieved_at": events[0]["captured_at"], "route": "gateway:crossref"}}]}]}
        check = {"outcome": "succeeded", "note": "Checked against the abstract."}
        judgment = {"judgment_version": "judgment-verify/1", "items": [{"claim_ref": "clm_quote00001", "verdict": "supports",
                    "cited_spans": [{"quote": "observed", "locator": "abstract"}], "checks": {k: check for k in receipts.KINDS}}]}
        build = receipts.make_builder(self.router, Retained(self), lambda data, media: self.artifact(data, media), normalization="/".join(quote_matching.NORMALIZATION))
        outcome = build({"invocation_id": "inv_verify0001", "topic_id": TOPIC, "view": view}, judgment)
        for doc in outcome["verification_receipts"]:
            doc["verifier_capability_id"] = self.grant["capability_id"]
        return outcome

    def commit(self, outcome):
        refs = [r["evidence_ref"] for r in outcome["detailed_check_records"]] + [self.source]
        interim = {**outcome, "operation_kind": "interim_transition"}   # the fixture invocation is `running`; the supervisor commits the final outcome from `result_ready`
        return self.router.commit_outcome(self.envelope(self.grant, "op_t15verify01", interim, refs=refs))

    def record(self, outcome):
        (self.root / "outcome.json").write_bytes(canonical.canonical_bytes(outcome))
        verify_record.recorder(lambda topic: Retained(self))(self.router, {"invocation_id": "inv_verify0001", "topic_id": TOPIC}, self.grant, self.root)


class VerifyCommitTest(CommitCase):
    def test_with_the_recorder_the_receipt_commits_and_the_claim_promotes(self):
        outcome = self.outcome()
        self.record(outcome)
        self.record(outcome)   # a repeat replays
        self.assertEqual(self.rows("SELECT count(*) FROM source_acquisitions"), [(1,)])
        out = self.commit(outcome)
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT verdict, access_tier, extraction_method FROM verification_receipts"), [("supports", "abstract", "canonical_bytes")])
        self.assertEqual(self.rows("SELECT exact_match, quote_quarantined FROM quote_checks"), [("matched", 0)])
        self.assertEqual(self.value("SELECT count(*) FROM detailed_check_records"), 4)
        promoted = self.send([], grant=self.capture_grant, claim_promotions=[{"claim_id": "clm_quote00001", "revision": 2}])
        self.assertEqual(promoted["status"], "committed", promoted)
        self.assertEqual(self.value("SELECT status FROM claims WHERE claim_id = 'clm_quote00001' AND revision = 2"), "accepted_support")

    def test_without_the_recorder_the_receipt_commit_fails(self):
        before = self.state()
        out = self.commit(self.outcome())
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertIn("must consume its admitted acquisition", out["detail"])
        self.assert_audited_state(before, 1)
        self.assertEqual(self.value("SELECT count(*) FROM verification_receipts"), 0)
