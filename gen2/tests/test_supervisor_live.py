"""Live dispatch authority and the supervisor's live start (PR-L1). Oracles: the real Router's audit rows (dispatch_authorized, dispatch_result),
the job files the supervisor writes (docker-plan.json, spawn.json), and the verified record's refusals, all through the real Router, supervisor,
spool and a fake executor child. Limits: the backend is simulated by writing the same `docker-complete.json` DockerCLI.run writes (no provider, no
container: F1); the real-route classifier, rejection mapping and the child's live agent are PR-L2's.
"""
import json
import unittest

from gen2.core import canonical
from gen2.supervisor import authority as auth
from gen2.supervisor.isolation import ABSENT_PROFILE, LiveProfileRefused
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import MAIN, SupervisedTestCase, succeed

MANIFEST = b'{"profile": "fixture-only"}'
SCOPE = ["model", "delegates", "retries", "verification", "gateway", "maintenance"]


def record_doc(root, route="fixture", **over):
    doc = {"record_version": auth.RECORD, "state": "qualified", "route": route, "manifest_pin": canonical.bytes_digest(MANIFEST), "backend": "docker-cli/1",
           "credential_ref": "dummy-seed-1",
           "witnesses": [{"name": n, "passed": True, "receipt": "sha256:" + "a" * 64} for n in (auth.REAL_WITNESSES if route == "real" else auth.WITNESSES)],
           "policy": {"run_id": "trial-1", "accounting_owner": "operator", "deadline_at": rf.DEADLINE, "max_attempts": 3, "ceiling_minor_units": 10000,
                      "currency": "USD", "ceiling_scope": SCOPE, "policy_version": "v1"},
           "upper_minor_units": 400,
           "plan": {"engine_jobs": str(root / "jobs"), "host_jobs": "/host/jobs", "slots": {"out": "/host/out", "evidence": "/host/ev"}, "seed": "/host/seed"},
           **({"deployment_id": "dep-1", "provider_route": "openai/codex"} if route == "real" else {})}
    return {**doc, **over}


def sealed(doc):
    data = canonical.canonical_bytes(doc)
    return data, canonical.bytes_digest(data)


class Verification(unittest.TestCase):
    def test_a_record_is_accepted_only_when_qualified_for_exactly_this_manifest_and_pin(self):
        from pathlib import Path
        for case, route, change, ok in (("fixture", "fixture", {}, True), ("real", "real", {}, True),
                                        ("not qualified", "fixture", {"state": "stale"}, False), ("other manifest", "fixture", {"manifest_pin": "sha256:" + "0" * 64}, False),
                                        ("other version", "fixture", {"record_version": "qualification-record/2"}, False), ("unknown route", "fixture", {"route": "magic"}, False),
                                        ("witness failed", "fixture", {"witnesses": [{"name": n, "passed": n != "Q2", "receipt": "sha256:" + "a" * 64} for n in auth.WITNESSES]}, False),
                                        ("witness missing", "fixture", {"witnesses": [{"name": "Q1", "passed": True, "receipt": "sha256:" + "a" * 64}]}, False),
                                        ("real without the rejection witness", "real", {"witnesses": [{"name": n, "passed": True, "receipt": "sha256:" + "a" * 64} for n in auth.WITNESSES]}, False),
                                        ("real without a deployment", "real", {"deployment_id": ""}, False)):
            with self.subTest(case):
                data, pin = sealed(record_doc(Path("/r"), **{"route": route, **change}))
                self.assertEqual(auth.verify_record(data, pin, MANIFEST) is not None, ok)
        data, pin = sealed(record_doc(Path("/r")))
        for case, args in (("tampered record", (data + b" ", pin, MANIFEST)), ("wrong pin", (data, "sha256:" + "0" * 64, MANIFEST)),
                           ("other manifest bytes", (data, pin, MANIFEST + b" ")), ("not json", (b"x", canonical.bytes_digest(b"x"), MANIFEST))):
            with self.subTest(case):
                self.assertIsNone(auth.verify_record(*args))


