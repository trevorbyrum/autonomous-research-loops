"""F5/v7 §2: literal audit readbacks and whole-store refusal/replay equality.

The bound reader is a trusted double: these tests prove Router admission and
charging, never runtime isolation, real enforcement or collector authenticity.
"""
import copy
import json
from unittest.mock import patch

from gen2.tests import router_fixtures as rf


class Authority:
    epoch = "epoch-1"
    current = True
    def admission(self, invocation_id, run_id, attempt):
        return self.admissions.get(invocation_id)
    def result(self, admission_ref, evidence_ref):
        return self.evidence
    def is_current(self, origin):
        return self.current


class DispatchTests(rf.RouterTestCase):
    refused = rf.ContractWorld.refused_command

    def setUp(self):
        super().setUp()
        self.authority = Authority()
        self.authority.admissions = {}
        self.router = self.make_router(dispatch_authority=self.authority)
        self.to_queued()
        self.to_queued(rf.OTHER)
        self.req = self.prepare("inv_dispatch01", rf.TOPIC)

    def prepare(self, iid, topic, upper=6, ceiling=10):
        grant = self.claim(iid, tid=topic)
        out = self.router.record_transition({**{k: grant[k] for k in ("capability_id", "invocation_id")},
            "to_state": "launching", "job_handle": "job-" + iid})
        self.assertEqual(out["status"], "recorded", out)
        manifest = self.artifact(b'{"profile":"fixture-only"}', "application/json")
        self.authority.admissions[iid] = {"origin": {"invocation_id": iid, "topic_id": topic,
            "config_bundle_hash": rf.CONFIG, "job_handle": "job-" + iid, "lease_id": grant["lease"]["lease_id"],
            "generation": grant["lease"]["generation"], "epoch": "epoch-1", "manifest_ref": manifest["content_hash"],
            "credential_ref": "dummy-seed-1", "route": "fixture", "backend": "fixture-docker", "evidence_generation": "generation-1"},
            "policy": {"run_id": "trial-1", "topic_id": topic, "accounting_owner": "operator", "deadline_at": rf.DEADLINE,
                "max_attempts": 3, "max_concurrent_attempts": 1, "ceiling_minor_units": ceiling, "currency": "USD",
                "ceiling_scope": ["model", "delegates", "retries", "verification", "gateway", "maintenance"], "policy_version": "v1"},
            "upper_minor_units": upper, "artifacts": [manifest]}
        return {**{k: grant[k] for k in ("capability_id", "invocation_id")}, "run_id": "trial-1", "attempt": 1}

    def authorize(self, req=None):
        out = self.router.authorize_dispatch(req or self.req)
        self.assertEqual(out["status"], "authorized", out)
        return out["admission_ref"]

    def result(self, ref, actual=2, ended=True):
        artifact = self.artifact(b'{"end":"authenticated-by-test-reader"}', "application/json")
        self.authority.evidence = {"origin": copy.deepcopy(self.authority.admissions[self.req["invocation_id"]]["origin"]),
            "admission_ref": ref, "evidence_ref": artifact["content_hash"], "artifacts": [artifact],
            "confirmed_end": ended, "actual_minor_units": actual}
        return {**self.req, "admission_ref": ref, "evidence_ref": artifact["content_hash"]}

    def launch(self, req):
        return self.router.invocation_status({k: req[k] for k in ("capability_id", "invocation_id")})["launch_admission"]

    def detail(self):
        return json.loads(self.value("SELECT detail FROM audit_events WHERE kind='dispatch_result'"))

    def test_serial_slot_replay_and_shared_headroom(self):
        """Unsent intent owns the slot; SQL charge and boundary equality are the oracle; no sends."""
        ref = self.authorize()
        before = self.state()
        self.assertEqual(self.router.authorize_dispatch(self.req)["admission_ref"], ref)
        self.assertEqual(self.state(), before)
        other = self.prepare("inv_dispatch02", rf.OTHER, upper=9)
        self.refused("authorize_dispatch", other, "dispatch_slot_occupied")
        result = self.result(ref)
        self.assertEqual(self.router.record_dispatch_result(result), {"status": "recorded", "charge_state": "actual", "trial_stopped": False})
        self.assertEqual(self.detail()["charge_minor_units"], 2)
        self.refused("authorize_dispatch", other, "dispatch_ceiling_exceeded")
        self.authority.admissions[other["invocation_id"]]["upper_minor_units"] = 8
        self.authorize(other)
        self.assertEqual(self.launch(other), None)

    def test_authorization_refusals_and_final_start_rechecks(self):
        """One bad operand per row leaves every table equal; final check runs under BEGIN IMMEDIATE."""
        doc = self.authority.admissions[self.req["invocation_id"]]
        for group, field, bad, reason in (
            (doc["origin"], "topic_id", rf.OTHER, "dispatch_origin_invalid"),
            (doc["origin"], "generation", 999, "dispatch_origin_invalid"),
            (doc["origin"], "backend", "", "dispatch_origin_invalid"),
            (doc["policy"], "max_concurrent_attempts", 2, "spend_unbounded"),
            (doc, "upper_minor_units", None, "spend_unbounded"),
            (doc["artifacts"][0], "size_bytes", 999, "payload_digest_mismatch"),
            (doc, "upper_minor_units", 11, "dispatch_ceiling_exceeded")):
            with self.subTest(field=field), patch.dict(group, {field: bad}):
                self.refused("authorize_dispatch", self.req, reason)
        self.refused("authorize_dispatch", {**self.req, "actor": "supervisor"}, "request_invalid")
        self.router = self.make_router()
        self.refused("authorize_dispatch", self.req, "spend_unbounded")
        self.router = self.make_router(dispatch_authority=self.authority)
        self.authorize()
        with patch.object(self.authority, "is_current", side_effect=lambda origin: self.db.in_transaction) as check:
            self.assertIsNone(self.launch(self.req))
            check.assert_called_once()
        with patch.object(self.authority, "epoch", "epoch-2"):
            self.assertEqual(self.launch(self.req)["reason"], "dispatch_origin_invalid")
        self.authority.current = False
        self.assertEqual(self.launch(self.req)["reason"], "spend_unbounded")

    def test_result_origins_conflict_replay_and_atomic_write_failure(self):
        """Original-bound results replay after lease expiry; bad provenance/write fails atomically; fixture only."""
        ref = self.authorize()
        req = self.result(ref)
        for field in ("topic_id", "invocation_id", "job_handle", "epoch", "manifest_ref", "credential_ref", "route", "backend", "evidence_generation"):
            with self.subTest(field=field), patch.dict(self.authority.evidence["origin"], {field: "wrong"}):
                self.refused("record_dispatch_result", req, "dispatch_origin_invalid")
        with patch.object(self.router, "_store", rf.Refusing(self.store, 2)):
            self.refused("record_dispatch_result", req, "dispatch_refused")
        self.router.record_dispatch_result(req)
        self.clock.set("2027-01-01T00:00:00Z")
        before = self.state()
        self.assertEqual(self.router.record_dispatch_result(req)["status"], "replayed")
        self.assertEqual(self.state(), before)
        self.authority.evidence["actual_minor_units"] = 0
        self.refused("record_dispatch_result", req, "dispatch_result_conflict")

    def test_first_charge_known_zero_unknown_and_overrun(self):
        """SQL U/A oracle; independent worlds prove zero/unknown/overrun and durable stop; no real cost."""
        for actual, ended, upper, expected, charge, stopped in (
            (0, True, 6, "actual", 0, False), (None, True, 6, "worst_case", 6, True),
            (0, False, 6, "worst_case", 6, True), (None, True, 0, "worst_case", 0, True),
            (9, True, 6, "actual", 9, True)):
            with self.subTest(actual=actual, ended=ended, upper=upper):
                case = type(self)()
                case.setUp()
                self.addCleanup(case.tearDown)
                case.authority.admissions[case.req["invocation_id"]]["upper_minor_units"] = upper
                req = case.result(case.authorize(), actual=actual, ended=ended)
                out = case.router.record_dispatch_result(req)
                self.assertEqual((out["charge_state"], out["trial_stopped"]), (expected, stopped))
                self.assertEqual(case.detail()["charge_minor_units"], charge)
                case.router = case.make_router(dispatch_authority=case.authority)
                other = case.prepare("inv_dispatch02", rf.OTHER, ceiling=100)
                if stopped:
                    case.refused("authorize_dispatch", other, "dispatch_trial_stopped")

    def test_paused_cancelled_request(self):
        """Current-lease pause/cancel still retains cost without lifecycle changes; SQL oracle, fixture only."""
        req = self.result(self.authorize())
        self.router.request_cancel({"invocation_id": self.req["invocation_id"], "requested_by": "operator", "reason": "stop"})
        self.x("UPDATE queue_entries SET paused_at='2026-09-27T10:00:00Z' WHERE topic_id=?", rf.TOPIC)
        self.assertEqual(self.router.record_dispatch_result(req)["status"], "recorded")
        self.assertEqual(self.detail()["charge_minor_units"], 2)
        self.assertIsNotNone(self.value("SELECT cancel_requested_at FROM invocations WHERE invocation_id=?", self.req["invocation_id"]))
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id=?", self.req["invocation_id"]), "launching")

    def test_expired_first_result_and_wrong_evidence(self):
        """Unregistered bytes and expired first result refuse atomically; late retention awaits 3b."""
        req = self.result(self.authorize())
        self.refused("record_dispatch_result", {**req, "evidence_ref": rf.h("f")}, "dispatch_origin_invalid")
        self.clock.set("2027-01-01T00:00:00Z")
        self.refused("record_dispatch_result", req, "lease_not_current")

    def test_uncertain_intent_charges_original_u_and_stops(self):
        """L-4 uncertainty fixes original U even before a result; audit readback, not real end detection."""
        req = self.result(self.authorize())
        out = self.router.record_transition({**{k: self.req[k] for k in ("capability_id", "invocation_id")},
            "to_state": "outcome_unknown", "unknown_episode": 1, "unknown_cause": "spawn_uncertain"})
        self.assertEqual(out["status"], "recorded", out)
        self.assertEqual(json.loads(self.value("SELECT detail FROM audit_events WHERE kind='dispatch_stopped'"))["charge_minor_units"], 6)
        self.refused("record_dispatch_result", req, "dispatch_result_not_current")
        self.refused("authorize_dispatch", self.prepare("inv_dispatch02", rf.OTHER), "dispatch_trial_stopped")
