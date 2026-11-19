"""Live dispatch authority and the supervisor's live start (PR-L1). Oracles: the real Router's audit rows (dispatch_authorized, dispatch_result),
the job files the supervisor writes (docker-plan.json, spawn.json), and the verified record's refusals, all through the real Router, supervisor,
spool and a fake executor child. Limits: the backend is simulated by writing the same `docker-complete.json` DockerCLI.run writes (no provider, no
container: F1); the real-route classifier, rejection mapping and the child's live agent are PR-L2's.
"""
import dataclasses
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from gen2.core import canonical
from gen2.core.instants import utc_instant_ns
from gen2.supervisor import authority as auth, docker_cli, jobs
from gen2.supervisor.isolation import LiveProfileRefused
from gen2.tests import children, router_fixtures as rf
from gen2.tests.test_rejection import FAILED, ROW, jl
from gen2.tests.supervisor_fixtures import MAIN, SupervisedTestCase, succeed

REAL_CONTAIN = docker_cli.contain_job   # before any test patches it
MANIFEST = b'{"profile": "fixture-only"}'
SCOPE = ["model", "delegates", "retries", "verification", "gateway", "maintenance"]


def record_doc(root, route="fixture", **over):
    doc = {"record_version": auth.RECORD, "state": "qualified", "route": route, "manifest_pin": canonical.bytes_digest(MANIFEST), "backend": "docker-cli/1",
           "credential_ref": "dummy-seed-1",
           "witnesses": [{"name": n, "passed": True, "receipt": "sha256:" + "a" * 64} for n in (auth.REAL_WITNESSES if route == "real" else auth.WITNESSES)],
           "policy": {"run_id": "trial-1", "accounting_owner": "operator", "deadline_at": rf.DEADLINE, "max_attempts": 3, "ceiling_minor_units": 10000,
                      "currency": "USD", "ceiling_scope": SCOPE, "policy_version": "v1"},
           "upper_minor_units": 400,
           "plan": {"engine_jobs": str(root / "jobs"), "host_jobs": "/host/jobs", "slots": {"out": "/host/out", "evidence": "/host/ev"}, "seed": "/host/seed",
                    **({"upstream": "203.0.113.7:443", "provider_auth": "/host/relay/provider-auth.conf", "provider_ca": "/host/relay/provider-ca.pem"} if route == "real" else {})},
           **({"deployment_id": "dep-1", "provider_route": "openai/codex", "runner_version": "1.2.3", "affected_lanes": ["codex"]} if route == "real" else {})}
    return {**doc, **over}


def sealed(doc):
    data = canonical.canonical_bytes(doc)
    return data, canonical.bytes_digest(data)