class LiveWorld(SupervisedTestCase):
    """A real Router wired to the qualified authority, a real supervisor, a fake executor."""
    CHANGE: dict = {}

    def make_router(self, **overrides):
        data, pin = sealed(record_doc(self.root, **self.CHANGE))
        self.authority = auth.QualifiedAuthority(self.root / "jobs", record=data, pin=pin, manifest=MANIFEST, stage=self.spool.stage)
        return super().make_router(dispatch_authority=self.authority, **overrides)

    def live_supervisor(self, **options):
        return self.make_supervisor(dispatch=self.authority, **options)

    def prepare(self, supervisor, inv=MAIN, steps=None):
        order = self.order("research_pass", succeed(inv) if steps is None else steps, inv=inv)
        supervisor.prepare(order, live=True)
        return supervisor.job(inv)

    def finish_backend(self, job):
        """What DockerCLI.run leaves when its end is confirmed: the complete file for this plan's origin (the backend itself is not run)."""
        job.write("docker-complete.json", {"origin": job.read("docker-plan.json")["origin"], "refs": [], "disposition": {"disposition": "unknown", "reason": "test"}})

    def audit(self, kind):
        return [json.loads(row[0]) for row in self.rows("SELECT detail FROM audit_events WHERE kind = ? ORDER BY at, audit_event_id", kind)]


class PlanAndGate(LiveWorld):
    def test_without_an_authority_or_with_a_caller_profile_a_live_order_refuses_as_before(self):
        order = self.order("research_pass", succeed())
        with self.assertRaises(LiveProfileRefused):
            self.supervisor.prepare(order, live=True)                                   # the default station has no authority
        with self.assertRaises(LiveProfileRefused):
            self.live_supervisor().prepare(order, isolation_profile={"manifest_pin": "x"})   # a profile is never accepted in its place
        with self.assertRaises(LiveProfileRefused):
            self.live_supervisor().prepare(order, live=False, isolation_profile={"state": "qualified"})
        self.assertFalse((self.root / "jobs" / f"job-{MAIN}" / "order.json").exists())  # nothing durable

    def test_prepare_writes_the_plan_with_host_paths_a_fixed_generation_and_the_origin_the_backend_will_sign(self):
        job = self.prepare(self.live_supervisor())
        plan = job.read("docker-plan.json")
        self.assertEqual((plan["binds"]["inputs"], plan["binds"]["out"], plan["binds"]["seed"]), (f"/host/jobs/job-{MAIN}/scratch/inputs", f"/host/out/{plan['generation']}", "/host/seed"))
        self.assertRegex(plan["generation"], r"^[0-9a-f]{32}$")
        self.assertEqual({k: plan["origin"][k] for k in ("invocation_id", "job_handle", "route", "evidence_generation", "manifest_ref")},
                         {"invocation_id": MAIN, "job_handle": "job-" + MAIN, "route": "fixture", "evidence_generation": plan["generation"],
                          "manifest_ref": canonical.bytes_digest(MANIFEST)})
        again = self.live_supervisor()
        again.prepare(self.order("research_pass", succeed()), live=True)               # a repeat is a no-op: the plan is written once
        self.assertEqual(job.read("docker-plan.json"), plan)

    def test_a_real_route_plan_carries_the_protected_egress_network_id_and_never_a_name(self):
        from pathlib import Path
        base = record_doc(self.root, "real")
        for case, template, ok in (("an id", {**base["plan"], "egress_network_id": "c" * 64}, True), ("a name", {**base["plan"], "egress_network_id": "gen2-egress"}, False),
                                   ("none", base["plan"], False)):
            with self.subTest(case):
                data, pin = sealed({**base, "plan": template})
                real = auth.QualifiedAuthority(self.root / "jobs", record=data, pin=pin, manifest=MANIFEST, stage=self.spool.stage)
                order = {"invocation_id": MAIN, "topic_id": rf.TOPIC, "config_bundle_hash": rf.CONFIG}
                if ok:
                    self.assertEqual(real.plan(order)["egress"], {"network_id": "c" * 64})
                else:
                    with self.assertRaises(LiveProfileRefused):
                        real.plan(order)
        fixture = {**record_doc(self.root), "plan": {**record_doc(self.root)["plan"], "egress_network_id": "c" * 64}}   # a fixture route has no bridge
        data, pin = sealed(fixture)
        with self.assertRaises(LiveProfileRefused):
            auth.QualifiedAuthority(self.root / "jobs", record=data, pin=pin, manifest=MANIFEST, stage=self.spool.stage).plan(
                {"invocation_id": MAIN, "topic_id": rf.TOPIC, "config_bundle_hash": rf.CONFIG})

    def test_a_job_directory_outside_the_mapped_prefix_cannot_be_planned(self):
        data, pin = sealed(record_doc(self.root, plan={**record_doc(self.root)["plan"], "engine_jobs": "/somewhere/else"}))
        elsewhere = auth.QualifiedAuthority(self.root / "jobs", record=data, pin=pin, manifest=MANIFEST, stage=self.spool.stage)
        with self.assertRaises(LiveProfileRefused):
            elsewhere.plan({"invocation_id": MAIN, "topic_id": rf.TOPIC, "config_bundle_hash": rf.CONFIG})

    def test_a_stored_live_order_is_not_permission_the_start_needs_this_calls_flag(self):
        supervisor = self.live_supervisor()
        job = self.prepare(supervisor)
        self.assertEqual(supervisor.advance(MAIN), "live_not_authorized")                 # a later call without live starts nothing
        self.assertFalse((job.dir / "spawn.json").exists())
        self.assertEqual(self.audit("dispatch_authorized"), [])
        self.assertEqual(supervisor.advance(MAIN, live_start=False), "live_not_authorized")


