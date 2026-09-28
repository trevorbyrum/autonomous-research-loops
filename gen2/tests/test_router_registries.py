"""The router's registries (task 1d): config bundles, the question registry
they carry, and fake qualification records.

Trace: INVARIANTS G-10, RG-9, C-12, D-1, D-4, D-5, D-7, D-11, H-2, §13
(Phase 1: loading, pinning and restart retention of the question registry
with fake or disabled providers; fake qualification and revocation records
exercising the authority fences); DEPLOYMENT-CONTRACT.md §2 (versioned
bundles, pinned in flight; an invalid bundle is refused with a dated fact
and the previous one stays active); gen2/router/registries.py.

Oracles: hand-written expectations; raw SQL read-back of the whole store
(every table but the audit log) for each refusal; bundle identities are
SHA-256 over RFC 8785 bytes (gen2/core/canonical.py, verified against the
RFC's vectors in test_canonical.py), the identity C-13 defines.

Structural limits: no provider runs (D-7): the decision receipts here are
fixture documents, and qualification records are fakes naming no real
evaluation (Phase 3). Durable-store restarts reopen the store in this
process (test_router_restart.py covers a fresh process for the commit path).
"""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
from pathlib import Path

from gen2.core import canonical, instants
from gen2.router import service
from gen2.store import api
from gen2.tests import router_fixtures as rf, store_fixtures
from gen2.tests.router_fixtures import BUNDLE, CONFIG, QUESTION, TOPIC, RouterTestCase, empty_outcome, h, question
from gen2.tests.test_router_evidence import T, ScreeningBase, qual_ref


def bundle(version: int, *, policy: dict | None = None, questions=(QUESTION,)) -> dict:
    return {"bundle_version": "config-bundle/1", "version": version, "policy": policy or {}, "questions": list(questions)}


