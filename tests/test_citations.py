"""Regression coverage for the typed citation format (see docs/citations.md).

Every evidence_ref an obligation cites on a schema_version >= 2 topic must
resolve to a real, typed [SRC-NNN] citation block -- not just an existing
file (already covered by test_completion_lock.py). schema_version 1 topics
are never retroactively checked against this.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_STATE = ROOT / "research_loops" / "chassis" / "semantic-state.py"
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SEMANTIC_STATE), *args],
        capture_output=True,
        text=True,
    )


def _make_supported(topic_dir: Path, obligation_index: int, evidence_refs: list[str]) -> str:
    """Bring one obligation to `supported` with the given evidence_refs, and
    every other obligation to a valid terminal state so only the one under
    test can produce a citation error. Returns that obligation's id."""
    state_path = topic_dir / "SEMANTIC-STATE.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for index, obligation in enumerate(state["obligations"]):
        obligation["counterevidence_reviewed"] = True
        obligation["acceptance_summary"] = "test"
        obligation["counterevidence_summary"] = "test"
        if index == obligation_index:
            obligation["disposition"] = "supported"
            obligation["confidence"] = "high"
            obligation["evidence_refs"] = evidence_refs
        else:
            obligation["disposition"] = "unresolved"
            obligation["adequate_search"] = {
                "summary": "x",
                "queries": ["x"],
                "source_lanes": ["x"],
                "retrieval_failures": [],
            }
    (topic_dir / "SYNTHESIS.md").write_text("synthesis\n", encoding="utf-8")
    for deliverable in state["deliverables"]:
        deliverable["status"] = "complete"
        deliverable["acceptance_summary"] = "test"
        deliverable["acceptance_evidence_refs"] = [deliverable["path"]]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state["obligations"][obligation_index]["id"]


def _set_schema_version(topic_dir: Path, version: int) -> None:
    state_path = topic_dir / "SEMANTIC-STATE.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["schema_version"] = version
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class CitationValidationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topics_root = Path(self._tmp.name)
        self.topic_dir = self.topics_root / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)
        _set_schema_version(self.topic_dir, 2)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_ledger(self, contents: str) -> None:
        (self.topic_dir / "SOURCE-LEDGER.md").write_text(contents, encoding="utf-8")

    def test_uncited_evidence_is_rejected(self):
        (self.topic_dir / "FINDINGS-LOG.md").write_text(
            "# FINDINGS-LOG.md\n\nA claim with no citation tag.\n", encoding="utf-8"
        )
        obligation_id = _make_supported(self.topic_dir, 0, ["FINDINGS-LOG.md"])
        result = _run("validate", str(self.topic_dir))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"obligation {obligation_id}", result.stderr)
        self.assertIn("uncited", result.stderr)

    def test_direct_external_citation_is_accepted(self):
        self._write_ledger(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n"
            "- url: https://example.com/article\n"
            "- title: An Example Article\n"
            "- retrieved: 2026-08-29\n"
            "- verified: true\n"
        )
        _make_supported(self.topic_dir, 0, ["SOURCE-LEDGER.md#SRC-001"])
        result = _run("validate", str(self.topic_dir))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_indirect_inline_tag_citation_is_accepted(self):
        self._write_ledger(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n"
            "- url: https://example.com/article\n"
            "- title: An Example Article\n"
            "- retrieved: 2026-08-29\n"
            "- verified: true\n"
        )
        (self.topic_dir / "FINDINGS-LOG.md").write_text(
            "# FINDINGS-LOG.md\n\nline2\nA verified claim. [SRC-001]\nline4\n",
            encoding="utf-8",
        )
        # Line 1: '# FINDINGS-LOG.md', 2: blank, 3: 'line2', 4: the tagged claim.
        _make_supported(self.topic_dir, 0, ["FINDINGS-LOG.md:L4-L4"])
        result = _run("validate", str(self.topic_dir))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_local_citation_requires_a_resolvable_path(self):
        self._write_ledger(
            "# SOURCE-LEDGER.md\n\n## [SRC-001] local\n- path: NOWHERE.md\n- verified: true\n"
        )
        _make_supported(self.topic_dir, 0, ["SOURCE-LEDGER.md#SRC-001"])
        result = _run("validate", str(self.topic_dir))
        self.assertNotEqual(result.returncode, 0)
        # Block-scoped error (a block isn't owned by one citing obligation),
        # unlike the resolution-failure messages evidence_citation_errors()
        # itself produces (uncited / not-defined), which do name the obligation.
        self.assertIn("citation SRC-001 (local)", result.stderr)
        self.assertIn("does not resolve", result.stderr)

    def test_local_citation_with_real_path_is_accepted(self):
        (self.topic_dir / "FINDINGS-LOG.md").write_text(
            "# FINDINGS-LOG.md\n\nMeasured result.\n", encoding="utf-8"
        )
        self._write_ledger(
            "# SOURCE-LEDGER.md\n\n## [SRC-001] local\n- path: FINDINGS-LOG.md\n- verified: true\n"
        )
        _make_supported(self.topic_dir, 0, ["SOURCE-LEDGER.md#SRC-001"])
        result = _run("validate", str(self.topic_dir))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unverified_external_citation_is_rejected(self):
        self._write_ledger(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n"
            "- url: https://example.com/article\n"
            "- title: An Example Article\n"
            "- retrieved: 2026-08-29\n"
        )
        _make_supported(self.topic_dir, 0, ["SOURCE-LEDGER.md#SRC-001"])
        result = _run("validate", str(self.topic_dir))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not yet independently verified", result.stderr)

    def test_flagged_hallucination_is_rejected_even_if_marked_verified(self):
        self._write_ledger(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-001] external\n"
            "- url: https://example.com/article\n"
            "- title: An Example Article\n"
            "- retrieved: 2026-08-29\n"
            "- verified: true\n"
            "- flagged: hallucination\n"
        )
        _make_supported(self.topic_dir, 0, ["SOURCE-LEDGER.md#SRC-001"])
        result = _run("validate", str(self.topic_dir))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("flagged as a hallucination", result.stderr)

    def test_external_citation_missing_required_fields_is_rejected(self):
        self._write_ledger("# SOURCE-LEDGER.md\n\n## [SRC-001] external\n- url: not-a-url\n")
        _make_supported(self.topic_dir, 0, ["SOURCE-LEDGER.md#SRC-001"])
        result = _run("validate", str(self.topic_dir))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("external", result.stderr)

    def test_schema_version_1_topic_is_never_checked_for_citations(self):
        _set_schema_version(self.topic_dir, 1)
        (self.topic_dir / "FINDINGS-LOG.md").write_text(
            "# FINDINGS-LOG.md\n\nNo citation at all.\n", encoding="utf-8"
        )
        _make_supported(self.topic_dir, 0, ["FINDINGS-LOG.md"])
        result = _run("validate", str(self.topic_dir))
        self.assertEqual(result.returncode, 0, result.stderr)


class InternalCitationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topics_root = Path(self._tmp.name)
        self.topic_a = self.topics_root / "topic-a"
        self.topic_b = self.topics_root / "topic-b"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_a)
        shutil.copytree(EXAMPLE_TOPIC, self.topic_b)
        _set_schema_version(self.topic_a, 2)
        (self.topic_b / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-007] external\n"
            "- url: https://example.com/already-vetted\n"
            "- title: Already Vetted Source\n"
            "- retrieved: 2026-08-20\n"
            "- verified: true\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _cite_internal(self, ref: str) -> str:
        (self.topic_a / "SOURCE-LEDGER.md").write_text(
            f"# SOURCE-LEDGER.md\n\n## [SRC-002] internal\n- topic: topic-b\n- ref: {ref}\n",
            encoding="utf-8",
        )
        return _make_supported(self.topic_a, 0, ["SOURCE-LEDGER.md#SRC-002"])

    def test_internal_citation_rejected_by_default(self):
        self._cite_internal("SRC-007")
        result = _run("validate", str(self.topic_a), "--topics-root", str(self.topics_root))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not enabled", result.stderr)

    def test_internal_citation_accepted_when_enabled(self):
        self._cite_internal("SRC-007")
        result = _run(
            "validate", str(self.topic_a),
            "--topics-root", str(self.topics_root),
            "--allow-internal-citations",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dangling_internal_pointer_is_rejected(self):
        self._cite_internal("SRC-999")
        result = _run(
            "validate", str(self.topic_a),
            "--topics-root", str(self.topics_root),
            "--allow-internal-citations",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exist", result.stderr)

    def test_internal_pointing_at_internal_is_rejected(self):
        (self.topic_b / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n## [SRC-007] internal\n- topic: topic-a\n- ref: SRC-002\n",
            encoding="utf-8",
        )
        self._cite_internal("SRC-007")
        result = _run(
            "validate", str(self.topic_a),
            "--topics-root", str(self.topics_root),
            "--allow-internal-citations",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must point at external or local", result.stderr)

    def test_default_topics_root_is_topic_dirs_parent(self):
        # Without --topics-root, it must default to topic_dir.resolve().parent --
        # which is exactly self.topics_root here, so internal resolution should
        # still work with no explicit flag.
        self._cite_internal("SRC-007")
        result = _run("validate", str(self.topic_a), "--allow-internal-citations")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_internal_citation_inherits_an_unverified_target(self):
        (self.topic_b / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-007] external\n"
            "- url: https://example.com/not-yet-checked\n"
            "- title: Not Yet Checked\n"
            "- retrieved: 2026-08-20\n",
            encoding="utf-8",
        )
        self._cite_internal("SRC-007")
        result = _run(
            "validate", str(self.topic_a),
            "--topics-root", str(self.topics_root),
            "--allow-internal-citations",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inherits its target's verification status", result.stderr)

    def test_internal_citation_inherits_a_flagged_target(self):
        (self.topic_b / "SOURCE-LEDGER.md").write_text(
            "# SOURCE-LEDGER.md\n\n"
            "## [SRC-007] external\n"
            "- url: https://example.com/hallucinated\n"
            "- title: Hallucinated Source\n"
            "- retrieved: 2026-08-20\n"
            "- verified: true\n"
            "- flagged: hallucination\n",
            encoding="utf-8",
        )
        self._cite_internal("SRC-007")
        result = _run(
            "validate", str(self.topic_a),
            "--topics-root", str(self.topics_root),
            "--allow-internal-citations",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inherits its target's verification status", result.stderr)


class SourceCountTests(unittest.TestCase):
    def test_source_count_is_the_number_of_citation_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "SOURCE-LEDGER.md"
            ledger.write_text(
                "# SOURCE-LEDGER.md\n\n"
                "## [SRC-001] external\n- url: https://a.example\n- title: A\n- retrieved: 2026-08-01\n\n"
                "## [SRC-002] local\n- path: FINDINGS-LOG.md\n\n"
                "## [SRC-003] external\n- url: https://b.example\n- title: B\n- retrieved: 2026-08-02\n",
                encoding="utf-8",
            )
            import importlib.util

            spec = importlib.util.spec_from_file_location("semantic_state", SEMANTIC_STATE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            blocks = module.parse_source_ledger(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(blocks), 3)
            self.assertEqual(set(blocks), {"SRC-001", "SRC-002", "SRC-003"})


if __name__ == "__main__":
    unittest.main()
