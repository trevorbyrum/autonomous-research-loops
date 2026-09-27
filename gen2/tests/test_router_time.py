"""Time under the router: exact instants and time spent waiting for the write
lock (task 1b; Astra 1b review A1 and C1).

Trace: INVARIANTS L-7 (the final launch-admission check runs against current
state), C-2/C-3 (a commit is fenced by its lease at commit time); design
review §5 (leases with generations fence every write); gen2/core/control.py
(claim, record_transition, record_observation, commit_outcome).

ExactInstantTest: a fixed, non-ticking clock at one nanosecond before an
expiry or deadline E, at E, and one nanosecond after. A lease or deadline at
E is over at E: only E-1ns is before it. (The fixture clock ticks a
millisecond per reading, so it cannot land on E.)

LockWaitTest: a durable store and two connections. This test's connection
holds the write lock; a second router, with its own connection and a clock
the test sets, is asked to act. Once that router has issued BEGIN IMMEDIATE
(seen through its connection's statement trace — the store is then waiting
for the lock), the clock moves from E-1ns to E and the lock is released. The
lease or the deadline, varied independently with the other left live until
noon, therefore expires while the request waits. The request must be judged
at the time it holds the lock: refused, with every table unchanged. The same
interleaving with the clock left at E-1ns is the positive control.

Oracles: expected outcomes by hand; the store read back with raw SQL.
Structural limits: one interleaving per case, chosen to cross the boundary;
threads in one process; the statement trace is SQLite's report that the
statement began, which here is the wait for the lock.
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gen2.core import canonical
from gen2.router import service
from gen2.store import api
from gen2.tests import router_fixtures as rf
from gen2.tests import router_crash_child  # not its World by name: the loader would collect it

E = "2026-09-27T11:00:00Z"
E_MINUS = "2026-09-27T10:59:59.999999999Z"
E_PLUS = "2026-09-27T11:00:00.000000001Z"
NOON = "2026-09-27T12:00:00Z"


def claim_request(inv: str, *, lease: str = NOON, deadline: str = NOON, kind: str = "checkpoint") -> dict:
    return {"invocation_id": inv, "kind": kind, "topic_id": rf.TOPIC, "station_id": "station-1", "config_bundle_hash": rf.CONFIG,
            "deadline_at": deadline, "lease_expires_at": lease}


def observation_request(grant: dict) -> dict:
    request = {"lane": "crossref", "query": "intake latency", "cursor": None}
    return {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"],
            "observation": {"observation_id": "obs_000000000001", "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1,
                            "lane": "crossref", "obligation_ids": [], "started_at": "2026-09-27T10:30:00Z", "ended_at": "2026-09-27T10:30:01Z",
                            "coverage_state": "searched_ok", "result_count": 1, "completeness": "complete", "error_class": None,
                            "capability_fact_id": None, "policy_version": "gw-policy/1", "cost_units": None, "gateway_call_ref": "call-1"},
            "retrieval_events": [{"event_id": "rev_000000000001", "provider_record_id": "rec-1", "rank": 1, "captured_at": "2026-09-27T10:30:01Z"}]}


def launch_request(grant: dict) -> dict:
    return {"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "to_state": "launching", "job_handle": "job-1"}


class ExactInstantTest(rf.RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.to_queued()

    def at(self, instant: str) -> None:
        self.router = self.make_router(clock=lambda: instant)

    def unchanged(self, out: dict, reason: str, before: dict) -> None:
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        self.assertEqual(self.state(exclude=()), before)

    def test_a_commit_at_its_lease_expiry_is_refused(self) -> None:
        grant = self.started("inv_checkpt01", "checkpoint", lease_expires_at=E)
        env = self.envelope(grant, "op_interim0001", rf.empty_outcome("inv_checkpt01", "interim_transition"))
        before, audits = self.state(), self.value("SELECT count(*) FROM audit_events")
        for instant in (E_PLUS, E):
            with self.subTest(instant):
                self.at(instant)
                out = self.router.commit_outcome(env)
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "lease_not_current"), out)
                self.assertEqual(self.state(), before)
                audits += 1
                self.assertEqual(self.value("SELECT count(*) FROM audit_events"), audits)
        self.at(E_MINUS)
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")

    def test_a_launch_at_its_lease_expiry_is_refused(self) -> None:
        grant = self.claim("inv_checkpt01", "checkpoint", lease_expires_at=E, deadline_at=NOON)
        before = self.state(exclude=())
        for instant in (E_PLUS, E):
            with self.subTest(instant):
                self.at(instant)
                self.unchanged(self.router.record_transition(launch_request(grant)), "lease_not_current", before)
        self.at(E_MINUS)
        self.assertEqual(self.router.record_transition(launch_request(grant))["status"], "recorded")

    def test_a_launch_at_its_deadline_is_refused(self) -> None:
        grant = self.claim("inv_checkpt01", "checkpoint", lease_expires_at=NOON, deadline_at=E)
        before = self.state(exclude=())
        for instant in (E_PLUS, E):
            with self.subTest(instant):
                self.at(instant)
                self.unchanged(self.router.record_transition(launch_request(grant)), "deadline_passed", before)
        self.at(E_MINUS)
        self.assertEqual(self.router.record_transition(launch_request(grant))["status"], "recorded")

    def test_an_observation_at_its_lease_expiry_is_refused(self) -> None:
        grant = self.started("inv_checkpt01", "checkpoint", lease_expires_at=E, deadline_at=NOON)
        before = self.state(exclude=())
        for instant in (E_PLUS, E):
            with self.subTest(instant):
                self.at(instant)
                self.unchanged(self.router.record_observation(observation_request(grant)), "lease_not_current", before)
        self.at(E_MINUS)
        self.assertEqual(self.router.record_observation(observation_request(grant))["status"], "recorded")

    def test_a_claim_whose_lease_or_deadline_is_now_is_refused(self) -> None:
        for field in ("lease", "deadline"):
            before = self.state(exclude=())
            for instant in (E_PLUS, E):
                with self.subTest(field=field, instant=instant):
                    self.at(instant)
                    out = self.router.claim(claim_request(f"inv_{field[:5]}001", **{field: E}))
                    self.unchanged(out, "request_invalid", before)
                    self.assertIn(f"{field}_", out.get("detail", ""))
        self.at(E_MINUS)
        self.assertEqual(self.router.claim(claim_request("inv_lease001", lease=E))["status"], "granted")
        self.assertEqual(self.router.claim(claim_request("inv_deadl001", deadline=E, kind="verification"))["status"], "granted")

    def test_a_lease_is_superseded_at_its_expiry_and_not_before(self) -> None:
        first = self.claim("inv_checkpt01", "checkpoint", lease_expires_at=E, deadline_at=NOON)
        before = self.state(exclude=())
        self.at(E_MINUS)
        self.unchanged(self.router.claim(claim_request("inv_checkpt02")), "lease_held", before)
        self.at(E)
        second = self.router.claim(claim_request("inv_checkpt02"))
        self.assertEqual(second["status"], "granted", second)
        self.assertEqual(self.rows("SELECT released_at, release_reason FROM leases WHERE lease_id = ?", first["lease"]["lease_id"]), [(E, "expired")])


class LockWaitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.world = router_crash_child.World(Path(self.tmp.name))
        self.world.setUp()
        self.world.to_queued()

    def tearDown(self) -> None:
        self.world.router.close()
        self.world.db.close()
        self.tmp.cleanup()

    def waiting(self, operation: str, request: dict, *, cross: bool = True) -> dict:
        """`operation` on a second router while this test's connection holds
        the write lock; the clock crosses E while the router waits for it."""
        clock = {"now": E_MINUS}
        issued = threading.Event()

        def act() -> dict:  # a connection is used on the thread that opened it
            store = api.open_store(self.world.directory / "store.sqlite3")
            store._conn.set_trace_callback(lambda sql: issued.set() if sql == "BEGIN IMMEDIATE" else None)
            router = service.Router(store, self.world.spool, clock=lambda: clock["now"])
            try:
                return getattr(router, operation)(request)
            finally:
                router.close()

        self.world.db.execute("BEGIN IMMEDIATE")
        try:
            with ThreadPoolExecutor(1) as pool:
                pending = pool.submit(act)
                if not issued.wait(10):
                    pending.result(timeout=0)  # an error before the lock is the failure to report
                    self.fail("the router never asked for the write lock")
                if cross:
                    clock["now"] = E
                self.world.db.execute("ROLLBACK")
                return pending.result(timeout=10)
        finally:
            if self.world.db.in_transaction:
                self.world.db.execute("ROLLBACK")

    def refused_across_the_wait(self, operation: str, request: dict, reason: str) -> None:
        before = self.world.state(exclude=())
        out = self.waiting(operation, request)
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        self.assertEqual(self.world.state(exclude=()), before)
        control = self.waiting(operation, request, cross=False)
        self.assertIn(control["status"], ("granted", "recorded"), control)

    def test_a_claim_whose_lease_ends_during_the_wait(self) -> None:
        self.refused_across_the_wait("claim", claim_request("inv_checkpt01", lease=E), "request_invalid")

    def test_a_claim_whose_deadline_passes_during_the_wait(self) -> None:
        self.refused_across_the_wait("claim", claim_request("inv_checkpt01", deadline=E), "request_invalid")

    def test_a_launch_whose_lease_ends_during_the_wait(self) -> None:
        grant = self.world.router.claim(claim_request("inv_checkpt01", lease=E))
        self.refused_across_the_wait("record_transition", launch_request(grant), "lease_not_current")

    def test_a_launch_whose_deadline_passes_during_the_wait(self) -> None:
        grant = self.world.router.claim(claim_request("inv_checkpt01", deadline=E))
        self.refused_across_the_wait("record_transition", launch_request(grant), "deadline_passed")

    def test_an_observation_whose_lease_ends_during_the_wait(self) -> None:
        grant = self.world.started("inv_checkpt01", "checkpoint", lease_expires_at=E, deadline_at=NOON)
        self.refused_across_the_wait("record_observation", observation_request(grant), "lease_not_current")

    def test_a_commit_whose_lease_ends_during_the_wait(self) -> None:
        grant = self.world.started("inv_checkpt01", "checkpoint", lease_expires_at=E, deadline_at=NOON)
        env = self.world.envelope(grant, "op_interim0001", rf.empty_outcome("inv_checkpt01", "interim_transition"))
        before, audits = self.world.state(), self.world.value("SELECT count(*) FROM audit_events")
        out = self.waiting("commit_outcome", env)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "lease_not_current"), out)
        self.assertEqual((self.world.state(), self.world.value("SELECT count(*) FROM audit_events")), (before, audits + 1))
        self.assertEqual(self.waiting("commit_outcome", env, cross=False)["status"], "committed")


if __name__ == "__main__":
    unittest.main()
