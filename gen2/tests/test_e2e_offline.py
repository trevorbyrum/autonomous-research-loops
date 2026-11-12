"""The whole workflow, offline, on a fresh store (2e2-min T18; plan §4.4; Gate S #7 §5.3). One topic walked from a brief to an approved
completion by the production driver, with the operator's steps (through the authenticated CLI/listener) between its waits.

Oracles: independent read-only SQL for the persisted records, plus listener status (the approved dossier's record families and the
status `review` block), and the supervisor's refusal when a recorder is missing. What is real: the station, the router and store, the
supervisor and its subprocess executors, the production child, builders, views, recorders and discovery client. What is canned: the model
(`OfflineAgent`, fixed judgments) and the gateway (`OfflineGateway`); each fixture cites the artifact it replays in its own module
(`offline_gateway`: T12-G's adapter-shaped Semantic Scholar record, gen2/tests/fixtures/gateway_answers/semanticscholar_abstract.json;
`offline_agent`: the judgment schemas and examples under gen2/schema/examples/judgment-*). Limits: it proves wiring and the record
families, not research quality; the three failures that are proven at their own layers are not repeated here.

The offline contract replaces the example's stopping profile with one automatic known-item rule over a staged sentinel set (offline_world.contract),
because the example's reviewed-judgment and window rules have no automatic evaluator; the router's own completion fixtures make the same substitution.
The Router's reviewed hand-off enters waiting; only the operator completes the topic.
"""
import unittest
from unittest import mock

from gen2.app.engine import Engine
from gen2.core import canonical
from gen2.tests.offline_run import Offline


class WholeWorkflowTest(unittest.TestCase):
    def test_one_topic_from_brief_to_an_approved_completion_through_production_routes_only(self):
        run = Offline()
        self.addCleanup(run.close)
        # No private read or Engine.call may supply a decision, even accidentally.
        with mock.patch.object(run, "records", side_effect=AssertionError("private operator read")), \
             mock.patch.object(Engine, "call", side_effect=AssertionError("owner escape")):
            self.assertEqual(run.walk(), "done")
        topic = run.topic()
        self.assertEqual(topic["status"], "completed_with_qualified_conclusions")
        review = topic["review"]
        self.assertEqual([(g["gate"], g["state"]) for g in review["dossier"]["gates"]],
                         [("load_bearing_verification_tiers", "satisfied"), ("challenge_pass_completed", "satisfied"), ("coverage_integrity", "satisfied")])
        self.assertEqual((review["dossier"]["state"], review["reviews"][0]["outcome"], review["approvable"]), ("satisfied", "sufficient", True))
        self.assertEqual(topic["completion"]["dossier_revision"], review["dossier"]["revision"])
        # the approved dossier's record families, each written by its own production route
        families = {name: run.records(name) for name in ("scoping_reports", "search_observations", "works", "claims", "claim_source_links", "source_artifacts",
                                                         "source_acquisitions", "verification_receipts", "detailed_check_records", "quote_checks", "completion_records")}
        self.assertEqual({name: len(rows) for name, rows in families.items() if name != "search_observations"},
                         {"scoping_reports": 1, "works": 2, "claims": 1, "claim_source_links": 1, "source_artifacts": 1, "source_acquisitions": 1,
                          "verification_receipts": 1, "detailed_check_records": 4, "quote_checks": 1, "completion_records": 2})
        self.assertEqual(sorted(r["kind"] for r in families["completion_records"]), ["counterevidence_search", "sufficiency_review"])
        self.assertEqual(len(families["search_observations"]), 3)
        self.assertTrue(all("proposal_ref" in o["request"] for o in families["search_observations"]))
        decisions = run.records("operator_decisions")
        self.assertEqual({d["operator_id"] for d in decisions}, {"alice"})
        self.assertEqual({d["kind"] for d in decisions}, {"brief_confirmation", "scope_approval", "rating_approval", "contract_approval", "completion_approval"})
        for draft in run.records("contract_revisions"):
            self.assertEqual(canonical.content_hash(draft["document"]), draft["content_hash"])
            self.assertEqual(draft["document"]["stopping_profiles"][0]["rules"][0]["params"]["sentinel_set"], run.sentinel)
        (receipt,) = families["verification_receipts"]
        self.assertEqual((receipt["verdict"], receipt["access_tier"], receipt["extraction_method"]), ("supports", "abstract", "canonical_bytes"))
        self.assertEqual([q["exact_match"] for q in families["quote_checks"]], ["matched"])

    def test_removing_any_of_the_three_recorders_fails_the_run(self):
        """The DEBT-051 condition: each recorded purpose refuses to be submitted on a station that lacks its recorder."""
        control = Offline()
        self.addCleanup(control.close)
        self.assertIn("contract_approval", control.walk(until="contract_approval"), "control: with every recorder installed, scoping and discovery run")
        for key in ("discovery/search", "verification/verify", "checkpoint/dossier"):
            with self.subTest(key):
                run = Offline(without_recorder=key)
                self.addCleanup(run.close)
                with self.assertRaisesRegex(AssertionError, "internal"):
                    run.walk()
                self.assertTrue(any("RecorderMissing" in line for line in run.logs))
                self.assertNotIn("completion_approval", {d["kind"] for d in run.records("operator_decisions")})
