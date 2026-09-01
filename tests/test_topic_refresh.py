"""Regression coverage for the topic_refresh scheduling mechanism:
QueueStore.due_refreshes()/reopen_for_refresh(), finalize_run()'s
refresh_due_at scheduling, research_loops.refresh.apply_refresh(), and the
`research-loops add --topic-refresh`/`refresh` CLI surface.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import LoopRunner, UsageLedger
from research_loops import refresh as refresh_mod

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class RefreshSchedulingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _complete(self, item_id: str) -> dict:
        self.store.claim_next(worker="worker-1")
        _, item = self.store.finalize_run(
            item_id,
            expected_restart_generation=0,
            requested_control=None,
            outcome="completed",
            exit_code=0,
        )
        return item

    def test_refresh_due_at_is_none_when_off(self):
        self.store.add(title="a", cwd="/tmp", command=["true"], item_id="a")
        item = self._complete("a")
        self.assertIsNone(item["refresh_due_at"])

    def test_refresh_due_at_is_seven_days_out_for_weekly(self):
        self.store.add(
            title="a", cwd="/tmp", command=["true"], item_id="a", topic_refresh="weekly"
        )
        before = datetime.now(timezone.utc)
        item = self._complete("a")
        due = datetime.fromisoformat(item["refresh_due_at"].replace("Z", "+00:00"))
        delta = due - before
        self.assertAlmostEqual(delta.total_seconds(), timedelta(days=7).total_seconds(), delta=5)

    def test_refresh_due_at_is_thirty_days_out_for_monthly(self):
        self.store.add(
            title="a", cwd="/tmp", command=["true"], item_id="a", topic_refresh="monthly"
        )
        before = datetime.now(timezone.utc)
        item = self._complete("a")
        due = datetime.fromisoformat(item["refresh_due_at"].replace("Z", "+00:00"))
        delta = due - before
        self.assertAlmostEqual(delta.total_seconds(), timedelta(days=30).total_seconds(), delta=5)

    def test_add_rejects_an_invalid_schedule_or_mode(self):
        with self.assertRaises(QueueError):
            self.store.add(title="a", cwd="/tmp", command=["true"], item_id="a", topic_refresh="daily")
        with self.assertRaises(QueueError):
            self.store.add(
                title="a", cwd="/tmp", command=["true"], item_id="a", topic_refresh_mode="bogus"
            )

    def test_due_refreshes_filters_by_due_time(self):
        self.store.add(
            title="a", cwd="/tmp", command=["true"], item_id="a", topic_refresh="weekly"
        )
        self._complete("a")
        # Not due yet (refresh_due_at is ~7 days out).
        self.assertEqual(self.store.due_refreshes(), [])

        # Force it into the past directly on disk, bypassing the public API
        # (there's no operator-facing way to backdate a schedule -- this
        # simulates time having passed).
        with self.store._locked() as state:
            item = self.store._find(state, "a")
            item["refresh_due_at"] = _iso(datetime.now(timezone.utc) - timedelta(seconds=1))
        due = self.store.due_refreshes()
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["id"], "a")
        self.assertEqual(due[0]["cwd"], "/tmp")
        self.assertEqual(due[0]["mode"], "continue")

    def test_due_refreshes_ignores_non_completed_items(self):
        self.store.add(
            title="a", cwd="/tmp", command=["true"], item_id="a", topic_refresh="weekly"
        )
        with self.store._locked() as state:
            item = self.store._find(state, "a")
            item["refresh_due_at"] = _iso(datetime.now(timezone.utc) - timedelta(days=1))
        # Still "queued", never completed -- due_refreshes must ignore it.
        self.assertEqual(self.store.due_refreshes(), [])

    def test_reopen_for_refresh_requeues_and_clears_schedule(self):
        self.store.add(
            title="a", cwd="/tmp", command=["true"], item_id="a", topic_refresh="weekly"
        )
        self._complete("a")
        item = self.store.reopen_for_refresh("a")
        self.assertEqual(item["status"], "queued")
        self.assertEqual(item["desired_state"], "running")
        self.assertIsNone(item["claimed_by"])
        self.assertIsNone(item["refresh_due_at"])
        self.assertEqual(item["refresh_count"], 1)

    def test_reopen_for_refresh_refuses_a_non_completed_item(self):
        self.store.add(title="a", cwd="/tmp", command=["true"], item_id="a")
        with self.assertRaises(QueueError):
            self.store.reopen_for_refresh("a")

    def test_configure_topic_can_change_refresh_settings(self):
        self.store.add(title="a", cwd="/tmp", command=["true"], item_id="a")
        item = self.store.configure_topic("a", topic_refresh="monthly", topic_refresh_mode="full")
        self.assertEqual(item["topic_refresh"], "monthly")
        self.assertEqual(item["topic_refresh_mode"], "full")

    def test_a_dependent_item_stays_blocked_while_its_prerequisite_is_mid_refresh(self):
        self.store.add(title="a", cwd="/tmp", command=["true"], item_id="a")
        self.store.add(title="b", cwd="/tmp", command=["true"], item_id="b", depends_on=["a"])
        self._complete("a")
        # Once "a" is completed, "b" is the only eligible item.
        claimed = self.store.claim_next(worker="w1")
        self.assertEqual(claimed["id"], "b")
        # Release "b" back to the unclaimed pool (undo the claim above) so
        # the next check starts from a clean, comparable state.
        with self.store._locked() as state:
            item = self.store._find(state, "b")
            item["status"] = "queued"
            item["claimed_by"] = None

        # Reopen "a" (e.g. a scheduled refresh firing) -- this falls out of
        # dependencies_satisfied() with no new code: it requires the
        # prerequisite's status to literally be "completed".
        with self.store._locked() as state:
            item = self.store._find(state, "a")
            item["status"] = "queued"
            item["desired_state"] = "running"
        claimed_again = self.store.claim_next(worker="w2")
        self.assertEqual(claimed_again["id"], "a")


class ApplyRefreshTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self._tmp.name) / "queue")
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _complete(self, item_id: str) -> dict:
        self.store.claim_next(worker="worker-1")
        _, item = self.store.finalize_run(
            item_id,
            expected_restart_generation=0,
            requested_control=None,
            outcome="completed",
            exit_code=0,
        )
        return item

    def test_apply_refresh_refuses_before_completion(self):
        self.store.add(
            title="a", cwd=str(self.topic_dir), command=["true"], item_id="a",
            topic_refresh="weekly", topic_refresh_mode="light",
        )
        with self.assertRaises(QueueError):
            refresh_mod.apply_refresh(self.store, "a")

    def test_apply_refresh_runs_refresh_policy_and_requeues(self):
        self.store.add(
            title="a", cwd=str(self.topic_dir), command=["true"], item_id="a",
            topic_refresh="weekly", topic_refresh_mode="light",
        )
        self._complete("a")
        obligations_before = len(
            json.loads((self.topic_dir / "SEMANTIC-STATE.json").read_text())["obligations"]
        )
        result = refresh_mod.apply_refresh(self.store, "a")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["refresh_count"], 1)
        obligations_after = len(
            json.loads((self.topic_dir / "SEMANTIC-STATE.json").read_text())["obligations"]
        )
        self.assertEqual(obligations_after, obligations_before + 1)

    def test_apply_refresh_honors_an_explicit_mode_override(self):
        self.store.add(
            title="a", cwd=str(self.topic_dir), command=["true"], item_id="a",
            topic_refresh="weekly", topic_refresh_mode="light",
        )
        self._complete("a")
        state_path = self.topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text())
        for ob in state["obligations"]:
            ob["disposition"] = "supported"
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True))

        refresh_mod.apply_refresh(self.store, "a", mode="full")
        after = json.loads(state_path.read_text())["obligations"]
        self.assertTrue(all(ob["disposition"] == "open" for ob in after))


class RunnerRefreshIntegrationTests(unittest.TestCase):
    """Confirms the refresh mechanism through a real LoopRunner tick, not
    just direct QueueStore calls -- mirrors test_runner_integration.py's
    style of using a trivial real subprocess rather than mocking."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "queue"
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)

    def tearDown(self):
        self._tmp.cleanup()

    def _obligation_count(self) -> int:
        state = json.loads((self.topic_dir / "SEMANTIC-STATE.json").read_text())
        return len(state["obligations"])

    def test_a_real_tick_reopens_a_due_topic_and_it_becomes_claimable_again(self):
        self.store.add(
            title="a",
            cwd=str(self.topic_dir),
            command=[sys.executable, "-c", "pass"],
            item_id="a",
            topic_refresh="weekly",
            topic_refresh_mode="light",
        )
        first = self.runner.run_once()
        self.assertEqual(first["outcome"], "completed")
        before_obligations = self._obligation_count()

        # Simulate the schedule coming due (backdate on disk -- there's no
        # operator-facing way to do this, same technique used elsewhere in
        # this file).
        with self.store._locked() as state:
            item = self.store._find(state, "a")
            item["refresh_due_at"] = _iso(datetime.now(timezone.utc) - timedelta(seconds=1))

        second = self.runner.run_once()
        # _process_due_refreshes() reopened "a" for real (refresh-policy.py
        # ran against the actual topic dir on disk) and claim_next() picked
        # it straight back up within the same tick, running the trivial
        # command again to a fresh completion.
        self.assertEqual(second["outcome"], "completed")
        after_obligations = self._obligation_count()
        self.assertEqual(after_obligations, before_obligations + 1)

        final_item = self.store.get("a")
        self.assertEqual(final_item["status"], "completed")
        self.assertEqual(final_item["refresh_count"], 1)
        self.assertIsNotNone(final_item["refresh_due_at"])


