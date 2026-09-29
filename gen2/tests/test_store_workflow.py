"""Scoping reports and source proposals in the store (task 2a).

Trace: flow S2 (the scoping report, committed by pre-contract work and
approved by the operator's scope approval), SOURCE-GOVERNANCE.md steps 1-2
(an agent's typed source proposal, retained; the operator's exact-subject
approve/reject/defer); INVARIANTS C-12, G-13, C-11; the Phase 2 plan audit
(finding 4: a scoping-report subject had shape checks only, no stored
subject).

Oracle: accepted rows and one-dimension near-misses written by hand; each
refusal is followed by a read-back showing nothing was written. Which
message SQLite reports where several guards refuse one write is trigger
order, so each near-miss differs in exactly the dimension its guard reads.

What these tests cannot show: that a report's content hash is the hash of
its document, that its brief pin is its committing work's, or that its
coverage facts are its observations' (the router's, test_router_workflow.py);
nor anything about the gateway's registry, which no table here is.
"""
from __future__ import annotations

import json

from gen2.tests.store_fixtures import OTHER, TOPIC, StoreTestCase, T, h

REPORT = ("INSERT INTO scoping_reports (topic_id, report_id, version, parent_version, content_hash, document, brief_id, brief_version, brief_hash, invocation_id, "
          "committed_by_operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
PROPOSAL = ("INSERT INTO source_proposals (proposal_id, topic_id, content_hash, document, proposed_by_invocation_id, committed_by_operation_id, supersedes_proposal_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
DECISION = ("INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'user', ?)")


class ScopingReportTest(StoreTestCase):
    """OTHER's pre-contract pass (inv_ssssssss, op_scoping01) is the report's
    committer; TOPIC's contract-admitted pass (inv_pppppppp, op_00000001)
    and a second pre-contract pass of OTHER under brief-2 are the near-misses."""

    def setUp(self) -> None:
        super().setUp()
        self.scoping_pass()
        self.bhash = self.brief_hash(OTHER)

    def row(self, **changes) -> tuple:
        cols = {"topic_id": OTHER, "report_id": "scope-1", "version": 1, "parent_version": None, "content_hash": h("5"), "brief_id": "brief-1", "brief_version": 1,
                "brief_hash": self.bhash, "invocation_id": "inv_ssssssss", "committed_by_operation_id": "op_scoping01"}
        cols.update(changes)
        doc = {"topic_id": cols["topic_id"], "report_id": cols["report_id"], "version": cols["version"], "parent_version": cols["parent_version"],
               "content_hash": cols["content_hash"], "brief": {"brief_id": cols["brief_id"], "version": cols["brief_version"], "content_hash": cols["brief_hash"]}}
        doc.update(changes.pop("doc", {}))
        return (cols["topic_id"], cols["report_id"], cols["version"], cols["parent_version"], cols["content_hash"], json.dumps(doc), cols["brief_id"],
                cols["brief_version"], cols["brief_hash"], cols["invocation_id"], cols["committed_by_operation_id"], T)

    def test_a_report_is_committed_by_pre_contract_work_of_its_brief(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")  # TOPIC's contract-admitted research pass
        self.receipt("op_00000001", "inv_pppppppp")
        self.brief(OTHER, "brief-2", 1)  # OTHER's second brief, awaiting confirmation
        guard = "a scoping report is committed by pre-contract work of its topic pinned to exactly the brief it names"
        for case, changes in (("another invocation than the receipt's", dict(invocation_id="inv_pppppppp")),
                              ("a receipt of another invocation", dict(committed_by_operation_id="op_00000001")),
                              ("contract-admitted work of another topic", dict(invocation_id="inv_pppppppp", committed_by_operation_id="op_00000001")),
                              ("another brief than its work's pin", dict(brief_id="brief-2", brief_hash=self.brief_hash(OTHER, "brief-2"))),
                              ("its brief under another hash", dict(brief_hash=h("9")))):
            with self.subTest(case):
                self.rejects(guard, REPORT, *self.row(**changes))
                self.assertEqual(self.snapshot("scoping_reports"), [])
        self.x(REPORT, *self.row())
        self.assertEqual(self.rows("SELECT topic_id, report_id, version, invocation_id, committed_by_operation_id FROM scoping_reports"),
                         [(OTHER, "scope-1", 1, "inv_ssssssss", "op_scoping01")])

    def test_its_document_is_its_row(self) -> None:
        for field, value in (("topic_id", TOPIC), ("report_id", "scope-2"), ("version", 2), ("parent_version", 1), ("content_hash", h("6")),
                             ("brief", {"brief_id": "brief-1", "version": 1, "content_hash": h("9")})):
            with self.subTest(document_field=field):
                self.rejects("CHECK constraint failed", REPORT, *self.row(doc={field: value}))
                self.assertEqual(self.snapshot("scoping_reports"), [])
        self.x(REPORT, *self.row())

    def test_a_version_revises_an_earlier_stored_one(self) -> None:
        self.x(REPORT, *self.row())
        self.rejects("scoping_report_parent_is_earlier", REPORT, *self.row(version=2, parent_version=2, content_hash=h("6")))
        self.rejects("FOREIGN KEY constraint failed", REPORT, *self.row(version=3, parent_version=2, content_hash=h("6")))
        self.assertEqual(self.rows("SELECT version FROM scoping_reports"), [(1,)])
        self.x(REPORT, *self.row(version=2, parent_version=1, content_hash=h("6")))
        self.assertEqual(self.rows("SELECT version, parent_version FROM scoping_reports ORDER BY version"), [(1, None), (2, 1)])

    def test_a_report_is_immutable_and_never_deleted(self) -> None:
        self.x(REPORT, *self.row())
        before = self.snapshot("scoping_reports")
        self.rejects("scoping reports are immutable", "UPDATE scoping_reports SET created_at = created_at")
        self.rejects("scoping reports are never deleted", "DELETE FROM scoping_reports")
        self.assertEqual(self.snapshot("scoping_reports"), before)

    def test_a_scope_decision_names_a_stored_report_exactly(self) -> None:
        report = self.scoping_report()
        for case, (tid, ref, rev, hsh) in (("an unstored report", (OTHER, "scope-9", 1, report)), ("an unstored version", (OTHER, "scope-1", 2, report)),
                                           ("another hash", (OTHER, "scope-1", 1, h("9"))), ("another topic", (TOPIC, "scope-1", 1, report))):
            with self.subTest(case):
                self.rejects("must name an existing subject", DECISION, "opd_scope_x", tid, "scope_approval", "approved", "scoping_report", ref, rev, hsh, T)
                self.assertEqual(self.rows("SELECT count(*) FROM operator_decisions WHERE kind = 'scope_approval'"), [(0,)])
        self.x(DECISION, "opd_scope_x", OTHER, "scope_approval", "approved", "scoping_report", "scope-1", 1, report, T)


class SourceProposalTest(StoreTestCase):
    """OTHER's pre-contract research pass proposes; TOPIC's contract-admitted
    pass is the near-miss proposer of another topic."""

    def setUp(self) -> None:
        super().setUp()
        self.scoping_pass()

    def row(self, pid: str = "srcp_00000001", **changes) -> tuple:
        cols = {"topic_id": OTHER, "content_hash": h("5"), "proposed_by_invocation_id": "inv_ssssssss", "committed_by_operation_id": "op_scoping01",
                "supersedes_proposal_id": None, "kind": "research_pass"}
        cols.update({k: v for k, v in changes.items() if k != "doc"})
        doc = {"proposal_id": pid, "topic_id": cols["topic_id"], "proposed_by": {"invocation_id": cols["proposed_by_invocation_id"], "invocation_kind": cols["kind"]}}
        if cols["supersedes_proposal_id"] is not None:
            doc["supersedes_proposal_id"] = cols["supersedes_proposal_id"]
        doc.update(changes.get("doc", {}))
        return (pid, cols["topic_id"], cols["content_hash"], json.dumps(doc), cols["proposed_by_invocation_id"], cols["committed_by_operation_id"],
                cols["supersedes_proposal_id"], T)

    def test_a_proposal_is_committed_by_its_proposer(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp")
        guard = "a source proposal is committed by the invocation that proposes it, of its topic and kind"
        for case, changes in (("committed by another invocation's operation", dict(committed_by_operation_id="op_00000001")),
                              ("a proposer of another topic", dict(proposed_by_invocation_id="inv_pppppppp", committed_by_operation_id="op_00000001")),
                              ("a kind its proposer is not", dict(kind="discovery"))):
            with self.subTest(case):
                self.rejects(guard, PROPOSAL, *self.row(**changes))
                self.assertEqual(self.snapshot("source_proposals"), [])
        self.x(PROPOSAL, *self.row())
        self.assertEqual(self.rows("SELECT proposal_id, topic_id, proposed_by_invocation_id FROM source_proposals"), [("srcp_00000001", OTHER, "inv_ssssssss")])

    def test_its_document_is_its_row(self) -> None:
        for field, value in (("proposal_id", "srcp_00000009"), ("topic_id", TOPIC), ("proposed_by", {"invocation_id": "inv_other000", "invocation_kind": "research_pass"}),
                             ("supersedes_proposal_id", "srcp_00000000")):
            with self.subTest(document_field=field):
                self.rejects("CHECK constraint failed", PROPOSAL, *self.row(doc={field: value}))
                self.assertEqual(self.snapshot("source_proposals"), [])
        self.x(PROPOSAL, *self.row())

    def test_a_re_proposal_supersedes_another_stored_proposal(self) -> None:
        self.rejects("CHECK constraint failed", PROPOSAL, *self.row(supersedes_proposal_id="srcp_00000001"))  # itself
        self.rejects("FOREIGN KEY constraint failed", PROPOSAL, *self.row(supersedes_proposal_id="srcp_00000000"))  # none stored
        self.assertEqual(self.snapshot("source_proposals"), [])
        self.x(PROPOSAL, *self.row())
        self.x(PROPOSAL, *self.row("srcp_00000002", content_hash=h("6"), supersedes_proposal_id="srcp_00000001"))
        self.assertEqual(self.rows("SELECT proposal_id, supersedes_proposal_id FROM source_proposals ORDER BY rowid"),
                         [("srcp_00000001", None), ("srcp_00000002", "srcp_00000001")])

    def test_a_proposal_is_immutable_and_never_deleted(self) -> None:
        self.x(PROPOSAL, *self.row())
        before = self.snapshot("source_proposals")
        self.rejects("source proposals are immutable", "UPDATE source_proposals SET created_at = created_at")
        self.rejects("source proposals are never deleted", "DELETE FROM source_proposals")
        self.assertEqual(self.snapshot("source_proposals"), before)

    def test_a_source_decision_names_a_stored_proposal_exactly(self) -> None:
        proposal = self.source_proposal()
        for case, (tid, ref, hsh) in (("an unstored proposal", (OTHER, "srcp_00000009", proposal)), ("another hash", (OTHER, "srcp_00000001", h("9"))),
                                      ("another topic", (TOPIC, "srcp_00000001", proposal))):
            with self.subTest(case):
                self.rejects("must name an existing subject", DECISION, "opd_source_x", tid, "source_approval", "approved", "source_proposal", ref, None, hsh, T)
        with self.subTest("a revision a proposal does not have"):
            self.rejects("CHECK constraint failed", DECISION, "opd_source_x", OTHER, "source_approval", "approved", "source_proposal", "srcp_00000001", 1, proposal, T)
        with self.subTest("another kind about the proposal"):  # the kind -> subject-kind map
            self.rejects("CHECK constraint failed", DECISION, "opd_source_x", OTHER, "publication_approval", "approved", "source_proposal", "srcp_00000001", None, proposal, T)
        self.assertEqual(self.rows("SELECT count(*) FROM operator_decisions WHERE subject_kind = 'source_proposal'"), [(0,)])
        for n, disposition in enumerate(("approved", "rejected", "deferred")):
            self.x(DECISION, f"opd_source_{n}", OTHER, "source_approval", disposition, "source_proposal", "srcp_00000001", None, proposal, T)
        self.assertEqual(self.rows("SELECT disposition FROM operator_decisions WHERE subject_kind = 'source_proposal' ORDER BY rowid"),
                         [("approved",), ("rejected",), ("deferred",)])
