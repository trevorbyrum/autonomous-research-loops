"""Re-queues and reservations through the supervisor's work orders (task 1d;
Astra 1d review finding 3): a lane whose last work failed or was cancelled
is claimed again only as that work's re-queued retry (service.Router claim,
requeue_required), which an order names (WorkOrder.retry_of); a reservation
is drawn by the order naming it (WorkOrder.reservation). Both are stored
with the order and sent with every claim, so a restart before the claim, or
a lost reply, sends the same request again.

Trace: INVARIANTS L-6, RG-3, G-5, L-8, C-12; gen2/router/scheduling.py;
gen2/supervisor/supervisor.py (WorkOrder, Supervisor._grant); the 1d
review's ruling on question 1 (the lane rule stands; this is its supervisor
integration).

Every kind but the delegate runs each case. A delegate holds its parent's
lease, so it is never a lane's retry and draws no reservation: the router
refuses both, and its order ends not_admitted (DelegateContextTest).

Oracles: hand-written outcomes; raw-SQL read-back of invocations, retries,
reservation draws and holds, and of the whole store around each refusal.

Structural limits: fake executors; a first run fails by its exit status or
is cancelled by the operator; the re-queue is asked for here, as the trusted
surface (1e) or a policy caller would — no autonomous scheduler exists or is
exercised.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from gen2.core import canonical
from gen2.supervisor.supervisor import WorkOrder
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import PARENT, SupervisedTestCase

FIRST, SECOND, THIRD = "inv_first00001", "inv_second0001", "inv_third00001"
FAILS = [{"op": "exit", "code": 3}]
HANGS = [{"op": "hang"}]
RESERVATION = "rsv_explore0001"
# The pinned bundle: one policy re-run of an exit_nonzero failure, and one protected-exploration admission.
BUNDLE = {"bundle_version": "config-bundle/1", "version": 2, "questions": [rf.QUESTION],
          "policy": {"router": {"retry": {"attempts": 1, "failure_classes": ["exit_nonzero"]},
                                "reservations": {"protected_exploration": {"units": 1}}}}}
BUNDLE_HASH = canonical.logical_hash(BUNDLE)


class Stop(Exception):
    pass


class Requeues:
    KIND: str

    def setUp(self) -> None:
        super().setUp()
        assert self.router.activate_config_bundle(BUNDLE)["status"] == "activated"

    def work(self, inv: str, steps=None, **context) -> WorkOrder:
        return replace(self.order(self.KIND, steps, inv=inv), config_bundle_hash=BUNDLE_HASH, **context)

    def ends(self, order: WorkOrder, outcome: str) -> None:
        self.supervisor.prepare(order)
        self.assertEqual(self.supervisor.run(order.invocation_id), outcome)

    def refused_order(self, order: WorkOrder, reason: str) -> None:
        before = self.state(exclude=())
        self.assertEqual(self.supervisor.submit(order), "not_admitted")
        self.assertEqual(self.journal(order.invocation_id)["refused"]["reason"], reason)
        self.assertEqual(self.state(exclude=()), before)  # nothing admitted, drawn or written

    def requeue(self, inv: str, by: str = "policy") -> dict:
        return self.router.requeue({"invocation_id": inv, "requested_by": by, "reason": "transient" if by == "policy" else "diagnosed"})

    def linked(self) -> list[tuple]:
        return self.rows("SELECT invocation_id, attempt, retry_invocation_id FROM retries ORDER BY rowid")

    def test_a_failed_run_is_requeued_and_its_retry_runs(self) -> None:
        self.ends(self.work(FIRST, FAILS), "failed")
        self.assertEqual(self.rows("SELECT failure_class FROM invocations WHERE invocation_id = ?", FIRST), [("exit_nonzero",)])
        self.refused_order(self.work(SECOND), "requeue_required")  # the lane waits for the re-queue
        self.assertEqual(self.requeue(FIRST)["status"], "requeued")
        self.ends(self.work(THIRD, retry_of=FIRST), "committed")
        self.assertEqual(self.linked(), [(FIRST, 2, THIRD)])
        self.assertEqual(self.rows("SELECT invocation_id, state FROM invocations ORDER BY admitted_at"), [(FIRST, "failed"), (THIRD, "committed")])

    def test_a_cancelled_run_is_requeued_by_the_operator_and_runs_again(self) -> None:
        self.supervisor.prepare(self.work(FIRST, HANGS))
        self.assertEqual(self.supervisor.run(FIRST, until=("running",)), "running")
        self.assertEqual(self.router.request_cancel({"invocation_id": FIRST, "requested_by": "operator", "reason": "stop"})["status"], "recorded")
        self.assertEqual(self.supervisor.run(FIRST), "cancelled")
        self.assertEqual(self.requeue(FIRST, "operator")["status"], "requeued")
        self.ends(self.work(SECOND, retry_of=FIRST), "committed")
        self.assertEqual(self.linked(), [(FIRST, 2, SECOND)])

    def test_the_retry_survives_a_restart_before_its_claim(self) -> None:
        self.ends(self.work(FIRST, FAILS), "failed")
        self.requeue(FIRST)
        self.supervisor.prepare(self.work(SECOND, retry_of=FIRST))  # durable, not yet claimed
        self.supervisor = self.make_supervisor()  # a restart
        self.assertEqual(self.supervisor.recover()[SECOND], "running")
        self.assertEqual(self.supervisor.run(SECOND), "committed")
        self.assertEqual(self.linked(), [(FIRST, 2, SECOND)])

    def test_a_lost_claim_reply_replays_with_its_retry(self) -> None:
        self.ends(self.work(FIRST, FAILS), "failed")
        self.requeue(FIRST)

        def lose(point: str) -> None:
            if point == "claimed":
                raise Stop(point)
        with self.assertRaises(Stop):  # the router admitted the retry; the grant never reached the journal
            self.make_supervisor(fault=lose).submit(self.work(SECOND, retry_of=FIRST))
        self.assertEqual(self.linked(), [(FIRST, 2, SECOND)])
        self.supervisor = self.make_supervisor()
        self.assertEqual(self.supervisor.run(SECOND), "committed")  # the same claim again: a replay, not a conflict
        self.assertEqual(self.rows("SELECT count(*) FROM invocations WHERE invocation_id = ?", SECOND), [(1,)])
        self.assertEqual(self.linked(), [(FIRST, 2, SECOND)])

    def test_the_policy_budget_ends_in_a_hold_not_a_run(self) -> None:
        self.ends(self.work(FIRST, FAILS), "failed")
        self.assertEqual(self.requeue(FIRST)["status"], "requeued")
        self.ends(self.work(SECOND, FAILS, retry_of=FIRST), "failed")
        self.assertEqual(self.requeue(SECOND)["status"], "exhausted")  # the bundle's one re-run is spent
        self.assertEqual(self.value("SELECT count(*) FROM holds WHERE subject_ref = ? AND cleared_at IS NULL", f"invocation:{SECOND}#requeue"), 1)
        self.refused_order(self.work(THIRD, retry_of=SECOND), "requeue_required")

    def test_a_reservation_is_drawn_by_the_order_naming_it(self) -> None:
        opened = self.router.open_reservation({"topic_id": rf.TOPIC, "reservation_id": RESERVATION, "purpose": "protected_exploration"})
        self.assertEqual(opened["status"], "opened", opened)
        self.ends(self.work(FIRST, reservation={"reservation_id": RESERVATION}), "committed")
        self.assertEqual(self.rows("SELECT invocation_id, reservation_id FROM reservation_draws"), [(FIRST, RESERVATION)])
        self.refused_order(self.work(SECOND, reservation={"reservation_id": RESERVATION}), "reservation_exhausted")


class ResearchPassRequeueTest(Requeues, SupervisedTestCase):
    KIND = "research_pass"


class DiscoveryRequeueTest(Requeues, SupervisedTestCase):
    KIND = "discovery"


class VerificationRequeueTest(Requeues, SupervisedTestCase):
    KIND = "verification"


class CheckpointRequeueTest(Requeues, SupervisedTestCase):
    KIND = "checkpoint"


class DelegateContextTest(SupervisedTestCase):
    """L-8: a delegate order naming a retry or a reservation is refused by
    the router (the claim's delegate shape), and admits nothing."""

    def test_a_delegate_is_no_retry_and_draws_nothing(self) -> None:
        self.start_parent()
        for context in ({"retry_of": PARENT}, {"reservation": {"reservation_id": RESERVATION}}):
            with self.subTest(**context):
                order = replace(self.order("delegate", inv="inv_deleg" + ("r" if "retry_of" in context else "v") + "0001"), **context)
                before = self.state(exclude=())
                self.assertEqual(self.supervisor.submit(order), "not_admitted")
                self.assertEqual(self.journal(order.invocation_id)["refused"]["reason"], "request_invalid")
                self.assertEqual(self.state(exclude=()), before)


if __name__ == "__main__":
    unittest.main()
