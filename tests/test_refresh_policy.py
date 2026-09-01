import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFRESH_POLICY = ROOT / "research_loops" / "chassis" / "refresh-policy.py"
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(REFRESH_POLICY), *args],
        capture_output=True,
        text=True,
    )


class RefreshPolicyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)
        self.state_path = self.topic_dir / "SEMANTIC-STATE.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write_state(self, state):
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    def _lock_hash(self):
        return self._state()["contract_sha256"]

    def test_light_appends_exactly_one_obligation_and_rehashes(self):
        before = self._state()
        before_lock = self._lock_hash()
        before_count = len(before["obligations"])

        result = _run("apply", str(self.topic_dir), "light")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary, {
            "mode": "light",
            "obligations_touched": 1,
            "fell_back_to_light": False,
            "stop_removed": False,
        })

        after = self._state()
        self.assertEqual(len(after["obligations"]), before_count + 1)
        new_ob = after["obligations"][-1]
        self.assertEqual(new_ob["disposition"], "open")
        self.assertIn(f"**{new_ob['id']}**", self.topic_dir.joinpath("TOPIC.md").read_text())
        self.assertNotEqual(after["contract_sha256"], before_lock)
        self.assertIn("REFRESH-light-", self.topic_dir.joinpath("DECISIONS-LOG.md").read_text())

    def test_continue_reopens_only_supported_obligations_and_keeps_evidence_refs(self):
        state = self._state()
        obs = state["obligations"]
        obs[0]["disposition"] = "supported"
        obs[0]["confidence"] = "high"
        obs[0]["acceptance_summary"] = "already checked"
        obs[0]["counterevidence_summary"] = "none found"
        obs[0]["counterevidence_reviewed"] = True
        obs[0]["evidence_refs"] = ["SOURCE-LEDGER.md#SRC-001"]
        obs[1]["disposition"] = "unresolved"
        self._write_state(state)

        result = _run("apply", str(self.topic_dir), "continue")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["obligations_touched"], 1)
        self.assertFalse(summary["fell_back_to_light"])

        after = self._state()["obligations"]
        self.assertEqual(after[0]["disposition"], "open")
        self.assertIsNone(after[0]["confidence"])
        self.assertIsNone(after[0]["acceptance_summary"])
        self.assertIsNone(after[0]["counterevidence_summary"])
        self.assertFalse(after[0]["counterevidence_reviewed"])
        # evidence_refs is deliberately left in place, not wiped.
        self.assertEqual(after[0]["evidence_refs"], ["SOURCE-LEDGER.md#SRC-001"])
        # The unresolved obligation is a settled non-finding -- left alone.
        self.assertEqual(after[1]["disposition"], "unresolved")

    def test_continue_falls_back_to_light_when_nothing_is_supported(self):
        state = self._state()
        for ob in state["obligations"]:
            ob["disposition"] = "unresolved"
        self._write_state(state)
        before_count = len(state["obligations"])

        result = _run("apply", str(self.topic_dir), "continue")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["obligations_touched"], 1)
        self.assertTrue(summary["fell_back_to_light"])

        after = self._state()["obligations"]
        self.assertEqual(len(after), before_count + 1)
        self.assertEqual(after[-1]["disposition"], "open")

    def test_full_reopens_every_obligation_regardless_of_disposition(self):
        state = self._state()
        dispositions = ["supported", "contradicted", "unresolved", "deferred"]
        for i, ob in enumerate(state["obligations"]):
            ob["disposition"] = dispositions[i % len(dispositions)]
        self._write_state(state)
        total = len(state["obligations"])

        result = _run("apply", str(self.topic_dir), "full")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["obligations_touched"], total)
        self.assertFalse(summary["fell_back_to_light"])

        after = self._state()["obligations"]
        self.assertTrue(all(ob["disposition"] == "open" for ob in after))

    def test_unknown_mode_is_rejected(self):
        result = _run("apply", str(self.topic_dir), "bogus")
        self.assertNotEqual(result.returncode, 0)

    def test_apply_fails_cleanly_when_topic_md_is_missing(self):
        (self.topic_dir / "TOPIC.md").unlink()
        result = _run("apply", str(self.topic_dir), "light")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())

    def test_every_mode_removes_a_stale_stop_file(self):
        # A completed topic's STOP DONE would make run-topic.sh exit 3 on the
        # very next iteration -- reopening must clear it. Fresh topic copy per
        # mode: light-style obligation ids are second-resolution timestamps,
        # so repeated applies against one dir could collide.
        for mode in ("light", "continue", "full"):
            with self.subTest(mode=mode):
                topic_dir = Path(self._tmp.name) / f"topic-{mode}"
                shutil.copytree(EXAMPLE_TOPIC, topic_dir)
                stop = topic_dir / "STOP"
                stop.write_text("DONE\n\nvalidated earlier\n", encoding="utf-8")
                result = _run("apply", str(topic_dir), mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                summary = json.loads(result.stdout)
                self.assertTrue(summary["stop_removed"])
                self.assertFalse(stop.exists())

    def test_apply_without_a_stop_file_reports_stop_removed_false(self):
        result = _run("apply", str(self.topic_dir), "full")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["stop_removed"])


if __name__ == "__main__":
    unittest.main()
