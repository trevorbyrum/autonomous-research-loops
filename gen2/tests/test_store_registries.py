"""The DDL of task 1d's tables: config bundles, the question registry,
qualification records, reservations and their draws, re-queues, amendment
impact records, and the signal queue's episode binding.

Trace: gen2/store/schema.sql "Engine configuration and registries (task 1d)";
INVARIANTS G-1, G-5, G-10, G-12, RG-9, C-11, C-12, D-1, D-4, D-5, D-11, L-6.

Oracles: hand-written expectations; each refusal is one defect beside the
statement without it, which the same guard admits; read-backs are raw SQL.
The router refuses most of these first (test_router_registries.py,
test_router_amendments.py, test_router_scheduling.py); here the store refuses
them on its own, as the second layer.
"""
from __future__ import annotations

import json
import sqlite3

from gen2.tests.store_fixtures import BUNDLE, OTHER, QUESTION, TOPIC, T, StoreTestCase, facet, h, obligation

BUNDLE_INSERT = "INSERT INTO config_bundles (bundle_hash, version, document, status, activated_at) VALUES (?, ?, ?, ?, ?)"
QUESTION_INSERT = "INSERT INTO questions (question_id, version, content_hash, document, registered_by_bundle_hash, registered_at) VALUES (?, ?, ?, ?, ?, ?)"
QUAL_INSERT = "INSERT INTO qualifications (qualification_id, provider, decision_class, spec_hash, evaluation_ref, granted_by, granted_at) VALUES (?, ?, ?, ?, 'eval-1', 'user', ?)"
RESERVE = "INSERT INTO reservations (reservation_id, topic_id, purpose, contract_revision, units, min_band, bundle_hash, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
DRAW = "INSERT INTO reservation_draws (invocation_id, reservation_id, facet_id, drawn_at) VALUES (?, ?, ?, ?)"
RETRY = "INSERT INTO retries (invocation_id, topic_id, attempt, requested_by, reason, requested_at, retry_invocation_id) VALUES (?, ?, ?, 'operator', 'again', ?, ?)"
IMPACT = "INSERT INTO amendment_impacts (decision_id, topic_id, kind, classification, document, recorded_at) VALUES (?, ?, ?, ?, ?, ?)"


def question(qid: str, version: int = 1, ch: str = "8") -> dict:
    return {"question_id": qid, "version": version, "text": f"{qid} v{version}", "content_hash": h(ch)}


def bundle(version: int, questions=(QUESTION,)) -> dict:
    return {**BUNDLE, "version": version, "questions": list(questions)}


