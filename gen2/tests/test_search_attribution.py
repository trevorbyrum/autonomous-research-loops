"""E-2/E-4/G-8: exact Router facts and literal window/hash oracles; fixture searches only."""
import copy
from unittest.mock import patch

from gen2 import accounting as a
from gen2.core.search_proposals import MODE, FACTS, gateway_request
from gen2.router import gates, material
from gen2.router.accounting import records, convert_inventory
from gen2.tests import router_fixtures as rf
from gen2.tests import test_accounting as window_tests
from gen2.tests.test_completion_gates import with_rows
from gen2.tests.test_router_workflow_interface import PROPOSAL


class AttributionTest(rf.Workflow):
    page = window_tests.WindowTest.page
    refused = rf.ContractWorld.refused_command

    def setUp(self):
        super().setUp()
        self.bundle = self.router.activate_config_bundle({**rf.BUNDLE, "version": 2, "policy": {"search_capture": MODE}})["bundle_hash"]
        self.to_queued()

    def claim(self, inv, kind="research_pass", tid=rf.TOPIC, **extra):
        return super().claim(inv, kind, tid, config_bundle_hash=self.bundle, **extra)

    def proposer(self, proposals=(PROPOSAL,), kind="research_pass", iid="inv_proposer01"):
        p = self.started(iid, kind)
        payload = {**rf.empty_outcome(iid), "search_proposals": list(proposals)}
        self.assertEqual(self.finish(p, "op_" + iid[4:], payload)["status"], "committed")
        return p

    def discovery(self, source, iid="inv_discover01"):
        return self.started(iid, "discovery", requested_by_invocation_id=source["invocation_id"])

    def capture(self, d, source, p=PROPOSAL, oid="obs_discover01", *, end="exhausted", next_cursor=None, **changes):
        request = {"lane": p["lane"], "page": 1, "request": gateway_request(p), "proposal_ref": source["invocation_id"] + ":" + p["proposal_id"]}
        request.update(changes)
        return self.page(d, oid, request, end=end, next_cursor=next_cursor)

    def finish_discovery(self, d):
        self.assertEqual(self.finish(d, "op_" + d["invocation_id"][4:])["status"], "committed")

    def inventory(self):
        return self.router.evidence_inventory(rf.TOPIC, history="native")

    def test_separate_discovery_window_and_empty_plan(self):
        """One completed bound chain earns its proposer's window, retaining its actual owner; literal identities/counts."""
        p = self.proposer()
        self.assertEqual(gates.coverage_state(self.inventory()), "unknown")
        d = self.discovery(p)
        self.capture(d, p)
        self.assertEqual(gates.coverage_state(self.inventory()), "unknown")
        self.finish_discovery(d)
        inv = self.inventory()
        self.assertEqual((inv.observations[-1].invocation_id, inv.observations[-1].proposed_by), (d["invocation_id"], p["invocation_id"]))
        self.assertEqual((gates.coverage_state(inv), a.saturation_passes(inv)), ("satisfied", (p["invocation_id"],)))
        empty = self.proposer((), iid="inv_empty00001")
        self.assertEqual(gates.coverage_state(self.inventory()), "satisfied")
        self.assertEqual(a.window_standings(self.inventory())[-1], a.WindowStanding(empty["invocation_id"], "ineligible", "no complete distinct search"))
        self.assertIsNone(a.novelty(a.candidate_units(self.inventory()).assessed_candidates, ()))

    def test_skipped_proposals_and_checkpoint_do_not_invent_windows(self):
        """A matching direct search cannot discharge a proposal; checkpoints contribute capture but no window."""
        p = self.proposer((PROPOSAL, {**PROPOSAL, "proposal_id": "search-2"}), kind="checkpoint")
        d = self.discovery(p)
        self.capture(d, p)
        self.finish_discovery(d)
        self.assertEqual((gates.coverage_state(self.inventory()), a.saturation_passes(self.inventory())), ("unknown", ()))
        d2 = self.discovery(p, "inv_discover02")
        self.capture(d2, p, {**PROPOSAL, "proposal_id": "search-2"}, oid="obs_discover02")
        self.finish_discovery(d2)
        self.assertEqual((gates.coverage_state(self.inventory()), a.saturation_passes(self.inventory())), ("satisfied", ()))

    def test_pages_cannot_be_spliced_between_executions(self):
        """Bound chains retain execution identity before population deduplication; two incomplete jobs earn no window."""
        proposal = {**PROPOSAL, "page_cap": 2}
        p = self.proposer((proposal,))
        d = self.discovery(p)
        self.capture(d, p, proposal, end="continuation", next_cursor="next")
        self.finish_discovery(d)
        d2 = self.discovery(p, "inv_discover02")
        self.capture(d2, p, proposal, oid="obs_discover02", page=2, request={**gateway_request(proposal), "cursors": {"crossref": "next"}})
        self.finish_discovery(d2)
        self.assertEqual((gates.coverage_state(self.inventory()), a.saturation_passes(self.inventory())), ("unknown", ()))

    def test_ownership_requires_both_facts_and_exact_pins(self):
        """Detached corruptions cannot gain ownership; material changes bind every used operand, without Store I/O."""
        p = self.proposer()
        d = self.discovery(p)
        self.capture(d, p)
        self.finish_discovery(d)
        inputs = self.router._accounting.dossier_inputs(rf.TOPIC, history="native")
        before = material.digest(inputs.raw, "native")
        for name, change in (("audit_events", lambda rows: [r for r in rows if r["kind"] != FACTS[0]]),
                ("audit_events", lambda rows: rows + [next(r for r in rows if r["kind"] == FACTS[1])]),
                ("audit_events", lambda rows: [{**r, "detail": {**r["detail"], "proposer": "inv_unbound001"}} if r["kind"] == FACTS[1] else r for r in rows]),
                ("invocations", lambda rows: [{**r, "requested_by_invocation_id": None} if r["invocation_id"] == d["invocation_id"] else r for r in rows]),
                ("invocations", lambda rows: [{**r, "config_bundle_hash": rf.CONFIG} if r["invocation_id"] == p["invocation_id"] else r for r in rows]),
                ("operation_receipts", lambda rows: [{**r, "payload_digest": rf.h("0")} if r["invocation_id"] == p["invocation_id"] else r for r in rows]),
                ("operation_receipts", lambda rows: [{**r, "topic_id": rf.OTHER} if r["invocation_id"] == p["invocation_id"] else r for r in rows])):
            with self.subTest(name=name):
                raw = with_rows(inputs, name, change(copy.deepcopy(list(records(inputs.raw, name))))).raw
                with patch.object(self.store, "select", side_effect=AssertionError("detached read Store")):
                    inv = convert_inventory(rf.TOPIC, raw, "native", modes={self.bundle: True})
                self.assertEqual(gates.coverage_state(inv), "unknown")
                self.assertEqual(a.saturation_passes(inv), ())
                self.assertNotEqual(material.digest(raw, "native"), before)

    def test_reference_query_and_requester_are_not_authority(self):
        """Real Router accepts the capture, but forged/missing proposal constraints never count as complete coverage."""
        for changes in ({"proposal_ref": "inv_wrong00001:search-1"}, {"proposal_ref": "inv_proposer01:missing"},
                        {"proposal_ref": None}, {"request": {**gateway_request(PROPOSAL), "query": "other"}}, {"page": 2}):
            with self.subTest(changes=changes):
                p = self.proposer(iid=self.ids("inv_"))
                d = self.discovery(p, self.ids("inv_"))
                self.capture(d, p, oid=self.ids("obs_"), **changes)
                self.finish_discovery(d)
                self.assertTrue(self.inventory().observations[-1].unbound)
                self.assertEqual(gates.coverage_state(self.inventory()), "unknown")
                self.assertEqual(a.saturation_passes(self.inventory()), ())

    def test_plan_replay_rollback_and_retained_mode(self):
        """Proof and receipt are one commit; an active policy switch cannot alter the invocation's retained mode."""
        p = self.started("inv_retained001")
        env = self.envelope(p, "op_retained001", {**rf.empty_outcome(p["invocation_id"]), "search_proposals": [PROPOSAL]})
        self.ready(p, env["payload_digest"])
        self.router.activate_config_bundle({**rf.BUNDLE, "version": 3})
        env["expected_state_revision"] = self.state_revision()
        before = self.state()
        self.faults["in_transaction:evidence"] = RuntimeError("rollback proof")
        with self.assertRaisesRegex(RuntimeError, "rollback proof"):
            self.router.commit_outcome(env)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
        self.assertEqual(self.value("SELECT count(*) FROM audit_events WHERE kind=? AND invocation_id=?", FACTS[0], p["invocation_id"]), 1)
        before = self.state()
        self.assertEqual(self.router.commit_outcome(env)["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_ordinary_review_audits_do_not_stale_the_dossier(self):
        """Only scientific proof kinds enter material v2; captured raw audit bookkeeping remains hash-visible."""
        self.proposer(())
        raw = self.store.capture_topic(rf.TOPIC)
        before = material.digest(raw, "native")
        self.router.open_review({"episode_id": "rev_attrib0001", "topic_id": rf.TOPIC, "kind": "fixed_cadence"})
        self.assertEqual(material.digest(self.store.capture_topic(rf.TOPIC), "native"), before)

    def test_binding_refusal_is_atomic(self):
        """An unfinished/missing plan refuses discovery admission with all-table equality; no caller-label authority."""
        p = self.started("inv_pending001")
        request = {"invocation_id": "inv_refused001", "kind": "discovery", "topic_id": rf.TOPIC, "config_bundle_hash": self.bundle,
                   "deadline_at": rf.DEADLINE, "station_id": "station-1", "lease_expires_at": rf.EXPIRES, "requested_by_invocation_id": p["invocation_id"]}
        self.refused("claim", request, "discovery_binding_invalid")

    def test_new_active_mode_cannot_backfill_a_legacy_pass(self):
        """A legacy invocation stays uncertain under a newer active mode; no zero-search inference."""
        self.bundle = self.router.activate_config_bundle({**rf.BUNDLE, "version": 3})["bundle_hash"]
        p = self.started("inv_oldmode001")
        self.router.activate_config_bundle({**rf.BUNDLE, "version": 4, "policy": {"search_capture": MODE}})
        self.assertEqual(self.finish(p, "op_oldmode001")["status"], "committed")
        self.assertEqual(self.value("SELECT count(*) FROM audit_events WHERE kind=? AND invocation_id=?", FACTS[0], p["invocation_id"]), 0)
        self.assertEqual(gates.coverage_state(self.inventory()), "unknown")
