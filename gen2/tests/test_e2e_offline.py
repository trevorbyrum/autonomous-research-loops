"""The whole workflow, offline, on a fresh store (2e2-min T18; plan §4.4; Gate S #7 §5.3). One topic walked from a brief to an approved
completion by the production driver, with the operator's steps (through the router's own commands) between its waits.

Oracle: the router's records, read back through its own `topic_records` and `status` (the approved dossier's record families and the
status `review` block), and the supervisor's refusal when a recorder is missing. What is real: the station, the router and store, the
supervisor and its subprocess executors, the production child, builders, views, recorders and discovery client. What is canned: the model
(`OfflineAgent`, fixed judgments) and the gateway (`OfflineGateway`); each fixture cites the artifact it replays in its own module
(`offline_gateway`: T12-G's adapter-shaped Semantic Scholar record, gen2/tests/fixtures/gateway_answers/semanticscholar_abstract.json;
`offline_agent`: the judgment schemas and examples under gen2/schema/examples/judgment-*). Limits: it proves wiring and the record
families, not research quality; the three failures that are proven at their own layers are not repeated here.

The coverage witness reaches the completion-approval wait with a satisfied dossier.
The separate reviewed state-machine hand-off extends this same walk through approval.
"""
import unittest

from gen2.supervisor.supervisor import RecorderMissing
from gen2.tests.offline_run import Offline

class WholeWorkflowTest(unittest.TestCase):
    def test_one_topic_from_brief_to_a_satisfied_review_through_production_routes_only(self):
        run = Offline()
        self.addCleanup(run.close)
        self.assertIn("waiting for: the dossier and its review await", run.walk(until="completion_approval"))
        topic = run.topic()
        self.assertEqual(topic["status"], "resting")
        review = topic["review"]
        self.assertEqual([(g["gate"], g["state"]) for g in review["dossier"]["gates"]],
                         [("load_bearing_verification_tiers", "satisfied"), ("challenge_pass_completed", "satisfied"), ("coverage_integrity", "satisfied")])
        self.assertEqual((review["dossier"]["state"], review["reviews"][0]["outcome"], review["approvable"]), ("satisfied", "sufficient", True))
        self.assertIsNone(topic["completion"])
        # the approved dossier's record families, each written by its own production route
        families = {name: run.records(name) for name in ("scoping_reports", "search_observations", "works", "claims", "claim_source_links", "source_artifacts",
                                                         "source_acquisitions", "verification_receipts", "detailed_check_records", "quote_checks", "completion_records")}
        self.assertEqual({name: len(rows) for name, rows in families.items() if name != "search_observations"},
                         {"scoping_reports": 1, "works": 2, "claims": 1, "claim_source_links": 1, "source_artifacts": 1, "source_acquisitions": 1,
                          "verification_receipts": 1, "detailed_check_records": 4, "quote_checks": 1, "completion_records": 2})
        self.assertEqual(sorted(r["kind"] for r in families["completion_records"]), ["counterevidence_search", "sufficiency_review"])
        self.assertEqual(len(families["search_observations"]), 3)
        self.assertTrue(all("proposal_ref" in o["request"] for o in families["search_observations"]))
        (receipt,) = families["verification_receipts"]
        self.assertEqual((receipt["verdict"], receipt["access_tier"], receipt["extraction_method"]), ("supports", "abstract", "canonical_bytes"))
        self.assertEqual([q["exact_match"] for q in families["quote_checks"]], ["matched"])

    def test_removing_any_of_the_three_recorders_fails_the_run(self):
        """The DEBT-051 condition: each recorded purpose refuses to be submitted on a station that lacks its recorder."""
        for key in ("discovery/search", "verification/verify", "checkpoint/dossier"):
            with self.subTest(key):
                run = Offline(without_recorder=key)
                self.addCleanup(run.close)
                with self.assertRaises(RecorderMissing):
                    run.walk()