class Verification(unittest.TestCase):
    def test_malformed_or_missing_operands_mean_no_record_never_an_exception(self):
        from pathlib import Path
        good = record_doc(Path("/r"))
        for case, change in (("empty receipt", {"witnesses": [{"name": n, "passed": True, "receipt": ""} for n in auth.WITNESSES]}),
                             ("no backend", {"backend": ""}), ("no credential", {"credential_ref": None}), ("no policy", {"policy": None}),
                             ("negative upper", {"upper_minor_units": -1}), ("boolean upper", {"upper_minor_units": True}),
                             ("relative path", {"plan": {**good["plan"], "seed": "relative/seed"}}),
                             ("dotted path", {"plan": {**good["plan"], "host_jobs": "/host/../jobs"}}),
                             ("no slots", {"plan": {k: v for k, v in good["plan"].items() if k != "slots"}}),
                             ("slot not a path", {"plan": {**good["plan"], "slots": {"out": "", "evidence": "/ev"}}})):
            with self.subTest(case):
                data, pin = sealed({**good, **change})
                self.assertIsNone(auth.verify_record(data, pin, MANIFEST))
        data, pin = sealed({k: v for k, v in good.items() if k != "policy"})
        self.assertIsNone(auth.verify_record(data, pin, MANIFEST))
        self.assertFalse(auth.QualifiedAuthority(Path("/j"), record=data, pin=pin, manifest=MANIFEST, stage=lambda *a: {}).qualified)
    def test_a_record_is_accepted_only_when_qualified_for_exactly_this_manifest_and_pin(self):
        from pathlib import Path
        for case, route, change, ok in (("fixture", "fixture", {}, True), ("real", "real", {}, True),
                                        ("not qualified", "fixture", {"state": "stale"}, False), ("other manifest", "fixture", {"manifest_pin": "sha256:" + "0" * 64}, False),
                                        ("other version", "fixture", {"record_version": "qualification-record/2"}, False), ("unknown route", "fixture", {"route": "magic"}, False),
                                        ("witness failed", "fixture", {"witnesses": [{"name": n, "passed": n != "Q2", "receipt": "sha256:" + "a" * 64} for n in auth.WITNESSES]}, False),
                                        ("witness missing", "fixture", {"witnesses": [{"name": "Q1", "passed": True, "receipt": "sha256:" + "a" * 64}]}, False),
                                        ("real without the rejection witness", "real", {"witnesses": [{"name": n, "passed": True, "receipt": "sha256:" + "a" * 64} for n in auth.WITNESSES]}, False),
                                        ("real without the end-proof witness", "real", {"witnesses": [{"name": n, "passed": True, "receipt": "sha256:" + "a" * 64} for n in auth.REAL_WITNESSES if n != "Q8"]}, False),
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
        with self.assertRaises(TypeError):
            self.live_supervisor().prepare(order, isolation_profile={"manifest_pin": "x"})   # a profile is never accepted in its place
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

    def test_a_present_but_invalid_plan_file_is_uncertain_never_absent_so_it_is_not_rebuilt_from_the_order_and_nothing_starts(self):
        self.to_queued(rf.OTHER)
        for raw in ("null", "[]", "{"):
            with self.subTest(plan=raw):
                supervisor = self.live_supervisor()
                job = self.prepare(supervisor, inv=f"inv_plan{len(raw)}{ord(raw[0])}")
                (job.dir / "docker-plan.json").write_text(raw)
                try:
                    outcome = supervisor.advance(job.handle.removeprefix("job-"), live_start=True)
                except (LiveProfileRefused, ValueError):   # the corrupt file raises, as a malformed one always did
                    outcome = "refused"
                self.assertNotEqual(outcome, "running")
                self.assertEqual(((job.dir / "docker-plan.json").read_text(), (job.dir / "spawn.json").exists()), (raw, False))   # never rewritten, never spawned

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

    def test_the_relays_provider_files_come_only_from_the_protected_template_real_route_only(self):
        base = record_doc(self.root, "real")
        base["plan"]["egress_network_id"] = "c" * 64
        order = {"invocation_id": MAIN, "topic_id": rf.TOPIC, "config_bundle_hash": rf.CONFIG}
        plan = lambda doc: auth.QualifiedAuthority(self.root / "jobs", record=sealed(doc)[0], pin=sealed(doc)[1], manifest=MANIFEST, stage=self.spool.stage)
        planned = plan(base).plan(order)
        self.assertEqual({k: planned[k] for k in auth.RELAY_PROVIDER}, {"provider_auth": "/host/relay/provider-auth.conf", "provider_ca": "/host/relay/provider-ca.pem"})
        self.assertFalse(any(k in planned["binds"] for k in auth.RELAY_PROVIDER))               # the runner's binds are the fixed three
        for label, change in (("auth missing", {"provider_auth": None}), ("ca relative", {"provider_ca": "ca.pem"}), ("auth dotdot", {"provider_auth": "/a/../b"}), ("auth empty", {"provider_auth": ""})):
            template = {k: v for k, v in {**base["plan"], **change}.items() if v is not None}
            with self.subTest(label):
                data, pin = sealed({**base, "plan": template})
                self.assertIsNone(auth.verify_record(data, pin, MANIFEST))
        fixture = record_doc(self.root)
        data, pin = sealed({**fixture, "plan": {**fixture["plan"], "provider_ca": "/host/relay/provider-ca.pem"}})
        self.assertIsNone(auth.verify_record(data, pin, MANIFEST))                                # a fixture route has no provider files

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
        self.assertEqual((result["charge_minor_units"], result["response"]["charge_state"]), (400, "worst_case"))   # an unknown cost charges U (whether the trial then stops is the Router's rule: DEBT-052 amendment)
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


class CrashBoundaries(LiveWorld):
    """Every durable intermediate state of a live start has a defined safe recovery: no spawn, no second intent, no conversion into a non-live job."""

    def spawned(self, job):
        return (job.dir / "spawn.json").exists()

    def test_a_crash_after_the_order_and_before_its_plan_copy_leaves_a_live_order_that_recovery_will_not_start(self):
        from gen2.supervisor import jobs
        real_write = jobs.Job.write

        def broken(job, name, value):
            if name == "docker-plan.json":
                raise OSError("disk full")
            return real_write(job, name, value)
        with unittest.mock.patch.object(jobs.Job, "write", broken), self.assertRaises(OSError):
            self.live_supervisor().prepare(self.order("research_pass", succeed()), live=True)
        job = self.supervisor.job(MAIN)
        self.assertTrue(job.read("order.json")["live"])                          # the intent is in the order itself
        self.assertIsNone(job.read("docker-plan.json"))
        restarted = self.live_supervisor()
        self.assertEqual(restarted.advance(MAIN), "live_not_authorized")        # recovery's default call
        self.assertEqual(restarted.recover().get(MAIN), "live_not_authorized")
        self.assertEqual((self.spawned(job), self.audit("dispatch_authorized")), (False, []))
        with self.assertRaises(ValueError):                                      # and it cannot be re-prepared as an ordinary order
            self.live_supervisor().prepare(self.order("research_pass", succeed()))
        self.assertEqual(restarted.advance(MAIN, live_start=True), "running")   # with this call's flag the copy is restored from the order and the start is authorized
        self.assertEqual((self.spawned(job), len(self.audit("dispatch_authorized"))), (True, 1))
        self.assertEqual(job.read("docker-plan.json"), job.read("order.json")["plan"])

    def test_a_crash_after_the_routers_authorization_and_before_the_start_is_neither_a_second_intent_nor_an_unflagged_start(self):
        def die(point):
            if point == "dispatch_authorized":
                raise KeyboardInterrupt(point)
        first = self.live_supervisor(fault=die)
        job = self.prepare(first)
        with self.assertRaises(KeyboardInterrupt):
            first.advance(MAIN, live_start=True)
        self.assertEqual(len(self.audit("dispatch_authorized")), 1)
        restarted = self.live_supervisor()
        self.assertEqual(restarted.recover().get(MAIN), "live_not_authorized")
        self.assertFalse(self.spawned(job))
        self.assertEqual(restarted.advance(MAIN, live_start=True), "running")
        self.assertEqual((self.spawned(job), len(self.audit("dispatch_authorized"))), (True, 1))   # the same authorization replayed, no second intent

    def test_a_live_order_with_no_plan_anywhere_is_cancelled_not_started(self):
        supervisor = self.live_supervisor()
        job = self.prepare(supervisor)
        stored = job.read("order.json")
        job.write("order.json", {k: v for k, v in stored.items() if k != "plan"})   # partial preparation: the intent survives, the plan does not
        (job.dir / "docker-plan.json").unlink()
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "cancelled")
        self.assertEqual((self.spawned(job), self.audit("dispatch_authorized")), (False, []))

    def test_a_plan_file_alone_still_marks_an_order_live(self):
        supervisor = self.live_supervisor()
        job = self.prepare(supervisor)
        job.write("order.json", {k: v for k, v in job.read("order.json").items() if k not in ("live", "plan")})   # an order from before the marker existed
        self.assertEqual(supervisor.advance(MAIN), "live_not_authorized")
        self.assertFalse(self.spawned(job))

    def test_cancelling_or_expiring_an_unstarted_live_order_does_not_wait_for_a_backend_end_that_cannot_come(self):
        supervisor = self.live_supervisor()
        job = self.prepare(supervisor)
        self.assertEqual(supervisor.advance(MAIN), "live_not_authorized")
        grant = job.read("journal.json")["grant"]
        self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})
        self.assertEqual(supervisor.advance(MAIN), "cancelled")
        self.assertFalse(self.spawned(job))


