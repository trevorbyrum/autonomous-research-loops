"""End-to-end MCP protocol tests: every tool called through the wire.

test_mcp_server.py exercises the handlers in-process; this module spawns the
real server binary over stdio and drives it with the SDK's own client, so
schema generation, argument decoding, and result serialization — the layers
an in-process test never touches — are all on the hook. Every registered
tool gets at least one wire call.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from research_loops.mcp_server import _OPERATOR_TOOLS, _READ_ONLY_TOOLS
from research_loops.queue import QueueStore

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


def _server_params(root: Path, operator: bool) -> StdioServerParameters:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    args = ["-m", "research_loops.mcp_server", "--root", str(root)]
    if operator:
        args.append("--operator")
    return StdioServerParameters(command=sys.executable, args=args, env=env)


class WireTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "topics").mkdir()
        # Pre-seed a completed example topic so refresh_topic has something
        # genuinely refreshable, plus queue state the read tools can see.
        store = QueueStore(self.root)
        completed_dir = self.root / "topics" / "done-topic"
        shutil.copytree(EXAMPLE_TOPIC, completed_dir)
        store.add(
            title="Done topic",
            cwd=str(completed_dir),
            command=["true"],
            item_id="done-topic",
            repeat_seconds=900,
            topic_refresh="weekly",
            topic_refresh_mode="light",
        )
        store.mark_completed("done-topic", exit_code=0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_every_tool_over_the_wire(self):
        async def flow():
            calls_made = set()

            async with stdio_client(_server_params(self.root, operator=True)) as (
                read,
                write,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    listed = {t.name for t in (await session.list_tools()).tools}
                    self.assertEqual(
                        listed, set(_READ_ONLY_TOOLS) | set(_OPERATOR_TOOLS)
                    )

                    async def call(name, arguments=None, *, expect_error=False):
                        result = await session.call_tool(name, arguments or {})
                        text = "".join(
                            c.text for c in result.content if hasattr(c, "text")
                        )
                        if expect_error:
                            self.assertTrue(
                                result.is_error, f"{name}: expected error, got {text[:200]}"
                            )
                        else:
                            self.assertFalse(
                                result.is_error, f"{name} failed over the wire: {text[:400]}"
                            )
                        calls_made.add(name)
                        return text

                    # --- authoring flow (creates the item the rest operate on)
                    draft = await call(
                        "draft_topic",
                        {
                            "topic_id": "wire-topic",
                            "title": "Wire Topic",
                            "brief": "Investigate one thing.\n\nInvestigate another.",
                        },
                    )
                    self.assertIn("SCOPE-01", draft)
                    await call("read_draft", {"topic_id": "wire-topic"})
                    # Intake flow over the wire: queue a discovery pass (lands
                    # on the intake lane) and review the QA record.
                    discovery = await call("start_discovery", {"topic_id": "wire-topic"})
                    self.assertIn("discovery.wire-topic", discovery)
                    review = await call("read_scope_proposal", {"topic_id": "wire-topic"})
                    self.assertIn("## Mode", review)
                    # Refusal path: wrong confirmation must be a tool error.
                    await call(
                        "approve_and_queue",
                        {"topic_id": "wire-topic", "confirm": "nope"},
                        expect_error=True,
                    )
                    # The QA gate refuses even a correct confirm until the
                    # operator answers.
                    await call(
                        "approve_and_queue",
                        {"topic_id": "wire-topic", "confirm": "wire-topic"},
                        expect_error=True,
                    )
                    await call(
                        "record_qa",
                        {"topic_id": "wire-topic", "heading": "Operator confirmation",
                         "text": "Confirmed: matches my intent."},
                    )
                    await call(
                        "record_qa",
                        {"topic_id": "wire-topic", "heading": "Scope decision",
                         "text": "Adopt the draft obligations as scoped."},
                    )
                    # Stand-in for the criteria/discovery pass the intake
                    # worker would have written (queued above but no worker
                    # runs in this test).
                    (self.root / "topics" / "wire-topic" / "SCOPE-PROPOSAL.md").write_text(
                        "## Contract criteria findings\n\nall pass\n", encoding="utf-8"
                    )
                    approved = await call(
                        "approve_and_queue",
                        {"topic_id": "wire-topic", "confirm": "wire-topic", "position": 0},
                    )
                    self.assertIn("wire-topic", approved)

                    # --- read-only tier
                    status = await call("queue_status")
                    self.assertIn("wire-topic", status)
                    self.assertIn("done-topic", status)
                    state = await call("topic_state", {"topic_id": "wire-topic"})
                    self.assertIn("obligations_by_disposition", state)
                    await call("doctor")
                    await call("recent_events", {"limit": 10})
                    await call("usage_summary")

                    # --- scheduling controls
                    await call("move_topic", {"topic_id": "wire-topic", "position": 1})
                    await call(
                        "pause_topic",
                        {"topic_id": "wire-topic", "reason": "wire test", "graceful": False},
                    )
                    await call("resume_topic", {"topic_id": "wire-topic"})
                    await call("restart_topic", {"topic_id": "wire-topic"})
                    await call(
                        "swap_active", {"worker": "worker-1", "topic_id": "wire-topic"}
                    )
                    # Per-item agents are deprecated (station property now):
                    # a tool error on the wire, never a silent no-op.
                    await call(
                        "set_agents", {"topic_id": "wire-topic", "agent_main": "hermes"},
                        expect_error=True,
                    )
                    agents = await call(
                        "set_worker_agents", {"worker": "worker-1", "agent_main": "hermes"}
                    )
                    self.assertIn("hermes", agents)
                    await call("relock_topic", {"topic_id": "wire-topic"})
                    await call(
                        "refresh_topic", {"topic_id": "done-topic", "mode": "light"}
                    )
                    await call("pause_all", {"reason": "wire test", "graceful": False})
                    await call("resume_all")

            self.assertEqual(
                calls_made,
                set(_READ_ONLY_TOOLS) | set(_OPERATOR_TOOLS),
                "every registered tool must be exercised through the wire",
            )

        asyncio.run(asyncio.wait_for(flow(), timeout=120))

    def test_read_only_instance_refuses_operator_calls_on_the_wire(self):
        async def flow():
            async with stdio_client(_server_params(self.root, operator=False)) as (
                read,
                write,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = {t.name for t in (await session.list_tools()).tools}
                    self.assertEqual(listed, set(_READ_ONLY_TOOLS))
                    result = await session.call_tool(
                        "pause_all", {"reason": "should not work"}
                    )
                    self.assertTrue(result.is_error)
                    # And the queue must be untouched.
                    state = json.loads(
                        (self.root / "state" / "queue.json").read_text()
                    )
                    self.assertFalse(state.get("paused"))

        asyncio.run(asyncio.wait_for(flow(), timeout=60))


if __name__ == "__main__":
    unittest.main()
