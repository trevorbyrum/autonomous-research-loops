"""G-8/D1: one review commit hands off, never approves; fixture evaluator, real Router receipts and auth."""
import json
from dataclasses import replace
from unittest.mock import patch

from gen2.accounting import stopping as s
from gen2.operator.service import OperatorService
from gen2.router import completion
from gen2.tests import operator_fixtures as of, router_fixtures as rf, test_stopping as st
from gen2.tests.test_dossier_record import FixtureEvaluator, ITEMS

HOLD = {"hold_id": "hold_wait00001", "subject_ref": "review", "hold_class": "judgment", "cause": "review needs follow-up",
        "recoverability": "needs_decision", "required_authority": "operator", "owner": "operator", "deadline_at": rf.DEADLINE,
        "clears_when": "operator review", "capability_fact_id": None}
TRIGGER = {"reason_code": "persistent_contradiction", "cause_ref": "follow-up", "source_revision": 1, "observed_at": rf.STAMP}


class World(FixtureEvaluator, rf.ContractWorld):
    @staticmethod
    def callback(inputs):
        context = s.Context(rf.TOPIC, 2, 1)
        rule = s.known_item(context, "r", replace(st.inventory(), current_contract_revision=2), ITEMS)
        return s.evaluate_profile(context, s.Profile("P", s.Expression("r"), ()), (rule,), ())

    def setUp(self):
        super().setUp()
        self.assertEqual(self.finish(self.started("inv_research01"), "op_research01")["status"], "committed")
        cp = self.started("inv_dossier001", "checkpoint")
        if getattr(self, "blocker", None) == "hold":
            self.hold(cp, "hold_existing01")
        if getattr(self, "blocker", None) == "unfinished":
            self.started("inv_other00001", "verification")
        if getattr(self, "blocker", None) == "episode":
            self.router.open_review({"episode_id": "rev_pending001", "topic_id": rf.TOPIC, "kind": "fixed_cadence"})
        self.dossier = self.router.record_dossier({**{k: cp[k] for k in ("capability_id", "invocation_id")}, "topic_id": rf.TOPIC})
        self.assertEqual(self.dossier["status"], "recorded", self.dossier)
        self.assertEqual(self.finish(cp, "op_dossier001")["status"], "committed")
        self.reviewer, self.ref = self.started("inv_review0001", "checkpoint"), self.artifact(b"Independent fixture review")

    def ready_review(self, outcome="sufficient", **sections):
        review = {"record_id": "cr-wait", "kind": "sufficiency_review", "contract_revision": 2, "subject_ref": rf.TOPIC,
                  "subject_revision": self.dossier["dossier_revision"], "subject_hash": self.dossier["content_hash"],
                  "assessment": {"outcome": outcome, "summary": "Independent review"}, "evidence_refs": [self.ref]}
        payload = {**rf.empty_outcome(self.reviewer["invocation_id"]), "completion_records": [review], **sections}
        env = self.envelope(self.reviewer, "op_review0001", payload, refs=[self.ref])
        self.ready(self.reviewer, env["payload_digest"])
        env["expected_state_revision"] = self.state_revision()
        return env


