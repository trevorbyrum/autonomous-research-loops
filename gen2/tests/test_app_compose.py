"""Composition and the command line (T17 PR3b-B). Oracles: the supervisor's own RECORDED set, the merged views run on stub rows, the
distinctive capability value planted in a prior receipt (absent from everything the child can see), and the driver's printed line.
Limits: the station is the driver tests' fake with a real spool shape; the real Router and supervisor lifecycle are the other
suites'; the pure builders are lane D's (PR3b-D), exercised here only through the factories' wiring.
"""
import json
import tempfile
import unittest
from pathlib import Path

from gen2.app import compose, workflow
from gen2.app.driver import Context
from gen2.app.workflow import Step
from gen2.core import canonical
from gen2.exec.common import Refused
from gen2.supervisor import jobs as supervisor_jobs
from gen2.supervisor.supervisor import RECORDED
from gen2.tests import supervisor_fixtures as sf
from gen2.tests.test_app_driver import TOPIC, World, contract, checkpoint, scope

CAPABILITY = "cap_" + "d" * 32       # a distinctive bearer-style value from a prior receipt


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.station = self.world.station()
        self.composition = compose.Composition().bind(self.station)

    def kits(self):
        return self.composition.kits(TOPIC, lanes=["semanticscholar"], gateway={"commercial": False, "accept_per_item": False, "policy_version": 1},
                                     validate=lambda name, document: None)

    def test_every_purpose_of_the_workflow_has_a_kit_and_every_recorded_purpose_a_recorder(self):
        self.assertEqual(set(self.kits()), set(workflow.LIMITS))
        self.assertEqual(set(self.composition.recorders()), set(RECORDED))

    def test_the_exchange_index_lists_this_topics_discovery_scratches_only(self):
        root = self.world.root / "jobs"
        for iid, topic, purpose in (("inv_disc000a", TOPIC, "discovery/search"), ("inv_disc000b", "fleet:other", "discovery/search"), ("inv_disc000c", TOPIC, "research_pass/research"),
                                    ("inv_disc000d", TOPIC, "discovery/search")):
            supervisor_jobs.Job(root, "job-" + iid).prepare(sf.bare_order(iid, topic, env={"GEN2_PURPOSE": purpose, "GEN2_STEP": "discovery/search#1"}))
        listed = compose.discovery_scratches(self.station, TOPIC)()
        self.assertEqual(sorted(p.parent.name for p in listed), ["job-inv_disc000a", "job-inv_disc000d"])   # purpose, not the step name, and this topic

    def test_the_scope_and_dossier_kits_build_and_the_discovery_kit_refuses_without_its_proposer(self):
        kits = self.kits()
        topic = {**self.world.topic, "active_contract_revision": None}
        context = Context(scope(1), "inv_x", TOPIC, {"context": "pre-contract/1", "brief": {"brief_id": "b", "version": 2, "content_hash": "sha256:" + "a" * 64},
                                                     "brief_confirmation_decision_id": "opd_aaaaaaaa"}, [], None, lambda step: None, "2026-11-08T09:00:00Z")
        records = {"intake_briefs": [{"brief_id": "b", "version": 2, "content_hash": "sha256:" + "a" * 64, "document": {"objective": "x"}}],
                   "search_observations": [], "scoping_reports": []}
        view = kits[("research_pass", "scope")].view(context, records, [])
        self.assertEqual(view["available_lanes"], ["semanticscholar"])
        self.assertEqual(kits[("checkpoint", "dossier")].view(context, {}, []), {})
        with self.assertRaises(Refused):
            kits[("discovery", "search")].view(context, {}, [])

    def test_challenge_pass_two_is_given_pass_ones_proposals_and_invocation(self):
        kits = self.kits()
        first = checkpoint("challenge", 1)
        proposals = [{"proposal_version": "search-proposal/1", "proposal_id": "p1", "proposer": "x", "lane": "semanticscholar", "request_type": "find",
                      "query": "q", "page_cap": 1, "obligation_ids": [], "rationale": "r", "subject_ref": {"claim_ref": "clm_00000001"}}]
        context = Context(checkpoint("challenge", 2), "inv_two", TOPIC, {"context": "contract/1", "contract": {"revision": 1}}, ["rev_one"], None,
                          lambda step: {"search_proposals": proposals} if step == first else None, "2026-11-08T09:00:00Z", None, 0,
                          lambda step: "inv_pass_one" if step == first else "inv_other")
        records = {"claims": [{"claim_id": "clm_00000001", "revision": 1, "load_bearing": 1, "status": "provisional", "required_access_tier": "abstract",
                               "producer_invocation_id": "inv_producer", "text_ref": "sha256:" + "1" * 64}],
                   "verification_receipts": [], "registry_dispositions": [], "search_observations": []}
        view = kits[("checkpoint", "challenge")].view(context, records, [])
        self.assertEqual((view["pass"], [s["proposal_id"] for s in view["searches"]], view["review_episodes"]), (2, ["p1"], ["rev_one"]))

    def test_a_capability_in_a_prior_receipt_reaches_nothing_the_child_can_see(self):
        """F1: no receipt row is carried; the view is curated and the child's files, env and order hold none of it."""
        receipt = {"verification_receipt_id": "ver_00000001", "claim_id": "clm_00000001", "claim_revision": 1, "verdict": "does_not_support",
                   "verifier_capability_id": CAPABILITY, "receipt": {"verifier_capability_id": CAPABILITY}}
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[])
        self.world.records.update(
            claims=[{"claim_id": "clm_00000001", "revision": 1, "load_bearing": 1, "status": "provisional", "required_access_tier": "abstract",
                     "producer_invocation_id": "inv_producer", "text_ref": "sha256:" + "1" * 64}],
            verification_receipts=[receipt], registry_dispositions=[], search_observations=[], claim_source_links=[], source_artifacts=[], works=[],
            retrieval_events=[], record_work_links=[], detailed_check_records=[], source_acquisitions=[], quote_checks=[], contract_revisions=[{"revision": 1, "content_hash": "sha256:" + "a" * 64}])
        driver = self.world.driver(self.station)
        driver.kits = self.kits()
        for step in (contract("verification", "verify"), checkpoint("challenge")):
            driver.issue(step, {**self.world.topic, "review": None})
        seen = ""
        for path in (self.world.root / "jobs").rglob("*"):
            if path.is_file():
                seen += path.read_text(errors="replace")
        self.assertNotIn(CAPABILITY, seen)                                     # input.json, prompts, evidence, order.json (env) and journals
        self.assertNotIn(CAPABILITY, json.dumps([o.env for o in self.station.supervisor.submitted]))


class AuthorityWiring(unittest.TestCase):
    def test_the_authority_exists_only_when_the_record_its_pin_and_the_manifest_are_all_named(self):
        from gen2.tests.test_supervisor_live import MANIFEST, record_doc, sealed
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, pin = sealed(record_doc(root))
            (root / "record.json").write_bytes(data)
            (root / "manifest.json").write_bytes(MANIFEST)
            names = {"GEN2_QUALIFICATION_RECORD": str(root / "record.json"), "GEN2_QUALIFICATION_PIN": pin, "GEN2_MANIFEST": str(root / "manifest.json")}
            composition = compose.Composition()
            self.assertTrue(composition.authority(root / "jobs", names).qualified)
            for missing in names:
                with self.subTest(missing=missing):
                    self.assertIsNone(composition.authority(root / "jobs", {k: v for k, v in names.items() if k != missing}))
            self.assertFalse(composition.authority(root / "jobs", {**names, "GEN2_QUALIFICATION_PIN": "sha256:" + "0" * 64}).qualified)   # a wrong pin: present but unqualified
            self.assertIsNone(composition.authority(root / "jobs", {}))
