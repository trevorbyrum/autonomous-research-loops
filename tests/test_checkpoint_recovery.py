import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_loops.access import AccessError, initialize_access
from research_loops.control_store import ControlStore, default_configuration, default_work
from research_loops.controller import Controller
from research_loops.mcp_server import EngineTools


class CheckpointRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.chmod(0o755)
        config = default_configuration()
        config["active_count"] = 1
        for station in config["stations"]:
            station.update(primary_profile="test", secondary_profile="test")
        work = default_work()
        work["agent_profiles"] = {"test": {"adapter": "generic", "model": "test", "executable": "/bin/true", "argv": []}}
        work["topics"] = {"topic": {"topic_id": "topic", "active_episode_id": "episode", "review_state": "needs_attention",
            "research_iterations_completed": 25, "next_research_ordinal": 26, "proposal_allowance_remaining": 0}}
        work["episodes"] = {"episode": {"episode_id": "episode", "topic_id": "topic", "state": "needs_attention",
            "failure_reason": "counter provider unavailable", "trigger_ids": ["trigger"], "attempt_history": [{"run_id": "old"}],
            "remaining_budgets": {"delegate_launches": 0, "final_proposals": 0, "repair_exchanges": 0}, "invocations": {}}}
        self.control = ControlStore.initialize(self.root, configuration=config, work=work,
            queue={"revision": 7, "paused": False, "stopping": False, "items": [{"id": "topic", "status": "queued", "desired_state": "running"}]})
        initialize_access(self.root, agent_uid=65534 if os.geteuid() != 65534 else 65533,
                          agent_gid=65534 if os.geteuid() != 65534 else 65533,
                          operator_uids=[os.geteuid()], socket_path=str(self.root / "run" / "control.sock"))
        self.controller = Controller(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _payload(self, **changes):
        value = {"schema_version": 1, "request_id": "recover-1", "expected_revision": self.control.snapshot()["revision"],
                 "topic_id": "topic", "episode_id": "episode", "reason": "retry after provider recovery"}
        return value | changes

    def _dispatch(self, payload):
        return self.controller.dispatch({"method": "checkpoint.retry", "params": payload}, peer_uid=os.geteuid(), peer_pid=1)

    def test_retry_is_durable_idempotent_and_preserves_ledger(self):
        before = self.control.snapshot()
        payload = self._payload()
        result = self._dispatch(payload)
        after = self.control.snapshot()
        self.assertEqual(result["state"], "retry_wait")
        self.assertEqual(after["work"]["topics"]["topic"]["review_state"], "checkpoint_due")
        episode = after["work"]["episodes"]["episode"]
        self.assertEqual(episode["state"], "retry_wait")
        self.assertNotIn("failure_reason", episode)
        self.assertEqual(episode["recovery_audit"][0]["previous_failure_reason"], "counter provider unavailable")
        self.assertEqual(before["queue"], after["queue"])
        self.assertEqual(before["work"]["topics"]["topic"]["research_iterations_completed"], after["work"]["topics"]["topic"]["research_iterations_completed"])
        self.assertEqual(before["work"]["episodes"]["episode"]["attempt_history"], episode["attempt_history"])
        self.assertEqual(before["work"]["episodes"]["episode"]["remaining_budgets"], episode["remaining_budgets"])
        self.assertEqual(self._dispatch(payload), result)
        self.assertEqual(self.control.snapshot(), after)
        with self.assertRaises(AccessError):
            self._dispatch(payload | {"reason": "different"})

    def test_retry_rejects_stale_revision_and_active_execution_or_pending_proposal(self):
        with self.assertRaises(AccessError):
            self._dispatch(self._payload(expected_revision=self.control.snapshot()["revision"] + 1))
        with self.control.transaction(actor="fixture") as state:
            state["work"]["assignments"]["1"] = {"current": {"topic_id": "topic", "lease_id": "live"}}
        with self.assertRaisesRegex(AccessError, "current execution"):
            self._dispatch(self._payload(request_id="recover-live"))
        with self.control.transaction(actor="fixture") as state:
            state["work"]["assignments"]["1"] = {}
            state["work"]["proposals"]["proposal"] = {"episode_id": "episode", "status": "pending"}
        with self.assertRaisesRegex(AccessError, "unresolved proposals"):
            self._dispatch(self._payload(request_id="recover-proposal"))

    def test_mcp_retry_forwards_only_to_the_controller(self):
        payload = self._payload()
        with patch.dict("os.environ", {"RESEARCH_LOOP_CONTROLLER_SOCKET": "/tmp/controller.sock"}):
            with patch("research_loops.mcp_server.controller_call", return_value={"state": "retry_wait"}) as call:
                self.assertEqual(EngineTools(self.root).retry_checkpoint(payload), {"state": "retry_wait"})
        call.assert_called_once_with("/tmp/controller.sock", "checkpoint.retry", payload)


if __name__ == "__main__":
    unittest.main()
