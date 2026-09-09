import tempfile
import unittest
from pathlib import Path

from research_loops.control_store import (
    ControlStore,
    ControlStoreError,
    ControlValidationError,
    default_configuration,
)


def configuration():
    result = default_configuration()
    for station in result["stations"]:
        station["primary_profile"] = f"primary-{station['id']}"
        station["secondary_profile"] = f"secondary-{station['id']}"
        station["interval_seconds"] = station["id"] * 10
    result["active_count"] = 3
    return result


def profiles(config):
    ids = {station[key] for station in config["stations"] for key in ("primary_profile", "secondary_profile")}
    return {profile_id: {"adapter": "fake", "model": profile_id, "executable": "fake-agent", "argv": []} for profile_id in ids}


class ControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_opening_unmanaged_root_is_read_only(self):
        store = ControlStore(self.root)
        self.assertFalse(store.exists)
        with self.assertRaises(ControlStoreError):
            store.snapshot()
        self.assertFalse((self.root / "state" / "control.sqlite3").exists())

    def test_one_transaction_commits_all_logical_records_once(self):
        config = configuration(); store = ControlStore.initialize(self.root, configuration=config, agent_profiles=profiles(config))
        with store.transaction(actor="operator", operation_id="op-1", affected_ids=["A"]) as state:
            state["configuration"]["active_count"] = 2
            state["queue"]["items"].append({"id": "A"})
            state["queue"]["revision"] += 1
            ControlStore.ensure_topic_work(state, "A", inventory_version="inventory-1")
        snapshot = store.snapshot()
        self.assertEqual(snapshot["revision"], 1)
        self.assertEqual(snapshot["configuration"]["active_count"], 2)
        self.assertEqual(snapshot["queue"]["items"], [{"id": "A"}])
        self.assertEqual(snapshot["work"]["topics"]["A"]["next_research_ordinal"], 1)

    def test_invalid_group_change_rolls_back_everything(self):
        config = configuration(); store = ControlStore.initialize(self.root, configuration=config, agent_profiles=profiles(config))
        with self.assertRaises(ControlValidationError):
            with store.transaction() as state:
                state["configuration"]["stations"][1]["interval_seconds"] = 1
                state["configuration"]["stations"][2]["primary_profile"] = "changed"
        snapshot = store.snapshot()
        self.assertEqual(snapshot["revision"], 0)
        self.assertEqual(snapshot["configuration"]["stations"][2]["primary_profile"], "primary-3")

    def test_checkpoint_pair_is_inherited_or_explicit(self):
        config = configuration()
        store = ControlStore.initialize(self.root, configuration=config, agent_profiles=profiles(config))
        self.assertEqual(store.effective_checkpoint_profiles(), {"primary_profile": "primary-1", "secondary_profile": "secondary-1"})
        with store.transaction() as state:
            state["work"]["agent_profiles"].update({"review-primary": {"adapter": "fake", "model": "rp", "executable": "fake-agent", "argv": []}, "review-secondary": {"adapter": "fake", "model": "rs", "executable": "fake-agent", "argv": []}})
            state["configuration"]["checkpoints"].update({"agent_source": "explicit", "primary_profile": "review-primary", "secondary_profile": "review-secondary"})
        self.assertEqual(store.effective_checkpoint_profiles(), {"primary_profile": "review-primary", "secondary_profile": "review-secondary"})

    def test_migration_report_never_creates_or_imports(self):
        state = self.root / "state"
        state.mkdir()
        (state / "queue.json").write_text('{"items":[{"id":"legacy"}]}')
        report = ControlStore.migration_report(self.root)
        self.assertEqual(report["legacy_queue"]["items"][0]["id"], "legacy")
        self.assertFalse((state / "control.sqlite3").exists())

    def test_profiles_are_strict_and_resolved_without_fallback(self):
        config = configuration()
        with self.assertRaisesRegex(ControlValidationError, "unregistered"):
            ControlStore.initialize(self.root, configuration=config)
        store = ControlStore.initialize(self.root, configuration=config, agent_profiles=profiles(config))
        pair = store.resolve_station_pair(1)
        self.assertEqual(pair["primary"]["model"], "primary-1")
        with self.assertRaisesRegex(ControlValidationError, "adapter"):
            store.register_profile("bad", adapter="", model="m", executable="run", argv=[])

    def test_boolean_station_id_is_rejected(self):
        config = configuration()
        config["stations"][0]["id"] = True
        with self.assertRaises(ControlValidationError):
            ControlStore.initialize(self.root, configuration=config, agent_profiles=profiles(configuration()))

    def test_explicit_migration_never_uses_attempts_as_count(self):
        state = self.root / "state"
        state.mkdir()
        (state / "queue.json").write_text('{"items":[{"id":"old","attempts":99}]}')
        config = configuration()
        report = ControlStore.apply_legacy_migration(self.root, configuration=config, agent_profiles=profiles(config), baseline_counts={"old": 7})
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["baseline_counts"]["old"], 7)
        self.assertFalse((state / "control.sqlite3").exists())
        ControlStore.apply_legacy_migration(self.root, configuration=config, agent_profiles=profiles(config), baseline_counts={"old": 7}, dry_run=False)
        self.assertEqual(ControlStore(self.root).snapshot()["work"]["topics"]["old"]["research_iterations_completed"], 7)

    def test_migration_overdue_boundary_is_due_without_changing_next_ordinal(self):
        state = self.root / "state"; state.mkdir()
        (state / "queue.json").write_text('{"items":[{"id":"old","completion_lock":"inventory-v1"}]}')
        config = configuration()
        ControlStore.apply_legacy_migration(self.root, configuration=config, agent_profiles=profiles(config), baseline_counts={"old": 41}, dry_run=False)
        topic = ControlStore(self.root).snapshot()["work"]["topics"]["old"]
        self.assertEqual(topic["next_research_ordinal"], 42)
        self.assertEqual(topic["review_state"], "checkpoint_due")
        from research_loops.checkpoints.service import start_checkpoint, reserve_delegate_launch
        control = ControlStore(self.root)
        episode = start_checkpoint(control, episode_id=topic["active_episode_id"], station_id=1, run_id="catch-up-review")
        self.assertEqual(episode["remaining_budgets"]["delegate_launches"], 4)
        reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="catch-up-review", invocation_id="counter", role="counter")
        self.assertEqual(control.snapshot()["work"]["topics"]["old"]["next_research_ordinal"], 42)

    def test_migration_preserves_reviewed_deepening_and_completed_history(self):
        state = self.root / "state"; state.mkdir()
        (state / "queue.json").write_text('{"items":[{"id":"old","deepening_seen":true,"completion_lock":"abc"},{"id":"done","status":"completed","completion_lock":"xyz"}]}')
        config = configuration()
        ControlStore.apply_legacy_migration(self.root, configuration=config, agent_profiles=profiles(config),
            baseline_counts={"old": 3, "done": 50}, checkpoint_history={"old": {"reviewed_inventory_versions": ["abc"]}}, dry_run=False)
        control = ControlStore(self.root)
        from research_loops.checkpoints.service import accept_research_completion
        result = accept_research_completion(control, topic_id="old", run_id="after-migration", station_id=1, inventory_version="abc", accepted=True, deepening_entry=True)
        self.assertIsNone(result["episode_id"])
        done = control.snapshot()["work"]["topics"]["done"]
        self.assertIsNone(done["active_episode_id"])

    def test_deepening_migration_requires_explicit_review_history(self):
        state = self.root / "state"; state.mkdir()
        (state / "queue.json").write_text('{"items":[{"id":"old","deepening_seen":true,"completion_lock":"abc"}]}')
        config = configuration()
        with self.assertRaisesRegex(ControlValidationError, "reviewed inventory"):
            ControlStore.apply_legacy_migration(self.root, configuration=config, agent_profiles=profiles(config), baseline_counts={"old": 3})


if __name__ == "__main__":
    unittest.main()
