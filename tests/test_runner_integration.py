import json
import math
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import LoopRunner, UsageLedger


class LoopRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_success_records_usage_and_completes(self):
        usage = self.root / "usage.json"
        payload = {
            "input_tokens": 10,
            "output_tokens": 4,
            "cache_read_tokens": 25,
            "cache_write_tokens": 3,
            "estimated_cost_usd": 0.25,
        }
        command = (
            "import json; from pathlib import Path; "
            f"Path({str(usage)!r}).write_text(json.dumps({payload!r}))"
        )
        item = self.store.add(
            title="Success",
            cwd=str(self.root),
            command=[sys.executable, "-c", command],
            usage_file=str(usage),
            provider="test-provider",
        )

        result = self.runner.run_once()

        self.assertEqual(result["outcome"], "completed")
        state_item = self.store.get(item["id"])
        self.assertEqual(state_item["status"], "completed")
        summary = self.ledger.summary()
        self.assertEqual(summary["input_tokens"], 10)
        self.assertEqual(summary["output_tokens"], 4)
        self.assertEqual(summary["cache_read_input_tokens"], 25)
        self.assertEqual(summary["cache_creation_input_tokens"], 3)
        self.assertEqual(summary["cost_usd"], 0.25)
        provider = summary["by_provider"]["test-provider"]
        self.assertEqual(provider["cache_read_input_tokens"], 25)
        self.assertEqual(provider["cache_creation_input_tokens"], 3)

    def test_repeating_success_is_scheduled_for_next_cadence(self):
        item = self.store.add(
            title="Recurring",
            cwd=str(self.root),
            command=[sys.executable, "-c", "print('iteration complete')"],
            repeat_seconds=900,
        )

        result = self.runner.run_once()

        self.assertEqual(result["outcome"], "scheduled")
        state_item = self.store.get(item["id"])
        self.assertEqual(state_item["status"], "backoff")
        self.assertEqual(state_item["last_error_kind"], None)
        self.assertIsNotNone(state_item["next_eligible_at"])

    def test_outage_enters_backoff_without_spinning(self):
        item = self.store.add(
            title="Outage",
            cwd=str(self.root),
            command=[sys.executable, "-c", "import sys; print('HTTP 503 service unavailable'); sys.exit(1)"],
        )

        result = self.runner.run_once()

        self.assertEqual(result["outcome"], "backoff")
        state_item = self.store.get(item["id"])
        self.assertEqual(state_item["status"], "backoff")
        self.assertEqual(state_item["last_error_kind"], "outage")
        self.assertIsNotNone(state_item["next_eligible_at"])
        self.assertIsNone(self.runner.run_once())

    def test_uncommon_process_startup_oserror_is_finalized(self):
        item = self.store.add(
            title="Bad executable",
            cwd=str(self.root),
            command=["bad-executable"],
        )

        with mock.patch(
            "research_loops.runner.subprocess.Popen",
            side_effect=OSError(8, "Exec format error"),
        ):
            result = self.runner.run_once()

        self.assertEqual(result["outcome"], "needs_attention")
        state_item = self.store.get(item["id"])
        self.assertEqual(state_item["status"], "needs_attention")
        self.assertEqual(state_item["last_error_kind"], "configuration")
        self.assertIsNone(state_item["last_pid"])

    def test_subscription_limit_never_exhausts_attempt_budget(self):
        item = self.store.add(
            title="Quota",
            cwd=str(self.root),
            command=[
                sys.executable,
                "-c",
                "import sys; print('hit your weekly usage limit'); sys.exit(1)",
            ],
            max_attempts=1,
        )

        result = self.runner.run_once()

        self.assertEqual(result["outcome"], "backoff")
        state_item = self.store.get(item["id"])
        self.assertEqual(state_item["status"], "backoff")
        self.assertEqual(state_item["last_error_kind"], "subscription_limit")
        self.assertEqual(state_item["consecutive_failures"], 0)

    def test_subscription_limit_does_not_poison_later_failure_budget(self):
        counter = self.root / "attempt-count"
        script = (
            "from pathlib import Path; import sys; "
            f"p=Path({str(counter)!r}); n=int(p.read_text()) if p.exists() else 0; "
            "p.write_text(str(n+1)); "
            "print('hit your weekly usage limit' if n == 0 else 'HTTP 503 service unavailable'); "
            "sys.exit(1)"
        )
        item = self.store.add(
            title="Quota then outage",
            cwd=str(self.root),
            command=[sys.executable, "-c", script],
            max_attempts=2,
        )

        self.assertEqual(self.runner.run_once()["outcome"], "backoff")
        with self.store._locked() as state:
            queued = self.store._find(state, item["id"])
            queued["status"] = "queued"
            queued["next_eligible_at"] = None
        second = self.runner.run_once()

        self.assertEqual(second["outcome"], "backoff")
        self.assertEqual(self.store.get(item["id"])["consecutive_failures"], 1)

    def test_stale_usage_file_is_not_counted_for_a_failed_run(self):
        usage = self.root / "usage.json"
        usage.write_text(json.dumps({"input_tokens": 999, "output_tokens": 999}))
        self.store.add(
            title="Stale usage",
            cwd=str(self.root),
            command=[sys.executable, "-c", "import sys; print('HTTP 503'); sys.exit(1)"],
            usage_file=str(usage),
        )

        self.runner.run_once()

        summary = self.ledger.summary()
        self.assertEqual(summary["input_tokens"], 0)
        self.assertEqual(summary["output_tokens"], 0)

    def test_pause_terminates_child_and_preserves_restartability(self):
        item = self.store.add(
            title="Long",
            cwd=str(self.root),
            command=[sys.executable, "-c", "import time; time.sleep(30)"],
        )
        result = {}

        thread = threading.Thread(target=lambda: result.update(self.runner.run_once() or {}))
        thread.start()
        deadline = time.time() + 5
        while time.time() < deadline and not self.store.get(item["id"])["last_pid"]:
            time.sleep(0.02)
        self.store.pause_item(item["id"], "operator test")
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result["outcome"], "paused")
        self.assertEqual(self.store.get(item["id"])["status"], "paused")
        self.store.resume_item(item["id"])
        self.assertEqual(self.store.get(item["id"])["status"], "queued")

    def test_global_pause_stops_child_but_global_resume_requeues_it(self):
        item = self.store.add(
            title="Global pause",
            cwd=str(self.root),
            command=[sys.executable, "-c", "import time; time.sleep(30)"],
        )
        result = {}
        thread = threading.Thread(target=lambda: result.update(self.runner.run_once() or {}))
        thread.start()
        deadline = time.time() + 5
        while time.time() < deadline and not self.store.get(item["id"])["last_pid"]:
            time.sleep(0.02)
        self.store.pause_all("maintenance")
        thread.join(timeout=5)

        self.assertEqual(result["outcome"], "global_paused")
        self.assertEqual(self.store.get(item["id"])["status"], "queued")
        self.assertIsNone(self.store.claim_next())
        self.store.resume_all()
        self.assertEqual(self.store.claim_next()["id"], item["id"])

    def _run_with_control_after_final_poll(self, control, *, exit_code):
        item = self.store.add(
            title="Final poll race",
            cwd=str(self.root),
            command=["fake-command"],
        )

        class ProcessFinishingBeforeControlPoll:
            pid = os.getpid()

            def __init__(process_self, *args, stdout, **kwargs):
                process_self.polls = 0
                process_self.control_applied = False
                if exit_code:
                    stdout.write("HTTP 503 service unavailable\n")
                    stdout.flush()

            def poll(process_self):
                process_self.polls += 1
                return None if process_self.polls == 1 else exit_code

            def wait(process_self):
                if not process_self.control_applied:
                    process_self.control_applied = True
                    control(item["id"])
                return exit_code

        with mock.patch("research_loops.runner.subprocess.Popen", ProcessFinishingBeforeControlPoll):
            result = self.runner.run_once()
        return item, result

    def test_restart_after_final_child_poll_prevents_completion(self):
        item, result = self._run_with_control_after_final_poll(
            self.store.request_restart, exit_code=0
        )

        self.assertEqual(result["outcome"], "restarted")
        self.assertEqual(self.store.get(item["id"])["status"], "queued")

    def test_item_pause_after_final_child_poll_prevents_backoff(self):
        item, result = self._run_with_control_after_final_poll(
            lambda item_id: self.store.pause_item(item_id, "race"), exit_code=1
        )

        self.assertEqual(result["outcome"], "paused")
        self.assertEqual(self.store.get(item["id"])["status"], "paused")

    def test_global_pause_after_final_child_poll_prevents_completion(self):
        item, result = self._run_with_control_after_final_poll(
            lambda _item_id: self.store.pause_all("race"), exit_code=0
        )

        self.assertEqual(result["outcome"], "global_paused")
        self.assertEqual(self.store.get(item["id"])["status"], "queued")

    def test_runner_rejects_invalid_poll_interval(self):
        for value in (0, -1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(QueueError):
                LoopRunner(self.store, self.ledger, poll_seconds=value)

    def test_runner_rejects_invalid_idle_sleep(self):
        for value in (0, -1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(QueueError):
                self.runner.run_forever(idle_sleep=value)

    def test_log_path_must_resolve_inside_log_directory(self):
        outside = self.root / "outside.log"
        link = self.runner.log_dir / "safe-attempt-1-stamp.log"
        link.symlink_to(outside)

        with self.assertRaises(QueueError):
            self.runner._log_path("safe", 1, "stamp")


if __name__ == "__main__":
    unittest.main()
