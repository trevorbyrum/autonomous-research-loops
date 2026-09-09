"""Stations hold ALL mechanics; the queue is just the queue.

Operator ruling 2026-09-09: station profiles and fleet policy live in the
stations' own collective config (state/stations.json). The queue carries
order, contracts, and topic substance only — no cadence, no agent binding,
no schedule. The fleet's obligations-checkpoint trigger is station
machinery: the worker monitors each topic's iteration history and assigns
the checkpoint; a topic never schedules its own.
"""

import json
import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import LoopRunner, UsageLedger
from research_loops.stations import (
    DEFAULT_CHECKPOINT_EVERY,
    StationsError,
    StationsStore,
)


class StationsStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.state_dir = self.root / "state"

    def tearDown(self):
        self._tmp.cleanup()

    def test_migrates_legacy_worker_agents_out_of_queue_state(self):
        self.state_dir.mkdir(parents=True)
        legacy = {
            "worker-1": {"agent_main": "codex", "interval_seconds": 0},
            "worker-2": {"agent_main": "codex", "interval_seconds": 1800},
            "malformed": "not-a-profile",
        }
        (self.state_dir / "queue.json").write_text(
            json.dumps({"items": [], "worker_agents": legacy})
        )
        stations = StationsStore(self.state_dir)
        self.assertEqual(stations.station("worker-1")["agent_main"], "codex")
        self.assertEqual(stations.interval("worker-2"), 1800)
        self.assertEqual(stations.station("malformed"), {})
        self.assertTrue((self.state_dir / "stations.json").exists())

    def test_queue_strips_its_legacy_copy_after_migration(self):
        store = QueueStore(self.root)
        with store._locked() as state:
            state["worker_agents"] = {"worker-1": {"interval_seconds": 5}}
        # Any later locked access strips the queue-held copy: mechanics have
        # exactly one home.
        with store._locked():
            pass
        raw = json.loads((self.state_dir / "queue.json").read_text())
        self.assertNotIn("worker_agents", raw)

    def test_queue_strips_topic_held_mechanics_fields(self):
        store = QueueStore(self.root)
        item = store.add(title="t", cwd=self._tmp.name, command=["true"])
        with store._locked() as state:
            state["items"][0]["repeat_seconds"] = 900
            state["items"][0]["agent_main"] = "claude"
        with store._locked():
            pass
        current = store.get(item["id"])
        self.assertNotIn("repeat_seconds", current)
        self.assertNotIn("agent_main", current)

    def test_fleet_defaults_and_configure(self):
        stations = StationsStore(self.state_dir)
        fleet = stations.fleet()
        self.assertEqual(fleet["checkpoint_every"], DEFAULT_CHECKPOINT_EVERY)
        self.assertTrue(fleet["checkpoint_on_deepening"])
        stations.configure_fleet(checkpoint_every=10, checkpoint_on_deepening=False)
        fleet = stations.fleet()
        self.assertEqual(fleet["checkpoint_every"], 10)
        self.assertFalse(fleet["checkpoint_on_deepening"])
        with self.assertRaises(StationsError):
            stations.configure_fleet()
        with self.assertRaises(StationsError):
            stations.configure_fleet(checkpoint_every=-1)

    def test_cascade_still_enforced_through_queue_delegate(self):
        store = QueueStore(self.root)
        store.configure_worker_agents("worker-1", interval_seconds=600)
        with self.assertRaises(QueueError):
            store.configure_worker_agents("worker-2", interval_seconds=60)
        store.configure_worker_agents("worker-2", interval_seconds=1800)
        with self.assertRaises(QueueError):
            store.configure_worker_agents("worker-1", interval_seconds=3600)

    def test_snapshot_read_does_not_bump_revision(self):
        stations = StationsStore(self.state_dir)
        stations.configure("worker-1", interval_seconds=0)
        first = stations.snapshot()["revision"]
        second = stations.snapshot()["revision"]
        self.assertEqual(first, second)