class RefreshCLITests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "queue"
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "research_loops", "--root", str(self.root), *args],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )

    def test_add_topic_refresh_flags_round_trip(self):
        result = self._cli(
            "add", "--title", "t", "--cwd", str(self.topic_dir), "--id", "t1",
            "--topic-refresh", "monthly", "--topic-refresh-mode", "full",
            "--", "true",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        item = json.loads(result.stdout)
        self.assertEqual(item["topic_refresh"], "monthly")
        self.assertEqual(item["topic_refresh_mode"], "full")
        self.assertIsNone(item["refresh_due_at"])
        self.assertEqual(item["refresh_count"], 0)

    def test_add_defaults_topic_refresh_to_off(self):
        result = self._cli(
            "add", "--title", "t", "--cwd", str(self.topic_dir), "--id", "t1", "--", "true"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        item = json.loads(result.stdout)
        self.assertEqual(item["topic_refresh"], "off")

    def test_refresh_cli_refuses_a_non_completed_item(self):
        self._cli("add", "--title", "t", "--cwd", str(self.topic_dir), "--id", "t1", "--", "true")
        result = self._cli("refresh", "t1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not completed", result.stderr)

    def test_refresh_cli_works_even_with_topic_refresh_off(self):
        self._cli(
            "add", "--title", "t", "--cwd", str(self.topic_dir), "--id", "t1",
            "--topic-refresh", "off", "--", "true",
        )
        store = QueueStore(self.root)
        store.claim_next(worker="worker-1")
        store.finalize_run(
            "t1", expected_restart_generation=0, requested_control=None,
            outcome="completed", exit_code=0,
        )
        result = self._cli("refresh", "t1", "--mode", "light")
        self.assertEqual(result.returncode, 0, result.stderr)
        item = json.loads(result.stdout)
        self.assertEqual(item["status"], "queued")
        self.assertEqual(item["refresh_count"], 1)


if __name__ == "__main__":
    unittest.main()