class ConfigBundleTest(StoreTestCase):
    """RG-9, G-10: one active bundle, each newer than every recorded one; a
    bundle never changes, a superseded one is never reactivated; an
    invocation pins a recorded bundle."""

    def supersede_first(self) -> None:
        self.x("UPDATE config_bundles SET status = 'superseded' WHERE bundle_hash = ?", h("c"))

    def test_a_bundle_row_is_its_document(self) -> None:
        self.supersede_first()
        for name, doc in (("another version", bundle(3)), ("another document version", {**bundle(2), "bundle_version": "config-bundle/2"})):
            with self.subTest(name):
                self.rejects("CHECK constraint failed", BUNDLE_INSERT, h("d"), 2, json.dumps(doc), "active", T)
        self.x(BUNDLE_INSERT, h("d"), 2, json.dumps(bundle(2)), "active", T)

    def test_a_bundle_is_recorded_active_newest_and_alone(self) -> None:
        self.rejects("UNIQUE constraint failed: config_bundles.status", BUNDLE_INSERT, h("d"), 2, json.dumps(bundle(2)), "active", T)  # two active
        self.supersede_first()
        self.rejects("recorded active, with a version above", BUNDLE_INSERT, h("d"), 2, json.dumps(bundle(2)), "superseded", T)
        self.rejects("recorded active, with a version above", BUNDLE_INSERT, h("d"), 1, json.dumps(bundle(1, ())), "active", T)
        self.x(BUNDLE_INSERT, h("d"), 2, json.dumps(bundle(2)), "active", T)
        self.assertEqual(self.rows("SELECT bundle_hash, status FROM config_bundles ORDER BY version"), [(h("c"), "superseded"), (h("d"), "active")])

    def test_a_bundle_never_changes_and_is_never_reactivated(self) -> None:
        self.supersede_first()  # active -> superseded is the one change
        self.x(BUNDLE_INSERT, h("d"), 2, json.dumps(bundle(2, ())), "active", T)  # nothing pins bundle 2: only the guard refuses
        for name, sql in (("its document", "UPDATE config_bundles SET document = ? WHERE version = 2"), ("its version", "UPDATE config_bundles SET version = 9 WHERE version = ?"),
                          ("its hash", "UPDATE config_bundles SET bundle_hash = 'sha256:" + "e" * 64 + "' WHERE version = ?"),
                          ("its activation time", "UPDATE config_bundles SET activated_at = 'x' WHERE version = ?")):
            with self.subTest(name):
                self.rejects("a config bundle never changes", sql, json.dumps(bundle(2, (QUESTION,))) if "document" in sql else 2)
        self.x("UPDATE config_bundles SET status = 'superseded' WHERE version = 2")
        self.rejects("a superseded one is never reactivated", "UPDATE config_bundles SET status = 'active' WHERE version = 2")
        self.assertEqual(self.rows("SELECT version, status FROM config_bundles ORDER BY version"), [(1, "superseded"), (2, "superseded")])

    def test_an_invocation_pins_a_recorded_bundle(self) -> None:
        self.approve_contract(TOPIC, 1)
        self.lease("lease_aaaaaaaa", 1)
        self.rejects("FOREIGN KEY constraint failed", *self.raw_invocation(invocation_id="inv_pppppppp", config_bundle_hash=h("e")))
        self.invocation("inv_pppppppp")
        self.assertEqual(self.rows("SELECT config_bundle_hash FROM invocations"), [(h("c"),)])


