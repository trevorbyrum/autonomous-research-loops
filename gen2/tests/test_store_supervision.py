"""DDL for the supervisor's ends of an invocation (task 1c).

Trace: BOUNDARIES.md Station supervisor (structural telemetry; never trust
agent self-reported completion; never treat outcome_unknown as anything
without reconciliation); INVARIANTS L-4, L-5, L-7, L-9, H-3, RG-3; design
review §6 ("ambiguous outcomes create a visible diagnostic/reconciliation
state with an owner and deadline").

What these show, each negative beside the same write minus its one defect
accepted: a failure's structural class is from a closed list and exists only
on a failed row; an end's evidence names a recorded artifact and exists only
on a failed or cancelled row; the supervisor may request a cancellation; the
cancellation request, descendant confirmation and failure record are
write-once; a reconciliation record clears exactly the router hold of its
own episode. Oracle: expected refusals written by hand from the rules above;
read-backs are raw SQL.

What they cannot show: that the router writes these columns at the right
moment, or that the evidence is true (test_router_lifecycle.py and the
supervisor suites).
"""
from __future__ import annotations

from gen2.tests.store_fixtures import TOPIC, OTHER, StoreTestCase, T, h

EVIDENCE = h("e")


class SupervisionTestCase(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        for tid in (TOPIC, OTHER):
            self.approve_contract(tid, 1)
        self.lease("lease_aaaaaaaa", 1)
        self.lease("lease_oooooooo", 1, tid=OTHER)
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", EVIDENCE, T)
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")

    def value(self, sql: str, *params):
        return self.rows(sql, *params)[0][0]


class FailureRecordTest(SupervisionTestCase):
    def test_a_failure_class_is_one_of_the_structural_findings(self) -> None:
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'failed', failure_class = 'agent_said_so', end_evidence_ref = ? WHERE invocation_id = 'inv_pppppppp'", EVIDENCE)
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = 'inv_pppppppp'"), "running")
        self.x("UPDATE invocations SET state = 'failed', failure_class = 'empty_output', end_evidence_ref = ? WHERE invocation_id = 'inv_pppppppp'", EVIDENCE)
        self.assertEqual(self.rows("SELECT state, failure_class, end_evidence_ref FROM invocations WHERE invocation_id = 'inv_pppppppp'"),
                         [("failed", "empty_output", EVIDENCE)])

    def test_every_listed_class_is_accepted(self) -> None:
        classes = ("spawn_failed", "never_started", "exit_nonzero", "killed", "timeout", "empty_output", "output_refused",
                   "output_digest_mismatch", "result_rejected", "no_exit_record")
        for n, cls in enumerate(classes):
            with self.subTest(cls):
                iid = f"inv_fail{n:04d}"
                self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE topic_id = ? AND scope = 'research' AND released_at IS NULL", T, TOPIC)
                self.lease(f"lease_fail{n:04d}", 10 + n)
                self.invocation(iid, lease=f"lease_fail{n:04d}")
                self.to_launching(iid)
                self.x("UPDATE invocations SET state = 'failed', failure_class = ? WHERE invocation_id = ?", cls, iid)
                self.assertEqual(self.value("SELECT failure_class FROM invocations WHERE invocation_id = ?", iid), cls)

    def test_a_failure_class_exists_only_on_a_failed_row(self) -> None:
        self.rejects("CHECK constraint failed", "UPDATE invocations SET failure_class = 'timeout' WHERE invocation_id = 'inv_pppppppp'")
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ?, failure_class = 'timeout' "
                                                "WHERE invocation_id = 'inv_pppppppp'", h("d"), T)
        self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'", h("d"), T)

    def test_end_evidence_exists_only_on_a_failed_or_cancelled_row(self) -> None:
        self.rejects("CHECK constraint failed", "UPDATE invocations SET end_evidence_ref = ? WHERE invocation_id = 'inv_pppppppp'", EVIDENCE)
        self.x("UPDATE invocations SET state = 'cancelled', cancel_requested_at = ?, cancel_requested_by = 'operator', descendants_confirmed_at = ?, end_evidence_ref = ? "
               "WHERE invocation_id = 'inv_pppppppp'", T, T, EVIDENCE)
        self.assertEqual(self.value("SELECT end_evidence_ref FROM invocations WHERE invocation_id = 'inv_pppppppp'"), EVIDENCE)

    def test_end_evidence_is_a_recorded_artifact(self) -> None:
        self.rejects("FOREIGN KEY constraint failed", "UPDATE invocations SET state = 'failed', failure_class = 'timeout', end_evidence_ref = ? WHERE invocation_id = 'inv_pppppppp'", h("9"))
        self.x("UPDATE invocations SET state = 'failed', failure_class = 'timeout', end_evidence_ref = ? WHERE invocation_id = 'inv_pppppppp'", EVIDENCE)

    def test_the_failure_record_is_write_once(self) -> None:
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 11, 'application/json', ?)", h("f"), T)
        self.x("UPDATE invocations SET state = 'failed', failure_class = 'timeout', end_evidence_ref = ? WHERE invocation_id = 'inv_pppppppp'", EVIDENCE)
        before = self.snapshot("invocations")
        self.rejects("write-once", "UPDATE invocations SET failure_class = 'killed' WHERE invocation_id = 'inv_pppppppp'")
        self.rejects("write-once", "UPDATE invocations SET end_evidence_ref = ? WHERE invocation_id = 'inv_pppppppp'", h("f"))
        self.assertEqual(self.snapshot("invocations"), before)
        self.x("UPDATE invocations SET failure_class = 'timeout', end_evidence_ref = ? WHERE invocation_id = 'inv_pppppppp'", EVIDENCE)  # the same values: no change


