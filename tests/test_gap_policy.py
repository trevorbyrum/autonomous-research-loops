import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAP_POLICY = ROOT / "research_loops" / "chassis" / "gap-policy.py"
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"
SEMANTIC_STATE = ROOT / "research_loops" / "chassis" / "semantic-state.py"


class GapPolicyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(GAP_POLICY), *args],
            capture_output=True,
            text=True,
        )

    def _status(self, policy="auto", limit=2):
        result = self._run(
            "status", str(self.topic_dir), "--policy", policy, "--limit", str(limit)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_fresh_topic_has_full_budget(self):
        status = self._status(limit=3)
        self.assertEqual(status["auto_promotions_used"], 0)
        self.assertEqual(status["remaining"], 3)
        self.assertTrue(status["auto_promotion_allowed"])

    def test_review_policy_never_allows_auto_promotion(self):
        status = self._status(policy="review", limit=5)
        self.assertFalse(status["auto_promotion_allowed"])
        self.assertEqual(status["remaining"], 0)

    def test_promote_appends_obligation_and_rehashes(self):
        result = self._run(
            "promote",
            str(self.topic_dir),
            "--id",
            "NEW-01",
            "--text",
            "A newly discovered gap.",
            "--source-ref",
            "test",
            "--auto",
            "--limit",
            "2",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        topic_md = (self.topic_dir / "TOPIC.md").read_text(encoding="utf-8")
        self.assertIn("**NEW-01**", topic_md)
        state = json.loads((self.topic_dir / "SEMANTIC-STATE.json").read_text())
        ids = [o["id"] for o in state["obligations"]]
        self.assertIn("NEW-01", ids)
        # semantic-state.py check must still pass -- hashes were kept in sync.
        check = subprocess.run(
            [sys.executable, str(SEMANTIC_STATE), "check", str(self.topic_dir)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        log = (self.topic_dir / "DECISIONS-LOG.md").read_text(encoding="utf-8")
        self.assertIn("AUTO-PROMOTED", log)

    def test_promote_refuses_duplicate_obligation_id(self):
        common = [
            str(self.topic_dir),
            "--id",
            "DUP-01",
            "--text",
            "First.",
            "--source-ref",
            "test",
        ]
        first = self._run("promote", *common)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self._run("promote", *common)
        self.assertNotEqual(second.returncode, 0)

    def test_auto_promotion_refused_once_limit_reached(self):
        for index in range(2):
            result = self._run(
                "promote",
                str(self.topic_dir),
                "--id",
                f"AUTO-0{index}",
                "--text",
                "A gap.",
                "--source-ref",
                "test",
                "--auto",
                "--limit",
                "2",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        blocked = self._run(
            "promote",
            str(self.topic_dir),
            "--id",
            "AUTO-02",
            "--text",
            "One too many.",
            "--source-ref",
            "test",
            "--auto",
            "--limit",
            "2",
        )
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("auto-limit reached", blocked.stderr)
        topic_md = (self.topic_dir / "TOPIC.md").read_text(encoding="utf-8")
        self.assertNotIn("**AUTO-02**", topic_md)

    def test_review_reset_restores_the_budget(self):
        for index in range(2):
            self._run(
                "promote",
                str(self.topic_dir),
                "--id",
                f"BUDGET-0{index}",
                "--text",
                "A gap.",
                "--source-ref",
                "test",
                "--auto",
                "--limit",
                "2",
            )
        used_up = self._status(limit=2)
        self.assertFalse(used_up["auto_promotion_allowed"])

        reset = self._run(
            "review-reset", str(self.topic_dir), "--note", "reviewed both, looked fine"
        )
        self.assertEqual(reset.returncode, 0, reset.stderr)

        restored = self._status(limit=2)
        self.assertEqual(restored["auto_promotions_used"], 0)
        self.assertTrue(restored["auto_promotion_allowed"])

    def test_manual_promote_without_auto_flag_is_tagged_promoted_not_auto(self):
        result = self._run(
            "promote",
            str(self.topic_dir),
            "--id",
            "MANUAL-01",
            "--text",
            "Operator-reviewed gap.",
            "--source-ref",
            "test",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.topic_dir / "DECISIONS-LOG.md").read_text(encoding="utf-8")
        self.assertIn("[operator] PROMOTED", log)
        self.assertNotIn("AUTO-PROMOTED", log)


if __name__ == "__main__":
    unittest.main()
