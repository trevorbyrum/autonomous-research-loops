"""Premise P7 (T15's first obligation): does a `canonical_bytes` receipt at abstract tier, over the exchange the DISCOVERY
JOB actually stages, reach `require_support`? Oracle: the production `reaccess.check_reaccess`, `support.content_rank` and
`support.require_support`, applied to bytes read back through `ExchangeIndex` (the production capture reader), for a record
taken from T12-G's adapter-shaped fixture, with the missing and blank abstract controls. Limits: the rows are the hand-built
operands of T12-G's witness (a real Router admitting the acquisition is the recorder's and the end-to-end run's); the staged
bytes are a canonical reconstruction of the client's parsed exchange, not transport octets."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from gen2.core import canonical
from gen2.discovery import exchanges, recorder
from gen2.router import reaccess, support
from gen2.router.boundary import Refusal
from gen2.supervisor.spool import Spool
from gen2.tests.test_discovery_child import INV, TOPIC, Fixture, Gateway, proposal
from gen2.tests.test_discovery_recorder import GRANT, ORDER, Control
from gen2.tests.test_discovery_stamp import observations, result_of

KINDS = ("numeric_units", "denominators", "negation", "qualifications")
ADAPTER = json.loads((Path(__file__).parent / "fixtures/gateway_answers/semanticscholar_abstract.json").read_bytes())["gateway_response"]["records"][0]


class Rows:
    def __init__(self, **tables):
        self.tables = tables

    def select(self, table, where=None):
        return [row for row in self.tables.get(table, []) if all(row.get(k) == v for k, v in (where or {}).items())]


class AdapterGateway(Gateway):
    def __init__(self, abstract, **kw):
        super().__init__(**kw)
        self.abstract = abstract

    def records(self, lane):
        record = dict(ADAPTER)
        if self.abstract == "missing":
            record.pop("abstract")
        elif self.abstract == "blank":
            record["abstract"] = " \t\n"
        return [record]


class P7Test(Fixture, unittest.TestCase):
    def operands(self, abstract):
        self.gateway = AdapterGateway(abstract)
        spool_dir = tempfile.TemporaryDirectory()
        self.addCleanup(spool_dir.cleanup)
        spool = Spool(spool_dir.name)
        self.run_child(self.stage([proposal(1, lane="semanticscholar", obligation_ids=[])]))
        log = []
        recorder.recorder(spool.stage)(Control(log), ORDER, GRANT, self.root)
        item = observations(result_of(self))[0]
        observation, event = item["observation"], item["retrieval_events"][0]
        found = exchanges.ExchangeIndex(spool, TOPIC, lambda: [self.root]).read(
            topic_id=TOPIC, invocation_id=INV, attempt=1, gateway_call_ref=observation["gateway_call_ref"])
        raw, digest = found.response_bytes, canonical.bytes_digest(found.response_bytes)
        topic, work, verifier = TOPIC, "wrk_abstract01", "inv_verify0001"
        source = dict(topic_id=topic, work_id=work, source_version="v1", content_hash=digest)
        row = {**observation, "topic_id": topic, "invocation_id": INV}
        acquired = reaccess.check_reaccess(
            source=source, artifact=dict(content_hash=digest, size_bytes=len(raw), media_type="application/json"), observation=row,
            event={**event, "topic_id": topic, "observation_id": observation["observation_id"]}, link=dict(event_id=event["event_id"], work_id=work), raw=raw)
        acquisition = {**asdict(acquired), "verifier_invocation_id": verifier, "response_bytes": raw}
        spans = [{"start": 0, "end": 5}]
        doc = dict(receipt_version="verification-receipt/2", topic_id=topic, verdict="supports", claim=dict(claim_id="clm_abstract01", claim_revision=1),
                   source=dict(work_id=work, source_version="v1"), cited_spans=spans, obtained_content_hash=digest, verifier_invocation_id=verifier,
                   quote_check_id=None, requested_for=dict(use="load_bearing", required_access_tier="abstract"),
                   acquisition=dict(gateway_call_ref=acquired.gateway_call_ref, retrieved_at=acquired.retrieved_at, route="gateway:semanticscholar"),
                   extraction=dict(method="canonical_bytes", produced_by_invocation_id=acquired.acquired_by_invocation_id, validation_ref=None),
                   checks={kind: "checked_ok" for kind in KINDS}, detailed_checks={kind: dict(outcome="succeeded", record_id="chk_" + kind) for kind in KINDS})
        receipt = dict(topic_id=topic, claim_id="clm_abstract01", claim_revision=1, work_id=work, source_version="v1", verdict="supports", use="load_bearing",
                       required_access_tier="abstract", access_tier="abstract", receipt=doc, cited_spans=spans, verifier_invocation_id=verifier,
                       quote_check_id=None, obtained_content_hash=digest, acquisition=doc["acquisition"], extraction_method="canonical_bytes",
                       extraction_invocation_id=acquired.acquired_by_invocation_id, extraction_validation_ref=None)
        checks = [dict(check_id="chk_" + kind, topic_id=topic, performer_invocation_id=verifier,
                       assessment={**doc["claim"], **doc["source"], "kind": kind, "outcome": "succeeded", "cited_spans": spans,
                                   "source_artifact_hash": digest, "examined_artifact_ref": {"content_hash": digest}}) for kind in KINDS]
        rows = Rows(source_acquisitions=[acquisition], search_observations=[row], source_artifacts=[source], verification_receipts=[receipt], detailed_check_records=checks)
        return rows, acquisition, dict(claim_id="clm_abstract01", revision=1, load_bearing=True, required_access_tier="abstract")

    def test_the_staged_adapter_abstract_qualifies_but_missing_or_blank_cannot(self):
        for abstract, rank in (("retained", 2), ("missing", 1), ("blank", 1)):
            with self.subTest(abstract):
                self.tearDown()
                self.setUp()
                rows, acquired, claim = self.operands(abstract)
                self.assertEqual(support.content_rank(rows, acquired), rank)
                valid = lambda doc: doc["obtained_content_hash"] == canonical.bytes_digest(acquired["response_bytes"])
                if rank == 2:
                    self.assertIsNone(support.require_support(rows, claim, valid))
                else:
                    with self.assertRaisesRegex(Refusal, "performed detailed checks"):
                        support.require_support(rows, claim, valid)