class ConfigBundleTest(RouterTestCase):
    """RG-9, G-10: versioned, validated, activated; new work pins the active
    bundle, admitted work keeps its own."""

    def activate(self, document: dict) -> dict:
        return self.router.activate_config_bundle(document)

    def refused(self, document: dict, reason: str, detail: str) -> None:
        before = self.state(exclude=("audit_events", "capability_facts"))
        out = self.activate(document)
        self.assertEqual((out["status"], out["reason"]), ("refused", reason), out)
        self.assertIn(detail, out["detail"])
        self.assertEqual(self.state(exclude=("audit_events", "capability_facts")), before)
        self.assertEqual(self.rows("SELECT bundle_hash FROM config_bundles WHERE status = 'active'"), [(CONFIG,)])  # the previous one stays active

    def test_activation_records_the_bundle_its_questions_and_supersedes_the_last(self) -> None:
        q2 = question("Q-method", 1, "Which coherent method-design template fits?")
        second = bundle(2, policy={"supervisor": {"refusal_attempts": 4}}, questions=(QUESTION, q2))
        out = self.activate(second)
        second_hash = canonical.logical_hash(second)
        self.assertEqual(out, {"status": "activated", "bundle_hash": second_hash, "version": 2, "superseded": CONFIG})
        self.assertEqual(self.rows("SELECT bundle_hash, version, status FROM config_bundles ORDER BY version"),
                         [(CONFIG, 1, "superseded"), (second_hash, 2, "active")])
        self.assertEqual(json.loads(self.value("SELECT document FROM config_bundles WHERE version = 2")), second)
        self.assertEqual(self.rows("SELECT question_id, version, content_hash, registered_by_bundle_hash FROM questions ORDER BY question_id DESC"),
                         [("Q-screen", 1, QUESTION["content_hash"], CONFIG), ("Q-method", 1, q2["content_hash"], second_hash)])

    def test_the_active_bundle_again_is_a_replay(self) -> None:
        before = self.state()
        self.assertEqual(self.activate(copy.deepcopy(BUNDLE)), {"status": "replayed", "bundle_hash": CONFIG, "version": 1})
        self.assertEqual(self.state(), before)

    def test_a_version_not_above_every_recorded_one_is_refused(self) -> None:
        self.refused(bundle(1, policy={"router": {"hold_window_s": 60}}), "bundle_invalid", "is not above the newest recorded bundle's 1")
        self.assertEqual(self.activate(bundle(2, policy={"router": {"hold_window_s": 60}}))["status"], "activated")

    def test_a_superseded_bundle_is_never_reactivated(self) -> None:
        self.assertEqual(self.activate(bundle(2))["status"], "activated")
        before = self.state(exclude=("audit_events", "capability_facts"))
        out = self.activate(BUNDLE)
        self.assertEqual((out["status"], out["reason"]), ("refused", "bundle_superseded"), out)
        self.assertEqual(self.state(exclude=("audit_events", "capability_facts")), before)
        self.assertEqual(self.value("SELECT version FROM config_bundles WHERE status = 'active'"), 2)

    def test_an_altered_question_is_refused_and_a_new_version_is_not(self) -> None:
        reworded = question("Q-screen", 1, "Does this work meet criterion C-1?")
        self.refused(bundle(2, questions=(reworded,)), "question_altered", "Q-screen v1 is registered with another content")
        self.assertEqual(self.activate(bundle(2, questions=(QUESTION, question("Q-screen", 2, "Does this work meet criterion C-1?"))))["status"], "activated")
        self.assertEqual(self.rows("SELECT question_id, version FROM questions ORDER BY version"), [("Q-screen", 1), ("Q-screen", 2)])

    def test_a_question_that_does_not_hash_to_its_label_is_refused(self) -> None:
        self.refused(bundle(2, questions=({**question("Q-other"), "content_hash": h("4")},)), "bundle_invalid", "does not hash to its content hash")

    def test_a_question_version_twice_is_refused(self) -> None:
        self.refused(bundle(2, questions=(QUESTION, QUESTION)), "bundle_invalid", "appears twice")

    def test_a_bundle_the_schema_refuses_is_refused(self) -> None:
        self.refused(bundle(2, policy={"supervisor": {"refusal_attempt": 4}}), "bundle_invalid", "config-bundle.schema.json")

    def test_a_refusal_is_a_dated_fact_raised_on_the_transition_only(self) -> None:
        for _ in range(2):
            self.assertEqual(self.activate(bundle(1, policy={"router": {"hold_window_s": 1}}))["status"], "refused")
        facts = self.rows("SELECT state, superseded_by_fact_id IS NULL FROM capability_facts WHERE capability = 'config-bundle' ORDER BY rowid")
        self.assertEqual(facts, [("failing", 1)])  # one fact for two refusals (H-2)
        self.assertEqual(self.activate(bundle(2))["status"], "activated")
        self.assertEqual(self.rows("SELECT state, superseded_by_fact_id IS NULL FROM capability_facts WHERE capability = 'config-bundle' ORDER BY rowid"),
                         [("failing", 0), ("healthy", 1)])

    def test_new_work_pins_the_active_bundle(self) -> None:
        self.to_queued()
        second = bundle(2)
        self.activate(second)
        before = self.state()
        refused = self.claim("inv_research01")
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "config_bundle_not_active"), refused)
        self.assertEqual(self.state(), before)
        grant = self.claim("inv_research01", config_bundle_hash=canonical.logical_hash(second))
        self.assertEqual(grant["status"], "granted", grant)
        self.assertEqual(self.value("SELECT config_bundle_hash FROM invocations WHERE invocation_id = 'inv_research01'"), canonical.logical_hash(second))

    def test_no_active_bundle_admits_no_work(self) -> None:
        db = store_fixtures.connect()
        try:
            router = service.Router(api.adopt_in_memory(db), rf.Spool(), clock=rf.Clock())
            db.execute("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)",
                       (TOPIC, "2026-09-27T09:00:00Z", "2026-09-27T09:00:00Z"))
            refused = router.claim({"invocation_id": "inv_research01", "kind": "discovery", "topic_id": TOPIC, "config_bundle_hash": CONFIG,
                                    "deadline_at": rf.DEADLINE, "station_id": "station-1", "lease_expires_at": rf.EXPIRES})
            self.assertEqual((refused["status"], refused["reason"]), ("refused", "config_bundle_not_active"), refused)
            self.assertEqual(db.execute("SELECT count(*) FROM invocations").fetchone(), (0,))
        finally:
            db.close()

    def test_admitted_work_keeps_its_pinned_bundle(self) -> None:
        """A commit and a delegate of work admitted under bundle 1 keep bundle
        1 after bundle 2 is activated; the receipt records the policy it ran
        under (C-12, RG-9)."""
        self.to_queued()
        parent = self.started("inv_research01")
        self.activate(bundle(2))
        refused = self.claim("inv_deleg001", "delegate", parent=parent, config_bundle_hash=canonical.logical_hash(bundle(2)))
        self.assertEqual(refused.get("reason"), "config_bundle_mismatch")
        delegate = self.claim("inv_deleg001", "delegate", parent=parent)
        self.assertEqual((delegate["status"], delegate["config_bundle_hash"]), ("granted", CONFIG))
        self.assertEqual(self.value("SELECT config_bundle_hash FROM invocations WHERE invocation_id = 'inv_deleg001'"), CONFIG)
        self.assertEqual(self.router.request_cancel({"invocation_id": "inv_deleg001", "requested_by": "operator", "reason": "not needed"})["status"], "cancelled")
        response = self.finish(parent, "op_final000001")
        self.assertEqual(response["status"], "committed", response)
        self.assertEqual(self.rows("SELECT config_bundle_hash, policy_version FROM operation_receipts"), [(CONFIG, "config-bundle/1")])
        self.assertEqual(response["receipt"]["validation"]["policy_version"], "config-bundle/1")

    def hold_window(self, invocation_id: str) -> int:
        created, deadline = self.rows("SELECT created_at, deadline_at FROM holds WHERE subject_ref = ?", f"invocation:{invocation_id}#unknown:1")[0]
        return (instants.utc_instant_ns(deadline) - instants.utc_instant_ns(created)) // 10**9

    def test_an_episode_holds_window_is_its_pinned_bundles(self) -> None:
        """G-10: the router's hold window (shipped: one hour) is the value of
        the bundle the invocation is pinned to, not the active one's."""
        self.to_queued()
        first = self.started("inv_research01")
        self.activate(bundle(2, policy={"router": {"hold_window_s": 120}}))
        second = self.started("inv_checkpt01", "checkpoint", config_bundle_hash=canonical.logical_hash(bundle(2, policy={"router": {"hold_window_s": 120}})))
        for grant in (first, second):
            out = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "to_state": "outcome_unknown",
                                                 "unknown_episode": 1, "unknown_cause": "contact_lost"})
            self.assertEqual(out["status"], "recorded", out)
        self.assertEqual((self.hold_window("inv_research01"), self.hold_window("inv_checkpt01")), (3600, 120))


