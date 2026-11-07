"""G-8/E-6: actual sufficiency review and evidence reach operator status; fixture judgments only."""
from unittest.mock import patch
from dataclasses import replace

from gen2.accounting.stopping import GateResult
from gen2.operator.service import OperatorService
from gen2.tests import operator_fixtures as of
from gen2.tests.test_completion_records import World, TOPIC, OTHER
from gen2.tests.test_dossier_record import record_inputs, evaluate


class ReviewStatusTests(World):
    @staticmethod
    def callback(inputs):
        result = evaluate(inputs)
        return replace(result, gates=(GateResult(result.context, "coverage_integrity", "unknown", ()),))

    def review_status(self):
        service = OperatorService(self.router, of.credentials())
        code, doc = service.handle("GET", "/v1/status?topic=" + TOPIC, "Bearer " + of.OPERATOR_TOKEN, None, lambda size: b"")
        self.assertEqual(code, 200, doc)
        return doc["topics"][0]["review"]

    def test_operator_sees_insufficient_summary_and_retained_evidence(self):
        """Literal review text/gates reach the real operator service without writes; no scientific adequacy claim."""
        self.accepted("sufficiency_review")
        before = self.state()
        review = self.review_status()
        self.assertEqual(review["dossier"]["content_hash"], self.dossier["content_hash"])
        self.assertTrue(review["approvable"])
        self.assertEqual(review["dossier"]["gates"], [{"gate": "coverage_integrity", "state": "unknown"}])
        self.assertEqual([(r["outcome"], r["summary"], r["evidence"][0]["text"]) for r in review["reviews"]],
                         [("insufficient", "Recorded by the independent seat", "completion evidence")])
        self.assertEqual(self.state(), before)
        with patch.object(self.spool, "read", return_value=None):
            self.assertIsNone(self.review_status()["reviews"][0]["evidence"][0]["text"])

    def test_only_exact_candidate_reviews_are_presented(self):
        """A newer dossier does not inherit an older revision/hash review; persisted-row oracle, no completion approval."""
        self.accepted("sufficiency_review")
        latest = record_inputs(self.router, TOPIC, invocation_id="inv_capture001", history="native")
        review = self.review_status()
        self.assertEqual((review["dossier"]["revision"], review["dossier"]["content_hash"]), (latest["dossier_revision"], latest["content_hash"]))
        self.assertEqual((review["reviews"], review["approvable"]), ([], False))
        topics = self.router.status({"topic_id": OTHER})["topics"]
        self.assertIsNone(topics[0]["review"])