class HandoffTest(World):
    def test_wait_is_one_atomic_receipted_transition_and_replay(self):
        """Receipt, queue, review and finalization agree; lost reply adds nothing, completion still needs an operator."""
        env = self.ready_review()
        before = self.state_revision()
        out = self.router.commit_outcome(env)
        self.assertEqual((out["status"], out["receipt"]["effects"]["queue_transition"], self.status()),
                         ("committed", {"from": "resting", "to": "awaiting_judgment"}, "awaiting_judgment"))
        self.assertEqual(self.state_revision(), before + 1)
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id=?", self.reviewer["invocation_id"]), "committed")
        before = self.state()
        self.assertEqual(self.router.commit_outcome(env)["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_review_rollback_leaves_no_transition_or_receipt(self):
        """C-4: a write failure after choosing waiting rolls back the review and queue; unchanged retry succeeds."""
        env = self.ready_review()
        before = self.state()
        self.faults["in_transaction:evidence"] = RuntimeError("rollback waiting")
        with self.assertRaisesRegex(RuntimeError, "rollback waiting"):
            self.router.commit_outcome(env)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.router.commit_outcome(env)["receipt"]["effects"]["queue_transition"]["to"], "awaiting_judgment")

    def test_proposed_material_effects_and_insufficient_review_do_not_wait(self):
        """B2: a new hold/trigger or non-sufficient review remains recorded without a waiting transition."""
        for outcome, sections, blocker in (("insufficient", {}, None), ("sufficient", {"holds": [HOLD]}, None),
                ("sufficient", {"review_triggers": [TRIGGER]}, None), ("sufficient", {}, "hold"), ("sufficient", {}, "unfinished"), ("sufficient", {}, "episode")):
            with self.subTest(outcome=outcome, sections=sections):
                case = World()
                case.blocker = blocker
                case.setUp()
                self.addCleanup(case.tearDown)
                out = case.router.commit_outcome(case.ready_review(outcome, **sections))
                self.assertEqual((out["status"], out["receipt"]["effects"]["queue_transition"], case.status()), ("committed", None, "resting"))

    def test_new_signal_between_preparation_and_writer_is_not_lost(self):
        """The existing freshness fence recaptures; the writer observes a new pending signal and withholds hand-off."""
        env, original = self.ready_review(), completion.candidate
        def race(*args):
            ready = original(*args)
            if not self.value("SELECT count(*) FROM review_triggers"):
                self.router.raise_signal({"topic_id": rf.TOPIC, "reason_code": "retraction", "signal_source": "operator", "cause_ref": "work", "source_revision": 1, "observed_at": rf.STAMP})
            return ready
        with patch.object(completion, "candidate", side_effect=race) as prepare:
            out = self.router.commit_outcome(env)
        self.assertEqual((out["status"], self.status(), prepare.call_count), ("committed", "resting", 2))

    def test_explicit_rework_uses_operator_auth_and_replays_once(self):
        """Exporter and spoofed identity cannot resume; the operator opens one episode and requeues atomically."""
        self.router.commit_outcome(self.ready_review())
        service = OperatorService(self.router, of.credentials())
        body = {"episode_id": "rev_rework0001", "topic_id": rf.TOPIC, "kind": "fixed_cadence", "rework": True}
        def call(token, doc=body):
            raw = json.dumps(doc).encode()
            return service.handle("POST", "/v1/commands/open_review", "Bearer " + token, str(len(raw)), lambda size: raw)
        self.assertEqual(call(of.EXPORTER_TOKEN)[0], 403)
        self.assertEqual(call(of.OPERATOR_TOKEN, {**body, "operator_id": "forged"})[0], 400)
        self.assertEqual((call(of.OPERATOR_TOKEN)[1]["status"], self.status()), ("opened", "queued"))
        before = self.state()
        self.assertEqual(call(of.OPERATOR_TOKEN)[1]["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_later_signal_cannot_be_approved_while_waiting(self):
        """Fresh material alone cannot bypass a later operational blocker; the decision rolls back without writes."""
        self.router.commit_outcome(self.ready_review())
        self.router.raise_signal({"topic_id": rf.TOPIC, "reason_code": "retraction", "signal_source": "operator", "cause_ref": "work", "source_revision": 1, "observed_at": rf.STAMP})
        request = {"decision_id": "opd_wait00001", "topic_id": rf.TOPIC, "kind": "completion_approval", "disposition": "approved",
                   "subject": {"kind": "dossier", "ref": rf.TOPIC, "revision": self.dossier["dossier_revision"], "hash": self.dossier["content_hash"]},
                   "operator_id": "alice", "decided_at": rf.STAMP, "notes": None, "payload": None}
        self.refused_command("apply_operator_decision", request, "decision_refused", status="rejected")
