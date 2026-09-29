"""A contract's brief basis after the topic's first approval (task 2a-repair-3;
Astra 2a-repair-2 review, F1-R continued).

Trace: docs/gen2/tasks/2a-repair-3.md; flow S1, §6.1 (an edited brief
re-versions; the contract takes the change only through an approved
framework diff), S3; INVARIANTS G-4, G-6, C-12.

What is shown: once a later confirmation has replaced the brief version an
amendment names — another content of that brief, or another brief,
confirmed after it — the amendment is neither proposed nor approved,
whatever follows: the replacement archived, several versions of it, owner
or deadline successors before or after it, the old content confirmed
again. Archival alone, owner or deadline successors (archived or current)
and a brief or version written but never confirmed leave the basis
standing, and a brief confirmed and archived before the contract's own
basis replaces nothing of it. Each history runs at both timings: before the amendment is
proposed (refused at proposal) and between its proposal and its approval
(refused at approval). Each refusal leaves the whole store, but the audit
log, as it was. A revision naming the newest basis is approved as a reframe
and only as one, and it fences the work pinned to the old revision.

Oracles: expectations are written here by hand, from the task brief and
Astra's review: its 26-case matrix (astra_amendment_edges.py: ten barred
and three accepted histories at two timings), its four router-only
regressions (astra_cross_brief_regression.py: different_brief_archived and
archived_lineage_then_different_archived, at both timings) and its two
history controls. No expectation comes from the router's replacement record
or its standing helpers. Every write goes through the router, the topic's creation
included (x() refuses raw SQL).

Limits: structural authority only — which brief a revision may name, not
whether the contract fits the brief; no concurrent interleavings.
"""
from __future__ import annotations

from gen2.tests.router_fixtures import BUNDLE, TOPIC
from gen2.tests.test_router_workflow import REVIEW_BY, Workflow, contract

OTHER_OWNER = {"owner": "other-owner", "deadline": "2026-10-02T00:00:00Z"}
THIRD_OWNER = {"owner": "third-owner", "deadline": "2026-10-03T00:00:00Z"}


def amendment(revision: int = 3, parent: int = 2, basis: dict | None = None) -> dict:
    """Astra's amendment: a result stays current 90 days, not 180. Naming
    another `basis` changes the decision record: framing version 2 (G-6)."""
    def edit(doc: dict) -> None:
        doc["surveillance_policy"]["freshness_requirement"]["max_currency_age_days"] = 90
        if basis is not None:
            doc["decision_record"]["objective"]["confirmed_brief"] = dict(basis)
            doc["facet_map"]["framing_version"] = 2
    return contract(revision, parent, edit=edit)