class RealRoute(LiveWorld):
    CHANGE = {"route": "real", "plan": {"engine_jobs": "", "host_jobs": "/host/jobs", "slots": {"out": "/host/out", "evidence": "/host/ev"}, "seed": "/host/seed",
                                        "upstream": "203.0.113.7:443", "egress_network_id": "c" * 64,
                                        "provider_auth": "/host/relay/provider-auth.conf", "provider_ca": "/host/relay/provider-ca.pem"}}

    def make_router(self, **overrides):
        self.CHANGE = {**self.CHANGE, "plan": {**self.CHANGE["plan"], "engine_jobs": str(self.root / "jobs")}}
        data, pin = sealed(record_doc(self.root, "real", **{k: v for k, v in self.CHANGE.items() if k != "route"}))
        self.authority = auth.QualifiedAuthority(self.root / "jobs", record=data, pin=pin, manifest=MANIFEST, stage=self.spool.stage,
                                                 read=lambda topic, digest: self.spool.read(digest, topic_id=topic))
        return super(LiveWorld, self).make_router(dispatch_authority=self.authority, **overrides)

    def test_the_real_plan_carries_the_upstream_the_judgment_output_and_the_bridge_id(self):
        plan = self.prepare(self.live_supervisor()).read("docker-plan.json")
        self.assertEqual((plan["route"], plan["output"], plan["upstream"], plan["egress"], plan["origin"]["deployment_id"]),
                         ("real", "judgment", "203.0.113.7:443", {"network_id": "c" * 64}, "dep-1"))

    def test_a_rejected_credential_end_carries_the_routers_rejection_operands_from_the_backends_own_records(self):
        supervisor = self.live_supervisor()
        job = self.prepare(supervisor)
        job.write("runner-start.json", {"State": {"StartedAt": "2026-09-27T10:00:05.123456789Z"}})
        job.write("docker-complete.json", {"origin": job.read("docker-plan.json")["origin"], "refs": [],
                                           "disposition": {"disposition": "credentials_rejected", "reason": "relay_401"}})
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "running")
        for _ in range(200):
            if job.read("journal.json").get("collected"):
                break
            supervisor.advance(MAIN, live_start=True)
        record = job.read("journal.json")["collected"]["record"]
        result = self.authority.result("adm", record["content_hash"])
        self.assertEqual(result["rejection"]["started_at"], "2026-09-27T10:00:05Z")
        self.assertEqual((result["rejection"]["runner"], result["rejection"]["affected_lanes"]), ({"name": "codex", "version": "1.2.3"}, ["codex"]))
        self.assertEqual(result["rejection"]["observed_at"], json.loads(self.spool.read(record["content_hash"], topic_id=rf.TOPIC))["observed_at"])
        job.write("docker-complete.json", {"origin": job.read("docker-plan.json")["origin"], "refs": [], "disposition": {"disposition": "unknown"}})
        self.assertNotIn("rejection", self.authority.result("adm", record["content_hash"]))   # only a classified rejection is a rejection
        job.write("runner-start.json", {"State": {}})
        job.write("docker-complete.json", {"origin": job.read("docker-plan.json")["origin"], "refs": [], "disposition": {"disposition": "credentials_rejected"}})
        self.assertIsNone(self.authority.result("adm", record["content_hash"]))               # an unassemblable rejection is no result: fixed U


