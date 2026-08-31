"""Worker-restart resume behavior: never launch a duplicate of a running item."""

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from research_loops.queue import QueueStore
from research_loops.runner import LoopRunner, UsageLedger


class ResumeAfterWorkerRestartTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)

    def tearDown(self):
        self.tempdir.cleanup()

    def _claim_running_item(self, **add_kwargs):
        item = self.store.add(
            title="Resumable",
            cwd=str(self.root),
            command=[sys.executable, "-c", "import time; time.sleep(60)"],
            **add_kwargs,
        )
        claimed = self.store.claim_next()
        assert claimed is not None and not claimed.get("resumed")
        return item

    def test_dead_recorded_pid_requeues_without_relaunching(self):
        item = self._claim_running_item()
        # Simulate the old worker's child: record a PID that no longer exists.
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.store.mark_pid(item["id"], dead.pid)

        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            result = self.runner.run_once()

        assert result is not None
        self.assertEqual(result["outcome"], "restarted")
        self.assertEqual(self.store.get(item["id"])["status"], "queued")
        events = [e["type"] for e in self.ledger.events()]
        self.assertIn("process_reclaimed", events)

    def test_exhausted_worker_reclaims_accepted_topic_after_dead_pid(self):
        self.store.configure_worker_policy("worker-1", claim_limit=1)
        item = self._claim_running_item(item_id="accepted")
        self.store.add(
            title="new", cwd=str(self.root), command=["true"], item_id="new"
        )
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.store.mark_pid(item["id"], dead.pid)

        restarted_store = QueueStore(self.root)
        restarted_runner = LoopRunner(
            restarted_store, self.ledger, poll_seconds=0.05, worker="worker-1"
        )
        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            result = restarted_runner.run_once()

        assert result is not None
        self.assertEqual(result["outcome"], "restarted")
        reclaimed = restarted_store.claim_next(worker="worker-1")
        assert reclaimed is not None
        self.assertEqual(reclaimed["id"], "accepted")
        self.assertEqual(
            restarted_store.snapshot()["worker_policies"]["worker-1"]["claims_used"],
            1,
        )
        event = next(
            e for e in self.ledger.events() if e["type"] == "process_reclaimed"
        )
        self.assertEqual(event["worker"], "worker-1")
        self.assertIsNone(event["profile"])

    def test_missing_pid_requeues_without_relaunching(self):
        item = self._claim_running_item()
        self.assertIsNone(self.store.get(item["id"])["last_pid"])

        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            result = self.runner.run_once()

        assert result is not None
        self.assertEqual(result["outcome"], "restarted")
        self.assertEqual(self.store.get(item["id"])["status"], "queued")

    def test_live_pid_is_adopted_and_pause_terminates_it(self):
        item = self._claim_running_item()
        orphan = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        self.addCleanup(lambda: orphan.poll() is None and orphan.kill())
        self.store.mark_pid(item["id"], orphan.pid)

        result = {}
        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            thread = threading.Thread(
                target=lambda: result.update(self.runner.run_once() or {})
            )
            thread.start()
            deadline = time.time() + 5
            while time.time() < deadline and not any(
                e["type"] == "process_adopted" for e in self.ledger.events()
            ):
                time.sleep(0.02)
            self.store.pause_item(item["id"], "operator pause during adoption")
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result["outcome"], "paused")
        self.assertEqual(self.store.get(item["id"])["status"], "paused")
        # The adopted orphan was actually terminated.
        orphan.wait(timeout=5)
        self.assertIsNotNone(orphan.poll())

    def test_adopted_process_natural_exit_fails_closed_to_needs_attention(self):
        item = self._claim_running_item()
        orphan = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.3)"],
            start_new_session=True,
        )
        self.store.mark_pid(item["id"], orphan.pid)

        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            result = self.runner.run_once()
        orphan.wait(timeout=5)

        assert result is not None
        self.assertEqual(result["outcome"], "needs_attention")
        state_item = self.store.get(item["id"])
        self.assertEqual(state_item["status"], "needs_attention")
        self.assertIn("adopted process", state_item["last_error"])

    def test_recycled_pid_from_before_claim_is_not_adopted(self):
        # A process that started long before the claim cannot be our child.
        item = self._claim_running_item()
        with self.store._locked() as state:
            found = self.store._find(state, item["id"])
            found["last_pid"] = 1  # init: alive, started at boot, not ours
        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            result = self.runner.run_once()

        assert result is not None
        self.assertEqual(result["outcome"], "restarted")
        self.assertEqual(self.store.get(item["id"])["status"], "queued")

    def test_fingerprint_mismatch_refuses_adoption_of_recycled_pid(self):
        # Recorded fingerprint differs from the live process at that PID:
        # simulates PID reuse by an unrelated process started after the claim.
        item = self._claim_running_item()
        impostor = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        self.addCleanup(lambda: impostor.poll() is None and impostor.kill())
        self.store.mark_pid(
            item["id"],
            impostor.pid,
            fingerprint={
                "boot_id": self.runner._boot_id(),
                "start_ticks": (self.runner._pid_start_ticks(impostor.pid) or 0) + 999,
                "cmdline": ["the-real-child"],
            },
        )

        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            result = self.runner.run_once()

        assert result is not None
        self.assertEqual(result["outcome"], "restarted")
        # The unrelated process must NOT have been signalled.
        self.assertIsNone(impostor.poll())

    def test_matching_fingerprint_allows_adoption(self):
        item = self._claim_running_item()
        orphan = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.3)"],
            start_new_session=True,
        )
        self.store.mark_pid(
            item["id"], orphan.pid, fingerprint=self.runner._fingerprint(orphan.pid)
        )

        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            result = self.runner.run_once()
        orphan.wait(timeout=5)

        assert result is not None
        self.assertEqual(result["outcome"], "needs_attention")
        events = [e["type"] for e in self.ledger.events()]
        self.assertIn("process_adopted", events)
        attributed = [
            e
            for e in self.ledger.events()
            if e["type"] in {"process_adopted", "process_finished"}
        ]
        for event in attributed:
            self.assertEqual(event["worker"], "worker-1")
            self.assertIsNone(event["profile"])

    def test_legacy_state_without_fingerprint_requires_cmdline_match(self):
        # Pre-fingerprint queue state: live PID in the claim window but whose
        # cmdline does not reference the item command must be refused.
        item = self._claim_running_item()
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        self.addCleanup(lambda: unrelated.poll() is None and unrelated.kill())
        with self.store._locked() as state:
            found = self.store._find(state, item["id"])
            found["last_pid"] = unrelated.pid
            found["last_pid_fingerprint"] = None
            found["command"] = ["/nonexistent/loop-entrypoint.sh"]

        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=AssertionError("resume must not launch a new process"),
        ):
            result = self.runner.run_once()

        assert result is not None
        self.assertEqual(result["outcome"], "restarted")
        self.assertIsNone(unrelated.poll(), "unrelated process must not be signalled")

    def test_launch_records_fingerprint(self):
        item = self.store.add(
            title="Fingerprinted",
            cwd=str(self.root),
            command=[sys.executable, "-c", "import time; time.sleep(30)"],
        )
        thread = threading.Thread(target=self.runner.run_once)
        thread.start()
        deadline = time.time() + 5
        fingerprint = None
        while time.time() < deadline:
            state_item = self.store.get(item["id"])
            fingerprint = state_item.get("last_pid_fingerprint")
            if fingerprint:
                break
            time.sleep(0.02)
        self.store.pause_item(item["id"], "stop test child")
        thread.join(timeout=10)

        assert fingerprint is not None
        self.assertIsNotNone(fingerprint["boot_id"])
        self.assertIsNotNone(fingerprint["start_ticks"])
        self.assertTrue(any(sys.executable in p for p in fingerprint["cmdline"]))


if __name__ == "__main__":
    unittest.main()
