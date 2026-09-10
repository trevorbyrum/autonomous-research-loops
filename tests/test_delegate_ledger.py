"""Managed delegate observability: launch/usage ledger lines and the
silent-empty-response guard (2026-09-09 hardening — the managed shim
previously wrote no ledger events at all, so the throughput report claimed
"zero delegation, complete coverage" for every managed iteration)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "research_loops" / "chassis" / "managed-delegate.py"

STUB_OK = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
assert args[0] == 'exec', args
out = args[args.index('-o') + 1]
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10, "reasoning_output_tokens": 5}}))
open(out, 'w').write('delegate answer')
"""

STUB_EMPTY = """#!/usr/bin/env python3
import sys
# Exit 0 with no event stream and no final message: the silent-failure class.
"""


class DelegateLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.topic = Path(self.temp.name) / "topic"
        (self.topic / "logs").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, stub_source: str, role: str = "secondary"):
        stub = Path(self.temp.name) / "fake-codex"
        stub.write_text(stub_source)
        stub.chmod(0o755)
        profile = {"id": "luna", "adapter": "codex", "model": "fake-luna",
                   "executable": str(stub), "argv": []}
        env = {**os.environ,
               f"RESEARCH_LOOP_MANAGED_{role.upper()}_PROFILE": json.dumps(profile)}
        return subprocess.run([sys.executable, str(SHIM), role, str(self.topic), "do the legwork"],
                              env=env, capture_output=True, text=True, timeout=60)

    def _ledger(self):
        path = self.topic / "logs" / "delegate-usage.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def test_successful_call_writes_launch_and_usage_lines(self):
        result = self._run(STUB_OK)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("delegate answer", result.stdout)
        events = self._ledger()
        launches = [e for e in events if e.get("event") == "launch"]
        usage = [e for e in events if "event" not in e]
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0]["model"], "fake-luna")
        self.assertEqual(len(usage), 1, events)
        # codex.sh's total excludes cached input (billed at ~a tenth); the
        # split detail is preserved alongside it.
        self.assertEqual(usage[0]["total_tokens"], 115)
        self.assertEqual(usage[0]["input_tokens"], 100)
        self.assertEqual(usage[0]["cached_input_tokens"], 40)

    def test_empty_response_becomes_exit_70_with_stderr_surface(self):
        result = self._run(STUB_EMPTY)
        self.assertEqual(result.returncode, 70, (result.stdout, result.stderr))
        self.assertIn("failed rc=0", result.stderr)
        events = self._ledger()
        self.assertEqual([e.get("event") for e in events], ["launch"])  # unobserved outcome

    def test_missing_profile_is_a_configuration_error_not_a_json_error(self):
        result = subprocess.run([sys.executable, str(SHIM), "secondary", str(self.topic), "task"],
                                env={**os.environ}, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not configured", result.stderr)

    def test_throughput_report_reader_sees_the_delegation(self):
        self._run(STUB_OK)
        from research_loops.throughput_report import UNKNOWN, _delegate_tokens  # type: ignore[attr-defined]
        # Marker-window shape: an iteration marker before the events, as the
        # chassis writes at loop start.
        path = self.topic / "logs" / "delegate-usage.jsonl"
        events = path.read_text()
        path.write_text('{"ts":"2026-09-10T00:00:00Z","event":"iteration","stamp":"20260910T000000Z"}\n' + events)
        from datetime import datetime, timezone
        start = datetime(2026, 9, 10, tzinfo=timezone.utc)
        total, unobserved, coverage = _delegate_tokens(self.topic, "20260910T000000Z", start, None)
        self.assertEqual(total, 115)
        self.assertEqual(unobserved, 0)
        self.assertEqual(coverage, "complete")


if __name__ == "__main__":
    unittest.main()
