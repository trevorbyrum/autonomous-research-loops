"""Re-queues, reservations and the coalesced signal queue (task 1d).

Trace: INVARIANTS L-6, RG-3, G-5, G-10, G-12, H-3, §13 (reservations and
the signal queue's budget and cooldown are Phase 1 router state); the 1c
deferrals (scheduling and retry of failed and cancelled work);
gen2/router/scheduling.py.

Every test here runs under POLICY, a bundle whose router section declares a
retry budget, reservation sizes and a signal-queue budget and cooldown (the
test bundle of router_fixtures declares none, and none of these is
admitted without one).

Oracles: hand-written expectations; raw SQL read-back of the whole store
(every table but the audit log) around each refusal.

Structural limits: invocations are the router fixture's, standing in for
fake executors; nothing schedules — each operation is asked for by the
test, as the trusted surface (1e) or a policy caller would. The router
cannot tell a fresh claim of a lane whose last work ended well from a
retry: the retry budget binds the lanes whose last work failed or was
cancelled, which is where a retry happens.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from gen2.core import canonical
from gen2.store import api
from gen2.tests import router_fixtures as rf, store_fixtures
from gen2.core.instants import utc_instant_ns
from gen2.tests.router_fixtures import TOPIC, RouterTestCase, empty_outcome
from gen2.tests.test_router_amendments import ContractWorld, compatible, reframed

KINDS = ("research_pass", "discovery", "verification", "checkpoint")
POLICY = {"bundle_version": "config-bundle/1", "version": 2, "questions": [],
          "policy": {"router": {"hold_window_s": 600, "retry": {"attempts": 1, "failure_classes": ["killed", "spawn_failed"]},
                                "reservations": {"protected_exploration": {"units": 2}, "auto_promotion": {"units": 1, "min_band": "critical"}},
                                "signal_queue": {"budget": 2, "window_s": 86400, "cooldown_s": 3600}}}}
POLICY_HASH = canonical.logical_hash(POLICY)


class PolicyCase(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        assert self.router.activate_config_bundle(POLICY)["status"] == "activated"

    def claim(self, inv: str, kind: str = "research_pass", tid: str = TOPIC, **extra) -> dict:
        extra.setdefault("config_bundle_hash", POLICY_HASH)  # new work pins the active bundle
        return super().claim(inv, kind, tid, **extra)

    def fail(self, grant: dict, failure_class: str = "killed") -> None:
        out = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "to_state": "failed",
                                             "failure_class": failure_class, "end_evidence_ref": self.evidence(grant, (failure_class,))})
        assert out["status"] == "recorded", out

    def refused(self, out: dict, reason: str, before: dict, detail: str | None = None) -> None:
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        if detail is not None:
            self.assertIn(detail, out.get("detail", ""))
        self.assertEqual(self.state(), before)

    def requeue(self, inv: str, by: str = "policy", reason: str = "transient") -> dict:
        return self.router.requeue({"invocation_id": inv, "requested_by": by, "reason": reason})


class RequeueTest(PolicyCase):
    """L-6, RG-3, for every kind: a lane whose last work failed or was
    cancelled is claimed again only as that work's re-queued retry; policy
    re-queues a transient failure within the pinned budget, and past it opens
    one owned, deadlined hold, which an operator clears before re-queueing."""

    def setUp(self) -> None:
        super().setUp()
        self.to_queued()

    def test_every_kinds_lane_waits_for_a_requeue_within_its_budget(self) -> None:
        for kind in KINDS:
            with self.subTest(kind):
                first = self.started(f"inv_{kind[:6]}01", kind)
                self.fail(first)
                before = self.state()
                self.refused(self.claim(f"inv_{kind[:6]}02", kind), "requeue_required", before, f"{first['invocation_id']}, the last")
                self.refused(self.claim(f"inv_{kind[:6]}02", kind, retry_of=first["invocation_id"]), "requeue_required", before)  # named, not yet re-queued
                self.assertEqual(self.requeue(first["invocation_id"]), {"status": "requeued", "invocation_id": first["invocation_id"], "attempt": 2})
                before = self.state()
                self.refused(self.claim(f"inv_{kind[:6]}02", kind), "requeue_required", before)  # re-queued, the lane is claimed as its retry, by name
                second = self.claim(f"inv_{kind[:6]}02", kind, retry_of=first["invocation_id"])
                self.assertEqual(second["status"], "granted", second)
                self.assertEqual(self.rows("SELECT attempt, requested_by, retry_invocation_id FROM retries WHERE invocation_id = ?", first["invocation_id"]),
                                 [(2, "policy", second["invocation_id"])])
                self.running(second)
                self.fail(second)
                out = self.requeue(second["invocation_id"])  # attempt 3 is past a budget of one retry
                self.assertEqual(out["status"], "exhausted", out)
                self.assertEqual(self.rows("SELECT subject_ref, hold_class, required_authority, owner, cleared_at FROM holds WHERE hold_id = ?", out.get("hold_id")),
                                 [(f"invocation:{second['invocation_id']}#requeue", "transient", "operator", "operator", None)])
                self.assertEqual(self.rows("SELECT count(*) FROM retries WHERE invocation_id = ?", second["invocation_id"]), [(0,)])
                before = self.state()
                self.refused(self.requeue(second["invocation_id"]), "incident_open", before)  # one hold; nothing more is re-queued
                self.refused(self.requeue(second["invocation_id"], "operator", "diagnosed"), "incident_open", before)
                self.assertEqual(self.decide(f"opd_clear{kind[:6]}", "hold_clearance", {"kind": "hold", "ref": out.get("hold_id")})["status"], "applied")
                self.assertEqual(self.requeue(second["invocation_id"], "operator", "diagnosed"),
                                 {"status": "requeued", "invocation_id": second["invocation_id"], "attempt": 3})
                third = self.started(f"inv_{kind[:6]}03", kind, retry_of=second["invocation_id"])
                self.assertEqual(self.finish(third, f"op_{kind[:6]}0003")["status"], "committed")
                self.assertEqual(self.claim(f"inv_{kind[:6]}04", kind)["status"], "granted")  # a lane whose last work committed takes fresh work

    def test_the_hold_deadline_is_the_pinned_bundles_window(self) -> None:
        self.fail(first := self.started("inv_discov01", "discovery"))
        self.requeue(first["invocation_id"])
        second = self.started("inv_discov02", "discovery", retry_of=first["invocation_id"])
        self.fail(second)
        hold_id = self.requeue(second["invocation_id"]).get("hold_id")
        created, deadline = self.rows("SELECT created_at, deadline_at FROM holds WHERE hold_id = ?", hold_id)[0]
        self.assertEqual((utc_instant_ns(deadline) - utc_instant_ns(created)) // 10**9, 600)

    def test_policy_requeues_only_transient_ends(self) -> None:
        """L-6: a semantic failure, or a cancellation the operator made, is the
        operator's to diagnose; a failure class the bundle lists, or a
        cancellation the supervisor or the router made, is policy's."""
        cases = (("an empty output", "discovery", lambda g: self.fail(g, "empty_output"), False),
                 ("an operator's cancellation", "checkpoint", lambda g: self.router.request_cancel(
                     {"invocation_id": g["invocation_id"], "requested_by": "operator", "reason": "stop"}), False),
                 ("the supervisor's cancellation", "verification", lambda g: self.router.request_cancel(
                     {"invocation_id": g["invocation_id"], "requested_by": "supervisor", "reason": "launch refused", "capability_id": g["capability_id"]}), True))
        for name, kind, end, retryable in cases:
            with self.subTest(name):
                grant = self.claim(f"inv_{kind[:6]}01", kind)  # admitted: a cancellation ends it at once, a failure needs it running
                if not retryable and kind == "discovery":
                    self.running(grant)
                end(grant)
                if retryable:
                    self.assertEqual(self.requeue(grant["invocation_id"])["status"], "requeued")
                else:
                    before = self.state()
                    self.refused(self.requeue(grant["invocation_id"]), "not_policy_retryable", before, "the operator's to diagnose")
                    self.assertEqual(self.requeue(grant["invocation_id"], "operator", "diagnosed")["status"], "requeued")

    def test_only_a_lanes_last_ended_non_delegate_work_is_requeued(self) -> None:
        parent = self.started("inv_research01")
        delegate = self.started("inv_deleg001", "delegate", parent=parent)
        committed = self.started("inv_checkpt01", "checkpoint")
        self.assertEqual(self.finish(committed, "op_checkpt0001")["status"], "committed")
        cancelled = self.claim("inv_discov01", "discovery")
        self.router.request_cancel({"invocation_id": "inv_discov01", "requested_by": "operator", "reason": "stop"})
        self.requeue("inv_discov01", "operator", "again")
        self.started("inv_discov02", "discovery", retry_of="inv_discov01")
        ended_delegate = self.claim("inv_deleg002", "delegate", parent=parent)
        self.assertEqual(self.router.request_cancel({"invocation_id": "inv_deleg002", "requested_by": "operator", "reason": "stop"}).get("status"), "cancelled")
        before = self.state()
        for name, inv in (("a running delegate", delegate["invocation_id"]), ("an ended delegate", ended_delegate["invocation_id"]),
                          ("committed work", committed["invocation_id"]), ("running work", "inv_research01")):
            with self.subTest(name):
                self.refused(self.requeue(inv, "operator", "x"), "not_requeueable", before)
        self.refused(self.requeue("inv_discov01", "operator", "another reason"), "requeue_conflict", before)  # re-queued once, already claimed
        self.assertEqual(self.requeue("inv_discov01", "operator", "again")["status"], "replayed")
        self.assertEqual(self.state(), before)
        self.assertEqual(cancelled["status"], "granted")

    def test_ended_work_its_lane_moved_past_is_not_requeued(self) -> None:
        """Work whose lease expired and was replaced ends afterwards: its lane's
        last work is the replacement, so it is not re-queued (the replacement
        is, once it ends)."""
        first = self.claim("inv_discov01", "discovery", lease_expires_at="2026-09-27T10:30:00Z")
        self.running(first)
        self.clock.set("2026-09-27T10:31:00Z")
        second = self.started("inv_discov02", "discovery")  # the expired lease is released and replaced
        self.fail(first)
        before = self.state()
        self.refused(self.requeue("inv_discov01"), "not_requeueable", before, "only the last work of a lane")
        self.fail(second)
        self.assertEqual(self.requeue("inv_discov02")["status"], "requeued")

    def test_the_same_requeue_again_replays(self) -> None:
        """The accepted path of the re-queue conflict guard, on its own."""
        self.claim("inv_discov01", "discovery")
        self.router.request_cancel({"invocation_id": "inv_discov01", "requested_by": "operator", "reason": "stop"})
        self.assertEqual(self.requeue("inv_discov01", "operator", "again")["status"], "requeued")
        before = self.state()
        self.assertEqual(self.requeue("inv_discov01", "operator", "again"), {"status": "replayed", "invocation_id": "inv_discov01", "attempt": 2})
        self.assertEqual(self.state(), before)

    def test_a_retry_names_only_the_lanes_waiting_work(self) -> None:
        first = self.claim("inv_discov01", "discovery")
        self.router.request_cancel({"invocation_id": "inv_discov01", "requested_by": "operator", "reason": "stop"})
        self.requeue("inv_discov01", "operator", "again")
        before = self.state()
        self.refused(self.claim("inv_checkpt01", "checkpoint", retry_of="inv_discov01"), "request_invalid", before, "not ended work waiting in this lane")
        retry = self.claim("inv_discov02", "discovery", retry_of="inv_discov01")
        self.assertEqual(retry["status"], "granted")
        self.assertEqual(self.claim("inv_discov02", "discovery", retry_of="inv_discov01")["status"], "replayed")  # the same claim again
        conflict = self.claim("inv_discov02", "discovery")
        self.assertEqual(conflict.get("reason"), "invocation_id_conflict")  # the same id without its retry_of is another request
        self.assertEqual(first["status"], "granted")