class QuestionRegistryTest(StoreTestCase):
    """D-1, D-4: a question version has one content forever and is the entry
    of the bundle that registers it; a DecisionSpec pins a registered version
    under exactly its hash."""

    def carrying(self, *questions: dict) -> str:
        """Bundle 2, active, carrying these questions (and Q-screen)."""
        self.x("UPDATE config_bundles SET status = 'superseded' WHERE bundle_hash = ?", h("c"))
        self.x(BUNDLE_INSERT, h("d"), 2, json.dumps(bundle(2, (QUESTION, *questions))), "active", T)
        return h("d")

    def test_a_question_is_the_entry_of_its_bundle(self) -> None:
        q2 = question("Q-method")
        registered_by = self.carrying(q2)
        self.rejects("recorded as the entry of the bundle", QUESTION_INSERT, "Q-method", 1, h("8"), json.dumps(q2), h("c"), T)  # bundle 1 does not carry it
        self.rejects("recorded as the entry of the bundle", QUESTION_INSERT, "Q-other", 1, h("7"), json.dumps(question("Q-other", ch="7")), registered_by, T)
        for name, row in (("another version", ("Q-method", 2, h("8"))), ("another id", ("Q-other", 1, h("8"))), ("another hash", ("Q-method", 1, h("6")))):
            with self.subTest(name):  # the bundle carries the document: only the row's disagreement with it refuses
                self.rejects("CHECK constraint failed", QUESTION_INSERT, *row, json.dumps(q2), registered_by, T)
        self.x(QUESTION_INSERT, "Q-method", 1, h("8"), json.dumps(q2), registered_by, T)

    def test_a_bundle_carries_a_registered_version_only_under_its_content(self) -> None:
        self.x("UPDATE config_bundles SET status = 'superseded' WHERE bundle_hash = ?", h("c"))
        reworded = {**QUESTION, "text": "reworded", "content_hash": h("7")}
        self.rejects("carries a registered question version only under its registered content", BUNDLE_INSERT, h("d"), 2, json.dumps(bundle(2, (reworded,))), "active", T)
        self.x(BUNDLE_INSERT, h("d"), 2, json.dumps(bundle(2, (QUESTION, {**reworded, "version": 2}))), "active", T)  # the same, and the rewording as version 2

    def test_a_version_has_one_content_forever(self) -> None:
        """The primary key, isolated: the bundle guard above is dropped so a
        bundle can carry the rewording (the store's second layer behind it)."""
        reworded = {**QUESTION, "text": "reworded", "content_hash": h("7")}
        self.x("DROP TRIGGER config_bundles_questions_unaltered")
        registered_by = self.carrying(reworded)  # a bundle carrying the reworded entry under the recorded version
        self.rejects("UNIQUE constraint failed: questions.question_id, questions.version", QUESTION_INSERT, "Q-screen", 1, h("7"), json.dumps(reworded), registered_by, T)
        for name, sql in (("its text", "UPDATE questions SET document = json_set(document, '$.text', 'reworded')"),
                          ("its hash", "UPDATE questions SET content_hash = 'sha256:" + "7" * 64 + "'")):
            with self.subTest(name):
                self.rejects("a question version is immutable", sql)
        self.assertEqual(self.rows("SELECT question_id, version, content_hash FROM questions"), [("Q-screen", 1, h("9"))])

    def test_a_spec_pins_a_registered_question_under_its_hash(self) -> None:
        for name, pin in (("an unknown question", {"question_id": "Q-none", "version": 1, "content_hash": h("9")}),
                          ("another version", {"question_id": "Q-screen", "version": 2, "content_hash": h("9")}),
                          ("another hash (an altered question)", {"question_id": "Q-screen", "version": 1, "content_hash": h("7")}),
                          ("no question", None)):
            with self.subTest(name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.spec("dspec_pinned01", document_overrides={"question": pin} if pin else {}, drop=() if pin else ("question",))
                self.assertIn("pins a question version recorded in the registry", str(ctx.exception))
        self.spec("dspec_pinned01")
        self.assertEqual(self.rows("SELECT json_extract(document, '$.question.question_id') FROM decision_specs"), [("Q-screen",)])


class QualificationTest(StoreTestCase):
    """D-4, D-5, D-11: a record qualifies exactly its spec's provider and
    class, is created live and revoked once; qualified authority rests on a
    live record of exactly the receipt's provider, class and spec."""

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")
        self.jev = self.spec()
        self.prefilter = self.spec("dspec_prefil01", cls="relevance_prefilter")

    def test_a_record_is_created_live_for_its_specs_provider_and_class(self) -> None:
        for name, args in (("another provider", ("qual_00000001", "llm_fallback", "screening", self.jev, T)),
                           ("another class", ("qual_00000001", "jev", "relevance_prefilter", self.jev, T))):
            with self.subTest(name):
                self.rejects("recorded live, for exactly its spec", QUAL_INSERT, *args)
        with self.assertRaises(sqlite3.IntegrityError):  # an unknown spec: the trigger and the foreign key both refuse it
            self.x(QUAL_INSERT, "qual_00000001", "jev", "screening", h("e"), T)
        self.rejects("recorded live, for exactly its spec",
                     "INSERT INTO qualifications (qualification_id, provider, decision_class, spec_hash, evaluation_ref, granted_by, granted_at, revoked_by, revoked_at, revoke_reason) "
                     "VALUES ('qual_00000001', 'jev', 'screening', ?, 'eval-1', 'user', ?, 'user', ?, 'born revoked')", self.jev, T, T)
        self.x(QUAL_INSERT, "qual_00000001", "jev", "screening", self.jev, T)

    def test_revocation_is_recorded_once_and_is_final(self) -> None:
        self.x(QUAL_INSERT, "qual_00000001", "jev", "screening", self.jev, T)
        self.rejects("CHECK constraint failed", "UPDATE qualifications SET revoked_at = ? WHERE qualification_id = 'qual_00000001'", T)  # revocation facts go together
        for name, sql in (("its spec", "UPDATE qualifications SET spec_hash = ? WHERE qualification_id = 'qual_00000001'"),
                          ("its evaluation", "UPDATE qualifications SET evaluation_ref = ? WHERE qualification_id = 'qual_00000001'")):
            with self.subTest(name):
                self.rejects("changes only by its revocation", sql, self.prefilter if "spec" in sql else "eval-2")
        self.x("UPDATE qualifications SET revoked_by = 'user', revoked_at = ?, revoke_reason = 'drift' WHERE qualification_id = 'qual_00000001'", T)
        self.rejects("changes only by its revocation", "UPDATE qualifications SET revoke_reason = 'other' WHERE qualification_id = 'qual_00000001'")
        self.assertEqual(self.rows("SELECT revoke_reason FROM qualifications"), [("drift",)])

    def test_qualified_authority_rests_on_a_live_record_of_exactly_its_spec(self) -> None:
        self.x(QUAL_INSERT, "qual_screen01", "jev", "screening", self.jev, T)
        self.x(QUAL_INSERT, "qual_prefil01", "jev", "relevance_prefilter", self.prefilter, T)
        self.x(QUAL_INSERT, "qual_screen02", "jev", "screening", self.spec("dspec_screen02"), T)  # the same provider and class, another spec
        self.x(QUAL_INSERT, "qual_revoked1", "jev", "screening", self.jev, T)
        self.x("UPDATE qualifications SET revoked_by = 'user', revoked_at = ?, revoke_reason = 'drift' WHERE qualification_id = 'qual_revoked1'", T)
        qualified = dict(authority="qualified", action="commit_reversible_action", commit_op="op_00000001", live_qualification=False)
        for n, (name, ref) in enumerate((("an unrecorded reference", "qual_nosuchone"), ("a revoked record", "qual_revoked1"),
                                         ("another spec's record", "qual_screen02"), ("another class's record", "qual_prefil01")), start=1):
            with self.subTest(name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt(f"dec_0000000{n}", "inv_pppppppp", self.jev, qualification=ref, **qualified)
                self.assertIn("qualified authority needs a live qualification", str(ctx.exception))
        self.decision_receipt("dec_00000009", "inv_pppppppp", self.jev, qualification="qual_screen01", **qualified)
        self.decision_receipt("dec_00000008", "inv_pppppppp", self.jev, authority="advisory", qualification="qual_nosuchone", action="attach_proposal",
                              proposal="prop-1", live_qualification=False)  # below qualified authority the reference authorizes nothing, and binds nothing
        self.assertEqual(self.rows("SELECT decision_receipt_id, authority_level FROM decision_receipts ORDER BY decision_receipt_id"),
                         [("dec_00000008", "advisory"), ("dec_00000009", "qualified")])


class ReservationTest(StoreTestCase):
    """G-5, G-10: a reservation is opened under its topic's approved revision,
    sized as its bundle declares, one open per purpose, closed once; a draw is
    within it, revision-bound, and for auto-promotion inside a facet rated at
    or above the threshold."""

    def setUp(self) -> None:
        super().setUp()
        self.rev = self.approved_with_obligation(TOPIC)  # critical facet F-1
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_cccccccc", 2, scope="checkpoint")
        self.invocation("inv_cccccccc", kind="checkpoint", lease="lease_cccccccc")
        self.lease("lease_dddddddd", 3, scope="discovery")
        self.invocation("inv_dddddddd", kind="discovery", lease="lease_dddddddd")

    def test_a_reservation_is_opened_under_the_approved_revision_as_its_bundle_sizes_it(self) -> None:
        guard = "opened under its topic's approved contract revision"
        for name, args in (("a draft revision", ("rsv_00000001", OTHER, "protected_exploration", 1, 2, None, h("c"), T)),
                           ("another size", ("rsv_00000001", TOPIC, "protected_exploration", self.rev, 3, None, h("c"), T)),
                           ("another threshold", ("rsv_00000001", TOPIC, "auto_promotion", self.rev, 2, "important", h("c"), T))):
            with self.subTest(name):
                self.rejects(guard, RESERVE, *args)
        self.rejects(guard, "INSERT INTO reservations (reservation_id, topic_id, purpose, contract_revision, units, bundle_hash, opened_at, closed_at, close_reason) "
                            "VALUES ('rsv_00000001', ?, 'protected_exploration', ?, 2, ?, ?, ?, 'born closed')", TOPIC, self.rev, h("c"), T, T)
        self.x(RESERVE, "rsv_00000001", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)
        self.x(RESERVE, "rsv_00000002", TOPIC, "auto_promotion", self.rev, 2, "critical", h("c"), T)

    def test_a_threshold_is_auto_promotions_alone(self) -> None:
        """The CHECK, isolated: a bundle (raw, which the schema would refuse)
        declaring a threshold for exploration sizes a reservation the insert
        trigger admits; the CHECK refuses it."""
        self.x("UPDATE config_bundles SET status = 'superseded' WHERE bundle_hash = ?", h("c"))
        odd = {**BUNDLE, "version": 2, "policy": {"router": {"reservations": {"protected_exploration": {"units": 2, "min_band": "critical"},
                                                                             "auto_promotion": {"units": 2}}}}}
        self.x(BUNDLE_INSERT, h("d"), 2, json.dumps(odd), "active", T)
        self.rejects("CHECK constraint failed", RESERVE, "rsv_00000001", TOPIC, "protected_exploration", self.rev, 2, "critical", h("d"), T)
        self.rejects("CHECK constraint failed", RESERVE, "rsv_00000002", TOPIC, "auto_promotion", self.rev, 2, None, h("d"), T)
        self.assertEqual(self.rows("SELECT count(*) FROM reservations"), [(0,)])

    def test_one_open_reservation_per_purpose_closed_once(self) -> None:
        self.x(RESERVE, "rsv_00000001", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)
        self.rejects("UNIQUE constraint failed", RESERVE, "rsv_00000002", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)
        self.rejects("changes only by closing", "UPDATE reservations SET units = 1 WHERE reservation_id = 'rsv_00000001'")
        self.rejects("CHECK constraint failed", "UPDATE reservations SET closed_at = ? WHERE reservation_id = 'rsv_00000001'", T)  # closed without a reason
        self.x("UPDATE reservations SET closed_at = ?, close_reason = 'exhausted' WHERE reservation_id = 'rsv_00000001'", T)
        self.rejects("changes only by closing", "UPDATE reservations SET close_reason = 'other' WHERE reservation_id = 'rsv_00000001'")
        self.x(RESERVE, "rsv_00000002", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)

    def test_a_draw_is_within_its_reservation_and_bound_to_its_revision(self) -> None:
        guard = "a draw is within its open reservation"
        self.x(RESERVE, "rsv_00000001", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)
        self.rejects(guard, DRAW, "inv_pppppppp", "rsv_00000001", "F-1", T)  # a facet is auto-promotion's
        self.x(DRAW, "inv_pppppppp", "rsv_00000001", None, T)
        self.x(DRAW, "inv_cccccccc", "rsv_00000001", None, T)
        self.rejects(guard, DRAW, "inv_dddddddd", "rsv_00000001", None, T)  # its two units are drawn
        self.assertEqual(self.rows("SELECT invocation_id FROM reservation_draws ORDER BY rowid"), [("inv_pppppppp",), ("inv_cccccccc",)])

    def test_each_binding_of_a_draw_refuses_alone(self) -> None:
        guard = "a draw is within its open reservation"
        self.x(RESERVE, "rsv_00000001", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)
        self.to_running("inv_pppppppp")
        self.invocation("inv_deleg001", kind="delegate", lease=None, parent="inv_pppppppp")
        self.rejects(guard, DRAW, "inv_deleg001", "rsv_00000001", None, T)  # a delegate draws under its parent's
        self.assertEqual(self.approved_with_obligation(OTHER), self.rev)  # the same revision number: only the topic differs
        self.lease("lease_other001", 1, tid=OTHER)
        self.invocation("inv_other001", tid=OTHER, lease="lease_other001")
        self.rejects(guard, DRAW, "inv_other001", "rsv_00000001", None, T)  # another topic's work
        self.x("UPDATE reservations SET closed_at = ?, close_reason = 'test' WHERE reservation_id = 'rsv_00000001'", T)
        self.rejects(guard, DRAW, "inv_cccccccc", "rsv_00000001", None, T)  # closed
        self.x(RESERVE, "rsv_00000002", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)
        self.x(DRAW, "inv_cccccccc", "rsv_00000002", None, T)

    def test_a_draw_under_a_superseded_or_another_revision_is_refused(self) -> None:
        guard = "a draw is within its open reservation"
        self.x(RESERVE, "rsv_00000001", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)
        newer = self.approved_with_obligation(TOPIC)  # the reservation's revision is superseded, the reservation left open (the router closes it)
        self.rejects(guard, DRAW, "inv_pppppppp", "rsv_00000001", None, T)
        self.x("UPDATE reservations SET closed_at = ?, close_reason = 'superseded' WHERE reservation_id = 'rsv_00000001'", T)
        self.x(RESERVE, "rsv_00000002", TOPIC, "protected_exploration", newer, 2, None, h("c"), T)
        self.rejects(guard, DRAW, "inv_pppppppp", "rsv_00000002", None, T)  # admitted under the older revision
        self.lease("lease_eeeeeeee", 4, scope="verification")
        self.invocation("inv_eeeeeeee", kind="verification", lease="lease_eeeeeeee")  # admitted under the newer one
        self.x(DRAW, "inv_eeeeeeee", "rsv_00000002", None, T)

    def test_an_auto_promotion_draw_is_inside_a_facet_rated_at_the_threshold(self) -> None:
        guard = "a draw is within its open reservation"
        self.x(RESERVE, "rsv_00000001", TOPIC, "auto_promotion", self.rev, 2, "critical", h("c"), T)
        self.rejects(guard, DRAW, "inv_pppppppp", "rsv_00000001", None, T)  # no facet
        self.rejects(guard, DRAW, "inv_pppppppp", "rsv_00000001", "F-9", T)  # no such facet
        self.x(DRAW, "inv_pppppppp", "rsv_00000001", "F-1", T)

    def test_a_facet_below_the_threshold_is_refused(self) -> None:
        guard = "a draw is within its open reservation"
        n = self.rows("SELECT coalesce(max(revision), 0) + 1 FROM contract_revisions WHERE topic_id = ?", OTHER)[0][0]
        did = "opd_rateot01"
        important = dict(band="important", score=5, decision=did)
        entries = dict(facets=(facet("F-2", **important),), obligations=(obligation("O-2", ("F-2",), **important),))
        self.rate(did, OTHER, **entries)
        self.contract_with_rows(OTHER, n + 1, **entries, content_hash=self.chash(OTHER, n + 1))
        self.approve_contract(OTHER, n + 1)
        self.lease("lease_other001", 1, tid=OTHER)
        self.invocation("inv_other001", tid=OTHER, lease="lease_other001")
        self.x(RESERVE, "rsv_00000009", OTHER, "auto_promotion", n + 1, 2, "critical", h("c"), T)
        self.rejects(guard, DRAW, "inv_other001", "rsv_00000009", "F-2", T)
        self.x("UPDATE reservations SET closed_at = ?, close_reason = 'test' WHERE reservation_id = 'rsv_00000009'", T)
        self.x("UPDATE config_bundles SET status = 'superseded' WHERE bundle_hash = ?", h("c"))
        lower = {**BUNDLE, "version": 2, "policy": {"router": {"reservations": {"auto_promotion": {"units": 2, "min_band": "important"}}}}}
        self.x(BUNDLE_INSERT, h("d"), 2, json.dumps(lower), "active", T)
        self.x(RESERVE, "rsv_00000010", OTHER, "auto_promotion", n + 1, 2, "important", h("d"), T)
        self.x(DRAW, "inv_other001", "rsv_00000010", "F-2", T)

    def test_a_draw_never_changes(self) -> None:
        self.x(RESERVE, "rsv_00000001", TOPIC, "protected_exploration", self.rev, 2, None, h("c"), T)
        self.x(DRAW, "inv_pppppppp", "rsv_00000001", None, T)
        self.rejects("a reservation draw is a record", "UPDATE reservation_draws SET drawn_at = 'x'")


class RetryTest(StoreTestCase):
    """L-6: a re-queue is of a non-delegate invocation of its topic that ended
    failed or cancelled, counting one attempt more than it; it is claimed
    once, by an invocation of the same topic and kind."""

    def setUp(self) -> None:
        super().setUp()
        self.approve_contract(TOPIC, 1)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.invocation("inv_deleg001", kind="delegate", lease=None, parent="inv_pppppppp")
        self.x("UPDATE invocations SET state = 'cancelled', cancel_requested_at = ?, cancel_requested_by = 'operator', descendants_confirmed_at = ? WHERE invocation_id = 'inv_deleg001'", T, T)
        self.x("UPDATE invocations SET state = 'failed', failure_class = 'killed' WHERE invocation_id = 'inv_pppppppp'")
        self.x("UPDATE leases SET released_at = ?, release_reason = 'failed' WHERE lease_id = 'lease_aaaaaaaa'", T)

    def next_attempt(self, lid: str, gen: int, iid: str, kind: str = "research_pass", scope: str = "research") -> None:
        self.lease(lid, gen, scope=scope)
        self.invocation(iid, kind=kind, lease=lid)

    def test_a_requeue_is_of_ended_non_delegate_work_one_attempt_on(self) -> None:
        guard = "a re-queue is of a non-delegate invocation"
        self.rejects(guard, RETRY, "inv_deleg001", TOPIC, 2, T, None)
        self.rejects(guard, RETRY, "inv_pppppppp", OTHER, 2, T, None)
        self.rejects(guard, RETRY, "inv_pppppppp", TOPIC, 3, T, None)
        self.rejects(guard, RETRY, "inv_pppppppp", TOPIC, 2, T, "inv_pppppppp")  # claimed at insert
        self.next_attempt("lease_bbbbbbbb", 2, "inv_qqqqqqqq")
        self.rejects(guard, RETRY, "inv_qqqqqqqq", TOPIC, 2, T, None)  # admitted, not ended
        self.x(RETRY, "inv_pppppppp", TOPIC, 2, T, None)

    def test_a_retry_counts_along_its_chain(self) -> None:
        self.x(RETRY, "inv_pppppppp", TOPIC, 2, T, None)
        self.next_attempt("lease_bbbbbbbb", 2, "inv_qqqqqqqq")
        self.x("UPDATE retries SET retry_invocation_id = 'inv_qqqqqqqq' WHERE invocation_id = 'inv_pppppppp'")
        self.x("UPDATE invocations SET state = 'cancelled', cancel_requested_at = ?, cancel_requested_by = 'supervisor', descendants_confirmed_at = ? WHERE invocation_id = 'inv_qqqqqqqq'", T, T)
        self.rejects("a re-queue is of a non-delegate invocation", RETRY, "inv_qqqqqqqq", TOPIC, 2, T, None)
        self.x(RETRY, "inv_qqqqqqqq", TOPIC, 3, T, None)

    def test_a_requeue_is_claimed_once_by_the_same_topic_and_kind(self) -> None:
        guard = "claimed once, by an invocation of the same topic and kind"
        self.x(RETRY, "inv_pppppppp", TOPIC, 2, T, None)
        self.next_attempt("lease_cccccccc", 2, "inv_cccccccc", "checkpoint", "checkpoint")
        self.rejects(guard, "UPDATE retries SET retry_invocation_id = 'inv_cccccccc' WHERE invocation_id = 'inv_pppppppp'")  # another kind
        self.next_attempt("lease_bbbbbbbb", 3, "inv_qqqqqqqq")
        self.rejects(guard, "UPDATE retries SET retry_invocation_id = 'inv_qqqqqqqq', reason = 'other' WHERE invocation_id = 'inv_pppppppp'")  # a claim rewriting its reason
        self.x("UPDATE retries SET retry_invocation_id = 'inv_qqqqqqqq' WHERE invocation_id = 'inv_pppppppp'")
        self.rejects(guard, "UPDATE retries SET retry_invocation_id = NULL WHERE invocation_id = 'inv_pppppppp'")
        self.x("UPDATE leases SET released_at = ?, release_reason = 'test' WHERE lease_id = 'lease_bbbbbbbb'", T)
        self.next_attempt("lease_dddddddd", 4, "inv_rrrrrrrr")
        self.rejects(guard, "UPDATE retries SET retry_invocation_id = 'inv_rrrrrrrr' WHERE invocation_id = 'inv_pppppppp'")  # claimed again, by valid work
        self.assertEqual(self.rows("SELECT retry_invocation_id FROM retries"), [("inv_qqqqqqqq",)])

    def test_a_retry_of_another_topic_is_refused(self) -> None:
        self.x(RETRY, "inv_pppppppp", TOPIC, 2, T, None)
        self.approve_contract(OTHER, 1)
        self.lease("lease_other001", 1, tid=OTHER)
        self.invocation("inv_other001", tid=OTHER, lease="lease_other001")
        self.rejects("claimed once, by an invocation of the same topic and kind", "UPDATE retries SET retry_invocation_id = 'inv_other001'")


class AmendmentImpactTest(StoreTestCase):
    """G-1: an impact record is of an approved contract or brief approval of
    its topic, its document names its row, and it never changes."""

    def setUp(self) -> None:
        super().setUp()
        self.confirmation = self.confirm_brief(TOPIC)[3]
        self.approval = self.approve_contract(TOPIC, 1)

    @staticmethod
    def doc(did: str, kind: str, classification: str, tid: str = TOPIC) -> str:
        return json.dumps({"decision_id": did, "topic_id": tid, "kind": kind, "classification": classification})

    def test_an_impact_is_of_an_approval_of_its_topic(self) -> None:
        guard = "recorded for an approved contract or brief approval of its topic"
        rejected = self.decision("opd_rejected1", "amendment_approval", disposition="rejected", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        scope = self.decision("opd_scope0001", "scope_approval", ref="scope-1", rev=1, hsh=h("5"))
        for name, args in (("a rejected decision", (rejected, TOPIC, "contract", "compatible", self.doc(rejected, "contract", "compatible"))),
                           ("another kind of decision", (scope, TOPIC, "contract", "compatible", self.doc(scope, "contract", "compatible"))),
                           ("a brief record of a contract approval", (self.approval, TOPIC, "brief", "lineage_only", self.doc(self.approval, "brief", "lineage_only"))),
                           ("a contract record of a brief confirmation", (self.confirmation, TOPIC, "contract", "compatible", self.doc(self.confirmation, "contract", "compatible"))),
                           ("another topic", (self.approval, OTHER, "contract", "compatible", self.doc(self.approval, "contract", "compatible", OTHER)))):
            with self.subTest(name):
                self.rejects(guard, IMPACT, *args, T)
        self.x(IMPACT, self.approval, TOPIC, "contract", "compatible", self.doc(self.approval, "contract", "compatible"), T)
        self.x(IMPACT, self.confirmation, TOPIC, "brief", "content_changed", self.doc(self.confirmation, "brief", "content_changed"), T)

    def test_an_impact_record_names_its_row_and_never_changes(self) -> None:
        self.rejects("CHECK constraint failed", IMPACT, self.approval, TOPIC, "contract", "lineage_only", self.doc(self.approval, "contract", "lineage_only"), T)
        self.rejects("CHECK constraint failed", IMPACT, self.approval, TOPIC, "contract", "compatible", self.doc(self.approval, "contract", "reframed"), T)
        self.x(IMPACT, self.approval, TOPIC, "contract", "compatible", self.doc(self.approval, "contract", "compatible"), T)
        self.rejects("an amendment impact record is immutable", "UPDATE amendment_impacts SET recorded_at = 'x'")


class SignalQueueEpisodeTest(StoreTestCase):
    """G-12: a trigger joins only a review episode of its own topic."""

    def test_a_trigger_joins_only_its_topics_episode(self) -> None:
        for tid, eid in ((TOPIC, "rev_t1000001"), (OTHER, "rev_t2000001")):
            self.x("INSERT INTO review_episodes (episode_id, topic_id, kind, opened_at) VALUES (?, ?, 'method_fit', ?)", eid, tid, T)
        self.x("INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, 'persistent_contradiction', 'deterministic', 'c', ?)",
               h("1"), TOPIC, T)
        self.rejects("joins only a review episode of its own topic", "UPDATE review_triggers SET episode_id = 'rev_t2000001'")
        self.x("UPDATE review_triggers SET episode_id = 'rev_t1000001'")
        self.assertEqual(self.rows("SELECT episode_id FROM review_triggers"), [("rev_t1000001",)])
