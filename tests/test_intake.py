"""The intake pipeline: QA-gated topic authoring with parallel discovery.

Pins the operator-designed properties: broad mode is the default and
surfaces assumptions; scoped mode fixes the operator's frame; approval is
structurally impossible without the operator's recorded ruling; discovery
runs on its own lane so it never competes with research workers; and the
intake lane serializes (cap 1 by default, a general config knob) — a pile
of broad-mode drafts must queue their discovery passes, never fan out.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research_loops import topic_authoring
from research_loops.queue import QueueError, QueueStore

ROOT = Path(__file__).resolve().parents[1]
RUN_DISCOVERY = ROOT / "research_loops" / "chassis" / "run-discovery.sh"


class QaModesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self._tmp.name) / "topics"

    def tearDown(self):
        self._tmp.cleanup()

    def _draft(self, topic_id, mode):
        return topic_authoring.new_topic(
            topic_id, title="T", brief_text="Research one thing.\n\nAnother thing.",
            dest=self.dest, mode=mode,
        )

    def _answer(self, topic_id, *headings_and_answers):
        qa = self.dest / topic_id / "QA-RECORD.md"
        content = qa.read_text(encoding="utf-8")
        for heading, answer in headings_and_answers:
            self.assertIn(heading, content)
            content = content.replace(heading, heading + "\n\n" + answer, 1)
        qa.write_text(content, encoding="utf-8")

    def test_broad_is_default_and_requires_scope_decision(self):
        result = self._draft("b-topic", "broad")
        self.assertEqual(result["mode"], "broad")
        qa = (self.dest / "b-topic" / "QA-RECORD.md").read_text()
        self.assertIn("## Scope decision", qa)
        # Confirmation alone is not enough in broad mode.
        self._answer("b-topic", ("## Operator confirmation", "Confirmed."))
        with self.assertRaises(QueueError) as ctx:
            topic_authoring.approve_topic("b-topic", dest=self.dest)
        self.assertIn("Scope decision", str(ctx.exception))
        self._answer("b-topic", ("## Scope decision", "Adopt as drafted."))
        approved = topic_authoring.approve_topic("b-topic", dest=self.dest)
        self.assertIn("lock", approved)

    def test_scoped_mode_needs_no_scope_decision(self):
        self._draft("s-topic", "scoped")
        qa = (self.dest / "s-topic" / "QA-RECORD.md").read_text()
        self.assertNotIn("## Scope decision", qa)
        with self.assertRaises(QueueError):
            topic_authoring.approve_topic("s-topic", dest=self.dest)
        self._answer("s-topic", ("## Operator confirmation", "Confirmed."))
        approved = topic_authoring.approve_topic("s-topic", dest=self.dest)
        self.assertIn("lock", approved)

    def test_authority_carries_the_assumptions_section(self):
        self._draft("a-topic", "broad")
        authority = (self.dest / "a-topic" / "DRAFT-AUTHORITY.md").read_text()
        self.assertIn("## Assumptions", authority)
        self.assertIn("Operator-fixed", authority)
        self.assertIn("Surfaced and answered", authority)


class LaneTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _add(self, item_id, lane):
        self.store.add(
            title=item_id, cwd=self._tmp.name, command=["true"],
            item_id=item_id, lane=lane,
        )

    def test_workers_only_see_their_lanes(self):
        self._add("research-1", "research")
        self._add("intake-1", "intake")
        research_claim = self.store.claim_next(worker="w-research")
        self.assertEqual(research_claim["id"], "research-1")
        intake_claim = self.store.claim_next(worker="w-intake", lanes=("intake",))
        self.assertEqual(intake_claim["id"], "intake-1")

    def test_intake_lane_serializes_by_default(self):
        self._add("intake-1", "intake")
        self._add("intake-2", "intake")
        first = self.store.claim_next(worker="w-a", lanes=("intake",))
        self.assertEqual(first["id"], "intake-1")
        # One discovery pass running: a second intake worker gets NOTHING,
        # regardless of queue depth — the cap is in the store, not the worker.
        self.assertIsNone(self.store.claim_next(worker="w-b", lanes=("intake",)))
        # Raising the cap (the config knob) unlocks parallel discovery.
        self.store.set_lane_limit("intake", 2)
        second = self.store.claim_next(worker="w-b", lanes=("intake",))
        self.assertEqual(second["id"], "intake-2")

    def test_lane_validation(self):
        with self.assertRaises(QueueError):
            self._add("bad", "nope")
        with self.assertRaises(QueueError):
            self.store.set_lane_limit("intake", 0)


class DiscoveryChassisTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self._tmp.name) / "topics"
        topic_authoring.new_topic(
            "d-topic", title="D", brief_text="Map this space.",
            dest=self.dest, mode="broad",
        )
        self.draft_dir = self.dest / "d-topic"

    def tearDown(self):
        self._tmp.cleanup()

    def _stub(self, body):
        stub = Path(self._tmp.name) / "stub.sh"
        stub.write_text("#!/usr/bin/env bash\n" + body + "\nexit 0\n")
        stub.chmod(0o755)
        return stub

    def test_discovery_requires_a_scope_proposal(self):
        no_output = subprocess.run(
            [str(RUN_DISCOVERY), str(self.draft_dir), str(self._stub("true"))],
            capture_output=True, text=True,
        )
        self.assertEqual(no_output.returncode, 65)
        produced = subprocess.run(
            [str(RUN_DISCOVERY), str(self.draft_dir),
             str(self._stub('echo "## Proposed obligations" > "$1/SCOPE-PROPOSAL.md"'))],
            capture_output=True, text=True,
        )
        self.assertEqual(produced.returncode, 0, produced.stderr)

    def test_discovery_refuses_an_approved_topic(self):
        qa = self.draft_dir / "QA-RECORD.md"
        content = qa.read_text().replace(
            "## Operator confirmation", "## Operator confirmation\n\nConfirmed.", 1
        ).replace("## Scope decision", "## Scope decision\n\nAdopt.", 1)
        qa.write_text(content)
        topic_authoring.approve_topic("d-topic", dest=self.dest)
        result = subprocess.run(
            [str(RUN_DISCOVERY), str(self.draft_dir), "true"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 78)  # drafts only


class DiscoverCliTests(unittest.TestCase):
    def test_discover_queues_on_the_intake_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            dest = root / "topics"
            topic_authoring.new_topic(
                "c-topic", title="C", brief_text="Brief.", dest=dest, mode="broad"
            )
            result = subprocess.run(
                [sys.executable, "-m", "research_loops", "--root", str(root),
                 "discover", "c-topic"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            item = json.loads(result.stdout)
            self.assertEqual(item["lane"], "intake")
            self.assertEqual(item["id"], "discovery.c-topic")
            self.assertIsNone(item["repeat_seconds"])  # bounded: one pass


if __name__ == "__main__":
    unittest.main()


class LaneReclaimTests(unittest.TestCase):
    """Ownership trumps lanes for reclaim; strays get released, not hostaged.

    Regression: the first lane implementation filtered the own-running lookup
    by lane, so an intake worker restarted without --lanes intake abandoned
    its running item forever — and, on the capped intake lane, permanently
    blocked every future intake claim.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_restarted_worker_still_reclaims_running_item_across_lanes(self):
        self.store.add(
            title="d", cwd=self._tmp.name, command=["true"],
            item_id="discovery.x", lane="intake",
        )
        claimed = self.store.claim_next(worker="w", lanes=("intake",))
        self.assertEqual(claimed["id"], "discovery.x")
        # Same worker, restarted with research-only lanes: it must still get
        # its running item back (resumed) so the dead-PID/supervision path runs.
        reclaimed = self.store.claim_next(worker="w", lanes=("research",))
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["id"], "discovery.x")
        self.assertTrue(reclaimed.get("resumed"))

    def test_stray_queued_claim_is_released_to_the_pool(self):
        self.store.add(
            title="d", cwd=self._tmp.name, command=["true"],
            item_id="discovery.y", lane="intake",
        )
        self.store.add(
            title="r", cwd=self._tmp.name, command=["true"],
            item_id="research-1", lane="research",
        )
        # Worker claims the intake item, then it lands back in queued state
        # (simulating a finished cadence cycle would need a runner; emulate
        # the sticky-claim shape directly).
        self.store.claim_next(worker="w", lanes=("intake",))
        with self.store._locked() as state:
            item = self.store._find(state, "discovery.y")
            item["status"] = "queued"
        # Restarted as research-only: the stray intake claim is released and
        # the worker claims research work instead of hostaging the intake item.
        claimed = self.store.claim_next(worker="w", lanes=("research",))
        self.assertEqual(claimed["id"], "research-1")
        self.assertIsNone(self.store.get("discovery.y")["claimed_by"])
        # A proper intake worker can now take it.
        taken = self.store.claim_next(worker="intake-1", lanes=("intake",))
        self.assertEqual(taken["id"], "discovery.y")


class PromptTemplatingTests(unittest.TestCase):
    """sed metacharacters in substituted values must pass through verbatim."""

    def test_agent_note_with_sed_metacharacters_renders_literally(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "topics"
            topic_authoring.new_topic(
                "m-topic", title="M", brief_text="Brief.", dest=dest, mode="broad"
            )
            draft = dest / "m-topic"
            captured = Path(tmp) / "captured-prompt.txt"
            stub = Path(tmp) / "stub.sh"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                f'cp "$2" "{captured}"\n'
                'echo done > "$1/SCOPE-PROPOSAL.md"\n'
                "exit 0\n"
            )
            stub.chmod(0o755)
            import os
            env = os.environ.copy()
            env["RESEARCH_LOOP_AGENT_SECONDARY"] = "codex exec -m luna 2>&1 #priority"
            result = subprocess.run(
                [str(RUN_DISCOVERY), str(draft), str(stub)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            prompt = captured.read_text(encoding="utf-8")
            # The exact operator string, unmangled: no `&` expansion into the
            # matched pattern, no truncation at `#`.
            self.assertIn("codex exec -m luna 2>&1 #priority", prompt)
            self.assertNotIn("${AGENT_NOTE}", prompt)
