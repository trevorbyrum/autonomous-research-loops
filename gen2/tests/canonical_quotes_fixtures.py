"""Admitted canonical content for existing capture/promotion/attention controls."""
import json

from gen2.core import canonical
from gen2.core.gateway_capture import RetainedExchange
from gen2.tests.router_fixtures import find_request
from gen2.tests.test_governed_quotes import QuotesCase

STAMP = "2026-09-27T10:00:00Z"


class CanonicalQuotesCase(QuotesCase):
    # Exact quote offsets 2..17, plus a separately checked opening brace.
    SOURCE_BYTES = b'{"effect observed":0,"request_type":"find","observation":{"captured":true,"call_ref":1,"invocation_id":"inv_capture001","attempt":1},"lanes":[{"source":"crossref","coverage":"searched_ok","completeness":"complete","retrieved":["quote-record"]}],"records":[{"identity":"quote-record","kind":"full_text","text":"effect observed"}]}'
    SOURCE_MEDIA = "application/json"
    SPAN = (2, 17)

    def observe(self, grant, observation_id, records):
        request = find_request(observation_id)
        events = [{"event_id": f"rev_{observation_id[4:]}{n:02d}", "provider_record_id": record, "rank": n, "captured_at": STAMP}
            for n, record in enumerate(records, 1)]
        observation = {"observation_id": observation_id, "request": request, "request_identity": canonical.logical_hash(request),
            "attempt": 1, "lane": "crossref", "obligation_ids": ["O-1"], "started_at": STAMP, "ended_at": STAMP,
            "coverage_state": "searched_ok", "result_count": len(events), "completeness": "complete", "error_class": None,
            "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None, "gateway_call_ref": "gw-call:1",
            "page_outcome": "end_unknown", "continuation": None}
        out = self.router.record_observation({**{k: grant[k] for k in ("capability_id", "invocation_id")},
            "observation": observation, "retrieval_events": events})
        self.assertEqual(out["status"], "recorded", out)
        return [e["event_id"] for e in events]

    def read(self, **key):
        request = json.loads(self.value("SELECT request FROM search_observations WHERE observation_id = 'obs_quote00001'"))
        return RetainedExchange(self.grant["topic_id"], "inv_capture001", 1, "gw-call:1", canonical.canonical_bytes(request), self.SOURCE_BYTES)

    def setUp(self):
        super().setUp()
        self.router = self.make_router(gateway_captures=self)
        out = self.router.admit_reaccess({**{k: self.grant[k] for k in ("capability_id", "invocation_id")},
            "work_id": self.work, "source_version": "v1", "event_id": "rev_quote0000101"})
        self.assertEqual(out["status"], "admitted", out)

    def receipt_document(self, *args, **kwargs):
        doc = super().receipt_document(*args, **kwargs)
        doc["extraction"].update(method="canonical_bytes", produced_by_invocation_id="inv_capture001")
        doc["acquisition"].update(route="gateway:crossref", retrieved_at=STAMP, gateway_call_ref="gw-call:1")
        return doc
