"""Agents are a worker (station) property, never a queue-item property.

Operator ruling 2026-09-04: the queue is the production line -- it knows what
work exists and in what order. Which harness/model pair processes an item is
the station's configuration; swapping it is one durable change on the worker
and never touches the queue.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import LoopRunner, UsageLedger


class WorkerAgentProfileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_profile_roundtrip_merge_and_clear(self):
        self.assertEqual(self.store.worker_agents("worker-1"), {})
        self.store.configure_worker_agents(
            "worker-1", agent_main="codex", agent_model="gpt-5.6-terra",
            agent_secondary="claude -p --model claude-haiku-4-5-20251001",
        )
        self.store.configure_worker_agents("worker-1", agent_flags="--dangerously-bypass-approvals-and-sandbox")
        profile = self.store.worker_agents("worker-1")
        self.assertEqual(profile["agent_main"], "codex")
        self.assertEqual(profile["agent_flags"], "--dangerously-bypass-approvals-and-sandbox")
        self.store.configure_worker_agents("worker-1", agent_secondary="")
        self.assertNotIn("agent_secondary", self.store.worker_agents("worker-1"))
        self.store.configure_worker_agents("worker-1", clear=True)
        self.assertEqual(self.store.worker_agents("worker-1"), {})

    def test_profile_requires_a_field_and_rejects_non_strings(self):
        with self.assertRaises(QueueError):
            self.store.configure_worker_agents("worker-1")
        with self.assertRaises(QueueError):
            self.store.configure_worker_agents("worker-1", agent_main=5)  # type: ignore[arg-type]

    def test_legacy_state_without_worker_agents_key_reads_empty(self):
        with self.store._locked() as state:
            state.pop("worker_agents", None)
        self.assertEqual(self.store.worker_agents("worker-1"), {})


class RunnerUsesStationProfileTests(unittest.TestCase):
    """The runner launches iterations with the WORKER's profile; the item's
    legacy agent fields only apply when the worker has no profile at all."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)
        self.cwd = self.root / "item-cwd"
        (self.cwd / "logs").mkdir(parents=True)
        self.capture = self.root / "env.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _env_dump_command(self):
        script = (
            "import json, os, pathlib\n"
            "keys = [k for k in os.environ if k.startswith('RESEARCH_LOOP_')]\n"
            f"pathlib.Path({str(self.capture)!r}).write_text(json.dumps({{k: os.environ[k] for k in keys}}))\n"
        )
        return [sys.executable, "-c", script]

    def _run_and_capture(self):
        self.runner.run_once()
        return json.loads(self.capture.read_text())

    def test_worker_profile_overrides_item_fields(self):
        self.store.add(
            title="t", cwd=str(self.cwd), command=self._env_dump_command(), item_id="t",
            agent_main="claude", agent_secondary="codex exec -m gpt-5.6-luna",
        )
        self.store.configure_worker_agents(
            "worker-1", agent_main="codex", agent_model="gpt-5.6-terra",
            agent_secondary="claude -p --model claude-haiku-4-5-20251001",
            agent_flags="--dangerously-bypass-approvals-and-sandbox",
        )
        env = self._run_and_capture()
        self.assertEqual(env["RESEARCH_LOOP_RUNNER"], "codex")
        self.assertEqual(env["RESEARCH_LOOP_CODEX_MODEL"], "gpt-5.6-terra")
        self.assertEqual(env["RESEARCH_LOOP_CODEX_FLAGS"], "--dangerously-bypass-approvals-and-sandbox")
        self.assertEqual(env["RESEARCH_LOOP_AGENT_SECONDARY"], "claude -p --model claude-haiku-4-5-20251001")

    def test_without_a_profile_item_fields_still_apply(self):
        self.store.add(
            title="t", cwd=str(self.cwd), command=self._env_dump_command(), item_id="t",
            agent_main="hermes", agent_secondary="qwen3.8-27b",
        )
        env = self._run_and_capture()
        self.assertEqual(env["RESEARCH_LOOP_RUNNER"], "hermes")
        self.assertEqual(env["RESEARCH_LOOP_AGENT_SECONDARY"], "qwen3.8-27b")


if __name__ == "__main__":
    unittest.main()
