"""The composition root with a mounted config bundle (task 1d): the router
activates it at start, and the supervisor takes each job's policy from the
bundle that job was admitted under — across a restart onto a newer bundle,
and across a restart with nothing mounted (the active bundle restored; with
none, no start). Through the station too: a failed job's re-queued retry
runs, a mounted fractional hold window is kept, and a restored bundle
clears the failure a refused one raised (task 1d-repair, Astra 1d review
findings 2-5).

Trace: INVARIANTS G-10, RG-9, C-12, L-6, H-2; DEPLOYMENT-CONTRACT.md §2
("in-flight work keeps the bundle it was admitted under ... a mounted edit
applies to the next admission"; "the engine does not start on an invalid
bundle"; restart preserves configuration pins); gen2/app/station.py;
gen2/supervisor/supervisor.py (Supervisor._policy, WorkOrder).

Oracle: behaviour, not the resolved object. The launch budget decides how
many advances a paused topic's admitted job waits before the supervisor
cancels it; the two bundles give it 1 and 4, so the count of waits says
which bundle governed the job.

Structural limits: in the budget cases the job never launches (its topic
is paused), so no executor runs; the other budgets are pinned by the same
resolution (Supervisor._policy), which test_supervisor_* exercise with the
station's own policy. The scheduling cases run a command that writes no
output, so every execution ends failed (L-9); test_supervisor_requeue has
the committed retries.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from gen2.app.station import StationRefused, open_station
from gen2.core import canonical
from gen2.core.instants import utc_instant_ns
from gen2.supervisor.supervisor import Policy, WorkOrder, supervisor_policy
from gen2.tests import router_fixtures as rf, store_fixtures

B1 = {"bundle_version": "config-bundle/1", "version": 1, "questions": [], "policy": {"supervisor": {"launch_attempts": 1, "lock_wait_s": 5}}}
B2 = {"bundle_version": "config-bundle/1", "version": 2, "questions": [], "policy": {"supervisor": {"launch_attempts": 4, "lock_wait_s": 7}}}


class Stop(Exception):
    pass


class StationWorld(rf.RouterTestCase):
    """The router fixture's world builders, over a station's durable store."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.clock, self.ids, self.faults, self.spool = rf.Clock(), rf.Ids(), {}, None
        self.station = self.open(B1, create=True)
        self.router = self.station.router
        self.db = sqlite3.connect(self.root / "store.sqlite3", isolation_level=None)
        self.db.executescript(store_fixtures.CONNECTION_TEXT)
        for tid in (rf.TOPIC, rf.OTHER):
            self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)",
                   tid, "2026-09-27T09:00:00Z", "2026-09-27T09:00:00Z")
        self.to_queued()

    def tearDown(self) -> None:
        self.station.close()
        self.db.close()
        self._tmp.cleanup()

    def open(self, bundle: dict, **options):
        return open_station(self.root, station_id="station-1", host_id="host-test", clock=self.clock, config_bundle=bundle, **options)

    def reopen(self, bundle: dict, **options) -> None:
        self.station.close()
        self.station = self.open(bundle, **options)
        self.router = self.station.router

    def order(self, inv: str, bundle: dict) -> WorkOrder:
        return WorkOrder(invocation_id=inv, kind="discovery", topic_id=rf.TOPIC, config_bundle_hash=canonical.logical_hash(bundle),
                         deadline_at=rf.DEADLINE, lease_expires_at=rf.DEADLINE, command=(sys.executable, "-c", "pass"))