class BriefBasisTest(Workflow):
    def seed(self) -> None:
        self.assertEqual(self.router.activate_config_bundle(BUNDLE)["status"], "activated")
        self.assertEqual(self.router.create_topic({"topic_id": TOPIC, "priority": 1})["status"], "created")

    def x(self, sql: str, *params):
        raise AssertionError("every write here is the router's")

    # -- steps -----------------------------------------------------------------
    def brief(self, version: int, feeds: str = "rebuild or not", bid: str = "brief-1", owner: str = "user", deadline: str = REVIEW_BY,
              confirm: bool = True) -> dict:
        """`bid` v`version` written through the router (and confirmed); returns its reference as a decision record names it."""
        doc = self.brief_document(TOPIC, version, brief_id=bid, feeds=feeds)
        write = self.router.open_brief if version == 1 else self.router.version_brief
        self.assertEqual(write({"document": doc, "owner_operator_id": owner, "review_deadline": deadline})["status"], "recorded")
        did = f"opd_{bid}v{version:02d}"
        if confirm:
            out = self.decide(did, "brief_confirmation", {"kind": "intake_brief", "ref": bid, "revision": version, "hash": doc["content_hash"]})
            self.assertEqual(out["status"], "applied", out)
        return {"brief_id": bid, "version": version, "confirmed_by": did}

    def archive(self, version: int = 1, bid: str = "brief-1") -> None:
        out = self.router.close_brief({"topic_id": TOPIC, "brief_id": bid, "version": version, "closure": "archived", "closed_by": "user", "reason": "intake done"})
        self.assertEqual(out["status"], "closed", out)

    def propose(self, doc: dict) -> dict:
        return self.router.propose_amendment({"document": doc})

    def approve_amendment(self, doc: dict, kind: str = "amendment_approval") -> dict:
        return self.decide(f"opd_{kind[:6]}{doc['revision']:03d}", kind, {"kind": "contract_revision", "revision": doc["revision"], "hash": doc["content_hash"]})

    def refused(self, call, status: str, reason: str, detail: str) -> None:
        before = self.state()
        out = call()
        self.assertEqual((out["status"], out.get("reason")), (status, reason), out)
        self.assertIn(detail, out["detail"])
        self.assertEqual(self.state(), before)

    # -- histories after the first approval: each returns the newest confirmed brief --
    def original_material(self) -> dict:
        return self.brief(2, "a materially different decision")

    def multiple_material(self) -> dict:
        return [self.brief(v, f"material decision {v}") for v in (2, 3, 4)][-1]

    def material_then_archived(self) -> dict:
        newest = self.brief(2, "material decision 2")
        self.archive(2)
        return newest

    def lineage_material_lineage(self) -> dict:
        self.brief(2, **OTHER_OWNER)
        self.brief(3, "material decision 3", owner="other-owner")
        return self.brief(4, "material decision 3", **THIRD_OWNER)

    def lineage_material_lineage_archived(self) -> dict:
        newest = self.lineage_material_lineage()
        self.archive(4)
        return newest

    def material_reverted_archived(self) -> dict:
        self.brief(2, "material decision 2")
        newest = self.brief(3)  # v1's content again
        self.archive(3)
        return newest

    def different_brief_current(self) -> dict:
        self.archive()
        return self.brief(1, "a materially different decision", bid="brief-2")

    def different_brief_archived(self) -> dict:
        newest = self.different_brief_current()
        self.archive(bid="brief-2")
        return newest

    def archived_lineage_then_different_archived(self) -> dict:
        self.brief(2, **OTHER_OWNER)
        self.archive(2)
        newest = self.brief(1, "a materially different decision", bid="brief-2")
        self.archive(bid="brief-2")
        return newest

    def different_brief_versions_archived(self) -> dict:
        self.different_brief_current()
        newest = self.brief(2, "yet another material decision", bid="brief-2")
        self.archive(2, bid="brief-2")
        return newest

    def archival_only(self) -> None:
        self.archive()

    def lineage_only_archived(self) -> None:
        self.brief(2, **OTHER_OWNER)
        self.brief(3, **THIRD_OWNER)
        self.archive(3)

    def lineage_only_current(self) -> None:
        self.brief(2, **OTHER_OWNER)
        self.brief(3, **THIRD_OWNER)

    def unconfirmed_different_brief(self) -> None:
        self.archive()
        self.brief(1, "not confirmed", bid="brief-2", confirm=False)

    def unconfirmed_material_version(self) -> None:
        self.brief(2, "a material draft, never confirmed", confirm=False)
        self.brief(3, **OTHER_OWNER)  # v1's content, confirmed

    # -- the two outcomes ------------------------------------------------------------
    def barred(self, history, before_proposal: bool) -> None:
        """The amendment naming brief-1 v1 is refused, the store unchanged;
        the newest basis comes in only through a reframe, which fences the
        work pinned to revision 2."""
        self.approved()
        grant = self.started("inv_pinnedr2")
        stale = amendment()
        if before_proposal:
            newest = history()
            self.refused(lambda: self.propose(stale), "refused", "contract_inconsistent", "names brief brief-1 v1, which no longer stands")
        else:
            self.assertEqual(self.propose(stale)["status"], "recorded")
            newest = history()
            self.refused(lambda: self.approve_amendment(stale), "rejected", "decision_refused", "names brief brief-1 v1, which no longer stands")
        self.assertEqual(self.capture(grant, "op_pinnedr2a", claim=None)["status"], "committed")
        reframe = amendment(self.value("SELECT max(revision) FROM contract_revisions") + 1, 2, newest)
        self.assertEqual(self.propose(reframe)["status"], "recorded")
        self.refused(lambda: self.approve_amendment(reframe), "rejected", "decision_refused", "a framing change is approved as a reframe")
        out = self.approve_amendment(reframe, "reframe_approval")
        self.assertEqual((out["status"], out["effects"]["impact"]["classification"]), ("applied", "reframed"), out)
        self.refused_commit(grant, "op_pinnedr2b", "amendment_pending", "pinned contract revision 2 was superseded (reframed)")

    def accepted(self, history, before_proposal: bool) -> None:
        self.approved()
        stale = amendment()
        if before_proposal:
            history()
        self.assertEqual(self.propose(stale)["status"], "recorded")
        if not before_proposal:
            history()
        out = self.approve_amendment(stale)
        self.assertEqual((out["status"], out["effects"]["impact"]["classification"]), ("applied", "compatible"), out)

    # -- Astra's matrix: ten barred histories ------------------------------------------
    def test_original_material_before_proposal(self) -> None:
        self.barred(self.original_material, True)

    def test_original_material_after_proposal(self) -> None:
        self.barred(self.original_material, False)

    def test_multiple_material_before_proposal(self) -> None:
        self.barred(self.multiple_material, True)

    def test_multiple_material_after_proposal(self) -> None:
        self.barred(self.multiple_material, False)

    def test_material_then_archived_before_proposal(self) -> None:
        self.barred(self.material_then_archived, True)

    def test_material_then_archived_after_proposal(self) -> None:
        self.barred(self.material_then_archived, False)

    def test_lineage_material_lineage_before_proposal(self) -> None:
        self.barred(self.lineage_material_lineage, True)

    def test_lineage_material_lineage_after_proposal(self) -> None:
        self.barred(self.lineage_material_lineage, False)

    def test_lineage_material_lineage_archived_before_proposal(self) -> None:
        self.barred(self.lineage_material_lineage_archived, True)

    def test_lineage_material_lineage_archived_after_proposal(self) -> None:
        self.barred(self.lineage_material_lineage_archived, False)

    def test_material_reverted_archived_before_proposal(self) -> None:
        self.barred(self.material_reverted_archived, True)

    def test_material_reverted_archived_after_proposal(self) -> None:
        self.barred(self.material_reverted_archived, False)

    def test_different_brief_current_before_proposal(self) -> None:
        self.barred(self.different_brief_current, True)

    def test_different_brief_current_after_proposal(self) -> None:
        self.barred(self.different_brief_current, False)

    def test_different_brief_archived_before_proposal(self) -> None:  # Astra's regression: replacement archived before proposal
        self.barred(self.different_brief_archived, True)

    def test_different_brief_archived_after_proposal(self) -> None:  # ... between proposal and approval
        self.barred(self.different_brief_archived, False)

    def test_archived_lineage_then_different_archived_before_proposal(self) -> None:  # Astra's regression: archived lineage before proposal
        self.barred(self.archived_lineage_then_different_archived, True)

    def test_archived_lineage_then_different_archived_after_proposal(self) -> None:  # ... between proposal and approval
        self.barred(self.archived_lineage_then_different_archived, False)

    def test_different_brief_versions_archived_before_proposal(self) -> None:
        self.barred(self.different_brief_versions_archived, True)

    def test_different_brief_versions_archived_after_proposal(self) -> None:
        self.barred(self.different_brief_versions_archived, False)

    # -- accepted histories: the matrix's three; owner/deadline successors still current; a material version never confirmed --
    def test_archival_only_before_proposal(self) -> None:
        self.accepted(self.archival_only, True)

    def test_archival_only_after_proposal(self) -> None:
        self.accepted(self.archival_only, False)

    def test_lineage_only_archived_before_proposal(self) -> None:
        self.accepted(self.lineage_only_archived, True)

    def test_lineage_only_archived_after_proposal(self) -> None:
        self.accepted(self.lineage_only_archived, False)

    def test_lineage_only_current_before_proposal(self) -> None:
        self.accepted(self.lineage_only_current, True)

    def test_lineage_only_current_after_proposal(self) -> None:
        self.accepted(self.lineage_only_current, False)

    def test_unconfirmed_different_brief_before_proposal(self) -> None:
        self.accepted(self.unconfirmed_different_brief, True)

    def test_unconfirmed_different_brief_after_proposal(self) -> None:
        self.accepted(self.unconfirmed_different_brief, False)

    def test_unconfirmed_material_version_before_proposal(self) -> None:
        self.accepted(self.unconfirmed_material_version, True)

    def test_unconfirmed_material_version_after_proposal(self) -> None:
        self.accepted(self.unconfirmed_material_version, False)

    def test_a_brief_confirmed_and_archived_before_the_basis_replaces_none_of_it(self) -> None:
        """Brief-2 was confirmed and archived before brief-1 v1, the contract's
        basis, was confirmed: brief-1 v1 stands after its own archival, while
        brief-2, which it replaced, is not taken as a basis."""
        earlier = self.brief(1, "an earlier need", bid="brief-2")
        self.archive(bid="brief-2")
        self.assertEqual(self.open_brief()["status"], "recorded")
        self.confirm()
        self.approved()
        self.archive()
        kept = amendment()
        self.assertEqual(self.propose(kept)["status"], "recorded")
        self.assertEqual(self.approve_amendment(kept)["status"], "applied")
        self.refused(lambda: self.propose(amendment(4, 3, earlier)), "refused", "contract_inconsistent", "names brief brief-2 v1, which no longer stands")