class QuestionPinTest(ScreeningBase):
    """D-1: a decision commits only under a spec whose question the committing
    invocation's pinned bundle carries, under exactly its hash."""

    def test_a_spec_whose_question_the_pinned_bundle_lacks_is_refused(self) -> None:
        q2 = question("Q-screen", 2, "Does this work meet criterion C-1 of the pinned protocol?")
        second = bundle(2, questions=(QUESTION, q2))
        self.assertEqual(self.router.activate_config_bundle(second)["status"], "activated")  # registers Q-screen v2: a spec may pin it
        doc = self.spec_document("dspec_screen0002")
        doc["question"] = {k: q2[k] for k in ("question_id", "version", "content_hash")}
        spec_hash = canonical.logical_hash(doc)
        self.x("INSERT INTO decision_specs (spec_hash, spec_id, decision_class, provider, primitive, policy_id, policy_version, protocol_topic_id, document, created_at) "
               "VALUES (?, ?, 'screening', 'jev', 'choice', 'P1', 1, ?, ?, ?)", spec_hash, doc["spec_id"], TOPIC, json.dumps(doc), T)
        self.qualify(self.spec_hash, spec_hash)
        spec = ("dspec_screen0002", spec_hash)
        # inv_research01 was admitted under bundle 1, which does not carry Q-screen v2
        self.refused(self.grant, "op_screen00001", self.provider(spec=spec), "payload_invalid", refs=[self.raw], detail="not in the invocation's pinned question registry")
        self.committed(self.grant, "op_screen00001", self.provider(), refs=[self.raw])  # its own spec, Q-screen v1, commits


