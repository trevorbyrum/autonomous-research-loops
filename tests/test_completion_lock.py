"""Regression coverage for the completion-inventory lock.

Without a pinned lock, an agent can pass `validate` on a plausible, well-formed
SEMANTIC-STATE.json that no longer matches what was actually approved: delete
an inconvenient obligation, invent a new one, rename a source_ref, or retarget
a deliverable's path/required_headings -- none of that touches TOPIC.md or
AUTHORITY.md, so the contract/authority hashes alone miss it entirely. The
lock covers exactly that gap (see chassis/semantic-state.py's
inventory_lock/inventory_projection and docs/topic-authoring.md).
"""

import copy
import json
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


def _make_fully_terminal(topic_dir: Path) -> None:
    """Bring every obligation/deliverable to a valid terminal state, changing
    only agent-writable fields -- the baseline a tampering agent would also
    have to reach, so the lock is the only thing left to catch the tamper."""
    state_path = topic_dir / "SEMANTIC-STATE.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for obligation in state["obligations"]:
        obligation["disposition"] = "unresolved"
        obligation["counterevidence_reviewed"] = True
        obligation["acceptance_summary"] = "resolved during test"
        obligation["counterevidence_summary"] = "resolved during test"
        obligation["adequate_search"] = {
            "summary": "x",
            "queries": ["x"],
            "source_lanes": ["x"],
            "retrieval_failures": [],
        }
    (topic_dir / "SYNTHESIS.md").write_text("synthesis\n", encoding="utf-8")
    for deliverable in state["deliverables"]:
        deliverable["status"] = "complete"
        deliverable["acceptance_summary"] = "resolved during test"
        deliverable["acceptance_evidence_refs"] = [deliverable["path"]]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class CompletionLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        self.topic_dir.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)
        _make_fully_terminal(self.topic_dir)
        self.approved_lock = _run("lock", str(self.topic_dir)).stdout.strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_untampered_topic_validates_against_its_own_lock(self):
        result = _run("validate", str(self.topic_dir), "--lock-sha256", self.approved_lock)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deleting_an_obligation_passes_without_a_lock(self):
        # This documents the exact gap the lock exists to close: a plausible,
        # fully-terminal, well-formed state with one obligation silently
        # removed passes `validate` when no lock is pinned.
        state_path = self.topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        del state["obligations"][-1]
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _run("validate", str(self.topic_dir))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deleting_an_obligation_is_rejected_with_the_lock_pinned(self):
        state_path = self.topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        del state["obligations"][-1]
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _run("validate", str(self.topic_dir), "--lock-sha256", self.approved_lock)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lock mismatch", result.stderr)

    def test_inventing_a_new_obligation_is_rejected_with_the_lock_pinned(self):
        state_path = self.topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        invented = copy.deepcopy(state["obligations"][0])
        invented["id"] = "INVENTED-01"
        invented["disposition"] = "unresolved"
        state["obligations"].append(invented)
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _run("validate", str(self.topic_dir), "--lock-sha256", self.approved_lock)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lock mismatch", result.stderr)

    def test_renaming_a_source_ref_is_rejected_with_the_lock_pinned(self):
        state_path = self.topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["obligations"][0]["source_ref"] = "AUTHORITY.md#somewhere-else-entirely"
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _run("validate", str(self.topic_dir), "--lock-sha256", self.approved_lock)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lock mismatch", result.stderr)

    def test_retargeting_a_deliverable_path_is_rejected_with_the_lock_pinned(self):
        state_path = self.topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        (self.topic_dir / "EASIER.md").write_text("trivially satisfied\n", encoding="utf-8")
        state["deliverables"][0]["path"] = "EASIER.md"
        state["deliverables"][0]["acceptance_evidence_refs"] = ["EASIER.md"]
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _run("validate", str(self.topic_dir), "--lock-sha256", self.approved_lock)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lock mismatch", result.stderr)

    def test_retargeting_required_headings_is_rejected_with_the_lock_pinned(self):
        state_path = self.topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["deliverables"][0]["required_headings"] = ["## Anything Already Present"]
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _run("validate", str(self.topic_dir), "--lock-sha256", self.approved_lock)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lock mismatch", result.stderr)


class RunTopicShLockWiringTests(unittest.TestCase):
    """End-to-end: the queue's default path actually threads the lock through
    run-topic.sh, not just semantic-state.py's own CLI in isolation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        import shutil

        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)
        _make_fully_terminal(self.topic_dir)
        self.approved_lock = _run("lock", str(self.topic_dir)).stdout.strip()

        self.tamper_runner = Path(self._tmp.name) / "tamper-runner.sh"
        self.tamper_runner.write_text(
            "#!/usr/bin/env bash\n"
            'topic_dir="$1"\n'
            "python3 - \"$topic_dir\" <<'PY'\n"
            "import json, sys\n"
            'state_path = f"{sys.argv[1]}/SEMANTIC-STATE.json"\n'
            "state = json.load(open(state_path))\n"
            'del state["obligations"][-1]\n'
            'json.dump(state, open(state_path, "w"), indent=2, sort_keys=True)\n'
            "PY\n"
            'echo "DONE tampered" > "$topic_dir/STOP"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        self.tamper_runner.chmod(0o755)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_topic_sh(self, env_extra):
        import os

        env = os.environ.copy()
        env.update(env_extra)
        return subprocess.run(
            [str(ROOT / "research_loops" / "chassis" / "run-topic.sh"), str(self.topic_dir), str(self.tamper_runner)],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_tampering_is_rejected_when_lock_env_var_is_set(self):
        result = self._run_topic_sh({"RESEARCH_LOOP_COMPLETION_LOCK": self.approved_lock})
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertIn("rejected by semantic completion validator", result.stderr)

    def test_tampering_passes_without_the_lock_env_var(self):
        # Documents the gap this feature closes -- without the lock threaded
        # through, run-topic.sh has no way to catch this class of tampering.
        result = self._run_topic_sh({})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
