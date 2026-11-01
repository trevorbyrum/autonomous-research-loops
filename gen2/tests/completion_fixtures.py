"""Derivable completion candidates; only fixture setup edits immutable seed data."""
import json

from gen2.core import canonical
from gen2.router import gates
from gen2.router.boundary import Refusal
from gen2.tests import router_fixtures as rf
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks
from gen2.tests.extraction_receipt_fixtures import seed
from gen2.tests.test_registry_dispositions import example_disposition


class CompletionFixture(rf.CaptureCase):
    def __init__(self, case):
        # Reuse this world's store and assertions, with the quote fixture's helpers.
        self.__dict__ = case.__dict__

    def prepare(self):
        self.router = rf.RouterTestCase.make_router(self, gateway_captures=self)
        self.capture_grant = self.started("inv_capture001")
        events = self.observe(self.capture_grant, "obs_quote00001", ("quote-record",))
        self.work = self.register(self.capture_grant, [("doi", "10.1/quote", events)])["works"][0]["work_id"]
        self.source = self.artifact(self.SOURCE_BYTES, self.SOURCE_MEDIA)
        self.text = self.artifact(b"effect observed")
        self.assertEqual(self.send([], grant=self.capture_grant, refs=[self.source, self.text],
            source_artifacts=[{"work_id": self.work, "source_version": "v1", "artifact_ref": self.source}],
            claims=[{"claim_id": "clm_quote00001", "revision": 1, "text_ref": self.text, "load_bearing": False, "required_access_tier": None}])["status"], "committed")
        self.grant = self.started("inv_verify0001", "verification")
        self.assertEqual(self.router.admit_reaccess({**{k: self.grant[k] for k in ("capability_id", "invocation_id")},
            "work_id": self.work, "source_version": "v1", "event_id": events[0]})["status"], "admitted")
        seed(self)
        self.verifier = self.grant
        seed_checks(self, self.receipt_document(detailed=False))
        self.new_capture(2, b"effect observed")
        quote, receipt = self.operands()
        self.assertEqual(self.send([quote], verification_receipts=[receipt])["status"], "committed")
        self.promote()
        self.ref = self.artifact(b"independent review and challenge evidence")
        self.cp = self.started("inv_challenge01", "checkpoint")
        self.pin = self.value("SELECT active_contract_revision FROM queue_entries WHERE topic_id=?", rf.TOPIC)
        self.assertEqual(self.send([], grant=self.cp, refs=[self.ref], registry_dispositions=[example_disposition(self.ref, 0, contract_revision=self.pin)])["status"], "committed")
        adverse = self.receipt_document(verdict="does_not_support")
        adverse["verification_receipt_id"] = "ver_adverse001"
        adverse["claim"]["claim_revision"] = 2
        attach_checks(self, adverse)
        self.assertEqual(self.send([], verification_receipts=[adverse])["status"], "committed")
        records = [self.completion("counterevidence_search", "clm_quote00001", 2, "none_found"),
            self.completion("competing_explanation", "rdp_history00", None, "explanation_rejected"),
            self.completion("verification_adjudication", "ver_adverse001", 2, "verdict_upheld")]
        self.assertEqual(self.send([], grant=self.cp, refs=[self.ref], completion_records=records)["status"], "committed")
        for grant in (self.cp, self.grant, self.capture_grant):
            self.assertEqual(self.finish(grant, self.ids("op_"))["status"], "committed")
        sentinel = self.artifact(canonical.canonical_bytes([self.work]), "application/json")
        doc = json.loads(self.value("SELECT document FROM contract_revisions WHERE status='approved'"))
        doc.setdefault("stopping_profiles", rf.contract_doc(1, None)["stopping_profiles"])
        profile = doc["stopping_profiles"][0]
        profile.update(rules=[{"rule_id": "R", "family": "known_item", "evaluation": "automatic",
            "params": {"sentinel_set": sentinel, "tests": "retrieval", "seeded_into_prompts": False}}], completion_condition={"rule": "R"})
        doc["content_hash"] = canonical.content_hash(doc)
        self.replace_seed("contract_revisions", "document=?,content_hash=?", canonical.canonical_bytes(doc).decode(), canonical.content_hash(doc))
        self.replace_seed("search_observations", "page_outcome='exhausted'")
        self.x("UPDATE queue_entries SET status='active',state_revision=state_revision+1 WHERE topic_id=?", rf.TOPIC)
        return self

    def replace_seed(self, table, assignment, *params):
        triggers = self.rows("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", table)
        for name, _ in triggers:
            self.x(f"DROP TRIGGER {name}")
        self.x(f"UPDATE {table} SET {assignment}" + (" WHERE status='approved'" if table == "contract_revisions" else ""), *params)
        for _, sql in triggers:
            self.x(sql)

    def completion(self, kind, subject, revision, outcome, **changes):
        return {"record_id": self.ids("cr_"), "kind": kind, "contract_revision": self.pin,
            "subject_ref": subject, "subject_revision": revision, "subject_hash": None,
            "assessment": {"outcome": outcome, "summary": "Independent attributed assessment"}, "evidence_refs": [self.ref], **changes}

    def candidate(self, review=True, **sections):
        producer = self.started(self.ids("inv_"), "checkpoint")
        try:
            out = self.router.record_dossier(rf.TOPIC, invocation_id=producer["invocation_id"], history="native")
        except (ValueError, Refusal) as exc:
            if str(exc) not in ("R: sentinel inventory required", "stale_inputs: dossier context differs from captured approved contract"):
                raise
            self.fail(f"completion-candidate-recording: expected a recorded dossier, raised {type(exc).__name__}: {exc}")
        self.assertEqual(out["status"], "recorded", "completion-candidate-recording")
        self.assertEqual(self.finish(producer, self.ids("op_"))["status"], "committed")
        if review:
            self.review(out, **sections)
        return out

    def review(self, dossier, **sections):
        reviewer = self.started(self.ids("inv_"), "checkpoint")
        record = self.completion("sufficiency_review", rf.TOPIC, dossier["dossier_revision"], "insufficient", subject_hash=dossier["content_hash"])
        self.assertEqual(self.finish(reviewer, self.ids("op_"),
            {**rf.empty_outcome(reviewer["invocation_id"]), "completion_records": [record], **sections}, refs=[self.ref])["status"], "committed")

    def approve_candidate(self, dossier, did="opd_complete01", **changes):
        return self.decide(did, "completion_approval", {"kind": "dossier", "revision": dossier["dossier_revision"], "hash": dossier["content_hash"], **changes})

    def gate_states(self):
        inputs = self.router._accounting.dossier_inputs(rf.TOPIC, history="native")
        return tuple(g.state for g in gates.evaluate(inputs, self.spool, rf.STAMP).gates)


def completion_world(case):
    return CompletionFixture(case).prepare()
