import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from research_loops.queue import QueueConflict, QueueError, QueueStore


class QueueStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_add_move_and_claim_follow_queue_order(self):
        first = self.store.add(title="First", cwd="/tmp", command=["true"])
        second = self.store.add(title="Second", cwd="/tmp", command=["true"])

        self.store.move(second["id"], 0)
        claimed = self.store.claim_next()

        self.assertEqual(claimed["id"], second["id"])
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["attempts"], 1)
        self.assertEqual(
            [item["id"] for item in self.store.snapshot()["items"]],
            [second["id"], first["id"]],
        )
    def test_pause_resume_restart_and_remove_controls(self):
        item = self.store.add(title="Controlled", cwd="/tmp", command=["sleep", "1"])
        self.store.pause_item(item["id"], "maintenance")
        self.assertIsNone(self.store.claim_next())

        self.store.resume_item(item["id"])
        claimed = self.store.claim_next()
        self.assertEqual(claimed["id"], item["id"])

        restarted = self.store.request_restart(item["id"])
        self.assertEqual(restarted["restart_generation"], 1)
        with self.assertRaises(QueueConflict):
            self.store.remove(item["id"])

        self.store.mark_completed(item["id"], exit_code=0)
        removed = self.store.remove(item["id"])
        self.assertEqual(removed["id"], item["id"])

    def test_resume_after_detected_pause_requeues_finalized_run(self):
        item = self.store.add(title="Pause race", cwd="/tmp", command=["true"])
        claimed = self.store.claim_next()
        self.store.pause_item(item["id"], "brief pause")
        self.store.resume_item(item["id"])

        outcome, finalized = self.store.finalize_run(
            item["id"],
            expected_restart_generation=claimed["restart_generation"],
            requested_control="paused",
            outcome="completed",
            exit_code=0,
        )

        self.assertEqual(outcome, "restarted")
        self.assertEqual(finalized["status"], "queued")
        self.assertEqual(finalized["desired_state"], "running")
        self.assertEqual(self.store.claim_next()["id"], item["id"])

    def test_global_pause_blocks_claims_until_resumed(self):
        self.store.add(title="Blocked", cwd="/tmp", command=["true"])
        self.store.pause_all("quota reserve")
        self.assertIsNone(self.store.claim_next())
        self.store.resume_all()
        self.assertIsNotNone(self.store.claim_next())

    def test_operator_resume_resets_failure_budget(self):
        item = self.store.add(title="Retry", cwd="/tmp", command=["false"])
        self.store.claim_next()
        self.store.mark_needs_attention(
            item["id"], exit_code=1, error_kind="configuration", message="bad config"
        )

        resumed = self.store.resume_item(item["id"])

        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(resumed["consecutive_failures"], 0)
        self.assertIsNone(resumed["last_error"])
        self.assertIsNone(resumed["last_error_kind"])

    def test_empty_claim_does_not_rewrite_state(self):
        before = self.store.snapshot()
        self.assertIsNone(self.store.claim_next())
        after = self.store.snapshot()
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["updated_at"], before["updated_at"])

    def test_initial_queue_creation_does_not_overwrite_concurrent_add(self):
        root = self.root / "initialization-race"
        original_write = QueueStore._write_unlocked
        first_write_entered = threading.Event()
        allow_first_write = threading.Event()

        def delayed_first_write(store, state):
            if threading.current_thread().name == "delayed-initializer":
                first_write_entered.set()
                self.assertTrue(allow_first_write.wait(timeout=5))
            return original_write(store, state)

        created = {}

        def initialize_and_add():
            concurrent_store = QueueStore(root)
            created["item"] = concurrent_store.add(
                title="Preserved", cwd="/tmp", command=["true"]
            )

        first = threading.Thread(
            target=lambda: QueueStore(root), name="delayed-initializer"
        )
        second = threading.Thread(target=initialize_and_add, name="concurrent-initializer")
        with mock.patch.object(QueueStore, "_write_unlocked", delayed_first_write):
            first.start()
            self.assertTrue(first_write_entered.wait(timeout=5))
            second.start()
            threading.Event().wait(0.05)
            allow_first_write.set()
            first.join(timeout=5)
            second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        item = created["item"]
        self.assertEqual(QueueStore(root).get(item["id"])["title"], "Preserved")

    def test_add_rejects_unsafe_item_ids(self):
        for item_id in ("../escape", "nested/item", "nested\\item", ".", "..", "has space"):
            with self.subTest(item_id=item_id), self.assertRaises(QueueError):
                self.store.add(
                    title="Unsafe", cwd="/tmp", command=["true"], item_id=item_id
                )

    def test_add_validates_retry_and_repeat_bounds(self):
        for max_attempts in (0, -1):
            with self.subTest(max_attempts=max_attempts), self.assertRaises(QueueError):
                self.store.add(
                    title="Invalid", cwd="/tmp", command=["true"], max_attempts=max_attempts
                )
        # 0 is legal: continuous cadence (re-eligible the moment an iteration
        # finishes). Only negatives are rejected; None stays "bounded, run once".
        with self.assertRaises(QueueError):
            self.store.add(
                title="Invalid", cwd="/tmp", command=["true"], repeat_seconds=-1
            )
        continuous = self.store.add(
            title="Continuous", cwd="/tmp", command=["true"], repeat_seconds=0
        )
        self.assertEqual(continuous["repeat_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
