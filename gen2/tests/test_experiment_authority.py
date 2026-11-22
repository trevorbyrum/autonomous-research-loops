"""§4.2 and Astra §2: exercise the production loader, Supervisor, Router, child and backend with offline operands."""
import dataclasses
import json
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest import mock

from gen2.app.compose import Composition
from gen2.core import canonical
from gen2.core.instants import utc_instant_ns
from gen2.supervisor import authority, docker_cli
from gen2.supervisor.isolation import LiveProfileRefused
from gen2.tests import children, live_refusing_child as child, router_fixtures as rf, supervisor_fixtures as sf
from gen2.tests import test_supervisor_live as live
from gen2.tests.test_rejection import ROW, jl

START, END = "2026-09-27T10:00:00Z", "2026-09-27T10:02:00Z"
MAIN = sf.MAIN
PENDING = {"name": "DEBT-004", "passed": False}
SCOPE = {"invocation_id": MAIN, "topic_id": rf.TOPIC, "config_bundle_hash": rf.CONFIG, "not_before": START}
UNAVAILABLE = "profile_qualification_unavailable"


class Experiment(sf.SupervisedTestCase):
    def make_router(self, **overrides):
        self.composition = Composition().bind(SimpleNamespace(spool=self.spool))
        clock = mock.patch.object(authority, "time_ns", side_effect=lambda: utc_instant_ns(self.clock()))
        clock.start()
        self.addCleanup(clock.stop)
        self.manifest = child.manifest_for(qualification_state="rejection_experiment", credential_ref="dummy-seed-1")
        self.record = live.record_doc(self.root, "real", state="rejection_experiment", experiment=SCOPE)
        self.record["witnesses"] = [PENDING if row["name"] == "DEBT-004" else row for row in self.record["witnesses"]]
        self.record["plan"].update(live.EGRESS_TEMPLATE, relay_config="/host/relay/nginx.conf")
        self.record["policy"].update(max_attempts=1, ceiling_minor_units=6, currency="REQ", deadline_at=END)
        self.record["upper_minor_units"] = 6
        self.dispatch = self.load()
        return super().make_router(dispatch_authority=self.dispatch, **overrides)

    def load(self, *, record=None, manifest=None, approval=None, env=None):
        manifest = self.manifest if manifest is None else manifest
        manifest_bytes, manifest_pin = live.sealed(manifest)
        document = {**self.record, **(record or {}), "manifest_pin": manifest_pin}
        data, pin = live.sealed(document)
        authorization = {"authorization_version": "rejection-experiment-authorization/1", "record_pin": pin, "manifest_pin": manifest_pin,
                         "experiment": document.get("experiment"), "ruling_ref": "ruling-1", "approved_at": START}
        data_approval, pin_approval = live.sealed(authorization if approval is None else approval(authorization))
        for name, content in (("record.json", data), ("manifest.json", manifest_bytes), ("authorization.json", data_approval)):
            (self.root / name).write_bytes(content)
        self.environ = {"GEN2_QUALIFICATION_RECORD": str(self.root / "record.json"), "GEN2_QUALIFICATION_PIN": pin,
                        "GEN2_MANIFEST": str(self.root / "manifest.json"), "GEN2_EXPERIMENT_AUTHORIZATION": str(self.root / "authorization.json"),
                        "GEN2_EXPERIMENT_AUTHORIZATION_PIN": pin_approval}
        return self.composition.authority(self.root / "jobs", self.environ if env is None else env(self.environ))

    def audit(self, kind):
        return [json.loads(row[0]) for row in self.rows("SELECT detail FROM audit_events WHERE kind = ?", kind)]

    def unavailable(self, loaded):
        self.assertFalse(loaded.admits(MAIN))
        self.assertFalse(loaded.qualified)
        with self.assertRaisesRegex(LiveProfileRefused, UNAVAILABLE):
            loaded.plan(SCOPE)

    def test_record_has_only_the_literal_pending_row_and_one_of_each_witness(self):
        """§4.2 Record: one literal false, without a receipt, alongside all required passes."""
        others = [row for row in self.record["witnesses"] if row["name"] != "DEBT-004"]
        cases = [[], [None], [{}], [{"name": "DEBT-004"}], [dict(PENDING, receipt=None)], [dict(PENDING, receipt="sha256:" + "a" * 64)],
                 [dict(PENDING, passed=True)], [dict(PENDING, passed=0)], [dict(PENDING, extra=False)], [PENDING, PENDING]]
        for pending in cases:
            with self.subTest(pending=pending):
                self.unavailable(self.load(record={"witnesses": others + pending}))
        self.unavailable(self.load(record={"witnesses": [*others[1:], others[1], PENDING]}))
        for policy in ({"max_attempts": True}, {"max_attempts": 2}, {"ceiling_minor_units": 7}, {"deadline_at": START}):
            with self.subTest(policy=policy):
                self.unavailable(self.load(record={"policy": self.record["policy"] | policy}))

    def test_authorization_byte_pin_pair_pins_and_exact_scope_are_independent(self):
        """§4.2 Authorization: every approval failure leaves the record unavailable."""
        for name in ("GEN2_EXPERIMENT_AUTHORIZATION", "GEN2_EXPERIMENT_AUTHORIZATION_PIN"):
            with self.subTest(missing=name):
                self.unavailable(self.load(env=lambda env: {k: v for k, v in env.items() if k != name}))
        wrong_pin = "sha256:" + "0" * 64
        for name in ("GEN2_EXPERIMENT_AUTHORIZATION_PIN", "GEN2_QUALIFICATION_PIN"):
            with self.subTest(wrong_pin=name):
                self.unavailable(self.load(env=lambda env: env | {name: wrong_pin}))
        self.unavailable(self.load(env=lambda env: env | {"GEN2_EXPERIMENT_AUTHORIZATION": str(self.root / "missing")}))
        for name in ("record_pin", "manifest_pin"):
            with self.subTest(pair_pin=name):
                self.unavailable(self.load(approval=lambda approval: approval | {name: wrong_pin}))
        for malformed in (None, {}, {k: v for k, v in SCOPE.items() if k != "not_before"}, SCOPE | {"extra": "x"}):
            with self.subTest(scope=malformed):
                self.unavailable(self.load(approval=lambda approval: approval | {"experiment": malformed}))
                self.unavailable(self.load(record={"experiment": malformed}))
        self.unavailable(self.load(approval=lambda approval: approval | {"experiment": SCOPE | {"topic_id": rf.OTHER}}))
        self.unavailable(self.load(approval=lambda approval: approval | {"extra": True}))
        for malformed in (None, {}, {"experiment": SCOPE}):
            with self.subTest(approval=malformed):
                self.unavailable(self.load(approval=lambda _: malformed))

    def test_literal_state_and_route_agreement_preserve_ordinary_qualification(self):
        """§4.2 Record and Manifest: productive readers still require genuine, passed witnesses."""
        data = (self.root / "record.json").read_bytes()
        manifest = (self.root / "manifest.json").read_bytes()
        self.assertIsNone(authority.verify_record(data, canonical.bytes_digest(data), manifest))
        self.assertFalse(self.dispatch.qualified)
        for state in (None, {}, "pending", "qualified"):
            with self.subTest(state=state):
                self.unavailable(self.load(manifest=self.manifest | {"qualification_state": state}))
        self.unavailable(self.load(manifest=self.manifest | {"route": "fixture"}))
        self.unavailable(self.load(manifest=self.manifest | {"credential_ref": "different-session"}))
        qualified = live.record_doc(self.root, "real")
        ordinary = self.load(record=qualified | {"plan": qualified["plan"] | live.EGRESS_TEMPLATE},
                             manifest=self.manifest | {"qualification_state": "qualified"},
                             env=lambda env: {k: v for k, v in env.items() if "EXPERIMENT" not in k})
        self.assertTrue(ordinary.qualified)

    def interrupt_after_authorize(self):
        def stop(point):
            if point == "dispatch_authorized":
                raise KeyboardInterrupt(point)
        supervisor = self.make_supervisor(dispatch=self.dispatch, fault=stop)
        supervisor.prepare(self.order("research_pass", []), live=True)
        with self.assertRaises(KeyboardInterrupt):
            supervisor.advance(MAIN, live_start=True)
        return supervisor.job(MAIN)

    def test_every_scope_operand_is_checked_at_plan_admission_and_start(self):
        """Astra scope 2: invocation, topic, bundle and both edges of [not_before, deadline)."""
        job = self.interrupt_after_authorize()
        order, plan = (job.read(name) for name in ("order.json", "docker-plan.json"))
        origin = self.audit("dispatch_authorized")[0]["origin"]
        self.assertTrue(self.dispatch.is_current(origin))
        self.assertEqual(origin["qualification_ref"], self.environ["GEN2_QUALIFICATION_PIN"])
        self.assertIsNotNone(self.dispatch.admission(MAIN, self.dispatch.run_id, 1))
        for changes, timestamp in (({"invocation_id": "inv_other0001"}, START), ({"topic_id": rf.OTHER}, START),
                                   ({"config_bundle_hash": "sha256:" + "0" * 64}, START), ({}, "2026-09-27T09:59:59Z"), ({}, END)):
            with self.subTest(changes=changes, timestamp=timestamp), mock.patch.object(authority, "time_ns", return_value=utc_instant_ns(timestamp)):
                with self.assertRaisesRegex(LiveProfileRefused, UNAVAILABLE):
                    self.dispatch.plan(order | changes)
                self.assertFalse(self.dispatch.is_current(origin | changes))
                job.write("order.json", order | changes)
                self.assertIsNone(self.dispatch.admission(MAIN, self.dispatch.run_id, 1))
                job.write("order.json", order)
                job.write("docker-plan.json", plan | {"origin": plan["origin"] | changes})
                self.assertIsNone(self.dispatch.admission(MAIN, self.dispatch.run_id, 1))
                job.write("docker-plan.json", plan)

    def test_the_window_closing_in_the_authorizing_advance_spawns_nothing(self):
        """Astra scope 2/3: the first launch, not a recovery, takes the Router's start check after the intent is durable."""
        def close(point):
            if point == "dispatch_authorized":
                self.clock.set(END)   # returns normally: the same advance goes on to the spawn
        supervisor = self.make_supervisor(dispatch=self.dispatch, fault=close)
        supervisor.prepare(self.order("research_pass", []), live=True)
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "cancelled")
        self.assertEqual(len(self.audit("dispatch_authorized")), 1)
        self.assertIsNone(supervisor.job(MAIN).read("spawn.json"))

    def test_restart_refuses_the_old_epoch_even_inside_the_window(self):
        """Astra scope 3: a durable authorization cannot start under its successor engine."""
        job = self.interrupt_after_authorize()
        restarted = self.load()
        router = super().make_router(dispatch_authority=restarted)
        supervisor = self.make_supervisor(dispatch=restarted, control=router)
        self.assertNotEqual(self.dispatch.epoch, restarted.epoch)
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "cancelled")
        self.assertIsNone(job.read("spawn.json"))
        self.assertEqual(len(self.audit("dispatch_authorized")), 1)

    def test_restart_after_preparation_refuses_a_plan_that_names_another_record(self):
        """Astra scope 3: a prepared, unadmitted plan stays bound to the record that planned it; a qualified plan has no such pin to lose."""
        self.make_supervisor(dispatch=self.dispatch).prepare(self.order("research_pass", []), live=True)
        restarted = self.load(record={"deployment_id": "another-deployment"})   # same manifest, credential, state and order pins: only the record differs
        self.assertNotEqual(restarted._pin, self.dispatch._pin)
        supervisor = self.make_supervisor(dispatch=restarted, control=super().make_router(dispatch_authority=restarted))
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "cancelled")
        self.assertEqual(self.audit("dispatch_authorized"), [])
        self.assertIsNone(supervisor.job(MAIN).read("spawn.json"))

    def test_backend_refuses_both_directions_of_manifest_plan_disagreement(self):
        """Astra scope 1: backend independently enforces the literal manifest claim."""
        plan = self.dispatch.plan(SCOPE)
        job = self.make_supervisor(dispatch=self.dispatch).job(MAIN)
        job.prepare({"deadline_at": rf.DEADLINE})
        execute = mock.Mock()
        with mock.patch.object(docker_cli, "CLI_SHA", child.FAKE_SHA):
            for manifest_state, origin in (("qualified", plan["origin"]),
                                           ("rejection_experiment", {k: v for k, v in plan["origin"].items() if k != "qualification_state"}),
                                           ("rejection_experiment", plan["origin"] | {"qualification_state": None})):
                with self.subTest(manifest_state=manifest_state, origin=origin):
                    job.write("docker-plan.json", plan | {"origin": origin})
                    with self.assertRaisesRegex(LiveProfileRefused, "plan_qualification_state"):
                        docker_cli.DockerCLI(job, self.manifest | {"qualification_state": manifest_state}, lambda _: b"configuration", "t", execute=execute)
        execute.assert_not_called()
        self.assertIsNone(job.read("docker-attempt.json"))

    def end(self, outcome, *, race=False, late=False):
        supervisor = self.make_supervisor(dispatch=self.dispatch)
        invocation = self.order("research_pass", [])
        command = (sys.executable, str(children.path("gen2/tests/live_refusing_child.py")))
        invocation = dataclasses.replace(invocation, command=command)
        (self.root / outcome).touch()
        if race:
            other = self.order("research_pass", [], inv="inv_other0001", topic=rf.OTHER)
            barrier = Barrier(2, timeout=5)

            def prepare(candidate):
                barrier.wait()
                supervisor.prepare(candidate, live=True)

            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = (pool.submit(prepare, candidate) for candidate in (invocation, other))
                first.result()
                with self.assertRaisesRegex(LiveProfileRefused, UNAVAILABLE):
                    second.result()
        supervisor.prepare(invocation, live=True)
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "running")
        job = supervisor.job(MAIN)
        supervisor._children[job.handle].wait(timeout=10)
        if race:
            grant = job.read("journal.json")["grant"]
            replay = self.router.authorize_dispatch({"invocation_id": MAIN, "capability_id": grant["capability_id"],
                                                     "run_id": self.dispatch.run_id, "attempt": 1})
            self.assertEqual(replay["status"], "replayed")
            self.assertEqual(replay["admission_ref"], job.read("journal.json")["dispatch"]["admission_ref"])
        self.clock.set("2026-09-27T10:02:01Z" if late else "2026-09-27T10:00:30Z")
        self.assertEqual(live.LiveStart.drive(self, supervisor), "failed")
        (result,) = self.audit("dispatch_result")
        self.assertEqual(result["evidence"]["origin"], self.audit("dispatch_authorized")[0]["origin"])
        self.assertTrue(result["evidence"]["confirmed_end"])
        self.assertEqual((result["charge_minor_units"], result["response"]["charge_state"]), (6, "worst_case"))
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "failed")
        return supervisor, job, result

    def test_the_child_refuses_a_same_state_manifest_the_plan_does_not_name(self):
        """Astra scope 1: the bytes read at the backend entrance must be the durable plan's manifest, before any command."""
        supervisor = self.make_supervisor(dispatch=self.dispatch)
        supervisor.prepare(dataclasses.replace(self.order("research_pass", []), command=(sys.executable, str(children.path("gen2/tests/live_refusing_child.py")))), live=True)
        (self.root / "manifest.json").write_bytes(canonical.canonical_bytes(self.manifest | {"credential_version": "v2"}))   # same state and route, other pins
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "running")
        job = supervisor.job(MAIN)
        supervisor._children[job.handle].wait(timeout=10)
        self.assertEqual(job.read("exit.json"), {"code": 1, "signal": None})
        self.assertFalse((self.root / "calls.jsonl").exists())
        self.assertIsNone(job.read("docker-attempt.json"))

    def test_accepted_credential_retains_the_outcome_and_one_u_with_no_rejection(self):
        """Astra scope 3: concurrent orders, replay, expiry and a second invocation cannot send again."""
        supervisor, job, result = self.end("accepted", race=True, late=True)
        self.assertNotIn("rejection", result["evidence"])
        self.assertEqual(self.rows("SELECT fact_id FROM capability_facts WHERE state = 'failing'"), [])
        self.assertEqual(self.rows("SELECT hold_id FROM holds WHERE hold_class = 'capability'"), [])
        digest = canonical.bytes_digest(child.ACCEPTED)
        self.assertIn(digest, {ref["content_hash"] for ref in result["evidence"]["artifacts"]})
        self.assertEqual(self.spool.read(digest, topic_id=rf.TOPIC), child.ACCEPTED)
        self.assertFalse((job.scratch / "outcome.json").exists())
        self.assertTrue(result["trial_stopped"])
        self.clock.set(START)
        self.assertEqual(supervisor.advance(MAIN, live_start=True), "failed")
        with self.assertRaisesRegex(LiveProfileRefused, UNAVAILABLE):
            supervisor.prepare(self.order("research_pass", [], inv="inv_other0001"), live=True)
        self.assertEqual(job.read("spawn.json"), {"attempts": 1, "failed": 0})
        self.assertIsNotNone(job.read("docker-attempt.json"))
        self.assertEqual(len(self.audit("dispatch_authorized")), 1)
        self.assertEqual((self.root / "starts").read_text().split().count("runner"), 1)

    def test_real_401_writes_the_dated_fact_owned_hold_and_failed_with_evidence(self):
        """§4.2 Outcomes and DEBT-004: real-route classification through the production child."""
        _, job, result = self.end("rejected")
        self.assertEqual(job.read("exit.json"), {"code": 1, "signal": None})
        self.assertEqual(job.read("docker-complete.json")["disposition"], {"disposition": "credentials_rejected", "reason": "relay_401"})
        self.assertFalse(result["trial_stopped"])
        access = jl(ROW | {"upstream": "203.0.113.7:443"})
        self.assertEqual(self.spool.read(canonical.bytes_digest(access), topic_id=rf.TOPIC), access)
        fact, hold = result["response"]["fact_id"], result["response"]["hold_id"]
        observed = result["evidence"]["rejection"]["observed_at"]
        self.assertEqual(self.rows("SELECT state, since FROM capability_facts WHERE fact_id = ?", fact), [("failing", observed)])
        self.assertEqual(self.rows("SELECT hold_class, owner, cleared_at FROM holds WHERE hold_id = ?", hold), [("capability", "operator", None)])


if __name__ == "__main__":
    unittest.main()
