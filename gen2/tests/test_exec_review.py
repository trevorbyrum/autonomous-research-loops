"""Dossier recorder and review view/builder (T16 PR2). Oracles: outcome-document, completion-record and judgment-review
schemas (SchemaSet); the real router for the recorder's replay, the builder's admission and the operator's approval of the
exact revision (the last class). Limits: the supervisor's own retry and fail-closed ends are T12-B's witnesses; the
unit rows are hand-built to topic_records' shape.
"""
import json
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.exec import common, dossier, review
from gen2.router.schemas import SchemaSet
from gen2.tests import children
from gen2.tests import router_fixtures as rf
from gen2.tests.completion_fixtures import completion_world

SCHEMAS = SchemaSet()
ADMISSION = {"context": "contract/1", "contract": {"revision": 1, "content_hash": "sha256:" + "a" * 64}}
ME = "inv_reviewer1"
HASH = "sha256:" + "d" * 64


def dossier_row(**over):
    gates = [{"gate": g, "state": "satisfied"} for g in ("challenge_pass_completed", "coverage_integrity", "load_bearing_verification_tiers")]
    return {"dossier_revision": 3, "content_hash": HASH, "contract_revision": 1, "invocation_id": "inv_dossier1",
            "document": {"result": {"state": "satisfied", "gates": gates}}, **over}


def records(**over):
    return {"dossiers": [dossier_row()], "verification_receipts": [], "completion_records": [], **over}


def stage(data, media):
    return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": media}


class FakeControl:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def record_dossier(self, request):
        self.requests.append(request)
        return self.answers.pop(0)


class RecorderTest(unittest.TestCase):
    ORDER, GRANT = {"invocation_id": "inv_dossier1", "topic_id": "fleet:topic"}, {"capability_id": "cap_aaaaaaaa"}

    def test_the_request_names_the_invocation_and_accepts_recorded_or_replayed(self):
        control = FakeControl({"status": "recorded"}, {"status": "replayed"})
        dossier.record(control, self.ORDER, self.GRANT, None)
        dossier.record(control, self.ORDER, self.GRANT, None)
        self.assertEqual(control.requests, [{"capability_id": "cap_aaaaaaaa", "invocation_id": "inv_dossier1", "topic_id": "fleet:topic"}] * 2)

    def test_a_refusal_raises_so_the_supervisor_spends_an_attempt(self):
        with self.assertRaises(common.Refused) as caught:
            dossier.record(FakeControl({"status": "refused", "reason": "lease_not_current", "detail": "late"}), self.ORDER, self.GRANT, None)
        self.assertIn("lease_not_current", str(caught.exception))

    def test_the_job_outcome_is_an_empty_outcome(self):
        out = dossier.build_dossier({"invocation_id": "inv_dossier1", "topic_id": "fleet:topic"}, {})
        self.assertEqual(SCHEMAS.errors(out, "outcome-document.schema.json"), [])
        self.assertFalse(any(out[k] for k in out if isinstance(out[k], list)))


class ViewTest(unittest.TestCase):
    def view(self, recs=None, **over):
        return review.review_view(ADMISSION, recs or records(), **{"invocation_id": ME, "dossier_revision": 3, **over})

    def test_view_names_the_exact_revision_and_its_gates(self):
        got = self.view(records(verification_receipts=[{"verification_receipt_id": "ver_00000001", "claim_id": "clm_00000001", "claim_revision": 2,
                                                         "verdict": "does_not_support", "access_tier": "abstract"}],
                                completion_records=[{"kind": "counterevidence_search", "subject_ref": "clm_00000001", "assessment": {"outcome": "incomplete"}}]))
        self.assertEqual((got["dossier"]["revision"], got["dossier"]["content_hash"], got["dossier"]["state"]), (3, HASH, "satisfied"))
        self.assertEqual(len(got["dossier"]["gates"]), 3)
        self.assertEqual([r["verdict"] for r in got["receipts"]], ["does_not_support"])
        self.assertEqual(got["completion_records"], [{"kind": "counterevidence_search", "subject_ref": "clm_00000001", "outcome": "incomplete"}])

    def test_refusals(self):
        for case, call in (("other admission", lambda: review.review_view({"context": "pre-contract/1"}, records(), invocation_id=ME, dossier_revision=3)),
                           ("revision not present", lambda: self.view(dossier_revision=2)),
                           ("revision twice", lambda: self.view(records(dossiers=[dossier_row(), dossier_row()]))),
                           ("the reviewer produced it", lambda: self.view(invocation_id="inv_dossier1"))):
            with self.subTest(case), self.assertRaises(common.Refused):
                call()