class FailedEnd(LiveWorld):
    """Evidence the backend set aside is staged at every observed end, so a failed end's result records (Gate S #12 change 1)."""
    JUDGMENT, USAGE = b"2e1 complete", b'{"usage": "recorded"}'

    def failed_end(self, disposition, code=2):
        supervisor = self.live_supervisor()
        names = {"evidence-" + canonical.bytes_digest(b)[len("sha256:"):] + ext: (b, media) for b, ext, media in
                 ((self.JUDGMENT, ".txt", "text/plain"), (self.USAGE, ".json", "application/json"))}
        steps = [{"op": "write", "name": n, "hex": b.hex()} for n, (b, _) in names.items()] + [{"op": "exit", "code": code}]
        job = self.prepare(supervisor, steps=steps)
        refs = [{"content_hash": canonical.bytes_digest(b), "size_bytes": len(b), "media_type": m} for b, m in names.values()]
        job.write("docker-complete.json", {"origin": job.read("docker-plan.json")["origin"], "refs": refs, "disposition": disposition})
        outcome = LiveStart.drive(self, supervisor)
        return job, refs, outcome

    def assert_recorded(self, job, refs, outcome):
        self.assertEqual(outcome, "failed")
        self.assertTrue(refs)                                                              # non-vacuous: real set-aside refs
        (result,) = self.audit("dispatch_result")
        self.assertEqual((result["charge_minor_units"], result["response"]["charge_state"], result["trial_stopped"]), (400, "worst_case", False))
        recorded = {a["content_hash"] for a in result["evidence"]["artifacts"]}
        self.assertTrue({r["content_hash"] for r in refs} <= recorded)
        stored = {row[0] for row in self.rows("SELECT content_hash FROM artifacts WHERE topic_id = ?", rf.TOPIC)}
        self.assertTrue({r["content_hash"] for r in refs} <= stored)                       # registered as Router artifacts
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "failed")
        self.assertEqual(job.read("journal.json")["collected"]["result"], None)
        self.assertEqual(self.audit("dispatch_result_unrecorded"), [])

    def test_a_refused_judgment_after_a_confirmed_end_records_a_failed_result_with_its_set_aside_evidence(self):
        self.assert_recorded(*self.failed_end({"disposition": "unknown", "reason": "runner_not_failed_turn"}))

    def test_a_credential_rejection_shaped_end_with_no_outcome_also_records(self):
        self.assert_recorded(*self.failed_end({"disposition": "unknown", "reason": "relay_401"}, code=1))

    def test_a_failed_job_lists_the_evidence_it_set_aside_in_its_collected_end(self):
        job, refs, _ = self.failed_end({"disposition": "unknown"})
        self.assertEqual(sorted(r["content_hash"] for r in job.read("journal.json")["collected"]["evidence"]), sorted(r["content_hash"] for r in refs))

    def test_a_terminated_job_stages_the_evidence_it_had_set_aside(self):
        supervisor = self.live_supervisor()
        data = b"set aside before the deadline"
        name = "evidence-" + canonical.bytes_digest(data)[len("sha256:"):] + ".txt"
        job = self.prepare(supervisor, steps=[{"op": "write", "name": name, "hex": data.hex()}, {"op": "hang"}])
        self.finish_backend(job)
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "running")
        with unittest.mock.patch("gen2.supervisor.docker_cli.contain_job"):
            self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})
            for _ in range(200):
                supervisor.advance(MAIN, live_start=True)
                if job.read("journal.json").get("collected"):
                    break
        collected = job.read("journal.json")["collected"]
        self.assertTrue(collected["terminated"])
        self.assertEqual([r["content_hash"] for r in collected["evidence"]], [canonical.bytes_digest(data)])