class PinnedPolicyTest(StationWorld):
    def test_a_job_keeps_its_admitted_bundles_policy_across_a_restart(self) -> None:
        def stop(point: str) -> None:
            if point == "claimed":
                raise Stop(point)
        self.reopen(B1, supervisor_options={"fault": stop})
        with self.assertRaises(Stop):
            self.station.supervisor.submit(self.order("inv_discov01", B1))  # admitted under bundle 1, then the supervisor stops
        self.x("UPDATE queue_entries SET paused_at = ? WHERE topic_id = ?", "2026-09-27T10:00:00Z", rf.TOPIC)
        self.reopen(B2)  # the next start mounts bundle 2
        self.assertEqual(self.rows("SELECT version, status FROM config_bundles ORDER BY version"), [(1, "superseded"), (2, "active")])
        outcomes = [self.station.supervisor.advance("inv_discov01") for _ in range(3)]
        self.assertEqual(outcomes, ["waiting_launch", "cancelled", "cancelled"])  # bundle 1's budget of one launch refusal, not bundle 2's four
        self.assertEqual(self.station.supervisor.policy, replace(Policy(), launch_attempts=4, lock_wait_s=7))  # the station's own is the active bundle's
        self.assertEqual(supervisor_policy(B2), replace(Policy(), launch_attempts=4, lock_wait_s=7))  # every value not named keeps its shipped default

    def test_new_work_pins_the_mounted_bundle(self) -> None:
        self.reopen(B2)
        self.assertEqual(self.station.supervisor.submit(self.order("inv_discov01", B1)), "not_admitted")  # an order pinning a superseded bundle
        self.assertEqual(self.rows("SELECT count(*) FROM invocations"), [(0,)])
        self.station.supervisor.prepare(self.order("inv_discov02", B2))
        self.assertEqual(self.station.supervisor.run("inv_discov02"), "failed")  # admitted and run to its end (an executor writing no output fails, L-9)
        self.assertEqual(self.rows("SELECT config_bundle_hash, failure_class FROM invocations"), [(canonical.logical_hash(B2), "empty_output")])
        with self.assertRaises(KeyError):  # an order pinning no recorded bundle is refused before anything is written
            self.station.supervisor.prepare(self.order("inv_discov03", {**B2, "version": 9}))
        self.assertFalse((self.root / "jobs" / "job-inv_discov03").exists())

    def test_a_bundles_identity_is_the_hash_of_its_whole_document(self) -> None:
        """C-13: the identity the router records, and new work pins, is the
        JCS hash of the whole mounted document, its question registry included."""
        entry = {"question_id": "Q-screen", "version": 1, "text": "Does this work meet the pinned eligibility criteria?"}
        carrying = {**B2, "questions": [{**entry, "content_hash": canonical.content_hash(entry)}]}
        self.reopen(carrying)
        self.assertEqual(self.rows("SELECT bundle_hash FROM config_bundles WHERE status = 'active'"), [(canonical.logical_hash(carrying),)])

    def test_the_station_does_not_start_on_a_refused_bundle(self) -> None:
        self.station.close()
        with self.assertRaises(StationRefused):
            self.open({**B1, "policy": {"supervisor": {"launch_attempt": 1}}, "version": 3})
        self.assertEqual(self.rows("SELECT state FROM capability_facts WHERE capability = 'config-bundle' AND superseded_by_fact_id IS NULL"), [("failing",)])
        self.station = self.open(B1)  # the active bundle is still bundle 1: its activation replays, and the capability has recovered
        self.router = self.station.router
        self.assertEqual(self.rows("SELECT version, status FROM config_bundles"), [(1, "active")])
        self.assertEqual(self.rows("SELECT state, superseded_by_fact_id IS NULL FROM capability_facts WHERE capability = 'config-bundle' ORDER BY rowid"),
                         [("failing", 0), ("healthy", 1)])  # the refusal stays history (H-2)
        with self.assertRaises(ValueError):
            open_station(self.root, station_id="station-1", host_id="host-test", clock=self.clock, config_bundle=B1, fixture_policy=Policy())


class StationSchedulingTest(StationWorld):
    """The review's station probes for findings 3 and 4: a failed job's
    re-queued retry runs through the station's supervisor as a new
    execution; the mounted bundle's fractional hold window is the exhaustion
    hold's, exactly."""

    RETRYING = {**B2, "policy": {"supervisor": B2["policy"]["supervisor"],
                                 "router": {"hold_window_s": 0.5, "retry": {"attempts": 1, "failure_classes": ["empty_output"]}}}}

    def test_a_requeued_failure_runs_again_through_the_station(self) -> None:
        self.station.supervisor.prepare(self.order("inv_probe0001", B1))
        self.assertEqual(self.station.supervisor.run("inv_probe0001"), "failed")
        self.assertEqual(self.station.supervisor.submit(self.order("inv_probe0002", B1)), "not_admitted")  # the lane waits for its re-queue
        self.assertEqual(self.router.requeue({"invocation_id": "inv_probe0001", "requested_by": "operator", "reason": "diagnosed"})["status"], "requeued")
        self.station.supervisor.prepare(replace(self.order("inv_probe0003", B1), retry_of="inv_probe0001"))
        self.assertEqual(self.station.supervisor.run("inv_probe0003"), "failed")  # a new execution (this command writes no output, L-9)
        self.assertEqual(self.rows("SELECT invocation_id, state, failure_class FROM invocations ORDER BY admitted_at"),
                         [("inv_probe0001", "failed", "empty_output"), ("inv_probe0003", "failed", "empty_output")])
        self.assertEqual(self.rows("SELECT invocation_id, attempt, retry_invocation_id FROM retries"), [("inv_probe0001", 2, "inv_probe0003")])

    def test_a_mounted_fractional_hold_window_is_kept(self) -> None:
        self.reopen(self.RETRYING)
        self.station.supervisor.prepare(self.order("inv_probe0001", self.RETRYING))
        self.assertEqual(self.station.supervisor.run("inv_probe0001"), "failed")
        self.assertEqual(self.router.requeue({"invocation_id": "inv_probe0001", "requested_by": "policy", "reason": "transient"})["status"], "requeued")
        self.station.supervisor.prepare(replace(self.order("inv_probe0002", self.RETRYING), retry_of="inv_probe0001"))
        self.assertEqual(self.station.supervisor.run("inv_probe0002"), "failed")
        self.assertEqual(self.router.requeue({"invocation_id": "inv_probe0002", "requested_by": "policy", "reason": "transient"})["status"], "exhausted")
        created, deadline = self.rows("SELECT created_at, deadline_at FROM holds")[0]
        self.assertEqual(utc_instant_ns(deadline) - utc_instant_ns(created), 500_000_000)