class CancellationRecordTest(SupervisionTestCase):
    def test_the_supervisor_may_request_a_cancellation(self) -> None:
        self.rejects("CHECK constraint failed", "UPDATE invocations SET cancel_requested_at = ?, cancel_requested_by = 'agent' WHERE invocation_id = 'inv_pppppppp'", T)
        for requester in ("router", "operator", "supervisor"):
            with self.subTest(requester):
                iid = "inv_c" + requester[:7].ljust(7, "x")
                self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE topic_id = ? AND scope = 'research' AND released_at IS NULL", T, TOPIC)
                lease = "lease_c" + requester[:6]
                self.lease(lease, {"router": 20, "operator": 21, "supervisor": 22}[requester])
                self.invocation(iid, lease=lease)
                self.x("UPDATE invocations SET cancel_requested_at = ?, cancel_requested_by = ? WHERE invocation_id = ?", T, requester, iid)
                self.assertEqual(self.value("SELECT cancel_requested_by FROM invocations WHERE invocation_id = ?", iid), requester)

    def test_the_cancellation_request_is_write_once(self) -> None:
        self.x("UPDATE invocations SET cancel_requested_at = ?, cancel_requested_by = 'operator' WHERE invocation_id = 'inv_pppppppp'", T)
        before = self.snapshot("invocations")
        self.rejects("write-once", "UPDATE invocations SET cancel_requested_at = '2026-09-25T13:00:00Z' WHERE invocation_id = 'inv_pppppppp'")
        self.rejects("write-once", "UPDATE invocations SET cancel_requested_by = 'router' WHERE invocation_id = 'inv_pppppppp'")
        self.assertEqual(self.snapshot("invocations"), before)
        self.x("UPDATE invocations SET cancel_requested_at = ?, cancel_requested_by = 'operator' WHERE invocation_id = 'inv_pppppppp'", T)  # unchanged: allowed

    def test_descendant_confirmation_is_write_once(self) -> None:
        self.x("UPDATE invocations SET state = 'cancelled', cancel_requested_at = ?, cancel_requested_by = 'operator', descendants_confirmed_at = ?, end_evidence_ref = ? "
               "WHERE invocation_id = 'inv_pppppppp'", T, T, EVIDENCE)
        before = self.snapshot("invocations")
        self.rejects("write-once", "UPDATE invocations SET descendants_confirmed_at = '2026-09-25T13:00:00Z' WHERE invocation_id = 'inv_pppppppp'")
        self.assertEqual(self.snapshot("invocations"), before)


