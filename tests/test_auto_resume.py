"""A failure taxonomy with no behavior attached is decoration.

Before auto_resume_transient(), a needs_attention park was equally terminal
for every error kind: a 3-hour gateway outage (classified "transient",
correctly) burned the retry budget and parked topics that then waited hours
for a human after the gateway had already recovered. These tests pin the
behavior the kinds now carry: external, self-healing failures re-queue after
a cooldown; configuration/auth/liveness parks wait for an operator; and an
operator's explicit pause always wins.
"""

import sys
import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueStore
from research_loops.runner import LoopRunner, UsageLedger


def _backdate(store: QueueStore, item_id: str, *, seconds: int) -> None:
    from datetime import datetime, timedelta, timezone

    stamp = (
        datetime.now(timezone.utc) - timedelta(seconds=seconds)
    ).isoformat().replace("+00:00", "Z")
    with store._locked() as state:
        store._find(state, item_id)["finished_at"] = stamp


class AutoResumeStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)

    def tearDown(self):
        self.tempdir.cleanup()

    def _park(self, item_id: str, kind: str, *, age_seconds: int = 3600):
        self.store.add(
            title=item_id, cwd=str(self.root), command=["true"], item_id=item_id
        )
        self.store.mark_needs_attention(
            item_id, exit_code=1, error_kind=kind, message=f"parked by {kind}"
        )
        _backdate(self.store, item_id, seconds=age_seconds)

    def test_external_failure_kinds_resume_after_cooldown(self):
        for kind in ("transient", "outage", "rate_limit"):
            with self.subTest(kind=kind):
                self._park(f"item-{kind}", kind)
                resumed = self.store.auto_resume_transient(cooldown_seconds=1800)
                self.assertEqual([i["id"] for i in resumed], [f"item-{kind}"])
                self.assertEqual(resumed[0]["resumed_from_kind"], kind)
                item = self.store.get(f"item-{kind}")
                self.assertEqual(item["status"], "queued")
                self.assertEqual(item["desired_state"], "running")
                self.assertEqual(item["consecutive_failures"], 0)

    def test_operator_owned_kinds_stay_parked(self):
        for kind in ("configuration", "auth", "stalled", "refresh_failed"):
            with self.subTest(kind=kind):
                self._park(f"item-{kind}", kind)
                self.assertEqual(self.store.auto_resume_transient(cooldown_seconds=0), [])
                self.assertEqual(self.store.get(f"item-{kind}")["status"], "needs_attention")

    def test_cooldown_must_elapse_first(self):
        self._park("fresh", "transient", age_seconds=10)
        self.assertEqual(self.store.auto_resume_transient(cooldown_seconds=1800), [])
        self.assertEqual(self.store.get("fresh")["status"], "needs_attention")

    def test_an_operator_pause_always_wins(self):
        # pause_item converts needs_attention -> paused: the operator has
        # looked at it and said "stay down"; auto-resume must never override.
        self._park("held", "transient")
        self.store.pause_item("held", "operator wants this down")
        self.assertEqual(self.store.auto_resume_transient(cooldown_seconds=0), [])
        self.assertEqual(self.store.get("held")["status"], "paused")

    def test_no_resumes_while_queue_is_paused_or_stopping(self):
        self._park("parked", "transient")
        self.store.pause_all(graceful=False)
        self.assertEqual(self.store.auto_resume_transient(cooldown_seconds=0), [])
        self.store.resume_all()
        self.store.pause_all(graceful=True)  # stopping flag
        self.assertEqual(self.store.auto_resume_transient(cooldown_seconds=0), [])

    def test_error_fields_survive_as_the_visible_explanation(self):
        # Unlike an operator resume, auto-resume keeps last_error/-kind: they
        # explain why the item was parked until the next successful run's
        # finalize clears them.
        self._park("explained", "outage")
        self.store.auto_resume_transient(cooldown_seconds=0)
        item = self.store.get("explained")
        self.assertEqual(item["last_error_kind"], "outage")
        self.assertIn("parked by outage", item["last_error"])


class AutoResumeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(
            self.store,
            self.ledger,
            poll_seconds=0.05,
            auto_resume_cooldown_seconds=0,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_resume_is_ledgered_and_the_item_claims_same_tick(self):
        self.store.add(
            title="t",
            cwd=str(self.root),
            command=[sys.executable, "-c", "print('ok')"],
            item_id="t",
        )
        self.store.mark_needs_attention(
            "t", exit_code=1, error_kind="transient", message="gateway down"
        )
        _backdate(self.store, "t", seconds=60)
        result = self.runner.run_once()
        self.assertIsNotNone(result)
        self.assertEqual(result["item_id"], "t")
        self.assertEqual(result["outcome"], "completed")
        events = [e for e in self.ledger.events() if e["type"] == "auto_resume"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["item_id"], "t")
        self.assertEqual(events[0]["resumed_from_kind"], "transient")


if __name__ == "__main__":
    unittest.main()
