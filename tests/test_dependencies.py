import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self.tempdir.name))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_blocked_consumer_does_not_hide_its_later_prerequisite(self):
        self.store.add(
            title="Consumer",
            cwd="/tmp",
            command=["true"],
            item_id="consumer",
            depends_on=["router"],
        )
        self.store.add(
            title="Router",
            cwd="/tmp",
            command=["true"],
            item_id="router",
        )

        claimed = self.store.claim_next(worker="worker-1")

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], "router")

    def test_sync_persists_manifest_dependencies(self):
        manifest = [
            {
                "id": "router",
                "title": "Router",
                "cwd": "/tmp",
                "command": ["true"],
            },
            {
                "id": "consumer",
                "title": "Consumer",
                "cwd": "/tmp",
                "command": ["true"],
                "depends_on": ["router"],
            },
        ]

        self.store.sync(manifest)

        self.assertEqual(self.store.get("consumer")["depends_on"], ["router"])

    def test_sync_rejects_missing_dependencies_before_mutating(self):
        manifest = [
            {
                "id": "consumer",
                "title": "Consumer",
                "cwd": "/tmp",
                "command": ["true"],
                "depends_on": ["missing-router"],
            }
        ]

        with self.assertRaisesRegex(QueueError, "missing-router"):
            self.store.sync(manifest)

        self.assertEqual(self.store.snapshot()["items"], [])

    def test_sync_rejects_dependency_cycles_before_mutating(self):
        manifest = [
            {
                "id": "a",
                "title": "A",
                "cwd": "/tmp",
                "command": ["true"],
                "depends_on": ["b"],
            },
            {
                "id": "b",
                "title": "B",
                "cwd": "/tmp",
                "command": ["true"],
                "depends_on": ["a"],
            },
        ]

        with self.assertRaisesRegex(QueueError, "cycle"):
            self.store.sync(manifest)

        self.assertEqual(self.store.snapshot()["items"], [])

    def test_prior_worker_ownership_cannot_bypass_restarted_prerequisite(self):
        self.store.add(
            title="Router", cwd="/tmp", command=["true"], item_id="router"
        )
        self.store.add(
            title="Consumer",
            cwd="/tmp",
            command=["true"],
            item_id="consumer",
            depends_on=["router"],
        )
        self.store.claim_next(worker="worker-1")
        self.store.mark_completed("router", exit_code=0)
        self.store.claim_next(worker="worker-2")
        self.store.mark_completed("consumer", exit_code=0)
        self.store.request_restart("consumer")
        self.store.request_restart("router")

        claimed = self.store.claim_next(worker="worker-2")

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], "router")

    def test_sync_does_not_change_dependencies_of_running_item(self):
        manifest = [
            {
                "id": "consumer",
                "title": "Consumer",
                "cwd": "/tmp",
                "command": ["true"],
            },
            {
                "id": "router",
                "title": "Router",
                "cwd": "/tmp",
                "command": ["true"],
            },
        ]
        self.store.sync(manifest)
        self.store.claim_next(worker="worker-1")
        manifest[0]["depends_on"] = ["router"]

        report = self.store.sync(manifest)

        self.assertEqual(self.store.get("consumer")["depends_on"], [])
        self.assertIn("dependencies", report["skipped"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
