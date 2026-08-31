"""Multi-worker claim semantics: workers never touch each other's items."""

import sys
import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import LoopRunner, UsageLedger


class MultiWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")

    def tearDown(self):
        self.tempdir.cleanup()

    def _add(self, item_id):
        return self.store.add(
            title=item_id, cwd="/tmp", command=["true"], item_id=item_id
        )

    def test_two_workers_claim_distinct_items_in_order(self):
        self._add("a"); self._add("b"); self._add("c")
        one = self.store.claim_next(worker="worker-1")
        two = self.store.claim_next(worker="worker-2")
        assert one is not None and two is not None
        self.assertEqual(one["id"], "a")
        self.assertEqual(two["id"], "b")
        self.assertEqual(one["claimed_by"], "worker-1")
        self.assertEqual(two["claimed_by"], "worker-2")

    def test_three_workers_claim_distinct_items_in_order(self):
        self._add("a"); self._add("b"); self._add("c")
        claimed = [
            self.store.claim_next(worker=f"worker-{slot}") for slot in range(1, 4)
        ]
        self.assertEqual([item["id"] for item in claimed if item], ["a", "b", "c"])

    def test_finite_policy_survives_restart_and_blocks_only_new_topics(self):
        self._add("a"); self._add("b")
        self.store.configure_worker_policy("worker-3", claim_limit=1)
        first = self.store.claim_next(worker="worker-3")
        assert first is not None
        self.store.mark_completed("a", exit_code=0)

        restarted = QueueStore(self.root)
        self.assertIsNone(restarted.claim_next(worker="worker-3"))
        policy = restarted.snapshot()["worker_policies"]["worker-3"]
        self.assertEqual(policy, {"claim_limit": 1, "claims_used": 1})

    def test_continuous_switch_resets_counter_and_accepts_next_topic(self):
        self._add("a"); self._add("b")
        self.store.configure_worker_policy("worker-3", claim_limit=1)
        self.store.claim_next(worker="worker-3")
        self.store.mark_completed("a", exit_code=0)

        policy = self.store.configure_worker_policy("worker-3", claim_limit=None)
        self.assertEqual(policy, {"claim_limit": None, "claims_used": 0})
        second = self.store.claim_next(worker="worker-3")
        assert second is not None
        self.assertEqual(second["id"], "b")

    def test_prior_topic_reacquisition_never_consumes_a_second_claim(self):
        self._add("a"); self._add("b")
        self.store.configure_worker_policy("worker-1", claim_limit=1)
        self.store.configure_worker_policy("worker-2", claim_limit=1)

        self.store.claim_next(worker="worker-1")
        self.store.mark_completed("a", exit_code=0)
        self.store.request_restart("a")
        self.store.claim_next(worker="worker-2")
        self.store.mark_completed("a", exit_code=0)
        self.store.request_restart("a")

        reclaimed = self.store.claim_next(worker="worker-1")
        assert reclaimed is not None
        self.assertEqual(reclaimed["id"], "a")
        self.assertEqual(reclaimed["accepted_by_workers"], ["worker-1", "worker-2"])
        self.assertEqual(
            self.store.snapshot()["worker_policies"]["worker-1"]["claims_used"], 1
        )

    def test_exhausted_worker_reacquires_prior_topic_behind_new_head(self):
        self._add("owned-by-other"); self._add("prior")
        self.store.claim_next(worker="worker-1")
        self.store.configure_worker_policy("worker-3", claim_limit=1)
        self.store.claim_next(worker="worker-3")
        self.store.mark_completed("prior", exit_code=0)
        self.store.request_restart("prior")
        self._add("new-head")
        self.store.move("new-head", 1)

        reclaimed = self.store.claim_next(worker="worker-3")
        assert reclaimed is not None
        self.assertEqual(reclaimed["id"], "prior")

    def test_worker_resumes_only_its_own_running_item(self):
        self._add("a"); self._add("b")
        self.store.claim_next(worker="worker-1")
        # worker-2 must NOT resume worker-1's running item; it claims "b".
        two = self.store.claim_next(worker="worker-2")
        assert two is not None
        self.assertEqual(two["id"], "b")
        self.assertFalse(two.get("resumed"))
        # worker-1 asking again resumes its own.
        again = self.store.claim_next(worker="worker-1")
        assert again is not None
        self.assertEqual(again["id"], "a")
        self.assertTrue(again["resumed"])

    def test_single_worker_upgrade_resumes_legacy_running_item(self):
        # Items claimed before the claimed_by field existed default to worker-1.
        self._add("legacy")
        claimed = self.store.claim_next(worker="worker-1")
        assert claimed is not None
        with self.store._locked() as state:
            del self.store._find(state, "legacy")["claimed_by"]
        resumed = self.store.claim_next(worker="worker-1")
        assert resumed is not None
        self.assertEqual(resumed["id"], "legacy")
        self.assertTrue(resumed["resumed"])
        self.assertEqual(claimed["id"], "legacy")

    def test_no_eligible_items_returns_none_per_worker(self):
        self._add("a")
        self.store.claim_next(worker="worker-1")
        self.assertIsNone(self.store.claim_next(worker="worker-2"))

    def test_runner_carries_worker_identity(self):
        self._add("a")
        runner = LoopRunner(
            self.store, self.ledger, poll_seconds=0.05, worker="worker-2"
        )
        # replace command with a real quick one
        with self.store._locked() as state:
            self.store._find(state, "a")["command"] = [
                sys.executable, "-c", "print('ok')"
            ]
        result = runner.run_once()
        assert result is not None
        self.assertEqual(result["outcome"], "completed")
        # Terminal outcomes release ownership so any worker can act next;
        # the ledger event retains attribution.
        self.assertIsNone(self.store.get("a")["claimed_by"])

    def test_worker_keeps_its_recurring_item_through_cadence(self):
        # A worker's repeating topic in cadence backoff is NOT stolen by
        # another worker, and the owner does not start a second topic.
        self.store.add(
            title="recurring", cwd="/tmp", command=["true"], item_id="r",
            repeat_seconds=900,
        )
        self._add("b")
        one = self.store.claim_next(worker="worker-1")
        assert one is not None and one["id"] == "r"
        self.store.finalize_run(
            "r",
            expected_restart_generation=one["restart_generation"],
            requested_control=None,
            outcome="scheduled",
            exit_code=0,
            next_eligible_at="2099-01-01T00:00:00Z",
        )
        # Owner waits during the cadence gap instead of claiming "b".
        self.assertIsNone(self.store.claim_next(worker="worker-1"))
        # A second worker skips the owned item and takes "b".
        two = self.store.claim_next(worker="worker-2")
        assert two is not None
        self.assertEqual(two["id"], "b")

    def test_exhausted_worker_continues_its_owned_cadence_topic(self):
        self.store.configure_worker_policy("worker-3", claim_limit=1)
        self.store.add(
            title="recurring", cwd="/tmp", command=["true"], item_id="r",
            repeat_seconds=900,
        )
        self._add("next")
        claimed = self.store.claim_next(worker="worker-3")
        assert claimed is not None
        self.store.finalize_run(
            "r",
            expected_restart_generation=claimed["restart_generation"],
            requested_control=None,
            outcome="scheduled",
            exit_code=0,
            next_eligible_at="2000-01-01T00:00:00Z",
        )
        resumed = self.store.claim_next(worker="worker-3")
        assert resumed is not None
        self.assertEqual(resumed["id"], "r")
        self.assertEqual(
            self.store.snapshot()["worker_policies"]["worker-3"]["claims_used"], 1
        )

    def test_malformed_persisted_policy_fails_closed(self):
        self._add("a")
        with self.store._locked() as state:
            state["worker_policies"] = {
                "worker-3": {"claim_limit": 1, "claims_used": True}
            }
        with self.assertRaises(QueueError):
            self.store.claim_next(worker="worker-3")

    def test_null_worker_policies_fails_closed_on_running_resume(self):
        self._add("running")
        self.store.claim_next(worker="worker-3")
        with self.store._locked() as state:
            state["worker_policies"] = None
        with self.assertRaisesRegex(QueueError, "worker_policies must be an object"):
            self.store.claim_next(worker="worker-3")

    def test_null_worker_policies_fails_closed_on_prior_reacquisition(self):
        self._add("prior")
        self.store.claim_next(worker="worker-3")
        self.store.mark_completed("prior", exit_code=0)
        self.store.request_restart("prior")
        with self.store._locked() as state:
            state["worker_policies"] = None
        with self.assertRaisesRegex(QueueError, "worker_policies must be an object"):
            self.store.claim_next(worker="worker-3")

    def test_null_worker_policy_entry_fails_closed(self):
        self._add("new")
        with self.store._locked() as state:
            state["worker_policies"] = {"worker-3": None}
        with self.assertRaisesRegex(QueueError, "worker policy must contain exactly"):
            self.store.claim_next(worker="worker-3")

    def test_worker_never_skips_ahead_of_an_unclaimed_cadence_item(self):
        # Regression (live 2026-08-26): the head item sat in cadence backoff
        # without an owner (legacy pre-claimed_by state) and the worker
        # skipped it to start the SECOND topic. Strict order: wait for the
        # head item, never run ahead of it.
        self.store.add(
            title="head", cwd="/tmp", command=["true"], item_id="head",
            repeat_seconds=900,
        )
        self._add("second")
        one = self.store.claim_next(worker="worker-1")
        assert one is not None and one["id"] == "head"
        self.store.finalize_run(
            "head",
            expected_restart_generation=one["restart_generation"],
            requested_control=None,
            outcome="scheduled",
            exit_code=0,
            next_eligible_at="2099-01-01T00:00:00Z",
        )
        # Simulate legacy state: cadence backoff with no recorded owner.
        with self.store._locked() as state:
            self.store._find(state, "head")["claimed_by"] = None
        self.assertIsNone(
            self.store.claim_next(worker="worker-1"),
            "worker must wait for the unclaimed head item, not skip ahead",
        )
        # Once the head item is eligible again, it is claimed first.
        with self.store._locked() as state:
            self.store._find(state, "head")["next_eligible_at"] = None
        head_again = self.store.claim_next(worker="worker-1")
        assert head_again is not None
        self.assertEqual(head_again["id"], "head")


if __name__ == "__main__":
    unittest.main()
