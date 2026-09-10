import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from research_loops.control_store import (
    ControlRevisionConflict,
    ControlScheduler,
    ControlStore,
    ControlValidationError,
    default_configuration,
)
from research_loops.queue import QueueStore
from research_loops.runner import LoopRunner, UsageLedger
from research_loops.workers import start


def configuration():
    config = default_configuration()
    config["active_count"] = 3
    for station in config["stations"]:
        station["primary_profile"] = f"p-{station['id']}"
        station["secondary_profile"] = f"s-{station['id']}"
        station["interval_seconds"] = station["id"] * 100
    return config


def profiles(config):
    ids = {station[key] for station in config["stations"] for key in ("primary_profile", "secondary_profile")}
    return {profile_id: {"adapter": "fake", "model": profile_id, "executable": "fake-agent", "argv": []} for profile_id in ids}


def queue():
    return {"version": 1, "revision": 4, "paused": False, "stopping": False, "items": [{"id": item, "status": "queued", "desired_state": "running"} for item in "ABCD"]}


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        config = configuration()
        self.store = ControlStore.initialize(Path(self.temp.name), configuration=config, queue=queue(), agent_profiles=profiles(config))
        self.scheduler = ControlScheduler(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_active_prefix_and_deterministic_priority(self):
        self.assertEqual(self.scheduler.claim("station-2")["topic_id"], "B")
        self.assertEqual(self.scheduler.claim("station-1")["topic_id"], "A")
        self.assertEqual(self.scheduler.claim("station-3")["topic_id"], "C")
        self.scheduler.update_stations(all_stations=True, active_count=2)
        self.assertIsNone(self.scheduler.claim("station-4"))
        assignments = self.store.snapshot()["work"]["assignments"]
        self.assertTrue(assignments["3"]["draining"])

    def test_group_updates_are_atomic_and_full_chain_validated(self):
        self.scheduler.update_stations(active_count=2)
        self.assertEqual(self.store.snapshot()["configuration"]["active_count"], 2)
        original_intervals = [s["interval_seconds"] for s in self.store.snapshot()["configuration"]["stations"]]
        self.scheduler.update_stations(intervals=original_intervals)
        self.store.register_profile("terra", adapter="fake", model="terra", executable="fake-agent", argv=[])
        result = self.scheduler.update_stations(station_ids=[1, 3], primary_profile="terra")
        self.assertEqual(result["stations"][0]["primary_profile"], "terra")
        self.assertEqual(result["stations"][2]["primary_profile"], "terra")
        with self.assertRaises(ControlValidationError):
            self.scheduler.update_stations(all_stations=True, intervals=[0, 500, 100, 600, 700])
        self.assertEqual(self.store.snapshot()["configuration"]["stations"][2]["interval_seconds"], 300)

    def test_checkpoint_policy_and_interval_chain_commit_together_or_not_at_all(self):
        before = self.store.snapshot()
        policy = before["configuration"]["checkpoints"] | {"every_research_iterations": 17}
        with self.assertRaises(ControlValidationError):
            self.scheduler.update_stations(all_stations=True, intervals=[0, 5, 1, 7, 8], checkpoints=policy)
        self.assertEqual(self.store.snapshot(), before)
        self.scheduler.update_stations(checkpoints=policy)
        self.assertEqual(self.store.snapshot()["configuration"]["checkpoints"]["every_research_iterations"], 17)

    def test_review_hold_preserves_order_and_restores_head_assignment(self):
        first = self.scheduler.claim(1)
        self.assertEqual(first["topic_id"], "A")
        with self.store.transaction() as state:
            state["work"]["topics"]["A"]["review_state"] = "awaiting_operator"
        self.scheduler.finalize(1, first["lease_id"])
        self.assertEqual(self.scheduler.claim(1)["topic_id"], "B")
        with self.store.transaction() as state:
            state["work"]["topics"]["A"]["review_state"] = "eligible"
        # B remains current until its safe boundary; it cannot begin another
        # lease ahead of restored A after finalization.
        current = self.store.snapshot()["work"]["assignments"]["1"]["current"]
        self.scheduler.finalize(1, current["lease_id"])
        self.assertEqual(self.scheduler.claim(1)["topic_id"], "A")

    def test_handoff_clears_pacing_but_not_failure_retry(self):
        lease = self.scheduler.claim(1)
        self.scheduler.finalize(1, lease["lease_id"], pacing_ready_at="2999-01-01T00:00:00Z", retry_not_before="2000-01-01T00:00:00Z")
        with self.store.transaction() as state:
            state["work"]["assignments"]["1"]["handoff_reason"] = "priority_reconciliation"
            state["work"]["assignments"]["1"]["current"] = {**lease, "lease_id": "handoff"}
        self.scheduler.finalize(1, "handoff", pacing_ready_at="2999-01-01T00:00:00Z")
        topic = self.store.snapshot()["work"]["topics"]["A"]
        self.assertNotIn("pacing_ready_at", topic)
        self.assertEqual(topic["retry_not_before"], "2000-01-01T00:00:00Z")

    def test_stale_reorder_is_all_or_nothing(self):
        with self.assertRaises(ControlRevisionConflict):
            self.scheduler.reorder(["D", "C", "B", "A"], expected_queue_revision=3)
        self.assertEqual([item["id"] for item in self.store.snapshot()["queue"]["items"]], list("ABCD"))

    def test_queue_adapter_and_production_finalization_use_managed_lease(self):
        queue_store = QueueStore(self.store.root)
        self.assertIs(queue_store.control.__class__, ControlStore)
        item = queue_store.claim_next(worker="station-1")
        self.assertEqual(item["id"], "A")
        self.assertEqual(item["status"], "running")
        self.assertEqual(item["attempts"], 1)
        queue_store.finalize_run("A", expected_restart_generation=0, requested_control=None, outcome="scheduled", exit_code=0, next_eligible_at="2999-01-01T00:00:00Z")
        self.assertIsNone(self.store.snapshot()["work"]["assignments"]["1"]["current"])

    def test_recovered_managed_research_lease_adopts_live_child_without_new_attempt(self):
        root = self.store.root
        with self.store.transaction() as state:
            for entry in state["queue"]["items"]:
                entry["status"] = "completed"
        store = QueueStore(root)
        item = store.add(title="recover", cwd=str(root), command=[sys.executable, "-c", "import time; time.sleep(.15)"], item_id="recover")
        first = store.claim_next(worker="station-1")
        self.assertFalse(first["resumed"])
        child = subprocess.Popen(item["command"], start_new_session=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        store.mark_pid("recover", child.pid)
        restarted = QueueStore(root)
        recovered = restarted.claim_next(worker="station-1")
        self.assertTrue(recovered["resumed"])
        self.assertEqual(recovered["attempts"], 1)
        outcome = LoopRunner(restarted, UsageLedger(root / "events.jsonl"), worker="station-1", poll_seconds=.02).run_once()
        self.assertEqual(outcome["outcome"], "needs_attention")
        self.assertEqual(restarted.get("recover")["attempts"], 1)

    def test_workers_refuse_managed_count_above_active_prefix(self):
        self.scheduler.update_stations(all_stations=True, active_count=1)
        with self.assertRaisesRegex(Exception, "active_count"):
            start(self.store.root, 2)

    def test_downscale_between_claim_and_spawn_rejects_lease(self):
        lease = self.scheduler.claim(3)
        self.scheduler.update_stations(all_stations=True, active_count=2)
        with self.assertRaises(ControlRevisionConflict):
            self.scheduler.confirm_launch(3, lease["lease_id"])

    def test_reorder_deals_head_to_first_available_station(self):
        # PURE PRIORITY (operator ruling 2026-09-10): nothing waits for a
        # specific station and no station waits for a specific topic.
        a = self.scheduler.claim(1); b = self.scheduler.claim(2)
        self.scheduler.reorder(["B", "A", "C", "D"], expected_queue_revision=4)
        self.scheduler.finalize(1, a["lease_id"])
        # B (the new head) is mid-iteration on station 2 and stays pinned
        # there until its iteration ends; freed station 1 takes the best
        # NON-executing topic instead of idling in reservation.
        self.assertEqual(self.scheduler.claim(1)["topic_id"], "A")
        self.scheduler.finalize(2, b["lease_id"])
        # Back in the pool, the head goes to the first available station.
        self.assertEqual(self.scheduler.claim(2)["topic_id"], "B")

    def test_due_reviews_deal_before_ordinary_research(self):
        # "There shouldn't be any checkpoint queue — they should just be
        # handled" (operator ruling 2026-09-10): a due review is served by
        # the next free station even from deep in the queue.
        with self.store.transaction() as state:
            from research_loops.checkpoints.service import _new_episode
            topic = self.store.ensure_topic_work(state, "D")
            _new_episode(state["work"], topic, ["trigger-review"])
        claim = self.scheduler.claim(1)
        self.assertEqual((claim["topic_id"], claim["execution_kind"]), ("D", "checkpoint"))

    def test_executing_station_resolves_the_claiming_stations_pair(self):
        with self.store.transaction() as state:
            state["configuration"]["checkpoints"]["agent_source"] = "executing_station"
        pair = self.store.resolve_checkpoint_pair(station_id=3)
        self.assertEqual(pair["primary"]["id"], "p-3")
        self.assertEqual(pair["secondary"]["id"], "s-3")
        # Without a station context, station 1 is the representative default.
        display = self.store.effective_checkpoint_profiles()
        self.assertEqual(display["primary_profile"], "p-1")

    def test_station_rest_never_blocks_its_topic_or_lower_stations(self):
        # The interval throttles the SEAT, never the topic: a resting
        # station claims nothing, while the topic it just ran is immediately
        # claimable by any other station in priority order.
        a = self.scheduler.claim(1)
        self.scheduler.finalize(1, a["lease_id"], pacing_ready_at="2999-01-01T00:00:00Z")
        self.assertIsNone(self.scheduler.claim(1))
        self.assertEqual(self.scheduler.claim(2)["topic_id"], a["topic_id"])

    def test_incomplete_dependency_is_not_assignable_but_coverage_blocker_is(self):
        with self.store.transaction() as state:
            state["queue"]["items"][0]["depends_on"] = ["B"]
            state["queue"]["items"][1]["research_blockers"] = [{"key": "blocked"}]
        claim = self.scheduler.claim(1)
        self.assertEqual(claim["topic_id"], "B")
        self.assertEqual(self.store.snapshot()["queue"]["items"][1]["research_blockers"], [{"key": "blocked"}])


if __name__ == "__main__":
    unittest.main()
