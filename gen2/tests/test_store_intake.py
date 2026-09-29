"""Durable intake briefs (task 0b; INVARIANTS G-4, C-12, G-13, §13).

Trace: flow S1 — the brief is confirmed by an explicit, versioned operator
act; unconfirmed briefs cannot advance (structural); a draft brief is a
durable intake item with an operator owner, awaiting_confirmation state,
creation time and review deadline; expiry marks it overdue and never
advances it; cancellation and archival are explicit acts; §6.1 — an edited
brief re-versions. Adjudication (a)G-A8.

Oracle: transitions and refusals written by hand from the flow text and the
README's brief lifecycle table, never read from the DDL; each refused write
is followed by a read-back showing nothing changed.

What these tests cannot show: that the deadline has actually passed when a
brief is marked overdue (the router compares instants; the DDL stores
router-validated text), or anything about the Phase 1 confirmation and
amendment fencing of in-flight work.
"""
from __future__ import annotations

import json
import sqlite3
import unittest

from gen2.tests.store_fixtures import OTHER, TOPIC, StoreTestCase, T, h

LATER = "2026-09-26T12:00:00Z"
UPDATE = "UPDATE intake_briefs SET {} WHERE topic_id = ? AND brief_id = 'brief-1' AND version = ?"


class IntakeBriefTest(StoreTestCase):
    def status(self, version: int = 1) -> tuple:
        return self.rows("SELECT status, confirmed_by_decision_id, overdue_since, closed_at FROM intake_briefs WHERE topic_id = ? AND brief_id = 'brief-1' AND version = ?",
                         TOPIC, version)[0]

    def rejects_any(self, fragments: tuple, sql: str, *params) -> None:
        """Refused, by any of these guards: where several refuse one write,
        which one SQLite reports is trigger order, not the rule."""
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.x(sql, *params)
        self.assertTrue(any(f in str(ctx.exception) for f in fragments), str(ctx.exception))

    def confirm(self, did: str, version: int = 1) -> None:
        self.x(UPDATE.format("status = 'confirmed', confirmed_by_decision_id = ?"), did, TOPIC, version)

    def test_a_brief_is_written_awaiting_confirmation_with_owner_and_deadline(self) -> None:
        cols = ("topic_id, brief_id, version, parent_version, content_hash, document, owner_operator_id, status, created_at, review_deadline, "
                "overdue_since, confirmed_by_decision_id, closed_by, closed_at, close_reason")
        ins = f"INSERT INTO intake_briefs ({cols}) VALUES (?, 'brief-1', 1, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        doc = json.dumps({"topic_id": TOPIC, "brief_id": "brief-1", "version": 1, "parent_version": None, "created_at": T, "content_hash": h("b")})
        for case, row in (("confirmed", ("confirmed", T, None, None, None, None, None)),
                          ("overdue", ("awaiting_confirmation", T, T, None, None, None, None)),
                          ("cancelled", ("cancelled", T, None, None, "user", T, "dup")),
                          ("archived", ("archived", T, None, None, "user", T, "done"))):
            with self.subTest(inserted=case):
                self.rejects("written awaiting confirmation", ins, TOPIC, h("b"), doc, "user", row[0], T, row[1], row[2], row[3], row[4], row[5], row[6])
        with self.subTest(owner="empty"):
            self.rejects("CHECK constraint failed", ins, TOPIC, h("b"), doc, "", "awaiting_confirmation", T, T, None, None, None, None, None)
        base = json.loads(doc)
        for field, value in (("topic_id", OTHER), ("brief_id", "brief-2"), ("version", 2), ("parent_version", 1), ("created_at", LATER), ("content_hash", h("c"))):
            with self.subTest(document_field=field):
                self.rejects("CHECK constraint failed", ins, TOPIC, h("b"), json.dumps(dict(base, **{field: value})), "user", "awaiting_confirmation", T, T, None, None, None, None, None)
        self.assertEqual(self.rows("SELECT count(*) FROM intake_briefs"), [(0,)])
        self.x(ins, TOPIC, h("b"), doc, "user", "awaiting_confirmation", T, LATER, None, None, None, None, None)
        self.assertEqual(self.rows("SELECT owner_operator_id, status, review_deadline FROM intake_briefs"), [("user", "awaiting_confirmation", LATER)])

    def test_confirmation_names_an_approved_decision_about_exactly_this_version(self) -> None:
        """Near-misses, one dimension each: no decision, a rejected one, one
        of another kind, one about another (stored) version, one about
        another topic's brief. The exact decision is accepted, recorded by
        that transition only, and never changes afterwards."""
        b1 = self.brief(TOPIC)
        b2 = self.brief(TOPIC, "brief-1", 2, parent=1)
        ob = self.brief(OTHER, "brief-1", 1)
        self.decision("opd_rejected", "brief_confirmation", disposition="rejected", ref="brief-1", rev=1, hsh=b1)
        self.decision("opd_wrongknd", "publication_approval", ref="brief-1", rev=1, hsh=b1)  # task 2a: a kind whose subject has no stored table (a scope approval now needs a stored report)
        self.decision("opd_otherver", "brief_confirmation", ref="brief-1", rev=2, hsh=b2)
        self.decision("opd_othertop", "brief_confirmation", tid=OTHER, ref="brief-1", rev=1, hsh=ob)
        self.decision("opd_confirm1", "brief_confirmation", ref="brief-1", rev=1, hsh=b1)
        self.decision("opd_confirmb", "brief_confirmation", ref="brief-1", rev=1, hsh=b1)
        refused = "confirming a brief needs an approved brief_confirmation decision about this exact"
        for did in (None, "opd_rejected", "opd_wrongknd", "opd_otherver", "opd_othertop"):
            with self.subTest(decision=did):
                self.rejects(refused, UPDATE.format("status = 'confirmed', confirmed_by_decision_id = ?"), did, TOPIC, 1)
                self.assertEqual(self.status(), ("awaiting_confirmation", None, None, None))
        with self.subTest(case="the pointer recorded without the transition"):
            self.rejects("recorded only by the awaiting_confirmation -> confirmed transition", UPDATE.format("confirmed_by_decision_id = 'opd_confirm1'"), TOPIC, 1)
        with self.subTest(case="superseded with a pointer (would skip the gate)"):
            self.rejects("recorded only by the awaiting_confirmation -> confirmed transition",
                         UPDATE.format("status = 'superseded', confirmed_by_decision_id = 'opd_confirm1'"), TOPIC, 1)
        self.confirm("opd_confirm1")
        self.assertEqual(self.status(), ("confirmed", "opd_confirm1", None, None))
        self.rejects("recorded only by the awaiting_confirmation -> confirmed transition", UPDATE.format("confirmed_by_decision_id = 'opd_confirmb'"), TOPIC, 1)
        self.assertEqual(self.status(), ("confirmed", "opd_confirm1", None, None))

    def test_an_unconfirmed_brief_cannot_advance_the_topic(self) -> None:
        """G-4, structurally: intake -> scoping needs a confirmed brief. Not
        with no brief, not with one awaiting (overdue or not), not with a
        cancelled one; then yes once one is confirmed."""
        leave = "UPDATE queue_entries SET status = 'scoping', state_revision = state_revision + 1 WHERE topic_id = ?"
        refused = "leaves intake only with a confirmed intake brief"
        self.rejects(refused, leave, TOPIC)
        self.brief(TOPIC)
        self.rejects(refused, leave, TOPIC)
        self.x(UPDATE.format("overdue_since = ?"), T, TOPIC, 1)
        self.rejects(refused, leave, TOPIC)
        self.x(UPDATE.format("status = 'cancelled', closed_by = 'user', closed_at = ?, close_reason = 'duplicate ask'"), T, TOPIC, 1)
        self.rejects(refused, leave, TOPIC)
        self.brief(OTHER)
        self.confirm_brief(OTHER, "brief-1", 1, did="opd_otherbrf")
        self.rejects(refused, leave, TOPIC)  # another topic's confirmed brief does not count
        self.assertEqual(self.rows("SELECT status, state_revision FROM queue_entries WHERE topic_id = ?", TOPIC), [("awaiting_brief_confirmation", 0)])
        self.confirm_brief(TOPIC, "brief-2", 1)
        self.x(leave, TOPIC)
        self.assertEqual(self.rows("SELECT status FROM queue_entries WHERE topic_id = ?", TOPIC), [("scoping",)])

    def test_expiry_marks_overdue_and_never_advances(self) -> None:
        b1 = self.brief(TOPIC)
        self.decision("opd_confirm1", "brief_confirmation", ref="brief-1", rev=1, hsh=b1)
        mark_and_confirm = UPDATE.format("overdue_since = ?, status = 'confirmed', confirmed_by_decision_id = 'opd_confirm1'")
        refused = "overdue is marked once"
        self.rejects(refused, mark_and_confirm, T, TOPIC, 1)
        self.x(UPDATE.format("overdue_since = ?"), T, TOPIC, 1)
        self.assertEqual(self.status(), ("awaiting_confirmation", None, T, None))
        self.rejects(refused, UPDATE.format("overdue_since = ?"), LATER, TOPIC, 1)
        self.rejects(refused, UPDATE.format("overdue_since = NULL"), TOPIC, 1)
        self.confirm("opd_confirm1")  # waiting is not failure: an overdue brief can still be confirmed
        self.assertEqual(self.status(), ("confirmed", "opd_confirm1", T, None))
        b2 = self.brief(TOPIC, "brief-1", 2, parent=1)
        self.rejects(refused, UPDATE.format("overdue_since = ?"), LATER, TOPIC, 1)  # already marked once
        self.confirm_brief(OTHER)  # a confirmed brief never marked overdue: it is not awaiting anything
        self.rejects(refused, "UPDATE intake_briefs SET overdue_since = ? WHERE topic_id = ?", T, OTHER)
        self.assertEqual(self.status(2), ("awaiting_confirmation", None, None, None))
        self.assertTrue(b2)

    def test_cancellation_and_archival_are_explicit_and_final(self) -> None:
        b1 = self.brief(TOPIC)
        cancel = UPDATE.format("status = 'cancelled', closed_by = 'user', closed_at = ?, close_reason = 'superseded by a new topic'")
        self.rejects("CHECK constraint failed", UPDATE.format("status = 'cancelled'"), TOPIC, 1)  # no actor, time or reason
        self.rejects("CHECK constraint failed", UPDATE.format("status = 'cancelled', closed_at = ?, close_reason = 'x'"), T, TOPIC, 1)  # no actor
        self.x(cancel, T, TOPIC, 1)
        self.assertEqual(self.status(), ("cancelled", None, None, T))
        self.decision("opd_confirm1", "brief_confirmation", ref="brief-1", rev=1, hsh=b1)
        for case, sets in (("confirmed after cancellation", "status = 'confirmed', confirmed_by_decision_id = 'opd_confirm1'"),
                           ("reason rewritten", "close_reason = 'other'"), ("overdue marked", f"overdue_since = '{T}'")):
            with self.subTest(case=case):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.x(UPDATE.format(sets), TOPIC, 1)
                self.assertEqual(self.status(), ("cancelled", None, None, T))
        b = self.brief(TOPIC, "brief-2", 1)
        self.decision("opd_confirmb", "brief_confirmation", ref="brief-2", rev=1, hsh=b)
        archive = "UPDATE intake_briefs SET status = 'archived', closed_by = 'user', closed_at = ?, close_reason = 'topic retired' WHERE topic_id = ? AND brief_id = 'brief-2'"
        self.rejects("intake brief status moves", archive, T, TOPIC)  # archival is for a confirmed brief; an unconfirmed one is cancelled
        self.x("UPDATE intake_briefs SET status = 'confirmed', confirmed_by_decision_id = 'opd_confirmb' WHERE topic_id = ? AND brief_id = 'brief-2'", TOPIC)
        self.rejects("intake brief status moves", "UPDATE intake_briefs SET status = 'cancelled', closed_by = 'user', closed_at = ?, close_reason = 'x' WHERE topic_id = ? AND brief_id = 'brief-2'", T, TOPIC)
        self.x(archive, T, TOPIC)
        self.assertEqual(self.rows("SELECT status, confirmed_by_decision_id FROM intake_briefs WHERE brief_id = 'brief-2'"), [("archived", "opd_confirmb")])
        self.rejects_any(("never changes", "intake brief status moves"),  # both guards refuse; which reports first is trigger order
                         "UPDATE intake_briefs SET status = 'confirmed', closed_by = NULL, closed_at = NULL, close_reason = NULL WHERE topic_id = ? AND brief_id = 'brief-2'", TOPIC)

    def test_a_version_is_superseded_only_by_a_later_one_and_one_is_confirmed(self) -> None:
        b1 = self.brief(TOPIC)
        self.decision("opd_confirm1", "brief_confirmation", ref="brief-1", rev=1, hsh=b1)
        self.rejects("superseded only by a later version", UPDATE.format("status = 'superseded'"), TOPIC, 1)
        self.confirm("opd_confirm1")
        self.rejects("superseded only by a later version", UPDATE.format("status = 'superseded'"), TOPIC, 1)
        b2 = self.brief(TOPIC, "brief-1", 2, parent=1)
        self.decision("opd_confirm2", "brief_confirmation", ref="brief-1", rev=2, hsh=b2)
        self.rejects("UNIQUE constraint failed: intake_briefs.topic_id", UPDATE.format("status = 'confirmed', confirmed_by_decision_id = 'opd_confirm2'"), TOPIC, 2)
        self.x(UPDATE.format("status = 'superseded'"), TOPIC, 1)
        self.confirm("opd_confirm2", 2)
        self.assertEqual(self.rows("SELECT version, status, confirmed_by_decision_id FROM intake_briefs ORDER BY version"),
                         [(1, "superseded", "opd_confirm1"), (2, "confirmed", "opd_confirm2")])
        self.rejects_any(("never changes", "intake brief status moves"), UPDATE.format("status = 'confirmed'"), TOPIC, 1)

    def test_content_lineage_owner_and_deadline_are_immutable(self) -> None:
        self.brief(TOPIC)
        self.brief(TOPIC, "brief-1", 2, parent=1)
        stored = self.snapshot("intake_briefs")
        for column, value in (("document", '{}'), ("content_hash", h("9")), ("owner_operator_id", "someone"), ("review_deadline", LATER),
                              ("created_at", LATER), ("parent_version", None), ("brief_id", "brief-9"), ("version", 7), ("topic_id", OTHER)):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.x(UPDATE.format(f"{column} = ?"), value, TOPIC, 2)
        self.assertEqual(self.snapshot("intake_briefs"), stored)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.brief(TOPIC, "brief-1", 3, parent=3)
        self.assertIn("intake_brief_parent_is_earlier", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.brief(TOPIC, "brief-1", 4, parent=3)  # names a version that does not exist
        self.assertIn("FOREIGN KEY constraint failed", str(ctx.exception))
        self.rejects("never deleted", "DELETE FROM intake_briefs WHERE topic_id = ? AND version = 1", TOPIC)
        self.rejects("never deleted", "INSERT OR REPLACE INTO intake_briefs SELECT * FROM intake_briefs WHERE topic_id = ? AND version = 1", TOPIC)
        self.assertEqual(self.snapshot("intake_briefs"), stored)


if __name__ == "__main__":
    unittest.main()
