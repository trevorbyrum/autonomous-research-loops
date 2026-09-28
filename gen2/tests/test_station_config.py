"""The composition root with a mounted config bundle (task 1d): the router
activates it at start, and the supervisor takes each job's policy from the
bundle that job was admitted under — across a restart onto a newer bundle.

Trace: INVARIANTS G-10, RG-9, C-12; DEPLOYMENT-CONTRACT.md §2 ("in-flight
work keeps the bundle it was admitted under ... a mounted edit applies to
the next admission"; "the engine does not start on an invalid bundle");
gen2/app/station.py; gen2/supervisor/supervisor.py (Supervisor._policy).

Oracle: behaviour, not the resolved object. The launch budget decides how
many advances a paused topic's admitted job waits before the supervisor
cancels it; the two bundles give it 1 and 4, so the count of waits says
which bundle governed the job.

Structural limits: the job never launches (its topic is paused), so no
executor runs; the other budgets are pinned by the same resolution
(Supervisor._policy), which test_supervisor_* exercise with the station's
own policy.
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
        self.station = self.open(B1)  # the active bundle is still bundle 1: its activation replays
        self.router = self.station.router
        self.assertEqual(self.rows("SELECT version, status FROM config_bundles"), [(1, "active")])
        self.assertEqual(self.rows("SELECT state FROM capability_facts WHERE capability = 'config-bundle' AND superseded_by_fact_id IS NULL"), [("failing",)])
        with self.assertRaises(ValueError):
            open_station(self.root, station_id="station-1", host_id="host-test", clock=self.clock, config_bundle=B1, policy=Policy())


if __name__ == "__main__":
    unittest.main()
