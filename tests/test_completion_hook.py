"""The on_completed_command hook: mechanical post-completion ingestion.

Operator ruling 2026-09-04: derived stores (the GraphRAG corpus) are fed by
one mechanical backfill when a topic lands completed -- never by the research
agent writing per-source mid-loop, and never by hand after the fact. The
queue owns the trigger; the configured command owns the destination. A hook
failure is ledgered but can never un-complete the research itself.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import LoopRunner, UsageLedger


class CompletionHookTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)
        self.cwd = self.root / "topic"
        (self.cwd / "logs").mkdir(parents=True)
        self.marker = self.cwd / "hook-ran.json"

    def tearDown(self):
        self.tempdir.cleanup()

    def _hook(self, exit_code=0):
        script = (
            "import json, os, pathlib, sys\n"
            f"pathlib.Path({str(self.marker)!r}).write_text(json.dumps({{\n"
            "    'topic_dir': os.environ.get('RESEARCH_LOOP_TOPIC_DIR'),\n"
            "    'item_id': os.environ.get('RESEARCH_LOOP_ITEM_ID'),\n"
            "}))\n"
            f"sys.exit({exit_code})\n"
        )
        return [sys.executable, "-c", script]

    def _add(self, *, hook, repeat_seconds=None, command=None):
        self.store.add(
            title="t", cwd=str(self.cwd), command=command or ["true"],
            item_id="t", repeat_seconds=repeat_seconds,
            on_completed_command=hook,
        )

    def _events(self, kind):
        path = self.root / "state" / "events.jsonl"
        return [
            e for e in (json.loads(l) for l in path.read_text().splitlines() if l)
            if e.get("type") == kind
        ]

    def test_hook_runs_once_on_completion_with_topic_env(self):
        self._add(hook=self._hook())
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")
        recorded = json.loads(self.marker.read_text())
        self.assertEqual(recorded["topic_dir"], str(self.cwd))
        self.assertEqual(recorded["item_id"], "t")
        events = self._events("completion_hook")
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["ok"])
        self.assertEqual(events[0]["exit_code"], 0)

    def test_hook_failure_is_ledgered_but_never_uncompletes(self):
        self._add(hook=self._hook(exit_code=3))
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(self.store.get("t")["status"], "completed")
        event = self._events("completion_hook")[0]
        self.assertFalse(event["ok"])
        self.assertEqual(event["exit_code"], 3)

    def test_no_hook_configured_means_no_event(self):
        self._add(hook=None)
        self.assertEqual(self.runner.run_once()["outcome"], "completed")
        self.assertEqual(self._events("completion_hook"), [])

    def test_hook_does_not_run_on_a_rescheduled_iteration(self):
        (self.cwd / "SEMANTIC-STATE.json").write_text("{}", encoding="utf-8")
        record = {"outcome": "ok", "semantic_valid": False, "stop_written": False}
        writer = [sys.executable, "-c", (
            "import json, pathlib\n"
            f"pathlib.Path({str(self.cwd / 'logs' / 'latest-result.json')!r})"
            f".write_text(json.dumps({record!r}))\n"
        )]
        self._add(hook=self._hook(), repeat_seconds=0, command=writer)
        self.assertEqual(self.runner.run_once()["outcome"], "scheduled")
        self.assertFalse(self.marker.exists())
        self.assertEqual(self._events("completion_hook"), [])

    def test_saturation_completion_fires_the_hook(self):
        # The measured completion path (the only one research topics have
        # left) must feed the hook exactly like a bounded completion.
        (self.cwd / "SEMANTIC-STATE.json").write_text("{}", encoding="utf-8")
        record = {"outcome": "ok", "semantic_valid": True,
                  "signature_changed": False, "stop_written": False}
        writer = [sys.executable, "-c", (
            "import json, pathlib\n"
            f"pathlib.Path({str(self.cwd / 'logs' / 'latest-result.json')!r})"
            f".write_text(json.dumps({record!r}))\n"
        )]
        self.store.add(
            title="t", cwd=str(self.cwd), command=writer, item_id="t",
            repeat_seconds=0, completion_command=["true"],
            on_completed_command=self._hook(),
        )
        for _ in range(LoopRunner.DEFAULT_SATURATION_LIMIT - 1):
            self.assertEqual(self.runner.run_once()["outcome"], "scheduled")
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.runner.run_once()["outcome"], "completed")
        self.assertTrue(self.marker.exists())
        self.assertEqual(len(self._events("completion_hook")), 1)

    def test_malformed_hook_command_is_refused_by_configure_topic(self):
        # add() historically skips _definition_from (same as progress_command);
        # the validated paths are sync() and configure_topic(), and
        # configure_topic is how the fleet actually gets this field set.
        self._add(hook=None)
        with self.assertRaises(QueueError):
            self.store.configure_topic("t", on_completed_command=["", "  "])

    def test_configure_topic_can_set_the_hook_on_an_existing_item(self):
        self._add(hook=None)
        self.store.configure_topic("t", on_completed_command=["/bin/true"])
        self.assertEqual(self.store.get("t")["on_completed_command"], ["/bin/true"])
