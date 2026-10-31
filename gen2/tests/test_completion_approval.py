"""Approval binds the independently reviewed scientific basis at the writer fence."""
import json
from dataclasses import replace
from unittest.mock import patch

from gen2.core import canonical
from gen2.router import gates, material
from gen2.tests import router_fixtures as rf
from gen2.tests.completion_fixtures import completion_world
from gen2.tests.test_registry_dispositions import example_disposition


class ApprovalTest(rf.ContractWorld):
    def setUp(self):
        super().setUp()
        self.f = completion_world(self)

    def refused(self, candidate, reason, fragment, **changes):
        before = self.state(exclude=())
        out = self.f.approve_candidate(candidate, **changes)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assertIn(fragment, out.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)  # audits and generation included
        return out

    def changed(self, **sections):
        grant = self.started(self.ids("inv_"), "checkpoint")
        self.assertEqual(self.finish(grant, self.ids("op_"),
            {**rf.empty_outcome(grant["invocation_id"]), **sections}, refs=[self.ref])["status"], "committed")

    def test_review_only_approves_and_replays_with_exact_status(self):
        candidate = self.f.candidate()
        self.assertIs(self.router._evaluate, gates.evaluate)
        topic = self.router.status({"topic_id": rf.TOPIC})["topics"][0]
        self.assertEqual((topic["completion"], topic["export_delivery"], topic["currency"]), (None, "not_attempted", "unknown"))
        self.assertEqual(self.f.gate_states(), ("satisfied",) * 3)
        self.assertEqual(self.f.approve_candidate(candidate)["status"], "applied")
        topic = self.router.status({"topic_id": rf.TOPIC})["topics"][0]
        self.assertEqual(topic["completion"], {"dossier_revision": 1, "content_hash": candidate["content_hash"], "decision_id": "opd_complete01"})
        self.assertEqual((topic["export_delivery"], topic["currency"]), ("not_attempted", "unknown"))
        self.assertEqual(self.f.approve_candidate(candidate)["status"], "replayed")
        self.refused(candidate, "decision_id_conflict", "different content", hash=rf.h("e"))

    def test_satisfied_and_exact_review_are_required(self):
        candidate = self.f.candidate(review=False)
        self.refused(candidate, "decision_refused", "sufficiency review of this exact dossier revision and hash")
        self.f.review(candidate)
        newer = self.f.candidate(review=False)
        self.refused(newer, "decision_refused", "sufficiency review of this exact dossier revision and hash")
        self.refused(candidate, "decision_refused", "current dossier")
        self.f.review(newer)
        self.assertEqual(self.f.approve_candidate(newer)["status"], "applied")

    def test_unknown_dossier_refuses_even_when_reviewed(self):
        self.f.replace_seed("search_observations", "page_outcome='end_unknown'")
        candidate = self.f.candidate()
        self.assertEqual(json.loads(self.value("SELECT document FROM dossiers"))["result"]["state"], "unknown")
        self.refused(candidate, "decision_refused", "requires a satisfied dossier")

    def test_missing_or_invalid_binding_is_typed_and_effect_free(self):
        candidate = self.f.candidate()
        original = json.loads(self.value("SELECT document FROM dossiers"))
        for binding in (None, "unsupported"):
            doc = dict(original)
            if binding is None:
                del doc["material_digest"]
            else:
                doc["material_digest"] = binding
            self.f.replace_seed("dossiers", "document=?,content_hash=?", canonical.canonical_bytes(doc).decode(), canonical.content_hash(doc))
            self.refused({**candidate, "content_hash": canonical.content_hash(doc)}, "decision_refused", "no supported material binding; reassemble and review")
        self.f.replace_seed("dossiers", "document=?,content_hash=?", canonical.canonical_bytes(original).decode(), candidate["content_hash"])
        self.assertEqual(self.f.approve_candidate(candidate)["status"], "applied")
        self.f.replace_seed("dossiers", "document=?", canonical.canonical_bytes(doc).decode())
        self.assertEqual(self.f.approve_candidate(candidate)["status"], "replayed")

    def test_each_same_gate_output_assessment_change_refuses(self):
        candidate = self.f.candidate()
        for kind, subject, revision, outcome in (("counterevidence_search", "clm_quote00001", 2, "counterevidence_found"),
                ("competing_explanation", "rdp_history00", None, "explanation_stands"),
                ("verification_adjudication", "ver_adverse001", 2, "verdict_overturned")):
            with self.subTest(kind=kind):
                before = self.f.gate_states()
                self.changed(completion_records=[self.f.completion(kind, subject, revision, outcome)])
                self.assertEqual(self.f.gate_states(), before)
                self.refused(candidate, "stale_inputs", "material operands changed since the dossier was assembled")
                candidate = self.f.candidate()  # reviewed control on the changed operands
        self.assertEqual(self.f.approve_candidate(candidate)["status"], "applied")

    def hold(self, kind="judgment"):
        return {"hold_id": self.ids("hold_"), "subject_ref": "claim:clm_quote00001", "hold_class": kind,
            "cause": "Scientific concern", "recoverability": "needs_decision", "required_authority": "primary", "owner": "primary",
            "deadline_at": "2026-10-01T00:00:00Z", "clears_when": "primary resolves the concern", "capability_fact_id": None}

    def test_science_in_review_commit_and_holds_stale_even_with_equal_gates(self):
        for kind in ("judgment", "scope"):
            candidate = self.f.candidate(review=False)
            before = self.f.gate_states()
            self.f.review(candidate, holds=[self.hold(kind)])
            self.assertEqual(self.f.gate_states(), before)
            self.refused(candidate, "stale_inputs", "material operands changed")
        candidate = self.f.candidate(review=False)
        before = self.f.gate_states()
        record = self.f.completion("counterevidence_search", "clm_quote00001", 2, "counterevidence_found")
        # The review and changed scientific assessment are one real final outcome.
        review = self.f.completion("sufficiency_review", rf.TOPIC, candidate["dossier_revision"], "sufficient", subject_hash=candidate["content_hash"])
        self.changed(completion_records=[review, record])
        self.assertEqual(self.f.gate_states(), before)
        self.refused(candidate, "stale_inputs", "material operands changed")
        self.assertEqual(self.f.approve_candidate(self.f.candidate())["status"], "applied")

    def test_claim_contradiction_adverse_receipt_and_amendment_stale(self):
        candidate = self.f.candidate()
        self.changed(claims=[{"claim_id": "clm_quote00001", "revision": 3, "text_ref": self.ref, "load_bearing": True, "required_access_tier": "full_text"}])
        self.refused(candidate, "stale_inputs", "material operands changed")
        candidate = self.f.candidate()
        self.changed(registry_dispositions=[example_disposition(self.ref, 1, contract_revision=self.pin)])
        self.refused(candidate, "stale_inputs", "material operands changed")
        verifier = self.started("inv_adverse002", "verification")
        self.f.verifier = self.f.grant = verifier
        self.assertEqual(self.router.admit_reaccess({**{k: verifier[k] for k in ("capability_id", "invocation_id")},
            "work_id": self.work, "source_version": "v1", "event_id": "rev_quote0000101"})["status"], "admitted")
        doc = self.f.receipt_document(detailed=False, verdict="does_not_support")
        doc["claim"]["claim_revision"] = 2
        doc.update(verification_receipt_id="ver_adverse002", verifier_invocation_id=verifier["invocation_id"], verifier_capability_id=verifier["capability_id"])
        from gen2.tests.detailed_receipt_fixtures import seed_checks
        seed_checks(self.f, doc)
        candidate = self.f.candidate()
        out = self.f.send([], verification_receipts=[doc])
        self.assertEqual(out["status"], "committed", out)
        self.refused(candidate, "stale_inputs", "material operands changed")
        candidate = self.f.candidate()
        self.assertEqual(self.approve(self.propose(3, rf.protocol_changed))["status"], "applied")
        self.refused(candidate, "stale_inputs", "material operands changed")

    def test_operator_feedback_is_material_despite_equal_gate_states(self):
        from gen2.tests.store_fixtures import StoreTestCase
        question = dict(zip(("question_id", "version", "content_hash"), self.rows("SELECT question_id,version,content_hash FROM questions LIMIT 1")[0]))
        spec = StoreTestCase.spec(self, cls="importance_score", document_overrides={"question": question})
        StoreTestCase.decision_receipt(self, "dec_feedback01", "inv_capture001", spec, cls="importance_score", raw=None, status="error")
        candidate = self.f.candidate()
        before = self.f.gate_states()
        out = self.router.apply_operator_decision({"decision_id": "opd_feedback01", "topic_id": rf.TOPIC, "kind": "advised_feedback", "disposition": "recorded",
            "subject": {"kind": "decision_receipt", "ref": "dec_feedback01", "revision": None, "hash": None},
            "operator_id": "user", "decided_at": rf.STAMP, "notes": "The assessment needs a different interpretation", "payload": None})
        self.assertEqual(out["status"], "applied", out)
        self.assertEqual(self.f.gate_states(), before)
        self.refused(candidate, "stale_inputs", "material operands changed")
        self.assertEqual(self.f.approve_candidate(self.f.candidate())["status"], "applied")

    def test_interleaving_is_checked_at_the_fence_and_has_no_approval_effects(self):
        candidate = self.f.candidate()
        digest, states = material.digest, []
        def race(raw, history):
            result = digest(raw, history)
            if not states:
                self.changed(holds=[self.hold()])
                states.append(self.state(exclude=()))
            return result
        with patch.object(material, "digest", race):
            out = self.f.approve_candidate(candidate)
        self.assertEqual((out["status"], out["reason"]), ("rejected", "stale_inputs"))
        self.assertIn("material operands changed", out["detail"])
        self.assertEqual(self.state(exclude=()), states[0])

    def test_benign_epoch_and_unrelated_writes_recapture_but_exhaustion_refuses(self):
        candidate = self.f.candidate()
        digest = material.digest
        for mode in ("epoch", "unrelated", "exhaust"):
            calls, states = [], []
            def race(raw, history):
                calls.append(raw.freshness)
                result = digest(raw, history)
                if len(calls) == 1 or mode == "exhaust":
                    with self.store.transaction():
                        if mode == "epoch":
                            self.x("UPDATE store_generation SET epoch=?", "a" * 32)
                        else:
                            self.store.update("queue_entries", {"topic_id": rf.OTHER}, {"priority": len(calls) + 5})
                    states.append(self.state(exclude=()))
                return result
            audits = self.value("SELECT count(*) FROM audit_events WHERE kind='dossier_input_recaptures'")
            with patch.object(material, "digest", race):
                out = self.f.approve_candidate(candidate, did="opd_recapture_" + mode)
            self.assertEqual(self.value("SELECT count(*) FROM audit_events WHERE kind='dossier_input_recaptures'"), audits)
            if mode == "exhaust":
                self.assertEqual((out["status"], out["reason"]), ("rejected", "stale_inputs"))
                self.assertIn("after two recaptures", out["detail"])
                self.assertEqual(self.state(exclude=()), states[-1])
                self.assertEqual(len(calls), 3)
            else:
                self.assertEqual(out["status"], "applied", out)
                self.assertEqual(len(calls), 2)
                # Requeue the completed topic for the next independent control.
                self.f.replace_seed("queue_entries", "status='active',status_decision_id=NULL")
                candidate = self.f.candidate()

    def test_terminal_file_or_schema_mismatch_refuses_without_recapture(self):
        candidate = self.f.candidate()
        inputs = self.router._accounting.dossier_inputs(rf.TOPIC, history="native")
        token = inputs.raw.freshness
        for stale in (replace(token, file=("different-file",)), replace(token, generation=(*token.generation[:2], token.generation[2] + 1))):
            with patch.object(self.router._accounting, "dossier_inputs", return_value=replace(inputs, raw=replace(inputs.raw, freshness=stale))):
                self.refused(candidate, "stale_inputs", "store file or schema changed after capture")
        self.assertEqual(self.f.approve_candidate(candidate)["status"], "applied")