class ReservationTest(ContractWorld):
    """G-5: protected-exploration and auto-promotion reservations: bound to
    the approved revision they were opened under, drawn within their units,
    and for auto-promotion only inside a facet the operator rated at or above
    the bundle's threshold; an amendment closes them."""

    def setUp(self) -> None:
        super().setUp()
        assert self.router.activate_config_bundle(POLICY)["status"] == "activated"

    def claim(self, inv: str, kind: str = "research_pass", tid: str = TOPIC, **extra) -> dict:
        extra.setdefault("config_bundle_hash", POLICY_HASH)
        return super().claim(inv, kind, tid, **extra)

    def open(self, rid: str, purpose: str) -> dict:
        return self.router.open_reservation({"reservation_id": rid, "topic_id": TOPIC, "purpose": purpose})

    def refused(self, out: dict, reason: str, before: dict) -> None:
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        self.assertEqual(self.state(), before)

    def test_a_reservation_is_sized_by_the_bundle_and_drawn_within_its_units(self) -> None:
        self.assertEqual(self.open("rsv_explore001", "protected_exploration"),
                         {"status": "opened", "reservation_id": "rsv_explore001", "contract_revision": 2, "units": 2})
        self.assertEqual(self.rows("SELECT purpose, contract_revision, units, min_band, bundle_hash, closed_at FROM reservations"),
                         [("protected_exploration", 2, 2, None, POLICY_HASH, None)])
        draw = {"reservation_id": "rsv_explore001"}
        self.assertEqual(self.claim("inv_discov01", "discovery", reservation=draw)["status"], "granted")
        self.assertEqual(self.claim("inv_checkpt01", "checkpoint", reservation=draw)["status"], "granted")
        before = self.state()
        self.refused(self.claim("inv_verify01", "verification", reservation=draw), "reservation_exhausted", before)
        self.assertEqual(self.rows("SELECT invocation_id, reservation_id, facet_id FROM reservation_draws ORDER BY invocation_id"),
                         [("inv_checkpt01", "rsv_explore001", None), ("inv_discov01", "rsv_explore001", None)])
        self.assertEqual(self.claim("inv_verify01", "verification")["status"], "granted")  # without the reservation, as ordinary work

    def test_an_auto_promotion_draw_is_inside_a_facet_rated_at_the_threshold(self) -> None:
        self.assertEqual(self.open("rsv_promote01", "auto_promotion").get("units"), 1)
        before = self.state()
        for name, facet in (("an important facet", "F-cost"), ("no such facet", "F-none")):
            with self.subTest(name):
                self.refused(self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_promote01", "facet_id": facet}), "reservation_invalid", before)
        self.refused(self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_promote01"}), "reservation_invalid", before)
        grant = self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_promote01", "facet_id": "F-effect"})
        self.assertEqual(grant["status"], "granted", grant)
        self.assertEqual(self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_promote01", "facet_id": "F-effect"})["status"], "replayed")
        self.assertEqual(self.claim("inv_checkpt01", "checkpoint").get("reason"), "invocation_id_conflict")  # without its reservation it is another request

    def test_an_auto_promotion_draw_inside_a_critical_facet(self) -> None:
        """The accepted path of the threshold guard, on its own."""
        self.open("rsv_promote01", "auto_promotion")
        self.assertEqual(self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_promote01", "facet_id": "F-effect"})["status"], "granted")
        self.assertEqual(self.rows("SELECT invocation_id, facet_id FROM reservation_draws"), [("inv_checkpt01", "F-effect")])

    def test_the_same_reservation_again_replays(self) -> None:
        """The accepted path of the reservation-conflict guard, on its own."""
        self.open("rsv_explore001", "protected_exploration")
        before = self.state()
        self.assertEqual(self.open("rsv_explore001", "protected_exploration"), {"status": "replayed", "reservation_id": "rsv_explore001", "units": 2})
        self.assertEqual(self.state(), before)

    def test_an_exhausted_reservation_is_closed_when_the_next_opens(self) -> None:
        """The accepted path of the guard refusing a second open reservation:
        the one open has no units left, so the next opens."""
        self.open("rsv_explore001", "protected_exploration")
        self.claim("inv_discov01", "discovery", reservation={"reservation_id": "rsv_explore001"})
        self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_explore001"})
        self.assertEqual(self.open("rsv_explore002", "protected_exploration")["status"], "opened")
        self.assertEqual(self.rows("SELECT reservation_id, close_reason FROM reservations ORDER BY rowid"), [("rsv_explore001", "exhausted"), ("rsv_explore002", None)])

    def test_an_amendment_leaves_a_closed_reservation_as_it_was(self) -> None:
        """The accepted path of the impact's closing guard: a reservation already
        closed is passed over, its closure kept."""
        self.open("rsv_explore001", "protected_exploration")
        self.claim("inv_discov01", "discovery", reservation={"reservation_id": "rsv_explore001"})
        self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_explore001"})
        self.open("rsv_explore002", "protected_exploration")  # the first closes, exhausted
        closed = self.rows("SELECT * FROM reservations WHERE reservation_id = 'rsv_explore001'")
        self.approve(self.propose(3, compatible))
        self.assertEqual(self.rows("SELECT * FROM reservations WHERE reservation_id = 'rsv_explore001'"), closed)

    def test_an_amendment_closes_the_reservations_of_the_revision_it_supersedes(self) -> None:
        self.open("rsv_explore001", "protected_exploration")
        self.open("rsv_promote01", "auto_promotion")
        self.approve(self.propose(3, reframed), "reframe_approval")
        record = self.impact("opd_amend0003")
        self.assertEqual(sorted(record["reservations_closed"]), ["rsv_explore001", "rsv_promote01"])
        before = self.state()
        self.refused(self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_promote01", "facet_id": "F-effect"}), "reservation_closed", before)
        self.assertEqual(self.open("rsv_promote02", "auto_promotion").get("contract_revision"), 3)  # a new reservation, under the reframed revision

    def test_opening_needs_an_approved_revision_a_size_and_no_open_one_with_units_left(self) -> None:
        self.assertEqual(self.open("rsv_explore001", "protected_exploration")["status"], "opened")
        before = self.state()
        self.refused(self.open("rsv_explore002", "protected_exploration"), "reservation_open", before)
        self.refused(self.router.open_reservation({"reservation_id": "rsv_explore009", "topic_id": "fleet-a:t2", "purpose": "protected_exploration"}),
                     "no_approved_contract", before)
        self.refused(self.router.open_reservation({"reservation_id": "rsv_explore001", "topic_id": TOPIC, "purpose": "auto_promotion"}), "reservation_conflict", before)
        self.assertEqual(self.open("rsv_explore001", "protected_exploration")["status"], "replayed")
        for n in (1, 2):
            self.claim(f"inv_discov0{n}", "discovery" if n == 1 else "checkpoint", reservation={"reservation_id": "rsv_explore001"})
        self.assertEqual(self.open("rsv_explore002", "protected_exploration")["status"], "opened")  # the exhausted one closes
        self.assertEqual(self.rows("SELECT reservation_id, close_reason FROM reservations WHERE purpose = 'protected_exploration' ORDER BY rowid"),
                         [("rsv_explore001", "exhausted"), ("rsv_explore002", None)])
        unsized = {**POLICY, "version": 3, "policy": {}}
        self.assertEqual(self.router.activate_config_bundle(unsized)["status"], "activated")
        before = self.state()
        self.refused(self.open("rsv_promote01", "auto_promotion"), "not_configured", before)


class SignalQueueTest(PolicyCase):
    """G-12, flow S5: one coalesced signal queue per topic. A review takes
    every pending trigger; signal-driven reviews are budgeted per window and
    cooled down; the fixed cadence floor and a pending mandatory signal are
    never held back; a refused review drops nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.checkpoint = self.started("inv_checkpt01", "checkpoint")
        self.n = 0

    def signal(self) -> str:
        self.n += 1
        outcome = empty_outcome("inv_checkpt01", "interim_transition")
        outcome["review_triggers"] = [{"reason_code": "persistent_contradiction", "cause_ref": f"c{self.n}", "source_revision": 1, "observed_at": "2026-09-27T10:00:00Z"}]
        response = self.router.commit_outcome(self.envelope(self.checkpoint, f"op_signal{self.n:05d}", outcome))
        assert response["status"] == "committed", response
        return response["receipt"]["effects"]["trigger_identities"][0]

    def review(self, n: int, kind: str = "method_fit") -> dict:
        return self.router.open_review({"episode_id": f"rev_episode{n:04d}", "topic_id": TOPIC, "kind": kind})

    def pending(self) -> list:
        return [r[0] for r in self.rows("SELECT trigger_identity FROM review_triggers WHERE episode_id IS NULL ORDER BY rowid")]

    def test_reviews_coalesce_within_budget_and_cooldown_and_drop_nothing(self) -> None:
        first = [self.signal(), self.signal()]
        self.assertEqual(self.review(1), {"status": "opened", "episode_id": "rev_episode0001", "triggers": first})
        waiting = self.signal()
        before = self.state()
        self.refused(self.review(2), "signal_cooldown", before, "the signals stay queued")
        self.assertEqual(self.pending(), [waiting])
        self.clock.set("2026-09-27T11:00:00.100Z")  # past the hour's cooldown
        self.assertEqual(self.review(2).get("triggers"), [waiting])
        self.signal()
        self.clock.set("2026-09-27T13:00:00Z")
        before = self.state()
        self.refused(self.review(3), "signal_budget_spent", before, "2 signal reviews within 86400 s")
        self.clock.set("2026-09-28T10:00:01Z")  # the first review has left the window
        self.assertEqual(self.review(3)["status"], "opened")
        self.assertEqual(self.rows("SELECT episode_id, count(*) FROM review_triggers GROUP BY episode_id ORDER BY episode_id"),
                         [("rev_episode0001", 2), ("rev_episode0002", 1), ("rev_episode0003", 1)])

    def test_the_cadence_floor_and_mandatory_signals_are_never_held_back(self) -> None:
        self.signal()
        self.review(1)
        routine = self.signal()
        self.assertEqual(self.review(2, "fixed_cadence").get("triggers"), [routine])  # the floor, during the cooldown
        self.x("INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, 'retraction', 'deterministic', 'doi:10.1/x', ?)",
               "sha256:" + "d" * 64, TOPIC, "2026-09-27T10:30:00Z")  # code policy's signal (no router path raises one yet: surveillance is Phase 2)
        self.assertEqual(self.review(3).get("triggers"), ["sha256:" + "d" * 64])  # mandatory: during the cooldown
        self.clock.set("2026-09-27T13:00:00Z")
        waiting = self.signal()
        before = self.state()
        self.refused(self.review(4), "signal_budget_spent", before)  # episodes 1 and 3 fill the budget of two
        self.x("INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, 'decision_record_change', 'operator', 'DR-2', ?)",
               "sha256:" + "e" * 64, TOPIC, "2026-09-27T13:00:00Z")
        self.assertEqual(self.review(4).get("triggers"), [waiting, "sha256:" + "e" * 64])  # mandatory: past the budget, and the queued signal with it

    def test_the_same_review_again_replays(self) -> None:
        """The accepted path of the review-conflict guard, on its own."""
        self.signal()
        self.assertEqual(self.review(1)["status"], "opened")
        before = self.state()
        self.assertEqual(self.review(1), {"status": "replayed", "episode_id": "rev_episode0001"})
        self.assertEqual(self.state(), before)

    def test_a_review_needs_a_pending_signal_a_configured_queue_and_its_own_key(self) -> None:
        before = self.state()
        self.refused(self.review(1), "no_pending_signal", before)
        self.signal()
        self.assertEqual(self.router.activate_config_bundle({**POLICY, "version": 3, "policy": {}})["status"], "activated")
        before = self.state()
        self.refused(self.review(1), "not_configured", before, "the signals stay queued")
        self.assertEqual(self.review(1, "fixed_cadence")["status"], "opened")
        self.assertEqual(self.review(1, "fixed_cadence")["status"], "replayed")
        before = self.state()
        self.refused(self.review(1, "method_fit"), "review_conflict", before)


class SchedulingRestartTest(ContractWorld):
    """RG-9: re-queues, reservations and their draws are store state: after a
    restart a waiting lane still waits for its retry, a claimed re-queue is
    still claimed, and a reservation's drawn units still count."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        api.open_store(self.directory / "store.sqlite3", create=True).close()
        self.db = sqlite3.connect(self.directory / "store.sqlite3", isolation_level=None)
        self.db.executescript(store_fixtures.CONNECTION_TEXT)
        self.store = api.open_store(self.directory / "store.sqlite3")
        self.spool, self.clock, self.ids, self.faults = rf.Spool(), rf.Clock(), rf.Ids(), {}
        self.router = self.make_router()
        self.seed()
        self.build_world()
        assert self.router.activate_config_bundle(POLICY)["status"] == "activated"

    def tearDown(self) -> None:
        self.router.close()
        self.db.close()
        self._tmp.cleanup()

    def reopen(self) -> None:
        self.router.close()
        self.store = api.open_store(self.directory / "store.sqlite3")
        self.router = self.make_router()

    def claim(self, inv: str, kind: str = "research_pass", tid: str = TOPIC, **extra) -> dict:
        extra.setdefault("config_bundle_hash", POLICY_HASH)
        return super().claim(inv, kind, tid, **extra)

    def open(self, rid: str, purpose: str) -> dict:
        return self.router.open_reservation({"reservation_id": rid, "topic_id": TOPIC, "purpose": purpose})

    def test_retry_and_reservation_state_survive_a_restart(self) -> None:
        self.open("rsv_explore001", "protected_exploration")
        first = self.claim("inv_discov01", "discovery", reservation={"reservation_id": "rsv_explore001"})
        self.running(first)
        out = self.router.record_transition({"capability_id": first["capability_id"], "invocation_id": "inv_discov01", "to_state": "failed",
                                             "failure_class": "killed", "end_evidence_ref": self.evidence(first, ("killed",))})
        self.assertEqual(out["status"], "recorded", out)
        self.assertEqual(self.router.requeue({"invocation_id": "inv_discov01", "requested_by": "policy", "reason": "transient"}).get("attempt"), 2)
        self.reopen()
        before = self.state()
        refused = self.claim("inv_discov02", "discovery")
        self.assertEqual((refused["status"], refused.get("reason")), ("refused", "requeue_required"))
        self.assertEqual(self.state(), before)
        retry = self.claim("inv_discov02", "discovery", retry_of="inv_discov01", reservation={"reservation_id": "rsv_explore001"})
        self.assertEqual(retry["status"], "granted", retry)
        self.reopen()
        self.assertEqual(self.rows("SELECT invocation_id, attempt, retry_invocation_id FROM retries"), [("inv_discov01", 2, "inv_discov02")])
        before = self.state()
        refused = self.claim("inv_checkpt01", "checkpoint", reservation={"reservation_id": "rsv_explore001"})
        self.assertEqual((refused["status"], refused.get("reason")), ("refused", "reservation_exhausted"))  # two units, both drawn before the restarts
        self.assertEqual(self.state(), before)
