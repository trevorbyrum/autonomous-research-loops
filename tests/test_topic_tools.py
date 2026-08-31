import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW_TOPIC = ROOT / "tools" / "new-topic"
APPROVE_TOPIC = ROOT / "tools" / "approve-topic"
SEMANTIC_STATE = ROOT / "chassis" / "semantic-state.py"


class NewTopicTests(unittest.TestCase):
    def _run(self, script, *args):
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
        )

    def test_new_topic_decomposes_a_brief_into_distinct_obligations(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text(
                "Research X. Cover A; cover B; and cover C without conflating it with D.",
                encoding="utf-8",
            )
            dest = Path(tmp) / "topics"
            result = self._run(
                NEW_TOPIC, "my-topic", "--title", "My Topic", "--brief", str(brief), "--dest", str(dest)
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
                NEW_TOPIC, "Not_A_Valid_ID", "--title", "X", "--brief", str(brief), "--dest", tmp
            )
            self.assertNotEqual(result.returncode, 0)

    def test_approve_topic_recomputes_hashes_from_edited_drafts_not_stale_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text("Cover A; cover B.", encoding="utf-8")
            dest = Path(tmp) / "topics"
            self._run(NEW_TOPIC, "edit-topic", "--title", "Edit Topic", "--brief", str(brief), "--dest", str(dest))
            topic_dir = dest / "edit-topic"

            # Simulate a human editing the draft after scaffolding, before approval.
            draft_topic = topic_dir / "DRAFT-TOPIC.md"
            draft_topic.write_text(draft_topic.read_text() + "\n<!-- human edit -->\n", encoding="utf-8")

            result = self._run(APPROVE_TOPIC, "edit-topic", "--dest", str(dest))
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
            self._run(NEW_TOPIC, "lock-topic", "--title", "Lock Topic", "--brief", str(brief), "--dest", str(dest))
            topic_dir = dest / "lock-topic"

            result = self._run(APPROVE_TOPIC, "lock-topic", "--dest", str(dest))
            self.assertEqual(result.returncode, 0, result.stderr)

            actual_lock = self._run(SEMANTIC_STATE, "lock", str(topic_dir)).stdout.strip()
            self.assertIn("--lock-sha256", result.stdout)
            self.assertIn(actual_lock, result.stdout)
            # The printed command must appear BEFORE the `--` runner separator --
            # otherwise it silently becomes an argument to the runner instead.
            printed_command_line = next(
                line for line in result.stdout.splitlines() if "research-loops add" in line
            )
            self.assertLess(printed_command_line.index("--lock-sha256"), printed_command_line.index(" -- "))

    def test_approved_topic_passes_the_structural_check_but_not_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text("Cover A; cover B.", encoding="utf-8")
            dest = Path(tmp) / "topics"
            self._run(NEW_TOPIC, "check-topic", "--title", "Check Topic", "--brief", str(brief), "--dest", str(dest))
            topic_dir = dest / "check-topic"
            self._run(APPROVE_TOPIC, "check-topic", "--dest", str(dest))

            check = self._run(SEMANTIC_STATE, "check", str(topic_dir))
            self.assertEqual(check.returncode, 0, check.stderr)

            validate = self._run(SEMANTIC_STATE, "validate", str(topic_dir))
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("open obligation", validate.stderr)

    def test_approve_topic_refuses_to_run_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            brief.write_text("Cover A.", encoding="utf-8")
            dest = Path(tmp) / "topics"
            self._run(NEW_TOPIC, "twice-topic", "--title", "Twice", "--brief", str(brief), "--dest", str(dest))
            first = self._run(APPROVE_TOPIC, "twice-topic", "--dest", str(dest))
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self._run(APPROVE_TOPIC, "twice-topic", "--dest", str(dest))
            self.assertNotEqual(second.returncode, 0)


if __name__ == "__main__":
    unittest.main()
