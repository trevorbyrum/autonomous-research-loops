"""Regression coverage for the optional citation-index.py cross-reference
index (see docs/citations.md). Entirely derived, never authoritative --
nothing in the completion validator depends on this file existing."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CITATION_INDEX = ROOT / "research_loops" / "chassis" / "citation-index.py"
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(CITATION_INDEX), *args],
        capture_output=True,
        text=True,
    )


class CitationIndexTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topics_root = Path(self._tmp.name) / "topics"
        self.topics_root.mkdir()
        self.output = Path(self._tmp.name) / "index.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _copy_topic(self, name: str) -> Path:
        dest = self.topics_root / name
        shutil.copytree(EXAMPLE_TOPIC, dest)
        return dest

    def test_build_indexes_every_citation_across_topics(self):
        topic_a = self._copy_topic("topic-a")
        topic_b = self._copy_topic("topic-b")
        (topic_a / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n- url: https://a.example\n- title: A\n- retrieved: 2026-08-01\n",
            encoding="utf-8",
        )
        (topic_b / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n- url: https://b.example\n- title: B\n- retrieved: 2026-08-02\n",
            encoding="utf-8",
        )

        result = _run("build", str(self.topics_root), str(self.output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("indexed 2 citation(s)", result.stdout)

        records = [json.loads(line) for line in self.output.read_text().splitlines()]
        self.assertEqual(len(records), 2)
        by_topic = {r["topic_id"]: r for r in records}
        self.assertEqual(by_topic["topic-a"]["url"], "https://a.example")
        self.assertEqual(by_topic["topic-b"]["url"], "https://b.example")

    def test_build_maps_citations_to_the_obligations_that_cite_them(self):
        topic_a = self._copy_topic("topic-a")
        (topic_a / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n- url: https://a.example\n- title: A\n- retrieved: 2026-08-01\n",
            encoding="utf-8",
        )
        state_path = topic_a / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["obligations"][0]["evidence_refs"] = ["SOURCE-LEDGER.md#SRC-001"]
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        expected_obligation_id = state["obligations"][0]["id"]

        _run("build", str(self.topics_root), str(self.output))
        records = [json.loads(line) for line in self.output.read_text().splitlines()]
        self.assertEqual(records[0]["obligation_ids"], [expected_obligation_id])

    def test_query_filters_by_url_title_and_topic(self):
        topic_a = self._copy_topic("topic-a")
        topic_b = self._copy_topic("topic-b")
        (topic_a / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n- url: https://match.example/x\n- title: Findable\n- retrieved: 2026-08-01\n",
            encoding="utf-8",
        )
        (topic_b / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n- url: https://other.example/y\n- title: Different\n- retrieved: 2026-08-02\n",
            encoding="utf-8",
        )
        _run("build", str(self.topics_root), str(self.output))

        by_url = json.loads(_run("query", str(self.output), "--url-contains", "match.example").stdout)
        self.assertEqual(len(by_url), 1)
        self.assertEqual(by_url[0]["topic_id"], "topic-a")

        by_title = json.loads(_run("query", str(self.output), "--title-contains", "Different").stdout)
        self.assertEqual(len(by_title), 1)
        self.assertEqual(by_title[0]["topic_id"], "topic-b")

        by_topic = json.loads(_run("query", str(self.output), "--topic", "topic-b").stdout)
        self.assertEqual(len(by_topic), 1)
        self.assertEqual(by_topic[0]["topic_id"], "topic-b")

    def test_doctor_reports_a_dangling_internal_pointer(self):
        topic_a = self._copy_topic("topic-a")
        self._copy_topic("topic-b")
        (topic_a / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n## [SRC-001] internal\n- topic: topic-b\n- ref: SRC-999\n",
            encoding="utf-8",
        )
        result = _run("doctor", str(self.topics_root))
        self.assertEqual(result.returncode, 1)
        problems = json.loads(result.stdout)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["topic_id"], "topic-a")
        self.assertIn("does not exist", problems[0]["problem"])

    def test_doctor_reports_an_internal_citation_chain(self):
        topic_a = self._copy_topic("topic-a")
        topic_b = self._copy_topic("topic-b")
        (topic_a / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n## [SRC-001] internal\n- topic: topic-b\n- ref: SRC-001\n",
            encoding="utf-8",
        )
        (topic_b / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n## [SRC-001] internal\n- topic: topic-a\n- ref: SRC-001\n",
            encoding="utf-8",
        )
        result = _run("doctor", str(self.topics_root))
        self.assertEqual(result.returncode, 1)
        problems = json.loads(result.stdout)
        self.assertEqual(len(problems), 2)  # both topics point at an internal citation

    def test_doctor_is_clean_when_nothing_is_internal(self):
        topic_a = self._copy_topic("topic-a")
        (topic_a / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n## [SRC-001] external\n- url: https://a.example\n- title: A\n- retrieved: 2026-08-01\n",
            encoding="utf-8",
        )
        result = _run("doctor", str(self.topics_root))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout), [])

    def test_build_over_a_portfolio_with_no_citations_produces_an_empty_index(self):
        self._copy_topic("topic-a")  # example topic's SOURCE-LEDGER.md is a bare stub
        result = _run("build", str(self.topics_root), str(self.output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("indexed 0 citation(s)", result.stdout)
        self.assertEqual(self.output.read_text(), "")


if __name__ == "__main__":
    unittest.main()
