"""Station cascade: queue order is priority across stations of different cadence.

Operator design 2026-09-04: a faster station never leapfrogs priority. When it
frees up, it takes the highest-priority non-terminal topic even if a slower
station holds it -- immediately if that station is pausing, at the iteration
boundary (sitting idle meanwhile) if it is mid-flight. The slower station then
moves on to the next topic in order. Cadence itself is a station property.
"""

import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore


class CascadeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self._tmp.name))
        for item_id in ("A", "B", "C"):
            self.store.add(
                title=item_id, cwd=self._tmp.name, command=["true"],
                item_id=item_id, repeat_seconds=0,
            )
        # station-2 pauses 30 min between iterations; station-1 is continuous.
        self.store.configure_worker_agents("station-2", agent_main="codex", interval_seconds=1800)
        self.store.configure_worker_agents("station-1", agent_main="codex", interval_seconds=0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fast_station_takes_over_a_pausing_slower_station_immediately(self):
        # station-2 works A and lands it into its pause.
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "A")
        self.store.mark_scheduled("A", next_eligible_at="2099-01-01T00:00:00Z")
        # station-1 frees up: A is highest priority and its holder is pausing.
        taken = self.store.claim_next(worker="station-1")
        assert taken is not None
        self.assertEqual(taken["id"], "A")
        self.assertEqual(self.store.get("A")["claimed_by"], "station-1")
        # station-2 moves on to the next topic in order, never back to A.
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "B")

    def test_fast_station_reserves_and_idles_when_holder_is_mid_iteration(self):
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "A")  # A running on station-2
        # station-1 must NOT leapfrog to B: it reserves A and sits idle.
        self.assertIsNone(self.store.claim_next(worker="station-1"))
        self.assertEqual(self.store.get("A")["reserved_for"], "station-1")
        self.assertIsNone(self.store.claim_next(worker="station-1"))  # still idle
        # The boundary: station-2's iteration lands -> ownership transfers,
        # A is immediately eligible for station-1 (no inherited pause).
        self.store.mark_scheduled("A", next_eligible_at="2099-01-01T00:00:00Z")
        a = self.store.get("A")
        self.assertEqual(a["claimed_by"], "station-1")
        self.assertIsNone(a["next_eligible_at"])
        self.assertNotIn("reserved_for", a)
        self.assertEqual(self.store.claim_next(worker="station-1")["id"], "A")
        # station-2 goes straight to B.
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "B")

    def test_equal_cadence_stations_do_not_cascade(self):
        self.store.configure_worker_agents("station-2", interval_seconds=0)
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "A")
        # Same speed: no takeover, normal skip to the next unclaimed topic.
        self.assertEqual(self.store.claim_next(worker="station-1")["id"], "B")

    def test_slower_station_never_takes_from_a_faster_one(self):
        self.assertEqual(self.store.claim_next(worker="station-1")["id"], "A")
        self.store.mark_scheduled("A", next_eligible_at="2099-01-01T00:00:00Z")
        # A is pausing on the FAST station; the slow station must skip it.
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "B")
        self.assertEqual(self.store.get("A")["claimed_by"], "station-1")

    def test_stale_reservation_self_heals(self):
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "A")
        self.assertIsNone(self.store.claim_next(worker="station-1"))  # reserved
        # A completes instead of scheduling: the reservation is moot.
        self.store.mark_completed("A", exit_code=0)
        claimed = self.store.claim_next(worker="station-1")
        assert claimed is not None
        self.assertEqual(claimed["id"], "B")
        self.assertNotIn("reserved_for", self.store.get("A"))


if __name__ == "__main__":
    unittest.main()


class MultiStationCascadeTests(unittest.TestCase):
    """Any number of tiers: priority fills from the fastest stations down."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self._tmp.name))
        for item_id in ("A", "B", "C", "D", "E", "F"):
            self.store.add(
                title=item_id, cwd=self._tmp.name, command=["true"],
                item_id=item_id, repeat_seconds=0,
            )
        for n, interval in ((1, 0), (2, 900), (3, 1800)):
            self.store.configure_worker_agents(f"station-{n}", agent_main="codex", interval_seconds=interval)

    def tearDown(self):
        self._tmp.cleanup()

    def test_three_tier_chain_cascade(self):
        # Steady state: A on s1, B on s2, C on s3 -- all pausing.
        self.assertEqual(self.store.claim_next(worker="station-1")["id"], "A")
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "B")
        self.assertEqual(self.store.claim_next(worker="station-3")["id"], "C")
        for i in ("A", "B", "C"):
            self.store.mark_scheduled(i, next_eligible_at="2099-01-01T00:00:00Z")
        # station-1's topic completes; it frees up and takes B off station-2.
        self.store.mark_completed("A", exit_code=0)
        self.assertEqual(self.store.claim_next(worker="station-1")["id"], "B")
        # station-2 is now free: it must take C off the slower station-3, not
        # jump to unclaimed D.
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "C")
        # station-3 takes the first unclaimed topic in order.
        self.assertEqual(self.store.claim_next(worker="station-3")["id"], "D")

    def test_equal_speed_pair_fills_in_order_then_slower_tier(self):
        self.store.configure_worker_agents("station-2", interval_seconds=0)  # s1 == s2
        self.assertEqual(self.store.claim_next(worker="station-1")["id"], "A")
        self.assertEqual(self.store.claim_next(worker="station-2")["id"], "B")
        self.assertEqual(self.store.claim_next(worker="station-3")["id"], "C")
        for i in ("B", "C"):
            self.store.mark_scheduled(i, next_eligible_at="2099-01-01T00:00:00Z")
        # station-1 frees: B is held by an EQUAL station -> skipped; C is held
        # by the slower, pausing station-3 -> cascades to station-1.
        self.store.mark_completed("A", exit_code=0)
        self.assertEqual(self.store.claim_next(worker="station-1")["id"], "C")

    def test_monotonic_cadence_invariant_is_enforced(self):
        with self.assertRaises(QueueError):
            self.store.configure_worker_agents("station-2", interval_seconds=1900)  # slower than station-3
        with self.assertRaises(QueueError):
            self.store.configure_worker_agents("station-3", interval_seconds=100)   # faster than station-2
        self.store.configure_worker_agents("station-3", interval_seconds=3600)  # slower is fine
        with self.assertRaises(QueueError):
            self.store.configure_worker_agents("station-6", interval_seconds=3600)  # cap: 5 for now
        self.store.configure_worker_agents("intake-1", interval_seconds=0)  # other prefix unaffected
