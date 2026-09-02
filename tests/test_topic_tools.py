import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_STATE = ROOT / "research_loops" / "chassis" / "semantic-state.py"


def answer_qa(topic_dir: Path) -> None:
    """Record operator answers so the approval QA gate opens.

    Tests that exercise approval mechanics (hashes, locks, idempotency) are
    not QA-gate tests; this is the minimum honest record. The gate itself is
    covered in tests/test_intake.py.
    """
    qa = Path(topic_dir) / "QA-RECORD.md"
    content = qa.read_text(encoding="utf-8")
    for heading, answer in (
        ("## Operator confirmation", "Confirmed: matches my intent."),
        ("## Scope decision", "Adopt the draft obligations as scoped."),
    ):
        if heading in content:
            content = content.replace(heading, heading + "\n\n" + answer, 1)
    qa.write_text(content, encoding="utf-8")
    # Stand-in for the criteria/discovery pass approval also requires.
    (Path(topic_dir) / "SCOPE-PROPOSAL.md").write_text(
        "## Contract criteria findings\n\nall pass\n", encoding="utf-8"
    )


class NewTopicTests(unittest.TestCase):
    def _run(self, action, *args, root=None):
        return subprocess.run(
            [sys.executable, "-m", "research_loops", "--root", str(root or self._root), action, *args],
            capture_output=True,
            text=True,
        )

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self._root = Path(self._tempdir.name) / "root"
        self._root.mkdir()

    def tearDown(self):
        self._tempdir.cleanup()

    def test_new_topic_decomposes_a_brief_into_distinct_obligations(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text(
                "Research X. Cover A; cover B; and cover C without conflating it with D.",
                encoding="utf-8",
            )
            dest = Path(tmp) / "topics"
            result = self._run(
                "new-topic", "my-topic", "--title", "My Topic", "--brief", str(brief), "--dest", str(dest)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            draft = json.loads((dest / "my-topic" / "DRAFT-SEMANTIC-STATE.json").read_text())
            texts = [o["text"] for o in draft["obligations"]]
            self.assertGreaterEqual(len(texts), 3)
            # no leading conjunction should survive the split
            self.assertFalse(any(t.lower().startswith(("and ", "or ", "but ")) for t in texts))
            # every obligation must trace back to the brief, never invented
            for o in draft["obligations"]:
                self.assertEqual(o["source_ref"], "AUTHORITY.md#operator-brief-verbatim")
                self.assertEqual(o["disposition"], "open")

    def test_new_topic_refuses_a_malformed_topic_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text("Research X.", encoding="utf-8")
            result = self._run(
                "new-topic", "Not_A_Valid_ID", "--title", "X", "--brief", str(brief), "--dest", tmp
            )
            self.assertNotEqual(result.returncode, 0)

    def test_approve_topic_recomputes_hashes_from_edited_drafts_not_stale_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text("Cover A; cover B.", encoding="utf-8")
            dest = Path(tmp) / "topics"
            self._run("new-topic", "edit-topic", "--title", "Edit Topic", "--brief", str(brief), "--dest", str(dest))
            topic_dir = dest / "edit-topic"

            # Simulate a human editing the draft after scaffolding, before approval.
            draft_topic = topic_dir / "DRAFT-TOPIC.md"
            draft_topic.write_text(draft_topic.read_text() + "\n<!-- human edit -->\n", encoding="utf-8")

            answer_qa(dest / "edit-topic")
            result = self._run("approve-topic", "edit-topic", "--dest", str(dest))
            self.assertEqual(result.returncode, 0, result.stderr)

            state = json.loads((topic_dir / "SEMANTIC-STATE.json").read_text())
            import hashlib

            actual_hash = hashlib.sha256((topic_dir / "TOPIC.md").read_bytes()).hexdigest()
            self.assertEqual(state["contract_sha256"], actual_hash)
            self.assertFalse((topic_dir / "DRAFT-TOPIC.md").exists())
            self.assertFalse((topic_dir / "DRAFT-AUTHORITY.md").exists())
            self.assertFalse((topic_dir / "DRAFT-SEMANTIC-STATE.json").exists())

    def test_approve_topic_bakes_the_completion_lock_into_the_printed_add_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text("Cover A; cover B.", encoding="utf-8")
            dest = Path(tmp) / "topics"
            self._run("new-topic", "lock-topic", "--title", "Lock Topic", "--brief", str(brief), "--dest", str(dest))
            topic_dir = dest / "lock-topic"

            answer_qa(dest / "lock-topic")
            result = self._run("approve-topic", "lock-topic", "--dest", str(dest))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)

            actual_lock = subprocess.run(
                [sys.executable, str(SEMANTIC_STATE), "lock", str(topic_dir)],
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(payload["lock"], actual_lock)
            self.assertIn("--lock-sha256", payload["suggested_command"])
            self.assertIn(actual_lock, payload["suggested_command"])
            # The lock must appear BEFORE the `--` runner separator -- otherwise
            # it silently becomes an argument to the runner instead.
            self.assertLess(
                payload["suggested_command"].index("--lock-sha256"),
                payload["suggested_command"].index(" -- "),
            )

    def test_approved_topic_passes_the_structural_check_but_not_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text("Cover A; cover B.", encoding="utf-8")
            dest = Path(tmp) / "topics"
            self._run("new-topic", "check-topic", "--title", "Check Topic", "--brief", str(brief), "--dest", str(dest))
            topic_dir = dest / "check-topic"
            answer_qa(dest / "check-topic")
            self._run("approve-topic", "check-topic", "--dest", str(dest))

            check = subprocess.run(
                [sys.executable, str(SEMANTIC_STATE), "check", str(topic_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 0, check.stderr)

            validate = subprocess.run(
                [sys.executable, str(SEMANTIC_STATE), "validate", str(topic_dir)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("open obligation", validate.stderr)

    def test_approve_topic_refuses_to_run_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text("Cover A.", encoding="utf-8")
            dest = Path(tmp) / "topics"
            self._run("new-topic", "twice-topic", "--title", "Twice", "--brief", str(brief), "--dest", str(dest))
            answer_qa(dest / "twice-topic")
            first = self._run("approve-topic", "twice-topic", "--dest", str(dest))
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self._run("approve-topic", "twice-topic", "--dest", str(dest))
            self.assertNotEqual(second.returncode, 0)


if __name__ == "__main__":
    unittest.main()
