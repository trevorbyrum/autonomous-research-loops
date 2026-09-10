"""2026-09-09 hardening pass: lease-safe failure handling, claim-time run
records, capability revocation/TOCTOU, infra budget refunds, ledger bounds,
and full runtime-map validation."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

from research_loops.access import issue_capability
from research_loops.checkpoints.runner import CheckpointResultError
from research_loops.checkpoints.service import (
    CheckpointError,
    _new_episode,
    _topic,
    accept_research_completion,
    record_delegate_result,
    reserve_delegate_launch,
)
from research_loops.control_store import (
    ControlScheduler,
    ControlStore,
    ControlStoreError,
    ControlValidationError,
    RUNS_RETAINED_PER_TOPIC,
    default_configuration,
)
from research_loops.queue import QueueStore
from research_loops.runner import LoopRunner, UsageLedger


def configuration(active: int = 1):
    result = default_configuration()
    for station in result["stations"]:
        station.update(primary_profile="fake", secondary_profile="fake",
                       interval_seconds=station["id"] * 10)
    result["active_count"] = active
    return result


FAKE_PROFILES = {"fake": {"adapter": "codex", "model": "fake-model", "executable": "fake-agent", "argv": []}}


def research_item(root: Path, topic_id: str = "example") -> dict:
    cwd = root / "topics" / topic_id
    cwd.mkdir(parents=True, exist_ok=True)
    return {"id": topic_id, "title": topic_id, "cwd": str(cwd), "command": ["true"],
            "status": "queued", "desired_state": "running", "lane": "research",
            "completion_lock": "inventory-1", "attempts": 0, "restart_generation": 0}


class HardeningFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.control = ControlStore.initialize(
            self.root, configuration=configuration(), agent_profiles=dict(FAKE_PROFILES),
            queue={"revision": 0, "paused": False, "stopping": False,
                   "items": [research_item(self.root)]})
        self.scheduler = ControlScheduler(self.control)

    def tearDown(self):
        self.temp.cleanup()

    def _checkpoint_lease(self):
        """Arm a due episode and claim its checkpoint lease on station 1."""
        with self.control.transaction() as state:
            topic = self.control.ensure_topic_work(state, "example", inventory_version="inventory-1")
            _new_episode(state["work"], topic, ["trigger-x"])
        lease = self.scheduler.claim(1)
        assert lease and lease["execution_kind"] == "checkpoint", lease
        return lease


class ClaimRunRecordTests(HardeningFixture):
    def test_claim_writes_a_started_run_in_the_same_transaction(self):
        lease = self.scheduler.claim(1)
        run = self.control.snapshot()["work"]["runs"][lease["lease_id"]]
        self.assertEqual(run["state"], "started")
        self.assertEqual(run["topic_id"], "example")
        self.assertNotIn("accounting_result", run)

    def test_completion_finishes_the_started_record_without_replaying(self):
        lease = self.scheduler.claim(1)
        result = accept_research_completion(
            self.control, topic_id="example", run_id=lease["lease_id"], station_id=1,
            inventory_version="inventory-1", accepted=True)
        self.assertEqual(result["ordinal"], 1)
        run = self.control.snapshot()["work"]["runs"][lease["lease_id"]]
        self.assertEqual(run["state"], "finished")
        self.assertEqual(run["started_at"], run["started_at"])  # preserved
        # Idempotent replay returns the recorded result, never a second count.
        replay = accept_research_completion(
            self.control, topic_id="example", run_id=lease["lease_id"], station_id=1,
            inventory_version="inventory-1", accepted=True)
        self.assertEqual(replay, result)
        self.assertEqual(self.control.snapshot()["work"]["topics"]["example"]["research_iterations_completed"], 1)


class CheckpointFailureTests(HardeningFixture):
    def _runner(self, adapter):
        return LoopRunner(QueueStore(self.root), UsageLedger(self.root / "usage.jsonl"),
                          worker="station-1", checkpoint_adapter=adapter)

    def _item(self):
        return copy.deepcopy(self.control.snapshot()["queue"]["items"][0])

    def test_infra_failure_finalizes_lease_and_returns_episode_to_retry_wait(self):
        lease = self._checkpoint_lease()

        def adapter(_context):
            raise ControlStoreError("launch precondition failed (permissions)")

        outcome = self._runner(adapter)._run_managed_checkpoint(self._item(), lease)
        self.assertEqual(outcome["outcome"], "retry_wait")
        state = self.control.snapshot()
        episode = next(iter(state["work"]["episodes"].values()))
        self.assertEqual(episode["state"], "retry_wait")
        self.assertEqual(episode["infra_failure_count"], 1)
        topic = state["work"]["topics"]["example"]
        self.assertEqual(topic["review_state"], "checkpoint_due")
        # Bounded pacing (Astra F4): the topic cannot spin-reclaim instantly.
        self.assertIsInstance(topic.get("retry_not_before"), str)
        self.assertIsNone(state["work"]["assignments"]["1"]["current"])  # lease freed
        self.assertIsNone(self.scheduler.claim(1))  # paced, not immediately reclaimable
        # The claim-time run record is finished, not falsely in-progress.
        run = state["work"]["runs"][lease["lease_id"]]
        self.assertEqual(run["state"], "finished")
        self.assertTrue(run["finalized_without_accounting"])

    def test_persistent_infra_failures_park_needs_attention_after_the_limit(self):
        def adapter(_context):
            raise ControlStoreError("still broken")

        runner = self._runner(adapter)
        for attempt in range(LoopRunner.CHECKPOINT_INFRA_RETRY_LIMIT):
            with self.control.transaction() as state:
                state["work"]["topics"].get("example", {}).pop("retry_not_before", None)
            lease = self.scheduler.claim(1) if attempt else self._checkpoint_lease()
            self.assertIsNotNone(lease, attempt)
            runner._run_managed_checkpoint(self._item(), lease)
        state = self.control.snapshot()
        episode = next(iter(state["work"]["episodes"].values()))
        self.assertEqual(episode["state"], "needs_attention")
        self.assertEqual(state["work"]["topics"]["example"]["review_state"], "needs_attention")

    def test_missing_episode_parks_instead_of_raising_with_a_claimed_lease(self):
        lease = self._checkpoint_lease()
        with self.control.transaction() as state:
            state["work"]["topics"]["example"]["active_episode_id"] = None
        outcome = self._runner(lambda _c: {})._run_managed_checkpoint(self._item(), lease)
        self.assertEqual(outcome["outcome"], "needs_attention")
        self.assertIsNone(self.control.snapshot()["work"]["assignments"]["1"]["current"])

    def test_wrapped_infrastructure_causes_classify_as_infra(self):
        lease = self._checkpoint_lease()

        def adapter(_context):
            # Production adapters wrap provider timeouts as
            # CheckpointResultError (a ValueError); the cause must decide.
            raise CheckpointResultError("checkpoint provider launch failed") from subprocess.TimeoutExpired("codex", 900)

        outcome = self._runner(adapter)._run_managed_checkpoint(self._item(), lease)
        self.assertEqual(outcome["outcome"], "retry_wait")

    def test_unverified_finalize_never_reports_clean_success(self):
        lease = self._checkpoint_lease()

        def adapter(context):
            return {"episode_id": context["episode_id"], "run_id": context["run_id"],
                    "inventory_version": context["inventory_version"],
                    "trigger_ids": context["trigger_ids"], "complete": False,
                    "findings": [], "limitations": ["stub"],
                    "protocol_evidence_refs": [], "proposals": []}

        runner = self._runner(adapter)
        original = self.scheduler.finalize
        from research_loops.control_store import ControlValidationError

        def broken_finalize(*_args, **_kwargs):
            raise ControlValidationError("finalize validation failed")

        self.store_scheduler_patch = runner.store.scheduler.finalize = broken_finalize
        try:
            outcome = runner._run_managed_checkpoint(self._item(), lease)
        finally:
            runner.store.scheduler.finalize = original
        self.assertEqual(outcome["outcome"], "needs_attention")
        self.assertEqual(outcome["exit_code"], 78)
        self.assertIn("finalize_error", outcome)

    def test_semantic_failure_parks_needs_attention_and_still_frees_the_station(self):
        lease = self._checkpoint_lease()

        def adapter(_context):
            raise CheckpointResultError("adapter returned garbage")

        outcome = self._runner(adapter)._run_managed_checkpoint(self._item(), lease)
        self.assertEqual(outcome["outcome"], "needs_attention")
        state = self.control.snapshot()
        self.assertEqual(state["work"]["topics"]["example"]["review_state"], "needs_attention")
        self.assertIsNone(state["work"]["assignments"]["1"]["current"])


class CapabilityLifecycleTests(HardeningFixture):
    def test_finalize_revokes_and_compaction_reclaims_capabilities(self):
        lease = self.scheduler.claim(1)
        token = issue_capability(self.control, topic_id="example",
                                 lease_id=lease["lease_id"], agent_uid=65534)
        self.assertTrue(token)
        self.scheduler.finalize(1, lease["lease_id"])
        # Revoked at finalize, then reclaimed by compaction in the same call.
        self.assertEqual(self.control.snapshot()["work"].get("capabilities", {}), {})

    def test_reserve_rejects_a_revoked_capability_at_spend_time(self):
        lease = self._checkpoint_lease()
        import hashlib
        token = issue_capability(self.control, topic_id="example",
                                 lease_id=lease["lease_id"], agent_uid=65534)
        digest = hashlib.sha256(token.encode()).hexdigest()
        episode_id = self.control.snapshot()["work"]["topics"]["example"]["active_episode_id"]
        from research_loops.checkpoints.service import start_checkpoint
        start_checkpoint(self.control, episode_id=episode_id, station_id=1, run_id=lease["lease_id"])
        with self.control.transaction() as state:
            state["work"]["capabilities"][digest]["revoked"] = True
        with self.assertRaisesRegex(CheckpointError, "revoked"):
            reserve_delegate_launch(self.control, episode_id=episode_id,
                                    lease_id=lease["lease_id"], invocation_id="counter-1",
                                    role="counter", capability_digest=digest)


class InfraRefundTests(HardeningFixture):
    def _running_episode(self):
        lease = self._checkpoint_lease()
        episode_id = self.control.snapshot()["work"]["topics"]["example"]["active_episode_id"]
        from research_loops.checkpoints.service import start_checkpoint
        start_checkpoint(self.control, episode_id=episode_id, station_id=1, run_id=lease["lease_id"])
        return episode_id, lease["lease_id"]

    def _budgets(self, episode_id):
        return self.control.snapshot()["work"]["episodes"][episode_id]["remaining_budgets"]

    def test_infra_failures_refund_up_to_the_cap_semantic_failures_stay_spent(self):
        episode_id, lease_id = self._running_episode()
        self.assertEqual(self._budgets(episode_id)["delegate_launches"], 4)
        self.assertEqual(self._budgets(episode_id)["infra_refunds_remaining"], 2)
        for index, (exit_code, refunded) in enumerate([(124, True), (70, True), (124, False)]):
            reserve_delegate_launch(self.control, episode_id=episode_id, lease_id=lease_id,
                                    invocation_id=f"prep-{index}", role="preparation")
            before = self._budgets(episode_id)["delegate_launches"]
            record = record_delegate_result(self.control, episode_id=episode_id,
                                            invocation_id=f"prep-{index}", exit_code=exit_code)
            after = self._budgets(episode_id)["delegate_launches"]
            self.assertEqual(after, before + (1 if refunded else 0), (index, record))
            self.assertEqual(bool(record.get("infra_refund")), refunded)
        self.assertEqual(self._budgets(episode_id)["infra_refunds_remaining"], 0)
        # Semantic failure (invalid result, exit 78) never refunds.
        reserve_delegate_launch(self.control, episode_id=episode_id, lease_id=lease_id,
                                invocation_id="counter-1", role="counter")
        before = self._budgets(episode_id)["delegate_launches"]
        record_delegate_result(self.control, episode_id=episode_id,
                               invocation_id="counter-1", exit_code=78)
        self.assertEqual(self._budgets(episode_id)["delegate_launches"], before)


class RepairRetryTests(HardeningFixture):
    def test_infra_failed_repair_exchange_is_retryable_semantic_is_not(self):
        lease = self._checkpoint_lease()
        episode_id = self.control.snapshot()["work"]["topics"]["example"]["active_episode_id"]
        from research_loops.checkpoints.service import start_checkpoint
        start_checkpoint(self.control, episode_id=episode_id, station_id=1, run_id=lease["lease_id"])
        reserve_delegate_launch(self.control, episode_id=episode_id, lease_id=lease["lease_id"],
                                invocation_id="counter-1", role="counter")
        record_delegate_result(self.control, episode_id=episode_id, invocation_id="counter-1", exit_code=0)
        reserve_delegate_launch(self.control, episode_id=episode_id, lease_id=lease["lease_id"],
                                invocation_id="repair-1", role="repair_response")
        record_delegate_result(self.control, episode_id=episode_id, invocation_id="repair-1", exit_code=124)
        episode = self.control.snapshot()["work"]["episodes"][episode_id]
        self.assertEqual(episode["remaining_budgets"]["repair_exchanges"], 1)  # restored
        self.assertIsNone(episode.get("repair_phase"))
        # The same uncompleted exchange retries with a fresh id...
        reserve_delegate_launch(self.control, episode_id=episode_id, lease_id=lease["lease_id"],
                                invocation_id="repair-1-retry", role="repair_response")
        # ...and a SEMANTIC failure ends it for good.
        record_delegate_result(self.control, episode_id=episode_id, invocation_id="repair-1-retry", exit_code=78)
        episode = self.control.snapshot()["work"]["episodes"][episode_id]
        self.assertEqual(episode["remaining_budgets"]["repair_exchanges"], 0)
        self.assertEqual(episode["repair_phase"], "response_failed")
        with self.assertRaises(CheckpointError):
            reserve_delegate_launch(self.control, episode_id=episode_id, lease_id=lease["lease_id"],
                                    invocation_id="repair-2", role="repair_response")

    def test_legacy_episode_without_refund_budget_is_backfilled_at_start(self):
        lease = self._checkpoint_lease()
        episode_id = self.control.snapshot()["work"]["topics"]["example"]["active_episode_id"]
        with self.control.transaction() as state:
            state["work"]["episodes"][episode_id]["remaining_budgets"].pop("infra_refunds_remaining")
        from research_loops.checkpoints.service import start_checkpoint
        episode = start_checkpoint(self.control, episode_id=episode_id, station_id=1, run_id=lease["lease_id"])
        self.assertEqual(episode["remaining_budgets"]["infra_refunds_remaining"], 2)


class ClaudeLauncherTests(unittest.TestCase):
    def _launch(self, stdout_body: str):
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            stub = Path(temporary) / "fake-claude"
            stub.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write({stdout_body!r})\n")
            stub.chmod(0o755)
            from research_loops.checkpoints.runner import launch_registered_profile
            profile = {"id": "c", "adapter": "claude", "model": "m", "executable": str(stub), "argv": []}
            return launch_registered_profile(profile, "prompt", cwd=temporary, env=None,
                                             identity=None, timeout_seconds=30)

    def test_malformed_output_is_semantic_78_with_diagnostic(self):
        code, text = self._launch("not json")
        self.assertEqual(code, 78)
        self.assertIn("not json", text)
        code, text = self._launch('{"result": 42}')
        self.assertEqual(code, 78)
        self.assertIn("result", text)

    def test_truly_empty_output_stays_empty_for_infra_classification(self):
        code, text = self._launch("")
        self.assertEqual(code, 0)
        self.assertEqual(text, "")

    def test_valid_result_text_passes_through(self):
        code, text = self._launch('{"result": "{\\"ok\\": true}"}')
        self.assertEqual(code, 0)
        self.assertEqual(text, '{"ok": true}')


class LedgerBoundsTests(HardeningFixture):
    def test_compaction_bounds_runs_and_preserves_started_and_referenced(self):
        with self.control.transaction() as state:
            runs = state["work"]["runs"]
            for index in range(RUNS_RETAINED_PER_TOPIC + 25):
                runs[f"run-{index:04d}"] = {"run_id": f"run-{index:04d}", "topic_id": "example",
                                            "state": "finished", "started_at": f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}Z"}
            runs["run-started"] = {"run_id": "run-started", "topic_id": "example",
                                   "state": "started", "started_at": "2025-01-01T00:00:00Z"}
            removed = self.control.compact(state)
        self.assertGreaterEqual(removed["runs"], 24)
        state = self.control.snapshot()
        runs = state["work"]["runs"]
        self.assertIn("run-started", runs)  # a lost attempt is never silently pruned
        self.assertNotIn("run-0000", runs)
        self.assertGreaterEqual(state["work"]["pruned_runs"]["example"], 24)

    def test_pruned_run_replay_cannot_recount_but_fresh_claims_still_account(self):
        with self.control.transaction() as state:
            state["work"]["runs"]["run-old"] = {"run_id": "run-old", "topic_id": "example",
                                                "state": "finished", "started_at": "2026-01-01T00:00:00Z"}
            state["work"].setdefault("pruned_runs", {})["example"] = 1
            del state["work"]["runs"]["run-old"]
        # Replay of a pruned historical id: no record, no current lease.
        with self.assertRaisesRegex(CheckpointError, "pruned historical"):
            accept_research_completion(self.control, topic_id="example", run_id="run-old",
                                       station_id=1, inventory_version="inventory-1", accepted=True)
        # A genuine fresh claim still accounts normally after pruning.
        lease = self.scheduler.claim(1)
        result = accept_research_completion(self.control, topic_id="example", run_id=lease["lease_id"],
                                            station_id=1, inventory_version="inventory-1", accepted=True)
        self.assertEqual(result["ordinal"], 1)

    def test_finished_record_without_accounting_is_never_recounted(self):
        lease = self.scheduler.claim(1)
        self.scheduler.finalize(1, lease["lease_id"])  # finished, no accounting
        with self.assertRaisesRegex(CheckpointError, "refusing to recount"):
            accept_research_completion(self.control, topic_id="example", run_id=lease["lease_id"],
                                       station_id=1, inventory_version="inventory-1", accepted=True)

    def test_validate_state_rejects_corrupted_runtime_maps(self):
        for name in ("intake_drafts", "decision_publications", "state_operations", "capabilities"):
            with self.assertRaises(ControlValidationError, msg=name):
                with self.control.transaction() as state:
                    state["work"][name] = ["not", "a", "dict"]


class PublicationCleanupTests(unittest.TestCase):
    def test_non_object_json_journal_is_left_untouched_without_raising(self):
        from research_loops.contract_publication import finalize_checkpoint_publication
        with tempfile.TemporaryDirectory() as temporary:
            for body in ("[]", "null"):
                journal = Path(temporary) / "journal.json"
                journal.write_text(body)
                finalize_checkpoint_publication({"publication_journal": str(journal),
                                                 "publication_identity": "A"})
                self.assertTrue(journal.exists(), body)  # never guessed ownership

    def test_pre_upgrade_committed_publication_cleans_its_own_journal(self):
        # A decision committed BEFORE identity-checked cleanup saved results
        # without publication_identity while its journal carries the bundle
        # identity; the intent's prepared record supplies the trusted proof.
        import json as json_module
        from research_loops.checkpoints.service import _publications_for_cleanup
        from research_loops.contract_publication import finalize_checkpoint_publication
        with tempfile.TemporaryDirectory() as temporary:
            journal = Path(temporary) / ".checkpoint-contract-publication.json"
            journal.write_text(json_module.dumps({"identity": "bundle-A", "count": 1}))
            intent = {"prepared": {"identity": "bundle-A", "count": 1},
                      "publications": [{"completion_lock": "lock",
                                        "publication_journal": str(journal)}]}
            enriched = _publications_for_cleanup(intent)
            self.assertEqual(enriched[0]["publication_identity"], "bundle-A")
            finalize_checkpoint_publication(enriched[0])
            self.assertFalse(journal.exists())

    def test_enrichment_never_overrides_a_recorded_identity_or_invents_one(self):
        from research_loops.checkpoints.service import _publications_for_cleanup
        keeps = _publications_for_cleanup({"prepared": {"identity": "other"},
                                           "publications": [{"publication_identity": "own",
                                                             "publication_journal": "x"}]})
        self.assertEqual(keeps[0]["publication_identity"], "own")
        bare = _publications_for_cleanup({"prepared": None,
                                          "publications": [{"publication_journal": "x"}]})
        self.assertNotIn("publication_identity", bare[0])


class SocketPermissionTests(unittest.TestCase):
    def test_audit_sweep_prunes_old_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = ControlStore.initialize(root, configuration=configuration(0),
                                              agent_profiles=dict(FAKE_PROFILES))
            with control.transaction(actor="test") as state:
                state["work"]["topics"]["x"] = dict(topic_id="x", research_iterations_completed=0,
                                                    next_research_ordinal=1, inventory_version=None,
                                                    lifecycle_generation=0, review_state="eligible",
                                                    active_episode_id=None, last_accepted_run_id=None,
                                                    deepening_entries={}, proposal_allowance_remaining=2,
                                                    row_revision=0)
            connection_rows = control.sweep_audit(retention_days=0)
            self.assertGreaterEqual(connection_rows, 1)


if __name__ == "__main__":
    unittest.main()