class UnknownHoldTest(SupervisionTestCase):
    """The router hold an outcome_unknown episode opens (subject
    'invocation:<id>#unknown:<episode>'), cleared by that episode's record."""

    def setUp(self) -> None:
        super().setUp()
        self.to_unknown("inv_pppppppp")
        self.hold("hold_unknown01", "invocation:inv_pppppppp#unknown:1")
        self.reconcile("inv_pppppppp", "found_running", rid="rec_pppppppp1")

    def hold(self, hid: str, subject: str, *, tid: str = TOPIC, authority: str = "router") -> None:
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, created_at) "
               "VALUES (?, ?, ?, 'unknown', 'outcome unknown', 'unknown', ?, 'supervisor:st1', ?, 'its reconciliation record', ?)", hid, tid, subject, authority, T, T)

    def clear(self, hid: str, rid: str = "rec_pppppppp1") -> str:
        return f"UPDATE holds SET cleared_at = '{T}', cleared_by_reconciliation_id = '{rid}' WHERE hold_id = '{hid}'"

    def test_the_episode_record_clears_its_hold(self) -> None:
        self.x(self.clear("hold_unknown01"))
        self.assertEqual(self.rows("SELECT cleared_at, cleared_by_reconciliation_id FROM holds WHERE hold_id = 'hold_unknown01'"), [(T, "rec_pppppppp1")])

    def test_a_hold_is_not_created_cleared_by_a_record(self) -> None:
        self.rejects("a hold is created open", "INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, "
                     "clears_when, created_at, cleared_by_reconciliation_id) VALUES ('hold_unknown02', ?, 'invocation:inv_pppppppp#unknown:1', 'unknown', 'c', 'unknown', "
                     "'router', 'o', ?, 'w', ?, 'rec_pppppppp1')", TOPIC, T, T)

    def test_another_episode_is_not_cleared(self) -> None:
        self.hold("hold_unknown02", "invocation:inv_pppppppp#unknown:2")
        self.rejects("clears only the router hold of its own", self.clear("hold_unknown02"))
        self.assertEqual(self.rows("SELECT cleared_at FROM holds WHERE hold_id = 'hold_unknown02'"), [(None,)])

    def test_another_invocations_hold_is_not_cleared(self) -> None:
        self.hold("hold_unknown02", "invocation:inv_qqqqqqqq#unknown:1")
        self.rejects("clears only the router hold of its own", self.clear("hold_unknown02"))

    def test_another_topics_hold_is_not_cleared(self) -> None:
        self.hold("hold_unknown02", "invocation:inv_pppppppp#unknown:1", tid=OTHER)
        self.rejects("clears only the router hold of its own", self.clear("hold_unknown02"))

    def test_a_hold_another_authority_clears_is_not_cleared(self) -> None:
        for authority in ("primary", "operator"):
            with self.subTest(authority):
                hid = "hold_auth" + authority[:4]
                self.hold(hid, "invocation:inv_pppppppp#unknown:1", authority=authority)
                self.rejects("clears only the router hold of its own", self.clear(hid))

    def test_an_episode_hold_clears_only_through_a_reconciliation(self) -> None:
        """Astra 1c review A7: the converse of the tests above. An approved
        hold_clearance decision about the episode hold, and a committed
        operation, each clear nothing, each shown on its own; the episode's
        record does (test_the_episode_record_clears_its_hold). Controls: the
        same two paths clear an ordinary router hold."""
        self.decision("opd_clear0001", "hold_clearance", ref="hold_unknown01")
        self.receipt("op_clear00001", "inv_pppppppp", kind="interim_transition")
        before = self.rows("SELECT * FROM holds ORDER BY hold_id")
        for path, column, value in (("decision", "cleared_by_decision_id", "opd_clear0001"), ("operation", "cleared_by_operation_id", "op_clear00001")):
            with self.subTest(path):
                self.rejects("clears only through its reconciliation record", f"UPDATE holds SET cleared_at = ?, {column} = ? WHERE hold_id = 'hold_unknown01'", T, value)
                self.assertEqual(self.rows("SELECT * FROM holds ORDER BY hold_id"), before)
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, created_at) "
               "VALUES ('hold_ordinary1', ?, 'export:warehouse', 'transient', 'c', 'retry_within_budget', 'router', 'router', ?, 'w', ?), "
               "('hold_ordinary2', ?, 'export:warehouse', 'transient', 'c', 'retry_within_budget', 'router', 'router', ?, 'w', ?)", TOPIC, T, T, TOPIC, T, T)
        self.decision("opd_clear0002", "hold_clearance", ref="hold_ordinary1")
        self.x("UPDATE holds SET cleared_at = ?, cleared_by_decision_id = 'opd_clear0002' WHERE hold_id = 'hold_ordinary1'", T)
        self.x("UPDATE holds SET cleared_at = ?, cleared_by_operation_id = 'op_clear00001' WHERE hold_id = 'hold_ordinary2'", T)
        self.assertEqual(self.rows("SELECT hold_id FROM holds WHERE cleared_at IS NOT NULL ORDER BY hold_id"), [("hold_ordinary1",), ("hold_ordinary2",)])
        self.x(self.clear("hold_unknown01"))  # and the episode's own record clears it
        self.assertEqual(self.value("SELECT cleared_by_reconciliation_id FROM holds WHERE hold_id = 'hold_unknown01'"), "rec_pppppppp1")

    def test_a_cleared_hold_stays_cleared(self) -> None:
        self.x(self.clear("hold_unknown01"))
        self.rejects("a cleared hold is final", "UPDATE holds SET cleared_at = NULL, cleared_by_reconciliation_id = NULL WHERE hold_id = 'hold_unknown01'")


