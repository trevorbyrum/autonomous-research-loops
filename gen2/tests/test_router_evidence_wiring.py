"""The Router's evidence write and the five helpers split out of it (task 2q-b9, Astra's 2q-b3b ruling 4): what the exact replay cannot settle. Independent of the replay.

UnrecordedPromotionTest and ReportLineageTest.test_the_next_version_...: the two branches of `_write_evidence` that no test took before the split (a branch-level reach run,
evidence/2q-b9/reach-vs-verdicts-before.txt: 102 of its 104 were taken by a test whose replay verdict is `same`). Each is tested by what it refuses, and the accepted case beside it.

Rollback (the four tests named ..._whichever_write_is_refused): a commit that goes through a helper that writes (claims and links, scoping reports, source proposals, review closures)
is run with the store refusing its first write, then its second, and so on up to its last: every refusal is `payload_invalid` ("the store refused the write"), every table but the audit
log is as it was, the audit log gains one `commit_rejected` event, and the run allowed every write records the helper's rows. So the helpers run in the transaction
`_commit_in_transaction` holds, as the block they came from did.

Oracles: expected values by hand; the store read back with raw SQL. Limits: the refusing store is a double that refuses by position, not by the DDL's own guards; the post-lock clock read
is `_guarded`'s, which this change does not touch (the move tool's review list names only `_write_evidence` and the five helpers).
"""
from __future__ import annotations

import json

from gen2.router import service
from gen2.store import api
from gen2.tests import test_router_evidence as ev
from gen2.tests import test_router_workflow as wf
from gen2.tests.router_fixtures import TOPIC, empty_outcome


class UnrecordedPromotionTest(ev.EvidenceCase):
    def test_a_promotion_names_a_revision_the_topic_recorded(self) -> None:
        self.to_queued()
        grant = self.started("inv_research01")
        promote = lambda claim, revision: {**empty_outcome("inv_research01", "interim_transition"), "claim_promotions": [{"claim_id": claim, "revision": revision}]}  # noqa: E731
        self.refused(grant, "op_promote0001", promote("clm_00000009", 1), "payload_invalid", detail="clm_00000009 revision 1 is not recorded")
        text = self.artifact(b"the claim")
        self.committed(grant, "op_capture0001", {**promote("clm_00000001", 1), "claims": [self.claim_entry("clm_00000001", 1, text)]}, refs=[text])  # its own claim, recorded first
        self.refused(grant, "op_promote0002", promote("clm_00000001", 2), "payload_invalid", detail="clm_00000001 revision 2 is not recorded")
        self.assertEqual(self.rows("SELECT claim_id, revision, status FROM claims"), [("clm_00000001", 1, "accepted_support")])


class RefusesOnce:
    """The router's store, refusing its `at`-th write (an insert or an update, counted from 0) and no other; `tables` lists the tables written to, the refused write included."""

    def __init__(self, store, at: int) -> None:
        self._store, self.at, self.tables = store, at, []

    def __getattr__(self, name: str):
        member = getattr(self._store, name)
        if name not in ("insert", "update"):
            return member

        def write(table, *args, **kwargs):
            self.tables.append(table)
            if len(self.tables) - 1 == self.at:
                raise api.StoreWriteError("refused for the test")
            return member(table, *args, **kwargs)
        return write


class Rollback(wf.Workflow):
    """A world and a `commit()` answering through self.router; no test of its own."""

    def whichever_write_is_refused(self, commit, table: str) -> None:
        """Run `commit` with each of its writes refused in turn, then with none; the run with none must have written `table`, and every write before it was refused once."""
        before, rejected = self.state(), 0
        for position in range(80):
            double = RefusesOnce(self.store, position)
            self.router = service.Router(double, self.spool, clock=self.clock, new_id=self.ids, fault=self.fault)
            out = commit()
            if out["status"] == "committed":
                break
            self.assertEqual((out["status"], out["reason"]), ("rejected", "payload_invalid"), out)
            self.assertIn("the store refused the write", out["detail"])
            self.assertEqual(self.state(), before, f"write {position} refused")
            rejected += 1
            self.assertEqual(self.value("SELECT count(*) FROM audit_events WHERE kind = 'commit_rejected'"), rejected)
        else:
            self.fail("every run was refused")
        self.assertEqual(position, len(double.tables))
        self.assertIn(table, double.tables)


