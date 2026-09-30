"""Constraint tests for the gen-2 store DDL draft: contract governance, the
draft queue and claim vocabularies, facet importance (mostly
gen2/store/schema/01-queue-and-contracts.sql).

Split from test_store_ddl.py by concern (task 2r): the classes, their
methods and assertions are unchanged.

Trace: task 0a deliverable 3 ("Uniqueness/fencing constraints expressed in
DDL where SQLite allows"); invariant IDs refer to docs/gen2/INVARIANTS.md.

What these tests show: the named constraint or trigger rejects the stated
row. Where a test also shows the same write minus the violation being
accepted, that control rules out an unrelated failure (such as a missing
foreign key); the few tests without such a control say so. Every
connection applies gen2/store/connection.sql (store_fixtures.connect). What
they cannot show: that the router uses these tables correctly, that crash recovery or
replay behave (RG-1a/RG-1b need Phase 1 fault-injection tests against the
router), or anything about concurrency. They test the draft schema only.
"""
from __future__ import annotations

import json
import sqlite3
import unittest

from gen2.tests.store_fixtures import OTHER, TOPIC, StoreTestCase, T, facet, h, obligation


class ContractGovernanceTest(StoreTestCase):
    def test_contract_content_immutable_never_deleted(self) -> None:
        """D50 rewrite (A1/A2): every pin, REPLACE, creation as draft, and the
        approval subject. Approval near-misses differ in one dimension: kind (an
        approved rating decision about this very revision), disposition, or
        subject (another revision; a contract's revision, hash and topic are
        mutually determined because content hashes are unique and the decision's
        subject must exist when recorded)."""
        stored = self.snapshot("contract_revisions")
        for pin, value in (("protocol_revision", 2), ("framing_version", 2), ("content_hash", h("9")), ("parent_revision", 1),
                           ("document", '{"topic_id":"fleet-a:t1"}'), ("created_at", "2026-09-26T00:00:00Z"), ("revision", 7)):
            with self.subTest(pin=pin):
                self.rejects("contract revisions are immutable", f"UPDATE contract_revisions SET {pin} = ? WHERE topic_id = ? AND revision = 1", value, TOPIC)
        self.rejects("never deleted", "DELETE FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC)
        self.rejects("never deleted", "INSERT OR REPLACE INTO contract_revisions SELECT topic_id, revision, parent_revision, 2, framing_version, content_hash, json_set(document, '$.protocol_revision', 2), status, approved_by_decision_id, created_at FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC)
        self.assertEqual(self.snapshot("contract_revisions"), stored)
        approve = "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = 1"
        self.contract(TOPIC, 2)
        self.decision("opd_ratingxx", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.decision("opd_rejected", "contract_approval", disposition="rejected", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.decision("opd_otherrev", "contract_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        self.decision("opd_othertop", "contract_approval", tid=OTHER, rev=1, hsh=self.content_hash_of(OTHER, 1))
        for did in ("opd_ratingxx", "opd_rejected", "opd_otherrev", "opd_othertop"):
            with self.subTest(decision=did):
                self.rejects("exact topic, revision and content hash", approve, did, TOPIC)
        self.rejects("existing subject", "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_wronghsh', ?, 'contract_approval', 'approved', 'contract_revision', ?, 1, ?, 'user', ?)", TOPIC, TOPIC, h("0"), T)
        self.decision("opd_00000001", "contract_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.rejects("exact topic, revision and content hash", approve, "opd_rejected", TOPIC)  # a valid approval exists, but is not the one named
        self.x(approve, "opd_00000001", TOPIC)
        self.rejects("draft -> approved -> superseded", "UPDATE contract_revisions SET status = 'draft' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.rejects("written as a draft", "INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, approved_by_decision_id, created_at) "
                     "SELECT topic_id, 3, 2, protocol_revision, framing_version, ?, json_set(json_set(document, '$.revision', 3), '$.content_hash', ?), 'approved', 'opd_00000001', created_at FROM contract_revisions WHERE topic_id = ? AND revision = 1", h("8"), h("8"), TOPIC)

    def test_hash_lock_binds_document_to_row(self) -> None:
        """G-1 / RA6: every identity field the contract document duplicates —
        topic, revision, parent (the lineage RA2 reads), created_at, content
        hash, protocol revision, framing version — equals its column."""
        base = {"topic_id": TOPIC, "revision": 2, "parent_revision": 1, "created_at": T, "content_hash": h("9"), "protocol_revision": 1, "facet_map": {"framing_version": 1}}
        ins = "INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, created_at) VALUES (?, 2, 1, 1, 1, ?, ?, 'draft', ?)"
        for key, value in (("topic_id", OTHER), ("revision", 3), ("parent_revision", None), ("created_at", "2026-09-26T00:00:00Z"), ("content_hash", h("0")),
                           ("protocol_revision", 2), ("facet_map", {"framing_version": 2})):
            with self.subTest(field=key):
                self.rejects("CHECK constraint failed", ins, TOPIC, h("9"), json.dumps(dict(base, **{key: value})), T)
        self.x(ins, TOPIC, h("9"), json.dumps(base), T)

    def test_parent_is_a_strictly_earlier_revision(self) -> None:
        """RA2-R: the stored parent relation is proper ancestry. Refused, each
        with its document agreeing with its row (so only the ancestry CHECK can
        refuse) and nothing written: a revision naming itself as parent (the
        review's probe shape), a two-revision cycle written by one multi-row
        INSERT (its foreign key is checked at statement end, when both rows
        exist), and a parent that exists but is a later revision. Accepted: a
        direct parent, an earlier non-adjacent one (a sibling draft's shape),
        and the first revision's NULL parent (setUp)."""
        refused = "CHECK constraint failed: contract_parent_is_earlier"
        stored = self.snapshot("contract_revisions")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.contract(TOPIC, 2, parent=2)
        self.assertIn(refused, str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.contract_cycle(TOPIC, 2, 3)
        self.assertIn(refused, str(ctx.exception))
        self.assertEqual(self.snapshot("contract_revisions"), stored)
        self.contract(TOPIC, 2)  # direct parent 1
        self.contract(TOPIC, 5, parent=1)  # earlier, not adjacent
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.contract(TOPIC, 3, parent=5)  # an existing, later revision
        self.assertIn(refused, str(ctx.exception))
        self.contract(TOPIC, 3, parent=2)
        self.assertEqual(self.rows("SELECT revision, parent_revision FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC),
                         [(1, None), (2, 1), (3, 2), (5, 1)])

    def test_one_approved_revision_per_topic(self) -> None:
        self.approve_contract(TOPIC, 1, "opd_00000001")
        self.contract(TOPIC, 2)
        self.decision("opd_00000002", "amendment_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        self.rejects("UNIQUE constraint failed", "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000002' WHERE topic_id = ? AND revision = 2", TOPIC)
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000002' WHERE topic_id = ? AND revision = 2", TOPIC)

    def test_an_update_recording_no_approval_pointer_passes_its_guard(self) -> None:
        """The alternative contract_approval_pointer_set_by_approval's own WHEN
        admits without its approved-status exemption (task 1c-repair-4, the
        C4 re-check): an update of a draft that names the pointer column but
        records no pointer (it stays NULL) enters the trigger and passes, the
        draft unchanged. No write path makes this statement; it is the only
        such alternative that needs no approval (restating a pointer already
        recorded needs one first)."""
        stored = self.snapshot("contract_revisions")
        self.x("UPDATE contract_revisions SET approved_by_decision_id = NULL WHERE topic_id = ? AND revision = 1", TOPIC)
        self.assertEqual(self.snapshot("contract_revisions"), stored)
        self.assertEqual(self.rows("SELECT status, approved_by_decision_id FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC),
                         [("draft", None)])

    def test_approval_pointer_is_set_only_by_the_approval_transition(self) -> None:
        """RA3-R: a retained approving decision is evidence that its revision
        passed the draft -> approved transition, whose gate checks rows,
        ratings and coverage — so a dossier can rely on it. Draft 2 was rated;
        revision 3 carries the ratings with its rows (approvable); revision 4
        carries the same entries with its rows deliberately missing (the
        review's probe shape). Each has a valid contract_approval about its
        exact revision and hash. Refused, leaving every contract and dossier
        row unchanged: recording the decision while the revision stays a draft
        (the review's probe; on 3 and 4; also spelled as an upsert); the
        structural approval of 4; draft -> superseded with the decision (it
        would skip the approval gate) and without it — not an edge at all
        since ruling 1, so the status guard refuses it; approving 3 without
        naming its decision (the status CHECK); and a dossier under 3 or 4
        after each. Accepted: approving 3 with its
        decision in one update, then a dossier under it; after an amendment
        (revision 5) supersedes 3, revision 3 keeps its decision and a dossier
        under it is still accepted (historical pins)."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        rated = dict(band="critical", score=8, decision="opd_rate0001")
        entries = dict(facets=(facet("F-1", **rated),), obligations=(obligation("O-1", ("F-1",), **rated),))
        draft = self.rate("opd_rate0001", **entries)
        self.contract_with_rows(TOPIC, draft + 1, **entries, content_hash=self.chash(TOPIC, draft + 1))
        self.contract(TOPIC, draft + 2, **entries, parent=draft, content_hash=self.chash(TOPIC, draft + 2))
        self.assertEqual((draft, draft + 1, draft + 2), (2, 3, 4))
        for rev in (3, 4):
            self.decision(f"opd_appr{rev:04d}", "contract_approval", rev=rev, hsh=self.chash(TOPIC, rev))
        pointer = "UPDATE contract_revisions SET approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?"
        upsert = ("INSERT INTO contract_revisions SELECT topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, NULL, created_at "
                  "FROM contract_revisions WHERE topic_id = ? AND revision = ? ON CONFLICT (topic_id, revision) DO UPDATE SET approved_by_decision_id = ?")
        approve = "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?"
        supersede = "UPDATE contract_revisions SET status = 'superseded', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?"
        only = "recorded only by the draft -> approved transition"
        no_dossier = "never a draft"

        def dossier_refused(rev: int) -> None:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                self.dossier(9, rev, h("9"))
            self.assertIn(no_dossier, str(ctx.exception))

        stored = (self.snapshot("contract_revisions"), self.snapshot("dossiers"))
        for rev in (3, 4):
            with self.subTest(case="the decision recorded on a draft", revision=rev):
                self.rejects(only, pointer, f"opd_appr{rev:04d}", TOPIC, rev)
                self.rejects(only, upsert, TOPIC, rev, f"opd_appr{rev:04d}")
                dossier_refused(rev)
        with self.subTest(case="a failed structural approval"):
            self.rejects("approval needs complete obligation/facet rows", approve, "opd_appr0004", TOPIC, 4)
            dossier_refused(4)
        with self.subTest(case="draft -> superseded"):
            # Not an edge (ruling 1): the status guard refuses it. With a
            # decision named, the pointer guard refuses the same update too,
            # and which of the two SQLite fires first is trigger order, not
            # the invariant, so either is accepted. With none named, only the
            # status guard applies (triggers run before the CHECK).
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                self.x(supersede, "opd_appr0004", TOPIC, 4)
            self.assertTrue(any(f in str(ctx.exception) for f in (only, "draft -> approved -> superseded only")), str(ctx.exception))
            self.rejects("contract status moves draft -> approved -> superseded only",
                         "UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 4", TOPIC)
            dossier_refused(4)
        with self.subTest(case="approved without naming its decision"):
            # Revision 3 passes the approval gate (complete, rated, covered
            # rows), so the status CHECK is what refuses an approval that
            # records no decision.
            self.rejects("CHECK constraint failed: status = 'draft' OR approved_by_decision_id IS NOT NULL",
                         "UPDATE contract_revisions SET status = 'approved' WHERE topic_id = ? AND revision = 3", TOPIC)
            dossier_refused(3)
        self.assertEqual((self.snapshot("contract_revisions"), self.snapshot("dossiers")), stored)
        self.x(approve, "opd_appr0003", TOPIC, 3)
        self.dossier(1, 3, h("1"))
        self.contract_with_rows(TOPIC, 5, **entries, parent=3, content_hash=self.chash(TOPIC, 5))
        self.decision("opd_amend005", "amendment_approval", rev=5, hsh=self.chash(TOPIC, 5))
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 3", TOPIC)
        self.x(approve, "opd_amend005", TOPIC, 5)
        self.dossier(2, 3, h("2"))  # under the historically approved, now superseded revision
        self.dossier(3, 5, h("3"))
        self.assertEqual(self.rows("SELECT revision, status, approved_by_decision_id FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC),
                         [(1, "draft", None), (2, "draft", None), (3, "superseded", "opd_appr0003"), (4, "draft", None), (5, "approved", "opd_amend005")])
        self.assertEqual(self.rows("SELECT dossier_revision, contract_revision FROM dossiers ORDER BY dossier_revision"), [(1, 3), (2, 3), (3, 5)])

    def test_operator_rating_band_and_score_consistent(self) -> None:
        """Each probe's document entry carries the same values as its row, so the
        rejection is the band/score CHECK, not the document binding."""
        bad = (obligation("O-bad1", band="critical", score=5, decision="opd_00000001"),  # rated so by the payload too: only the CHECK refuses
               obligation("O-bad2", band="critical", score=8),
               obligation("O-bad3", score=8))  # a score without a band
        good = (obligation("O-1", band="critical", score=8, decision="opd_00000001"),
                obligation("O-2", band="important", decision="opd_00000001"),
                obligation("O-3"))
        draft = self.rate("opd_00000001", facets=(facet("F-1"),), obligations=bad + good)
        self.contract(TOPIC, draft + 1, facets=(facet("F-1"),), obligations=bad + good)
        self.insert_facet(TOPIC, draft + 1, facet("F-1"))
        for entry in bad:
            with self.subTest(obligation=entry["obligation_id"]):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, draft + 1, entry)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        for entry in good:
            self.insert_obligation(TOPIC, draft + 1, entry)
        self.rejects("obligations are immutable", "UPDATE obligations SET operator_importance_band = 'limited' WHERE obligation_id = 'O-2'")

    def next_revision(self, tid: str = TOPIC) -> int:
        return self.rows("SELECT coalesce(max(revision), 0) + 1 FROM contract_revisions WHERE topic_id = ?", tid)[0][0]

    def rated_revision(self, parent: int, *, obligations: tuple = (), facets: tuple = (facet("F-1"), facet("F-2")), facet_rows: bool = True) -> int:
        """A revision of TOPIC, child of `parent`, whose document carries these
        entries (and, by default, its facet rows); the caller writes the row
        under test."""
        rev = self.next_revision()
        self.contract(TOPIC, rev, facets=facets, obligations=obligations, parent=parent, content_hash=self.chash(TOPIC, rev))
        for entry in facets if facet_rows else ():
            self.insert_facet(TOPIC, rev, entry)
        return rev

    RATED = dict(band="critical", score=8)
    PAYLOAD_O1 = {"facets": {}, "obligations": {"O-1": {"band": "critical", "score": 8}}}

    def test_operator_rating_bound_to_a_rating_decision(self) -> None:
        """A2 / RA2 for obligation ratings. The operator rated draft 2
        (obligations O-1, O-2, O-3; the decision's retained payload rates O-1
        critical/8 and O-3 important with no score, and leaves O-2 unrated). A rated row must cite an approved
        rating decision of this topic about an ANCESTOR draft defining the
        obligation exactly as here, whose payload gives exactly this band and
        score. Each probe revision descends from draft 2 (unless lineage is the
        probe) and its document entry names the probe's decision, so only the
        rating binding can refuse: disposition, kind, topic (another topic's
        identical draft 2), a decision about the revision carrying it (a
        self-hash cycle), the review's probe (a decision about the EMPTY draft 1
        invoked for an invented obligation, and for O-1), an obligation the
        operator did not rate, a changed band (with and without a score) or
        score, the same id redefined, an unrelated sibling draft. RA2-R on top:
        no stored history makes a revision its own ancestor — a revision naming
        itself as parent, or two revisions naming each other in one INSERT, with
        the entry citing an approved decision (payload matching) about that very
        revision — so the rated row never lands; the ancestry CHECK refuses the
        history, and were it stored the rating binding would have to (either
        reason is accepted). No row is written by any of
        them; then an unchanged rating carries forward over two revisions."""
        o1 = obligation("O-1", ("F-1",), **self.RATED, decision="opd_00000001")
        o2 = obligation("O-2", ("F-2",))
        o3 = obligation("O-3", ("F-2",), band="important", decision="opd_00000001")  # rated without a score
        draft = self.rate("opd_00000001", facets=(facet("F-1"), facet("F-2")), obligations=(o1, o2, o3))
        self.assertEqual(draft, 2)
        self.decision("opd_rejected", "rating_approval", disposition="rejected", rev=draft, hsh=self.chash(TOPIC, draft), payload=self.PAYLOAD_O1)
        self.decision("opd_approval", "contract_approval", rev=draft, hsh=self.chash(TOPIC, draft))
        self.assertEqual(self.rate("opd_othertop", OTHER, facets=(facet("F-1"), facet("F-2")), obligations=(o1, o2, o3), payload=self.PAYLOAD_O1), draft)
        self.decision("opd_emptydft", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))  # draft 1 carries no obligation
        refused = "an obligation rating is exactly what the operator rated"

        def probe(label: str, entry: dict, parent: int = draft) -> None:
            with self.subTest(case=label):
                rev = self.rated_revision(parent, obligations=(entry,))
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, rev, entry)
                self.assertIn(refused, str(ctx.exception))

        for did in ("opd_rejected", "opd_approval", "opd_othertop"):
            probe(did, obligation("O-1", ("F-1",), **self.RATED, decision=did))
        samerev = obligation("O-1", ("F-1",), **self.RATED, decision="opd_samerev")
        rev = self.rated_revision(draft, obligations=(samerev,))
        self.decision("opd_samerev", "rating_approval", rev=rev, hsh=self.chash(TOPIC, rev), payload=self.PAYLOAD_O1)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_obligation(TOPIC, rev, samerev)
        self.assertIn(refused, str(ctx.exception))
        probe("the review's probe: an invented obligation under the empty draft's decision", obligation("O-new", ("F-1",), **self.RATED, decision="opd_emptydft"))
        probe("O-1 under the empty draft's decision", obligation("O-1", ("F-1",), **self.RATED, decision="opd_emptydft"))
        probe("an obligation the operator did not rate", obligation("O-2", ("F-2",), **self.RATED, decision="opd_00000001"))
        probe("a changed band and score", obligation("O-1", ("F-1",), band="important", decision="opd_00000001"))
        probe("a changed band alone (no score either way)", obligation("O-3", ("F-2",), band="limited", decision="opd_00000001"))
        probe("a changed score alone", obligation("O-1", ("F-1",), band="critical", score=9, decision="opd_00000001"))
        probe("the same id redefined", obligation("O-1", ("F-2",), **self.RATED, decision="opd_00000001"))
        probe("an unrelated (sibling) draft", o1, parent=1)
        for label, cyclic in (("a self-parent revision", False), ("a two-revision cycle", True)):
            with self.subTest(case=label):
                rev, did = self.next_revision(), f"opd_selfanc{int(cyclic)}"
                entry = obligation("O-1", ("F-1",), **self.RATED, decision=did)
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    if cyclic:
                        self.contract_cycle(TOPIC, rev, rev + 1, facets=(facet("F-1"), facet("F-2")), obligations=(entry,))
                    else:
                        self.contract(TOPIC, rev, facets=(facet("F-1"), facet("F-2")), obligations=(entry,), parent=rev, content_hash=self.chash(TOPIC, rev))
                    self.decision(did, "rating_approval", rev=rev, hsh=self.chash(TOPIC, rev), payload=self.PAYLOAD_O1)
                    for unrated in (facet("F-1"), facet("F-2")):
                        self.insert_facet(TOPIC, rev, unrated)
                    self.insert_obligation(TOPIC, rev, entry)
                self.assertTrue(any(f in str(ctx.exception) for f in ("contract_parent_is_earlier", refused)), str(ctx.exception))
                self.assertEqual(self.rows("SELECT count(*) FROM contract_revisions WHERE topic_id = ? AND revision >= ?", TOPIC, rev), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM obligations"), [(0,)])
        first = self.rated_revision(draft, obligations=(o1,))
        self.insert_obligation(TOPIC, first, o1)
        second = self.rated_revision(first, obligations=(o1,))
        self.insert_obligation(TOPIC, second, o1)
        self.assertEqual(self.rows("SELECT contract_revision, operator_importance_band, operator_importance_score FROM obligations ORDER BY contract_revision"),
                         [(first, "critical", 8), (second, "critical", 8)])

    def test_only_a_rating_decision_carries_a_rating_payload(self) -> None:
        """RA2: the retained payload is part of a rating decision (required), of
        no other kind, and rates only entries of the draft it is about, each
        with a band from the vocabulary."""
        ins = ("INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at, payload) "
               "VALUES ('opd_x', ?, ?, 'approved', 'contract_revision', ?, ?, ?, 'user', ?, ?)")
        draft = self.rate("opd_00000001", facets=(facet("F-1"),), obligations=(obligation("O-1", ("F-1",)),))
        ch = self.chash(TOPIC, draft)
        ok = json.dumps({"facets": {"F-1": {"band": "limited"}}, "obligations": {"O-1": {"band": "important", "score": 5}}})
        self.rejects("CHECK constraint failed", ins, TOPIC, "rating_approval", TOPIC, draft, ch, T, None)  # a rating without its payload
        self.rejects("CHECK constraint failed", ins, TOPIC, "contract_approval", TOPIC, draft, ch, T, ok)  # a payload on another kind
        self.rejects("CHECK constraint failed", ins, TOPIC, "rating_approval", TOPIC, draft, ch, T, json.dumps({"facets": {}}))  # malformed
        refused = "rates only entries of the draft the decision is about"
        for label, payload in (("a facet absent from the draft", {"facets": {"F-9": {"band": "limited"}}, "obligations": {}}),
                               ("an obligation absent from the draft", {"facets": {}, "obligations": {"O-9": {"band": "limited"}}}),
                               ("an obligation id given as a facet", {"facets": {"O-1": {"band": "limited"}}, "obligations": {}}),
                               ("a band outside the vocabulary", {"facets": {"F-1": {"band": "essential"}}, "obligations": {}}),
                               ("an obligation without a band", {"facets": {}, "obligations": {"O-1": {"score": 5}}})):
            with self.subTest(case=label):
                self.rejects(refused, ins, TOPIC, "rating_approval", TOPIC, draft, ch, T, json.dumps(payload))
        self.x(ins, TOPIC, "rating_approval", TOPIC, draft, ch, T, ok)

    def test_proposed_importance_cites_an_importance_receipt(self) -> None:
        """A2: a Jev-score proposal cites an importance_score decision receipt of
        the same topic; a receipt of another class or topic is refused."""
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        imp = self.spec("dspec_import01", cls="importance_score")
        self.decision_receipt("dec_screen01", "inv_pppppppp", self.spec())
        self.decision_receipt("dec_import01", "inv_pppppppp", imp, cls="importance_score")
        self.decision_receipt("dec_otherimp", "inv_oooooooo", imp, cls="importance_score", tid=OTHER)
        entries = {rid: obligation("O-" + rid, psource="jev_score", pscore=8, preceipt=rid) for rid in ("dec_screen01", "dec_otherimp", "dec_import01")}
        self.contract(TOPIC, 2, facets=(facet("F-1"),), obligations=tuple(entries.values()))
        self.insert_facet(TOPIC, 2, facet("F-1"))
        for rid in ("dec_screen01", "dec_otherimp"):
            with self.subTest(receipt=rid):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, 2, entries[rid])
                self.assertIn("importance_score receipt", str(ctx.exception))
        self.insert_obligation(TOPIC, 2, entries["dec_import01"])

    def dossier(self, rev: int, contract_rev: int, ch: str) -> None:
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, ?, ?, 1, 'eval-1', ?, ?, ?)", TOPIC, rev, contract_rev, ch, h("7"), T)

    def test_completion_needs_approval_of_current_dossier(self) -> None:
        """D54 rewrite (A2): the transition names an approved completion approval
        of the current dossier (revision + hash) evaluated under the active,
        approved contract. Each near-miss differs from a valid decision in one
        dimension: currency (stale dossier), disposition, kind (a rating
        decision whose subject revision/hash deliberately coincide with the
        current dossier's), naming (a valid approval exists but the transition
        names another), protocol (dossier under an approved but non-active
        contract; under the active contract after an amendment superseded it
        — a dossier under a draft cannot even be written, RA3)."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        self.approve_contract(TOPIC, 1)
        self.walk_to(TOPIC, "active")
        self.x("UPDATE queue_entries SET active_contract_revision = 1 WHERE topic_id = ?", TOPIC)
        complete = "UPDATE queue_entries SET status = 'completed_with_qualified_conclusions', status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?"
        refused = "completion requires operator approval"
        self.dossier(1, 1, h("3"))
        self.decision("opd_stale001", "completion_approval", rev=1, hsh=h("3"))
        self.dossier(2, 1, h("4"))  # material change after that approval
        self.rejects(refused, complete, "opd_stale001", TOPIC)
        self.decision("opd_rejected", "completion_approval", disposition="rejected", rev=2, hsh=h("4"))
        self.rejects(refused, complete, "opd_rejected", TOPIC)
        self.rejects("existing subject", "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_wronghsh', ?, 'completion_approval', 'approved', 'dossier', ?, 2, ?, 'user', ?)", TOPIC, TOPIC, h("3"), T)
        for rev in (2, 3, 4, 5):
            self.contract(TOPIC, rev)
        self.dossier(5, 1, self.content_hash_of(TOPIC, 5))  # current dossier carrying contract 5's hash
        self.decision("opd_wrongknd", "rating_approval", rev=5, hsh=self.content_hash_of(TOPIC, 5))
        self.rejects(refused, complete, "opd_wrongknd", TOPIC)
        self.approve_contract(OTHER, 1)
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 5, 1, 1, 'eval-1', ?, ?, ?)", OTHER, h("9"), h("7"), T)
        self.decision("opd_othertop", "completion_approval", tid=OTHER, rev=5, hsh=h("9"))
        self.rejects(refused, complete, "opd_othertop", TOPIC)  # another topic's approval of its own dossier 5
        self.decision("opd_valid005", "completion_approval", rev=5, hsh=self.content_hash_of(TOPIC, 5))
        self.rejects(refused, complete, "opd_wrongknd", TOPIC)  # a valid approval exists, but is not the one named
        self.x("UPDATE queue_entries SET active_contract_revision = 2 WHERE topic_id = ?", TOPIC)
        self.rejects(refused, complete, "opd_valid005", TOPIC)  # dossier's contract (approved) is not the active one
        # RA3: no dossier is ever evaluated against a draft (revision 2 is one)
        self.rejects("never a draft", "INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 6, 2, 1, 'eval-1', ?, ?, ?)", TOPIC, h("6"), h("7"), T)
        # protocol currency: the dossier's (active) contract was approved, then superseded by an amendment
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.approve_contract(TOPIC, 2, kind="amendment_approval")
        self.dossier(6, 2, h("6"))
        self.decision("opd_supersed", "completion_approval", rev=6, hsh=h("6"))
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 2", TOPIC)
        self.approve_contract(TOPIC, 3, kind="amendment_approval")
        self.rejects(refused, complete, "opd_supersed", TOPIC)  # dossier under the active contract, which is no longer approved
        self.x("UPDATE queue_entries SET active_contract_revision = 3 WHERE topic_id = ?", TOPIC)
        self.dossier(7, 3, h("8"))
        self.decision("opd_00000001", "completion_approval", rev=7, hsh=h("8"))
        self.x(complete, "opd_00000001", TOPIC)
        self.assertEqual(self.rows("SELECT status, status_decision_id FROM queue_entries WHERE topic_id = ?", TOPIC), [("completed_with_qualified_conclusions", "opd_00000001")])
        self.assert_terminal_authority_kept(TOPIC, "completed_with_qualified_conclusions", "opd_00000001",
                                            also_valid=self.decision("opd_second01", "completion_approval", rev=7, hsh=h("8")))
        # the pointer does move with an authorized transition: completed -> retired
        self.decision("opd_retire01", "retirement", rev=self.state_revision())
        self.x("UPDATE queue_entries SET status = 'retired', status_decision_id = 'opd_retire01', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.assertEqual(self.rows("SELECT status, status_decision_id FROM queue_entries WHERE topic_id = ?", TOPIC), [("retired", "opd_retire01")])

    def assert_terminal_authority_kept(self, tid: str, status: str, used: str, also_valid: str) -> None:
        """RA1: after a terminal transition the authorizing-decision pointer keeps
        the decision actually used. The review's probe first — a rejected
        retirement decision about ANOTHER topic written over it with status and
        revision unchanged — then the same with the revision advanced, clearing
        it, another valid approval of the same subject, and simultaneous
        status+decision writes (same status re-asserted; a gated transition
        naming the rejected decision). Each is refused and the row reads back
        unchanged."""
        if not self.rows("SELECT 1 FROM operator_decisions WHERE decision_id = 'opd_unrelatd'"):
            self.decision("opd_unrelatd", "retirement", OTHER, disposition="rejected", rev=0)
        before = self.snapshot("queue_entries")
        moved = "changes only with the status transition it authorizes"
        for label, sql, fragment in (
                ("rejected other-topic decision, nothing else changed (the review's probe)", "UPDATE queue_entries SET status_decision_id = 'opd_unrelatd' WHERE topic_id = ?", moved),
                ("same, revision advanced", "UPDATE queue_entries SET status_decision_id = 'opd_unrelatd', state_revision = state_revision + 1 WHERE topic_id = ?", moved),
                ("cleared", "UPDATE queue_entries SET status_decision_id = NULL WHERE topic_id = ?", moved),
                ("another valid approval of the same subject", f"UPDATE queue_entries SET status_decision_id = '{also_valid}' WHERE topic_id = ?", moved),
                ("same status re-asserted with the rejected decision", f"UPDATE queue_entries SET status = '{status}', status_decision_id = 'opd_unrelatd', state_revision = state_revision + 1 WHERE topic_id = ?", moved),
                ("a gated transition naming the rejected decision", "UPDATE queue_entries SET status = 'retired', status_decision_id = 'opd_unrelatd', state_revision = state_revision + 1 WHERE topic_id = ?", None)):
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.x(sql, tid)
                if fragment:
                    self.assertIn(fragment, str(ctx.exception))
                self.assertEqual(self.snapshot("queue_entries"), before)
        self.assertEqual(self.rows("SELECT status, status_decision_id FROM queue_entries WHERE topic_id = ?", tid), [(status, used)])

    def test_retirement_needs_operator_decision(self) -> None:
        """D55 rewrite (A2): the transition names an approved retirement decision
        about this topic at the state revision being left. Near-misses, one
        dimension each: no decision, stale revision, disposition, topic (same
        revision number), kind (a completion approval whose subject revision
        equals the current state revision), naming (a valid decision exists but
        another is named); and retired is final (draft vocabulary, R2.5), so a
        used decision has no transition left to authorize."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        self.approve_contract(TOPIC, 1)  # the wrong-kind probe below needs a dossier, and dossiers need an approved protocol (RA3)
        retire = "UPDATE queue_entries SET status = 'retired', status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?"
        refused = "retirement requires"
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(retire, None, TOPIC)  # no decision named at all
        self.decision("opd_stale000", "retirement", rev=self.state_revision())
        self.confirm_brief(TOPIC)
        self.set_status(TOPIC, "scoping")  # a commit after the decision makes it stale
        now = self.state_revision()
        self.rejects(refused, retire, "opd_stale000", TOPIC)
        self.decision("opd_rejected", "retirement", disposition="rejected", rev=now)
        self.decision("opd_othertop", "retirement", tid=OTHER, rev=now)
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, ?, 1, 1, 'eval-1', ?, ?, ?)", TOPIC, now, h("3"), h("7"), T)
        self.decision("opd_wrongknd", "completion_approval", rev=now, hsh=h("3"))
        for did in ("opd_rejected", "opd_othertop", "opd_wrongknd"):
            with self.subTest(decision=did):
                self.rejects(refused, retire, did, TOPIC)
        self.decision("opd_00000001", "retirement", rev=now)
        self.rejects(refused, retire, "opd_stale000", TOPIC)  # a valid decision exists, but is not the one named
        self.x(retire, "opd_00000001", TOPIC)
        self.rejects("queue status transition not allowed", "UPDATE queue_entries SET status = 'queued', status_decision_id = NULL, state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        # RA1: the used decision stays on the retired row (the rejected same-topic
        # decision, an approved other-topic one, and the review's other-topic
        # rejected decision are all refused)
        for did in ("opd_rejected", "opd_othertop"):
            with self.subTest(substitute=did):
                self.rejects("changes only with the status transition it authorizes", "UPDATE queue_entries SET status_decision_id = ? WHERE topic_id = ?", did, TOPIC)
        self.assert_terminal_authority_kept(TOPIC, "retired", "opd_00000001", also_valid=self.decision("opd_second01", "retirement", rev=now))

    def test_terminal_statuses_cannot_be_inserted(self) -> None:
        """A2: creation is constrained to the initial intake status."""
        ins = "INSERT INTO queue_entries (topic_id, fleet_id, priority, status, status_decision_id, state_revision, created_at, updated_at) VALUES ('fleet-a:t3', 'fleet-a', 1, ?, ?, ?, ?, ?)"
        self.decision("opd_00000001", "retirement", rev=self.state_revision())
        for status, did in (("retired", "opd_00000001"), ("completed_with_qualified_conclusions", "opd_00000001"), ("active", None)):
            with self.subTest(status=status):
                self.rejects("created awaiting brief confirmation", ins, status, did, 0, T, T)
        self.rejects("created awaiting brief confirmation", ins, "awaiting_brief_confirmation", None, 5, T, T)
        self.x(ins, "awaiting_brief_confirmation", None, 0, T, T)

    def test_status_change_is_a_commit(self) -> None:
        self.confirm_brief(TOPIC)  # leaving intake needs a confirmed brief (G-4); here only the revision rule may refuse
        self.rejects("advances state_revision by one", "UPDATE queue_entries SET status = 'scoping' WHERE topic_id = ?", TOPIC)
        self.set_status(TOPIC, "scoping")
        self.assertEqual(self.state_revision(), 1)
        # the authorizing decision is recorded only with a decision-gated status
        self.decision("opd_00000001", "retirement", rev=self.state_revision())
        self.rejects("CHECK constraint failed", "UPDATE queue_entries SET status = 'awaiting_scope_approval', status_decision_id = 'opd_00000001', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.set_status(TOPIC, "retired", "opd_00000001")


class DraftVocabularyTransitionTest(StoreTestCase):
    """Ruling R2.5: the draft queue and claim vocabularies carry explicit,
    tested transition semantics. Oracles are hand-written from the README's
    "Draft vocabularies" section, not read from the DDL."""

    QUEUE = {
        "awaiting_brief_confirmation": {"scoping", "retired"},
        "scoping": {"awaiting_scope_approval", "held", "capability_blocked", "retired"},
        "awaiting_scope_approval": {"awaiting_contract_approval", "scoping", "retired"},
        "awaiting_contract_approval": {"queued", "scoping", "retired"},
        "queued": {"active", "held", "capability_blocked", "retired"},
        "active": {"resting", "queued", "held", "awaiting_judgment", "completed_with_qualified_conclusions", "capability_blocked", "stopped_for_resources", "retired"},
        "resting": {"active", "queued", "held", "retired"},
        "held": {"scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued", "retired"},
        "capability_blocked": {"scoping", "queued", "held", "retired"},
        "stopped_for_resources": {"queued", "awaiting_judgment", "retired"},
        "awaiting_judgment": {"active", "queued", "completed_with_qualified_conclusions", "stopped_for_resources", "retired"},
        "completed_with_qualified_conclusions": {"queued", "retired"},
        "retired": set(),
    }
    CLAIMS = {
        "provisional": {"accepted_support", "contested", "rejected", "quarantined", "superseded"},
        "accepted_support": {"contested", "quarantined", "superseded"},
        "contested": {"accepted_support", "rejected", "quarantined", "superseded"},
        "quarantined": {"provisional", "rejected", "superseded"},
        "rejected": {"superseded"},
        "superseded": set(),
    }
    CLAIM_PATH = {"provisional": (), "accepted_support": ("accepted_support",), "contested": ("contested",), "quarantined": ("quarantined",),
                  "rejected": ("rejected",), "superseded": ("superseded",)}

    def fresh_topic(self, n: int) -> str:
        """A new topic with a confirmed intake brief, whose revision-1 contract
        is approved and active, with a current dossier and a valid completion
        approval of it, so leaving intake, completion and retirement attempts
        are decided by the transition rule alone."""
        tid = f"fleet-a:m{n:04d}"
        self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)", tid, T, T)
        self.confirm_brief(tid)
        self.contract(tid, 1, content_hash="sha256:" + f"{n:060x}c0c0")
        self.approve_contract(tid, 1, did=f"opd_ca{n:06d}")
        self.x("UPDATE queue_entries SET active_contract_revision = 1 WHERE topic_id = ?", tid)
        dossier_hash = "sha256:" + f"{n:060x}d0d0"
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 1, 1, 1, 'eval-1', ?, ?, ?)", tid, dossier_hash, h("7"), T)
        self.decision(f"opd_co{n:06d}", "completion_approval", tid, rev=1, hsh=dossier_hash)
        return tid

    def reach(self, tid: str, n: int, status: str) -> None:
        if status == "completed_with_qualified_conclusions":
            self.walk_to(tid, "active")
            self.set_status(tid, status, f"opd_co{n:06d}")
        elif status == "retired":
            self.decision(f"opd_rt{n:06d}", "retirement", tid, rev=self.state_revision(tid))
            self.set_status(tid, status, f"opd_rt{n:06d}")
        else:
            self.walk_to(tid, status)

    def test_queue_status_transitions(self) -> None:
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        n = 0
        for src, allowed in self.QUEUE.items():
            for dst in self.QUEUE:
                if dst == src:
                    continue
                n += 1
                with self.subTest(src=src, dst=dst):
                    tid = self.fresh_topic(n)
                    self.reach(tid, n, src)
                    decision = None
                    if dst == "completed_with_qualified_conclusions":
                        decision = f"opd_co{n:06d}"
                    elif dst == "retired":
                        decision = f"opd_rx{n:06d}"
                        self.decision(decision, "retirement", tid, rev=self.state_revision(tid))
                    attempt = "UPDATE queue_entries SET status = ?, status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?"
                    if dst in allowed:
                        self.x(attempt, dst, decision, tid)
                        self.assertEqual(self.rows("SELECT status FROM queue_entries WHERE topic_id = ?", tid), [(dst,)])
                    else:
                        self.rejects("queue status transition not allowed", attempt, dst, decision, tid)
        self.assertEqual(n, 13 * 12)

    def test_claim_status_transitions(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'text/plain', ?)", h("7"), T)
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        n = 0
        for src, allowed in self.CLAIMS.items():
            for dst in self.CLAIMS:
                if dst == src:
                    continue
                n += 1
                with self.subTest(src=src, dst=dst):
                    cid = f"clm_{n:08d}"
                    # non-load-bearing, so accepted_support is decided by the transition rule alone
                    self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES (?, 1, ?, ?, 'inv_pppppppp', 0, NULL, 'provisional', ?)", cid, TOPIC, h("7"), T)
                    for step in self.CLAIM_PATH[src]:
                        self.x("UPDATE claims SET status = ? WHERE claim_id = ?", step, cid)
                    attempt = "UPDATE claims SET status = ? WHERE claim_id = ?"
                    if dst in allowed:
                        self.x(attempt, dst, cid)
                    else:
                        self.rejects("claim status transition not allowed", attempt, dst, cid)
        self.assertEqual(n, 6 * 5)

    def test_mandatory_signals_are_code_or_operator_raised(self) -> None:
        """G-12 / R2.5: retraction and decision-record-change triggers are never a
        model observation (a model may rank discretionary alerts only)."""
        ins = "INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, ?, ?, 'SRC-9', ?)"
        for n, reason in enumerate(("retraction", "decision_record_change")):
            with self.subTest(reason=reason):
                self.rejects("CHECK constraint failed", ins, h(str(n)), TOPIC, reason, "primary_observation", T)
                self.x(ins, h(str(n)), TOPIC, reason, "deterministic", T)
        self.x(ins, h("9"), TOPIC, "persistent_contradiction", "primary_observation", T)  # discretionary signals may be observations


class FacetImportanceTest(StoreTestCase):
    """A3: facet importance is its own record, bound to the hash-locked
    document and the operator's rating decision — never inferred from
    obligations — and G-3's uncovered-critical-facet rule gates approval."""

    def approve(self, rev: int) -> None:
        self.decision(f"opd_appr{rev:04d}", "contract_approval", rev=rev, hsh=self.content_hash_of(TOPIC, rev))
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?", f"opd_appr{rev:04d}", TOPIC, rev)

    def uncovered(self, rev: int) -> list[tuple]:
        return self.rows("SELECT facet_id FROM uncovered_critical_facets WHERE topic_id = ? AND contract_revision = ? ORDER BY facet_id", TOPIC, rev)

    def test_critical_facet_with_zero_obligations_is_representable_and_blocks_approval(self) -> None:
        # F-omitted is rated critical by the operator (who rated draft 2) and no obligation tags it
        f_omitted = facet("F-omitted", band="critical", score=8, decision="opd_rate0001")
        f2 = facet("F-2", band="important", decision="opd_rate0001")
        o1 = obligation("O-1", ("F-2",), band="important", decision="opd_rate0001")
        draft = self.rate("opd_rate0001", facets=(f_omitted, f2), obligations=(o1,))
        self.contract_with_rows(TOPIC, draft + 1, facets=(f_omitted, f2), obligations=(o1,))
        self.assertEqual(self.rows("SELECT operator_importance_band FROM facets WHERE facet_id = 'F-omitted'"), [("critical",)])
        self.assertEqual(self.uncovered(draft + 1), [("F-omitted",)])
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.approve(draft + 1)
        self.assertIn("no uncovered critical facet", str(ctx.exception))
        # a revision whose obligation tags the critical facet is approvable
        self.contract_with_rows(TOPIC, draft + 2, facets=(f_omitted,), obligations=(obligation("O-2", ("F-omitted",)),))
        self.assertEqual(self.uncovered(draft + 2), [])
        self.approve(draft + 2)

    def test_approval_needs_complete_rows_and_every_facet_rated(self) -> None:
        both = (facet("F-1", band="limited", decision="opd_rate0001"), facet("F-2", band="limited", decision="opd_rate0001"))
        d = self.rate("opd_rate0001", facets=both)
        # a document facet without its row
        self.contract(TOPIC, d + 1, facets=both, obligations=(obligation("O-1", ("F-1",)),))
        self.insert_facet(TOPIC, d + 1, both[0])
        self.insert_obligation(TOPIC, d + 1, obligation("O-1", ("F-1",)))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(d + 1)
        # a document obligation without its row
        self.contract(TOPIC, d + 2, facets=both, obligations=(obligation("O-1", ("F-1",)), obligation("O-2", ("F-2",))))
        for entry in both:
            self.insert_facet(TOPIC, d + 2, entry)
        self.insert_obligation(TOPIC, d + 2, obligation("O-1", ("F-1",)))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(d + 2)
        # an unrated facet (its importance could not be known critical)
        self.contract_with_rows(TOPIC, d + 3, facets=(both[0], facet("F-2")), obligations=(obligation("O-1", ("F-1",)),))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(d + 3)
        self.contract_with_rows(TOPIC, d + 4, facets=both, obligations=(obligation("O-1", ("F-1",)),))
        self.approve(d + 4)

    def test_facet_row_must_equal_its_document_entry(self) -> None:
        doc_entry = facet("F-1", band="critical", score=8, decision="opd_rate0001")
        d = self.rate("opd_rate0001", facets=(doc_entry,))
        self.contract(TOPIC, d + 1, facets=(doc_entry,))
        # a rated probe that differs from what the operator rated is refused by the
        # rating binding too; which of the two reports first is SQLite's trigger
        # order, not the invariant, so either reason is accepted there
        document, rating = "equal its document entry", "exactly what the operator rated"
        for field, row, reasons in (("band", facet("F-1", band="important", decision="opd_rate0001"), (document, rating)),
                                    ("score", facet("F-1", band="critical", score=9, decision="opd_rate0001"), (document, rating)),
                                    ("unrated", facet("F-1"), (document,)),
                                    ("absent", facet("F-9", band="critical", score=8, decision="opd_rate0001"), (document, rating))):
            with self.subTest(field=field):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_facet(TOPIC, d + 1, row)
                self.assertTrue(any(reason in str(ctx.exception) for reason in reasons), str(ctx.exception))
        self.insert_facet(TOPIC, d + 1, doc_entry)

    def test_facet_rating_bound_to_a_rating_decision(self) -> None:
        """A3 / RA2 for facet ratings, mirroring the obligation test: the operator
        rated draft 2 (F-1 critical/8, F-3 important with no score; F-2
        present but unrated). Near-misses,
        one dimension each, with the probe's own decision named in its
        document entry: disposition, kind, topic (another topic's identical
        draft), a decision about the revision carrying it, the review's probe
        (the empty draft 1's decision invoked for an invented facet), a facet
        the operator did not rate, a changed band (with and without a score)
        or score, the same id redefined (another label), an unrelated sibling
        draft; and RA2-R, as for obligations: a self-parent revision and a
        two-revision cycle, the entry citing an approved decision (payload
        matching) about that very revision, never yield a rated row (the
        ancestry CHECK or the rating binding refuses). Then the
        out-of-band CHECK (the payload rates it so, so only the CHECK refuses),
        immutability, and an unchanged carry-forward over two revisions."""
        f1 = facet("F-1", band="critical", score=8, decision="opd_rate0001")
        f3 = facet("F-3", band="important", decision="opd_rate0001")  # rated without a score
        out_of_band = facet("F-x", band="critical", score=5, decision="opd_rate0001")
        draft = self.rate("opd_rate0001", facets=(f1, facet("F-2"), f3, out_of_band))
        payload = {"facets": {"F-1": {"band": "critical", "score": 8}}, "obligations": {}}
        self.decision("opd_rejected", "rating_approval", disposition="rejected", rev=draft, hsh=self.chash(TOPIC, draft), payload=payload)
        self.decision("opd_approval", "contract_approval", rev=draft, hsh=self.chash(TOPIC, draft))
        self.rate("opd_othertop", OTHER, facets=(f1, facet("F-2"), f3, out_of_band), payload=payload)
        self.decision("opd_emptydft", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        refused = "a facet rating is exactly what the operator rated"

        def revision(entry: dict, parent: int = draft) -> int:
            rev = self.rows("SELECT max(revision) + 1 FROM contract_revisions WHERE topic_id = ?", TOPIC)[0][0]
            self.contract(TOPIC, rev, facets=(entry,), parent=parent, content_hash=self.chash(TOPIC, rev))
            return rev

        def probe(label: str, entry: dict, parent: int = draft) -> None:
            with self.subTest(case=label):
                rev = revision(entry, parent)
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_facet(TOPIC, rev, entry)
                self.assertIn(refused, str(ctx.exception))

        for did in ("opd_rejected", "opd_approval", "opd_othertop"):
            probe(did, facet("F-1", band="critical", score=8, decision=did))
        samerev = facet("F-1", band="critical", score=8, decision="opd_samerev")
        rev = revision(samerev)
        self.decision("opd_samerev", "rating_approval", rev=rev, hsh=self.chash(TOPIC, rev), payload=payload)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_facet(TOPIC, rev, samerev)
        self.assertIn(refused, str(ctx.exception))
        probe("the review's probe: an invented facet under the empty draft's decision", facet("F-new", band="critical", score=9, decision="opd_emptydft"))
        probe("a facet the operator did not rate", facet("F-2", band="critical", score=8, decision="opd_rate0001"))
        probe("a changed band and score", facet("F-1", band="limited", score=1, decision="opd_rate0001"))
        probe("a changed band alone (no score either way)", facet("F-3", band="limited", decision="opd_rate0001"))
        probe("a changed score alone", facet("F-1", band="critical", score=9, decision="opd_rate0001"))
        probe("the same id redefined", dict(f1, label="another subject"))
        probe("an unrelated (sibling) draft", f1, parent=1)
        for label, cyclic in (("a self-parent revision", False), ("a two-revision cycle", True)):
            with self.subTest(case=label):
                rev = self.rows("SELECT max(revision) + 1 FROM contract_revisions WHERE topic_id = ?", TOPIC)[0][0]
                did = f"opd_selfanc{int(cyclic)}"
                entry = facet("F-1", band="critical", score=8, decision=did)
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    if cyclic:
                        self.contract_cycle(TOPIC, rev, rev + 1, facets=(entry,))
                    else:
                        self.contract(TOPIC, rev, facets=(entry,), parent=rev, content_hash=self.chash(TOPIC, rev))
                    self.decision(did, "rating_approval", rev=rev, hsh=self.chash(TOPIC, rev), payload=payload)
                    self.insert_facet(TOPIC, rev, entry)
                self.assertTrue(any(f in str(ctx.exception) for f in ("contract_parent_is_earlier", refused)), str(ctx.exception))
                self.assertEqual(self.rows("SELECT count(*) FROM contract_revisions WHERE topic_id = ? AND revision >= ?", TOPIC, rev), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM facets"), [(0,)])
        rev = revision(out_of_band)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_facet(TOPIC, rev, out_of_band)
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        first = revision(f1)
        self.insert_facet(TOPIC, first, f1)
        self.rejects("facets are immutable", "UPDATE facets SET operator_importance_band = 'limited'")
        second = revision(f1, parent=first)
        self.insert_facet(TOPIC, second, f1)
        self.assertEqual(self.rows("SELECT contract_revision, operator_importance_band, operator_importance_score FROM facets ORDER BY contract_revision"),
                         [(first, "critical", 8), (second, "critical", 8)])

    def test_facet_proposal_cites_an_importance_receipt(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        imp = self.spec("dspec_import01", cls="importance_score")
        self.decision_receipt("dec_screen01", "inv_pppppppp", self.spec())
        self.decision_receipt("dec_import01", "inv_pppppppp", imp, cls="importance_score")
        self.decision_receipt("dec_otherimp", "inv_oooooooo", imp, cls="importance_score", tid=OTHER)
        entries = {rid: facet("F-" + rid, psource="jev_score", pscore=8, preceipt=rid) for rid in ("dec_screen01", "dec_otherimp", "dec_import01")}
        self.contract(TOPIC, 2, facets=tuple(entries.values()))
        for rid in ("dec_screen01", "dec_otherimp"):
            with self.subTest(receipt=rid):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert_facet(TOPIC, 2, entries[rid])
        self.insert_facet(TOPIC, 2, entries["dec_import01"])

    def test_obligation_row_equals_its_entry_and_tags_only_its_facets(self) -> None:
        """A3 / RA6: an obligation row equals its document entry in every field
        it duplicates — facet tags, importance, template id/version/claim
        type, stopping profile, exploratory flag — and tags only facets of
        its revision."""
        entry = obligation("O-1", ("F-1",), band="important", decision="opd_rate0001")
        d = self.rate("opd_rate0001", facets=(facet("F-1"),), obligations=(entry,))
        self.contract(TOPIC, d + 1, facets=(facet("F-1"), facet("F-1b")), obligations=(entry, obligation("O-2", ("F-9",))))
        self.insert_facet(TOPIC, d + 1, facet("F-1"))
        self.insert_facet(TOPIC, d + 1, facet("F-1b"))
        # each row differs from its entry in one field. The rating binding reads
        # the documents, so it passes the tag probe and has nothing to check on
        # the unrated one; the band probe also differs from what the operator
        # rated, so the rating binding refuses it too (either reason is accepted:
        # which reports first is SQLite's trigger order, not the invariant)
        document, rating = "equal its document entry", "exactly what the operator rated"
        for name, row, reasons in (("facet tags (another facet of the revision)", obligation("O-1", ("F-1", "F-1b"), band="important", decision="opd_rate0001"), (document,)),
                                   ("band", obligation("O-1", ("F-1",), band="critical", decision="opd_rate0001"), (document, rating)),
                                   ("unrated row for a rated entry", obligation("O-1", ("F-1",)), (document,))):
            with self.subTest(field=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, d + 1, row)
                self.assertTrue(any(reason in str(ctx.exception) for reason in reasons), str(ctx.exception))
        # RA6: the protocol fields accounting reads (the review's probe values)
        for column, value in (("template_id", "T-approved"), ("template_version", 3), ("claim_type", "mechanism"),
                              ("stopping_profile_id", "SP-approved"), ("exploratory", 1)):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, d + 1, entry, **{column: value})
                self.assertIn("equal its document entry", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_obligation(TOPIC, d + 1, obligation("O-2", ("F-9",)))  # matches its entry, but F-9 is no facet of the revision
        self.assertIn("tag only facets of its revision", str(ctx.exception))
        self.insert_obligation(TOPIC, d + 1, entry)


if __name__ == "__main__":
    unittest.main()