class ArtifactTopicTest(SupervisionTestCase):
    """Task 1c-repair A6: an artifact row is the physical record of its bytes,
    shared by every topic that staged them; which topics may reference it is
    recorded separately, per topic, and only by that topic's own work (C-9)."""

    def test_a_topic_is_authorized_only_by_its_own_work(self) -> None:
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_oooooooo")
        ins = "INSERT INTO artifact_topics (content_hash, topic_id, recorded_by_invocation_id, recorded_at) VALUES (?, ?, ?, ?)"
        before = self.rows("SELECT * FROM artifact_topics")
        self.rejects("own invocation", ins, EVIDENCE, TOPIC, "inv_oooooooo", T)  # another topic's work authorizes nothing here
        self.rejects("own invocation", ins, EVIDENCE, OTHER, "inv_pppppppp", T)
        self.assertEqual(self.rows("SELECT * FROM artifact_topics"), before)
        self.x(ins, EVIDENCE, TOPIC, "inv_pppppppp", T)
        self.x(ins, EVIDENCE, OTHER, "inv_oooooooo", T)  # the same bytes, one physical row, a second topic's own authorization
        self.assertEqual(self.rows("SELECT topic_id, recorded_by_invocation_id FROM artifact_topics WHERE content_hash = ? ORDER BY topic_id", EVIDENCE),
                         [(TOPIC, "inv_pppppppp"), (OTHER, "inv_oooooooo")])
        self.assertEqual(self.value("SELECT count(*) FROM artifacts WHERE content_hash = ?", EVIDENCE), 1)