class BuilderTest(unittest.TestCase):
    def build(self, **over):
        view = ViewTest().view()
        work = {"invocation_id": ME, "topic_id": "fleet:topic", "view": view}
        return review.make_builder(stage)(work, {"judgment_version": "judgment-review/1", "outcome": "sufficient", "summary": "ok", **over})

    def test_one_review_bound_to_the_viewed_revision_and_hash(self):
        out = self.build()
        self.assertEqual(SCHEMAS.errors(out, "outcome-document.schema.json"), [])
        (record,) = out["completion_records"]
        self.assertEqual((record["kind"], record["subject_ref"], record["subject_revision"], record["subject_hash"], record["contract_revision"]),
                         ("sufficiency_review", "fleet:topic", 3, HASH, 1))
        self.assertEqual(self.build()["completion_records"], out["completion_records"])   # a replay builds the same record

    def test_an_outcome_outside_the_pair_is_refused(self):
        with self.assertRaises(common.Refused):
            self.build(outcome="approved")

    def test_example_and_prompt_agree_with_the_schema(self):
        prompt = Path(children.path("gen2/prompts/checkpoint.review.md")).read_text()
        example = json.loads(prompt.split("```json\n")[1].split("\n```")[0])
        self.assertEqual(SCHEMAS.errors(example, "judgment-review.schema.json"), [])


class WholeFlowTest(rf.ContractWorld):
    """Dossier job, fresh review, then the operator's approval of that exact revision, all through the real router."""

    def setUp(self):
        super().setUp()
        self.f = completion_world(self)

    def staged(self, data, media):
        self.refs.append(self.artifact(data, media))
        return self.refs[-1]

    def dossier_job(self):
        grant = self.started(self.ids("inv_"), "checkpoint")
        order = {"invocation_id": grant["invocation_id"], "topic_id": rf.TOPIC}
        dossier.record(self.router, order, grant, None)
        dossier.record(self.router, order, grant, None)   # a repeat after a lost marker adds nothing
        again = self.router.record_dossier({**order, "capability_id": grant["capability_id"]})
        self.assertEqual(again["status"], "replayed")
        rows = self.router.topic_records({"topic_id": rf.TOPIC, "families": ["dossiers"], "dossier_revision": again["dossier_revision"]})["records"]["dossiers"]
        self.assertEqual(len(rows), 1)
        outcome = dossier.build_dossier({"invocation_id": grant["invocation_id"], "topic_id": rf.TOPIC}, {})
        self.assertEqual(self.finish(grant, self.ids("op_"), outcome)["status"], "committed")
        return rows[0]

    def test_dossier_then_fresh_review_then_approval_of_the_exact_revision(self):
        row = self.dossier_job()
        reviewer = self.started(self.ids("inv_"), "checkpoint")
        got = self.router.topic_records({"topic_id": rf.TOPIC, "families": list(review.FAMILIES), "dossier_revision": row["dossier_revision"]})["records"]
        admission = {"context": "contract/1", "contract": {"revision": row["contract_revision"]}}
        view = review.review_view(admission, got, invocation_id=reviewer["invocation_id"], dossier_revision=row["dossier_revision"])
        self.refs = []
        outcome = review.make_builder(self.staged)({"invocation_id": reviewer["invocation_id"], "topic_id": rf.TOPIC, "view": view},
                                                    {"judgment_version": "judgment-review/1", "outcome": "sufficient", "summary": "ok"})
        out = self.finish(reviewer, self.ids("op_"), outcome, refs=self.refs)
        self.assertEqual(out["status"], "committed", out)
        applied = self.f.approve_candidate({"dossier_revision": row["dossier_revision"], "content_hash": row["content_hash"]})
        self.assertEqual(applied["status"], "applied", applied)

    def test_the_producer_cannot_review_its_own_dossier(self):
        row = self.dossier_job()
        got = self.router.topic_records({"topic_id": rf.TOPIC, "families": list(review.FAMILIES), "dossier_revision": row["dossier_revision"]})["records"]
        with self.assertRaises(common.Refused):
            review.review_view({"context": "contract/1"}, got, invocation_id=row["invocation_id"], dossier_revision=row["dossier_revision"])

    def test_a_non_checkpoint_capability_cannot_record_a_dossier(self):
        grant = self.started(self.ids("inv_"), "verification")
        with self.assertRaises(common.Refused):
            dossier.record(self.router, {"invocation_id": grant["invocation_id"], "topic_id": rf.TOPIC}, grant, None)