class QualificationRecordTest(ScreeningBase):
    """D-4, D-5, D-11: fake records exercise the fences end to end; a record
    qualifies exactly one (provider, class, spec); revocation takes effect for
    every commit after it and reinterprets nothing committed."""

    def setUp(self) -> None:
        super().setUp()
        self.qualify(self.spec_hash)

    def grant_request(self, spec_hash: str, **changes) -> dict:
        return {"qualification_id": qual_ref(spec_hash), "provider": "jev", "decision_class": "screening", "spec_hash": spec_hash,
                "evaluation_ref": "fake-evaluation-1", "operator_id": "user", **changes}

    def test_a_record_replays_and_conflicts_by_its_id(self) -> None:
        before = self.state()
        self.assertEqual(self.router.record_qualification(self.grant_request(self.spec_hash)), {"status": "replayed", "qualification_id": qual_ref(self.spec_hash)})
        out = self.router.record_qualification(self.grant_request(self.spec_hash, evaluation_ref="fake-evaluation-2"))
        self.assertEqual((out["status"], out["reason"]), ("refused", "qualification_conflict"))
        self.assertEqual(self.state(), before)

    def test_a_record_qualifies_only_its_specs_provider_and_class(self) -> None:
        other = self.spec("dspec_screen0005")
        before = self.state()
        for name, changes in (("another class", {"decision_class": "method_selection"}), ("another provider", {"provider": "llm_fallback"}),
                              ("an unknown spec", {"spec_hash": h("e")})):
            with self.subTest(name):
                out = self.router.record_qualification({**self.grant_request(other), **changes})
                self.assertEqual((out["status"], out["reason"]), ("refused", "qualification_invalid"), out)
                self.assertEqual(self.state(), before)
        self.assertEqual(self.router.record_qualification(self.grant_request(other))["status"], "recorded")

    def test_a_reference_to_another_specs_record_is_not_qualification(self) -> None:
        spec = ("dspec_screen0006", self.spec("dspec_screen0006"))  # never qualified
        receipt = self.decision_receipt("op_screen00001", spec=spec)
        receipt["authorization"]["qualification_ref"] = qual_ref(self.spec_hash)  # a live record, of another spec
        outcome = self.screen(self.assessment(actor="decision_provider", receipt="dec_000000000001"), receipts=[receipt])
        self.refused(self.grant, "op_screen00001", outcome, "payload_invalid", refs=[self.raw], detail="no live qualification record")
        self.committed(self.grant, "op_screen00001", self.provider(), refs=[self.raw])

    def test_revocation_takes_effect_and_reinterprets_nothing(self) -> None:
        self.committed(self.grant, "op_screen00001", self.provider(), refs=[self.raw])
        committed = self.rows("SELECT * FROM decision_receipts")
        out = self.router.revoke_qualification({"qualification_id": qual_ref(self.spec_hash), "operator_id": "user", "reason": "held-out drift"})
        self.assertEqual(out, {"status": "revoked", "qualification_id": qual_ref(self.spec_hash)})
        self.assertEqual(self.rows("SELECT revoked_by, revoke_reason FROM qualifications"), [("user", "held-out drift")])
        again = self.provider("op_screen00002")
        again["decision_receipts"][0]["decision_receipt_id"] = "dec_000000000002"
        again["screening_assessments"][0].update(assessment_id="asm_000000000002", decision_receipt_id="dec_000000000002")
        self.refused(self.grant, "op_screen00002", again, "payload_invalid", refs=[self.raw], detail="no live qualification record")
        self.assertEqual(self.rows("SELECT * FROM decision_receipts"), committed)  # the committed decision stands as it was (D-4)
        advisory = self.screen(receipts=[{**self.decision_receipt("op_screen00002", authority="advisory"), "decision_receipt_id": "dec_000000000002"}])
        self.committed(self.grant, "op_screen00002", advisory, refs=[self.raw])  # unqualified: advisory at most (D-5)

    def test_a_revocation_between_validation_and_the_write_is_seen(self) -> None:
        def revoke(point: str) -> None:
            if point == "after_validation":
                self.router.revoke_qualification({"qualification_id": qual_ref(self.spec_hash), "operator_id": "user", "reason": "revoked mid-commit"})
        self.router = self.make_router(fault=revoke)
        before = self.state(exclude=("audit_events", "qualifications"))
        response = self.router.commit_outcome(self.envelope(self.grant, "op_screen00001", self.provider(), refs=[self.raw]))
        self.assertEqual((response["status"], response["reason"]), ("rejected", "payload_invalid"), response)
        self.assertIn("revoked meanwhile", response["detail"])
        self.assertEqual(self.state(exclude=("audit_events", "qualifications")), before)
        self.assertEqual(self.rows("SELECT revoke_reason FROM qualifications"), [("revoked mid-commit",)])

    def test_the_same_revocation_again_replays(self) -> None:
        """The accepted path of the revocation-conflict guard, on its own: the
        identical revocation of a revoked record replays and changes nothing."""
        revocation = {"qualification_id": qual_ref(self.spec_hash), "operator_id": "user", "reason": "drift"}
        self.assertEqual(self.router.revoke_qualification(revocation)["status"], "revoked")
        before = self.state()
        self.assertEqual(self.router.revoke_qualification(revocation), {"status": "replayed", "qualification_id": qual_ref(self.spec_hash)})
        self.assertEqual(self.state(), before)

    def test_revocation_replays_conflicts_and_needs_a_record(self) -> None:
        revocation = {"qualification_id": qual_ref(self.spec_hash), "operator_id": "user", "reason": "drift"}
        self.assertEqual(self.router.revoke_qualification(revocation)["status"], "revoked")
        before = self.state()
        self.assertEqual(self.router.revoke_qualification(revocation)["status"], "replayed")
        for name, request, reason in (("another reason", {**revocation, "reason": "other"}, "qualification_conflict"),
                                      ("no such record", {**revocation, "qualification_id": "qual_nosuchrecord"}, "unknown_qualification")):
            with self.subTest(name):
                out = self.router.revoke_qualification(request)
                self.assertEqual((out["status"], out["reason"]), ("refused", reason), out)
        self.assertEqual(self.state(), before)


