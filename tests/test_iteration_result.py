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
        self.assertNotIn("error_class", record)

    def test_rejected_done_records_a_configuration_error_class(self):
        # The example topic is all-open, so a bare STOP DONE fails the
        # chassis validator — and here the chassis KNOWS the class, so the
        # record carries it and the queue never has to prose-scan.
        stub = self._stub_runner(
            'printf "DONE\\n" > "$1/STOP"'
        )
        result = self._run(stub)
        self.assertEqual(result.returncode, 78)
        record = self._latest_result()
        self.assertEqual(record["outcome"], "done_rejected")
        self.assertEqual(record["error_class"], "configuration")
        self.assertTrue(record["stop_written"])


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


class ChassisMeasuredDoneTests(unittest.TestCase):
    """A finished contract must complete even when the loop fumbles the STOP file.

    Documented failure class (2026-09-03): the agent types "STOP DONE" in its
    reply instead of writing the file, then idles until the stall guard parks
    a genuinely finished topic. The chassis now probes the semantic gate each
    iteration and reports semantic_valid; the queue re-validates with its own
    completion authority before acting.
    """

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

    def _writer_command(self, record: dict) -> list[str]:
        script = (
            "import json, pathlib, sys\n"
            f"record = {record!r}\n"
            f"path = pathlib.Path({str(self.cwd / 'logs' / 'latest-result.json')!r})\n"
            "path.write_text(json.dumps(record) + '\\n')\n"
            "sys.exit(0)\n"
        )
        return [sys.executable, "-c", script]

    def _add(self, record, completion):
        self.store.add(
            title="t", cwd=str(self.cwd), command=self._writer_command(record),
            item_id="t", repeat_seconds=0, completion_command=completion,
        )

    def test_semantic_valid_completes_a_recurring_item_without_stop(self):
        self._add({"outcome": "ok", "semantic_valid": True, "stop_written": False},
                  completion=["true"])
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(self.store.get("t")["status"], "completed")

    def test_lock_disagreement_parks_instead_of_completing(self):
        self._add({"outcome": "ok", "semantic_valid": True, "stop_written": False},
                  completion=["false"])
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "needs_attention")
        item = self.store.get("t")
        self.assertEqual(item["last_error_kind"], "configuration")
        self.assertIn("disagrees", item["last_error"])

    def test_without_semantic_valid_the_cadence_continues(self):
        self._add({"outcome": "ok", "semantic_valid": False, "stop_written": False},
                  completion=["true"])
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "scheduled")


class IterationPromptProtocolTests(unittest.TestCase):
    """The DONE declaration is an executable checklist, never buried prose.

    Regression for the 2026-09-03 incident: seven iterations typed "STOP
    DONE" as words because the file write was one prose sentence in a rule
    wall, after 'finish with JSON' had anchored output-production as the
    terminal act.
    """

    def test_prompt_ends_with_an_ordered_protocol_and_literal_commands(self):
        prompt = (
            Path(__file__).resolve().parents[1]
            / "research_loops" / "chassis" / "ITERATION-PROMPT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("END-OF-ITERATION PROTOCOL", prompt)
        self.assertIn("printf 'DONE\\n' > ${TOPIC_DIR}/STOP", prompt)
        self.assertIn("only the file counts", prompt)
        # The protocol is the terminal block: nothing rule-like after step 4.
        self.assertLess(
            prompt.index("Finish your reply with compact JSON"),
            len(prompt),
        )
        self.assertGreater(
            prompt.index("END-OF-ITERATION PROTOCOL"),
            len(prompt) - 1600,
        )
