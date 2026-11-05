"""F1/V-3/V-4: retained adapter output through acquisition and abstract support.

The paired gateway test binds these bytes to actual offline adapter output.
This proves content-shape/lineage consistency, not live availability, scientific
support, trusted capture provenance or durable Router admission.
"""
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from gen2.core import canonical
from gen2.router import reaccess, support
from gen2.router.boundary import Refusal

KINDS = ("numeric_units", "denominators", "negation", "qualifications")


class Rows:
    def __init__(self, **tables):
        self.tables = tables

    def select(self, table, where=None):
        return [row for row in self.tables.get(table, []) if all(row.get(k) == v for k, v in (where or {}).items())]


class AbstractSupportWitness(unittest.TestCase):
    def operands(self, content):
        fixture = Path(__file__).parent / "fixtures/gateway_answers/semanticscholar_abstract.json"
        body = json.loads(fixture.read_bytes())["gateway_response"]
        if content == "missing":
            body["records"][0].pop("abstract")
        elif content == "blank":
            body["records"][0]["abstract"] = " \t\n"
        raw = canonical.canonical_bytes(body)
        digest = canonical.bytes_digest(raw)
        topic, work, verifier = "fleet-a:t1", "wrk_abstract01", "inv_verify0001"
        identity = body["records"][0]["identity"]
        request = {"lane": "semanticscholar", "page": 1, "request": {"request_type": "find", "query": "abstract fixture"}}
        source = dict(topic_id=topic, work_id=work, source_version="v1", content_hash=digest)
        observation = dict(observation_id="obs_abstract01", topic_id=topic, invocation_id="inv_producer01", attempt=1,
            gateway_call_ref="gw-call:101", coverage_state="searched_ok", completeness="complete", lane="semanticscholar",
            request=request, request_identity=canonical.logical_hash(request))
        acquired = reaccess.check_reaccess(source=source, artifact=dict(content_hash=digest, size_bytes=len(raw), media_type="application/json"),
            observation=observation, event=dict(event_id="rev_abstract01", observation_id="obs_abstract01", topic_id=topic,
            provider_record_id=identity, captured_at="2026-11-05T00:00:00Z"), link=dict(event_id="rev_abstract01", work_id=work), raw=raw)
        acquisition = {**asdict(acquired), "verifier_invocation_id": verifier, "response_bytes": raw}
        spans = [{"start": 0, "end": 5}]
        doc = dict(receipt_version="verification-receipt/2", topic_id=topic, verdict="supports", claim=dict(claim_id="clm_abstract01", claim_revision=1),
            source=dict(work_id=work, source_version="v1"), cited_spans=spans, obtained_content_hash=digest,
            verifier_invocation_id=verifier, quote_check_id=None, requested_for=dict(use="load_bearing", required_access_tier="abstract"),
            acquisition=dict(gateway_call_ref=acquired.gateway_call_ref, retrieved_at=acquired.retrieved_at, route="gateway:semanticscholar"),
            extraction=dict(method="canonical_bytes", produced_by_invocation_id=acquired.acquired_by_invocation_id, validation_ref=None),
            checks={kind: "checked_ok" for kind in KINDS},
            detailed_checks={kind: dict(outcome="succeeded", record_id="chk_" + kind) for kind in KINDS})
        receipt = dict(topic_id=topic, claim_id="clm_abstract01", claim_revision=1, work_id=work, source_version="v1",
            verdict="supports", use="load_bearing", required_access_tier="abstract", access_tier="abstract", receipt=doc,
            cited_spans=spans, verifier_invocation_id=verifier, quote_check_id=None, obtained_content_hash=digest,
            acquisition=doc["acquisition"], extraction_method="canonical_bytes", extraction_invocation_id=acquired.acquired_by_invocation_id,
            extraction_validation_ref=None)
        checks = [dict(check_id="chk_" + kind, topic_id=topic, performer_invocation_id=verifier,
            assessment={**doc["claim"], **doc["source"], "kind": kind, "outcome": "succeeded", "cited_spans": spans,
                        "source_artifact_hash": digest, "examined_artifact_ref": {"content_hash": digest}}) for kind in KINDS]
        rows = Rows(source_acquisitions=[acquisition], search_observations=[observation], source_artifacts=[source],
                    verification_receipts=[receipt], detailed_check_records=checks)
        claim = dict(claim_id="clm_abstract01", revision=1, load_bearing=True, required_access_tier="abstract")
        return rows, acquisition, claim

    def test_adapter_abstract_qualifies_but_missing_or_blank_cannot(self):
        for content, rank in (("retained", 2), ("missing", 1), ("blank", 1)):
            with self.subTest(content=content):
                rows, acquired, claim = self.operands(content)
                self.assertEqual(support.content_rank(rows, acquired), rank)
                capture_valid = lambda doc: doc["obtained_content_hash"] == canonical.bytes_digest(acquired["response_bytes"])
                if rank == 2:
                    self.assertIsNone(support.require_support(rows, claim, capture_valid))
                else:
                    with self.assertRaisesRegex(Refusal, "performed detailed checks"):
                        support.require_support(rows, claim, capture_valid)
