"""Regression coverage for `research-loops doctor`, the non-mutating,
portfolio-wide health audit."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research_loops import doctor
from research_loops.queue import QueueStore

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


def _lock_for(topic_dir: Path) -> str:
    return subprocess.run(
        [sys.executable, str(ROOT / "research_loops" / "chassis" / "semantic-state.py"),
         "lock", str(topic_dir)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.topics_root = self.root / "topics"
        self.topics_root.mkdir(parents=True)
        self.store = QueueStore(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _copy_topic(self, name: str) -> Path:
        dest = self.topics_root / name
        shutil.copytree(EXAMPLE_TOPIC, dest)
        return dest

    def test_clean_portfolio_is_healthy(self):
        topic_dir = self._copy_topic("good")
        self.store.add(
            title="Good", cwd=str(topic_dir), command=["true"], item_id="good",
            completion_lock=_lock_for(topic_dir),
        )
        report = doctor.run_doctor(self.store.snapshot()["items"], topics_root=self.topics_root)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["unlocked_items"], [])
        self.assertEqual(report["orphaned_topic_dirs"], [])
        self.assertEqual(report["missing_dependencies"], [])
        self.assertIsNone(report["dependency_cycle"])
        self.assertEqual(report["source_counts"]["good"], 0)

    def test_item_without_completion_lock_is_flagged(self):
        topic_dir = self._copy_topic("unlocked")
        self.store.add(title="Unlocked", cwd=str(topic_dir), command=["true"], item_id="unlocked")
        report = doctor.run_doctor(self.store.snapshot()["items"], topics_root=self.topics_root)
        self.assertFalse(report["healthy"])
        self.assertEqual(report["unlocked_items"], ["unlocked"])

    def test_orphaned_topic_directory_is_flagged(self):
        (self.topics_root / "orphan").mkdir()
        report = doctor.run_doctor([], topics_root=self.topics_root)
        self.assertFalse(report["healthy"])
        self.assertEqual(len(report["orphaned_topic_dirs"]), 1)
        self.assertTrue(report["orphaned_topic_dirs"][0].endswith("orphan"))

    def test_missing_dependency_is_flagged(self):
        self.store.add(
            title="Consumer", cwd="/tmp", command=["true"], item_id="consumer",
            depends_on=["ghost"],
        )
        report = doctor.run_doctor(self.store.snapshot()["items"], topics_root=self.topics_root)
        self.assertFalse(report["healthy"])
        self.assertEqual(report["missing_dependencies"], [{"item": "consumer", "missing": "ghost"}])

    def test_dependency_cycle_is_flagged(self):
        self.store.add(title="A", cwd="/tmp", command=["true"], item_id="a", depends_on=["b"])
        self.store.add(title="B", cwd="/tmp", command=["true"], item_id="b", depends_on=["a"])
        report = doctor.run_doctor(self.store.snapshot()["items"], topics_root=self.topics_root)
        self.assertFalse(report["healthy"])
        self.assertIn(report["dependency_cycle"], ("a", "b"))

    def test_structural_error_in_a_topic_is_flagged(self):
        topic_dir = self._copy_topic("broken")
        (topic_dir / "TOPIC.md").write_text("tampered, hash will no longer match\n")
        self.store.add(title="Broken", cwd=str(topic_dir), command=["true"], item_id="broken")
        report = doctor.run_doctor(self.store.snapshot()["items"], topics_root=self.topics_root)
        self.assertFalse(report["healthy"])
        self.assertIn("broken", report["structural_errors"])

    def test_total_sources_cited_sums_across_topics(self):
        topic_a = self._copy_topic("a")
        topic_b = self._copy_topic("b")
        (topic_a / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n## [SRC-001] external\n"
            "- url: https://a.example\n- title: A\n- retrieved: 2026-08-01\n",
            encoding="utf-8",
        )
        (topic_b / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n- url: https://b1.example\n- title: B1\n- retrieved: 2026-08-01\n\n"
            "## [SRC-002] external\n- url: https://b2.example\n- title: B2\n- retrieved: 2026-08-02\n",
            encoding="utf-8",
        )
        self.store.add(title="A", cwd=str(topic_a), command=["true"], item_id="a")
        self.store.add(title="B", cwd=str(topic_b), command=["true"], item_id="b")
        report = doctor.run_doctor(self.store.snapshot()["items"], topics_root=self.topics_root)
        self.assertEqual(report["source_counts"], {"a": 1, "b": 2})
        self.assertEqual(report["total_sources_cited"], 3)

    def test_no_topics_root_skips_orphan_check_but_still_runs_others(self):
        self.store.add(
            title="Consumer", cwd="/tmp", command=["true"], item_id="consumer",
            depends_on=["ghost"],
        )
        report = doctor.run_doctor(self.store.snapshot()["items"], topics_root=None)
        self.assertEqual(report["orphaned_topic_dirs"], [])
        self.assertEqual(report["missing_dependencies"], [{"item": "consumer", "missing": "ghost"}])


if __name__ == "__main__":
    unittest.main()