class RegistryRestartTest(RouterTestCase):
    """RG-9: bundles, questions and qualification records are store state: a
    reopened store resolves every pin and keeps every revocation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        api.open_store(self.directory / "store.sqlite3", create=True).close()
        self.db = sqlite3.connect(self.directory / "store.sqlite3", isolation_level=None)
        self.db.executescript(store_fixtures.CONNECTION_TEXT)
        self.store = api.open_store(self.directory / "store.sqlite3")
        self.spool, self.clock, self.ids, self.faults = rf.Spool(), rf.Clock(), rf.Ids(), {}
        self.router = self.make_router()
        self.seed()

    def tearDown(self) -> None:
        self.router.close()
        self.db.close()
        self._tmp.cleanup()

    def reopen(self) -> None:
        self.router.close()
        self.store = api.open_store(self.directory / "store.sqlite3")
        self.router = self.make_router()

    def test_pins_and_registries_survive_a_restart(self) -> None:
        self.to_queued()
        grant = self.started("inv_research01")
        second = bundle(2, policy={"router": {"hold_window_s": 60}}, questions=(QUESTION, question("Q-method")))
        self.router.activate_config_bundle(second)
        tables = ("config_bundles", "questions", "invocations")
        before = {t: self.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in tables}
        self.reopen()
        self.assertEqual({t: self.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in tables}, before)
        self.assertEqual(self.router.activate_config_bundle(second)["status"], "replayed")  # the same mounted bundle at the next start
        self.assertEqual(self.router.config_bundle(CONFIG), BUNDLE)  # a superseded pin still resolves
        out = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": "inv_research01", "to_state": "outcome_unknown",
                                             "unknown_episode": 1, "unknown_cause": "contact_lost"})
        self.assertEqual(out["status"], "recorded")
        created, deadline = self.rows("SELECT created_at, deadline_at FROM holds")[0]
        self.assertEqual((instants.utc_instant_ns(deadline) - instants.utc_instant_ns(created)) // 10**9, 3600)  # bundle 1's window, not 2's

    def test_a_revocation_survives_a_restart(self) -> None:
        self.x("INSERT INTO decision_specs (spec_hash, spec_id, decision_class, provider, primitive, policy_id, policy_version, protocol_topic_id, document, created_at) "
               "VALUES (?, 'dspec_screen0001', 'screening', 'jev', 'choice', 'P1', 1, NULL, ?, ?)", h("5"),
               json.dumps({"spec_id": "dspec_screen0001", "provider": "jev", "decision_class": "screening", "primitive": "choice", "options": {"a": {}, "b": {}},
                           "action_policy": {"policy_id": "P1", "version": 1}, "protocol": {"eligibility_protocol_version": 1},
                           "question": {k: QUESTION[k] for k in ("question_id", "version", "content_hash")}}), T)
        grant = {"qualification_id": "qual_restart01", "provider": "jev", "decision_class": "screening", "spec_hash": h("5"), "evaluation_ref": "fake", "operator_id": "user"}
        self.assertEqual(self.router.record_qualification(grant)["status"], "recorded")
        self.assertTrue(self.router.is_qualified(provider="jev", decision_class="screening", spec_hash=h("5"), qualification_ref="qual_restart01"))
        self.router.revoke_qualification({"qualification_id": "qual_restart01", "operator_id": "user", "reason": "drift"})
        self.reopen()
        self.assertFalse(self.router.is_qualified(provider="jev", decision_class="screening", spec_hash=h("5"), qualification_ref="qual_restart01"))
        self.assertEqual(self.router.record_qualification(grant)["status"], "replayed")  # the record is kept; revocation is final