class RestartPolicyTest(StationWorld):
    """RG-9, G-10 on every start (Astra 1d review finding 2): a restart with
    nothing mounted restores the active bundle and still runs each admitted
    job under the bundle it pins; with nothing to restore the station does
    not start; an injected policy is a named fixture, never a fallback."""

    def admit_and_stop(self, inv: str, bundle: dict) -> None:
        """Admit a job under `bundle`, stop the supervisor right after the
        claim, and pause the topic so every launch request is refused."""
        def stop(point: str) -> None:
            if point == "claimed":
                raise Stop(point)
        self.reopen(bundle, supervisor_options={"fault": stop})
        with self.assertRaises(Stop):
            self.station.supervisor.submit(self.order(inv, bundle))
        self.x("UPDATE queue_entries SET paused_at = ? WHERE topic_id = ?", "2026-09-27T10:00:00Z", rf.TOPIC)

    def restart_unmounted(self, **options) -> None:
        self.station.close()
        self.station = open_station(self.root, station_id="station-1", host_id="host-test", clock=self.clock, **options)
        self.router = self.station.router

    def test_a_restart_with_nothing_mounted_keeps_every_pin(self) -> None:
        self.admit_and_stop("inv_discov01", B1)
        self.reopen(B2)  # bundle 2 becomes the active one
        self.restart_unmounted()
        self.assertEqual(self.station.supervisor.policy, supervisor_policy(B2))  # the station's own: the active bundle, restored
        self.assertEqual([self.station.supervisor.advance("inv_discov01") for _ in range(3)], ["waiting_launch", "cancelled", "cancelled"])  # B1's one refusal
        self.assertEqual(self.rows("SELECT version, status FROM config_bundles ORDER BY version"), [(1, "superseded"), (2, "active")])

    def test_the_reviewers_restart_with_nothing_mounted(self) -> None:
        """The review's probe: admitted under the active B1, restarted with no bundle argument."""
        self.admit_and_stop("inv_discov01", B1)
        self.restart_unmounted()
        self.assertEqual([self.station.supervisor.advance("inv_discov01") for _ in range(3)], ["waiting_launch", "cancelled", "cancelled"])

    def test_fresh_work_after_an_unmounted_restart_pins_the_active_bundle(self) -> None:
        self.reopen(B2)
        self.restart_unmounted()
        self.station.supervisor.prepare(self.order("inv_discov02", B2))
        self.assertEqual(self.station.supervisor.run("inv_discov02"), "failed")  # admitted and run to its end (no output: L-9)
        self.assertEqual(self.rows("SELECT config_bundle_hash FROM invocations"), [(canonical.logical_hash(B2),)])
        self.assertEqual(self.station.supervisor.submit(self.order("inv_discov03", B1)), "not_admitted")  # the superseded bundle admits nothing new

    def test_nothing_mounted_and_nothing_recorded_does_not_start(self) -> None:
        fresh = self.root / "fresh"
        try:
            open_station(fresh, station_id="station-1", host_id="host-test", clock=self.clock, create=True)
            raised = None
        except Exception as refusal:  # whatever it raises is asserted: a station started, or failed otherwise, is this test's failure
            raised = refusal
        self.assertIsInstance(raised, StationRefused)
        self.assertIn("no config bundle is mounted and none is recorded active", str(raised))
        self.assertFalse((fresh / "jobs").exists())  # no supervisor was made
        self.station.close()
        self.station = open_station(fresh, station_id="station-1", host_id="host-test", clock=self.clock, config_bundle=B1)  # mounting one starts it
        self.router = self.station.router
        self.assertEqual(self.station.supervisor.policy, supervisor_policy(B1))

    def test_a_fallback_policy_is_only_a_named_fixture(self) -> None:
        """No production parameter takes a replacement policy; the fixture
        one says what it is, overrides every pin, and takes no mount."""
        self.admit_and_stop("inv_discov01", B1)
        self.station.close()
        with self.assertRaises(TypeError):
            open_station(self.root, station_id="station-1", host_id="host-test", clock=self.clock, policy=Policy())
        self.restart_unmounted(fixture_policy=replace(Policy(), launch_attempts=5))
        self.assertEqual([self.station.supervisor.advance("inv_discov01") for _ in range(4)], ["waiting_launch"] * 4)  # the fixture's five, not B1's one or the shipped three


if __name__ == "__main__":
    unittest.main()