class CheckpointTriggerTests(unittest.TestCase):
    """The station assigns checkpoints from topic history + fleet policy."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = QueueStore(self.root)
        self.runner = LoopRunner(
            self.store, UsageLedger(self.root / "state" / "usage.jsonl")
        )
        self.topic_dir = self.root / "topic"
        self.topic_dir.mkdir()
        (self.topic_dir / "SEMANTIC-STATE.json").write_text("{}\n")
        self.item = self.store.add(
            title="topic", cwd=str(self.topic_dir), command=["true"]
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _item(self):
        return self.store.get(self.item["id"])

    def test_not_due_before_cadence(self):
        self.assertIsNone(self.runner._checkpoint_due(self._item()))

    def test_due_on_cadence_and_never_double_fires(self):
        for _ in range(25):
            self.store.record_iteration_accounting(
                self.item["id"], iteration_type="ordinary", deepening=False
            )
        self.assertEqual(self.runner._checkpoint_due(self._item()), "iteration-25")
        # The checkpoint pass pins the ordinal; the trigger disarms until 50.
        self.store.record_iteration_accounting(
            self.item["id"], iteration_type="checkpoint", deepening=False,
            checkpoint_reason="iteration-25",
        )
        item = self._item()
        self.assertEqual(item["iterations_completed"], 25)
        self.assertEqual(item["last_checkpoint_iteration"], 25)
        self.assertIsNone(self.runner._checkpoint_due(item))
        for _ in range(25):
            self.store.record_iteration_accounting(
                self.item["id"], iteration_type="ordinary", deepening=False
            )
        self.assertEqual(self.runner._checkpoint_due(self._item()), "iteration-50")

    def test_deepening_entry_fires_exactly_once(self):
        self.store.record_iteration_accounting(
            self.item["id"], iteration_type="ordinary", deepening=True
        )
        self.assertEqual(self.runner._checkpoint_due(self._item()), "deepening")
        self.store.record_iteration_accounting(
            self.item["id"], iteration_type="checkpoint", deepening=True,
            checkpoint_reason="deepening",
        )
        item = self._item()
        self.assertTrue(item["deepening_checkpoint_done"])
        self.assertIsNone(self.runner._checkpoint_due(item))

    def test_fleet_config_disables_triggers(self):
        self.store.stations.configure_fleet(
            checkpoint_every=0, checkpoint_on_deepening=False
        )
        for _ in range(25):
            self.store.record_iteration_accounting(
                self.item["id"], iteration_type="ordinary", deepening=True
            )
        self.assertIsNone(self.runner._checkpoint_due(self._item()))

    def test_backfilled_history_owes_exactly_one_immediate_checkpoint(self):
        # A legacy topic whose counter is backfilled from its logs (e.g. 137
        # iterations, never checkpointed) is due NOW, not at the next exact
        # multiple of the cadence.
        with self.store._locked() as state:
            state["items"][0]["iterations_completed"] = 137
        self.assertEqual(self.runner._checkpoint_due(self._item()), "iteration-137")
        self.store.record_iteration_accounting(
            self.item["id"], iteration_type="checkpoint", deepening=False,
            checkpoint_reason="iteration-137",
        )
        self.assertIsNone(self.runner._checkpoint_due(self._item()))

    def test_non_contract_items_never_get_checkpoints(self):
        plain_dir = self.root / "plain"
        plain_dir.mkdir()
        plain = self.store.add(title="plain", cwd=str(plain_dir), command=["true"])
        for _ in range(25):
            self.store.record_iteration_accounting(
                plain["id"], iteration_type="ordinary", deepening=False
            )
        self.assertIsNone(self.runner._checkpoint_due(self.store.get(plain["id"])))

    def test_legacy_items_without_history_fields_are_safe(self):
        with self.store._locked() as state:
            for field in (
                "iterations_completed",
                "deepening_seen",
                "last_checkpoint_iteration",
                "deepening_checkpoint_done",
            ):
                state["items"][0].pop(field, None)
        self.assertIsNone(self.runner._checkpoint_due(self._item()))
        self.store.record_iteration_accounting(
            self.item["id"], iteration_type="ordinary", deepening=True
        )
        item = self._item()
        self.assertEqual(item["iterations_completed"], 1)
        self.assertTrue(item["deepening_seen"])


if __name__ == "__main__":
    unittest.main()
