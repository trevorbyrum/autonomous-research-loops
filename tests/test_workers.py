import os
import signal
import tempfile
import time
import unittest
from pathlib import Path

from research_loops import workers
from research_loops.queue import QueueError, QueueStore


class WorkersTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        QueueStore(self.root)  # ensure state/ exists, matching real usage

    def tearDown(self):
        # Best-effort cleanup in case a test fails before its own stop() call.
        try:
            workers.stop(self.root)
        except Exception:
            pass
        self._tmp.cleanup()

    def _wait_alive(self, pid: int, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                time.sleep(0.05)
        return False

    def test_start_spawns_the_requested_worker_count(self):
        pids = workers.start(self.root, 2)
        self.assertEqual(set(pids), {"worker-1", "worker-2"})
        for pid in pids.values():
            self.assertTrue(self._wait_alive(pid))
        status = workers.status(self.root)
        self.assertEqual(set(status["running"]), {"worker-1", "worker-2"})

    def test_start_twice_without_stop_is_refused(self):
        workers.start(self.root, 1)
        with self.assertRaises(QueueError):
            workers.start(self.root, 1)

    def test_stop_terminates_every_spawned_worker(self):
        pids = workers.start(self.root, 2)
        for pid in pids.values():
            self._wait_alive(pid)
        result = workers.stop(self.root)
        self.assertCountEqual(result["stopped"], ["worker-1", "worker-2"])
        self.assertEqual(result["not_running"], [])
        # These are real children of THIS test process (Popen creates them even
        # though start() doesn't keep the Popen object) — SIGTERM alone leaves
        # a zombie until reaped, which only matters for a long-lived process
        # like this test; the real CLI exits right after start()/stop(), so
        # orphaned or terminated children get reaped by init instead.
        for pid in pids.values():
            _, exit_status = os.waitpid(pid, 0)
            self.assertTrue(os.WIFSIGNALED(exit_status))
            self.assertEqual(os.WTERMSIG(exit_status), signal.SIGTERM)

    def test_stop_with_nothing_started_is_a_noop(self):
        self.assertEqual(workers.stop(self.root), {"stopped": [], "not_running": []})

    def test_status_omits_workers_that_already_exited(self):
        pids = workers.start(self.root, 1)
        pid = pids["worker-1"]
        self._wait_alive(pid)
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)  # reap before checking -- see test_stop's note on zombies
        status = workers.status(self.root)
        self.assertEqual(status["running"], {})
        # The stale record is still on disk; stop() must tolerate an already-dead pid.
        result = workers.stop(self.root)
        self.assertEqual(result, {"stopped": [], "not_running": ["worker-1"]})

    def test_custom_worker_prefix_is_used_in_names(self):
        pids = workers.start(self.root, 1, worker_prefix="lane-")
        self.assertEqual(set(pids), {"lane-1"})


if __name__ == "__main__":
    unittest.main()
