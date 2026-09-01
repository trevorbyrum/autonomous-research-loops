"""The chassis→queue structured result record.

The queue used to learn about an iteration by regexing the last 2KB of LLM
transcript — prose standing in for an exit contract, and capability
degradations (a web backend silently rate-capped, a gateway down) lived only
inside agent prose nobody queries. run-topic.sh now writes
logs/result-<stamp>.json (+ the latest-result.json alias) with chassis-level
facts, the queue prefers it, and its degraded_capabilities/progress fields
land in the queue's event ledger.

Also pinned here: the chassis no longer has an opinion about stalls. An
unchanged semantic signature exits 0 with signature_changed=false in the
result record; whether that constitutes a stall is the queue stall guard's
call (stall_limit CONSECUTIVE unchanged runs — see test_stall_guard.py),
because CONTRACT-CORE's evidence discipline makes discovery-only iterations
legitimate.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueStore
from research_loops.runner import FailureKind, LoopRunner, UsageLedger

ROOT = Path(__file__).resolve().parents[1]
RUN_TOPIC = ROOT / "research_loops" / "chassis" / "run-topic.sh"
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


class ChassisResultRecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _stub_runner(self, body: str, exit_code: int = 0) -> Path:
        stub = Path(self._tmp.name) / "stub-runner.sh"
        stub.write_text(
            "#!/usr/bin/env bash\n" + body + f"\nexit {exit_code}\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return stub

    def _run(self, stub: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(RUN_TOPIC), str(self.topic_dir), str(stub)],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )

    def _latest_result(self) -> dict:
        return json.loads(
            (self.topic_dir / "logs" / "latest-result.json").read_text(encoding="utf-8")
        )

    def test_progress_iteration_writes_ok_record(self):
        stub = self._stub_runner(
            'python3 - "$1" <<\'PY\'\n'
            "import json, sys\n"
            'p = f"{sys.argv[1]}/SEMANTIC-STATE.json"\n'
            "s = json.load(open(p))\n"
            's["obligations"][0]["gap_state"] = "progressed"\n'
            'json.dump(s, open(p, "w"), indent=2, sort_keys=True)\n'
            "PY"
        )
        result = self._run(stub)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self._latest_result()
        self.assertEqual(record["outcome"], "ok")
        self.assertEqual(record["exit_code"], 0)
        self.assertTrue(record["signature_changed"])
        self.assertFalse(record["stop_written"])
        self.assertEqual(record["degraded_capabilities"], [])
        stamped = self.topic_dir / "logs" / f"result-{record['stamp']}.json"
        self.assertTrue(stamped.is_file(), "per-stamp result record missing")

    def test_unchanged_signature_exits_zero_not_five(self):
        # The pre-2026-09 chassis exited 5 here, pre-empting the queue's
        # stall_limit and parking contract-compliant discovery iterations.
        stub = self._stub_runner("true")
        result = self._run(stub)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self._latest_result()
        self.assertEqual(record["outcome"], "ok")
        self.assertFalse(record["signature_changed"])

    def test_runner_failure_writes_runner_failed_record(self):
        stub = self._stub_runner("echo boom >&2", exit_code=7)
        result = self._run(stub)
        self.assertEqual(result.returncode, 7)
        record = self._latest_result()
        self.assertEqual(record["outcome"], "runner_failed")
        self.assertEqual(record["exit_code"], 7)


class RunnerResultConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)
        self.cwd = self.root / "item-cwd"
        (self.cwd / "logs").mkdir(parents=True)

    def tearDown(self):
        self.tempdir.cleanup()

    def _writer_command(self, record: dict, exit_code: int = 0) -> list[str]:
        """A child that writes logs/latest-result.json the way the chassis does."""
        script = (
            "import json, pathlib, sys\n"
            f"record = {record!r}\n"
            f"path = pathlib.Path({str(self.cwd / 'logs' / 'latest-result.json')!r})\n"
            "path.write_text(json.dumps(record) + '\\n')\n"
            f"sys.exit({exit_code})\n"
        )
        return [sys.executable, "-c", script]

    def test_fresh_record_lands_in_the_process_event(self):
        record = {
            "outcome": "ok",
            "signature_changed": False,
            "sources_cited": 2,
            "stop_written": False,
            "degraded_capabilities": ["graphrag_call"],
        }
        self.store.add(
            title="t", cwd=str(self.cwd), command=self._writer_command(record), item_id="t"
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")
        finished = [
            e for e in self.ledger.events() if e["type"] == "process_finished"
        ]
        self.assertEqual(len(finished), 1)
        self.assertEqual(
            finished[0]["iteration_result"]["degraded_capabilities"],
            ["graphrag_call"],
        )
        self.assertEqual(finished[0]["iteration_result"]["sources_cited"], 2)

    def test_stale_record_is_never_misattributed(self):
        stale = self.cwd / "logs" / "latest-result.json"
        stale.write_text(json.dumps({"outcome": "ok"}) + "\n", encoding="utf-8")
        self.store.add(
            title="t",
            cwd=str(self.cwd),
            command=[sys.executable, "-c", "print('no record written')"],
            item_id="t",
        )
        self.runner.run_once()
        finished = [
            e for e in self.ledger.events() if e["type"] == "process_finished"
        ]
        self.assertNotIn("iteration_result", finished[0])

    def test_structured_error_class_beats_prose_scanning(self):
        record = {"outcome": "runner_failed", "error_class": "outage"}
        self.store.add(
            title="t",
            cwd=str(self.cwd),
            command=self._writer_command(record, exit_code=9),
            item_id="t",
        )
        self.runner.run_once()
        item = self.store.get("t")
        # Prose scanning of "no matching text" would have said TRANSIENT;
        # the chassis-recorded class wins.
        self.assertEqual(item["last_error_kind"], FailureKind.OUTAGE.value)

    def test_unrecognized_error_class_falls_back_to_prose(self):
        record = {"outcome": "runner_failed", "error_class": "not-a-kind"}
        self.store.add(
            title="t",
            cwd=str(self.cwd),
            command=self._writer_command(record, exit_code=9),
            item_id="t",
        )
        self.runner.run_once()
        item = self.store.get("t")
        self.assertEqual(item["last_error_kind"], FailureKind.TRANSIENT.value)


class DefaultCompletionValidationTests(unittest.TestCase):
    """A research topic's self-declared DONE is validated even with no
    completion_command configured — completion integrity must never depend on
    optional per-item configuration."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "queue"
        self.topic_dir = Path(self.tempdir.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)

    def tearDown(self):
        self.tempdir.cleanup()

    def _add_done_writer(self):
        stop_writer = (
            "from pathlib import Path; "
            f"Path({str(self.topic_dir / 'STOP')!r}).write_text('DONE\\n')"
        )
        self.store.add(
            title="t",
            cwd=str(self.topic_dir),
            command=[sys.executable, "-c", stop_writer],
            item_id="t",
            stop_file=str(self.topic_dir / "STOP"),
        )

    def test_done_with_open_obligations_is_rejected_by_default(self):
        self._add_done_writer()
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "needs_attention")
        item = self.store.get("t")
        self.assertIn("open obligation", item["last_error"])

    def test_generic_items_without_semantic_state_still_complete(self):
        cwd = Path(self.tempdir.name) / "generic"
        cwd.mkdir()
        stop = cwd / "STOP"
        self.store.add(
            title="g",
            cwd=str(cwd),
            command=[
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(stop)!r}).write_text('DONE\\n')",
            ],
            item_id="g",
            stop_file=str(stop),
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")


if __name__ == "__main__":
    unittest.main()