class Containment(LiveWorld):
    def test_a_deadline_or_cancel_termination_of_a_live_job_kills_and_removes_its_containers_and_an_unendable_one_leaves_the_end_unconfirmed(self):
        for failing in (False, True):
            with self.subTest(failing=failing):
                self.tearDown()
                self.setUp()
                supervisor = self.live_supervisor()
                job = self.prepare(supervisor, steps=[{"op": "hang"}])
                self.finish_backend(job)
                self.assertEqual(supervisor.advance(MAIN, live_start=True), "running")
                with unittest.mock.patch("gen2.supervisor.docker_cli.contain_job", side_effect=LiveProfileRefused("contain_failed") if failing else None) as contain:
                    self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})
                    for _ in range(200):
                        supervisor.advance(MAIN, live_start=True)
                        if job.read("journal.json").get("collected"):
                            break
                contain.assert_called()
                handling = job.read("journal.json")["collected"]["observation"]["descendants"]["handling"]
                self.assertEqual(handling == "unconfirmed", failing)


class ContainedEnd(LiveWorld):
    """The production `contain_job` is the one owner of the end fact for the supervisor's deadline and cancel paths: a fake CLI transport (or a
    one-line fake `docker` for the production `capture`), no hand-written marker anywhere here."""
    FIXTURE = "d" * 64

    def hung(self, supervisor=None, inv=MAIN):
        supervisor = supervisor or self.live_supervisor()
        job = self.prepare(supervisor, inv=inv, steps=[{"op": "hang"}])
        job.write("docker-plan.json", {**job.read("docker-plan.json"), "fixture": {"Id": self.FIXTURE}})   # the fixture route's protected plan owes a fixture ID
        job.write("docker.json", {})   # what `DockerCLI` leaves before its first command: an intact, empty mutation history
        self.assertEqual(supervisor.advance(inv, live_start=True), "running")
        return supervisor, job

    def contain(self, job, execute=None, seconds_after_deadline=1, **real):
        """The supervisor's own `contain_job(job)` call, run for real over a fake transport at an instant after the order's deadline."""
        calls = []
        def transport(job, argv, env, deadline, bounds):
            calls.append(argv[3:])
            return execute(argv[3:]) if execute else (0, b"", b"")
        run = REAL_CONTAIN
        def owner(target):
            return run(target, **({"execute": transport} if not real else {}), clock=lambda: utc_instant_ns(job.read("order.json")["deadline_at"]) / 1e9 + seconds_after_deadline)
        for name, value in (("contain_job", owner), ("CLI_SHA", hashlib.sha256(b"fake").hexdigest())):
            patch = unittest.mock.patch.object(docker_cli, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = unittest.mock.patch.object(docker_cli.Path, "read_bytes", lambda path: b"fake")
        patch.start()
        self.addCleanup(patch.stop)
        return calls

    def drive(self, supervisor, inv=MAIN):
        for _ in range(200):
            try:
                outcome = supervisor.advance(inv, live_start=True)
            except LiveProfileRefused:
                return "held"
            if outcome in ("committed", "failed", "cancelled"):
                return outcome
        return outcome

    def test_a_cancelled_job_is_ended_by_containment_alone_recorded_at_worst_case_and_the_next_admission_is_allowed(self):
        self.to_queued(rf.OTHER)
        supervisor, job = self.hung()
        calls = self.contain(job)
        self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})
        self.assertEqual(self.drive(supervisor), "cancelled")                              # cancellation stays cancelled, not relabelled failed
        self.assertEqual(calls, [("kill", self.FIXTURE), ("rm", "-f", self.FIXTURE)])      # nothing else was created: only the plan's fixture is an original
        (result,) = self.audit("dispatch_result")
        self.assertEqual((result["charge_minor_units"], result["response"]["charge_state"], result["trial_stopped"]), (400, "worst_case", False))
        self.assertEqual(job.read("docker-complete.json")["disposition"], {"disposition": "unknown", "reason": "contained_without_collection"})
        self.assertEqual(self.audit("dispatch_result_unrecorded"), [])
        second = self.live_supervisor()
        second.prepare(self.order("research_pass", succeed("inv_slot0002"), inv="inv_slot0002", topic=rf.OTHER), live=True)
        self.assertEqual(second.advance("inv_slot0002", live_start=True), "running")       # the next invocation is authorized

    def test_the_order_deadline_ends_through_the_same_owner_as_failed_timeout_and_a_late_or_failed_end_is_held(self):
        from gen2.tests.supervisor_fixtures import AFTER_DEADLINE
        for case, late, rm_fails in (("ended in time", 1, False), ("ended late", 100, False), ("relay will not go", 1, True)):
            with self.subTest(case):
                self.tearDown()
                self.setUp()
                supervisor, job = self.hung()
                self.contain(job, execute=lambda argv: (1, b"", b"error") if rm_fails and argv[0] == "rm" else (0, b"", b""), seconds_after_deadline=late)
                self.clock.set(AFTER_DEADLINE)
                outcome = self.drive(supervisor)
                if case == "ended in time":
                    self.assertEqual(outcome, "failed")
                    self.assertEqual(job.read("journal.json")["collected"]["observation"]["findings"], ["timeout"])
                    (result,) = self.audit("dispatch_result")
                    self.assertEqual((result["charge_minor_units"], result["response"]["charge_state"]), (400, "worst_case"))
                else:
                    self.assertEqual(outcome, "stalled" if rm_fails else "backend_end_unconfirmed")   # confirmed late, or not confirmed at all: an unknown end, nothing recorded
                    self.assertIsNone(job.read("docker-complete.json"))
                    self.assertEqual(self.audit("dispatch_result"), [])
                    self.assertEqual(job.read("containment.json")["late"], case == "ended late")

    def test_a_cli_the_killed_child_left_mid_wait_is_ended_by_its_recorded_identity_so_containment_can_confirm(self):
        fake = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False)
        fake.write("#!/bin/sh\nexit 0\n")
        fake.close()
        os.chmod(fake.name, stat.S_IRWXU)
        self.addCleanup(os.unlink, fake.name)
        supervisor, job = self.hung()
        waiter = subprocess.Popen(["sleep", "60"], start_new_session=True)               # the `docker wait` the supervisor's group kill never reached
        self.addCleanup(waiter.kill)
        state = jobs.proc_stat(waiter.pid)
        job.write("docker-cli.json", {"pid": waiter.pid, "session": waiter.pid, "starttime": state[2], "boot_id": jobs.boot_id()})
        for name, value in (("CLI", fake.name), ("CLI_SHA", hashlib.sha256(Path(fake.name).read_bytes()).hexdigest())):
            patch = unittest.mock.patch.object(docker_cli, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        run = REAL_CONTAIN
        patch = unittest.mock.patch.object(docker_cli, "contain_job", lambda target: run(target, clock=lambda: utc_instant_ns(target.read("order.json")["deadline_at"]) / 1e9 + 1))
        patch.start()
        self.addCleanup(patch.stop)
        self.router.request_cancel({"invocation_id": MAIN, "requested_by": "operator", "reason": "stop"})
        self.assertEqual(self.drive(supervisor), "cancelled")                              # production capture, a real subprocess: the stale CLI no longer blocks the end
        self.assertIsNotNone(waiter.wait(timeout=5))
        self.assertIsNotNone(job.read("docker-complete.json"))


class CollectionRefusal(RealRoute):
    """The first topic's accounting (REQ, U=6, seven attempts, ceiling 42) through the production chain: `DockerCLI.run` (the real `_run`, a fake `docker` transport that writes
    real cidfiles and returns inspect shapes) refuses at collection -> production `contain_job` publishes the generated marker -> the failed child -> the supervisor -> the Router."""
    CHANGE = {**RealRoute.CHANGE, "upper_minor_units": 6, "plan": {**RealRoute.CHANGE["plan"], "relay_config": "/host/relay/nginx.conf"},
              "policy": {"run_id": "trial-1", "accounting_owner": "operator", "deadline_at": rf.DEADLINE, "max_attempts": 7, "ceiling_minor_units": 42,
                         "currency": "REQ", "ceiling_scope": SCOPE, "policy_version": "v1"}}
    NET, EGRESS, IMAGE = "b" * 64, "c" * 64, "sha256:" + "1" * 64
    PIN = "sha256:" + hashlib.sha256(b"configuration").hexdigest()

    def world(self, publish=True, rejected=False):
        """A live job whose executor is the production child with the production live agent over a daemon-free transport; returns the job and waits for the child's end."""
        self.to_queued(rf.OTHER)
        supervisor = self.live_supervisor()
        order = dataclasses.replace(self.order("research_pass", [], inv=MAIN), command=(sys.executable, str(children.path("gen2/tests/live_refusing_child.py"))))
        if not publish:
            (self.root / "no-publish").write_text("")
        if rejected:
            (self.root / "rejected").write_text("")
        supervisor.prepare(order, live=True)
        job = supervisor.job(MAIN)
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "running")
        for _ in range(600):
            if (job.dir / "exit.json").exists():
                break
            time.sleep(0.05)
        if rejected:   # the production agent's own mapping of the backend's classified rejection, not a scripted exit
            self.assertEqual(job.read("exit.json")["code"], 1)
            self.assertIn("CredentialsRejected", (job.dir / "executor.log").read_text())
            return supervisor, job
        self.assertEqual(job.read("exit.json")["code"], 2)   # the child failed because the backend refused, through the production agent error path
        self.assertIn("the live backend refused: collection_absent", (job.dir / "executor.log").read_text())
        return supervisor, job

    def calls(self):
        return [tuple(json.loads(line)) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def test_an_empty_judgment_rejected_run_reaches_the_typed_fact_the_hold_the_retained_evidence_and_the_route_wide_block(self):
        """The 0.169-shaped rejected failed turn (runner exit 1, EMPTY judgment leaf, one 401 relay row) through the production child end to end: the real
        scratch collection and classifier, `ScratchBatch`, `agent_for` and `child.main` produce the evidence, the completion and exit 1; the supervisor
        stages every raw ref; the Router records the failed end at U, the typed fact and the operator hold, retains the evidence, and blocks the route."""
        supervisor, job = self.world(rejected=True)
        complete = job.read("docker-complete.json")
        self.assertEqual((complete["disposition"], complete["output_observation"]), ({"disposition": "credentials_rejected", "reason": "relay_401"}, {"kind": "judgment", "status": "empty"}))
        refs = complete["refs"]
        self.assertEqual(len(refs), 4)                                                     # events, diagnostics, access, usage: every nonempty ref is kept
        row = jl({**ROW, "upstream": "203.0.113.7:443"})
        wanted = {canonical.bytes_digest(b): b for b in (FAILED, b"diagnostics", row)}
        self.assertTrue(set(wanted) <= {r["content_hash"] for r in refs})
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "running")
        job.write("runner-start.json", {"State": {"StartedAt": "2026-09-27T10:00:10.123456789Z"}})   # the runner started after the intent
        self.clock.set("2026-09-27T10:00:30Z")
        self.assertEqual(LiveStart.drive(self, supervisor), "failed")
        hashes = {r["content_hash"] for r in refs}
        self.assertEqual(hashes - {r["content_hash"] for r in job.read("journal.json")["collected"]["evidence"]}, set())   # the supervisor's retained evidence
        (result,) = self.audit("dispatch_result")
        self.assertEqual(hashes - {a["content_hash"] for a in result["evidence"]["artifacts"]}, set())   # the dispatch result
        self.assertEqual(hashes - {row[0] for row in self.rows("SELECT content_hash FROM artifacts WHERE topic_id = ?", rf.TOPIC)}, set())   # the registered Router artifacts
        for digest, data in wanted.items():
            self.assertEqual(self.spool.read(digest, topic_id=rf.TOPIC), data)             # the bytes, not only the names
        self.assertEqual((result["charge_minor_units"], result["response"]["charge_state"]), (self.audit("dispatch_authorized")[0]["upper_minor_units"], "worst_case"))   # no scientific outcome: full U
        (fact,) = self.rows("SELECT state FROM capability_facts WHERE capability = ?", "provider-auth:codex")
        self.assertEqual(fact[0], "failing")
        (hold,) = self.rows("SELECT hold_class, owner FROM holds WHERE hold_class = ?", "capability")
        self.assertEqual(tuple(hold), ("capability", "operator"))
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "failed")
        again = self.live_supervisor()
        again.prepare(self.order("research_pass", succeed("inv_slot0002"), inv="inv_slot0002", topic=rf.OTHER), live=True)
        self.assertEqual(again.advance("inv_slot0002", live_start=True), "cancelled")   # route-wide: another topic's dispatch is refused, nothing started
        self.assertFalse((again.job("inv_slot0002").dir / "spawn.json").exists())
        (cancel,) = [json.loads(r[0]) for r in self.rows("SELECT detail FROM audit_events WHERE kind = 'cancel_requested' AND invocation_id = ?", "inv_slot0002")]
        self.assertEqual(cancel["reason"], "dispatch refused: provider_rejection_stopped")   # the retained route history, not the capability hold alone

    def test_without_fallback_publication_the_same_refusal_stays_held(self):
        supervisor, job = self.world(publish=False)
        self.assertIsNone(job.read("docker-complete.json"))
        self.assertEqual(LiveStart.drive(self, supervisor), "backend_end_unconfirmed")
        self.assertEqual(self.audit("dispatch_result"), [])
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "running")

    def test_the_generated_marker_path_keeps_its_fences_a_stale_epoch_records_nothing_and_an_unconfirmed_descendant_is_no_confirmed_end(self):
        def confirmed(job):
            collected = job.read("journal.json")["collected"]
            return self.authority.result(job.read("journal.json")["dispatch"]["admission_ref"], collected["record"]["content_hash"])["confirmed_end"]
        supervisor, job = self.world()
        self.authority.epoch = "epoch-2"                                                   # a restart between the marker and the result: a stale origin
        self.assertEqual(LiveStart.drive(self, supervisor), "stalled")
        self.assertEqual((self.audit("dispatch_result"), self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN)), ([], "running"))
        self.tearDown()
        self.setUp()
        supervisor, job = self.world()
        self.assertEqual(LiveStart.drive(self, supervisor), "failed")
        self.assertTrue(confirmed(job))                                                    # control: the generated marker with every descendant confirmed ended is a confirmed end
        journal = job.read("journal.json")
        journal["collected"]["observation"]["descendants"]["handling"] = "unconfirmed"      # the same end with a descendant the supervisor could not confirm
        job.write("journal.json", journal)
        self.assertFalse(confirmed(job))

    def test_the_generated_marker_path_with_a_stale_lease_records_nothing_and_the_same_world_with_its_lease_does(self):
        supervisor, job = self.world()
        journal = job.read("journal.json")
        journal["grant"]["lease"]["lease_id"] = "lease_stale00000"                          # the lease the origin names is not the Router's
        job.write("journal.json", journal)
        self.assertEqual(LiveStart.drive(self, supervisor), "stalled")
        self.assertEqual((self.audit("dispatch_result"), self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN)), ([], "running"))


class ExpiredRecord(LiveWorld):
    def test_a_retired_record_refuses_every_new_start(self):
        supervisor = self.live_supervisor()
        self.prepare(supervisor)
        self.authority.retire()
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "cancelled")
        self.assertEqual(self.audit("dispatch_authorized"), [])


if __name__ == "__main__":
    unittest.main()