class ClaimLinkTest(Rollback):
    def test_a_link_is_written_whichever_write_is_refused(self) -> None:
        self.approved()
        grant = self.started("inv_research01")
        self.register(grant, [("doi", "10.1/x", self.observe(grant, "obs_t1search01", ("rec-1",)))])
        self.whichever_write_is_refused(lambda: self.capture(grant, "op_capture0001", claim_source_links=[wf.link()]), "claim_source_links")
        self.assertEqual(self.rows("SELECT claim_id, work_id FROM claim_source_links"), [("clm_00000001", wf.work_of("doi", "10.1/x"))])
        self.assertEqual(self.rows("SELECT claim_id, revision FROM claims"), [("clm_00000001", 1)])
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE operation_id = 'op_capture0001' AND kind = 'commit_outcome'"))  # what the two helpers returned, as the commit's audit event names it
        self.assertEqual((audit["claims"], audit["claim_source_links"], audit["claim_promotions"]), ([["clm_00000001", 1]], [["clm_00000001", 1, wf.work_of("doi", "10.1/x"), "O-1"]], []))


class ReportLineageTest(Rollback):
    def setUp(self) -> None:  # wf.ScopingReportTest's world: a scoping pass that searched crossref and found semantic_scholar unavailable
        super().setUp()
        self.open_brief()
        self.confirm()
        self.grant = self.started("inv_scoping01")
        self.observe(self.grant, "obs_t1scope001", ("rec-1",))
        self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": "inv_scoping01", "observation": wf.UNAVAILABLE, "retrieval_events": []})

    def report(self, version: int) -> dict:
        coverage = [{"lane": "crossref", "coverage_state": "searched_ok", "observation_ids": ["obs_t1scope001"]},
                    {"lane": "semantic_scholar", "coverage_state": "provider_unavailable", "observation_ids": ["obs_t1scope002"]}]
        return self.scoping_report_document(version=version, coverage=coverage)

    def commit(self, op: str, version: int) -> dict:
        return self.router.commit_outcome(self.envelope(self.grant, op, {**empty_outcome("inv_scoping01", "interim_transition"), "scoping_reports": [self.report(version)]}))

    def test_a_report_is_written_whichever_write_is_refused(self) -> None:
        self.whichever_write_is_refused(lambda: self.commit("op_report00001", 1), "scoping_reports")
        self.assertEqual(self.rows("SELECT report_id, version, committed_by_operation_id FROM scoping_reports"), [("scope-1", 1, "op_report00001")])

    def test_the_next_version_follows_the_latest_one_recorded(self) -> None:
        self.assertEqual(self.commit("op_report00001", 1)["status"], "committed")
        rejected = self.decide("opd_scopereject", "scope_approval", {"kind": "scoping_report", "ref": "scope-1", "revision": 1, "hash": self.report(1)["content_hash"]}, disposition="rejected")
        self.assertEqual(rejected["status"], "applied", rejected)  # the topic is scoping again, to write the next version
        before = self.state()
        for label, version in (("a version skipped", 3), ("the recorded version again", 1)):
            with self.subTest(label):
                out = self.commit(f"op_bad{version}report", version)
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
                self.assertIn("scope-1: the next version is 2, with parent 1", out["detail"])
                self.assertEqual(self.state(), before)
        self.assertEqual(self.commit("op_report00002", 2)["status"], "committed")
        self.assertEqual(self.rows("SELECT version, parent_version FROM scoping_reports ORDER BY version"), [(1, None), (2, 1)])


class ProposalTest(Rollback):
    def test_a_proposal_is_written_whichever_write_is_refused(self) -> None:
        self.open_brief()
        self.confirm()
        grant = self.started("inv_scoping01")
        self.whichever_write_is_refused(lambda: self.capture(grant, "op_propose0001", claim=None, source_proposals=[wf.proposal(grant)]), "source_proposals")
        self.assertEqual(self.rows("SELECT proposal_id, committed_by_operation_id FROM source_proposals"), [("srcp_00000001", "op_propose0001")])


class ClosureTest(Rollback):
    def test_a_closure_is_written_whichever_write_is_refused(self) -> None:  # wf.ReviewClosureTest's world: an episode with two triggers, a checkpoint admitted after it
        self.to_queued()
        research = self.started("inv_research01")
        trigger = {"reason_code": "persistent_contradiction", "cause_ref": "clm_a vs clm_b", "source_revision": 0, "observed_at": "2026-09-27T09:55:00Z"}
        self.assertEqual(self.capture(research, "op_trigger0001", claim=None, review_triggers=[trigger])["status"], "committed")
        self.router.raise_signal(wf.signal())
        self.router.open_review({"episode_id": "rev_episode0001", "topic_id": TOPIC, "kind": "method_fit"})
        checkpoint = self.started("inv_checkpt01", "checkpoint")
        self.whichever_write_is_refused(lambda: self.capture(checkpoint, "op_closure0001", claim=None, review_closures=[{"episode_id": "rev_episode0001"}]), "review_episodes")
        self.assertEqual(self.rows("SELECT closed_by_operation_id FROM review_episodes"), [("op_closure0001",)])
        self.assertEqual(self.rows("SELECT count(*) FROM review_triggers WHERE episode_id IS NOT NULL AND handled_at IS NOT NULL"), [(2,)])
