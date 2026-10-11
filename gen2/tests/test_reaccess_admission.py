"""Literal retained exchanges through Router; acquisition authority only."""
import json
import sqlite3
from dataclasses import replace

from gen2.core.gateway_capture import RetainedExchange
from gen2.tests.router_fixtures import TOPIC, OTHER, empty_outcome
from gen2.tests.test_reaccess import digest
from gen2.tests.test_router_workflow import Workflow, contract
from gen2.tests.test_router_amendments import protocol_changed

REQUEST = b'{"lane":"crossref","page":1,"request":{"query":"fixture","request_type":"find"}}'
RAW = b'{"request_type":"find","observation":{"captured":true,"call_ref":101,"invocation_id":"inv_capture001","attempt":1},"lanes":[{"source":"crossref","coverage":"searched_ok","completeness":"complete","retrieved":["doi:10.1/fixture"]}],"records":[{"identity":"doi:10.1/fixture","kind":"article","title":"Fixture","abstract":"An abstract"}]}'
STAMP = "2026-09-27T10:00:00Z"


def raw_acquisition(case, **changes):
    row = {"topic_id": TOPIC, "work_id": case.work, "source_version": "v1", "content_hash": digest(case.raw),
        "observation_id": "obs_capture001", "event_id": "rev_capture001", "gateway_call_ref": "gw-call:101",
        "acquired_by_invocation_id": case.ACQUIRER, "attempt": 1, "lane": "crossref", "request_type": "find",
        "provider_record_id": "doi:10.1/fixture", "retrieved_at": STAMP, "verifier_invocation_id": "inv_verify0001",
        "request_identity": digest(REQUEST), "request_bytes": REQUEST, "response_bytes": case.raw, "admitted_at": STAMP, **changes}
    case.x(f"INSERT INTO source_acquisitions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())


class AcquisitionCase(Workflow):
    ACQUIRER = "inv_capture001"
    EVENT_ID = "rev_capture001"

    def setUp(self):
        super().setUp()
        self.approved()
        self.producer = self.started("inv_capture001")
        self.acquirer = self.producer if self.ACQUIRER == "inv_capture001" else self.started(self.ACQUIRER, "checkpoint")
        self.raw = RAW.replace(b"inv_capture001", self.ACQUIRER.encode())
        obs = {"observation_id": "obs_capture001", "request": json.loads(REQUEST), "request_identity": digest(REQUEST),
            "attempt": 1, "lane": "crossref", "obligation_ids": ["O-1"], "started_at": STAMP, "ended_at": STAMP,
            "coverage_state": "searched_ok", "result_count": 1, "completeness": "complete", "error_class": None,
            "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None, "gateway_call_ref": "gw-call:101",
            "page_outcome": "end_unknown", "continuation": None}
        event = {"event_id": self.EVENT_ID, "provider_record_id": "doi:10.1/fixture", "rank": 1, "captured_at": STAMP}
        self.assertEqual(self.router.record_observation({**{k: self.acquirer[k] for k in ("capability_id", "invocation_id")},
            "observation": obs, "retrieval_events": [event]})["status"], "recorded")
        self.work = self.register(self.acquirer, [("doi", "10.1/fixture", [self.EVENT_ID])])["works"][0]["work_id"]
        self.source = self.artifact(self.raw, "application/json")
        payload = {**empty_outcome("inv_capture001", "interim_transition"),
            "source_artifacts": [{"work_id": self.work, "source_version": "v1", "artifact_ref": self.source}]}
        self.assertEqual(self.router.commit_outcome(self.envelope(self.producer, "op_capture001", payload, refs=[self.source]))["status"], "committed")
        self.verifier = self.started("inv_verify0001", "verification")
        self.exchange = RetainedExchange(TOPIC, self.ACQUIRER, 1, "gw-call:101", REQUEST, self.raw)
        self.reads, self.after_read = [], lambda: None
        self.router = self.make_router(gateway_captures=self)

    def read(self, **key):
        self.reads.append((key, self.db.in_transaction))
        self.after_read()
        return self.exchange

    def request(self, **changes):
        return {**{k: self.verifier[k] for k in ("capability_id", "invocation_id")},
            "work_id": self.work, "source_version": "v1", "event_id": self.EVENT_ID, **changes}

    def refuse(self, detail, reason="reaccess_invalid", **changes):
        before = self.state(exclude=())
        out = self.router.admit_reaccess(self.request(**changes))
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        self.assertIn(detail, out.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)


class AdmissionTest(AcquisitionCase):
    def test_control(self):
        self.assertEqual(self.router.admit_reaccess(self.request()), {"status": "admitted", "topic_id": TOPIC,
            "work_id": self.work, "source_version": "v1", "event_id": self.EVENT_ID, "verifier_invocation_id": "inv_verify0001"})
        self.assertEqual(self.rows("SELECT content_hash, observation_id, gateway_call_ref, acquired_by_invocation_id, attempt, lane, request_type, provider_record_id, retrieved_at, request_identity, request_bytes, response_bytes FROM source_acquisitions"),
            [(digest(self.raw), "obs_capture001", "gw-call:101", self.ACQUIRER, 1, "crossref", "find", "doi:10.1/fixture", STAMP, digest(REQUEST), REQUEST, self.raw)])
        self.assertEqual(self.reads, [({"topic_id": TOPIC, "invocation_id": self.ACQUIRER, "attempt": 1, "gateway_call_ref": "gw-call:101"}, False)])
        self.assertEqual(self.value("SELECT admitted_at FROM source_acquisitions"), self.value("SELECT at FROM audit_events WHERE kind = 'reaccess'"))
        self.assertEqual(json.loads(self.value("SELECT detail FROM audit_events WHERE kind = 'reaccess'")),
            {"topic_id": TOPIC, "work_id": self.work, "source_version": "v1", "event_id": self.EVENT_ID, "verifier_invocation_id": "inv_verify0001"})
        before = self.state(exclude=())
        self.assertEqual(self.router.admit_reaccess(self.request())["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)

    def test_missing_reader(self):
        self.router = self.make_router()
        self.refuse("trusted capture reader unavailable")

    def test_missing_capture(self):
        self.exchange = None
        self.refuse("trusted capture missing")

    def test_capture_attribution(self):
        original = self.exchange
        for field, value, detail in (("topic_id", OTHER, "topic"), ("invocation_id", "inv_forged001", "invocation"),
                ("attempt", 2, "attempt"), ("attempt", True, "attempt"), ("gateway_call_ref", "gw-call:102", "call")):
            with self.subTest(field=field):
                self.exchange = replace(original, **{field: value})
                self.refuse("trusted capture " + detail)

    def test_coherent_request_forgery(self):
        forged = REQUEST.replace(b"fixture", b"forgery")
        self.x("DROP TRIGGER search_observations_immutable_u")
        self.x("UPDATE search_observations SET request = ?, request_identity = ?", forged.decode(), digest(forged))
        self.refuse("trusted capture request")

    def test_response_binding(self):
        self.exchange = replace(self.exchange, response_bytes=self.raw.replace(b"Fixture", b"Forgery"))
        self.refuse("acquisition bytes digest")

    def test_summary_reuse(self):
        summary = b'{"summary":"producer-selected summary"}'
        ref = self.artifact(summary, "application/json")
        payload = {**empty_outcome("inv_capture001", "interim_transition"),
            "source_artifacts": [{"work_id": self.work, "source_version": "summary", "artifact_ref": ref}]}
        self.assertEqual(self.router.commit_outcome(self.envelope(self.producer, "op_summary001", payload, refs=[ref]))["status"], "committed")
        self.exchange = replace(self.exchange, response_bytes=summary)
        self.refuse("gateway capture missing", source_version="summary")

    def test_response_type(self):
        self.exchange = replace(self.exchange, response_bytes=bytearray(self.raw))
        self.refuse("trusted response bytes")

    def test_request_bytes(self):
        self.exchange = replace(self.exchange, request_bytes=bytearray(REQUEST))
        self.refuse("trusted request bytes")

    def test_authority(self):
        self.refuse("contract-admitted verifier required", **{k: self.producer[k] for k in ("capability_id", "invocation_id")})

    def test_fences(self):
        self.after_read = lambda: self.clock.set("2027-01-01T00:00:00Z")
        self.refuse("expired", "lease_not_current")

    def test_cancel_fence(self):
        self.after_read = lambda: self.router.request_cancel({"invocation_id": "inv_verify0001", "requested_by": "operator", "reason": "fixture"})
        out = self.router.admit_reaccess(self.request())
        self.assertEqual((out["status"], out.get("detail")), ("refused", "live verifier required"), out)
        self.assertEqual(self.rows("SELECT * FROM source_acquisitions"), [])

    def test_operand_fence(self):
        self.x("DROP TRIGGER source_artifacts_immutable_u")
        self.after_read = lambda: self.x("UPDATE source_artifacts SET created_at = '2026-09-28T00:00:00Z'")
        out = self.router.admit_reaccess(self.request())
        self.assertEqual((out["status"], out.get("detail")), ("refused", "acquisition operands changed"), out)
        self.assertEqual(self.rows("SELECT * FROM source_acquisitions"), [])

    def test_conflict(self):
        raw_acquisition(self, response_bytes=self.raw.replace(b"Fixture", b"Forgery"))
        self.refuse("acquisition replay conflict")

    def test_missing_operand(self):
        self.refuse("recorded acquisition operand missing: source_artifacts", source_version="absent")

    def test_paused(self):
        self.x("UPDATE queue_entries SET paused_at = ? WHERE topic_id = ?", STAMP, TOPIC)
        self.refuse("topic paused")

    def test_pins(self):
        doc = contract(3, 2, edit=protocol_changed)
        self.assertEqual(self.router.propose_amendment({"document": doc})["status"], "recorded")
        self.assertEqual(self.decide("opd_amend001", "amendment_approval", {"kind": "contract_revision", "revision": 3, "hash": doc["content_hash"]})["status"], "applied")
        # Isolate the pins check from approval's independent cancellation fence.
        self.x("DROP TRIGGER invocations_identity_immutable")
        self.x("UPDATE invocations SET cancel_requested_at = NULL, cancel_requested_by = NULL WHERE invocation_id = 'inv_verify0001'")
        self.refuse("superseded", "amendment_pending")

    def test_state(self):
        payload = empty_outcome("inv_verify0001")
        env = self.envelope(self.verifier, "op_unused001", payload)
        self.ready(self.verifier, env["payload_digest"])
        self.refuse("live verifier required")

    def test_capability(self):
        self.refuse("no invocation holds", "capability_invalid", capability_id="cap_forged001")

    def test_rollback(self):
        self.faults["reaccess_written"] = sqlite3.IntegrityError("fixture failure after acquisition insert")
        self.refuse("fixture failure after acquisition insert")

    def test_request_shape(self):
        self.refuse("", "request_invalid", response_bytes=self.raw.hex())


class OtherAcquirerTest(AcquisitionCase):
    ACQUIRER = "inv_other0001"
    EVENT_ID = "rev_other0001"
    test_control = AdmissionTest.test_control
