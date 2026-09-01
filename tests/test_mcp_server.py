"""The MCP tool surface over the engine.

Handlers are plain functions (EngineTools) tested directly — the MCP SDK is
only involved in the tier-gating tests, which verify the one security
property that matters: a read-only server instance must not even REGISTER
the operator tools, so no session attached to it can reach them regardless
of what the model asks for.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from research_loops.mcp_server import (
    _OPERATOR_TOOLS,
    _READ_ONLY_TOOLS,
    EngineTools,
    build_server,
)
from research_loops.queue import QueueError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


class EngineToolsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "topics").mkdir()
        self.tools = EngineTools(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _add_example(self, topic_id="example"):
        topic_dir = self.root / "topics" / topic_id
        shutil.copytree(EXAMPLE_TOPIC, topic_dir)
        self.tools.store.add(
            title="Example",
            cwd=str(topic_dir),
            command=["true"],
            item_id=topic_id,
            repeat_seconds=900,
        )
        return topic_dir

    def test_queue_status_is_compact_and_positional(self):
        self._add_example("a")
        self._add_example("b")
        status = self.tools.queue_status()
        self.assertEqual(status["item_count"], 2)
        self.assertEqual(
            [(i["position"], i["id"]) for i in status["items"]], [(0, "a"), (1, "b")]
        )
        # Compact projection only — no command argv, no full history blobs.
        self.assertNotIn("command", status["items"][0])

    def test_topic_state_summarizes_semantics_and_latest_result(self):
        topic_dir = self._add_example()
        logs = topic_dir / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "latest-result.json").write_text(
            json.dumps({"outcome": "ok", "signature_changed": True}) + "\n"
        )
        state = self.tools.topic_state("example")
        self.assertEqual(state["item"]["id"], "example")
        self.assertIn("open", state["semantic"]["obligations_by_disposition"])
        self.assertEqual(state["latest_iteration"]["outcome"], "ok")

    def test_doctor_and_events_and_usage_run(self):
        self._add_example()
        self.assertIn("healthy", self.tools.doctor())
        self.assertEqual(self.tools.recent_events(), [])
        self.assertIn("summary", self.tools.usage_summary())

    def test_recent_events_filters_and_caps(self):
        for n in range(5):
            self.tools.ledger.append({"type": "auto_resume", "item_id": f"i{n}"})
        self.tools.ledger.append({"type": "stall_guard", "item_id": "i0"})
        self.assertEqual(len(self.tools.recent_events(limit=3)), 3)
        self.assertEqual(
            {e["type"] for e in self.tools.recent_events(event_type="stall_guard")},
            {"stall_guard"},
        )
        self.assertEqual(
            {e["item_id"] for e in self.tools.recent_events(topic_id="i0")},
            {"i0"},
        )

    def test_operator_pause_move_and_agents(self):
        self._add_example("a")
        self._add_example("b")
        self.tools.move_topic("b", 0)
        self.assertEqual(self.tools.queue_status()["items"][0]["id"], "b")
        paused = self.tools.pause_topic("a", "hold", graceful=False)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(self.tools.resume_topic("a")["status"], "queued")
        updated = self.tools.set_agents("a", agent_main="hermes")
        self.assertEqual(updated["agent_main"], "hermes")
        with self.assertRaises(QueueError):
            self.tools.set_agents("a")

    def test_relock_repins_from_topic_state(self):
        self._add_example()
        result = self.tools.relock_topic("example")
        self.assertRegex(result["completion_lock"], r"^[0-9a-f]{64}$")

    def test_draft_review_approve_flow(self):
        draft = self.tools.draft_topic(
            "phone-topic",
            title="Phone Topic",
            brief="Research one thing.\n\nResearch another thing.",
        )
        self.assertEqual(draft["obligation_count"], 2)
        self.assertEqual(
            [o["id"] for o in draft["obligations"]], ["SCOPE-01", "SCOPE-02"]
        )
        review = self.tools.read_draft("phone-topic")
        self.assertIn("SCOPE-01", review["draft_topic_md"])

        # The confirmation gate: minting scope requires repeating the id.
        with self.assertRaises(QueueError):
            self.tools.approve_and_queue("phone-topic", confirm="yes")

        result = self.tools.approve_and_queue(
            "phone-topic", confirm="phone-topic", position=0
        )
        self.assertEqual(result["item"]["id"], "phone-topic")
        status = self.tools.queue_status()
        self.assertEqual(status["items"][0]["id"], "phone-topic")
        item = self.tools.store.get("phone-topic")
        self.assertRegex(item["completion_lock"], r"^[0-9a-f]{64}$")
        self.assertEqual(item["agent_main"], "claude")
        # Approved: the draft is gone, the contract is binding.
        with self.assertRaises(QueueError):
            self.tools.read_draft("phone-topic")

    def test_redrafting_overwrites_the_draft(self):
        self.tools.draft_topic("t", title="T", brief="First idea.")
        second = self.tools.draft_topic("t", title="T", brief="Better.\n\nSplit.")
        self.assertEqual(second["obligation_count"], 2)


class TierGatingTests(unittest.TestCase):
    """A read-only instance must not even register operator tools."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "topics").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _tool_names(self, server) -> set[str]:
        import asyncio
        import inspect

        listed = server.list_tools()
        if inspect.iscoroutine(listed):
            listed = asyncio.run(listed)
        return {t.name for t in listed}

    def test_read_only_instance_registers_only_tier_one(self):
        server = build_server(self.root, operator=False)
        self.assertEqual(self._tool_names(server), set(_READ_ONLY_TOOLS))

    def test_operator_instance_registers_both_tiers(self):
        server = build_server(self.root, operator=True)
        self.assertEqual(
            self._tool_names(server), set(_READ_ONLY_TOOLS) | set(_OPERATOR_TOOLS)
        )


if __name__ == "__main__":
    unittest.main()
