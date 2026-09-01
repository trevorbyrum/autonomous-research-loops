"""run-topic.sh must maintain logs/latest-usage.json -- a stable alias of the
per-stamp usage file, so a queue item's `usage_file` freshness check has one
fixed path to watch across iterations."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_TOPIC = ROOT / "research_loops" / "chassis" / "run-topic.sh"
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


class LatestUsageAliasTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)

        # A stub runner that records usage and makes qualifying semantic
        # progress (changes an obligation disposition so the progress
        # signature moves and the stall guard doesn't fire).
        self.stub_runner = Path(self._tmp.name) / "stub-runner.sh"
        self.stub_runner.write_text(
            "#!/usr/bin/env bash\n"
            'topic_dir="$1"\n'
            'echo \'{"provider":"test","total_tokens":42}\' > "$RESEARCH_LOOP_USAGE_FILE"\n'
            "python3 - \"$topic_dir\" <<'PY'\n"
            "import json, sys\n"
            'p = f"{sys.argv[1]}/SEMANTIC-STATE.json"\n'
            "s = json.load(open(p))\n"
            's["obligations"][0]["gap_state"] = "progressed-by-stub"\n'
            'json.dump(s, open(p, "w"), indent=2, sort_keys=True)\n'
            "PY\n"
            "exit 0\n",
            encoding="utf-8",
        )
        self.stub_runner.chmod(0o755)

    def tearDown(self):
        self._tmp.cleanup()

    def test_successful_iteration_updates_latest_usage_alias(self):
        result = subprocess.run(
            [str(RUN_TOPIC), str(self.topic_dir), str(self.stub_runner)],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = self.topic_dir / "logs" / "latest-usage.json"
        self.assertTrue(latest.is_file(), "latest-usage.json alias missing")
        payload = json.loads(latest.read_text(encoding="utf-8"))
        self.assertEqual(payload["total_tokens"], 42)


if __name__ == "__main__":
    unittest.main()
