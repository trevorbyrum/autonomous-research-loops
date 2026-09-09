"""Queue-side stall guard: independent detection of successful-but-non-converging loops."""

import sys
import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import LoopRunner, UsageLedger


class StallGuardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)
        self.marker = self.root / "ledger-state"
        self.marker.write_text("state-A")

    def tearDown(self):
        self.tempdir.cleanup()

    def _contract_dir(self, name: str) -> Path:
        """A fresh cwd carrying SEMANTIC-STATE.json -- recurrence is
        intrinsic to the contract now (operator ruling 2026-09-09), not a
        repeat_seconds kwarg, so a "recurring" test needs its own dir rather
        than a marker in a shared one."""
        topic_dir = self.root / name
        topic_dir.mkdir()
        (topic_dir / "SEMANTIC-STATE.json").write_text("{}", encoding="utf-8")
        return topic_dir

    def _add_recurring(self, **kwargs):
        return self.store.add(
            title="Recurring loop",
            cwd=str(self._contract_dir("recurring")),
            command=[sys.executable, "-c", "print('iteration ok')"],
            progress_command=["cat", str(self.marker)],
            stall_limit=3,
            **kwargs,
        )

    def _run_and_requeue(self):
        result = self.runner.run_once()
        assert result is not None
        # Make the item immediately eligible again for the next test cycle.
        item_id = result["item_id"]
        with self.store._locked() as state:
            found = self.store._find(state, item_id)
            if found["status"] == "backoff":
                found["status"] = "queued"
                found["next_eligible_at"] = None
        return result

    def test_unchanged_signature_escalates_at_stall_limit(self):
        # Run 1 establishes the baseline signature; runs 2-4 are the three
        # consecutive no-progress runs that trip stall_limit=3.
        item = self._add_recurring()
        outcomes = [self._run_and_requeue()["outcome"] for _ in range(4)]
        self.assertEqual(outcomes[:3], ["scheduled", "scheduled", "scheduled"])
        self.assertEqual(outcomes[3], "needs_attention")
        state_item = self.store.get(item["id"])
        self.assertEqual(state_item["status"], "needs_attention")
        self.assertEqual(state_item["last_error_kind"], "stalled")
        self.assertIn("not converging", state_item["last_error"])
        stall_events = [
            e for e in self.ledger.events() if e["type"] == "stall_guard"
        ]
        self.assertEqual(len(stall_events), 4)
        self.assertTrue(stall_events[-1].get("escalated"))

    def test_changed_signature_resets_the_counter(self):
        item = self._add_recurring()
        self._run_and_requeue()
        self._run_and_requeue()
        self.marker.write_text("state-B")  # qualifying progress happened
        result = self._run_and_requeue()
        self.assertEqual(result["outcome"], "scheduled")
        self.assertEqual(self.store.get(item["id"])["stall_count"], 0)
        # Two more unchanged runs are still below the limit after the reset.
        self.assertEqual(self._run_and_requeue()["outcome"], "scheduled")
        self.assertEqual(self.store.get(item["id"])["stall_count"], 1)

    def test_failed_probe_does_not_accuse(self):
        item = self.store.add(
            title="Probe fails",
            cwd=str(self._contract_dir("probe-fails")),
            command=[sys.executable, "-c", "print('ok')"],
            progress_command=["/nonexistent/probe"],
            stall_limit=2,
        )
        for _ in range(4):
            result = self._run_and_requeue()
            self.assertEqual(result["outcome"], "scheduled")
        self.assertEqual(self.store.get(item["id"])["stall_count"], 0)

    # test_items_without_guard_are_untouched removed: its premise (a
    # RECURRING item with NO stall guard at all, across many reschedule
    # cycles) is now impossible. Recurrence is intrinsic to the contract
    # (SEMANTIC-STATE.json in cwd -- operator ruling 2026-09-09), and any
    # such contract topic gets the chassis default progress probe/guard
    # whether or not it configures its own (DefaultStallGuardTests below) --
    # so a recurring-yet-unguarded item can no longer be constructed. The
    # "stays unguarded" invariant now applies only to a truly generic
    # (non-contract, therefore bounded, single-shot) item, which is exactly
    # what DefaultStallGuardTests.test_generic_item_without_semantic_state_stays_unguarded
    # covers.

    def test_bounded_item_records_but_never_escalates_via_guard(self):
        # completed (non-recurring) items get signature bookkeeping but the
        # guard never flips a completed outcome. Bounded == no
        # SEMANTIC-STATE.json in cwd, so self.root (never marked as a
        # contract dir) is correct here.
        item = self.store.add(
            title="Bounded",
            cwd=str(self.root),
            command=[sys.executable, "-c", "print('ok')"],
            progress_command=["cat", str(self.marker)],
            stall_limit=1,
        )
        result = self.runner.run_once()
        assert result is not None
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(self.store.get(item["id"])["status"], "completed")

    def test_add_validates_stall_limit(self):
        with self.assertRaises(QueueError):
            self.store.add(
                title="Bad", cwd="/tmp", command=["true"], stall_limit=0
            )

    def test_sync_carries_guard_fields(self):
        manifest = [
            {
                "id": "guarded",
                "title": "Guarded",
                "cwd": "/tmp",
                "command": ["true"],
                "progress_command": ["echo", "sig"],
                "stall_limit": 3,
            }
        ]
        report = self.store.sync(manifest)
        self.assertEqual(report["added"], ["guarded"])
        item = self.store.get("guarded")
        self.assertEqual(item["progress_command"], ["echo", "sig"])
        self.assertEqual(item["stall_limit"], 3)
        # Invalid guard fields fail cleanly.
        with self.assertRaises(QueueError):
            self.store.sync(
                [{**manifest[0], "id": "bad", "progress_command": "echo sig"}]
            )
        with self.assertRaises(QueueError):
            self.store.sync([{**manifest[0], "id": "bad2", "stall_limit": 0}])