class LiveStart(LiveWorld):
    def test_the_router_authorizes_before_the_child_starts_and_the_result_is_recorded_at_worst_case_when_cost_is_unknown(self):
        supervisor = self.live_supervisor()
        job = self.prepare(supervisor)
        self.finish_backend(job)                                                          # the confirmed end DockerCLI.run would have left
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "running")
        (intent,) = self.audit("dispatch_authorized")
        self.assertEqual((intent["run_id"], intent["attempt"], intent["upper_minor_units"], intent["origin"]["route"]), ("trial-1", 1, 400, "fixture"))
        self.assertTrue((job.dir / "spawn.json").exists())                                # authorization came first, then the start
        self.assertEqual(self.drive(supervisor), "committed")
        (result,) = self.audit("dispatch_result")
        self.assertEqual((result["charge_minor_units"], result["trial_stopped"], result["response"]["charge_state"]), (400, True, "worst_case"))
        self.assertEqual(result["admission_ref"], job.read("journal.json")["dispatch"]["admission_ref"])

    def drive(self, supervisor):
        for _ in range(200):
            outcome = supervisor.advance(MAIN, live_start=True)
            if outcome in ("committed", "failed", "cancelled"):
                return outcome
        return outcome

    def test_a_refused_authorization_cancels_the_job_before_anything_starts(self):
        self.to_queued(rf.OTHER)
        first, second = self.live_supervisor(), self.live_supervisor()
        self.prepare(first, "inv_slot0001")
        second.prepare(self.order("research_pass", succeed("inv_slot0002"), inv="inv_slot0002", topic=rf.OTHER), live=True)
        two = second.job("inv_slot0002")
        self.assertEqual(first.advance("inv_slot0001", live_start=True), "running")        # the first intent now owns the one slot
        outcome = second.advance("inv_slot0002", live_start=True)
        self.assertEqual(outcome, "cancelled")
        self.assertFalse((two.dir / "spawn.json").exists())
        self.assertEqual(len(self.audit("dispatch_authorized")), 1)

    def test_with_no_confirmed_end_no_result_is_recorded_and_the_router_keeps_the_intent(self):
        supervisor = self.live_supervisor()
        job = self.prepare(supervisor)                                                    # the backend never wrote docker-complete.json
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "running")
        for _ in range(60):
            if supervisor.advance(MAIN, live_start=True) == "backend_end_unconfirmed":
                break
        self.assertEqual(self.audit("dispatch_result"), [])
        self.assertEqual(len(self.audit("dispatch_authorized")), 1)


class ExpiredRecord(LiveWorld):
    def test_a_retired_record_refuses_every_new_start(self):
        supervisor = self.live_supervisor()
        self.prepare(supervisor)
        self.authority.retire()
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "cancelled")
        self.assertEqual(self.audit("dispatch_authorized"), [])


if __name__ == "__main__":
    unittest.main()
