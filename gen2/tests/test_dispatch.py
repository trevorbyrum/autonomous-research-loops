"""F5/v7 §2: literal audit readbacks and whole-store refusal/replay equality.

The bound reader is a trusted double: these tests prove Router admission and
charging, never runtime isolation, real enforcement or collector authenticity.
"""
import copy
import json
from unittest.mock import Mock, patch

from gen2.router.boundary import Refusal
from gen2.tests import router_fixtures as rf
from gen2.tests.test_capability_probe import observation


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
        self.clock.set("2026-10-31T11:59:00Z")
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
        """Bad references refuse; expiry retains original U despite reported actual; SQL oracle, no real lease."""
        req = self.result(self.authorize())
        self.refused("record_dispatch_result", {**req, "evidence_ref": rf.h("f")}, "dispatch_origin_invalid")
        self.clock.set("2027-01-01T00:00:00Z")
        self.assertEqual(self.router.record_dispatch_result(req)["charge_state"], "worst_case")
        self.assertEqual((self.detail()["charge_minor_units"], self.detail()["trial_stopped"]), (6, True))

    def test_uncertain_intent_charges_original_u_and_stops(self):
        """L-4 uncertainty fixes original U even before a result; audit readback, not real end detection."""
        req = self.result(self.authorize())
        out = self.router.record_transition({**{k: self.req[k] for k in ("capability_id", "invocation_id")},
            "to_state": "outcome_unknown", "unknown_episode": 1, "unknown_cause": "spawn_uncertain"})
        self.assertEqual(out["status"], "recorded", out)
        self.assertEqual(json.loads(self.value("SELECT detail FROM audit_events WHERE kind='dispatch_stopped'"))["charge_minor_units"], 6)
        self.assertEqual(self.router.record_dispatch_result(req)["charge_state"], "worst_case")
        self.refused("authorize_dispatch", self.prepare("inv_dispatch02", rf.OTHER), "dispatch_trial_stopped")

    def test_late_results_fix_u_without_lifecycle_or_scientific_writes(self):
        """Original U and unchanged invocation/lease are SQL oracles; local doubles do not prove isolation."""
        for mode, upper in (("epoch", 6), ("released", 6), ("terminal", 6), ("qualification", 6), ("pins", 6), ("epoch", 0)):
            with self.subTest(mode=mode, upper=upper):
                case = DispatchTests()
                case.setUp()
                self.addCleanup(case.tearDown)
                case.authority.admissions[case.req["invocation_id"]]["upper_minor_units"] = upper
                req = case.result(case.authorize(), actual=0)
                if mode == "epoch":
                    case.authority.epoch = "epoch-2"
                elif mode == "released":
                    case.x("UPDATE leases SET released_at=?, release_reason='expired' WHERE topic_id=?", "2026-10-31T11:59:01Z", rf.TOPIC)
                elif mode == "qualification":
                    case.authority.current = False
                elif mode == "terminal":
                    end = case.evidence({"invocation_id": case.req["invocation_id"], "topic_id": rf.TOPIC})
                    self.assertEqual(case.router.record_transition({**{k: case.req[k] for k in ("capability_id", "invocation_id")},
                        "to_state": "failed", "failure_class": "exit_nonzero", "end_evidence_ref": end})["status"], "recorded")
                else:
                    case.router._amendments._require_current_pins = Mock(side_effect=Refusal("amendment_pending", "test incompatible pins"))
                before = case.state()
                self.assertEqual(case.router.record_dispatch_result(req), {"status": "recorded", "charge_state": "worst_case", "trial_stopped": True})
                self.assertEqual(case.detail()["charge_minor_units"], upper)
                after = case.state()
                for table in before.keys() - {"audit_events", "artifacts", "artifact_topics", "store_generation"}:
                    self.assertEqual(after[table], before[table], table)
                case.router = case.make_router(dispatch_authority=case.authority)
                case.authority.epoch, case.authority.current = "epoch-1", True
                case.refused("authorize_dispatch", case.prepare("inv_dispatch02", rf.OTHER, ceiling=100), "dispatch_trial_stopped")
                before = case.state()
                self.assertEqual(case.router.record_dispatch_result(req)["status"], "replayed")
                self.assertEqual(case.state(), before)

    def rejection(self, ref, **overrides):
        req = self.result(ref, actual=0)
        topic = self.authority.admissions[self.req["invocation_id"]]["origin"]["topic_id"]
        execution = self.evidence({"invocation_id": self.req["invocation_id"], "topic_id": topic},
                                  **{"observed_at": "2026-10-31T12:00:00Z", **overrides})
        raw = self.spool.read(execution, topic_id=topic)
        self.authority.evidence.update(evidence_ref=execution, artifacts=[self.artifact(raw, "application/json")],
            rejection={"started_at": "2026-10-31T11:59:59Z", "observed_at": "2026-10-31T12:00:00Z",
                       "runner": {"name": "codex", "version": "0.153.2"}, "affected_lanes": ["station:station-1"]})
        return {**req, "evidence_ref": execution}

    def test_rejection_fact_hold_and_failed_after_persistence_ack(self):
        """DEP 4(d): literal dates/owner/deadline and FAILED SQL readback; trusted fixture, no classifier proof."""
        self.clock.set("2026-10-31T12:00:00Z")
        self.router.record_capability_probe(observation("a1", "usable", "2026-10-30T12:00:00Z"))
        req = self.rejection(self.authorize())
        out = self.router.record_dispatch_result(req)
        self.assertEqual(out["status"], "recorded", out)
        self.assertEqual((out["charge_state"], out["trial_stopped"]), ("actual", False))
        fact = self.store.select("capability_facts", {"fact_id": out["fact_id"]})[0]
        hold = self.store.select("holds", {"hold_id": out["hold_id"]})[0]
        self.assertEqual((fact["capability"], fact["state"], fact["since"], fact["last_success_at"], fact["affected_lanes"]),
                         ("provider-auth:codex", "failing", "2026-10-31T12:00:00Z", "2026-10-30T12:00:00Z", ["station:station-1"]))
        self.assertEqual((hold["hold_class"], hold["owner"], hold["required_authority"], hold["recoverability"]), ("capability", "operator", "operator", "needs_remediation"))
        self.assertEqual(rf.utc_instant_ns(hold["deadline_at"]) - rf.utc_instant_ns(hold["created_at"]), 3600 * 10**9)
        self.assertIn("refreshed in its auth volume", hold["clears_when"])
        self.assertIn(req["evidence_ref"], fact["detail"])
        transition = {**{k: req[k] for k in ("capability_id", "invocation_id")}, "to_state": "failed", "failure_class": "exit_nonzero", "end_evidence_ref": req["evidence_ref"]}
        self.assertEqual(self.router.record_transition(transition)["state"], "failed")
        before = self.state()
        self.assertEqual(self.router.record_dispatch_result(req)["status"], "replayed")
        self.assertEqual(self.router.record_transition(transition)["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_rejection_refusals_and_hold_write_rollback(self):
        """One invalid date/end/identity per row and failed hold insertion leave the whole store equal; no runtime."""
        self.clock.set("2026-10-31T12:00:00Z")
        ref = self.authorize()
        for overrides, reason in (({"job_handle": "wrong"}, "evidence_refused"), ({"handling": "unconfirmed"}, "evidence_refused"),
                                  ({"findings": []}, "evidence_refused"), ({"exit": {"code": 0, "signal": None}}, "dispatch_origin_invalid")):
            req = self.rejection(ref, **overrides)
            self.refused("record_dispatch_result", req, reason)
        req = self.rejection(ref)
        for field, bad in (("observed_at", "bad"), ("started_at", "2026-11-01T00:00:00Z"), ("observed_at", "2027-01-01T00:00:00Z")):
            with patch.dict(self.authority.evidence["rejection"], {field: bad}):
                self.refused("record_dispatch_result", req, "dispatch_origin_invalid")
        insert = self.store.insert
        def fail_hold(table, row):
            if table == "holds":
                raise rf.api.StoreWriteError("test hold failure")
            return insert(table, row)
        with patch.object(self.store, "insert", side_effect=fail_hold):
            self.refused("record_dispatch_result", req, "dispatch_refused")
        self.assertEqual(self.router.record_dispatch_result(req)["status"], "recorded")

    def test_late_rejection_keeps_unknown_last_success_without_reopening(self):
        """Late rejection fixes U and dates failure with unknown last success; SQL oracle, no genuine provider."""
        req = self.rejection(self.authorize())
        self.clock.set("2027-01-01T00:00:00Z")
        before = self.rows("SELECT * FROM invocations")
        out = self.router.record_dispatch_result(req)
        self.assertEqual((out["charge_state"], out["trial_stopped"]), ("worst_case", True))
        self.assertEqual(self.rows("SELECT since,last_success_at FROM capability_facts WHERE fact_id=?", out["fact_id"]), [("2026-10-31T12:00:00Z", None)])
        self.assertEqual(self.rows("SELECT * FROM invocations"), before)

    def real_route(self, req=None, deployment="station-live", route="codex:responses"):
        origin = self.authority.admissions[(req or self.req)["invocation_id"]]["origin"]
        origin.update(route="real", deployment_id=deployment, provider_route=route)

    def test_known_zero_genuine_rejection_blocks_route_after_probe_and_clearance(self):
        """B2: known-zero history blocks another topic despite recovery/clearance; SQL and equality, no real send."""
        self.clock.set("2026-10-31T12:00:00Z")
        self.real_route()
        result = self.rejection(self.authorize())
        out = self.router.record_dispatch_result(result)
        self.assertEqual((out["charge_state"], out["trial_stopped"]), ("actual", False))
        self.assertEqual(self.detail()["charge_minor_units"], 0)
        self.router.record_capability_probe(observation("b2", "usable", "2026-10-31T12:00:01Z"))
        self.assertEqual(self.decide("opd_clearb2001", "hold_clearance", {"kind": "hold", "ref": out["hold_id"]}, tid=None)["status"], "applied")
        other = self.prepare("inv_dispatch02", rf.OTHER)
        self.real_route(other)
        self.router = self.make_router(dispatch_authority=self.authority)
        self.refused("authorize_dispatch", other, "provider_rejection_stopped")
        before = self.state()
        self.assertEqual(self.router.record_dispatch_result(result)["status"], "replayed")
        self.assertEqual(self.state(), before)
        self.real_route(other, route="codex:other-endpoint")
        self.authorize(other)

    def test_route_provenance_and_fixture_control(self):
        """Trusted originals scope rejection; artifact text does not. Whole-store refusals, fixture authority only."""
        self.real_route()
        origin = self.authority.admissions[self.req["invocation_id"]]["origin"]
        for key in ("deployment_id", "provider_route"):
            with patch.dict(origin, {key: None}):
                self.refused("authorize_dispatch", self.req, "dispatch_origin_invalid")
        origin["route"] = "fixture"
        self.clock.set("2026-10-31T12:00:00Z")
        result = self.rejection(self.authorize())
        self.assertEqual(self.router.record_dispatch_result(result)["charge_state"], "actual")
        other = self.prepare("inv_dispatch02", rf.OTHER)
        self.real_route(other)
        self.authorize(other)

    def test_final_start_checks_retained_route_history(self):
        """Final-start writer fence sees authenticated prior history; literal retained fixture, no external qualification."""
        self.real_route()
        self.authorize()
        origin = copy.deepcopy(self.authority.admissions[self.req["invocation_id"]]["origin"])
        origin.update(invocation_id="inv_prior0001", topic_id=rf.OTHER)
        self.x("INSERT INTO audit_events VALUES ('aud_prior0001', ?, 'dispatch_result', ?, 'inv_prior0001', NULL, ?)", rf.STAMP, rf.OTHER,
            json.dumps({"admission_ref": "aud_priorintent", "evidence": {"origin": origin, "rejection": {}}, "charge_minor_units": 0, "trial_stopped": False}))
        before = self.state()
        self.assertEqual(self.launch(self.req)["reason"], "provider_rejection_stopped")
        self.assertEqual(self.state(), before)