if __name__ == "__main__":
    unittest.main()


class DefaultStallGuardTests(unittest.TestCase):
    """Liveness detection must not depend on optional per-item configuration.

    With the chassis's first-miss exit-5 retired, a research topic whose item
    configures neither stall_limit nor progress_command would otherwise have
    NO stall detection at all and could loop forever without converging. Such
    topics get the chassis signature probe and DEFAULT_STALL_LIMIT by
    default; generic items with no SEMANTIC-STATE.json keep explicit-config
    behavior (there is no semantic signature to probe)."""

    def setUp(self):
        import shutil

        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "queue"
        self.topic_dir = Path(self.tempdir.name) / "topic"
        example = Path(__file__).resolve().parents[1] / "examples" / "static-site-generator-choice"
        shutil.copytree(example, self.topic_dir)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)

    def tearDown(self):
        self.tempdir.cleanup()

    def _run_and_requeue(self):
        result = self.runner.run_once()
        assert result is not None
        with self.store._locked() as state:
            found = self.store._find(state, result["item_id"])
            if found["status"] == "backoff":
                found["status"] = "queued"
                found["next_eligible_at"] = None
        return result

    def test_unconfigured_research_topic_is_still_guarded(self):
        self.store.add(
            title="unconfigured topic",
            cwd=str(self.topic_dir),
            command=[sys.executable, "-c", "print('no progress made')"],
            item_id="t",
        )
        outcomes = [
            self._run_and_requeue()["outcome"]
            for _ in range(LoopRunner.DEFAULT_STALL_LIMIT + 1)
        ]
        self.assertEqual(
            outcomes[: LoopRunner.DEFAULT_STALL_LIMIT],
            ["scheduled"] * LoopRunner.DEFAULT_STALL_LIMIT,
        )
        self.assertEqual(outcomes[-1], "needs_attention")
        item = self.store.get("t")
        self.assertEqual(item["last_error_kind"], "stalled")
        # Attempts budget untouched by liveness escalation.
        self.assertEqual(item["consecutive_failures"], 0)

    def test_generic_item_without_semantic_state_stays_unguarded(self):
        # A generic item (no SEMANTIC-STATE.json) is bounded by definition
        # now (recurrence is intrinsic to the contract -- operator ruling
        # 2026-09-09), so it can no longer be forced to recur via a
        # repeat_seconds kwarg: it completes on its first success. What's
        # still true, and still worth pinning, is that no default progress
        # probe/stall guard ever touches it.
        cwd = Path(self.tempdir.name) / "generic"
        cwd.mkdir()
        self.store.add(
            title="generic",
            cwd=str(cwd),
            command=[sys.executable, "-c", "print('ok')"],
            item_id="g",
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(
            [e for e in self.ledger.events() if e["type"] == "stall_guard"], []
        )
