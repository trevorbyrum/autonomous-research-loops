"""Regression coverage for `research-loops swap-active` / QueueStore.reassign_worker():
move a worker to a specific queued item without killing an in-flight iteration.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import LoopRunner, UsageLedger


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class ReassignWorkerUnitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_nothing_running_claims_target_immediately(self):
        self.store.add(title="A", cwd="/tmp", command=["true"], item_id="a")
        result = self.store.reassign_worker("worker-1", "a")
        self.assertIsNone(result["released"])
        self.assertEqual(result["target"]["claimed_by"], "worker-1")

    def test_refuses_a_target_claimed_by_another_worker(self):
        self.store.add(title="B", cwd="/tmp", command=["true"], item_id="b")
        with self.store._locked() as state:
            self.store._find(state, "b")["claimed_by"] = "worker-2"
        with self.assertRaises(QueueError):
            self.store.reassign_worker("worker-1", "b")

    def test_refuses_a_non_claimable_target(self):
        self.store.add(title="A", cwd="/tmp", command=["true"], item_id="a")
        self.store.pause_item("a", graceful=False)
        with self.assertRaises(QueueError):
            self.store.reassign_worker("worker-1", "a")

    def test_reassigning_to_the_same_target_a_worker_already_owns_is_a_noop_release(self):
        # Not claimed by anyone yet, so it's the "nothing running" path --
        # just confirms this doesn't crash on the self-reference edge case.
        self.store.add(title="A", cwd="/tmp", command=["true"], item_id="a")
        result = self.store.reassign_worker("worker-1", "a")
        self.assertIsNone(result["released"])


class ReassignWorkerLiveTests(unittest.TestCase):
    """Real subprocesses -- the in-flight iteration must never be killed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, worker="worker-1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_swap_lets_the_active_iteration_finish_then_releases_it_unpaused(self):
        self.store.add(
            title="Active", cwd="/tmp",
            command=[sys.executable, "-c", "import time; time.sleep(1)"],
            item_id="active", repeat_seconds=900,
        )
        self.store.add(title="Target", cwd="/tmp", command=["true"], item_id="target")

        thread = threading.Thread(target=self.runner.run_once)
        thread.start()
        deadline = time.time() + 5
        while time.time() < deadline and not self.store.get("active")["last_pid"]:
            time.sleep(0.02)
        pid = self.store.get("active")["last_pid"]
        self.assertTrue(_is_alive(pid))

        result = self.store.reassign_worker("worker-1", "target")
        self.assertEqual(result["released"]["id"], "active")
        self.assertEqual(result["target"]["claimed_by"], "worker-1")

        time.sleep(0.3)
        self.assertTrue(_is_alive(pid), "swap must not kill the in-flight iteration")

        thread.join(timeout=10)
        released = self.store.get("active")
        self.assertEqual(released["status"], "backoff")  # a real, successful "scheduled" landing
        self.assertIsNone(released["claimed_by"])
        self.assertEqual(released["desired_state"], "running")  # still normally schedulable

        claimed = self.store.claim_next(worker="worker-1")
        self.assertEqual(claimed["id"], "target")

    def test_swap_target_stays_claimed_by_another_worker_check_even_mid_release(self):
        self.store.add(
            title="Active", cwd="/tmp",
            command=[sys.executable, "-c", "import time; time.sleep(1)"],
            item_id="active", repeat_seconds=900,
        )
        self.store.add(title="Target", cwd="/tmp", command=["true"], item_id="target")
        with self.store._locked() as state:
            self.store._find(state, "target")["claimed_by"] = "worker-2"

        thread = threading.Thread(target=self.runner.run_once)
        thread.start()
        deadline = time.time() + 5
        while time.time() < deadline and not self.store.get("active")["last_pid"]:
            time.sleep(0.02)

        with self.assertRaises(QueueError):
            self.store.reassign_worker("worker-1", "target")

        thread.join(timeout=10)


if __name__ == "__main__":
    unittest.main()
