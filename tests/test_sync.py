import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore


def definition(item_id, *, title=None, command=None, position_marker=None):
    return {
        "id": item_id,
        "title": title or f"Title {item_id}",
        "cwd": "/tmp",
        "command": command or ["run", item_id],
        "provider": "anthropic-subscription",
        "max_attempts": 5,
    }


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self.tempdir.name))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_sync_preserves_runtime_history_of_existing_items(self):
        self.store.add(
            title="Old title", cwd="/tmp", command=["run", "a"], item_id="a"
        )
        claimed = self.store.claim_next()
        assert claimed is not None
        self.assertEqual(claimed["attempts"], 1)
        self.store.mark_backoff(
            "a",
            exit_code=1,
            error_kind="outage",
            message="503",
            next_eligible_at="2099-01-01T00:00:00Z",
        )
        before = self.store.get("a")

        report = self.store.sync([definition("a", title="New title")])

        self.assertEqual(report["updated"], ["a"])
        after = self.store.get("a")
        self.assertEqual(after["title"], "New title")
        # Runtime history survives untouched.
        self.assertEqual(after["attempts"], 1)
        self.assertEqual(after["consecutive_failures"], 1)
        self.assertEqual(after["status"], "backoff")
        self.assertEqual(after["last_error_kind"], "outage")
        self.assertEqual(after["created_at"], before["created_at"])
        self.assertEqual(after["started_at"], before["started_at"])

    def test_sync_adds_missing_items_and_orders_by_manifest(self):
        self.store.add(title="B", cwd="/tmp", command=["run", "b"], item_id="b")

        report = self.store.sync([definition("a"), definition("b")])

        self.assertEqual(report["added"], ["a"])
        self.assertTrue(report["reordered"])
        self.assertEqual(
            [item["id"] for item in self.store.snapshot()["items"]], ["a", "b"]
        )

    def test_sync_is_idempotent(self):
        manifest = [definition("a"), definition("b")]
        self.store.sync(manifest)
        state_before = self.store.snapshot()

        report = self.store.sync(manifest)

        self.assertEqual(report["added"], [])
        self.assertEqual(report["updated"], [])
        self.assertFalse(report["reordered"])
        self.assertEqual(report["pruned"], [])
        # No state rewrite at all for a no-op sync.
        self.assertEqual(self.store.snapshot()["revision"], state_before["revision"])

    def test_sync_carries_completion_command_as_definition(self):
        command = ["python3", "semantic-state.py", "validate", "."]
        entry = {**definition("a"), "completion_command": command}

        report = self.store.sync([entry])

        self.assertEqual(report["added"], ["a"])
        self.assertEqual(self.store.get("a")["completion_command"], command)

    def test_sync_never_changes_command_of_running_item(self):
        self.store.add(title="A", cwd="/tmp", command=["run", "a"], item_id="a")
        self.store.claim_next()

        report = self.store.sync([definition("a", command=["run", "changed"])])

        self.assertEqual(report["skipped"][0]["id"], "a")
        self.assertEqual(self.store.get("a")["command"], ["run", "a"])
        self.assertEqual(self.store.get("a")["status"], "running")

    def test_sync_prune_removes_absent_non_running_items_only(self):
        self.store.add(title="Gone", cwd="/tmp", command=["run", "gone"], item_id="gone")
        self.store.add(title="Live", cwd="/tmp", command=["run", "live"], item_id="live")
        self.store.claim_next()  # "gone" becomes running -> must not be pruned

        report = self.store.sync([definition("live")], prune=True)

        self.assertEqual(report["pruned"], [])
        self.assertIn(
            "never pruned", [s["reason"] for s in report["skipped"] if s["id"] == "gone"][0]
        )
        # Now with "gone" not running it is pruned.
        self.store.mark_completed("gone", exit_code=0)
        report = self.store.sync([definition("live")], prune=True)
        self.assertEqual(report["pruned"], ["gone"])
        self.assertEqual(
            [item["id"] for item in self.store.snapshot()["items"]], ["live"]
        )

    def test_sync_without_prune_keeps_non_manifest_items_after_manifest_block(self):
        self.store.add(title="Extra", cwd="/tmp", command=["run", "x"], item_id="extra")
        self.store.sync([definition("a")])
        self.assertEqual(
            [item["id"] for item in self.store.snapshot()["items"]], ["a", "extra"]
        )

    def test_sync_rejects_bad_manifests(self):
        with self.assertRaises(QueueError):
            self.store.sync([definition("a"), definition("a")])
        with self.assertRaises(QueueError):
            self.store.sync([{"id": "ok", "title": " ", "cwd": "/tmp", "command": ["x"]}])
        with self.assertRaises(QueueError):
            self.store.sync([{**definition("a"), "max_attempts": 0}])
        with self.assertRaises(QueueError):
            self.store.sync([{**definition("a"), "repeat_seconds": -5}])

    def test_sync_rejects_malformed_commands_cleanly(self):
        # A bare string must not be split into characters.
        with self.assertRaises(QueueError):
            self.store.sync([{**definition("a"), "command": "true"}])
        # Non-list, non-string shapes must raise QueueError, not TypeError.
        for bad in (123, None, [], ["ok", ""], ["ok", 5], [b"x"], "x"):
            with self.subTest(command=bad), self.assertRaises(QueueError):
                self.store.sync([{**definition("a"), "command": bad}])
        # Non-object manifest entries fail cleanly too.
        with self.assertRaises(QueueError):
            self.store.sync(["not-an-object"])  # type: ignore[list-item]

    def test_sync_validates_entire_manifest_before_mutating(self):
        # First entry valid, second malformed: nothing may be applied.
        with self.assertRaises(QueueError):
            self.store.sync([definition("good"), {**definition("bad"), "command": 7}])
        self.assertEqual(self.store.snapshot()["items"], [])

    def test_deferred_command_change_full_workflow(self):
        # A running item's command change is NOT applied by sync, is NOT
        # applied by restart, and IS applied by a rerun of sync once the
        # item is no longer running.
        self.store.add(title="A", cwd="/tmp", command=["old"], item_id="a")
        self.store.claim_next()
        manifest = [definition("a", command=["new"])]

        report = self.store.sync(manifest)
        self.assertIn("NOT changed", report["skipped"][0]["reason"])
        self.assertEqual(self.store.get("a")["command"], ["old"])

        self.store.request_restart("a")
        self.assertEqual(
            self.store.get("a")["command"], ["old"], "restart must not apply manifest"
        )

        # Item leaves running (worker finalized it) -> rerun sync applies it.
        self.store.finalize_run(
            "a",
            expected_restart_generation=self.store.get("a")["restart_generation"],
            requested_control="restarted",
            outcome="restarted",
            exit_code=0,
        )
        report = self.store.sync(manifest)
        self.assertEqual(report["updated"], ["a"])
        self.assertEqual(report["skipped"], [])
        self.assertEqual(self.store.get("a")["command"], ["new"])


if __name__ == "__main__":
    unittest.main()
